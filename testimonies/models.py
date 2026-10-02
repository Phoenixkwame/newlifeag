from django.db import models

from members.models import Member


class Testimony(models.Model):
    """
    A member's testimony of answered prayer/God's work in their life,
    submitted from their own dashboard - never anonymous to staff (someone
    needs to be accountable for what's posted publicly), but only shown on
    the public Testimony Wall (/testimonies/wall/) once a Pastor has
    approved it. Unlike prayer.PrayerRequest, which goes public the moment
    a member checks is_public, a testimony is unmoderated text headed
    straight for a public page with no other gate, so approval is the
    review step here rather than an optional extra. share_name_publicly
    only matters once approved, same as PrayerRequest.share_name_publicly.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="testimonies")
    testimony_text = models.TextField()
    share_name_publicly = models.BooleanField(
        default=False, help_text="Show your name alongside this testimony on the public wall."
    )
    # Marked, never deleted - no staff role has delete permission on
    # anything (see setup_groups.py), same reasoning as
    # prayer.PrayerRequest.prayed_for.
    is_approved = models.BooleanField(
        default=False, help_text="A Pastor has reviewed this and approved it for the public Testimony Wall."
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "testimonies"

    def __str__(self):
        return f"Testimony from {self.member} ({self.created_at:%Y-%m-%d})"
