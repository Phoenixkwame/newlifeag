from django.db import models


class Suggestion(models.Model):
    """
    Anonymous feedback/suggestions to church leadership - deliberately has
    no link to a Member or User at all, unlike PrayerRequest/CareRequest
    (always tied to whoever submitted them) or MemberNote (tied to whoever
    wrote it). There's no way for even a Pastor reading this list to trace
    a suggestion back to who wrote it, and no login is required to submit
    one (see suggestions/views.py's submit_suggestion). Same Pastor-only
    management as CareRequest - no Usher/Treasurer grant ever touches this
    model (see setup_groups.py's PASTOR_MODELS).
    """

    message = models.TextField(help_text="Your feedback or suggestion for church leadership.")
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_reviewed = models.BooleanField(default=False)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"Suggestion ({self.submitted_at:%Y-%m-%d})"
