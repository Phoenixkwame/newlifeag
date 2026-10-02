from django.conf import settings
from django.db import models

from members.models import Campus, Group, Member


class Announcement(models.Model):
    """
    A one-off bulk message to some slice of the church, sent by
    email and/or SMS - see announcements/services.py's send_announcement.
    Deliberately Pastor-only (see setup_groups.py) since it can reach every
    member's inbox and phone at once.
    """

    class Audience(models.TextChoices):
        ALL = "all", "All Active Members"
        CAMPUS = "campus", "One Campus"
        GROUP = "group", "One Group"
        # Two reusable, always-current segments - "reusable" in that they're
        # never a fixed list of members typed in once, but a live definition
        # (see announcements/services.py's audience_queryset) recomputed the
        # same way the existing staff pages for each already compute it:
        # members/services.py's absentee_members and giving/services.py's
        # lapsed_recurring_gifts. Picking one here means "whoever that page
        # would currently show", right up to the moment Send is clicked.
        ABSENTEES = "absentees", "Absentee Members"
        LAPSED_GIVERS = "lapsed_givers", "Lapsed Recurring Givers"

    subject = models.CharField(max_length=200)
    body = models.TextField(help_text="The full message, sent by email.")
    sms_body = models.CharField(
        max_length=300,
        blank=True,
        help_text=(
            "Shorter version for SMS - leave blank to send the email body "
            "instead, trimmed to fit a single text."
        ),
    )
    audience = models.CharField(max_length=15, choices=Audience.choices, default=Audience.ALL)
    campus = models.ForeignKey(
        Campus, on_delete=models.SET_NULL, null=True, blank=True, related_name="announcements"
    )
    group = models.ForeignKey(
        Group, on_delete=models.SET_NULL, null=True, blank=True, related_name="announcements"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Null until send_announcement() actually sends it - a draft can still be
    # edited or re-targeted right up until that moment (see
    # staff/views.py's announcement_edit), never after.
    sent_at = models.DateTimeField(null=True, blank=True)
    email_sent_count = models.PositiveIntegerField(default=0)
    sms_sent_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.subject

    @property
    def is_sent(self):
        return self.sent_at is not None


class AnnouncementDelivery(models.Model):
    """
    One row per member per channel this announcement was evaluated against -
    written once, right when send_announcement processes that member, and
    never edited afterward. Lets a Pastor audit exactly who this
    announcement reached (or didn't, and why) after the fact, rather than
    only knowing the aggregate totals on email_sent_count/sms_sent_count
    above - see staff/views.py's announcement_delivery_report.
    """

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED_OPTED_OUT = "skipped_opted_out", "Skipped (opted out)"
        SKIPPED_NO_CONTACT = "skipped_no_contact", "Skipped (no contact info)"

    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="deliveries")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="announcement_deliveries")
    channel = models.CharField(max_length=5, choices=Channel.choices)
    status = models.CharField(max_length=20, choices=Status.choices)

    class Meta:
        unique_together = ("announcement", "member", "channel")
        ordering = ["member__last_name", "member__first_name", "channel"]
        verbose_name_plural = "Announcement deliveries"

    def __str__(self):
        return f"{self.member} - {self.get_channel_display()} - {self.get_status_display()}"
