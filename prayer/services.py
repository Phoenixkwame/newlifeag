"""
Shared logic for marking a prayer request as prayed for - mirrors
giving/services.py's mark_donation_completed, so there's exactly one place
that decides what "prayed for" means and writes the audit trail for it,
whichever screen (currently just the staff area) is used.

Also holds the SMS-submission flow below: a member without a smartphone or
reliable data can submit a prayer request by texting the church's number,
e.g. "PRAY for my mother's surgery next week" - same SMS-keyword shape as
giving/services.py's SMS giving and members/services.py's SMS check-in, and
reuses their same phone-matching helper (find_member_by_phone).
"""

import re

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from giving.services import find_member_by_phone

from .models import PrayerRequest
from .notifications import send_prayer_answered_notification


def mark_prayed_for(prayer_request, *, user):
    """
    Marks a prayer request as prayed for. Idempotent - calling this again on
    an already-prayed-for request is a safe no-op that returns False, so a
    double-click on the staff button (or a re-submitted form) can't do
    anything strange, and prayed_for_at never gets silently overwritten.
    """
    if prayer_request.prayed_for:
        return False

    prayer_request.prayed_for = True
    prayer_request.prayed_for_at = timezone.now()
    prayer_request.save(update_fields=["prayed_for", "prayed_for_at"])

    content_type = ContentType.objects.get_for_model(prayer_request)
    LogEntry.objects.log_action(
        user_id=user.pk,
        content_type_id=content_type.pk,
        object_id=prayer_request.pk,
        object_repr=str(prayer_request),
        action_flag=CHANGE,
        change_message="Marked as prayed for.",
    )
    send_prayer_answered_notification(prayer_request)
    return True


# --- SMS-based prayer request submission --------------------------------------
#
# An SMS-submitted request is never public - is_public/share_name_publicly
# both default to False on PrayerRequest, so it only ever reaches the staff
# prayer list, never the public wall, unless a member later chooses to make
# it public from their own dashboard. There's no way to collect that consent
# over a single one-way text.

_PRAYER_MESSAGE_PATTERN = re.compile(r"^\s*PRAY\s+(\S.*)$", re.IGNORECASE | re.DOTALL)


def is_sms_prayer_message(text):
    """True if the text looks like a "PRAY <request>" submission - an unrelated text isn't a prayer request at all."""
    return bool(text and _PRAYER_MESSAGE_PATTERN.match(text.strip()))


def record_sms_prayer_request(*, phone, message_text):
    """
    Returns (prayer_request, error): error is None on success,
    "not_a_prayer_message" if the text wasn't a recognized "PRAY ..."
    submission at all (ignore silently, same as an unrelated text to any of
    this project's other SMS keywords), or "no_matching_member" if it was a
    submission but no member's phone matches (worth telling the sender,
    unlike the first case).
    """
    text = (message_text or "").strip()
    match = _PRAYER_MESSAGE_PATTERN.match(text)
    if not match:
        return None, "not_a_prayer_message"

    member = find_member_by_phone(phone)
    if member is None:
        return None, "no_matching_member"

    prayer_request = PrayerRequest.objects.create(member=member, request_text=match.group(1).strip())
    return prayer_request, None
