from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from members.models import Member

from .models import CareRequest
from .notifications import notify_pastors_of_new_care_request


class CareRequestModelTests(TestCase):
    def test_str_mentions_type_and_member(self):
        member = Member.objects.create(first_name="Efua", last_name="Owusu")
        care_request = CareRequest.objects.create(
            member=member, request_type=CareRequest.RequestType.HOME_VISIT, details="Please visit."
        )
        self.assertIn("Home visit", str(care_request))
        self.assertIn("Efua", str(care_request))

    def test_default_status_is_submitted(self):
        member = Member.objects.create(first_name="Efua", last_name="Owusu")
        care_request = CareRequest.objects.create(member=member, details="Please visit.")
        self.assertEqual(care_request.status, CareRequest.Status.SUBMITTED)


class SubmitCareRequestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="carer", password="test-pass-123")
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu", user=self.user)

    def test_member_can_submit_a_request(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("submit_care_request"),
            {"request_type": "counseling", "details": "I'd like to talk to a pastor.", "preferred_contact_method": ""},
        )
        self.assertEqual(response.status_code, 302)
        care_request = CareRequest.objects.get(member=self.member)
        self.assertEqual(care_request.request_type, "counseling")

    def test_user_without_member_profile_is_redirected(self):
        no_profile_user = User.objects.create_user(username="noprofile-care", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(
            self.client.post(reverse("submit_care_request"), {"request_type": "other", "details": "Hi."}),
            reverse("dashboard"),
        )

    @patch("care.views.notify_pastors_of_new_care_request")
    def test_submitting_notifies_pastors(self, mock_notify):
        self.client.force_login(self.user)
        self.client.post(reverse("submit_care_request"), {"request_type": "other", "details": "Please call me."})
        mock_notify.assert_called_once()


class NotifyPastorsOfNewCareRequestTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu")
        self.care_request = CareRequest.objects.create(member=self.member, details="Please visit.")

    def test_does_nothing_when_pastors_group_does_not_exist_yet(self):
        # setup_groups hasn't been run - this should not raise.
        notify_pastors_of_new_care_request(self.care_request)

    @patch("care.notifications.send_sms")
    @patch("care.notifications.send_mail")
    def test_emails_and_texts_pastors_only(self, mock_send_mail, mock_send_sms):
        pastors = Group.objects.create(name="Pastors")
        pastor_user = User.objects.create_user(username="pastor-a", password="test-pass-123", email="pastor@example.com")
        Member.objects.create(first_name="Pastor", last_name="A", phone="0244111111", user=pastor_user)
        pastor_user.groups.add(pastors)

        notify_pastors_of_new_care_request(self.care_request)

        mock_send_mail.assert_called_once()
        recipient_list = mock_send_mail.call_args[0][3]
        self.assertEqual(recipient_list, ["pastor@example.com"])
        mock_send_sms.assert_called_once()
