from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from members.models import Member

from .models import PrayerRequest
from .notifications import send_prayer_answered_notification
from .services import is_sms_prayer_message, mark_prayed_for, record_sms_prayer_request


class SubmitPrayerRequestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pray-er", password="test-pass-123")
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu", user=self.user)

    def test_member_can_submit_a_private_request_by_default(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("submit_prayer_request"), {"request_text": "Please pray for my exams."}
        )
        self.assertEqual(response.status_code, 302)
        prayer_request = PrayerRequest.objects.get(member=self.member)
        self.assertFalse(prayer_request.is_public)

    def test_member_can_mark_a_request_public(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("submit_prayer_request"),
            {"request_text": "Pray for my family's health.", "is_public": "on"},
        )
        prayer_request = PrayerRequest.objects.get(member=self.member)
        self.assertTrue(prayer_request.is_public)

    def test_user_without_member_profile_is_redirected(self):
        no_profile_user = User.objects.create_user(username="noprofile3", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(
            self.client.post(reverse("submit_prayer_request"), {"request_text": "Pray for me."}),
            reverse("dashboard"),
        )


class PrayerWallTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah")

    def test_approved_public_request_appears_on_the_wall(self):
        PrayerRequest.objects.create(
            member=self.member, request_text="Pray for my job search.", is_public=True, approved_for_public=True
        )
        response = self.client.get(reverse("prayer_wall"))
        self.assertContains(response, "Pray for my job search.")

    def test_public_request_is_held_until_staff_approve_it(self):
        PrayerRequest.objects.create(member=self.member, request_text="Awaiting review.", is_public=True)
        response = self.client.get(reverse("prayer_wall"))
        self.assertNotContains(response, "Awaiting review.")

    def test_private_request_does_not_appear_on_the_wall(self):
        PrayerRequest.objects.create(member=self.member, request_text="A private matter.", is_public=False)
        response = self.client.get(reverse("prayer_wall"))
        self.assertNotContains(response, "A private matter.")

    def test_name_is_hidden_unless_shared(self):
        PrayerRequest.objects.create(
            member=self.member, request_text="Pray for my health.", is_public=True, share_name_publicly=False,
            approved_for_public=True,
        )
        response = self.client.get(reverse("prayer_wall"))
        self.assertContains(response, "A church member")
        self.assertNotContains(response, "Kojo Mensah")

    def test_name_is_shown_when_shared(self):
        PrayerRequest.objects.create(
            member=self.member, request_text="Pray for my new job.", is_public=True, share_name_publicly=True,
            approved_for_public=True,
        )
        response = self.client.get(reverse("prayer_wall"))
        self.assertContains(response, "Kojo Mensah")


class MarkPrayedForServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="reconciler2", password="test-pass-123")
        self.member = Member.objects.create(first_name="Yaw", last_name="Asare")

    def test_marks_request_prayed_for_and_returns_true(self):
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Pray for me.")
        result = mark_prayed_for(prayer_request, user=self.user)
        prayer_request.refresh_from_db()
        self.assertTrue(result)
        self.assertTrue(prayer_request.prayed_for)
        self.assertIsNotNone(prayer_request.prayed_for_at)

    def test_marking_twice_is_a_no_op_the_second_time(self):
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Pray for me.")
        mark_prayed_for(prayer_request, user=self.user)
        result = mark_prayed_for(prayer_request, user=self.user)
        self.assertFalse(result)

    def test_marking_prayed_for_notifies_the_member(self):
        self.member.email = "yaw@example.com"
        self.member.save()
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Pray for me.")
        mark_prayed_for(prayer_request, user=self.user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("yaw@example.com", mail.outbox[0].to)

    def test_marking_twice_does_not_notify_a_second_time(self):
        self.member.email = "yaw@example.com"
        self.member.save()
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Pray for me.")
        mark_prayed_for(prayer_request, user=self.user)
        mark_prayed_for(prayer_request, user=self.user)
        self.assertEqual(len(mail.outbox), 1)


class SendPrayerAnsweredNotificationTests(TestCase):
    """Direct tests of send_prayer_answered_notification - the opt-out-able nudge fired by mark_prayed_for."""

    def test_emails_a_member_with_an_email_on_file(self):
        member = Member.objects.create(first_name="Yaw", last_name="Asare", email="yaw@example.com")
        prayer_request = PrayerRequest.objects.create(member=member, request_text="Pray for me.")
        result = send_prayer_answered_notification(prayer_request)
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("yaw@example.com", mail.outbox[0].to)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_texts_a_member_with_a_phone_on_file(self):
        member = Member.objects.create(first_name="Yaw", last_name="Asare", phone="0244000000")
        prayer_request = PrayerRequest.objects.create(member=member, request_text="Pray for me.")
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            result = send_prayer_answered_notification(prayer_request)
        self.assertTrue(result)
        mock_get.assert_called_once()

    def test_returns_false_and_sends_nothing_when_member_has_opted_out(self):
        member = Member.objects.create(
            first_name="No", last_name="Nudges", email="no-nudges@example.com", notify_prayer_updates=False
        )
        prayer_request = PrayerRequest.objects.create(member=member, request_text="Pray for me.")
        result = send_prayer_answered_notification(prayer_request)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_returns_false_for_a_member_with_no_contact_info(self):
        member = Member.objects.create(first_name="No", last_name="Contact")
        prayer_request = PrayerRequest.objects.create(member=member, request_text="Pray for me.")
        result = send_prayer_answered_notification(prayer_request)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)


class StaffPrayerManagementTests(TestCase):
    """Prayer requests in the staff area - Pastors only, same as households/groups/campuses."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher8", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor8", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.member = Member.objects.create(first_name="Ama", last_name="Boateng")

    def test_usher_cannot_view_prayer_requests(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_prayer_list")), reverse("dashboard"))

    def test_pastor_can_view_prayer_requests(self):
        PrayerRequest.objects.create(member=self.member, request_text="Please pray for my mother.")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_prayer_list"))
        self.assertContains(response, "Please pray for my mother.")

    def test_pastor_can_mark_a_request_prayed_for(self):
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Please pray for my mother.")
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_prayer_mark_prayed", args=[prayer_request.id]))
        self.assertEqual(response.status_code, 302)
        prayer_request.refresh_from_db()
        self.assertTrue(prayer_request.prayed_for)

    def test_pastor_can_approve_a_public_request_for_the_wall(self):
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Healing please.", is_public=True)
        self.client.force_login(self.pastor)
        self.client.post(reverse("staff_prayer_set_wall_approval", args=[prayer_request.id]), {"approve": "1"})
        self.assertContains(self.client.get(reverse("prayer_wall")), "Healing please.")
        self.client.post(reverse("staff_prayer_set_wall_approval", args=[prayer_request.id]), {"approve": "0"})
        self.assertNotContains(self.client.get(reverse("prayer_wall")), "Healing please.")

    def test_a_private_request_can_never_be_approved_for_the_wall(self):
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Private.", is_public=False)
        self.client.force_login(self.pastor)
        self.client.post(reverse("staff_prayer_set_wall_approval", args=[prayer_request.id]), {"approve": "1"})
        prayer_request.refresh_from_db()
        self.assertFalse(prayer_request.approved_for_public)

    def test_usher_cannot_approve_for_the_wall(self):
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Healing please.", is_public=True)
        self.client.force_login(self.usher)
        self.client.post(reverse("staff_prayer_set_wall_approval", args=[prayer_request.id]), {"approve": "1"})
        prayer_request.refresh_from_db()
        self.assertFalse(prayer_request.approved_for_public)

    def test_awaiting_filter_lists_only_unapproved_public_requests(self):
        PrayerRequest.objects.create(member=self.member, request_text="Needs review.", is_public=True)
        PrayerRequest.objects.create(member=self.member, request_text="Already live.", is_public=True, approved_for_public=True)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_prayer_list"), {"show": "awaiting"})
        self.assertContains(response, "Needs review.")
        self.assertNotContains(response, "Already live.")

    def test_pastor_can_assign_a_request_to_a_pastor(self):
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Please pray for my mother.")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_prayer_assign", args=[prayer_request.id]), {"assigned_pastor": self.pastor.id}
        )
        self.assertEqual(response.status_code, 302)
        prayer_request.refresh_from_db()
        self.assertEqual(prayer_request.assigned_pastor, self.pastor)

    def test_assigning_can_only_choose_a_pastor(self):
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Please pray for my mother.")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_prayer_list"))
        form = response.context["page_obj"][0].assign_form
        self.assertNotIn(self.usher, form.fields["assigned_pastor"].queryset)
        self.assertIn(self.pastor, form.fields["assigned_pastor"].queryset)

    def test_usher_cannot_assign_a_request(self):
        prayer_request = PrayerRequest.objects.create(member=self.member, request_text="Please pray for my mother.")
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_prayer_assign", args=[prayer_request.id]), {"assigned_pastor": self.pastor.id}
        )
        self.assertEqual(response.status_code, 302)
        prayer_request.refresh_from_db()
        self.assertIsNone(prayer_request.assigned_pastor)

    def test_reassigning_clears_a_previous_assignment(self):
        other_pastor = User.objects.create_user(username="pastor9", password="test-pass-123", is_staff=True)
        other_pastor.groups.add(Group.objects.get(name="Pastors"))
        prayer_request = PrayerRequest.objects.create(
            member=self.member, request_text="Please pray for my mother.", assigned_pastor=self.pastor
        )
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_prayer_assign", args=[prayer_request.id]), {"assigned_pastor": ""}
        )
        self.assertEqual(response.status_code, 302)
        prayer_request.refresh_from_db()
        self.assertIsNone(prayer_request.assigned_pastor)


class IsSmsPrayerMessageTests(TestCase):
    def test_recognizes_the_keyword_case_insensitively(self):
        self.assertTrue(is_sms_prayer_message("PRAY for my mother's surgery next week"))
        self.assertTrue(is_sms_prayer_message("pray for my exams"))
        self.assertTrue(is_sms_prayer_message("  Pray   for my family  "))

    def test_rejects_the_bare_keyword_with_nothing_after_it(self):
        self.assertFalse(is_sms_prayer_message("PRAY"))
        self.assertFalse(is_sms_prayer_message("PRAY   "))

    def test_rejects_an_unrelated_message(self):
        self.assertFalse(is_sms_prayer_message("What time is service?"))
        self.assertFalse(is_sms_prayer_message("IN"))
        self.assertFalse(is_sms_prayer_message("GIVE 50"))

    def test_rejects_empty_or_missing_text(self):
        self.assertFalse(is_sms_prayer_message(""))
        self.assertFalse(is_sms_prayer_message(None))


class RecordSmsPrayerRequestTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")

    def test_creates_a_private_request_for_a_matching_member(self):
        prayer_request, error = record_sms_prayer_request(
            phone="233244123456", message_text="PRAY for my mother's surgery next week"
        )
        self.assertIsNone(error)
        self.assertIsNotNone(prayer_request)
        self.assertEqual(prayer_request.member, self.member)
        self.assertEqual(prayer_request.request_text, "for my mother's surgery next week")
        self.assertFalse(prayer_request.is_public)
        self.assertFalse(prayer_request.share_name_publicly)

    def test_unrelated_message_is_ignored_not_an_error(self):
        prayer_request, error = record_sms_prayer_request(phone="0244123456", message_text="What time is service?")
        self.assertIsNone(prayer_request)
        self.assertEqual(error, "not_a_prayer_message")
        self.assertEqual(PrayerRequest.objects.count(), 0)

    def test_no_matching_member_reports_the_specific_error(self):
        prayer_request, error = record_sms_prayer_request(phone="0209999999", message_text="PRAY for my health")
        self.assertIsNone(prayer_request)
        self.assertEqual(error, "no_matching_member")
        self.assertEqual(PrayerRequest.objects.count(), 0)


@override_settings(SMS_WEBHOOK_TOKEN="test-provider-secret")
class SmsPrayerWebhookTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_X_SMS_WEBHOOK_TOKEN"] = "test-provider-secret"
        self.member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")

    def test_webhook_creates_a_request_for_a_matching_member_from_posted_fields(self):
        response = self.client.post(
            reverse("sms_prayer_webhook"), {"From": "0244123456", "Content": "PRAY for my job interview"}
        )
        self.assertEqual(response.status_code, 200)
        prayer_request = PrayerRequest.objects.get(member=self.member)
        self.assertEqual(prayer_request.request_text, "for my job interview")
        self.assertFalse(prayer_request.is_public)

    def test_webhook_always_responds_ok_even_for_an_unrelated_text(self):
        response = self.client.post(reverse("sms_prayer_webhook"), {"From": "0244123456", "Content": "Hello there"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PrayerRequest.objects.count(), 0)

    def test_webhook_always_responds_ok_for_an_unmatched_number(self):
        response = self.client.post(
            reverse("sms_prayer_webhook"), {"From": "0209999999", "Content": "PRAY for my health"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PrayerRequest.objects.count(), 0)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_webhook_sends_a_confirmation_text_back(self):
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            self.client.post(reverse("sms_prayer_webhook"), {"From": "0244123456", "Content": "PRAY for my health"})
        mock_get.assert_called_once()

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_webhook_sends_a_no_match_text_for_an_unrecognized_number(self):
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            self.client.post(reverse("sms_prayer_webhook"), {"From": "0209999999", "Content": "PRAY for my health"})
        mock_get.assert_called_once()
