from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from members.models import Member

from .models import ContactAttempt, FollowUp, VisitorInfo
from .notifications import notify_followup_team_of_new_connection
from .services import advance_stage, find_or_create_guest, log_contact, stale_follow_ups, start_follow_up


class StartFollowUpTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu")

    def test_creates_a_new_follow_up_with_the_default_stage(self):
        follow_up = start_follow_up(self.member)
        self.assertEqual(follow_up.member, self.member)
        self.assertEqual(follow_up.stage, FollowUp.Stage.NEW)

    def test_is_idempotent_for_a_member_already_being_followed_up_with(self):
        first = start_follow_up(self.member)
        first.stage = FollowUp.Stage.CONTACTED
        first.save()
        second = start_follow_up(self.member)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.stage, FollowUp.Stage.CONTACTED)

    def test_does_not_log_anything_when_no_user_is_given(self):
        start_follow_up(self.member)
        self.assertEqual(LogEntry.objects.count(), 0)

    def test_logs_an_activity_log_entry_when_a_user_is_given(self):
        user = User.objects.create_user(username="pastor1", password="test-pass-123")
        follow_up = start_follow_up(self.member, user=user)
        entry = LogEntry.objects.get()
        self.assertEqual(entry.user, user)
        self.assertEqual(entry.object_id, str(follow_up.pk))
        self.assertIn("Efua Owusu", entry.change_message)

    def test_does_not_log_again_on_a_repeat_call_for_the_same_member(self):
        user = User.objects.create_user(username="pastor1", password="test-pass-123")
        start_follow_up(self.member, user=user)
        start_follow_up(self.member, user=user)
        self.assertEqual(LogEntry.objects.count(), 1)


class LogContactTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        self.follow_up = start_follow_up(self.member)
        self.user = User.objects.create_user(username="follower", password="test-pass-123")

    def test_creates_a_contact_attempt(self):
        attempt = log_contact(self.follow_up, user=self.user, note="Called, left a voicemail.")
        self.assertEqual(attempt.follow_up, self.follow_up)
        self.assertEqual(attempt.contacted_by, self.user)
        self.assertEqual(attempt.note, "Called, left a voicemail.")

    def test_does_not_overwrite_a_previous_attempt(self):
        log_contact(self.follow_up, user=self.user, note="First call.")
        log_contact(self.follow_up, user=self.user, note="Second call.")
        self.assertEqual(self.follow_up.contact_attempts.count(), 2)

    def test_last_contacted_at_reflects_the_most_recent_attempt(self):
        self.assertIsNone(self.follow_up.last_contacted_at)
        first = log_contact(self.follow_up, user=self.user, note="First call.")
        self.assertEqual(self.follow_up.last_contacted_at, first.contacted_at)
        second = log_contact(self.follow_up, user=self.user, note="Second call.")
        self.assertEqual(self.follow_up.last_contacted_at, second.contacted_at)


class AdvanceStageTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Yaw", last_name="Asare")
        self.follow_up = start_follow_up(self.member)

    def test_moves_to_a_valid_stage(self):
        result = advance_stage(self.follow_up, FollowUp.Stage.INVITED)
        self.follow_up.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(self.follow_up.stage, FollowUp.Stage.INVITED)

    def test_rejects_an_invalid_stage_and_changes_nothing(self):
        result = advance_stage(self.follow_up, "not-a-real-stage")
        self.follow_up.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(self.follow_up.stage, FollowUp.Stage.NEW)


class FollowUpModelTests(TestCase):
    def test_str_includes_member_and_stage(self):
        member = Member.objects.create(first_name="Ama", last_name="Boateng")
        follow_up = FollowUp.objects.create(member=member, stage=FollowUp.Stage.CONTACTED)
        self.assertIn("Ama Boateng", str(follow_up))
        self.assertIn("Contacted", str(follow_up))

    def test_one_follow_up_per_member(self):
        member = Member.objects.create(first_name="Ama", last_name="Boateng")
        FollowUp.objects.create(member=member)
        with self.assertRaises(Exception):
            FollowUp.objects.create(member=member)


class FindOrCreateGuestTests(TestCase):
    def test_creates_a_new_member_when_nothing_matches(self):
        member = find_or_create_guest(first_name="Nana", last_name="Yeboah", phone="0244123456")
        self.assertEqual(member.first_name, "Nana")
        self.assertEqual(member.last_name, "Yeboah")
        self.assertEqual(Member.objects.count(), 1)

    def test_matches_an_existing_member_by_the_last_nine_digits_of_phone(self):
        existing = Member.objects.create(first_name="Kwabena", last_name="Otoo", phone="+233244123456")
        found = find_or_create_guest(first_name="Kwabena", last_name="Otoo", phone="0244123456")
        self.assertEqual(found.id, existing.id)
        self.assertEqual(Member.objects.count(), 1)

    def test_matches_an_existing_member_by_email_when_phone_does_not_match(self):
        existing = Member.objects.create(first_name="Abena", last_name="Frimpong", email="abena@example.com")
        found = find_or_create_guest(first_name="Abena", last_name="Frimpong", email="ABENA@example.com")
        self.assertEqual(found.id, existing.id)
        self.assertEqual(Member.objects.count(), 1)

    def test_no_match_with_neither_phone_nor_email_creates_a_new_member(self):
        Member.objects.create(first_name="Someone", last_name="Else")
        member = find_or_create_guest(first_name="New", last_name="Guest")
        self.assertNotEqual(member.id, Member.objects.get(first_name="Someone").id)
        self.assertEqual(Member.objects.count(), 2)


class NotifyFollowUpTeamTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu", phone="0244000000")
        self.follow_up = start_follow_up(self.member)

    def test_does_nothing_when_groups_do_not_exist_yet(self):
        # setup_groups hasn't been run - this should not raise.
        notify_followup_team_of_new_connection(self.follow_up)

    @patch("followup.notifications.send_sms")
    @patch("followup.notifications.send_mail")
    def test_emails_and_texts_ushers_and_pastors_without_duplicates(self, mock_send_mail, mock_send_sms):
        ushers = Group.objects.create(name="Ushers")
        pastors = Group.objects.create(name="Pastors")
        usher_user = User.objects.create_user(username="usher1", password="test-pass-123", email="usher1@example.com")
        Member.objects.create(first_name="Usher", last_name="One", phone="0244111111", user=usher_user)
        usher_user.groups.add(ushers)
        # Someone who is both an Usher and a Pastor should only be notified once.
        usher_user.groups.add(pastors)

        notify_followup_team_of_new_connection(self.follow_up)

        mock_send_mail.assert_called_once()
        recipient_list = mock_send_mail.call_args[0][3]
        self.assertEqual(recipient_list, ["usher1@example.com"])
        mock_send_sms.assert_called_once()

    @patch("followup.notifications.send_sms")
    @patch("followup.notifications.send_mail")
    def test_subject_and_action_can_be_overridden_for_a_non_connect_card_entry_point(self, mock_send_mail, mock_send_sms):
        Group.objects.create(name="Ushers")
        usher_user = User.objects.create_user(username="usher2", password="test-pass-123", email="usher2@example.com")
        Member.objects.create(first_name="Usher", last_name="Two", user=usher_user)
        usher_user.groups.add(Group.objects.get(name="Ushers"))

        notify_followup_team_of_new_connection(
            self.follow_up, subject="New member registered", action="created their own account"
        )

        mock_send_mail.assert_called_once()
        subject_arg = mock_send_mail.call_args[0][0]
        message_arg = mock_send_mail.call_args[0][1]
        self.assertEqual(subject_arg, "New member registered")
        self.assertIn("created their own account", message_arg)
        self.assertNotIn("connect card", message_arg)


class ConnectCardViewTests(TestCase):
    def test_get_shows_the_form(self):
        response = self.client.get(reverse("connect_card"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "We're glad you're here")

    def test_valid_submission_creates_a_member_and_follow_up_and_redirects(self):
        response = self.client.post(
            reverse("connect_card"),
            {
                "first_name": "Adjoa",
                "last_name": "Mensah",
                "phone": "0244555555",
                "email": "",
                "notes": "First time visiting, interested in a small group.",
            },
        )
        self.assertRedirects(response, reverse("connect_card_confirmation"))
        member = Member.objects.get(first_name="Adjoa", last_name="Mensah")
        follow_up = FollowUp.objects.get(member=member)
        self.assertEqual(follow_up.stage, FollowUp.Stage.NEW)
        self.assertIn("interested in a small group", follow_up.notes)

    def test_repeat_submission_does_not_create_a_duplicate_member(self):
        existing = Member.objects.create(first_name="Kwame", last_name="Boafo", phone="0244777777")
        self.client.post(
            reverse("connect_card"),
            {
                "first_name": "Kwame",
                "last_name": "Boafo",
                "phone": "0244777777",
                "email": "",
                "notes": "",
            },
        )
        self.assertEqual(Member.objects.filter(first_name="Kwame", last_name="Boafo").count(), 1)
        follow_up = FollowUp.objects.get(member=existing)
        self.assertEqual(follow_up.member_id, existing.id)

    def test_missing_phone_and_email_shows_a_validation_error(self):
        response = self.client.post(
            reverse("connect_card"),
            {"first_name": "No", "last_name": "Contact", "phone": "", "email": "", "notes": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Member.objects.filter(first_name="No", last_name="Contact").exists())

    def test_confirmation_page_loads(self):
        response = self.client.get(reverse("connect_card_confirmation"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Thank you")


class VisitorInfoGetCurrentTests(TestCase):
    """The always-one-row singleton behind the public visitor info page."""

    def test_creates_a_blank_row_the_first_time_its_asked_for(self):
        self.assertEqual(VisitorInfo.objects.count(), 0)
        info = VisitorInfo.get_current()
        self.assertEqual(VisitorInfo.objects.count(), 1)
        self.assertEqual(info.service_times, "")

    def test_returns_the_same_row_every_time(self):
        first = VisitorInfo.get_current()
        first.service_times = "Sundays at 9am and 11am"
        first.save()
        second = VisitorInfo.get_current()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.service_times, "Sundays at 9am and 11am")


class VisitorInfoPageTests(TestCase):
    """The public, no-login "Plan Your Visit" page (followup/views.py's visitor_info)."""

    def test_no_login_required(self):
        response = self.client.get(reverse("visitor_info"))
        self.assertEqual(response.status_code, 200)

    def test_shows_configured_info(self):
        info = VisitorInfo.get_current()
        info.service_times = "Sundays at 9am and 11am"
        info.wifi_network = "NewlifeGuest"
        info.wifi_password = "welcome123"
        info.save()
        response = self.client.get(reverse("visitor_info"))
        self.assertContains(response, "Sundays at 9am and 11am")
        self.assertContains(response, "NewlifeGuest")
        self.assertContains(response, "welcome123")

    def test_does_not_show_a_wifi_card_when_no_network_is_set(self):
        response = self.client.get(reverse("visitor_info"))
        self.assertNotContains(response, "Guest Wifi")

    def test_links_to_the_connect_card(self):
        response = self.client.get(reverse("visitor_info"))
        self.assertContains(response, reverse("connect_card"))


class StaleFollowUpsTests(TestCase):
    """stale_follow_ups - flags a follow-up nobody's touched in a while."""

    def setUp(self):
        self.member = Member.objects.create(first_name="Kofi", last_name="Asare")

    def test_flags_a_never_contacted_visitor_past_the_window(self):
        follow_up = FollowUp.objects.create(
            member=self.member, first_visit_date=timezone.localdate() - timezone.timedelta(days=10)
        )
        self.assertEqual(stale_follow_ups(), [follow_up])

    def test_does_not_flag_a_recently_started_follow_up(self):
        FollowUp.objects.create(member=self.member, first_visit_date=timezone.localdate())
        self.assertEqual(stale_follow_ups(), [])

    def test_does_not_flag_one_contacted_within_the_window(self):
        follow_up = FollowUp.objects.create(
            member=self.member, first_visit_date=timezone.localdate() - timezone.timedelta(days=10)
        )
        log_contact(follow_up, user=None)
        self.assertEqual(stale_follow_ups(), [])

    def test_flags_one_last_contacted_before_the_window(self):
        follow_up = FollowUp.objects.create(
            member=self.member, first_visit_date=timezone.localdate() - timezone.timedelta(days=30)
        )
        attempt = log_contact(follow_up, user=None)
        # ContactAttempt.contacted_at is auto_now_add, so a custom date passed
        # to create() would be silently ignored - back-date with a queryset
        # .update() instead, the same pattern used elsewhere in this project.
        ContactAttempt.objects.filter(pk=attempt.pk).update(
            contacted_at=timezone.now() - timezone.timedelta(days=10)
        )
        self.assertEqual(stale_follow_ups(), [follow_up])

    def test_excludes_joined_and_inactive_stages(self):
        old_date = timezone.localdate() - timezone.timedelta(days=30)
        FollowUp.objects.create(member=self.member, first_visit_date=old_date, stage=FollowUp.Stage.JOINED)
        other_member = Member.objects.create(first_name="Ama", last_name="Boateng")
        FollowUp.objects.create(member=other_member, first_visit_date=old_date, stage=FollowUp.Stage.INACTIVE)
        self.assertEqual(stale_follow_ups(), [])

    def test_a_custom_days_threshold_is_honored(self):
        follow_up = FollowUp.objects.create(
            member=self.member, first_visit_date=timezone.localdate() - timezone.timedelta(days=4)
        )
        self.assertEqual(stale_follow_ups(days=7), [])
        self.assertEqual(stale_follow_ups(days=3), [follow_up])

    def test_orders_the_longest_untouched_first(self):
        other_member = Member.objects.create(first_name="Ama", last_name="Boateng")
        newer = FollowUp.objects.create(
            member=self.member, first_visit_date=timezone.localdate() - timezone.timedelta(days=8)
        )
        older = FollowUp.objects.create(
            member=other_member, first_visit_date=timezone.localdate() - timezone.timedelta(days=20)
        )
        self.assertEqual(stale_follow_ups(), [older, newer])
