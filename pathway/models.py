from django.conf import settings
from django.db import models

from members.models import Member


class PathwayStep(models.Model):
    """
    One step in the church's discipleship pathway - e.g. "New Believers
    Class", "Water Baptism", "Membership Class" - shown to every member in a
    fixed order set by a Pastor. Steps apply to the whole church rather than
    being set up per member, so a MemberPathwayProgress row (below) is only
    ever created the moment a step is actually marked complete for someone -
    not one per member per step up front - see pathway/services.py.
    """

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(
        default=0, help_text="Controls the order steps are shown in - lower numbers come first."
    )

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class MemberPathwayProgress(models.Model):
    """
    One member's completion of one pathway step. Only exists once a step has
    actually been marked complete for that member - a step with no row here
    for a given member is simply treated as not yet completed (see
    pathway/services.py's progress_for_member), so adding a brand-new step
    never requires backfilling a row for every existing member.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="pathway_progress")
    step = models.ForeignKey(PathwayStep, on_delete=models.CASCADE, related_name="member_progress")
    completed_date = models.DateField(null=True, blank=True, help_text="Left blank until this step is completed.")
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        unique_together = ("member", "step")
        ordering = ["step__order"]

    @property
    def is_completed(self):
        return self.completed_date is not None

    def __str__(self):
        status = "completed" if self.is_completed else "pending"
        return f"{self.member} - {self.step} ({status})"
