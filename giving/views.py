import json
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from churchapp.sms import send_sms
from churchapp.webhooks import authenticated_sms_webhook
from .payments import payment_matches

from .flutterwave import FlutterwaveError, initiate_payment, verify_payment, webhook_signature_valid
from .forms import PledgeForm, PublicDonationForm, RecurringGivingForm
from .models import Donation, GivingCampaign, Pledge, RecurringGiving
from .notifications import (
    notify_treasurers_of_pending_donation,
    send_donation_receipt_email,
    send_giving_statement_email,
)
from .pdfs import build_giving_statement_pdf
from .services import record_sms_gift


THANK_YOU_SESSION_KEY = "giving_thank_you_refs"


def giving_payments_enabled():
    """Online giving needs both its own switch and the Flutterwave keys (see settings.GIVING_ONLINE_PAYMENTS)."""
    return settings.GIVING_ONLINE_PAYMENTS and bool(settings.FLUTTERWAVE_SECRET_KEY)


def _remember_for_thank_you(request, donation):
    """Let this browser (and only this one) see the thank-you page for its own gift."""
    refs = request.session.get(THANK_YOU_SESSION_KEY, [])[-9:]
    if donation.payment_reference not in refs:
        refs.append(donation.payment_reference)
    request.session[THANK_YOU_SESSION_KEY] = refs


def give(request):
    payments_enabled = giving_payments_enabled()
    member = getattr(request.user, "member_profile", None)

    if request.method == "POST":
        form = PublicDonationForm(
            request.POST, public_member=member, restrict_member=True, require_contact=payments_enabled
        )
        if form.is_valid():
            donation = form.save(commit=False)
            donation.status = Donation.Status.PENDING
            donation.payment_reference = uuid.uuid4().hex
            donation.save()

            if not payments_enabled:
                # Nothing has actually been paid, so stay on the giving page
                # rather than showing a thank-you for money not yet received.
                notify_treasurers_of_pending_donation(donation)
                messages.info(
                    request,
                    f"Your gift of GH₵{donation.amount} has been recorded as pending. Online payment "
                    "is not available yet, so a member of our finance team will contact you to complete it.",
                )
                return redirect("give")

            redirect_url = request.build_absolute_uri(reverse("giving_callback"))
            try:
                payment_link = initiate_payment(
                    tx_ref=donation.payment_reference,
                    amount=donation.amount,
                    email=donation.donor_email,
                    redirect_url=redirect_url,
                    name=donation.donor_name,
                    phone=donation.donor_phone,
                    description=f"{donation.get_donation_type_display()} - thank you for giving",
                    meta={"donation_id": donation.pk},
                )
            except FlutterwaveError:
                donation.status = Donation.Status.FAILED
                donation.save(update_fields=["status"])
                messages.error(
                    request,
                    "We couldn't connect to our payment provider just now. Nothing was charged - "
                    "please try again in a moment.",
                )
                return redirect("give")

            _remember_for_thank_you(request, donation)
            return redirect(payment_link)
    else:
        # Arriving here from a campaign page's "Give to this campaign" link
        # (see campaign_detail.html) pre-selects that campaign in the form.
        initial = {}
        campaign_id = request.GET.get("campaign")
        if campaign_id:
            initial["campaign"] = campaign_id
        if member:
            initial.update(
                member=member.pk,
                donor_name=f"{member.first_name} {member.last_name}".strip(),
                donor_email=member.email or "",
                donor_phone=member.phone or "",
            )
        form = PublicDonationForm(
            initial=initial, public_member=member, restrict_member=True, require_contact=payments_enabled
        )

    return render(
        request,
        "giving/give.html",
        {"form": form, "payments_enabled": payments_enabled, "sms_giving_number": settings.CHURCH_SMS_GIVING_NUMBER},
    )


def _complete_if_verified(donation, transaction_id):
    """
    Re-verify a transaction server-to-server and, only if it matches this
    exact donation (reference, amount, currency), mark it completed and send
    the receipt. Shared by the browser callback and the webhook, so whichever
    arrives first does the work and the other is a harmless no-op.

    Returns "completed", "pending" (e.g. Mobile Money still awaiting approval
    on the giver's phone) or "failed". A FAILED donation can still be
    completed here - if the money really did arrive later, it counts.
    Raises FlutterwaveError if Flutterwave can't be reached.
    """
    result = verify_payment(transaction_id)
    if payment_matches(result, reference=donation.payment_reference, amount=donation.amount):
        changed = (
            Donation.objects.filter(pk=donation.pk)
            .exclude(status=Donation.Status.COMPLETED)
            .update(status=Donation.Status.COMPLETED)
        )
        if changed:
            donation.status = Donation.Status.COMPLETED
            send_donation_receipt_email(donation)
        return "completed"

    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict) and data.get("status") == "pending" and data.get("tx_ref") == donation.payment_reference:
        return "pending"

    Donation.objects.filter(pk=donation.pk, status=Donation.Status.PENDING).update(status=Donation.Status.FAILED)
    return "failed"


def giving_callback(request):
    """Flutterwave sends the browser back here after checkout."""
    status = request.GET.get("status")
    tx_ref = request.GET.get("tx_ref")
    transaction_id = request.GET.get("transaction_id")
    if not tx_ref:
        raise Http404("Payment reference required.")

    donation = get_object_or_404(Donation, payment_reference=tx_ref)
    _remember_for_thank_you(request, donation)
    if donation.status == Donation.Status.COMPLETED:
        return redirect("giving_thank_you", reference=donation.payment_reference)

    if status not in ("successful", "completed", "pending") or not transaction_id:
        Donation.objects.filter(pk=donation.pk, status=Donation.Status.PENDING).update(status=Donation.Status.FAILED)
        messages.error(request, "Your payment was cancelled, so nothing was charged. You can try again below.")
        return redirect("give")

    # Never trust the query string alone - re-verify server-to-server and
    # cross-check the amount/currency against what we actually asked for.
    try:
        outcome = _complete_if_verified(donation, transaction_id)
    except FlutterwaveError:
        outcome = "pending"

    if outcome == "failed":
        messages.error(
            request,
            "We couldn't confirm that payment. If money left your account, please contact the "
            f"church office and quote reference {donation.payment_reference[:10].upper()}.",
        )
        return redirect("give")
    return redirect("giving_thank_you", reference=donation.payment_reference)


@csrf_exempt
@require_POST
def flutterwave_webhook(request):
    """
    Flutterwave calls this server-to-server when a charge finishes - so a gift
    still completes even if the giver closed their browser before being sent
    back to giving_callback, or approved a Mobile Money prompt minutes later.
    Only ever acts on donations this app created (matched by tx_ref), and
    always re-verifies with Flutterwave before marking anything completed.
    """
    if not settings.FLUTTERWAVE_WEBHOOK_HASH:
        return HttpResponse("Webhook not configured.", status=503)
    if not webhook_signature_valid(request):
        return HttpResponse("Unauthorized", status=401)

    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponse("Bad payload", status=400)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return HttpResponse("Ignored")

    tx_ref, transaction_id = data.get("tx_ref"), data.get("id")
    donation = Donation.objects.filter(payment_reference=tx_ref).first() if tx_ref else None
    if not donation or not transaction_id or donation.status == Donation.Status.COMPLETED:
        # Not one of ours (e.g. an event ticket), or already handled.
        return HttpResponse("Ignored")

    try:
        _complete_if_verified(donation, transaction_id)
    except FlutterwaveError:
        # A non-2xx tells Flutterwave to retry later.
        return HttpResponse("Verification unavailable", status=502)
    return HttpResponse("OK")


def giving_thank_you(request, reference):
    """
    The page a giver lands on after checkout. Only viewable from the browser
    that made the gift (its reference is remembered in the session), so a
    shared or guessed link shows nothing.
    """
    if reference not in request.session.get(THANK_YOU_SESSION_KEY, []):
        raise Http404()
    donation = get_object_or_404(Donation, payment_reference=reference)
    return render(
        request,
        "giving/thank_you.html",
        {
            "donation": donation,
            "payments_enabled": giving_payments_enabled(),
            "short_reference": donation.payment_reference[:10].upper(),
        },
    )


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@login_required
def giving_statement(request):
    """
    A member's own completed-gifts summary for a date range, styled to
    print cleanly (the page's own "Print / Save as PDF" button just calls
    the browser's print dialog - every browser can save that as a PDF, so
    this needs no extra PDF-generation dependency). A POST here (the
    page's separate "Email Me This Statement" form, carrying the same
    start/end as hidden fields) instead emails this exact range to the
    member's own address via send_giving_statement_email, then redirects
    back to the same range as a GET so refreshing never re-sends it.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    today = timezone.localdate()
    params = request.POST if request.method == "POST" else request.GET
    start = _parse_date(params.get("start")) or today.replace(month=1, day=1)
    end = _parse_date(params.get("end")) or today
    if start > end:
        start, end = end, start

    if request.method == "POST":
        if send_giving_statement_email(member, start, end):
            messages.success(request, "Your statement was emailed to you.")
        else:
            messages.error(request, "We couldn't email your statement - please check that you have an email on file.")
        return redirect(f"{reverse('giving_statement')}?start={start:%Y-%m-%d}&end={end:%Y-%m-%d}")

    donations = Donation.objects.filter(
        member=member,
        status=Donation.Status.COMPLETED,
        date__date__gte=start,
        date__date__lte=end,
    ).order_by("date")
    total = donations.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    return render(
        request,
        "giving/statement.html",
        {"member": member, "donations": donations, "start": start, "end": end, "total": total},
    )


@login_required
def giving_statement_pdf(request):
    """
    The same statement as giving_statement above, as an actual downloadable
    PDF file (see giving/pdfs.py) rather than the browser's own print
    dialog - a real file a member can save, attach, or hand to an accountant,
    not just a printout. Same date-range query, same start/end GET params.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    today = timezone.localdate()
    start = _parse_date(request.GET.get("start")) or today.replace(month=1, day=1)
    end = _parse_date(request.GET.get("end")) or today
    if start > end:
        start, end = end, start

    donations = Donation.objects.filter(
        member=member,
        status=Donation.Status.COMPLETED,
        date__date__gte=start,
        date__date__lte=end,
    ).order_by("date")
    total = donations.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    pdf_bytes = build_giving_statement_pdf(member, donations, start, end, total)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    filename = f"giving-statement-{start:%Y-%m-%d}-to-{end:%Y-%m-%d}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def donation_receipt(request, donation_id):
    """
    A printable receipt for one specific completed gift - narrower than
    giving_statement above (a whole date range at once), for a member who
    wants a receipt for a single gift right after giving it rather than
    pulling a full statement. Scoped to status=COMPLETED and member=member
    together, so a member can neither see a receipt for someone else's gift
    by guessing an id, nor get a receipt for a gift that hasn't actually
    gone through yet.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    donation = get_object_or_404(Donation, id=donation_id, member=member, status=Donation.Status.COMPLETED)
    return render(request, "giving/receipt.html", {"member": member, "donation": donation})


def campaign_list(request):
    """
    Public "building fund" style page - active giving campaigns and how
    they're tracking. Inactive campaigns (finished, or not yet launched)
    are left off entirely, same rule the give/pledge forms follow.
    """
    campaigns = GivingCampaign.objects.filter(is_active=True).select_related("campus").order_by("-start_date")
    return render(request, "giving/campaign_list.html", {"campaigns": campaigns})


def campaign_detail(request, campaign_id):
    campaign = get_object_or_404(GivingCampaign, id=campaign_id, is_active=True)
    member = getattr(request.user, "member_profile", None) if request.user.is_authenticated else None
    my_pledge = Pledge.objects.filter(campaign=campaign, member=member).first() if member else None
    return render(
        request,
        "giving/campaign_detail.html",
        {"campaign": campaign, "my_pledge": my_pledge, "sms_giving_number": settings.CHURCH_SMS_GIVING_NUMBER},
    )


@authenticated_sms_webhook
def sms_giving_webhook(request):
    """
    Called by the SMS provider (Hubtel or similar) whenever someone texts
    the church's number - e.g. "GIVE 50" or "GIVE 100 BUILDING" for a
    specific campaign. See giving/services.py's record_sms_gift for the
    parsing/matching logic and why this only ever records a *pending* gift,
    never actually moves money.

    Exactly which field names a provider's incoming-message webhook uses for
    the sender's number and the message text differs between aggregators
    and isn't consistently documented, so this reads a handful of the most
    common ones rather than assuming a single shape - once you've pointed
    your provider's dashboard at this URL, send yourself a real test text
    and check what actually arrived (e.g. by temporarily logging
    request.POST) against the names below, adding your provider's exact
    field name if it isn't already covered.

    Always responds 200 OK, whether or not the message parsed as a valid
    giving request - an unrecognized text to the church's number is simply
    ignored, not an error, and a provider shouldn't retry/resend a message
    it already delivered.
    """
    data = request.POST or request.GET
    phone = (
        data.get("From")
        or data.get("from")
        or data.get("Sender")
        or data.get("sender")
        or data.get("msisdn")
        or data.get("MSISDN")
        or ""
    )
    message_text = (
        data.get("Content")
        or data.get("content")
        or data.get("Text")
        or data.get("text")
        or data.get("Body")
        or data.get("message")
        or ""
    )

    donation = record_sms_gift(phone=phone, message_text=message_text)

    if donation is not None:
        reply = (
            f"Newlife AG: Thanks! We've recorded your GHS {donation.amount} gift as pending - "
            "a team member will confirm it soon. God bless you."
        )
        send_sms(phone, reply)

    return HttpResponse("OK")


@login_required
def pledge_campaign(request, campaign_id):
    """A member committing to (or updating) their own pledge toward a campaign."""
    campaign = get_object_or_404(GivingCampaign, id=campaign_id, is_active=True)
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    pledge = Pledge.objects.filter(campaign=campaign, member=member).first()
    if request.method == "POST":
        form = PledgeForm(request.POST, instance=pledge)
        if form.is_valid():
            new_pledge = form.save(commit=False)
            new_pledge.campaign = campaign
            new_pledge.member = member
            new_pledge.save()
            messages.success(request, f"Your pledge of GH₵{new_pledge.amount} to {campaign} was recorded.")
            return redirect("campaign_detail", campaign_id=campaign.id)
    else:
        form = PledgeForm(instance=pledge)

    return render(
        request,
        "giving/pledge_form.html",
        {"form": form, "campaign": campaign, "pledge": pledge},
    )


@login_required
def recurring_giving_create(request):
    """A member setting up their own recurring giving commitment - see RecurringGiving's docstring."""
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    if request.method == "POST":
        form = RecurringGivingForm(request.POST)
        if form.is_valid():
            recurring = form.save(commit=False)
            recurring.member = member
            recurring.save()
            messages.success(request, "Your recurring gift was set up.")
            return redirect("dashboard")
    else:
        form = RecurringGivingForm()
    return render(request, "giving/recurring_giving_form.html", {"form": form, "is_new": True})


@login_required
def recurring_giving_edit(request, recurring_id):
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    recurring = get_object_or_404(RecurringGiving, id=recurring_id, member=member)
    if request.method == "POST":
        form = RecurringGivingForm(request.POST, instance=recurring)
        if form.is_valid():
            form.save()
            messages.success(request, "Your recurring gift was updated.")
            return redirect("dashboard")
    else:
        form = RecurringGivingForm(instance=recurring)
    return render(
        request, "giving/recurring_giving_form.html", {"form": form, "is_new": False, "recurring": recurring}
    )


@login_required
def recurring_giving_cancel(request, recurring_id):
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    recurring = get_object_or_404(RecurringGiving, id=recurring_id, member=member)
    if request.method == "POST":
        recurring.is_active = False
        recurring.save(update_fields=["is_active"])
        messages.success(request, "Your recurring gift was cancelled.")
    return redirect("dashboard")


@login_required
def recurring_giving_history(request):
    """
    Every recurring giving commitment a member has ever set up - active and
    cancelled alike - unlike the dashboard's "Your Recurring Giving" card,
    which (by design) only ever shows the currently-active ones. Lets a
    member find and reactivate a commitment they cancelled a while back
    instead of re-entering the same amount/frequency/campaign from scratch
    in recurring_giving_create.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    recurring_gifts = member.recurring_gifts.select_related("campaign").order_by("-is_active", "-id")
    return render(request, "giving/recurring_giving_history.html", {"recurring_gifts": recurring_gifts})


@login_required
def recurring_giving_reactivate(request, recurring_id):
    """
    Turns a cancelled recurring gift back on. next_due_date is reset to
    today rather than left at whatever stale date it was cancelled on -
    otherwise a commitment reactivated months later would look overdue the
    moment send_recurring_giving_reminders next runs and could even fire a
    reminder immediately for a date long past. Resetting to today means a
    reactivated commitment is treated exactly like a brand new one.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    recurring = get_object_or_404(RecurringGiving, id=recurring_id, member=member)
    if request.method == "POST":
        recurring.is_active = True
        recurring.next_due_date = timezone.localdate()
        # Reset the reminder history too - see RecurringGiving.reminder_count's
        # docstring and giving/services.py's lapsed_recurring_gifts. Otherwise
        # a commitment reactivated today would carry over its old reminder
        # count from before it was cancelled and could look "lapsed" again
        # immediately, before it's even had a first chance to be reminded.
        recurring.reminder_count = 0
        recurring.last_reminder_sent = None
        recurring.save(update_fields=["is_active", "next_due_date", "reminder_count", "last_reminder_sent"])
        messages.success(request, "Your recurring gift was reactivated.")
    return redirect("recurring_giving_history")
