from django.conf import settings
from django.db import models
from django.utils import timezone

from events.models import Event
from members.models import Member


class Decision(models.Model):
    """
    A decision made at an altar call - salvation, rededication, interest in
    water baptism, or baptism in the Holy Spirit - recorded right after a
    service by whoever was at the altar (usually an Usher or Pastor).
    Distinct from followup.FollowUp: a FollowUp tracks a person through an
    ongoing, multi-stage relationship with the church, while a Decision is a
    dated, one-time record of what happened at the altar that particular
    service. A plain ForeignKey to Member, not a OneToOneField - the same
    person can make more than one decision over the years (e.g. salvation as
    a teenager, a rededication a decade later), same reasoning as
    milestones.BaptismRecord/TransferLetter. See decisions/services.py's
    record_decision, which also starts a FollowUp automatically for a
    first-time salvation decision, so nobody who responds to an altar call
    is lost track of afterward.
    """

    class DecisionType(models.TextChoices):
        SALVATION = "salvation", "Salvation (first-time)"
        REDEDICATION = "rededication", "Rededication"
        BAPTISM_INTEREST = "baptism_interest", "Interested in Water Baptism"
        HOLY_SPIRIT = "holy_spirit", "Baptism in the Holy Spirit"
        OTHER = "other", "Other"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="decisions")
    decision_type = models.CharField(max_length=20, choices=DecisionType.choices)
    date = models.DateField(default=timezone.localdate)
    event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decisions",
        help_text="Which service/event this happened at, if it was tied to one.",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.member} - {self.get_decision_type_display()} ({self.date})"
