"""
Shared logic for marking a member's progress through the discipleship
pathway - used by staff/views.py's member detail page, so there is exactly
one code path that ever changes a MemberPathwayProgress row.
"""

from django.utils import timezone

from .models import MemberPathwayProgress, PathwayStep


def progress_for_member(member):
    """
    Every pathway step, in order, paired with that member's progress on it
    (or None if they haven't started it) - so the caller never has to worry
    about a missing MemberPathwayProgress row meaning "not completed" versus
    an actual row that happens to have no completed_date yet; both render
    identically as "not completed" here.
    """
    progress_by_step_id = {p.step_id: p for p in member.pathway_progress.all()}
    return [(step, progress_by_step_id.get(step.id)) for step in PathwayStep.objects.all()]


def mark_step_complete(member, step, *, user):
    """Marks a step complete today, recording who marked it. Idempotent - completing an already-completed step just refreshes who/when."""
    progress, _created = MemberPathwayProgress.objects.get_or_create(member=member, step=step)
    progress.completed_date = timezone.localdate()
    progress.marked_by = user
    progress.save(update_fields=["completed_date", "marked_by"])
    return progress


def mark_step_incomplete(member, step):
    """
    Undoes a step marked complete by mistake - clears completed_date rather
    than deleting the row (no staff role is ever granted delete permission
    on anything in this app), so who most recently marked/unmarked it stays
    on record via marked_by.
    """
    progress = MemberPathwayProgress.objects.filter(member=member, step=step).first()
    if progress is None:
        return False
    progress.completed_date = None
    progress.save(update_fields=["completed_date"])
    return True
