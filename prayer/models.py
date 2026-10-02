from django.conf import settings
from django.db import models

from members.models import Member


class PrayerRequest(models.Model):
    """
    Submitted by a member from their own dashboard (see members/templates/
    members/dashboard.html) - never anonymous to staff, since someone needs
    to actually know who to follow up with, but optionally also shown on the
    public prayer wall (/prayer/wall/) without a name, unless the member
    chooses to share it there.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="prayer_requests", null=True, blank=True)
    guest_name = models.CharField(max_length=150, blank=True)
    guest_email = models.EmailField(blank=True)
    guest_phone = models.CharField(max_length=30, blank=True)
    approved_for_public = models.BooleanField(default=False)
    request_text = models.TextField()
    # Same "claim it, don't just leave it in a shared pile" pattern as
    # care.CareRequest.assigned_pastor - who's actually following up on this
    # one, not just whether it's been prayed for yet.
    assigned_pastor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Which pastor is following up on this request.",
    )
    is_public = models.BooleanField(
        default=False, help_text="Also show this on the public prayer wall, not just to staff."
    )
    share_name_publicly = models.BooleanField(
        default=False,
        help_text="Show your name on the public wall (only matters if this request is public).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Marked, never deleted - no staff role has delete permission on
    # anything (see setup_groups.py), the same reasoning behind
    # GroupMembership.left_date.
    prayed_for = models.BooleanField(default=False)
    prayed_for_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Prayer request from {self.submitter_name} ({self.created_at:%Y-%m-%d})"

    @property
    def submitter_name(self):
        return str(self.member) if self.member_id else (self.guest_name or "Anonymous visitor")
