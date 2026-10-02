"""
Best-effort email (and, if configured, SMS) to everyone in the Treasurers
group whenever a gift is recorded as pending in a way that needs a person to
reconcile it by hand (the manual fallback used while online payments aren't
configured, or a gift a Treasurer/Pastor logs directly in the staff area) -
so it doesn't just sit there until someone happens to open the Donations tab.

Never raises: a broken SMTP/SMS setup shouldn't stop someone from giving, or
stop a staff member from logging a gift. See churchapp/sms.py for how SMS
being "on" works.
"""

import logging
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.mail import send_mail
from django.db.models import Sum

from churchapp.sms import send_sms

from .models import Donation

logger = logging.getLogger(__name__)


def notify_treasurers_of_pending_donation(donation):
    try:
        treasurers = Group.objects.get(name="Treasurers")
    except Group.DoesNotExist:
        # setup_groups hasn't been run yet - nothing to notify.
        return

    treasurer_users = list(treasurers.user_set.select_related("member_profile"))
    recipient_list = [u.email for u in treasurer_users if u.email]

    who = donation.member if donation.member else "Anonymous"
    subject = "New pending gift needs reconciling"
    message = (
        f"{who} recorded a gift of GHS {donation.amount} ({donation.get_donation_type_display()}) "
        "that needs manual reconciliation once the cash or mobile money is confirmed.\n\n"
        "Reconcile it from the Donations tab in the staff area."
    )
    if recipient_list:
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=False)
        except Exception:
            logger.exception("Couldn't send the pending-donation notification email.")

    # SMS only reaches a Treasurer who's also linked to a Member record with
    # a phone number on file - Users themselves have no phone field. Most
    # staff accounts are linked this way, but it's fine if some aren't.
    sms_text = f"Newlife AG: New pending gift of GHS {donation.amount} from {who} needs reconciling."
    for user in treasurer_users:
        member = getattr(user, "member_profile", None)
        if member and member.phone:
            send_sms(member.phone, sms_text)


def send_pledge_reminder(pledge):
    """
    A gentle nudge to a member about a campaign pledge they haven't fully
    given toward yet - sent on demand by a Treasurer/Pastor from a
    campaign's staff page (see staff/views.py's campaign_send_reminders),
    never automatically. Returns True if the member has an email or phone
    on file to actually reach - False means there's no contact info at all,
    or the member has turned this nudge off (see Member.notify_pledge_
    reminders) - either way the calling view can report how many members
    were skipped entirely.
    """
    member = pledge.member
    if not member.notify_pledge_reminders:
        return False
    campaign = pledge.campaign
    # Decimal(...) rather than a bare subtraction - pledge.amount can still
    # be a plain string on an unsaved/unrefreshed in-memory instance (e.g.
    # one just built with Pledge.objects.create(amount="200.00")), and a
    # DecimalField only actually holds a Decimal once it's round-tripped
    # through the database.
    remaining = Decimal(str(pledge.amount)) - pledge.given_toward_pledge
    contacted = False

    if member.email:
        subject = f"Reminder: your pledge to {campaign.name}"
        message = (
            f"Hi {member.first_name},\n\n"
            f"Just a friendly reminder about your pledge of GHS {pledge.amount} to "
            f'"{campaign.name}". So far GHS {pledge.given_toward_pledge} has been given '
            f"toward it, leaving GHS {remaining} outstanding.\n\n"
            "You're welcome to give toward it any time from the church's giving page."
        )
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [member.email], fail_silently=False)
        except Exception:
            logger.exception("Couldn't send a pledge reminder email.")
        contacted = True

    if member.phone:
        sms_text = (
            f"Newlife AG: Reminder - GHS {remaining} is still outstanding on your "
            f'GHS {pledge.amount} pledge to "{campaign.name}".'
        )
        send_sms(member.phone, sms_text)
        contacted = True

    return contacted


def send_recurring_giving_reminder(recurring):
    """
    A member's own reminder that a recurring gift they set up is due - sent
    by the daily send_recurring_giving_reminders management command, never
    from a page view. Nothing here actually moves money (see
    RecurringGiving's docstring) - it just nudges the member back to the
    ordinary /give/ page. Returns True if the member has an email or phone
    on file to actually reach - same Member.notify_pledge_reminders opt-out
    as send_pledge_reminder above, since both are "you still owe something"
    nudges rather than a receipt or a confirmation.
    """
    member = recurring.member
    if not member.notify_pledge_reminders:
        return False
    campaign_note = f' toward "{recurring.campaign.name}"' if recurring.campaign else ""
    contacted = False

    if member.email:
        subject = "Your recurring gift is due"
        message = (
            f"Hi {member.first_name},\n\n"
            f"This is your {recurring.get_frequency_display().lower()} reminder to give "
            f"GHS {recurring.amount}{campaign_note}.\n\n"
            "You're welcome to give any time from the church's giving page."
        )
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [member.email], fail_silently=False)
        except Exception:
            logger.exception("Couldn't send a recurring-giving reminder email.")
        contacted = True

    if member.phone:
        sms_text = (
            f"Newlife AG: Reminder - your {recurring.get_frequency_display().lower()} gift of "
            f"GHS {recurring.amount}{campaign_note} is due."
        )
        send_sms(member.phone, sms_text)
        contacted = True

    return contacted


def send_annual_giving_statement(member, year):
    """
    Emails a member their own year-end giving statement for `year` - the
    same completed-gifts data as their own printable /give/statement/ page
    (giving/views.py's giving_statement), pushed straight to their inbox
    instead of waiting for them to visit the site or a Treasurer to
    download it for them one member at a time. Called by the
    send_giving_statements management command, never from a page view.

    Returns True if the member has an email on file to actually reach
    (False means nothing was sent - the calling command reports how many
    members were skipped this way).
    """
    if not member.email:
        return False

    donations = Donation.objects.filter(
        member=member, status=Donation.Status.COMPLETED, date__year=year
    ).order_by("date")
    total = donations.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    lines = [
        f"Hi {member.first_name},",
        "",
        f"Here is your giving statement for {year}, for your records:",
        "",
    ]
    for donation in donations:
        lines.append(
            f"  {donation.date:%b %d, %Y} - GHS {donation.amount} ({donation.get_donation_type_display()})"
        )
    lines.append("")
    lines.append(f"Total for {year}: GHS {total}")
    lines.append("")
    lines.append(
        "Thank you for your faithful giving this year. This statement is also available any time "
        "from your dashboard."
    )
    message = "\n".join(lines)

    subject = f"Your {year} Giving Statement - Newlife AG"
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [member.email], fail_silently=False)
    except Exception:
        logger.exception("Couldn't send an annual giving statement email.")

    return True


def send_giving_statement_email(member, start, end):
    """
    Emails a member their own giving statement for an arbitrary date range -
    the same donations query as their self-service /give/statement/ page
    (giving/views.py's giving_statement) - so a member looking at that page
    can have it land in their inbox on demand instead of only ever printing
    or saving it as a PDF from the browser. Deliberately separate from
    send_annual_giving_statement above, which is always a full calendar year
    and only ever sent in bulk by the send_giving_statements management
    command - this is a member's own one-off request for whatever range
    they're currently viewing.

    Returns True only if the member has an email on file and the send
    actually succeeded - unlike send_annual_giving_statement above, a
    failed send here is worth reporting back to the member (see
    giving/views.py's giving_statement), since they're waiting on it right
    now rather than it running unattended overnight.
    """
    if not member.email:
        return False

    donations = Donation.objects.filter(
        member=member, status=Donation.Status.COMPLETED, date__date__gte=start, date__date__lte=end
    ).order_by("date")
    total = donations.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    lines = [
        f"Hi {member.first_name},",
        "",
        f"Here is your giving statement for {start:%b %d, %Y} - {end:%b %d, %Y}, for your records:",
        "",
    ]
    for donation in donations:
        lines.append(
            f"  {donation.date:%b %d, %Y} - GHS {donation.amount} ({donation.get_donation_type_display()})"
        )
    lines.append("")
    lines.append(f"Total: GHS {total}")
    lines.append("")
    lines.append(
        "Thank you for your faithful giving. This statement is also available any time from your dashboard."
    )
    message = "\n".join(lines)

    subject = "Your Giving Statement - Newlife AG"
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [member.email], fail_silently=False)
    except Exception:
        logger.exception("Couldn't send an on-demand giving statement email.")
        return False
    return True


def send_donation_receipt_email(donation):
    """
    A short "thank you, here's your receipt" email the moment one of a
    member's own gifts is recorded as completed - whether that's an
    immediate online payment (giving/views.py's give_callback) or a
    Treasurer reconciling a pending gift by hand later (giving/services.py's
    mark_donation_completed). Distinct from the on-demand statement emails
    above (a member's own request for a date range) and the annual bulk
    statement - this is the one automatic, per-gift notification, so it's
    gated on its own Member.notify_giving_receipts flag rather than
    notify_pledge_reminders, which covers "you still owe something" nudges
    instead of "thanks, this went through" receipts.

    Silently does nothing for an anonymous gift (no member on it at all),
    a member with no email on file, or a member who's turned this off.
    """
    member = donation.member
    if not member or not member.email or not member.notify_giving_receipts:
        return False

    subject = "Thank you for your gift - Newlife AG"
    message = (
        f"Hi {member.first_name},\n\n"
        f"Thank you! Your gift of GHS {donation.amount} ({donation.get_donation_type_display()}) on "
        f"{donation.date:%b %d, %Y} has been recorded.\n\n"
        "You can view or print a receipt for this gift, or a full statement for any date range, "
        "any time from your dashboard."
    )
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [member.email], fail_silently=False)
    except Exception:
        logger.exception("Couldn't send a donation receipt email.")
        return False
    return True
