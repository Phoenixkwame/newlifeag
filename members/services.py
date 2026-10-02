"""
Shared logic for the member profile's free-text skills field - used by
MemberProfileForm (a member editing their own profile), so skill
creation/matching only ever happens in one place. Mirrors
sermons/services.py's set_sermon_tags.
"""

import re
import secrets
from datetime import timedelta

from django.utils import timezone

from giving.services import find_member_by_phone

from .models import Attendance, Group, Member, ServingAssignment, Skill
from .notifications import notify_leader_of_declined_assignment


def set_member_skills(member, skills_input):
    """
    Parses a comma-separated string of skill names (e.g. "Music, Sound
    Engineering") into real Skill rows - matching an existing skill
    case-insensitively rather than creating a near-duplicate ("music" vs
    "Music"), and creating a new one otherwise - then sets them as the
    member's skills. An empty/blank input clears every skill from the
    member, same as unchecking every box would.
    """
    names = [name.strip() for name in skills_input.split(",") if name.strip()]
    skills = []
    for name in names:
        skill = Skill.objects.filter(name__iexact=name).first()
        if skill is None:
            skill = Skill.objects.create(name=name)
        skills.append(skill)
    member.skills.set(skills)


def get_or_create_calendar_token(member):
    """
    Lazily generates and stores a long random token the first time a
    member's personal calendar feed is requested (see members/views.py's
    member_calendar_feed) - this token, not a login session, is what
    authenticates a calendar subscription URL, since a calendar app (Google
    Calendar, Apple Calendar, Outlook) fetches it on its own schedule with
    no session cookie or credentials attached.
    """
    if not member.calendar_token:
        member.calendar_token = secrets.token_urlsafe(24)
        member.save(update_fields=["calendar_token"])
    return member.calendar_token


def regenerate_calendar_token(member):
    """
    Issues a brand-new token, immediately invalidating the old subscription
    URL - for a member who's shared their calendar link somewhere they no
    longer want it working, the same "burn the old one" reasoning as
    rotating any other leaked credential.
    """
    member.calendar_token = secrets.token_urlsafe(24)
    member.save(update_fields=["calendar_token"])
    return member.calendar_token


def bulk_set_household_campus(household, campus):
    """
    Sets every current member of the household to the same campus in one
    query - the "our whole family just switched to the new branch" case, so
    staff don't have to open each member's own edit form one at a time. Uses
    a bulk .update() rather than looping and calling .save() per member,
    since there's nothing per-member happening here (no signals this project
    relies on for Member.campus changes). Returns how many members were
    updated, so the calling view can report it back.
    """
    return household.members.update(campus=campus)


def bulk_sync_household_phone(household):
    """
    Copies the household's own phone number onto every member who doesn't
    already have a personal one on file - a household often shares one
    landline/mobile number, and this saves re-typing it once per family
    member. Deliberately only fills in a blank phone rather than overwriting
    one a member already has of their own, since that could be a different,
    more personal number they specifically want on file. Does nothing (and
    returns 0) if the household itself has no phone number to copy.
    """
    if not household.phone:
        return 0
    return household.members.filter(phone="").update(phone=household.phone)


def bulk_set_household_active(household, is_active):
    """
    Marks every member of the household active or inactive at once - the
    "this whole family moved away" (or "they're back!") case. Mirrors what
    toggling is_active on a single Member already means elsewhere in the
    project (e.g. absentee_members only ever considers active members), just
    applied to everyone in the household in one query instead of one at a
    time. Returns how many members were updated.
    """
    return household.members.update(is_active=is_active)


def suggested_groups_for(member):
    """
    Groups whose interest_skills overlap with what the member has listed on
    their own profile (see set_member_skills above), excluding any group
    they're already an active member of - the matching behind the interest
    survey's "Suggested for you" list. Returns an empty queryset for a
    member with no skills listed yet, rather than every group tagged with
    anything (there's nothing to match against).
    """
    if not member.skills.exists():
        return Group.objects.none()

    joined_group_ids = member.memberships.filter(left_date__isnull=True).values_list("group_id", flat=True)
    return (
        Group.objects.filter(interest_skills__in=member.skills.all())
        .exclude(id__in=joined_group_ids)
        .distinct()
        .order_by("name")
    )


# Attendance streaks / engagement badges - a lightweight, encouraging
# counterpart to absentee_members below: instead of flagging who's fallen
# off, this celebrates who's been consistently showing up. Weeks (not
# individual dates) are the unit, same "any present Attendance row counts,
# a Sunday service or a small group/ministry meeting" scope as
# absentee_members, so someone who makes their small group but misses a
# Sunday still keeps their streak alive.
STREAK_BADGES = [
    (52, "1 Year Streak"),
    (26, "6 Month Streak"),
    (12, "12 Week Streak"),
    (8, "8 Week Streak"),
    (4, "4 Week Streak"),
]


def attendance_streak_weeks(member, *, today=None):
    """
    How many consecutive weeks in a row, counting backward from this week,
    the member has attended at least one present Attendance row. The
    current week still counts as soon as it has one attendance row in it,
    even if the week isn't over yet - so a streak doesn't look broken on a
    Tuesday just because Sunday's service hasn't happened. Breaks at the
    first gap week and returns immediately - a member who attended 10 weeks
    ago after a 3-week gap doesn't get credit for that older streak.
    """
    today = today or timezone.localdate()
    attended_weeks = {
        d - timedelta(days=d.weekday())
        for d in member.attendance_records.filter(present=True).values_list("date", flat=True)
    }
    if not attended_weeks:
        return 0

    streak = 0
    week_start = today - timedelta(days=today.weekday())
    while week_start in attended_weeks:
        streak += 1
        week_start -= timedelta(days=7)
    return streak


def streak_badge(streak_weeks):
    """The highest badge earned by a given streak length, or None if it hasn't reached the first threshold yet."""
    for threshold, label in STREAK_BADGES:
        if streak_weeks >= threshold:
            return label
    return None


# Default lookback window for absentee_members below - long enough that
# missing one Sunday (illness, travel) doesn't flag anyone, but short
# enough that a real drop-off gets caught while a check-in still helps.
ABSENTEE_WEEKS = 3


def absentee_members(weeks=ABSENTEE_WEEKS, campus=None):
    """
    Active members who haven't shown up to anything - a Sunday service or a
    small group/ministry meeting, see Attendance.present - in the last
    `weeks` weeks, so Ushers/Pastors can reach out before someone drifts
    away unnoticed. Deliberately excludes anyone who joined more recently
    than the window itself: a brand new member hasn't had a fair chance to
    attend yet, and flagging them the week they signed up would just be
    noise. Returns a list of (member, last_attended_date) pairs, a member
    who has never once attended shown first (last_attended_date is then
    None), followed by everyone else oldest-last-seen first.

    campus, when given, restricts the candidates to that campus (see
    staff/services.py's scope_members - same plain filter, no fallback,
    since a Member's own campus field is authoritative for them).
    """
    cutoff = timezone.localdate() - timedelta(weeks=weeks)
    candidates = (
        Member.objects.filter(is_active=True, date_joined__lte=cutoff)
        .exclude(attendance_records__present=True, attendance_records__date__gte=cutoff)
        .distinct()
    )
    if campus is not None:
        candidates = candidates.filter(campus=campus)

    results = []
    for member in candidates:
        last_attended = (
            member.attendance_records.filter(present=True).order_by("-date").values_list("date", flat=True).first()
        )
        results.append((member, last_attended))

    # Longest-absent (or never-attended, sorted last-first via None) shown
    # first - a plain sort with None last so it doesn't blow up comparing
    # None to a date.
    results.sort(key=lambda pair: (pair[1] is not None, pair[1]))
    return results


# --- SMS-based check-in/attendance -------------------------------------------
#
# A member without a smartphone or reliable data can check themselves into
# today's service by texting a single keyword ("IN", "HERE", or "PRESENT")
# to the church's number - same fallback-for-members-without-data reasoning
# as giving/services.py's SMS text-giving flow, and directly reuses that
# app's phone-matching helper rather than duplicating it (this is the one
# place in the project that deliberately shares a services.py helper across
# apps, since the phone-matching logic is genuinely identical either way).

_CHECKIN_MESSAGE_PATTERN = re.compile(r"^\s*(IN|HERE|PRESENT)\s*$", re.IGNORECASE)


def is_sms_checkin_message(text):
    """True if the text is (only) one of the recognized check-in keywords - an unrelated text isn't a check-in attempt at all."""
    return bool(text and _CHECKIN_MESSAGE_PATTERN.match(text.strip()))


def record_sms_checkin(*, phone, message_text):
    """
    Records general (non-event, non-group) attendance for today for the
    member matching the sender's phone - the same "general attendance" shape
    members/views.py's mark_attendance creates (event=None, group=None).

    Unlike SMS giving, there's no meaningful "anonymous" attendance record
    to fall back to when the phone doesn't match anyone - a promised gift
    can be reconciled later by hand, but there's no one to check in. So this
    returns a (attendance, error) pair instead of a single value: `error` is
    None on success, "not_a_checkin_message" if the text wasn't one of the
    recognized keywords at all (ignore silently, same as an unrelated text
    to the giving number), or "no_matching_member" if it was a check-in
    attempt but no member's phone matches (worth telling the sender, unlike
    the first case).
    """
    if not is_sms_checkin_message(message_text):
        return None, "not_a_checkin_message"

    member = find_member_by_phone(phone)
    if member is None:
        return None, "no_matching_member"

    attendance, _ = Attendance.objects.update_or_create(
        member=member,
        date=timezone.localdate(),
        event=None,
        group=None,
        defaults={"present": True, "campus": member.campus},
    )
    return attendance, None


# --- SMS-based serving assignment confirm/decline ----------------------------
#
# A serving-team member can reply YES/CONFIRM or NO/DECLINE to their own
# reminder text (see members/notifications.py's send_serving_reminder) -
# same "the reminder is one-way otherwise" fallback reasoning as SMS
# check-in above, and reuses the same phone-matching helper.

_CONFIRM_MESSAGE_PATTERN = re.compile(r"^\s*(YES|Y|CONFIRM|CONFIRMED)\s*$", re.IGNORECASE)
_DECLINE_MESSAGE_PATTERN = re.compile(r"^\s*(NO|N|DECLINE|DECLINED|CAN'?T MAKE IT)\s*$", re.IGNORECASE)


def record_sms_serving_response(*, phone, message_text):
    """
    Matches a YES/NO-style reply to the sender's *nearest upcoming, still-
    pending* ServingAssignment - there's no way for a plain "YES" text to
    say which assignment it's about, so this assumes it's about whichever
    one is coming up soonest, which is also the one the member was just
    reminded about (see send_serving_reminders' 3-day reminder window).

    Returns (assignment, error): error is None on success,
    "not_a_response_message" if the text wasn't a recognized YES/NO reply at
    all (ignore silently, same as an unrelated text to any of this
    project's other SMS keywords), "no_matching_member" if it was a
    response but no member's phone matches, or "no_pending_assignment" if
    the member matched but has nothing upcoming still awaiting a reply
    (already responded, or nothing scheduled at all).
    """
    text = (message_text or "").strip()
    if _CONFIRM_MESSAGE_PATTERN.match(text):
        status = ServingAssignment.ConfirmationStatus.CONFIRMED
    elif _DECLINE_MESSAGE_PATTERN.match(text):
        status = ServingAssignment.ConfirmationStatus.DECLINED
    else:
        return None, "not_a_response_message"

    member = find_member_by_phone(phone)
    if member is None:
        return None, "no_matching_member"

    assignment = (
        ServingAssignment.objects.filter(
            member=member,
            confirmation_status=ServingAssignment.ConfirmationStatus.PENDING,
            date__gte=timezone.localdate(),
        )
        .select_related("group")
        .order_by("date")
        .first()
    )
    if assignment is None:
        return None, "no_pending_assignment"

    assignment.confirmation_status = status
    assignment.save(update_fields=["confirmation_status"])

    if status == ServingAssignment.ConfirmationStatus.DECLINED:
        notify_leader_of_declined_assignment(assignment)

    return assignment, None
