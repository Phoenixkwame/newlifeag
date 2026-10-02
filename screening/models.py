from django.db import models
from django.utils import timezone

from members.models import Member


class BackgroundCheck(models.Model):
    """
    A background-check record for a volunteer in a sensitive role (children's
    ministry, ushering, and the like) - tracked here rather than as a single
    field on Member so a member's history of past checks/renewals is kept,
    not just their current status.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CLEARED = "cleared", "Cleared"
        FLAGGED = "flagged", "Flagged"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="background_checks")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    submitted_date = models.DateField(null=True, blank=True, help_text="When the check was requested/submitted.")
    cleared_date = models.DateField(null=True, blank=True, help_text="When the check came back cleared.")
    expiry_date = models.DateField(null=True, blank=True, help_text="When this clearance needs to be renewed.")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.member} - {self.get_status_display()}"

    @property
    def is_expired(self):
        return bool(self.expiry_date) and self.expiry_date < timezone.localdate()

    @property
    def is_expiring_soon(self):
        """Within 30 days of expiring, but not already expired - used to flag upcoming renewals."""
        if not self.expiry_date or self.is_expired:
            return False
        return self.expiry_date <= timezone.localdate() + timezone.timedelta(days=30)


class VolunteerTraining(models.Model):
    """
    A required training completed (or in progress) by a volunteer for a
    specific role - e.g. Child Safety training before serving in Children's
    Ministry, First Aid for an event first-responder team. One record per
    training per member, the same shape as BackgroundCheck above, so a
    member's whole training history is kept rather than a single "trained:
    yes/no" flag - and the same expiring-soon/expired convention, for
    trainings (like a first-aid certificate) that need periodic renewal.
    """

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="trainings")
    training_name = models.CharField(max_length=150, help_text='e.g. "Child Safety", "First Aid", "Safe Sanctuary".')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    completed_date = models.DateField(null=True, blank=True, help_text="When this training was completed.")
    expiry_date = models.DateField(
        null=True, blank=True, help_text="When this training needs to be renewed, if it expires at all."
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.member} - {self.training_name} ({self.get_status_display()})"

    @property
    def is_expired(self):
        return bool(self.expiry_date) and self.expiry_date < timezone.localdate()

    @property
    def is_expiring_soon(self):
        """Within 30 days of expiring, but not already expired - used to flag upcoming renewals."""
        if not self.expiry_date or self.is_expired:
            return False
        return self.expiry_date <= timezone.localdate() + timezone.timedelta(days=30)
