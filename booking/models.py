from django.db import models

from members.models import Campus, Member


class Resource(models.Model):
    """
    A bookable room, vehicle, or piece of equipment - deliberately separate
    from events.models.Event (an event happens somewhere; a resource is the
    somewhere/something being used). One Resource can be booked by many
    ResourceBookings, at non-overlapping times (see ResourceBooking's
    conflict check in booking/services.py).
    """

    class ResourceType(models.TextChoices):
        ROOM = "room", "Room"
        VEHICLE = "vehicle", "Vehicle"
        EQUIPMENT = "equipment", "Equipment"

    name = models.CharField(max_length=150, help_text="e.g. 'Main Sanctuary', 'Church Van', 'Projector #2'.")
    resource_type = models.CharField(max_length=20, choices=ResourceType.choices, default=ResourceType.ROOM)
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resources",
        help_text="Which campus this resource belongs to (only relevant once there's more than one).",
    )
    notes = models.TextField(blank=True, help_text="Capacity, location, anything staff should know before booking.")
    # Retired rather than deleted, same reasoning as GroupMembership.left_date
    # and every other soft-delete pattern in this project - no staff role
    # has delete permission on anything (see setup_groups.py).
    is_active = models.BooleanField(
        default=True, help_text="Turn off once a resource is no longer available, rather than deleting it."
    )

    class Meta:
        ordering = ["resource_type", "name"]

    def __str__(self):
        return self.name


class ResourceBooking(models.Model):
    """
    A single reservation of a Resource for a block of time. Optionally tied
    to an events.models.Event (e.g. reserving the van for a specific
    outreach), but doesn't have to be - a weekly committee meeting that was
    never itself created as an Event can still book the conference room.
    """

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="bookings")
    title = models.CharField(max_length=200, help_text="What this booking is for, e.g. 'Youth Ministry meeting'.")
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resource_bookings",
        help_text="Link this booking to an existing event, if any.",
    )
    booked_by = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="resource_bookings")
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_datetime"]

    def __str__(self):
        return f"{self.resource} - {self.title} ({self.start_datetime:%Y-%m-%d %H:%M})"

    def overlaps(self, start, end):
        """True if [start, end) overlaps this booking's [start_datetime, end_datetime)."""
        return self.start_datetime < end and start < self.end_datetime
