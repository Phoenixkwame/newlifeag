"""
Best-effort email (and, if configured, SMS) to a member telling them the
pastoral team has prayed for a request they submitted - sent once, right
when prayer/services.py's mark_prayed_for marks it (never from a page view
directly, so this fires exactly once per request no matter which staff
screen triggered it).

Never raises: a broken SMTP/SMS setup shouldn't stop a pastor from marking a
request prayed for. See churchapp/sms.py for how SMS being "on" works.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail

from churchapp.sms import send_sms

logger = logging.getLogger(__name__)


def send_prayer_answered_notification(prayer_request):
    """
    Skipped entirely if the member has turned this specific nudge off (see
    Member.notify_prayer_updates) - unlike a receipt or a confirmation of
    something the member themselves just did, this is a proactive update
    the church sends later, unprompted, so it follows the same opt-out
    pattern as send_volunteer_reminder and the giving reminders rather than
    the always-sent confirmations.
    """
    member = prayer_request.member
    if member is None:
        # Guest contact details are for personal pastoral follow-up.
        return False
    if not member.notify_prayer_updates:
        return False

    contacted = False
    if member.email:
        subject = "Someone prayed for your request - Newlife AG"
        message = (
            f"Hi {member.first_name},\n\n"
            "Just a note to let you know our pastoral team has prayed for the request you "
            "submitted. We're standing with you in prayer.\n\n"
            "You can submit another request any time from your dashboard."
        )
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [member.email], fail_silently=False)
        except Exception:
            logger.exception("Couldn't send a prayer-answered notification email.")
        contacted = True

    if member.phone:
        sms_text = "Newlife AG: Our pastoral team has prayed for the request you submitted. We're standing with you."
        send_sms(member.phone, sms_text)
        contacted = True

    return contacted
