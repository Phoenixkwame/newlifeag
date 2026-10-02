from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render

from churchapp.sms import send_sms
from churchapp.webhooks import authenticated_sms_webhook

from .forms import PrayerRequestForm, PublicPrayerRequestForm
from .models import PrayerRequest
from .services import record_sms_prayer_request


def public_prayer_request(request):
    form = PublicPrayerRequestForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        prayer_request = form.save(commit=False)
        prayer_request.member = getattr(request.user, "member_profile", None)
        prayer_request.approved_for_public = False
        prayer_request.save()
        return redirect("prayer_request_received")
    return render(request, "prayer/request.html", {"form": form})


def prayer_request_received(request):
    return render(request, "prayer/received.html")


@login_required
def submit_prayer_request(request):
    """
    Posted from the member's own dashboard (see members/templates/members/
    dashboard.html) - there's no separate page for this, just an inline form.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    if request.method == "POST":
        form = PrayerRequestForm(request.POST)
        if form.is_valid():
            prayer_request = form.save(commit=False)
            prayer_request.member = member
            prayer_request.save()
            messages.success(request, "Your prayer request has been submitted.")
        else:
            messages.error(request, "Couldn't submit that - please try again.")
    return redirect("dashboard")


def prayer_wall(request):
    """
    The public prayer wall - only requests a member explicitly marked
    is_public show up here at all, and even then only with their name if
    they also chose share_name_publicly (see PrayerRequestForm).
    """
    requests_qs = PrayerRequest.objects.filter(is_public=True, approved_for_public=True).select_related("member")
    page_obj = Paginator(requests_qs, 20).get_page(request.GET.get("page"))
    return render(request, "prayer/wall.html", {"page_obj": page_obj})


@authenticated_sms_webhook
def sms_prayer_webhook(request):
    """
    Called by the SMS provider whenever someone texts the church's number -
    same "read a handful of common field-name spellings" approach as
    giving/views.py's sms_giving_webhook and members/views.py's
    sms_checkin_webhook, since exactly which field names a provider uses for
    the sender's number and message text isn't consistently documented.
    Always responds 200 OK, whether or not the text was a recognized prayer
    submission, so a provider never retries a message it already delivered.
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

    prayer_request, error = record_sms_prayer_request(phone=phone, message_text=message_text)

    if prayer_request is not None:
        send_sms(
            phone,
            f"Newlife AG: Your prayer request has been received, {prayer_request.member.first_name}. "
            "Our pastoral team will be praying with you.",
        )
    elif error == "no_matching_member":
        send_sms(
            phone,
            "Newlife AG: We couldn't match that number to a member on file - "
            "please contact the church office, or update your phone number.",
        )
    # error == "not_a_prayer_message" is silently ignored, same as an
    # unrelated text to the giving/check-in numbers - not every text to this
    # number is meant for us.

    return HttpResponse("OK")
