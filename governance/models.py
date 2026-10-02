from django.conf import settings
from django.db import models
from django.utils import timezone

from members.models import Member


class Meeting(models.Model):
    """
    A leadership (Deacons/Elders board) meeting record - agenda, minutes,
    and who attended. Pastor-only, same governance-only reasoning as
    CareRequest and MemberNote elsewhere in this project - no Usher or
    Treasurer grant ever touches this model (see setup_groups.py's
    PASTOR_MODELS).
    """

    date = models.DateField(default=timezone.localdate)
    title = models.CharField(max_length=200, blank=True, help_text='e.g. "Monthly Elders Meeting" - optional.')
    attendees = models.ManyToManyField(Member, blank=True, related_name="meetings_attended")
    agenda = models.TextField(blank=True)
    minutes = models.TextField(blank=True, help_text="What was discussed and decided.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Who recorded these minutes.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.title} ({self.date})" if self.title else f"Meeting on {self.date}"

    @property
    def open_action_item_count(self):
        return self.action_items.filter(is_done=False).count()


class ActionItem(models.Model):
    """
    A single follow-up task assigned out of a Meeting, with an owner and a
    due date - so a decision made in a meeting doesn't just sit in the
    minutes text with nobody actually accountable for it.
    """

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="action_items")
    description = models.CharField(max_length=255)
    owner = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="governance_action_items"
    )
    due_date = models.DateField(null=True, blank=True)
    is_done = models.BooleanField(default=False)
    completed_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["is_done", "due_date"]

    def __str__(self):
        return self.description

    @property
    def is_overdue(self):
        return bool(self.due_date) and not self.is_done and self.due_date < timezone.localdate()

    def mark_done(self, done):
        """Sets is_done and stamps/clears completed_at accordingly - shared by every path that toggles this."""
        self.is_done = done
        self.completed_at = timezone.localdate() if done else None
        self.save(update_fields=["is_done", "completed_at"])
