"""
A podcast feed at /sermons/podcast.xml, built with Django's own syndication
framework - no extra dependency needed. Any sermon with an uploaded
audio_file (see models.py) appears here as an episode with a real audio
enclosure, so it plays directly in a podcast app; a sermon with only a
media_url (often a YouTube link, not something a podcast app can play as
audio) is left out of the feed but still shows on the public sermon pages.
"""

from datetime import datetime, time

from django.contrib.syndication.views import Feed
from django.urls import reverse

from .models import Sermon


class SermonPodcastFeed(Feed):
    title = "Newlife AG Sermons"
    description = "Sunday sermons from Newlife AG (Assemblies of God), Tema."

    def link(self):
        return reverse("sermon_list")

    def items(self):
        # Only sermons with an actual audio file - see the module docstring
        # for why media_url alone doesn't qualify. Capped at the 50 most
        # recent so the feed doesn't grow unbounded after years of sermons.
        return Sermon.objects.filter(audio_file__isnull=False).exclude(audio_file="").select_related("series").order_by("-date", "-pk")[:50]

    def item_title(self, item):
        return item.title

    def item_description(self, item):
        parts = []
        if item.series:
            parts.append(f"Series: {item.series.name}")
        if item.speaker:
            parts.append(f"Speaker: {item.speaker}")
        if item.scripture_reference:
            parts.append(f"Scripture: {item.scripture_reference}")
        if item.notes:
            parts.append(item.notes)
        return "\n\n".join(parts) or item.title

    def item_link(self, item):
        return reverse("sermon_detail", args=[item.id])

    def item_pubdate(self, item):
        # Sermon.date is a DateField, but Feed needs a datetime - midnight
        # on that date is precise enough for a podcast's publish ordering.
        return datetime.combine(item.date, time.min)

    def item_enclosure_url(self, item):
        return item.audio_file.url

    def item_enclosure_length(self, item):
        try:
            return item.audio_file.size
        except (OSError, ValueError):
            # The file is missing from storage (e.g. copied database without
            # its media files) - 0 is a harmless fallback some podcast apps
            # accept; the enclosure URL itself is what actually matters.
            return 0

    def item_enclosure_mime_type(self, item):
        return "audio/mpeg"
