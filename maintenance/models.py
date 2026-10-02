from django.db import models
from django.utils import timezone

from members.models import Member


class MaintenanceRequest(models.Model):
    """
    A facility issue reported by a member or staff - a broken chair, a leak,
    anything needing repair. Optionally linked to a booking.Resource, when
    the issue is with a specific room/vehicle/equipment already tracked
    there, but doesn't have to be (e.g. "the parking lot light is out").
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        DONE = "done", "Done"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(
        max_length=200, blank=True, help_text="Where the issue is, e.g. 'Main Sanctuary, back row'."
    )
    resource = models.ForeignKey(
        "booking.Resource",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_requests",
        help_text="Link to a specific room/vehicle, if applicable.",
    )
    # Separate from `resource` above - a tracked Equipment item (see the
    # equipment app) is checked out/in and has its own condition field,
    # unlike a booking.Resource which is reserved for a time block. Linking
    # here is what gives an Equipment item its "maintenance history" rather
    # than needing a second ticket system of its own.
    equipment = models.ForeignKey(
        "equipment.Equipment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_requests",
        help_text="Link to a specific tracked equipment item, if applicable.",
    )
    reported_by = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="maintenance_requests"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["status", "-created_at"]

    def __str__(self):
        return self.title

    def mark_status(self, status):
        """Sets the status and stamps/clears resolved_at accordingly - shared by every path that changes status."""
        self.status = status
        self.resolved_at = timezone.now() if status == self.Status.DONE else None
        self.save(update_fields=["status", "resolved_at"])
