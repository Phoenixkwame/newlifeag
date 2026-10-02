"""
Builds and sends the weekly staff digest - a single Friday email to Pastors
summarizing the week, so leadership doesn't have to open four different
staff pages to catch new members, gifts awaiting reconciliation, upcoming
volunteer gaps, and prayer requests needing attention. Sent by the
send_weekly_digest management command below; never from a page view.

Two different senses of "the week" are mixed together deliberately:
- New members: who actually joined in the last 7 days - a real weekly slice.
- Pending gifts, open prayer requests, and absentee members: the current
  backlog needing attention, not just this week's - the point is to surface
  anything still outstanding, the same way the existing Donations/Prayer
  Requests/Absentees tabs would show it right now.
- Volunteer gaps: slots still open for the next two weeks of events - looking
  forward, not back, since the whole point is giving staff time to fill them
  before the event, not after.

Recipients are the Pastors group, the same "sees everything across the
church" role already used elsewhere (see staff/services.py's backup export
and setup_groups.py's PASTOR_MODELS) - a natural fit for a summary that
touches membership, giving, volunteering, and pastoral care all at once.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.mail import send_mail
from django.db.models import Sum
from django.utils import timezone

from events.models import VolunteerSlot
from followup.services import stale_follow_ups
from giving.models import Donation
from giving.services import lapsed_recurring_gifts
from members.models import Member
from members.services import absentee_members
from prayer.models import PrayerRequest

logger = logging.getLogger(__name__)

# How far ahead to look for volunteer slots that still need filling.
VOLUNTEER_GAP_WINDOW = timedelta(days=14)


def build_weekly_digest():
    """
    Gathers this week's numbers into a plain dict - kept separate from the
    email-sending/formatting below so the underlying counts can be tested
    directly without going through django.core.mail at all.
    """
    now = timezone.now()
    week_ago = now - timedelta(days=7)

    new_members = list(
        Member.objects.filter(date_joined__gte=week_ago.date()).order_by("date_joined")
    )

    pending_donations = list(
        Donation.objects.filter(status=Donation.Status.PENDING).select_related("member").order_by("date")
    )
    pending_total = (
        Donation.objects.filter(status=Donation.Status.PENDING).aggregate(total=Sum("amount"))["total"] or 0
    )

    volunteer_gaps = [
        slot
        for slot in VolunteerSlot.objects.filter(
            event__start_datetime__gte=now, event__start_datetime__lte=now + VOLUNTEER_GAP_WINDOW
        ).select_related("event")
        if slot.spots_remaining > 0
    ]

    open_prayer_requests = list(
        PrayerRequest.objects.filter(prayed_for=False).select_related("member").order_by("-created_at")
    )

    absentees = absentee_members()
    lapsed_givers = lapsed_recurring_gifts()
    stale_followups = stale_follow_ups()

    return {
        "new_members": new_members,
        "pending_donations": pending_donations,
        "pending_total": pending_total,
        "volunteer_gaps": volunteer_gaps,
        "open_prayer_requests": open_prayer_requests,
        "absentees": absentees,
        "lapsed_givers": lapsed_givers,
        "stale_followups": stale_followups,
    }


def _format_digest_email(digest):
    lines = ["This week at Newlife AG:", ""]

    lines.append(f"New members this week: {len(digest['new_members'])}")
    for member in digest["new_members"]:
        lines.append(f"  - {member}")
    lines.append("")

    lines.append(
        f"Pending gifts awaiting reconciliation: {len(digest['pending_donations'])} "
        f"(GHS {digest['pending_total']} total)"
    )
    for donation in digest["pending_donations"]:
        who = donation.member if donation.member else "Anonymous"
        lines.append(f"  - {who}: GHS {donation.amount} ({donation.get_donation_type_display()})")
    lines.append("")

    lines.append(f"Upcoming volunteer gaps (next 2 weeks): {len(digest['volunteer_gaps'])}")
    for slot in digest["volunteer_gaps"]:
        lines.append(f"  - {slot.role_needed} for {slot.event} - {slot.spots_remaining} spot(s) open")
    lines.append("")

    lines.append(f"Open prayer requests: {len(digest['open_prayer_requests'])}")
    for request in digest["open_prayer_requests"]:
        lines.append(f"  - {request.member} ({request.created_at:%b %d})")
    lines.append("")

    lines.append(f"Members who've gone quiet (no attendance in a while): {len(digest['absentees'])}")
    for member, last_attended in digest["absentees"]:
        when = f"last seen {last_attended:%b %d}" if last_attended else "never attended"
        lines.append(f"  - {member} ({when})")
    lines.append("")

    lines.append(f"Lapsed recurring givers (reminded repeatedly, nothing given): {len(digest['lapsed_givers'])}")
    for recurring in digest["lapsed_givers"]:
        lines.append(f"  - {recurring.member}: GHS {recurring.amount} {recurring.get_frequency_display()}")
    lines.append("")

    lines.append(f"Follow-ups that have gone quiet: {len(digest['stale_followups'])}")
    for follow_up in digest["stale_followups"]:
        lines.append(f"  - {follow_up.member} ({follow_up.get_stage_display()})")
    lines.append("")

    lines.append("Full details are in the staff area, as always.")
    return "\n".join(lines)


def send_weekly_digest():
    """
    Builds the digest and emails it to every Pastor with an email on file.
    Never raises - a broken SMTP setup shouldn't crash the scheduled task
    that calls this (see send_weekly_digest management command). Returns the
    number of recipients the email was sent to (0 if there were none, or if
    the Pastors group doesn't exist yet because setup_groups hasn't run).
    """
    try:
        pastors = Group.objects.get(name="Pastors")
    except Group.DoesNotExist:
        return 0

    recipient_list = [user.email for user in pastors.user_set.all() if user.email]
    if not recipient_list:
        return 0

    digest = build_weekly_digest()
    subject = "Newlife AG - Weekly Staff Digest"
    message = _format_digest_email(digest)

    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=False)
    except Exception:
        logger.exception("Couldn't send the weekly staff digest email.")
        return 0

    return len(recipient_list)
