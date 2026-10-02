from django.db import models

from members.models import Member


class SermonSeries(models.Model):
    """A multi-week teaching series (e.g. a 6-week sermon series) that sermons can optionally belong to."""

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Sermon series"

    def __str__(self):
        return self.name


class Tag(models.Model):
    """A topic label a sermon can carry (e.g. "Faith", "Family") - set from the sermon form, not managed on its own."""

    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Sermon(models.Model):
    title = models.CharField(max_length=200)
    speaker = models.CharField(max_length=150, blank=True)
    date = models.DateField()
    scripture_reference = models.CharField(max_length=150, blank=True)
    media_url = models.URLField(
        blank=True, help_text="Link to the audio/video file (YouTube, S3, etc.)"
    )
    # Separate from media_url on purpose - media_url is often a YouTube/video
    # link, which isn't something a podcast app can play as an audio
    # enclosure. Uploading an actual MP3 here is what makes a sermon appear
    # in the podcast feed (see sermons/feeds.py) - a sermon with only a
    # media_url still shows up on the public sermon list/detail pages, just
    # not in the feed.
    audio_file = models.FileField(
        upload_to="sermon_audio/",
        null=True,
        blank=True,
        help_text="Upload an MP3 to include this sermon in the podcast feed (/sermons/podcast.xml).",
    )
    # A downloadable study guide/fill-in-the-blank notes sheet, separate from
    # `notes` (which is just a text field shown on the page itself) - this is
    # a real file (almost always a PDF) a member downloads and prints or
    # fills in on their own device.
    study_guide = models.FileField(
        upload_to="sermon_study_guides/",
        null=True,
        blank=True,
        help_text="Optional PDF study guide/notes sheet, downloadable from this sermon's public page.",
    )
    # Separate from study_guide on purpose - a study guide is for one
    # person's own personal notes/fill-in-the-blanks, while this is a set of
    # ready-made questions for a small group to talk through together at
    # their next meeting. Surfaced two places: this sermon's own public page
    # (same download-link pattern as study_guide), and a small group leader's
    # lesson-posting page (members/views.py's group_lessons), which links to
    # whichever sermon has the most recent one - so a leader preparing this
    # week's meeting doesn't have to go looking for it on the sermons page.
    discussion_guide = models.FileField(
        upload_to="sermon_discussion_guides/",
        null=True,
        blank=True,
        help_text="Optional small-group discussion guide (questions tied to this message) for group leaders.",
    )
    notes = models.TextField(blank=True)
    series = models.ForeignKey(
        SermonSeries,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sermons",
        help_text="Optional - part of a multi-week teaching series.",
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="sermons")

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.title} ({self.date:%Y-%m-%d})"

    @property
    def video_embed_url(self):
        from livestream.youtube import youtube_embed_url
        return youtube_embed_url(self.media_url)

    @property
    def video_thumbnail_url(self):
        embed = self.video_embed_url
        if embed and "/videoseries?" not in embed:
            return f"https://i.ytimg.com/vi/{embed.rsplit('/', 1)[-1]}/hqdefault.jpg"
        return None


class Devotional(models.Model):
    date = models.DateField(unique=True)
    title = models.CharField(max_length=200)
    scripture_reference = models.CharField(max_length=150)
    body = models.TextField()

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.title} ({self.date:%Y-%m-%d})"


class SermonProgress(models.Model):
    """
    One member marking one sermon as watched/listened to - only exists once
    marked, same "no row means not done yet" convention as
    pathway.MemberPathwayProgress (see that model's docstring). Powers the
    progress bar on a sermon series landing page (see series_detail): a
    series a member hasn't touched yet needs no rows at all, and one they've
    fully worked through is just as many rows as it has sermons.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="sermon_progress")
    sermon = models.ForeignKey(Sermon, on_delete=models.CASCADE, related_name="member_progress")
    watched_date = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ("member", "sermon")
        verbose_name_plural = "Sermon progress"

    def __str__(self):
        return f"{self.member} watched {self.sermon}"
