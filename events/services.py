"""
Volunteer sign-up logic that needs to be safe under concurrent requests -
pulled out of the view so the locking behaviour can be tested directly,
independent of form validation or HTTP plumbing. Also home to the
recurring-event generator (see generate_recurring_occurrences below).
"""

import calendar
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from giving.services import find_member_by_phone
from members.models import Attendance, ServingAssignment

from .models import Event, EventRegistration, EventTicket, VolunteerSignup, VolunteerSlot, VolunteerWaitlistEntry
from .notifications import send_waitlist_spot_opened_notification


class SlotFullError(Exception):
    """Raised when a volunteer slot has no spots left at the moment of signup."""


class TicketFullError(Exception):
    """Raised when an event ticket type has no capacity left at the moment of registration."""


def register_for_ticket(*, ticket_id, member):
    """
    Creates an EventRegistration for the given ticket/member.

    Same race-condition-safe pattern as sign_up_for_slot above: locks the
    ticket's row and re-checks capacity inside the transaction, so two people
    racing for the very last spot can't both succeed. A registration that's
    already pending or completed for this member/ticket is returned as-is
    (not a new claim on capacity) rather than rejected or duplicated - only a
    previously FAILED attempt (payment never went through) lets the member
    try again for a fresh spot.

    Returns (registration, created), same shape as get_or_create(). Raises
    TicketFullError if the ticket has no spots remaining once locked.
    """
    with transaction.atomic():
        locked_ticket = EventTicket.objects.select_for_update().get(pk=ticket_id)

        EventRegistration.objects.filter(
            ticket=locked_ticket, status=EventRegistration.Status.PENDING,
            expires_at__lte=timezone.now(),
        ).update(status=EventRegistration.Status.FAILED)

        existing = (
            EventRegistration.objects.filter(ticket=locked_ticket, member=member)
            .exclude(status=EventRegistration.Status.FAILED)
            .first()
        )
        if existing is not None:
            return existing, False

        if locked_ticket.is_full:
            raise TicketFullError(f"{locked_ticket} has no spots remaining.")

        return EventRegistration.objects.create(
            ticket=locked_ticket, member=member, amount_due=locked_ticket.price,
        ), True


def sign_up_for_slot(*, slot_id, member):
    """
    Creates a VolunteerSignup for the given slot/member.

    Locks the slot's row and re-checks its capacity *inside* the
    transaction, so two requests racing for the very last spot can't both
    succeed - whichever arrives second waits for the lock, then sees the
    first signup already counted, and gets SlotFullError instead of
    over-filling the slot.

    Note: SQLite doesn't support row locking - select_for_update() is a
    documented no-op there - so this only fully closes the race once
    deployed on PostgreSQL, which the README already recommends before real
    congregation use. On SQLite it still behaves correctly for any request
    that isn't truly simultaneous, which covers ordinary use in development.

    Returns (signup, created), same shape as get_or_create(). Raises
    SlotFullError if the slot has no spots remaining once locked.
    """
    with transaction.atomic():
        locked_slot = VolunteerSlot.objects.select_for_update().get(pk=slot_id)

        # Already signed up? That's a no-op, not a new claim on capacity -
        # otherwise re-submitting after a full slot would wrongly reject
        # someone who already has the spot.
        existing = VolunteerSignup.objects.filter(slot=locked_slot, member=member).first()
        if existing is not None:
            return existing, False

        if locked_slot.spots_remaining <= 0:
            raise SlotFullError(f"{locked_slot} has no spots remaining.")

        return VolunteerSignup.objects.create(slot=locked_slot, member=member), True


def join_waitlist(*, slot_id, member):
    """
    Adds `member` to the given slot's waitlist - called from event_detail
    right after sign_up_for_slot raises SlotFullError, so a member turned
    away from a full slot has somewhere to land instead of just an error
    message. Idempotent like sign_up_for_slot: already on the waitlist
    returns the existing entry rather than erroring or duplicating it.
    Returns (entry, created).
    """
    return VolunteerWaitlistEntry.objects.get_or_create(slot_id=slot_id, member=member)


def cancel_volunteer_signup(*, signup_id, member):
    """
    Cancels `member`'s own VolunteerSignup, then - inside the same locked
    transaction sign_up_for_slot uses, so a promotion here can never race
    against someone else signing up for the same freshly-opened spot -
    promotes the earliest still-waiting VolunteerWaitlistEntry for that slot
    (if any) into a real VolunteerSignup and removes it from the waitlist,
    notifying that member the spot is now theirs (see
    events/notifications.py's send_waitlist_spot_opened_notification).

    Returns (cancelled, promoted_signup): cancelled is False (a no-op) if
    this signup doesn't exist or belongs to someone else - never lets a
    member cancel another member's signup by guessing an id.
    promoted_signup is the newly created VolunteerSignup if a waitlisted
    member was promoted, or None if the waitlist was empty.
    """
    with transaction.atomic():
        signup = VolunteerSignup.objects.filter(id=signup_id, member=member).select_related("slot").first()
        if signup is None:
            return False, None

        slot_id = signup.slot_id
        signup.delete()

        locked_slot = VolunteerSlot.objects.select_for_update().get(pk=slot_id)
        promoted_signup = None
        if locked_slot.spots_remaining > 0:
            next_in_line = VolunteerWaitlistEntry.objects.filter(slot=locked_slot).order_by("joined_at").first()
            if next_in_line is not None:
                promoted_signup = VolunteerSignup.objects.create(slot=locked_slot, member=next_in_line.member)
                next_in_line.delete()

    if promoted_signup is not None:
        send_waitlist_spot_opened_notification(promoted_signup)

    return True, promoted_signup


def conflicting_commitments_on(member, on_date, *, exclude_event_id=None, exclude_assignment_id=None):
    """
    Every place `member` is already committed to serve on `on_date`, across
    both scheduling systems this project has: ServingAssignment's recurring
    weekly team lineups (members/models.py) and VolunteerSignup's one-off
    event slots (above). Returns a list of human-readable strings a calling
    view shows via django.contrib.messages - this is a warning, not a hard
    block. A member is sometimes legitimately serving in more than one
    place on the same day (ushering AND running media, say), so the actual
    judgment call is left to whoever's doing the scheduling; this just makes
    sure they see the double-booking before confirming it rather than
    finding out on the day itself.

    `exclude_event_id`/`exclude_assignment_id` leave out one specific
    volunteer signup's event or one specific serving assignment - used when
    checking right after that exact commitment was just created, so it
    doesn't show up as a "conflict" with itself.
    """
    conflicts = []

    assignments = ServingAssignment.objects.filter(member=member, date=on_date).select_related("group")
    if exclude_assignment_id is not None:
        assignments = assignments.exclude(id=exclude_assignment_id)
    for assignment in assignments:
        conflicts.append(
            f"Heads up: {member} is already scheduled to serve as {assignment.role} for "
            f"{assignment.group} on {on_date:%b %d, %Y}."
        )

    signups = VolunteerSignup.objects.filter(
        member=member, slot__event__start_datetime__date=on_date
    ).select_related("slot", "slot__event")
    if exclude_event_id is not None:
        signups = signups.exclude(slot__event_id=exclude_event_id)
    for signup in signups:
        conflicts.append(
            f"Heads up: {member} already signed up to volunteer as {signup.slot.role_needed} for "
            f"{signup.slot.event} on {on_date:%b %d, %Y}."
        )

    return conflicts


def _add_months(dt, months):
    """
    Adds whole calendar months to a datetime, clamping the day so e.g. Jan
    31 + 1 month lands on Feb 28/29 instead of raising - plain timedelta
    math can't do this since months aren't a fixed number of days.
    """
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def generate_recurring_occurrences(parent_event, *, frequency, count):
    """
    Creates up to `count - 1` further Event rows after parent_event, spaced
    weekly or monthly, copying its title/description/type/location and
    linking each one back via series_parent - so a recurring service shows
    up as real, independent events (each with its own RSVPs and volunteer
    slots), not one event that merely "repeats" in the UI.

    Returns the list of newly-created Event objects (not including
    parent_event itself, which the caller already has).
    """
    if frequency not in (Event.Recurrence.WEEKLY, Event.Recurrence.MONTHLY):
        return []

    duration = None
    if parent_event.end_datetime:
        duration = parent_event.end_datetime - parent_event.start_datetime

    created = []
    current_start = parent_event.start_datetime
    for _ in range(max(count - 1, 0)):
        if frequency == Event.Recurrence.WEEKLY:
            current_start = current_start + timedelta(weeks=1)
        else:
            current_start = _add_months(current_start, 1)

        current_end = current_start + duration if duration else None
        created.append(
            Event.objects.create(
                title=parent_event.title,
                description=parent_event.description,
                event_type=parent_event.event_type,
                start_datetime=current_start,
                end_datetime=current_end,
                location=parent_event.location,
                campus=parent_event.campus,
                series_parent=parent_event,
            )
        )
    return created


def check_in_via_qr(*, event, phone, service_time=None):
    """
    Marks the member matching `phone` present for `event` - the destination
    of that event's QR check-in page (events/views.py's event_qr_checkin,
    linked from a QR code staff can display or print - see
    staff/templates/staff/event_detail.html). Reuses the same
    phone-matching helper as SMS-based check-in
    (members/services.py's record_sms_checkin) rather than duplicating it -
    "which member is this phone number" is the same problem either way,
    just reached from a scanned link instead of a text message.

    Unlike SMS check-in's *general* attendance (no specific event), this
    always ties the record to `event` - the whole point of a QR code
    printed for one specific service/event - so it can never collide with a
    general check-in row for the same member/date (see Attendance.Meta's
    unique_together, which includes event). `service_time` is optional and
    only ever meaningful for a multi-service event (see
    events.EventServiceTime) - it's not part of the update_or_create lookup
    itself, just tagged onto the same row, so scanning the same event's code
    twice in one day still can't create two rows for one member.

    Returns (attendance, error): error is None on success, or
    "no_matching_member" if the phone doesn't match anyone on file.
    """
    member = find_member_by_phone(phone)
    if member is None:
        return None, "no_matching_member"

    attendance, _ = Attendance.objects.update_or_create(
        member=member,
        date=event.start_datetime.date(),
        event=event,
        group=None,
        defaults={"present": True, "campus": event.campus or member.campus, "service_time": service_time},
    )
    return attendance, None
