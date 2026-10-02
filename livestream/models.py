from django.db import models
from django.utils import timezone


class LiveStream(models.Model):
    """
    One week's online service link, posted by staff and shown on the public
    "Watch Online" page (livestream/views.py's watch_online) - the most
    recent one is shown prominently, the rest listed below as past
    services. Same "most-recent-first, browsable history" shape as Sermon,
    and managed the same way sermons/announcements are - Pastor-only, since
    it's public, site-wide content (see setup_groups.py's PASTOR_MODELS).
    """

    title = models.CharField(max_length=200, help_text='e.g. "Sunday Service - June 1, 2027"')
    stream_url = models.URLField(help_text="Link to the YouTube/Facebook live stream or recording.")
    scheduled_for = models.DateTimeField(help_text="When this service is/was streamed.")
    notes = models.TextField(blank=True, help_text="Optional - e.g. the sermon topic or a special note.")
    # Manually flipped on right before/during a service and back off
    # afterward - see churchapp/views.py's home, which shows this stream
    # embedded (when it's a recognizable YouTube link) or as a "Watch Live
    # Now"/"Watch the Replay" button otherwise, right on the homepage, not
    # just on the "Watch Online" page. Deliberately a manual toggle rather
    # than an automatic time-window guess (e.g. "within an hour of
    # scheduled_for") - staff know better than a clock does whether a
    # service actually started or ran long.
    featured_on_homepage = models.BooleanField(
        default=False,
        help_text="Show this one on the homepage right now. Only one stream should be featured at a time - "
        "turning this on for one automatically turns it off for every other stream.",
    )

    class Meta:
        ordering = ["-scheduled_for"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.featured_on_homepage:
            LiveStream.objects.exclude(pk=self.pk).filter(featured_on_homepage=True).update(
                featured_on_homepage=False
            )

    @property
    def is_upcoming(self):
        return self.scheduled_for > timezone.now()
