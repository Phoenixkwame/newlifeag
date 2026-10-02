from django.db import models


class Flyer(models.Model):
    """
    A promotional graphic - an upcoming event, a sermon series, a giving
    campaign, a general announcement - shown in a horizontally scrollable
    strip near the top of the public homepage (see churchapp/views.py's
    home and templates/home.html's "What's Happening" section). Purely
    visual, staff-managed content, same Pastor-only management as
    LiveStream/Announcement - public, site-wide content (see
    setup_groups.py's PASTOR_MODELS).

    Never deleted once posted, same "turn it off instead" policy as
    everywhere else in this project (e.g. GivingCampaign.is_active) - a
    flyer for a finished promotion is just switched to is_active=False
    rather than removed, so the historical record (and anything else that
    might reference it) stays intact.
    """

    title = models.CharField(
        max_length=150,
        help_text="Shown as the image's alt text and as a caption under it on the homepage.",
    )
    image = models.ImageField(upload_to="flyers/")
    link_url = models.URLField(
        blank=True, help_text="Optional - where the flyer links to, e.g. an event page or giving campaign."
    )
    is_active = models.BooleanField(
        default=True, help_text="Only active flyers show on the homepage."
    )
    # Manual ordering, same pattern as SetListSong.order (members/models.py)
    # and SurveyQuestion/SurveyChoice.order (surveys/models.py) - lower
    # numbers show first, ties broken by most-recently-added.
    order = models.PositiveIntegerField(default=0, help_text="Lower numbers show first on the homepage.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "-created_at"]

    def __str__(self):
        return self.title
