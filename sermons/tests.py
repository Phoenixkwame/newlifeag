from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from members.models import Member

from .models import Devotional, Sermon, SermonProgress, SermonSeries, Tag
from .services import set_sermon_tags, toggle_sermon_watched


class SermonsViewTests(TestCase):
    def test_sermon_list_shows_sermons(self):
        Sermon.objects.create(title="Faith in Action", date=timezone.localdate())
        response = self.client.get(reverse("sermon_list"))
        self.assertContains(response, "Faith in Action")

    def test_devotional_list_highlights_today(self):
        Devotional.objects.create(
            date=timezone.localdate(),
            title="Walking by Faith",
            scripture_reference="John 3:16",
            body="For God so loved the world...",
        )
        response = self.client.get(reverse("devotional_list"))
        self.assertContains(response, "Walking by Faith")
        self.assertContains(response, "John 3:16")

    def test_sermon_search_filters_by_title_or_speaker(self):
        Sermon.objects.create(title="Faith in Action", speaker="Pastor Kojo", date=timezone.localdate())
        Sermon.objects.create(title="Grace Abounds", speaker="Pastor Ama", date=timezone.localdate())
        response = self.client.get(reverse("sermon_list"), {"q": "kojo"})
        self.assertContains(response, "Faith in Action")
        self.assertNotContains(response, "Grace Abounds")

    def test_sermon_search_filters_by_scripture_reference(self):
        Sermon.objects.create(title="Faith in Action", scripture_reference="John 3:16", date=timezone.localdate())
        Sermon.objects.create(title="Grace Abounds", scripture_reference="Romans 5:8", date=timezone.localdate())
        response = self.client.get(reverse("sermon_list"), {"q": "John 3:16"})
        self.assertContains(response, "Faith in Action")
        self.assertNotContains(response, "Grace Abounds")

    def test_sermon_search_filters_by_a_verse_mentioned_only_in_the_notes(self):
        Sermon.objects.create(
            title="Faith in Action", notes="Let's look at John 3:16 together.", date=timezone.localdate()
        )
        Sermon.objects.create(title="Grace Abounds", date=timezone.localdate())
        response = self.client.get(reverse("sermon_list"), {"q": "John 3:16"})
        self.assertContains(response, "Faith in Action")
        self.assertNotContains(response, "Grace Abounds")

    def test_devotional_search_excludes_todays_highlight_card(self):
        Devotional.objects.create(
            date=timezone.localdate(), title="Today's Word", scripture_reference="Ps 23:1", body="The Lord is my shepherd."
        )
        Devotional.objects.create(
            date=timezone.localdate() - timezone.timedelta(days=1),
            title="Yesterday's Grace",
            scripture_reference="Rom 5:8",
            body="But God demonstrates his own love for us.",
        )
        response = self.client.get(reverse("devotional_list"), {"q": "grace"})
        # The devotional title is rendered through {{ devotional.title }},
        # so the apostrophe comes back HTML-escaped (Yesterday&#x27;s Grace).
        self.assertContains(response, escape("Yesterday's Grace"))
        self.assertNotContains(response, "Today's Word")


class SermonDetailTests(TestCase):
    def test_sermon_detail_shows_the_sermon(self):
        sermon = Sermon.objects.create(
            title="Faith in Action", speaker="Pastor Kojo", date=timezone.localdate(), notes="Great message."
        )
        response = self.client.get(reverse("sermon_detail", args=[sermon.id]))
        self.assertContains(response, "Faith in Action")
        self.assertContains(response, "Pastor Kojo")
        self.assertContains(response, "Great message.")

    def test_sermon_list_links_to_the_detail_page(self):
        sermon = Sermon.objects.create(title="Faith in Action", date=timezone.localdate())
        response = self.client.get(reverse("sermon_list"))
        self.assertContains(response, reverse("sermon_detail", args=[sermon.id]))


class SermonPodcastFeedTests(TestCase):
    def test_empty_podcast_page_explains_video_availability(self):
        Sermon.objects.create(title="Video service", date=timezone.localdate(), audio_file=None)
        response = self.client.get(reverse("sermon_podcast"))
        self.assertContains(response, "Audio podcast episodes have not been added yet.")
        self.assertNotContains(response, 'id="podcast-feed"')
        self.assertEqual(self.client.get(reverse("sermon_podcast_feed")).status_code, 200)

    def test_podcast_page_has_player_and_subscription_address_with_audio(self):
        Sermon.objects.create(title="Audio message", date=timezone.localdate(), audio_file="sermon_audio/message.mp3")
        response = self.client.get(reverse("sermon_podcast"))
        self.assertContains(response, "Audio message")
        self.assertContains(response, "<audio")
        self.assertContains(response, "http://testserver/sermons/podcast.xml")

    def test_library_links_to_readable_podcast_page(self):
        response = self.client.get(reverse("sermon_list"))
        self.assertContains(response, 'href="%s"' % reverse("sermon_podcast"))

    def test_sermon_with_audio_file_appears_in_the_feed(self):
        audio = SimpleUploadedFile("sermon.mp3", b"fake audio bytes", content_type="audio/mpeg")
        Sermon.objects.create(title="Faith in Action", date=timezone.localdate(), audio_file=audio)
        response = self.client.get(reverse("sermon_podcast_feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Faith in Action")
        self.assertContains(response, "<enclosure")

    def test_sermon_without_audio_file_is_excluded_from_the_feed(self):
        Sermon.objects.create(title="Grace Abounds", date=timezone.localdate(), media_url="https://youtube.com/x")
        response = self.client.get(reverse("sermon_podcast_feed"))
        self.assertNotContains(response, "Grace Abounds")

    def test_feed_links_to_the_sermon_detail_page(self):
        audio = SimpleUploadedFile("sermon.mp3", b"fake audio bytes", content_type="audio/mpeg")
        sermon = Sermon.objects.create(title="Faith in Action", date=timezone.localdate(), audio_file=audio)
        response = self.client.get(reverse("sermon_podcast_feed"))
        self.assertContains(response, reverse("sermon_detail", args=[sermon.id]))

    def test_feed_mentions_the_series_when_the_sermon_has_one(self):
        series = SermonSeries.objects.create(name="Rooted")
        audio = SimpleUploadedFile("sermon.mp3", b"fake audio bytes", content_type="audio/mpeg")
        Sermon.objects.create(title="Faith in Action", date=timezone.localdate(), audio_file=audio, series=series)
        response = self.client.get(reverse("sermon_podcast_feed"))
        self.assertContains(response, "Series: Rooted")


class SermonStudyGuideTests(TestCase):
    """The optional downloadable study guide/notes sheet on a sermon's public page."""

    def test_study_guide_download_link_shown_when_present(self):
        guide = SimpleUploadedFile("guide.pdf", b"fake pdf bytes", content_type="application/pdf")
        sermon = Sermon.objects.create(title="Faith in Action", date=timezone.localdate(), study_guide=guide)
        response = self.client.get(reverse("sermon_detail", args=[sermon.id]))
        self.assertContains(response, "Download Study Guide")

    def test_no_download_link_when_no_study_guide(self):
        sermon = Sermon.objects.create(title="Faith in Action", date=timezone.localdate())
        response = self.client.get(reverse("sermon_detail", args=[sermon.id]))
        self.assertNotContains(response, "Download Study Guide")

    def test_study_guide_badge_shown_on_the_list(self):
        guide = SimpleUploadedFile("guide.pdf", b"fake pdf bytes", content_type="application/pdf")
        Sermon.objects.create(title="Faith in Action", date=timezone.localdate(), study_guide=guide)
        response = self.client.get(reverse("sermon_list"))
        self.assertContains(response, "Study Guide")


class SermonDiscussionGuideTests(TestCase):
    """
    The optional downloadable small-group discussion guide on a sermon's
    public page - a separate file from study_guide (see
    SermonStudyGuideTests above), same download-link/badge pattern.
    """

    def test_discussion_guide_download_link_shown_when_present(self):
        guide = SimpleUploadedFile("questions.pdf", b"fake pdf bytes", content_type="application/pdf")
        sermon = Sermon.objects.create(title="Faith in Action", date=timezone.localdate(), discussion_guide=guide)
        response = self.client.get(reverse("sermon_detail", args=[sermon.id]))
        self.assertContains(response, "Download Small Group Discussion Guide")

    def test_no_download_link_when_no_discussion_guide(self):
        sermon = Sermon.objects.create(title="Faith in Action", date=timezone.localdate())
        response = self.client.get(reverse("sermon_detail", args=[sermon.id]))
        self.assertNotContains(response, "Download Small Group Discussion Guide")

    def test_discussion_guide_badge_shown_on_the_list(self):
        guide = SimpleUploadedFile("questions.pdf", b"fake pdf bytes", content_type="application/pdf")
        Sermon.objects.create(title="Faith in Action", date=timezone.localdate(), discussion_guide=guide)
        response = self.client.get(reverse("sermon_list"))
        self.assertContains(response, "Discussion Guide")


class SermonSeriesModelTests(TestCase):
    def test_str_is_the_series_name(self):
        series = SermonSeries.objects.create(name="Rooted")
        self.assertEqual(str(series), "Rooted")

    def test_sermons_can_belong_to_a_series(self):
        series = SermonSeries.objects.create(name="Rooted")
        sermon = Sermon.objects.create(title="Week 1", date=timezone.localdate(), series=series)
        self.assertIn(sermon, series.sermons.all())

    def test_deleting_a_series_leaves_its_sermons_with_no_series(self):
        series = SermonSeries.objects.create(name="Rooted")
        sermon = Sermon.objects.create(title="Week 1", date=timezone.localdate(), series=series)
        series.delete()
        sermon.refresh_from_db()
        self.assertIsNone(sermon.series)


class TagModelTests(TestCase):
    def test_str_is_the_tag_name(self):
        tag = Tag.objects.create(name="Faith")
        self.assertEqual(str(tag), "Faith")

    def test_sermons_can_have_multiple_tags(self):
        sermon = Sermon.objects.create(title="Week 1", date=timezone.localdate())
        sermon.tags.add(Tag.objects.create(name="Faith"), Tag.objects.create(name="Family"))
        self.assertEqual(sermon.tags.count(), 2)


class SetSermonTagsTests(TestCase):
    def setUp(self):
        self.sermon = Sermon.objects.create(title="Week 1", date=timezone.localdate())

    def test_creates_new_tags_from_comma_separated_input(self):
        set_sermon_tags(self.sermon, "Faith, Family")
        self.assertEqual(sorted(self.sermon.tags.values_list("name", flat=True)), ["Faith", "Family"])

    def test_reuses_an_existing_tag_case_insensitively(self):
        Tag.objects.create(name="Faith")
        set_sermon_tags(self.sermon, "faith")
        self.assertEqual(Tag.objects.filter(name__iexact="faith").count(), 1)
        self.assertEqual(list(self.sermon.tags.values_list("name", flat=True)), ["Faith"])

    def test_blank_input_clears_all_tags(self):
        self.sermon.tags.add(Tag.objects.create(name="Faith"))
        set_sermon_tags(self.sermon, "")
        self.assertEqual(self.sermon.tags.count(), 0)

    def test_ignores_extra_whitespace_and_empty_entries(self):
        set_sermon_tags(self.sermon, " Faith ,, Family  ")
        self.assertEqual(sorted(self.sermon.tags.values_list("name", flat=True)), ["Faith", "Family"])


class SermonListFilterTests(TestCase):
    def setUp(self):
        self.series = SermonSeries.objects.create(name="Rooted")
        self.other_series = SermonSeries.objects.create(name="Overflow")
        self.tag = Tag.objects.create(name="Faith")
        self.in_series = Sermon.objects.create(title="Rooted Week 1", date=timezone.localdate(), series=self.series)
        self.other = Sermon.objects.create(title="Overflow Week 1", date=timezone.localdate(), series=self.other_series)
        self.in_series.tags.add(self.tag)

    def test_filters_by_series(self):
        response = self.client.get(reverse("sermon_list"), {"series": self.series.id})
        self.assertContains(response, "Rooted Week 1")
        self.assertNotContains(response, "Overflow Week 1")

    def test_filters_by_tag(self):
        response = self.client.get(reverse("sermon_list"), {"tag": self.tag.id})
        self.assertContains(response, "Rooted Week 1")
        self.assertNotContains(response, "Overflow Week 1")

    def test_no_filter_shows_everything(self):
        response = self.client.get(reverse("sermon_list"))
        self.assertContains(response, "Rooted Week 1")
        self.assertContains(response, "Overflow Week 1")


class SeriesDetailViewTests(TestCase):
    def test_shows_the_series_and_its_sermons_in_date_order(self):
        series = SermonSeries.objects.create(name="Rooted", description="A study on staying grounded.")
        Sermon.objects.create(title="Week 2", date=timezone.localdate(), series=series)
        Sermon.objects.create(title="Week 1", date=timezone.localdate() - timezone.timedelta(days=7), series=series)
        response = self.client.get(reverse("sermon_series_detail", args=[series.id]))
        self.assertContains(response, "Rooted")
        self.assertContains(response, "A study on staying grounded.")
        self.assertContains(response, "Week 1")
        self.assertContains(response, "Week 2")

    def test_does_not_show_sermons_from_another_series(self):
        series = SermonSeries.objects.create(name="Rooted")
        other_series = SermonSeries.objects.create(name="Overflow")
        Sermon.objects.create(title="Overflow Week 1", date=timezone.localdate(), series=other_series)
        response = self.client.get(reverse("sermon_series_detail", args=[series.id]))
        self.assertNotContains(response, "Overflow Week 1")

    def test_missing_series_is_a_404(self):
        response = self.client.get(reverse("sermon_series_detail", args=[999]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_visitor_sees_no_progress_bar(self):
        series = SermonSeries.objects.create(name="Rooted")
        Sermon.objects.create(title="Week 1", date=timezone.localdate(), series=series)
        response = self.client.get(reverse("sermon_series_detail", args=[series.id]))
        self.assertNotContains(response, "Your Progress")

    def test_signed_in_member_sees_their_progress_bar_and_watched_badge(self):
        series = SermonSeries.objects.create(name="Rooted")
        watched = Sermon.objects.create(title="Week 1", date=timezone.localdate(), series=series)
        Sermon.objects.create(
            title="Week 2", date=timezone.localdate() + timezone.timedelta(days=7), series=series
        )
        user = User.objects.create_user(username="ama", password="test-pass-123")
        member = Member.objects.create(first_name="Ama", last_name="Owusu", user=user)
        SermonProgress.objects.create(member=member, sermon=watched)

        self.client.force_login(user)
        response = self.client.get(reverse("sermon_series_detail", args=[series.id]))
        self.assertContains(response, "Your Progress")
        self.assertContains(response, "1 of 2 watched (50%)")


class SermonToggleWatchedTests(TestCase):
    def setUp(self):
        self.sermon = Sermon.objects.create(title="Faith in Action", date=timezone.localdate())
        self.user = User.objects.create_user(username="kojo", password="test-pass-123")
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah", user=self.user)

    def test_marks_a_sermon_as_watched(self):
        result = toggle_sermon_watched(member=self.member, sermon=self.sermon)
        self.assertTrue(result)
        self.assertTrue(SermonProgress.objects.filter(member=self.member, sermon=self.sermon).exists())

    def test_toggling_a_second_time_unmarks_it(self):
        toggle_sermon_watched(member=self.member, sermon=self.sermon)
        result = toggle_sermon_watched(member=self.member, sermon=self.sermon)
        self.assertFalse(result)
        self.assertFalse(SermonProgress.objects.filter(member=self.member, sermon=self.sermon).exists())

    def test_anonymous_visitor_does_not_see_the_mark_as_watched_button(self):
        response = self.client.get(reverse("sermon_detail", args=[self.sermon.id]))
        self.assertNotContains(response, "Mark as Watched")

    def test_signed_in_member_sees_the_mark_as_watched_button(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("sermon_detail", args=[self.sermon.id]))
        self.assertContains(response, "Mark as Watched")

    def test_toggle_view_requires_login(self):
        response = self.client.post(reverse("sermon_toggle_watched", args=[self.sermon.id]))
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(SermonProgress.objects.filter(sermon=self.sermon).exists())

    def test_toggle_view_marks_watched_and_redirects_back_to_the_sermon(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("sermon_toggle_watched", args=[self.sermon.id]))
        self.assertRedirects(response, reverse("sermon_detail", args=[self.sermon.id]))
        self.assertTrue(SermonProgress.objects.filter(member=self.member, sermon=self.sermon).exists())

    def test_toggle_view_unmarks_when_already_watched(self):
        SermonProgress.objects.create(member=self.member, sermon=self.sermon)
        self.client.force_login(self.user)
        self.client.post(reverse("sermon_toggle_watched", args=[self.sermon.id]))
        self.assertFalse(SermonProgress.objects.filter(member=self.member, sermon=self.sermon).exists())


class SermonProgressModelTests(TestCase):
    def test_str_mentions_member_and_sermon(self):
        sermon = Sermon.objects.create(title="Faith in Action", date=timezone.localdate())
        member = Member.objects.create(first_name="Ama", last_name="Owusu")
        progress = SermonProgress.objects.create(member=member, sermon=sermon)
        self.assertIn("Ama Owusu", str(progress))
        self.assertIn("Faith in Action", str(progress))

    def test_a_member_can_only_have_one_progress_row_per_sermon(self):
        from django.db import IntegrityError

        sermon = Sermon.objects.create(title="Faith in Action", date=timezone.localdate())
        member = Member.objects.create(first_name="Ama", last_name="Owusu")
        SermonProgress.objects.create(member=member, sermon=sermon)
        with self.assertRaises(IntegrityError):
            SermonProgress.objects.create(member=member, sermon=sermon)
