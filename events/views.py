import io
import uuid
from decimal import Decimal, InvalidOperation

import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from giving.flutterwave import FlutterwaveError, initiate_payment, verify_payment
from giving.payments import payment_matches
from churchapp.validation import optional_id
from members.models import Campus

from .forms import EventRegistrationForm, QrCheckinForm, RSVPForm, VolunteerSignupForm
from .models import RSVP, Event, EventRegistration, EventTicket
from .notifications import send_registration_confirmation, send_rsvp_confirmation, send_volunteer_signup_confirmation
from .services import (
    SlotFullError,
    TicketFullError,
    cancel_volunteer_signup,
    check_in_via_qr,
    conflicting_commitments_on,
    join_waitlist,
    register_for_ticket,
    sign_up_for_slot,
)


def upcoming_events(request):
    events_qs = Event.objects.select_related("campus").filter(start_datetime__gte=timezone.now()).order_by(
        "start_datetime"
    )

    query = request.GET.get("q", "").strip()
    if query:
        events_qs = events_qs.filter(Q(title__icontains=query) | Q(location__icontains=query))

    event_type = request.GET.get("type", "")
    if event_type in dict(Event.EventType.choices):
        events_qs = events_qs.filter(event_type=event_type)
    else:
        event_type = ""

    # Same threshold as everywhere else campus fields/filters appear - see
    # the Campus model's docstring in members/models.py.
    show_campus_filter = Campus.objects.count() > 1
    campus_id = request.GET.get("campus", "") if show_campus_filter else ""
    if campus_id:
        events_qs = events_qs.filter(campus_id=optional_id(campus_id))

    page_obj = Paginator(events_qs, 10).get_page(request.GET.get("page"))
    return render(
        request,
        "events/upcoming_events.html",
        {
            "page_obj": page_obj,
            "query": query,
            "event_type": event_type,
            "event_types": Event.EventType.choices,
            "campus_id": campus_id,
            "campuses": Campus.objects.all() if show_campus_filter else None,
        },
    )


def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    slots = event.volunteer_slots.all()
    tickets = event.tickets.all()

    member = getattr(request.user, "member_profile", None)
    can_register = member is not None and member.is_active
    rsvp_form = RSVPForm(event=event, member=member)
    volunteer_form = VolunteerSignupForm(event=event, member=member)
    registration_form = EventRegistrationForm(event=event, member=member)

    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect_to_login(request.path)
        if not can_register:
            messages.error(request, "An active member profile is needed to sign up. Please contact the church office.")
            return redirect("event_detail", event_id=event.id)
        form_type = request.POST.get("form_type")

        if form_type == "rsvp":
            rsvp_form = RSVPForm(request.POST, event=event, member=member)
            if rsvp_form.is_valid():
                member = rsvp_form.cleaned_data["member"]
                status = rsvp_form.cleaned_data["status"]
                service_time = rsvp_form.cleaned_data.get("service_time")
                rsvp, _ = RSVP.objects.update_or_create(
                    event=event, member=member, defaults={"status": status, "service_time": service_time}
                )
                send_rsvp_confirmation(rsvp)
                messages.success(request, f"RSVP saved: {member} — {rsvp.get_status_display()}.")
                return redirect("event_detail", event_id=event.id)

        elif form_type == "volunteer":
            volunteer_form = VolunteerSignupForm(request.POST, event=event, member=member)
            if volunteer_form.is_valid():
                member = volunteer_form.cleaned_data["member"]
                slot = volunteer_form.cleaned_data["slot"]
                try:
                    signup, created = sign_up_for_slot(slot_id=slot.pk, member=member)
                except SlotFullError:
                    _, joined = join_waitlist(slot_id=slot.pk, member=member)
                    if joined:
                        messages.info(
                            request,
                            f"Sorry, {slot.role_needed} just filled up - {member} has been added to the "
                            "waitlist and will be notified automatically if a spot opens up.",
                        )
                    else:
                        messages.info(request, f"{member} is already on the waitlist for {slot.role_needed}.")
                else:
                    if created:
                        send_volunteer_signup_confirmation(signup)
                        messages.success(request, f"{member} signed up for {slot.role_needed}.")
                        for conflict in conflicting_commitments_on(
                            member, event.start_datetime.date(), exclude_event_id=event.id
                        ):
                            messages.warning(request, conflict)
                    else:
                        messages.info(request, f"{member} is already signed up for that slot.")
                return redirect("event_detail", event_id=event.id)

        elif form_type == "register":
            registration_form = EventRegistrationForm(request.POST, event=event, member=member)
            if registration_form.is_valid():
                member = registration_form.cleaned_data["member"]
                ticket = registration_form.cleaned_data["ticket"]
                try:
                    registration, created = register_for_ticket(ticket_id=ticket.pk, member=member)
                except TicketFullError:
                    messages.error(request, "Sorry, that ticket type just sold out.")
                    return redirect("event_detail", event_id=event.id)

                if not created and registration.status != EventRegistration.Status.PENDING:
                    messages.info(request, f"{member} is already registered for {ticket}.")
                    return redirect("event_detail", event_id=event.id)

                return _start_registration_payment(request, registration)

    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "slots": slots,
            "tickets": tickets,
            "rsvp_form": rsvp_form,
            "volunteer_form": volunteer_form,
            "registration_form": registration_form,
            "can_register": can_register,
        },
    )


@transaction.atomic
def _start_registration_payment(request, registration):
    """
    Moves a freshly-created (still PENDING) registration to payment, or - if
    it's free or Flutterwave isn't configured yet - straight to COMPLETED,
    same fallback-to-pending-for-staff-follow-up story as giving/views.py's
    give(). Pulled out of event_detail so that view stays focused on
    dispatching between its three forms.
    """
    registration = EventRegistration.objects.select_for_update().get(pk=registration.pk)
    ticket = registration.ticket
    member = registration.member
    payments_enabled = bool(settings.FLUTTERWAVE_SECRET_KEY)
    if registration.status != EventRegistration.Status.PENDING or registration.expires_at <= timezone.now():
        messages.info(request, "Please reserve a spot again to continue.")
        return redirect("event_detail", event_id=ticket.event_id)
    if registration.checkout_url:
        return redirect(registration.checkout_url)

    if not payments_enabled or registration.amount_due == 0:
        registration.status = EventRegistration.Status.COMPLETED
        registration.save(update_fields=["status"])
        send_registration_confirmation(registration)
        if ticket.price and not payments_enabled:
            messages.info(
                request,
                "Thanks! Online payments aren't turned on yet, so this has been "
                "recorded as a confirmed registration for staff to follow up on payment.",
            )
        else:
            messages.success(request, f"{member} is registered for {ticket}.")
        return redirect("event_detail", event_id=ticket.event_id)

    email = member.email if member and member.email else "anonymous@example.com"
    redirect_url = request.build_absolute_uri(reverse("event_registration_callback"))
    registration.payment_reference = registration.payment_reference or uuid.uuid4().hex
    registration.save(update_fields=["payment_reference"])

    try:
        payment_link = initiate_payment(
            tx_ref=registration.payment_reference,
            amount=registration.amount_due,
            email=email,
            redirect_url=redirect_url,
            name=str(member) if member else "Anonymous",
        )
    except FlutterwaveError as exc:
        registration.status = EventRegistration.Status.FAILED
        registration.save(update_fields=["status"])
        messages.error(request, f"Couldn't start payment: {exc}")
        return redirect("event_detail", event_id=ticket.event_id)

    registration.checkout_url = payment_link
    registration.save(update_fields=["checkout_url"])
    return redirect(payment_link)


def event_registration_callback(request):
    """Flutterwave sends the browser back here after checkout - same verify-then-trust pattern as giving_callback."""
    status = request.GET.get("status")
    tx_ref = request.GET.get("tx_ref")
    transaction_id = request.GET.get("transaction_id")
    if not tx_ref:
        raise Http404("Payment reference required.")

    registration = get_object_or_404(EventRegistration, payment_reference=tx_ref)
    event_id = registration.ticket.event_id
    if registration.status in (EventRegistration.Status.COMPLETED, EventRegistration.Status.REVIEW):
        return redirect("event_detail", event_id=event_id)

    if status != "successful" or not transaction_id:
        # A browser cancellation cannot release a reservation while a payment
        # may still be settling. Unpaid reservations expire automatically.
        messages.error(request, "Payment was not completed.")
        return redirect("event_detail", event_id=event_id)

    try:
        result = verify_payment(transaction_id)
    except FlutterwaveError as exc:
        messages.error(request, f"Couldn't verify that payment: {exc}")
        return redirect("event_detail", event_id=event_id)

    if payment_matches(result, reference=registration.payment_reference, amount=registration.amount_due):
        with transaction.atomic():
            ticket = EventTicket.objects.select_for_update().get(pk=registration.ticket_id)
            registration = EventRegistration.objects.select_for_update().get(pk=registration.pk)
            if registration.status in (EventRegistration.Status.COMPLETED, EventRegistration.Status.REVIEW):
                return redirect("event_detail", event_id=event_id)
            holds_spot = registration.status == EventRegistration.Status.PENDING and registration.expires_at > timezone.now()
            if holds_spot or not ticket.is_full:
                registration.status = EventRegistration.Status.COMPLETED
                registration.save(update_fields=["status"])
                transaction.on_commit(lambda: send_registration_confirmation(registration))
                messages.success(request, "Thank you! Your registration is confirmed.")
            else:
                registration.status = EventRegistration.Status.REVIEW
                registration.save(update_fields=["status"])
                messages.warning(request, "Payment received after your reservation expired. Please contact the church office to arrange a place or refund.")
    else:
        messages.error(request, "We couldn't verify that payment. Please contact the church office.")

    return redirect("event_detail", event_id=event_id)


def event_qr_checkin(request, event_id):
    """
    No-login page a member reaches by scanning the QR code staff display or
    print for a specific event (see the "QR Check-In" card in
    staff/templates/staff/event_detail.html, and event_qr_code below, which
    renders that code). Just a phone number - matched to a member and
    checked in via check_in_via_qr, the same phone-matching approach as
    SMS-based check-in (members/services.py's record_sms_checkin).
    """
    event = get_object_or_404(Event, id=event_id)
    result = None
    member_name = None

    if request.method == "POST":
        form = QrCheckinForm(request.POST, event=event)
        if form.is_valid():
            attendance, error = check_in_via_qr(
                event=event, phone=form.cleaned_data["phone"], service_time=form.cleaned_data.get("service_time")
            )
            if error == "no_matching_member":
                result = "not_found"
            else:
                result = "success"
                member_name = attendance.member.first_name
    else:
        form = QrCheckinForm(event=event)

    return render(
        request,
        "events/qr_checkin.html",
        {
            "event": event,
            "form": form,
            "result": result,
            "member_name": member_name,
        },
    )


def event_kiosk_checkin(request, event_id):
    """
    A stripped-down, large-button version of event_qr_checkin above, meant
    to be opened once on a tablet/kiosk left running at the door and never
    navigated away from - no site header/footer/nav (its own template is a
    standalone page, not extending base.html), just a big phone-number
    input and a big button. After a successful check-in it shows a large
    confirmation for a few seconds and then reloads itself automatically
    (see the template's own auto-refresh) so it's ready for the next person
    without anyone needing to touch the screen in between.

    Deliberately its own view/template rather than a "kiosk=1" flag on
    event_qr_checkin - the two pages want fundamentally different chrome
    (this one drops the whole site frame), and keeping them separate means
    neither view has to branch on how it's being displayed.
    """
    event = get_object_or_404(Event, id=event_id)
    result = None
    member_name = None

    if request.method == "POST":
        form = QrCheckinForm(request.POST, event=event)
        if form.is_valid():
            attendance, error = check_in_via_qr(
                event=event, phone=form.cleaned_data["phone"], service_time=form.cleaned_data.get("service_time")
            )
            if error == "no_matching_member":
                result = "not_found"
            else:
                result = "success"
                member_name = attendance.member.first_name
    else:
        form = QrCheckinForm(event=event)

    return render(
        request,
        "events/kiosk_checkin.html",
        {
            "event": event,
            "form": form,
            "result": result,
            "member_name": member_name,
        },
    )


def event_qr_code(request, event_id):
    """
    Renders a PNG QR code encoding this event's check-in page URL
    (event_qr_checkin above) - generated entirely server-side with the
    qrcode library, no external QR-generation service involved.
    """
    event = get_object_or_404(Event, id=event_id)
    checkin_url = request.build_absolute_uri(reverse("event_qr_checkin", args=[event.id]))

    image = qrcode.make(checkin_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")
