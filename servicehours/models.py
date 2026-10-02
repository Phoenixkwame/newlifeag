from django.db import models

from events.models import Event
from members.models import Group, Member


class ServiceHourLog(models.Model):
    """
    A volunteer's own record of hours served - self-logged from their
    dashboard (staff, e.g. a Pastor, can also log hours on someone's behalf),
    separate from ServingAssignment (members/models.py), which is a
    schedule of who's supposed to serve, not a record of what actually
    happened. Optionally tied to the group or event the hours were served
    for, so staff reporting can total hours per member, per group, or
    overall for a date range.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="service_hour_logs")
    date = models.DateField()
    hours = models.DecimalField(max_digits=5, decimal_places=2)
    role = models.CharField(max_length=200, help_text='What you served as, e.g. "Usher", "Sound tech".')
    group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_hour_logs",
        help_text="Which ministry/team this was for, if any.",
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_hour_logs",
        help_text="Which event this was for, if any.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.member} - {self.hours}h ({self.date})"
