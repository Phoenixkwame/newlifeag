"""
Shared logic for the follow-up pipeline, pulled out of staff/views.py the
same way checkin/services.py and giving/services.py's mark_donation_completed
are - so a stage change or a logged contact attempt always happens the same
way regardless of which screen triggers it.
"""

import re
from datetime import timedelta

from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from members.models import Member

from .models import ContactAttempt, FollowUp


def _digits_only(phone):
    return re.sub(r"\D", "", phone or "")


def find_or_create_guest(*, first_name, last_name, phone="", email=""):
    """
    Looks up an existing Member by phone (last 9 digits, same matching
    approach as giving/services.py's find_member_by_phone - kept as its own
    copy here since each app's services.py stands on its own in this
    project) or by email, so a repeat visitor filling out the public connect
    card (see followup/views.py's connect_card) a second time doesn't create
    a duplicate record. Falls back to creating a brand new Member when
    neither matches anything on file.
    """
    member = None
    target = _digits_only(phone)[-9:]
    if target:
        for candidate in Member.objects.exclude(phone=""):
            if _digits_only(candidate.phone)[-9:] == target:
                member = candidate
                break
    if member is None and email:
        member = Member.objects.filter(email__iexact=email).first()
    if member is None:
        member = Member.objects.create(first_name=first_name, last_name=last_name, phone=phone, email=email)
    return member


def start_follow_up(member, *, user=None):
    """
    Begins following up with a member. Idempotent - Member.follow_up is a
    OneToOneField, so calling this again for someone already being followed
    up with just returns their existing FollowUp rather than erroring.

    Only logs to the staff activity log (see staff/views.py's activity_log)
    the first time - `_created` guards against a noisy duplicate entry every
    time someone re-clicks "Start Follow-Up" on a member already being
    followed up with. `user` is optional so this keeps working from any
    caller that doesn't have (or care about) attribution - no entry is
    logged when it's omitted.
    """
    follow_up, created = FollowUp.objects.get_or_create(member=member)
    if created and user is not None:
        LogEntry.objects.log_action(
            user_id=user.pk,
            content_type_id=ContentType.objects.get_for_model(follow_up).pk,
            object_id=follow_up.pk,
            object_repr=str(follow_up),
            action_flag=ADDITION,
            change_message=f"Started following up with {member}.",
        )
    return follow_up


def log_contact(follow_up, *, user, note=""):
    """Records one contact attempt - never edits or removes a previous one."""
    return ContactAttempt.objects.create(follow_up=follow_up, contacted_by=user, note=note)


def advance_stage(follow_up, stage):
    """
    Moves a follow-up to a new stage. Returns False (and changes nothing)
    for a stage value that isn't one of FollowUp.Stage's actual choices,
    rather than saving bad data.
    """
    if stage not in FollowUp.Stage.values:
        return False
    follow_up.stage = stage
    follow_up.save(update_fields=["stage"])
    return True


# Default staleness window for stale_follow_ups below - long enough that
# someone contacted earlier in the week isn't flagged, short enough that a
# visitor genuinely being missed gets caught before too long.
STALE_FOLLOW_UP_DAYS = 7


def stale_follow_ups(days=STALE_FOLLOW_UP_DAYS):
    """
    Active follow-ups (excluding JOINED and INACTIVE, which are already
    resolved - there's nothing left to chase on either of those) that have
    gone at least `days` days since the last logged ContactAttempt, or since
    their first_visit_date for someone never yet contacted at all - so
    nobody still mid-pipeline quietly goes untouched. Returns FollowUp
    instances, oldest-touched (or oldest-never-touched) first, same
    "worst first" convention as members.services.absentee_members.
    """
    cutoff = timezone.localdate() - timedelta(days=days)
    dated = []
    for follow_up in (
        FollowUp.objects.exclude(stage__in=[FollowUp.Stage.JOINED, FollowUp.Stage.INACTIVE])
        .select_related("member")
        .prefetch_related("contact_attempts")
    ):
        last_contact = follow_up.last_contacted_at
        reference_date = last_contact.date() if last_contact else follow_up.first_visit_date
        if reference_date <= cutoff:
            dated.append((reference_date, follow_up))
    dated.sort(key=lambda pair: pair[0])
    return [follow_up for _, follow_up in dated]
