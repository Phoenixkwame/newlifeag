from django.conf import settings
from django.db import models

from members.models import Member


class CareRequest(models.Model):
    """
    A private request for pastoral care - counseling, a home or hospital
    visit, or anything else a member would rather not put on the public-ish
    PrayerRequest flow. Deliberately its own model rather than a flag on
    PrayerRequest: it's never shown on the prayer wall, and only the Pastors
    group ever gets any permission on it at all (see PASTOR_MODELS in
    setup_groups.py) - not Ushers, not Treasurers - so a member can trust
    this only reaches the pastoral team.
    """

    class RequestType(models.TextChoices):
        COUNSELING = "counseling", "Counseling appointment"
        HOME_VISIT = "home_visit", "Home visit"
        HOSPITAL_VISIT = "hospital_visit", "Hospital visit"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        SCHEDULED = "scheduled", "Scheduled"
        COMPLETED = "completed", "Completed"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="care_requests")
    request_type = models.CharField(max_length=20, choices=RequestType.choices, default=RequestType.OTHER)
    details = models.TextField(help_text="What you'd like the pastoral team to know.")
    preferred_contact_method = models.CharField(
        max_length=100, blank=True, help_text="e.g. 'Call my cell', 'Text is best' - optional."
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    assigned_pastor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Which pastor is handling this request.",
    )
    scheduled_date = models.DateField(null=True, blank=True, help_text="When a visit or appointment is scheduled for.")
    # Never shown to the member who submitted the request - staff-only,
    # same "for the eyes of whoever has permission on this model" reasoning
    # as PathwayStep being Pastor-only to define (see pathway/models.py).
    pastor_notes = models.TextField(blank=True, help_text="Private notes, visible only to Pastors.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_request_type_display()} request from {self.member} ({self.created_at:%Y-%m-%d})"
