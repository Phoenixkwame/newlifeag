from django.db import models
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta


def reservation_deadline():
    return timezone.now() + timedelta(minutes=30)

from members.models import Campus, Member


class Event(models.Model):
    class EventType(models.TextChoices):
        SERVICE = "service", "Service"
        MEETING = "meeting", "Meeting"
        OUTREACH = "outreach", "Outreach"
        OTHER = "other", "Other"

    class Recurrence(models.TextChoices):
        NONE = "none", "Does not repeat"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    event_type = models.CharField(max_length=20, choices=EventType.choices, default=EventType.SERVICE)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        help_text="Which campus this event is at (only relevant once there's more than one).",
    )
    # Only meaningful on the first event in a series - it's what the staff
    # area's "create event" form uses to generate the events below it. Each
    # generated occurrence is its own real Event row (own RSVPs, own
    # volunteer slots) rather than one event that just "repeats" in the UI,
    # and has its own recurrence left at NONE.
    recurrence = models.CharField(
        max_length=10,
        choices=Recurrence.choices,
        default=Recurrence.NONE,
        help_text="Generates future occurrences when this event is first created. Has no effect when editing an existing event.",
    )
    series_parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="occurrences",
        help_text="Set automatically on events generated from a recurring series.",
    )

    class Meta:
        ordering = ["start_datetime"]

    def __str__(self):
        return f"{self.title} ({self.start_datetime:%Y-%m-%d})"


class EventServiceTime(models.Model):
    """
    One specific service time/location within a multi-service Event - e.g.
    an 8:00 AM and a 10:30 AM Sunday service that are really the same
    "event" for scheduling purposes but need attendance and RSVPs tracked
    separately. Deliberately optional: most events have zero of these and
    are tracked as a single service exactly as before - RSVP.service_time
    and Attendance.service_time (both nullable) only ever get set once an
    event actually has more than one to choose from (see events/forms.py's
    RSVPForm/QrCheckinForm, which only show the picker when they exist).
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="service_times")
    label = models.CharField(max_length=100, help_text="e.g. '8:00 AM Service' or 'Main Sanctuary'.")
    start_time = models.TimeField(null=True, blank=True, help_text="What time this specific service starts.")
    location = models.CharField(
        max_length=200, blank=True, help_text="Overrides the event's own location, if this service meets somewhere else."
    )

    class Meta:
        ordering = ["start_time", "label"]

    def __str__(self):
        return f"{self.label} - {self.event}"


class RSVP(models.Model):
    class Status(models.TextChoices):
        GOING = "going", "Going"
        MAYBE = "maybe", "Maybe"
        NOT_GOING = "not_going", "Not going"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="rsvps")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="rsvps")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.GOING)
    # Which specific service this RSVP is for, on an event that actually
    # has more than one - left blank for every ordinary single-service
    # event, same "only relevant once it exists" story as Campus fields
    # elsewhere in this project.
    service_time = models.ForeignKey(
        EventServiceTime, on_delete=models.SET_NULL, null=True, blank=True, related_name="rsvps"
    )

    class Meta:
        unique_together = ("event", "member")

    def __str__(self):
        return f"{self.member} - {self.event} ({self.status})"


class VolunteerSlot(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="volunteer_slots")
    role_needed = models.CharField(max_length=100, help_text="e.g. Usher, Choir, Media Team")
    capacity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.role_needed} for {self.event}"

    @property
    def spots_filled(self):
        return self.signups.count()

    @property
    def spots_remaining(self):
        return max(self.capacity - self.spots_filled, 0)


class VolunteerSignup(models.Model):
    slot = models.ForeignKey(VolunteerSlot, on_delete=models.CASCADE, related_name="signups")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="volunteer_signups")
    signed_up_at = models.DateTimeField(auto_now_add=True)
    # Set the first (and only) time a reminder goes out for this signup - see
    # the send_volunteer_reminders management command. Kept separate from
    # signed_up_at so re-running the command daily never double-reminds
    # anyone, regardless of how the reminder window lines up with the
    # command's actual run schedule.
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("slot", "member")

    def __str__(self):
        return f"{self.member} -> {self.slot}"


class VolunteerWaitlistEntry(models.Model):
    """
    A member waiting for a spot in a VolunteerSlot that was full at the
    moment they tried to sign up (see events/services.py's join_waitlist,
    reached from event_detail whenever sign_up_for_slot raises
    SlotFullError). Ordered strictly first-come-first-served: when an
    existing VolunteerSignup for the same slot is cancelled
    (cancel_volunteer_signup) and a spot actually opens up, the earliest
    entry here is automatically promoted into a real VolunteerSignup and
    removed from this table - no staff action needed to notice the vacancy.
    """

    slot = models.ForeignKey(VolunteerSlot, on_delete=models.CASCADE, related_name="waitlist_entries")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="volunteer_waitlist_entries")
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["joined_at"]
        unique_together = ("slot", "member")

    def __str__(self):
        return f"{self.member} waiting for {self.slot}"


class EventTicket(models.Model):
    """
    A paid ticket type for an Event, e.g. "Retreat - Adult" GH₵150, "Retreat -
    Child" GH₵50. A free event doesn't need one of these at all - the plain
    RSVP above already covers that; tickets exist for events with a real
    cost and (optionally) a capacity limit, like a retreat or conference.
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="tickets")
    name = models.CharField(max_length=150, help_text='e.g. "Adult", "Child", "Early bird"')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    capacity = models.PositiveIntegerField(null=True, blank=True, help_text="Leave blank for no limit.")

    class Meta:
        ordering = ["price"]

    def __str__(self):
        return f"{self.name} - GH₵{self.price} ({self.event})"

    @property
    def registered_count(self):
        # Pending (not yet paid) registrations count against capacity too -
        # they're a reserved spot while payment is in progress, not a free
        # one - see events/services.py's register_for_ticket. Only a FAILED
        # registration (payment never completed) frees the spot back up.
        return self.registrations.filter(
            Q(status=EventRegistration.Status.COMPLETED)
            | Q(status=EventRegistration.Status.PENDING, expires_at__gt=timezone.now())
        ).count()

    @property
    def is_full(self):
        return self.capacity is not None and self.registered_count >= self.capacity


class EventRegistration(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        REVIEW = "review", "Paid - staff review required"

    ticket = models.ForeignKey(EventTicket, on_delete=models.CASCADE, related_name="registrations")
    member = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="event_registrations")
    payment_reference = models.CharField(
        max_length=100, blank=True, help_text="Reference/transaction ID from the payment provider."
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    registered_at = models.DateTimeField(auto_now_add=True)
    amount_due = models.DecimalField(max_digits=10, decimal_places=2, null=True, editable=False)
    expires_at = models.DateTimeField(default=reservation_deadline)
    checkout_url = models.URLField(max_length=2000, blank=True, editable=False)

    def save(self, *args, **kwargs):
        if self._state.adding and self.amount_due is None:
            self.amount_due = self.ticket.price
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["-registered_at"]

    def __str__(self):
        return f"{self.member} - {self.ticket} ({self.status})"
