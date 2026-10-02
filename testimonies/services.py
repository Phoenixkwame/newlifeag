"""
Shared logic for approving a testimony for the public Testimony Wall -
mirrors suggestions/services.py's mark_reviewed (and prayer/services.py's
mark_prayed_for, giving/services.py's mark_donation_completed), so there's
exactly one place that decides what "approved" means and writes the audit
trail for it.
"""

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone


def approve_testimony(testimony, *, user):
    """
    Marks a testimony as approved for the public wall. Idempotent - calling
    this again on an already-approved testimony is a safe no-op that returns
    False, so a double-click on the staff button can't do anything strange,
    and approved_at never gets silently overwritten.
    """
    if testimony.is_approved:
        return False

    testimony.is_approved = True
    testimony.approved_at = timezone.now()
    testimony.save(update_fields=["is_approved", "approved_at"])

    content_type = ContentType.objects.get_for_model(testimony)
    LogEntry.objects.log_action(
        user_id=user.pk,
        content_type_id=content_type.pk,
        object_id=testimony.pk,
        object_repr=str(testimony),
        action_flag=CHANGE,
        change_message="Approved for the public Testimony Wall.",
    )
    return True
