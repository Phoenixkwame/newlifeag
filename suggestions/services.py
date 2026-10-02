"""
Shared logic for marking a suggestion as reviewed - mirrors
prayer/services.py's mark_prayed_for and giving/services.py's
mark_donation_completed, so there's exactly one place that decides what
"reviewed" means and writes the audit trail for it.
"""

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone


def mark_reviewed(suggestion, *, user):
    """
    Marks a suggestion as reviewed. Idempotent - calling this again on an
    already-reviewed suggestion is a safe no-op that returns False, so a
    double-click on the staff button can't do anything strange, and
    reviewed_at never gets silently overwritten.
    """
    if suggestion.is_reviewed:
        return False

    suggestion.is_reviewed = True
    suggestion.reviewed_at = timezone.now()
    suggestion.save(update_fields=["is_reviewed", "reviewed_at"])

    content_type = ContentType.objects.get_for_model(suggestion)
    LogEntry.objects.log_action(
        user_id=user.pk,
        content_type_id=content_type.pk,
        object_id=suggestion.pk,
        object_repr=str(suggestion),
        action_flag=CHANGE,
        change_message="Marked as reviewed.",
    )
    return True
