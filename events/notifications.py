"""
Best-effort confirmation emails (and, if configured, SMS) for RSVPs and
volunteer sign-ups.

A broken or unconfigured SMTP/SMS setup should never stop someone from
RSVPing or signing up to volunteer - sending is wrapped so any failure here
is logged, never raised, and a member missing an email (or, for SMS, missing
a phone number, or SMS just not being configured at all) is simply skipped
rather than erroring. See churchapp/sms.py for how SMS being "on" works.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail

from churchapp.sms import send_sms

logger = logging.getLogger(__name__)


def send_rsvp_confirmation(rsvp):
    member = rsvp.member
    event = rsvp.event
    when = f"{event.start_datetime:%A, %B %d %Y at %I:%M %p}"

    if member.email:
        subject = f"RSVP confirmed: {event.title}"
        message = (
            f"Hi {member.first_name},\n\n"
            f'Your RSVP for "{event.title}" is recorded as: {rsvp.get_status_display()}.\n\n'
            f"When: {when}\n"
        )
        if event.location:
            message += f"Where: {event.location}\n"
        _send_email(subject, message, [member.email])

    sms_text = f'Newlife AG: Your RSVP for "{event.title}" ({when}) is recorded as {rsvp.get_status_display()}.'
    send_sms(member.phone, sms_text)


def send_volunteer_signup_confirmation(signup):
    member = signup.member
    slot = signup.slot
    event = slot.event
    when = f"{event.start_datetime:%A, %B %d %Y at %I:%M %p}"

    if member.email:
        subject = f"You're signed up to volunteer: {slot.role_needed}"
        message = (
            f"Hi {member.first_name},\n\n"
            f'You\'re confirmed as {slot.role_needed} for "{event.title}".\n\n'
            f"When: {when}\n"
        )
        if event.location:
            message += f"Where: {event.location}\n"
        _send_email(subject, message, [member.email])

    sms_text = f'Newlife AG: You\'re confirmed as {slot.role_needed} for "{event.title}" ({when}).'
    send_sms(member.phone, sms_text)


def send_waitlist_spot_opened_notification(signup):
    """
    Sent once, right when a waitlisted member is automatically promoted into
    a real VolunteerSignup (see events/services.py's
    cancel_volunteer_signup) - the whole point of a waitlist is that the
    member doesn't have to keep checking back themselves, so this tells them
    the spot is now theirs without them lifting a finger.
    """
    member = signup.member
    slot = signup.slot
    event = slot.event
    when = f"{event.start_datetime:%A, %B %d %Y at %I:%M %p}"

    if member.email:
        subject = f"A spot opened up: {slot.role_needed}"
        message = (
            f"Hi {member.first_name},\n\n"
            f'Good news - a spot opened up and you\'re now signed up as {slot.role_needed} '
            f'for "{event.title}".\n\n'
            f"When: {when}\n"
        )
        if event.location:
            message += f"Where: {event.location}\n"
        _send_email(subject, message, [member.email])

    sms_text = (
        f'Newlife AG: A spot opened up - you\'re now signed up as {slot.role_needed} for "{event.title}" ({when}).'
    )
    send_sms(member.phone, sms_text)


def send_registration_confirmation(registration):
    """Sent once a paid (or free-with-payments-disabled) ticket registration is confirmed - see events/views.py."""
    member = registration.member
    ticket = registration.ticket
    event = ticket.event
    when = f"{event.start_datetime:%A, %B %d %Y at %I:%M %p}"

    if member and member.email:
        subject = f"Registration confirmed: {event.title}"
        message = (
            f"Hi {member.first_name},\n\n"
            f'You\'re registered for "{event.title}" ({ticket.name}).\n\n'
            f"When: {when}\n"
        )
        if event.location:
            message += f"Where: {event.location}\n"
        _send_email(subject, message, [member.email])

    if member:
        sms_text = f'Newlife AG: You\'re registered for "{event.title}" ({ticket.name}, {when}).'
        send_sms(member.phone, sms_text)


def send_volunteer_reminder(signup):
    """
    A "don't forget" nudge sent shortly before a volunteer's slot - see the
    send_volunteer_reminders management command, which decides *when* this
    goes out and marks signup.reminder_sent_at so it's never sent twice.
    Skipped entirely if the member has turned this specific nudge off (see
    Member.notify_volunteer_reminders) - the command still marks
    reminder_sent_at either way, so opting out doesn't cause a retry loop.
    Unlike this, send_volunteer_signup_confirmation above is never gated -
    it's the immediate confirmation of the member's own action, not a
    proactive reminder sent later.
    """
    member = signup.member
    if not member.notify_volunteer_reminders:
        return
    slot = signup.slot
    event = slot.event
    when = f"{event.start_datetime:%A, %B %d %Y at %I:%M %p}"

    if member.email:
        subject = f"Reminder: you're volunteering tomorrow - {slot.role_needed}"
        message = (
            f"Hi {member.first_name},\n\n"
            f'Just a reminder that you\'re signed up as {slot.role_needed} for "{event.title}".\n\n'
            f"When: {when}\n"
        )
        if event.location:
            message += f"Where: {event.location}\n"
        _send_email(subject, message, [member.email])

    sms_text = f'Newlife AG reminder: you\'re volunteering as {slot.role_needed} for "{event.title}" ({when}).'
    send_sms(member.phone, sms_text)


def _send_email(subject, message, recipient_list):
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=False)
    except Exception:
        logger.exception("Couldn't send an event notification email.")
