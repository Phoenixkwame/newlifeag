"""
Best-effort email (and, if configured, SMS) to the Pastors group whenever a
member submits a pastoral care request (see care/views.py's
submit_care_request) - mirrors followup/notifications.py's
notify_followup_team_of_new_connection, but deliberately notifies Pastors
only, never Ushers, matching who's allowed to see CareRequest at all (see
PASTOR_MODELS in setup_groups.py).

Never raises: a broken SMTP/SMS setup shouldn't stop a member's request from
being recorded.
"""

import logging

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.mail import send_mail

from churchapp.sms import send_sms

logger = logging.getLogger(__name__)


def notify_pastors_of_new_care_request(care_request):
    try:
        pastors = Group.objects.get(name="Pastors")
    except Group.DoesNotExist:
        # setup_groups hasn't been run yet - nothing to notify.
        return

    member = care_request.member
    subject = "New pastoral care request"
    message = (
        f"{member} submitted a {care_request.get_request_type_display()} request.\n\n"
        f"{care_request.details}\n\n"
        "Review it from the Care Requests tab in the staff area."
    )
    sms_text = f"Newlife AG: {member} submitted a pastoral care request - check the Care Requests tab."

    users = list(pastors.user_set.select_related("member_profile"))
    recipient_list = [u.email for u in users if u.email]
    if recipient_list:
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=False)
        except Exception:
            logger.exception("Couldn't send the new-care-request notification email.")

    for user in users:
        staff_member = getattr(user, "member_profile", None)
        if staff_member and staff_member.phone:
            send_sms(staff_member.phone, sms_text)
