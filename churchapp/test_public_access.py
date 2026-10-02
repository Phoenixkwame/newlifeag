from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from sermons.models import Sermon


class VisitorAccessTests(TestCase):
    def test_visitors_can_browse_without_an_account(self):
        names = (
            "home", "visitor_info", "connect_card", "upcoming_events",
            "sermon_list", "watch_online", "public_group_finder", "give",
        )
        for name in names:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        event = Event.objects.create(title="Sunday Service", start_datetime=timezone.now())
        sermon = Sermon.objects.create(title="Welcome", date=timezone.localdate())
        for name, pk in (("event_detail", event.pk), ("sermon_detail", sermon.pk)):
            self.assertEqual(self.client.get(reverse(name, args=[pk])).status_code, 200)
        response = self.client.post(reverse("event_detail", args=[event.pk]), {"form_type": "rsvp"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).path, reverse("login"))

    def test_personal_and_staff_pages_still_require_login(self):
        for name in (
            "dashboard", "member_directory", "edit_profile", "account_settings",
            "giving_statement", "recurring_giving_history", "staff_home",
            "staff_member_list", "staff_member_export", "staff_full_backup",
        ):
            with self.subTest(page=name):
                url = reverse(name)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                target = urlsplit(response.url)
                self.assertEqual(target.path, reverse("login"))
                self.assertEqual(parse_qs(target.query)["next"], [url])

    def test_ordinary_member_cannot_open_staff_tools(self):
        user = get_user_model().objects.create_user(username="ordinary-member")
        self.client.force_login(user)
        for name in ("staff_home", "staff_member_list", "staff_member_export", "staff_full_backup"):
            with self.subTest(page=name):
                self.assertRedirects(self.client.get(reverse(name)), reverse("dashboard"))

    def test_guest_navigation_prioritizes_visiting_and_watching(self):
        for name in ("home", "watch_online"):
            response = self.client.get(reverse(name))
            self.assertContains(response, "Member Login")
            self.assertContains(response, 'href="%s"' % reverse("visitor_info"))
            self.assertContains(response, 'href="%s"' % reverse("watch_online"))
            self.assertNotContains(response, 'href="%s"' % reverse("dashboard"))
            self.assertNotContains(response, 'href="%s"' % reverse("staff_home"))
