"""
Shared logic for moving a donation from pending to completed by hand (a
Treasurer confirming cash/mobile money was actually received). Used by both
the admin's bulk action (giving/admin.py) and the staff area's donation list
(staff/views.py), so there is exactly one code path that ever marks a gift
completed this way, and exactly one place that writes the audit trail.
"""

import calendar
import re
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType

from members.models import Member

from .models import Donation, GivingCampaign, RecurringGiving
from .notifications import notify_treasurers_of_pending_donation, send_donation_receipt_email


def mark_donation_completed(donation, *, user):
    """
    Marks a single pending donation as completed and logs who did it and
    when, in Django's own admin history, regardless of which screen it was
    done from.

    Only ever moves a gift from pending to completed - never touches one
    that's already completed or failed. Returns True if it made that change,
    False if the donation wasn't pending (nothing was touched).
    """
    if donation.status != Donation.Status.PENDING:
        return False

    donation.status = Donation.Status.COMPLETED
    donation.save(update_fields=["status"])

    content_type = ContentType.objects.get_for_model(Donation)
    LogEntry.objects.log_action(
        user_id=user.pk,
        content_type_id=content_type.pk,
        object_id=donation.pk,
        object_repr=str(donation),
        action_flag=CHANGE,
        change_message="Marked as completed via manual reconciliation (cash/mobile money confirmed in person).",
    )
    send_donation_receipt_email(donation)
    return True


# --- Text/SMS giving ---------------------------------------------------------
#
# A member without a smartphone or reliable data can give by texting the
# church's number, e.g. "GIVE 50" or "GIVE 100 BUILDING" to tag it to a
# specific campaign (see GivingCampaign.sms_keyword). This is deliberately
# SMS-based, not a true interactive USSD session (a USSD menu needs a live,
# stateful session with the telco that this app has no way to hold open) -
# a single text message in, a single confirmation text back out, no menu.
#
# Just like the public giving page's manual/pending fallback, this can only
# ever *record* a promised gift, never actually move money - there's no
# payment happening over SMS. It creates a pending Donation for a Treasurer
# to reconcile once the cash or mobile money transfer is confirmed some
# other way, and notifies them the same way any other pending gift does.

_GIVING_MESSAGE_PATTERN = re.compile(r"(?:GIVE|GIFT)\s+(\d+(?:\.\d{1,2})?)\s*([A-Za-z0-9]*)", re.IGNORECASE)


def parse_sms_giving_message(text):
    """
    Parses a "GIVE <amount> [campaign keyword]" text - e.g. "GIVE 50" or
    "give 100 building" (case-insensitive, keyword optional). Returns
    (amount, keyword) with keyword as "" (uppercased) when none was given,
    or (None, None) if the message doesn't look like a giving request at
    all - an unrelated text to the same number shouldn't create a donation.
    """
    if not text:
        return None, None
    match = _GIVING_MESSAGE_PATTERN.search(text.strip())
    if not match:
        return None, None
    try:
        amount = Decimal(match.group(1))
    except InvalidOperation:
        return None, None
    if amount <= 0:
        return None, None
    return amount, match.group(2).strip().upper()


def _digits_only(phone):
    return re.sub(r"\D", "", phone or "")


def find_member_by_phone(phone):
    """
    Matches an incoming SMS sender's number to a Member by comparing the
    last 9 digits - a Ghanaian mobile number's significant digits regardless
    of whether it arrives with a leading 0, a 233 country code, or a "+".
    A small in-Python loop rather than a database query, since phone numbers
    aren't stored consistently enough across records to filter reliably in
    SQL, and one congregation's member list is small enough for this to be
    a non-issue.
    """
    target = _digits_only(phone)[-9:]
    if not target:
        return None
    for member in Member.objects.exclude(phone="").only("id", "phone", "first_name", "last_name"):
        if _digits_only(member.phone)[-9:] == target:
            return member
    return None


def find_campaign_by_keyword(keyword):
    if not keyword:
        return None
    return GivingCampaign.objects.filter(is_active=True, sms_keyword__iexact=keyword).first()


def record_sms_gift(*, phone, message_text):
    """
    The whole text-giving flow, independent of whichever SMS provider's
    webhook payload shape calls into it (see giving/views.py's
    sms_giving_webhook), so it can be tested directly without faking an
    HTTP request from a specific aggregator. Returns the created Donation,
    or None if the message didn't parse as a giving request at all.
    """
    amount, keyword = parse_sms_giving_message(message_text)
    if amount is None:
        return None

    donation = Donation.objects.create(
        member=find_member_by_phone(phone),
        amount=amount,
        campaign=find_campaign_by_keyword(keyword),
        donation_type=Donation.DonationType.OFFERING,
        payment_reference=f"SMS-{uuid.uuid4().hex[:12]}",
        status=Donation.Status.PENDING,
    )
    notify_treasurers_of_pending_donation(donation)
    return donation


# --- Recurring giving ---------------------------------------------------------

def _add_one_month(d):
    """
    Same month-end clamping approach as events/services.py's _add_months
    (kept as its own copy here since each app's services.py is meant to
    stand on its own in this project) - e.g. Jan 31 lands on Feb 28/29
    instead of raising, since plain timedelta math can't add "a month".
    """
    month_index = d.month - 1 + 1
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


def members_with_completed_giving(year):
    """
    Members with at least one completed gift dated in `year` - the audience
    for the annual statement email (see giving/notifications.py's
    send_annual_giving_statement and the send_giving_statements management
    command), instead of a Treasurer/Pastor downloading each member's
    statement one at a time from staff/views.py's annual_giving_statement
    page. Anonymous gifts (no member on the donation) are excluded - there's
    no one to email.
    """
    return (
        Member.objects.filter(donations__status=Donation.Status.COMPLETED, donations__date__year=year)
        .distinct()
        .order_by("last_name", "first_name")
    )


def lapsed_recurring_gifts(*, min_reminders=2, campus=None):
    """
    Active recurring giving commitments that have been reminded at least
    `min_reminders` times with zero completed donations recorded from that
    member since the commitment was set up - a quiet sign the payment
    method or giving habit lapsed, worth a gentle personal follow-up rather
    than just another automated reminder email. `min_reminders` defaults to
    2 so a member simply running a few days behind on this cycle's
    reminder isn't flagged as if they've stopped giving altogether - it
    takes a second unanswered reminder to surface here.

    Deliberately checks for *any* completed donation since the commitment
    was created, not one tagged to the same campaign or matching the exact
    amount - the point is whether this member is giving at all, not
    whether they're giving to precisely what they committed to.

    campus, when given, restricts this to commitments from members of that
    campus (see staff/services.py's scope_by_member_campus - RecurringGiving
    has no campus field of its own, so this always scopes via the member).
    """
    candidates = RecurringGiving.objects.filter(
        is_active=True, reminder_count__gte=min_reminders
    ).select_related("member", "campaign")
    if campus is not None:
        candidates = candidates.filter(member__campus=campus)

    lapsed = []
    for recurring in candidates:
        has_given_since = Donation.objects.filter(
            member=recurring.member, status=Donation.Status.COMPLETED, date__gte=recurring.created_at
        ).exists()
        if not has_given_since:
            lapsed.append(recurring)
    return lapsed


def advance_recurring_giving_due_date(recurring):
    """
    Moves next_due_date forward by one period *from itself*, not from
    today - so a reminder sent a few days late (e.g. the daily command
    didn't run for a day or two) doesn't shift every later due date along
    with it. Called by the send_recurring_giving_reminders management
    command right after a reminder goes out.
    """
    if recurring.frequency == RecurringGiving.Frequency.WEEKLY:
        recurring.next_due_date = recurring.next_due_date + timedelta(days=7)
    else:
        recurring.next_due_date = _add_one_month(recurring.next_due_date)
    recurring.save(update_fields=["next_due_date"])
