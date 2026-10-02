from django.conf import settings
from django.db import models
from django.utils import timezone

from members.models import Member


class FollowUp(models.Model):
    """
    Tracks a first-time visitor (or anyone the church wants to intentionally
    stay in touch with) through a simple pipeline, from their first visit
    through to becoming an established member - so nobody who walks through
    the door is forgotten about after the first Sunday.

    One per Member (OneToOneField) - a person is either being followed up
    with or they aren't, there's no sense in tracking the same person twice.
    Starting one is a deliberate staff action (see followup/services.py's
    start_follow_up, used by staff/views.py's followup_start from a member's
    detail page), not something that happens automatically on sign-up.
    """

    class Stage(models.TextChoices):
        NEW = "new", "New Visitor"
        CONTACTED = "contacted", "Contacted"
        INVITED = "invited", "Invited to a Group"
        JOINED = "joined", "Became a Member"
        INACTIVE = "inactive", "No Longer Following Up"

    member = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="follow_up")
    stage = models.CharField(max_length=10, choices=Stage.choices, default=Stage.NEW)
    first_visit_date = models.DateField(default=timezone.localdate)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_follow_ups",
        help_text="Which staff member is responsible for following up with this person.",
    )
    notes = models.TextField(
        blank=True, help_text="General notes about this person - for a dated log of contact attempts, see below."
    )

    class Meta:
        ordering = ["stage", "-first_visit_date"]

    def __str__(self):
        return f"{self.member} ({self.get_stage_display()})"

    @property
    def last_contacted_at(self):
        """
        Computed live from the most recent ContactAttempt, rather than
        stored as its own field - same reasoning as Pledge.given_toward_pledge
        elsewhere in this app: one source of truth, never a duplicated value
        that could drift out of sync with the actual log of attempts.
        """
        latest = self.contact_attempts.first()
        return latest.contacted_at if latest else None


class ContactAttempt(models.Model):
    """
    A single logged attempt to reach someone being followed up with - a
    call, a text, a home visit. An append-only log (no delete permission is
    ever granted on it, same no-delete policy as everywhere else in this
    app), so FollowUp.notes above stays for general context while this stays
    a reliable dated history of who reached out and when.
    """

    follow_up = models.ForeignKey(FollowUp, on_delete=models.CASCADE, related_name="contact_attempts")
    contacted_at = models.DateTimeField(auto_now_add=True)
    contacted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-contacted_at"]

    def __str__(self):
        return f"Contact with {self.follow_up.member} on {self.contacted_at:%Y-%m-%d}"


class VisitorInfo(models.Model):
    """
    The church's own "what to expect" info for a first-time visitor -
    service times, wifi, address, and a short welcome note - shown on the
    public, no-login /connect/welcome/ page (see followup/views.py's
    visitor_info, and staff/views.py's visitor_info_edit for how Pastors
    keep it up to date). Deliberately a single editable row rather than a
    list - there's exactly one "visiting us" story to tell, not several -
    enforced by always working through get_current() below rather than by
    application code creating rows directly.
    """

    service_times = models.TextField(
        blank=True, help_text="e.g. Sundays at 9:00 AM and 11:00 AM"
    )
    address = models.CharField(max_length=255, blank=True)
    wifi_network = models.CharField(max_length=100, blank=True)
    wifi_password = models.CharField(max_length=100, blank=True)
    what_to_expect = models.TextField(
        blank=True, help_text="A short welcome note - parking, dress code, what happens with kids, etc."
    )
    # Shown embedded on the homepage (see churchapp/views.py's home)
    # whenever no LiveStream is currently featured there (see that model's
    # featured_on_homepage) - a standing "get to know us" video rather than
    # week-to-week service content, so it belongs here alongside the rest
    # of the church's own "visiting us" story instead of on LiveStream.
    welcome_video_url = models.URLField(
        blank=True,
        help_text="A YouTube video or playlist link, embedded on the homepage whenever no live stream is "
        "currently featured there. Leave blank to show nothing in that case.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Visitor info"

    def __str__(self):
        return "Visitor info"

    @classmethod
    def get_current(cls):
        """
        Always returns the same single row (creating it, blank, the first
        time anyone asks) - both the public page and the staff edit form go
        through this rather than a plain queryset, so there's never a
        question of which row is "the" one.
        """
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
