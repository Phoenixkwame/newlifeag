from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import LiveStream


class LiveStreamModelTests(TestCase):
    def test_str_is_the_title(self):
        stream = LiveStream.objects.create(
            title="Sunday Service - June 1",
            stream_url="https://youtube.com/watch?v=abc123",
            scheduled_for=timezone.now(),
        )
        self.assertEqual(str(stream), "Sunday Service - June 1")

    def test_is_upcoming_is_true_for_a_future_date(self):
        stream = LiveStream.objects.create(
            title="Next Sunday",
            stream_url="https://youtube.com/watch?v=abc123",
            scheduled_for=timezone.now() + timezone.timedelta(days=3),
        )
        self.assertTrue(stream.is_upcoming)

    def test_is_upcoming_is_false_for_a_past_date(self):
        stream = LiveStream.objects.create(
            title="Last Sunday",
            stream_url="https://youtube.com/watch?v=abc123",
            scheduled_for=timezone.now() - timezone.timedelta(days=3),
        )
        self.assertFalse(stream.is_upcoming)


class FeaturedOnHomepageTests(TestCase):
    """
    featured_on_homepage is meant to be a singleton flag - staff shouldn't
    have to remember to unfeature last week's stream when featuring this
    week's (see LiveStream.save's override).
    """

    def test_defaults_to_not_featured(self):
        stream = LiveStream.objects.create(
            title="Sunday Service", stream_url="https://youtube.com/watch?v=abc123", scheduled_for=timezone.now()
        )
        self.assertFalse(stream.featured_on_homepage)

    def test_featuring_one_stream_unfeatures_every_other_one(self):
        last_week = LiveStream.objects.create(
            title="Last Week",
            stream_url="https://youtube.com/watch?v=old",
            scheduled_for=timezone.now() - timezone.timedelta(days=7),
            featured_on_homepage=True,
        )
        this_week = LiveStream.objects.create(
            title="This Week", stream_url="https://youtube.com/watch?v=new", scheduled_for=timezone.now()
        )
        this_week.featured_on_homepage = True
        this_week.save()

        last_week.refresh_from_db()
        this_week.refresh_from_db()
        self.assertFalse(last_week.featured_on_homepage)
        self.assertTrue(this_week.featured_on_homepage)

    def test_saving_without_featuring_does_not_disturb_the_featured_one(self):
        featured = LiveStream.objects.create(
            title="This Week",
            stream_url="https://youtube.com/watch?v=new",
            scheduled_for=timezone.now(),
            featured_on_homepage=True,
        )
        other = LiveStream.objects.create(
            title="Some Other Stream", stream_url="https://youtube.com/watch?v=other", scheduled_for=timezone.now()
        )
        other.notes = "updated"
        other.save()

        featured.refresh_from_db()
        self.assertTrue(featured.featured_on_homepage)


class WatchOnlineViewTests(TestCase):
    def test_channel_and_embedded_services_are_available_without_posts(self):
        for name in ("home", "watch_online"):
            response = self.client.get(reverse(name))
            self.assertContains(response, "https://www.youtube.com/@newlife-chapelag8034/streams")
            self.assertContains(response, "https://www.youtube-nocookie.com/embed/avfQCAACW7c")

    def test_posted_youtube_service_has_an_embedded_player(self):
        LiveStream.objects.create(
            title="Sunday Worship",
            stream_url="https://youtu.be/ybipbArL71U",
            scheduled_for=timezone.now(),
        )
        response = self.client.get(reverse("watch_online"))
        self.assertContains(response, 'src="https://www.youtube.com/embed/ybipbArL71U"')

    def test_non_youtube_service_keeps_its_outbound_link(self):
        LiveStream.objects.create(
            title="Sunday Worship",
            stream_url="https://www.facebook.com/newlyfag/videos/123/",
            scheduled_for=timezone.now(),
        )
        response = self.client.get(reverse("watch_online"))
        self.assertIsNone(response.context["latest_embed_url"])
        self.assertContains(response, 'href="https://www.facebook.com/newlyfag/videos/123/"')

    def test_shows_an_empty_state_with_nothing_posted(self):
        response = self.client.get(reverse("watch_online"))
        self.assertContains(response, "No live stream has been posted yet")

    def test_shows_the_most_recently_scheduled_stream_as_the_latest(self):
        LiveStream.objects.create(
            title="Older Service",
            stream_url="https://youtube.com/watch?v=old",
            scheduled_for=timezone.now() - timezone.timedelta(days=14),
        )
        LiveStream.objects.create(
            title="Newest Service",
            stream_url="https://youtube.com/watch?v=new",
            scheduled_for=timezone.now() - timezone.timedelta(days=1),
        )
        response = self.client.get(reverse("watch_online"))
        self.assertContains(response, "Newest Service")
        # The older one still shows up, just in the "Past Services" list
        # below rather than as the featured "latest" one.
        self.assertContains(response, "Older Service")

    def test_upcoming_stream_is_labeled_differently_from_a_past_one(self):
        LiveStream.objects.create(
            title="This Sunday",
            stream_url="https://youtube.com/watch?v=abc123",
            scheduled_for=timezone.now() + timezone.timedelta(days=2),
        )
        response = self.client.get(reverse("watch_online"))
        self.assertContains(response, "Upcoming")
        self.assertNotContains(response, "Latest Service")
