from django.db import models

from members.models import Campus, Member


class Equipment(models.Model):
    """
    A piece of church-owned gear worth tracking individually - sound/video
    equipment, instruments, lighting - deliberately separate from
    booking.Resource: a Resource is reserved for a block of time (a room,
    the church van), while a piece of Equipment here is simply checked out
    to someone and checked back in later, with a condition worth tracking
    over its lifetime. Maintenance history is handled by the existing
    maintenance app instead of a second ticket system of its own here - see
    MaintenanceRequest.equipment.
    """

    class Category(models.TextChoices):
        SOUND = "sound", "Sound"
        VIDEO = "video", "Video"
        INSTRUMENT = "instrument", "Instrument"
        LIGHTING = "lighting", "Lighting"
        OTHER = "other", "Other"

    class Condition(models.TextChoices):
        EXCELLENT = "excellent", "Excellent"
        GOOD = "good", "Good"
        FAIR = "fair", "Fair"
        NEEDS_REPAIR = "needs_repair", "Needs Repair"

    name = models.CharField(max_length=150, help_text="e.g. 'Shure SM58 Mic #3', 'Yamaha Keyboard'.")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.GOOD)
    serial_number = models.CharField(max_length=100, blank=True)
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment",
        help_text="Which campus this item belongs to (only relevant once there's more than one).",
    )
    notes = models.TextField(blank=True)
    # Retired rather than deleted, same soft-delete reasoning as
    # booking.Resource.is_active and everywhere else in this project - no
    # staff role has delete permission on anything (see setup_groups.py).
    is_active = models.BooleanField(
        default=True, help_text="Turn off once an item is retired/disposed of, rather than deleting it."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name

    @property
    def current_checkout(self):
        """The open checkout for this item, if any - see EquipmentCheckout.checked_in_at."""
        return self.checkouts.filter(checked_in_at__isnull=True).first()

    @property
    def is_checked_out(self):
        return self.current_checkout is not None


class EquipmentCheckout(models.Model):
    """
    One loan of an Equipment item to a member - open (checked_in_at is
    still blank) or closed. An item can only ever have one open checkout at
    a time (enforced in staff/views.py's equipment_checkout, the same way
    checkin/services.py enforces "one open CheckIn per child" - not a
    database constraint, since a closed checkout for the same item is
    perfectly normal history to keep).
    """

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="checkouts")
    checked_out_to = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    checked_out_at = models.DateTimeField(auto_now_add=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, help_text="What it's being used for, or condition notes on return.")

    class Meta:
        ordering = ["-checked_out_at"]

    def __str__(self):
        status = "checked in" if self.checked_in_at else "checked out"
        return f"{self.equipment} {status} to {self.checked_out_to or 'someone'}"
