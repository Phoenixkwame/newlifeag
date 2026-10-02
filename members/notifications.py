"""
Best-effort birthday/anniversary greetings - same pattern as
events/notifications.py and giving/notifications.py: never raises, silently
skipped if the member has no email/phone on file or if SMTP/SMS isn't
configured. Sent by the send_birthday_greetings/send_anniversary_greetings
management commands (see members/management/commands/), not from any page
view, since nothing about visiting a page should trigger someone else's
greeting.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail

from churchapp.sms import send_sms

from .models import Member

logger = logging.getLogger(__name__)


def send_birthday_greeting(member):
    subject = "Happy Birthday from Newlife AG!"
    message = (
        f"Happy Birthday, {member.first_name}!\n\n"
        "The whole Newlife AG family celebrates with you today. May God bless "
        "you richly in the year ahead."
    )
    sms_text = f"Newlife AG: Happy Birthday, {member.first_name}! We're celebrating with you today. God bless you."
    return _send_both(member, subject, message, sms_text)


def send_anniversary_greeting(member):
    subject = "Happy Anniversary from Newlife AG!"
    message = (
        f"Happy Anniversary, {member.first_name}!\n\n"
        "Congratulations on another year together. The Newlife AG family "
        "rejoices with you and your spouse today."
    )
    sms_text = f"Newlife AG: Happy Anniversary, {member.first_name}! We're rejoicing with you and your family today."
    return _send_both(member, subject, message, sms_text)


def send_serving_reminder(assignment):
    """
    A reminder that a member is scheduled to serve on a ministry team soon -
    sent by the daily send_serving_reminders management command, never from
    a page view. Returns True if the member has an email or phone on file to
    actually reach.

    Asks the member to reply YES/CONFIRM or NO/DECLINE - see
    members/services.py's record_sms_serving_response, which the
    sms_serving_response_webhook calls whenever a reply like that comes in -
    so a member with only a phone (no login, no email) still has a way to
    let the team know they can't make it, instead of a reminder they can
    only ever receive and never respond to.
    """
    member = assignment.member
    when = f"{assignment.date:%A, %B %d}"
    contacted = False

    if member.email:
        subject = f"You're serving on {assignment.group.name} - {when}"
        message = (
            f"Hi {member.first_name},\n\n"
            f'Just a reminder that you\'re scheduled to serve as "{assignment.role}" '
            f'on the {assignment.group.name} team for {when}.\n\n'
            + (f"Notes: {assignment.notes}\n\n" if assignment.notes else "")
            + "Reply YES to confirm or NO if you can't make it.\n\n"
            + "See you then!"
        )
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [member.email], fail_silently=False)
        except Exception:
            logger.exception("Couldn't send a serving reminder email.")
        contacted = True

    if member.phone:
        sms_text = (
            f'Newlife AG: Reminder - you\'re serving as "{assignment.role}" on {assignment.group.name} for {when}. '
            "Reply YES to confirm or NO to decline."
        )
        send_sms(member.phone, sms_text)
        contacted = True

    return contacted


def notify_leader_of_declined_assignment(assignment):
    """
    Lets a group's leader know right away when a member declines a serving
    assignment by text (see members/services.py's
    record_sms_serving_response) - the whole point of offering a decline
    reply is so the gap gets noticed and filled before the service, not
    discovered when the member simply doesn't show up.
    """
    leader = assignment.group.leader
    if leader is None:
        return False
    subject = f"{assignment.member} can't make it - {assignment.group.name}"
    when = f"{assignment.date:%A, %B %d}"
    message = (
        f"{assignment.member} just declined their assignment as \"{assignment.role}\" "
        f"on the {assignment.group.name} team for {when}. You may want to find a replacement."
    )
    sms_text = (
        f'Newlife AG: {assignment.member} declined "{assignment.role}" on {assignment.group.name} '
        f"for {when} - you may want to find a replacement."
    )
    return _send_both(leader, subject, message, sms_text)


def notify_group_of_shoutout(shoutout):
    """
    Pushes a freshly-posted TeamShoutout out by email/SMS to every currently
    active member of its group - called once, right after the shoutout is
    created (see members/views.py's group_shoutouts), never on a schedule or
    a page visit. Best-effort per member, same as everywhere else in this
    file: one member's failed email/SMS never stops the rest of the team
    from being reached. Returns how many members were actually contacted
    (had an email or phone on file) - the calling view uses this to tell
    the poster how many people were reached.
    """
    group = shoutout.group
    who = shoutout.posted_by.first_name if shoutout.posted_by else "Your group leader"
    subject = f"A message from {group}"
    message = f'{who} posted this to {group}:\n\n"{shoutout.message}"'
    sms_text = f'Newlife AG - {group}: "{shoutout.message}"'

    contacted = 0
    members = Member.objects.filter(memberships__group=group, memberships__left_date__isnull=True).distinct()
    for member in members:
        if _send_both(member, subject, message, sms_text):
            contacted += 1
    return contacted


def _send_both(member, subject, message, sms_text):
    """Returns True if either channel was actually attempted (has contact info on file)."""
    contacted = False
    if member.email:
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [member.email], fail_silently=False)
        except Exception:
            logger.exception("Couldn't send a greeting email to %s.", member)
        contacted = True
    if member.phone:
        send_sms(member.phone, sms_text)
        contacted = True
    return contacted
