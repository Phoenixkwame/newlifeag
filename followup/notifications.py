"""
Best-effort email (and, if configured, SMS) to the Ushers and Pastors groups
whenever someone submits the public connect card (see followup/views.py's
connect_card) - so a new guest doesn't just sit in the follow-up list until
someone happens to check it.

Never raises: a broken SMTP/SMS setup shouldn't stop a guest's card from
being recorded. See churchapp/sms.py for how SMS being "on" works.
"""

import logging

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.mail import send_mail

from churchapp.sms import send_sms

logger = logging.getLogger(__name__)


def notify_followup_team_of_new_connection(follow_up, *, subject="New connect card submitted", action="filled out the connect card"):
    """
    `subject`/`action` let a different entry point into the follow-up
    pipeline (e.g. members/views.py's signup, a brand-new member creating
    their own login account rather than submitting the anonymous connect
    card) send an accurate message instead of one that always says
    "connect card" - the notification logic and recipient list stay
    identical either way.
    """
    users = []
    seen_user_ids = set()
    for group_name in ("Ushers", "Pastors"):
        try:
            group = Group.objects.get(name=group_name)
        except Group.DoesNotExist:
            # setup_groups hasn't been run yet - nothing to notify.
            continue
        for user in group.user_set.select_related("member_profile"):
            if user.id not in seen_user_ids:
                seen_user_ids.add(user.id)
                users.append(user)

    member = follow_up.member
    message = (
        f"{member} just {action} on the church website "
        f"(phone: {member.phone or '—'}, email: {member.email or '—'}).\n\n"
        "Follow up with them from the Follow-Up tab in the staff area."
    )
    sms_text = f"Newlife AG: {member} just {action} - check the Follow-Up tab."

    recipient_list = [u.email for u in users if u.email]
    if recipient_list:
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=False)
        except Exception:
            logger.exception("Couldn't send the new-connection notification email.")

    # SMS only reaches someone who's also linked to a Member record with a
    # phone number on file - Users themselves have no phone field. Most
    # staff accounts are linked this way, but it's fine if some aren't.
    for user in users:
        staff_member = getattr(user, "member_profile", None)
        if staff_member and staff_member.phone:
            send_sms(staff_member.phone, sms_text)
