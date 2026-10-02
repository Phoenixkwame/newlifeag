import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from flyers.models import Flyer
from followup.models import VisitorInfo
from giving.models import GivingCampaign
from livestream.models import LiveStream
from members.models import Member
from sermons.models import Sermon
from testimonies.models import Testimony

from .sms import send_sms, sms_enabled
from .two_factor import SESSION_EXPIRES, SESSION_USER_ID
from .views import _youtube_embed_url


class HomePageTests(TestCase):
    def test_homepage_enhancements_use_real_visitor_content_and_escape_html(self):
        info = VisitorInfo.get_current()
        info.address = "Tema & Community 4"
        info.what_to_expect = "Welcome <script>alert(1)</script>"
        info.save()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "query=Tema%20%26%20Community%204")
        self.assertContains(response, "Welcome &lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertContains(response, 'id="visit-panel"')
        self.assertContains(response, 'id="online-panel"')
        self.assertContains(response, "home/home.js")

    def test_homepage_sermon_audio_and_study_guide_are_optional(self):
        sermon = Sermon.objects.create(
            title="A living hope", date=timezone.localdate(),
            audio_file="sermon_audio/hope.mp3", study_guide="sermon_study_guides/hope.pdf",
        )
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'preload="none"')
        self.assertContains(response, sermon.audio_file.url)
        self.assertContains(response, sermon.study_guide.url)
        self.assertContains(response, reverse("sermon_detail", args=[sermon.pk]))

    def test_countdown_only_appears_for_an_upcoming_event(self):
        self.assertNotContains(self.client.get(reverse("home")), 'data-countdown=')
        event = Event.objects.create(title="Gather together", start_datetime=timezone.now() + timedelta(days=1))
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'data-countdown=')
        self.assertContains(response, reverse("event_detail", args=[event.pk]))

    def test_shows_next_upcoming_event(self):
        Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=2)
        )
        Event.objects.create(
            title="Old Service", start_datetime=timezone.now() - timezone.timedelta(days=2)
        )
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Sunday Service")
        self.assertNotContains(response, "Old Service")

    def test_shows_latest_sermon(self):
        Sermon.objects.create(title="Older Sermon", date=timezone.now().date() - timezone.timedelta(days=10))
        Sermon.objects.create(title="Newest Sermon", date=timezone.now().date())
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Newest Sermon")
        self.assertNotContains(response, "Older Sermon")

    def test_loads_gracefully_with_no_data(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

    def test_shows_visitor_info_when_service_times_are_set(self):
        info = VisitorInfo.get_current()
        info.service_times = "Sundays at 9:00 AM and 11:00 AM"
        info.address = "123 Main Street, Tema"
        info.save()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Sundays at 9:00 AM and 11:00 AM")
        self.assertContains(response, "123 Main Street, Tema")
        self.assertContains(response, reverse("visitor_info"))

    def test_no_visitor_info_card_when_nothing_is_set(self):
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Planning a Visit?")

    def test_shows_a_featured_active_campaign_with_progress(self):
        GivingCampaign.objects.create(
            name="Building Fund", start_date=timezone.localdate(), goal_amount="1000.00", is_active=True
        )
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Building Fund")
        self.assertContains(response, "1000.00")

    def test_inactive_campaign_is_not_featured(self):
        GivingCampaign.objects.create(
            name="Finished Fund", start_date=timezone.localdate(), is_active=False
        )
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Finished Fund")

    def test_get_connected_section_links_to_groups_prayer_and_testimonies(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Get Connected")
        self.assertContains(response, reverse("public_group_finder"))
        self.assertContains(response, reverse("prayer_wall"))
        self.assertContains(response, reverse("testimony_wall"))

    def test_shows_the_latest_approved_testimony(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        Testimony.objects.create(member=member, testimony_text="God healed my mother.", is_approved=True)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "God healed my mother.")
        self.assertContains(response, "A church member")

    def test_unapproved_testimony_is_not_shown(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        Testimony.objects.create(member=member, testimony_text="Not approved yet.", is_approved=False)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Not approved yet.")

    def test_shows_the_testifiers_name_when_shared(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        Testimony.objects.create(
            member=member, testimony_text="Praise God.", is_approved=True, share_name_publicly=True
        )
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Kojo Mensah")


# A minimal valid 1x1 GIF, same tiny fixture pattern used for ImageField
# tests elsewhere in this project (see members/tests.py's photo tests).
TINY_GIF = b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"


def make_flyer(**kwargs):
    kwargs.setdefault("title", "VBS 2027")
    kwargs.setdefault("image", SimpleUploadedFile("flyer.gif", TINY_GIF, content_type="image/gif"))
    return Flyer.objects.create(**kwargs)


class YoutubeEmbedUrlTests(TestCase):
    """Direct tests of churchapp/views.py's _youtube_embed_url helper."""

    def test_recognizes_a_plain_watch_url(self):
        self.assertEqual(
            _youtube_embed_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        )

    def test_recognizes_a_watch_url_with_extra_query_params(self):
        self.assertEqual(
            _youtube_embed_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s"),
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        )

    def test_recognizes_a_short_share_url(self):
        self.assertEqual(
            _youtube_embed_url("https://youtu.be/dQw4w9WgXcQ"), "https://www.youtube.com/embed/dQw4w9WgXcQ"
        )

    def test_recognizes_a_live_url(self):
        self.assertEqual(
            _youtube_embed_url("https://www.youtube.com/live/dQw4w9WgXcQ"),
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        )

    def test_recognizes_an_already_embeddable_url(self):
        self.assertEqual(
            _youtube_embed_url("https://www.youtube.com/embed/dQw4w9WgXcQ"),
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        )

    def test_recognizes_a_playlist_url(self):
        self.assertEqual(
            _youtube_embed_url("https://www.youtube.com/playlist?list=PL12345"),
            "https://www.youtube.com/embed/videoseries?list=PL12345",
        )

    def test_returns_none_for_a_non_youtube_url(self):
        self.assertIsNone(_youtube_embed_url("https://www.facebook.com/newlifeag/videos/12345"))

    def test_returns_none_for_a_blank_url(self):
        self.assertIsNone(_youtube_embed_url(""))


class HomepageFlyerStripTests(TestCase):
    def test_no_flyer_strip_with_no_active_flyers(self):
        # Checks for the actual rendered div, not the bare class name -
        # base.html's <style> block defines .flyer-strip/.flyer-card CSS on
        # every page load regardless of whether any flyer is ever shown.
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, '<div class="flyer-strip">')

    def test_shows_active_flyers(self):
        make_flyer(title="Vacation Bible School")
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Vacation Bible School")
        self.assertContains(response, "flyer-strip")

    def test_hides_inactive_flyers(self):
        make_flyer(title="Old Promotion", is_active=False)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Old Promotion")

    def test_flyer_links_out_when_a_link_is_set(self):
        make_flyer(title="Building Fund", link_url="https://example.com/give")
        response = self.client.get(reverse("home"))
        self.assertContains(response, "https://example.com/give")

    def test_flyers_ordered_by_order_field(self):
        make_flyer(title="Shows Second", order=5)
        make_flyer(title="Shows First", order=1)
        response = self.client.get(reverse("home"))
        content = response.content.decode()
        self.assertLess(content.index("Shows First"), content.index("Shows Second"))


class HomepageVideoTests(TestCase):
    def test_channel_video_shown_with_no_featured_video_configured(self):
        # The church channel player remains available without a featured video.
        response = self.client.get(reverse("home"))
        self.assertContains(response, '<div class="video-embed">', count=1)
        self.assertNotContains(response, "Get to Know Us")

    def test_featured_live_stream_embeds_when_it_is_a_youtube_link(self):
        LiveStream.objects.create(
            title="Sunday Service",
            stream_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            scheduled_for=timezone.now(),
            featured_on_homepage=True,
        )
        response = self.client.get(reverse("home"))
        self.assertContains(response, "video-embed")
        self.assertContains(response, "youtube.com/embed/dQw4w9WgXcQ")
        self.assertContains(response, "Sunday Service")
        self.assertContains(response, "Live Now")

    def test_featured_live_stream_falls_back_to_a_link_when_not_youtube(self):
        LiveStream.objects.create(
            title="Sunday Service",
            stream_url="https://www.facebook.com/newlifeag/videos/12345",
            scheduled_for=timezone.now(),
            featured_on_homepage=True,
        )
        response = self.client.get(reverse("home"))
        self.assertContains(response, '<div class="video-embed">', count=1)
        self.assertContains(response, "https://www.facebook.com/newlifeag/videos/12345")

    def test_upcoming_featured_stream_is_labeled_live_soon(self):
        LiveStream.objects.create(
            title="Next Sunday",
            stream_url="https://youtu.be/dQw4w9WgXcQ",
            scheduled_for=timezone.now() + timezone.timedelta(days=1),
            featured_on_homepage=True,
        )
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Live Soon")
        self.assertNotContains(response, "Live Now")

    def test_falls_back_to_welcome_video_with_no_featured_stream(self):
        info = VisitorInfo.get_current()
        info.welcome_video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        info.save()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "video-embed")
        self.assertContains(response, "Get to Know Us")

    def test_featured_stream_takes_priority_over_welcome_video(self):
        info = VisitorInfo.get_current()
        info.welcome_video_url = "https://www.youtube.com/watch?v=fallback12"
        info.save()
        LiveStream.objects.create(
            title="Sunday Service",
            stream_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            scheduled_for=timezone.now(),
            featured_on_homepage=True,
        )
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Sunday Service")
        self.assertNotContains(response, "Get to Know Us")

    def test_unfeatured_stream_is_not_shown_even_if_most_recent(self):
        LiveStream.objects.create(
            title="Not Featured", stream_url="https://youtu.be/dQw4w9WgXcQ", scheduled_for=timezone.now()
        )
        response = self.client.get(reverse("home"))
        self.assertContains(response, '<div class="video-embed">', count=1)
        self.assertNotContains(response, "Not Featured")


class MainNavigationTests(TestCase):
    """
    The shared nav (templates/base.html) trims the public links down to a
    handful visible at all times (Events, Sermons, Give) plus a "More"
    dropdown for the rest - see home.html's own "Get Connected" section for
    where Small Groups/Prayer Wall/Testimonies get real visibility instead.
    """

    def test_more_dropdown_contains_the_secondary_public_links(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'class="nav-more"')
        for url_name in (
            "devotional_list",
            "watch_online",
            "campaign_list",
            "public_group_finder",
            "prayer_wall",
            "testimony_wall",
            "visitor_info",
            "submit_suggestion",
        ):
            self.assertContains(response, reverse(url_name))

    def test_primary_links_are_always_present(self):
        response = self.client.get(reverse("home"))
        for url_name in ("upcoming_events", "sermon_list", "give"):
            self.assertContains(response, reverse(url_name))


class MultiLanguageTests(TestCase):
    """
    The Twi/English toggle (see settings.py's LocaleMiddleware/LANGUAGES,
    the language switcher form in templates/base.html, and the translated
    strings in locale/tw/LC_MESSAGES/django.po). No URL prefix is used (no
    i18n_patterns), so LocaleMiddleware picks up the active language from
    the Accept-Language header/cookie/session rather than the path - these
    tests use the Accept-Language header, the simplest way to select a
    language from a plain test client request without a prior round trip
    through the switcher form itself.
    """

    def test_default_language_is_english(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Welcome to Newlife AG")

    def test_twi_translation_is_served_when_requested(self):
        response = self.client.get(reverse("home"), HTTP_ACCEPT_LANGUAGE="tw")
        self.assertContains(response, "Akwaaba Wɔ Newlife AG")
        self.assertNotContains(response, "Welcome to Newlife AG")

    def test_nav_labels_are_translated_on_other_public_pages(self):
        response = self.client.get(reverse("upcoming_events"), HTTP_ACCEPT_LANGUAGE="tw")
        # The nav itself is shared (base.html), so this also confirms the
        # switcher's translations reach every public page, not just home.
        self.assertContains(response, "Ma")  # nav's "Give" link, translated
        self.assertContains(response, "Bio")  # nav's "More" dropdown label, translated
        self.assertContains(response, "Nhyiamu A Ɛreba")  # the page's own "Upcoming Events" heading

    def test_language_switcher_form_posts_to_set_language(self):
        response = self.client.post(reverse("set_language"), {"language": "tw", "next": "/"}, follow=True)
        self.assertEqual(response.status_code, 200)
        # The session now remembers the choice for later requests, with no
        # Accept-Language header needed.
        self.assertContains(response, "Akwaaba Wɔ Newlife AG")


class SMSHelperTests(TestCase):
    """
    Direct tests of churchapp/sms.py - the test environment has no Hubtel
    credentials set, so sms_enabled() being False (and send_sms() being a
    silent no-op as a result) is exactly the state every other app's tests
    run under too, confirming SMS truly costs nothing when unconfigured.
    """

    def test_sms_is_disabled_with_no_credentials_configured(self):
        self.assertFalse(sms_enabled())

    def test_send_sms_is_a_no_op_when_not_configured(self):
        with patch("churchapp.sms.requests.get") as mock_get:
            result = send_sms("0244000000", "Test message")
        self.assertFalse(result)
        mock_get.assert_not_called()

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_send_sms_is_a_no_op_with_no_phone_number(self):
        with patch("churchapp.sms.requests.get") as mock_get:
            result = send_sms("", "Test message")
        self.assertFalse(result)
        mock_get.assert_not_called()

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_send_sms_calls_hubtel_when_configured(self):
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            result = send_sms("0244000000", "Test message")
        self.assertTrue(result)
        mock_get.assert_called_once()

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_send_sms_returns_false_and_logs_on_failure(self):
        import requests

        with patch("churchapp.sms.requests.get", side_effect=requests.RequestException("down")):
            result = send_sms("0244000000", "Test message")
        self.assertFalse(result)


class StaffTwoFactorLoginTests(TestCase):
    """
    churchapp/two_factor.py's StaffTwoFactorLoginView/verify_login_code -
    the extra emailed-code step required by staff accounts on the ordinary
    /accounts/login/ page (see churchapp/urls.py). Staff without email are
    blocked. Most unrelated feature tests use force_login to set up a
    session; security regression tests also cover the login flow.
    """

    def _extract_code(self):
        match = re.search(r"Your login code is: (\d{6})", mail.outbox[-1].body)
        self.assertIsNotNone(match, "Couldn't find a 6-digit code in the sent email.")
        return match.group(1)

    def test_ordinary_member_login_is_unaffected(self):
        User.objects.create_user(username="member1", password="test-pass-123")
        response = self.client.post(reverse("login"), {"username": "member1", "password": "test-pass-123"})
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_staff_with_email_is_emailed_a_code_and_not_logged_in_yet(self):
        User.objects.create_user(
            username="staffer1", password="test-pass-123", is_staff=True, email="staffer1@example.com"
        )
        response = self.client.post(reverse("login"), {"username": "staffer1", "password": "test-pass-123"})
        self.assertRedirects(response, reverse("verify_login_code"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["staffer1@example.com"])
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        # Confirms the login genuinely hasn't completed yet, not just that
        # the response redirected somewhere - a login-required page should
        # still bounce this client back to the login page.
        self.assertRedirects(
            self.client.get(reverse("staff_home")), f"{reverse('login')}?next={reverse('staff_home')}"
        )

    def test_staff_without_email_cannot_bypass_two_factor_login(self):
        User.objects.create_user(username="staffer2", password="test-pass-123", is_staff=True)
        response = self.client.post(reverse("login"), {"username": "staffer2", "password": "test-pass-123"})
        self.assertContains(response, "Staff login requires an email address.")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn(SESSION_USER_ID, self.client.session)

    def test_correct_code_completes_the_login(self):
        User.objects.create_user(
            username="staffer3", password="test-pass-123", is_staff=True, email="staffer3@example.com"
        )
        self.client.post(reverse("login"), {"username": "staffer3", "password": "test-pass-123"})
        code = self._extract_code()
        response = self.client.post(reverse("verify_login_code"), {"code": code})
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertEqual(response.wsgi_request.user.username, "staffer3")

    def test_wrong_code_does_not_log_in(self):
        User.objects.create_user(
            username="staffer4", password="test-pass-123", is_staff=True, email="staffer4@example.com"
        )
        self.client.post(reverse("login"), {"username": "staffer4", "password": "test-pass-123"})
        wrong_code = "000000" if self._extract_code() != "000000" else "111111"
        response = self.client.post(reverse("verify_login_code"), {"code": wrong_code})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "wasn&#x27;t right")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_a_used_up_or_expired_code_sends_back_to_login(self):
        User.objects.create_user(
            username="staffer5", password="test-pass-123", is_staff=True, email="staffer5@example.com"
        )
        self.client.post(reverse("login"), {"username": "staffer5", "password": "test-pass-123"})
        code = self._extract_code()

        session = self.client.session
        session[SESSION_EXPIRES] = (timezone.now() - timedelta(minutes=1)).isoformat()
        session.save()

        response = self.client.post(reverse("verify_login_code"), {"code": code})
        self.assertRedirects(response, reverse("login"))
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_verify_page_redirects_to_login_with_no_pending_login(self):
        response = self.client.get(reverse("verify_login_code"))
        self.assertRedirects(response, reverse("login"))

    def test_verify_page_redirects_if_the_pending_user_no_longer_exists(self):
        staffer = User.objects.create_user(
            username="staffer6", password="test-pass-123", is_staff=True, email="staffer6@example.com"
        )
        self.client.post(reverse("login"), {"username": "staffer6", "password": "test-pass-123"})
        code = self._extract_code()
        staffer.delete()
        response = self.client.post(reverse("verify_login_code"), {"code": code})
        self.assertRedirects(response, reverse("login"))

    def test_session_key_used_to_track_the_pending_login_is_cleared_on_success(self):
        User.objects.create_user(
            username="staffer7", password="test-pass-123", is_staff=True, email="staffer7@example.com"
        )
        self.client.post(reverse("login"), {"username": "staffer7", "password": "test-pass-123"})
        code = self._extract_code()
        self.client.post(reverse("verify_login_code"), {"code": code})
        self.assertNotIn(SESSION_USER_ID, self.client.session)
