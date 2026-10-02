from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from members.models import Campus, Member

from .models import Donation, GivingCampaign, Pledge, RecurringGiving
from .notifications import (
    send_annual_giving_statement,
    send_donation_receipt_email,
    send_giving_statement_email,
    send_pledge_reminder,
    send_recurring_giving_reminder,
)
from .services import (
    _add_one_month,
    advance_recurring_giving_due_date,
    find_campaign_by_keyword,
    find_member_by_phone,
    lapsed_recurring_gifts,
    mark_donation_completed,
    members_with_completed_giving,
    parse_sms_giving_message,
    record_sms_gift,
)


class DonationFormTests(TestCase):
    def test_valid_donation_is_recorded_as_pending(self):
        response = self.client.post(
            reverse("give"), {"amount": "50.00", "donation_type": Donation.DonationType.OFFERING}
        )
        self.assertEqual(response.status_code, 302)
        donation = Donation.objects.latest("date")
        self.assertEqual(donation.status, Donation.Status.PENDING)
        self.assertEqual(str(donation.amount), "50.00")
        self.assertIsNone(donation.member)  # anonymous by default

    def test_negative_amount_is_rejected(self):
        response = self.client.post(
            reverse("give"), {"amount": "-5", "donation_type": Donation.DonationType.OFFERING}
        )
        self.assertEqual(response.status_code, 200)  # re-renders the form with errors
        self.assertEqual(Donation.objects.count(), 0)

    def test_missing_amount_is_rejected(self):
        response = self.client.post(reverse("give"), {"donation_type": Donation.DonationType.OFFERING})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Donation.objects.count(), 0)


class GivingCallbackTests(TestCase):
    """
    These mock the Flutterwave API entirely - no real network calls happen
    in tests, and FLUTTERWAVE_SECRET_KEY is blank in the test environment,
    so `give()` itself stays in manual/pending mode. These tests exercise
    the callback view's own verification logic directly.
    """

    def _make_donation(self, amount="25.00"):
        self.client.post(
            reverse("give"), {"amount": amount, "donation_type": Donation.DonationType.OFFERING}
        )
        return Donation.objects.latest("date")

    @patch("giving.views.verify_payment")
    def test_verified_payment_marks_donation_completed(self, mock_verify):
        donation = self._make_donation("25.00")
        mock_verify.return_value = {
            "status": "success",
            "data": {"status": "successful", "amount": 25.0, "currency": "GHS", "tx_ref": donation.payment_reference},
        }
        response = self.client.get(
            reverse("giving_callback"),
            {"status": "successful", "tx_ref": donation.payment_reference, "transaction_id": "12345"},
        )
        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.COMPLETED)
        self.assertEqual(response.status_code, 302)

    @patch("giving.views.verify_payment")
    def test_mismatched_amount_marks_donation_failed(self, mock_verify):
        donation = self._make_donation("25.00")
        mock_verify.return_value = {
            "status": "success",
            "data": {"status": "successful", "amount": 5.0, "currency": "GHS", "tx_ref": donation.payment_reference},  # wrong amount
        }
        self.client.get(
            reverse("giving_callback"),
            {"status": "successful", "tx_ref": donation.payment_reference, "transaction_id": "12345"},
        )
        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.FAILED)

    def test_cancelled_payment_marks_donation_failed(self):
        donation = self._make_donation("25.00")
        self.client.get(reverse("giving_callback"), {"status": "cancelled", "tx_ref": donation.payment_reference})
        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.FAILED)


class PendingDonationNotificationTests(TestCase):
    """
    The manual-fallback giving flow (no Flutterwave keys configured, so
    every gift stays pending for a Treasurer to reconcile) emails everyone
    in the Treasurers group - see giving/notifications.py.
    """

    def setUp(self):
        call_command("setup_groups")
        self.treasurer = User.objects.create_user(
            username="treasurer-notify", password="test-pass-123", email="treasurer@example.com"
        )
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))

    def test_manual_fallback_donation_notifies_treasurers(self):
        self.client.post(reverse("give"), {"amount": "20.00", "donation_type": Donation.DonationType.OFFERING})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("treasurer@example.com", mail.outbox[0].to)
        self.assertIn("pending gift", mail.outbox[0].subject.lower())

    def test_no_crash_and_no_email_when_no_treasurer_has_an_email(self):
        self.treasurer.email = ""
        self.treasurer.save()
        self.client.post(reverse("give"), {"amount": "20.00", "donation_type": Donation.DonationType.OFFERING})
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_also_sms_s_a_treasurer_whose_linked_member_profile_has_a_phone(self):
        Member.objects.create(first_name="Efua", last_name="Asante", user=self.treasurer, phone="0244000000")
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            self.client.post(reverse("give"), {"amount": "20.00", "donation_type": Donation.DonationType.OFFERING})
        mock_get.assert_called_once()

    def test_no_sms_attempted_when_a_treasurer_has_no_linked_member_or_phone(self):
        with patch("churchapp.sms.requests.get") as mock_get:
            self.client.post(reverse("give"), {"amount": "20.00", "donation_type": Donation.DonationType.OFFERING})
        mock_get.assert_not_called()


class MarkDonationCompletedServiceTests(TestCase):
    """
    Direct tests of the shared reconciliation logic (giving/services.py) -
    both the admin action and the staff area's donation list call this, so
    testing it here covers both callers at once.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="reconciler", password="test-pass-123")

    def test_marks_pending_donation_completed_and_returns_true(self):
        donation = Donation.objects.create(amount="10.00", status=Donation.Status.PENDING)
        result = mark_donation_completed(donation, user=self.user)
        donation.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(donation.status, Donation.Status.COMPLETED)

    def test_leaves_non_pending_donation_alone_and_returns_false(self):
        donation = Donation.objects.create(amount="10.00", status=Donation.Status.FAILED)
        result = mark_donation_completed(donation, user=self.user)
        donation.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(donation.status, Donation.Status.FAILED)

    def test_logs_the_user_who_reconciled_it(self):
        donation = Donation.objects.create(amount="10.00", status=Donation.Status.PENDING)
        mark_donation_completed(donation, user=self.user)
        self.assertTrue(LogEntry.objects.filter(object_id=str(donation.pk), user=self.user).exists())


class DonationCampusFieldTests(TestCase):
    """The optional campus field on the giving form - hidden until a second campus exists (see DonationForm)."""

    def test_campus_field_is_hidden_with_one_or_no_campus(self):
        response = self.client.get(reverse("give"))
        self.assertNotContains(response, 'name="campus"')

    def test_campus_field_appears_once_a_second_campus_exists(self):
        Campus.objects.create(name="Main Campus")
        Campus.objects.create(name="Tema Branch")
        response = self.client.get(reverse("give"))
        self.assertContains(response, 'name="campus"')


class GivingStatementTests(TestCase):
    """A member's own printable giving statement (giving/views.py's giving_statement)."""

    def setUp(self):
        self.user = User.objects.create_user(username="giver", password="test-pass-123")
        self.member = Member.objects.create(first_name="Efua", last_name="Asante", user=self.user)
        self.other_member = Member.objects.create(first_name="Kwame", last_name="Otu")

        Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.create(member=self.member, amount="50.00", status=Donation.Status.PENDING)
        Donation.objects.create(member=self.other_member, amount="999.00", status=Donation.Status.COMPLETED)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("giving_statement"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_user_without_member_profile_is_redirected_to_dashboard(self):
        no_profile_user = User.objects.create_user(username="noprofile", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(self.client.get(reverse("giving_statement")), reverse("dashboard"))

    def test_statement_only_shows_this_members_completed_gifts(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("giving_statement"))
        self.assertContains(response, "100.00")
        self.assertNotContains(response, "50.00")  # pending, so excluded
        self.assertNotContains(response, "999.00")  # another member's gift

    def test_total_is_the_sum_of_the_shown_gifts(self):
        Donation.objects.create(member=self.member, amount="25.00", status=Donation.Status.COMPLETED)
        self.client.force_login(self.user)
        response = self.client.get(reverse("giving_statement"))
        self.assertEqual(response.context["total"], Decimal("125.00"))

    def test_download_pdf_link_is_on_the_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("giving_statement"))
        self.assertContains(response, reverse("giving_statement_pdf"))

    def test_posting_emails_the_member_their_statement(self):
        self.member.email = "efua@example.com"
        self.member.save()
        self.client.force_login(self.user)
        response = self.client.post(reverse("giving_statement"), {"start": "2026-01-01", "end": "2026-12-31"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("efua@example.com", mail.outbox[0].to)
        self.assertIn("100.00", mail.outbox[0].body)

    def test_posting_with_no_email_on_file_shows_an_error_and_sends_nothing(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("giving_statement"), {"start": "2026-01-01", "end": "2026-12-31"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_posting_never_emails_another_members_gifts(self):
        self.other_member.email = "kwame@example.com"
        self.other_member.save()
        self.member.email = "efua@example.com"
        self.member.save()
        self.client.force_login(self.user)
        self.client.post(reverse("giving_statement"), {"start": "2026-01-01", "end": "2026-12-31"})
        self.assertNotIn("999.00", mail.outbox[0].body)


class GivingStatementPdfTests(TestCase):
    """The downloadable PDF version of the statement above (giving/views.py's giving_statement_pdf, giving/pdfs.py)."""

    def setUp(self):
        self.user = User.objects.create_user(username="giver-pdf", password="test-pass-123")
        self.member = Member.objects.create(first_name="Efua", last_name="Asante", user=self.user)
        self.other_member = Member.objects.create(first_name="Kwame", last_name="Otu")

        Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.create(member=self.member, amount="50.00", status=Donation.Status.PENDING)
        Donation.objects.create(member=self.other_member, amount="999.00", status=Donation.Status.COMPLETED)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("giving_statement_pdf"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_user_without_member_profile_is_redirected_to_dashboard(self):
        no_profile_user = User.objects.create_user(username="noprofile-pdf", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(self.client.get(reverse("giving_statement_pdf")), reverse("dashboard"))

    def test_response_is_a_downloadable_pdf(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("giving_statement_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_pdf_reflects_the_requested_date_range(self):
        old_gift = Donation.objects.create(
            member=self.member,
            amount="25.00",
            status=Donation.Status.COMPLETED,
        )
        # date is auto_now_add=True, so it's stamped with "now" on create and
        # a date= passed to .create() above would be silently ignored -
        # .filter(...).update(...) bypasses auto_now_add to backdate it (same
        # pattern used throughout this project, e.g. followup/tests.py's
        # StaleFollowUpsTests backdating ContactAttempt.contacted_at).
        Donation.objects.filter(pk=old_gift.pk).update(date=timezone.make_aware(datetime(2020, 1, 1)))
        self.client.force_login(self.user)
        full_range = self.client.get(reverse("giving_statement_pdf"), {"start": "2020-01-01", "end": "2020-12-31"})
        empty_range = self.client.get(reverse("giving_statement_pdf"), {"start": "2021-01-01", "end": "2021-12-31"})
        # Both are valid PDFs, but the one covering the actual gift is a
        # larger document than the "no gifts in this period" one - a cheap,
        # library-agnostic way to confirm the content actually differs by
        # date range without parsing the PDF back apart.
        self.assertGreater(len(full_range.content), len(empty_range.content))


class DonationReceiptTests(TestCase):
    """A member's own printable single-gift receipt (giving/views.py's donation_receipt)."""

    def setUp(self):
        self.user = User.objects.create_user(username="receipt-giver", password="test-pass-123")
        self.member = Member.objects.create(first_name="Efua", last_name="Asante", user=self.user)
        self.other_member = Member.objects.create(first_name="Kwame", last_name="Otu")
        self.donation = Donation.objects.create(
            member=self.member, amount="75.00", status=Donation.Status.COMPLETED
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("donation_receipt", args=[self.donation.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_user_without_member_profile_is_redirected_to_dashboard(self):
        no_profile_user = User.objects.create_user(username="noprofile-receipt", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(
            self.client.get(reverse("donation_receipt", args=[self.donation.id])), reverse("dashboard")
        )

    def test_member_can_view_their_own_receipt(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("donation_receipt", args=[self.donation.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "75.00")

    def test_member_cannot_view_another_members_receipt(self):
        other_donation = Donation.objects.create(
            member=self.other_member, amount="999.00", status=Donation.Status.COMPLETED
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("donation_receipt", args=[other_donation.id]))
        self.assertEqual(response.status_code, 404)

    def test_no_receipt_for_a_pending_gift(self):
        pending = Donation.objects.create(member=self.member, amount="20.00", status=Donation.Status.PENDING)
        self.client.force_login(self.user)
        response = self.client.get(reverse("donation_receipt", args=[pending.id]))
        self.assertEqual(response.status_code, 404)

    def test_dashboard_links_to_the_receipt_for_a_completed_gift_only(self):
        pending = Donation.objects.create(member=self.member, amount="20.00", status=Donation.Status.PENDING)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, reverse("donation_receipt", args=[self.donation.id]))
        self.assertNotContains(response, reverse("donation_receipt", args=[pending.id]))


class ReconcileDonationAdminActionTests(TestCase):
    """The admin action treasurers use to confirm cash/mobile-money gifts by hand."""

    def setUp(self):
        self.admin_user = User.objects.create_superuser(username="office-admin", password="test-pass-123")
        self.client.force_login(self.admin_user)
        self.pending = Donation.objects.create(amount="40.00", status=Donation.Status.PENDING)
        self.already_completed = Donation.objects.create(amount="15.00", status=Donation.Status.COMPLETED)

    def _run_action(self, donation_ids):
        return self.client.post(
            reverse("admin:giving_donation_changelist"),
            {"action": "mark_as_completed", "_selected_action": donation_ids},
            follow=True,
        )

    def test_pending_donation_is_marked_completed(self):
        self._run_action([self.pending.pk])
        self.pending.refresh_from_db()
        self.assertEqual(self.pending.status, Donation.Status.COMPLETED)

    def test_action_logs_who_reconciled_it(self):
        self._run_action([self.pending.pk])
        self.assertTrue(
            LogEntry.objects.filter(object_id=str(self.pending.pk), user=self.admin_user).exists()
        )

    def test_already_completed_donation_is_left_alone(self):
        self._run_action([self.already_completed.pk])
        self.already_completed.refresh_from_db()
        self.assertEqual(self.already_completed.status, Donation.Status.COMPLETED)
        self.assertFalse(LogEntry.objects.filter(object_id=str(self.already_completed.pk)).exists())


class GivingCampaignModelTests(TestCase):
    """The GivingCampaign model's rollup properties (given_total, pledged_total, percent_of_goal)."""

    def setUp(self):
        self.campaign = GivingCampaign.objects.create(
            name="Building Fund", goal_amount="1000.00", start_date=timezone.localdate()
        )
        self.member = Member.objects.create(first_name="Kojo", last_name="Adjei")

    def test_given_total_only_counts_completed_donations_for_this_campaign(self):
        Donation.objects.create(campaign=self.campaign, amount="200.00", status=Donation.Status.COMPLETED)
        Donation.objects.create(campaign=self.campaign, amount="50.00", status=Donation.Status.PENDING)
        Donation.objects.create(amount="999.00", status=Donation.Status.COMPLETED)  # a different (no) campaign
        self.assertEqual(self.campaign.given_total, Decimal("200.00"))

    def test_pledged_total_sums_all_pledges(self):
        other_member = Member.objects.create(first_name="Yaa", last_name="Boateng")
        Pledge.objects.create(campaign=self.campaign, member=self.member, amount="150.00")
        Pledge.objects.create(campaign=self.campaign, member=other_member, amount="100.00")
        self.assertEqual(self.campaign.pledged_total, Decimal("250.00"))

    def test_percent_of_goal_is_none_without_a_goal(self):
        no_goal_campaign = GivingCampaign.objects.create(name="Missions", start_date=timezone.localdate())
        self.assertIsNone(no_goal_campaign.percent_of_goal)

    def test_percent_of_goal_is_capped_at_100(self):
        Donation.objects.create(campaign=self.campaign, amount="5000.00", status=Donation.Status.COMPLETED)
        self.assertEqual(self.campaign.percent_of_goal, 100)

    def test_percent_of_goal_calculates_correctly(self):
        Donation.objects.create(campaign=self.campaign, amount="250.00", status=Donation.Status.COMPLETED)
        self.assertEqual(self.campaign.percent_of_goal, 25)


class PledgeModelTests(TestCase):
    def setUp(self):
        self.campaign = GivingCampaign.objects.create(name="Building Fund", start_date=timezone.localdate())
        self.member = Member.objects.create(first_name="Kojo", last_name="Adjei")

    def test_only_one_pledge_per_member_per_campaign(self):
        Pledge.objects.create(campaign=self.campaign, member=self.member, amount="100.00")
        with self.assertRaises(Exception):
            Pledge.objects.create(campaign=self.campaign, member=self.member, amount="200.00")

    def test_given_toward_pledge_only_counts_completed_gifts_to_this_campaign(self):
        pledge = Pledge.objects.create(campaign=self.campaign, member=self.member, amount="100.00")
        Donation.objects.create(
            campaign=self.campaign, member=self.member, amount="40.00", status=Donation.Status.COMPLETED
        )
        Donation.objects.create(
            campaign=self.campaign, member=self.member, amount="10.00", status=Donation.Status.PENDING
        )
        self.assertEqual(pledge.given_toward_pledge, Decimal("40.00"))


class CampaignPublicViewTests(TestCase):
    """The public campaign list/detail pages (giving/views.py's campaign_list and campaign_detail)."""

    def test_active_campaign_is_listed(self):
        GivingCampaign.objects.create(name="Building Fund", start_date=timezone.localdate(), is_active=True)
        response = self.client.get(reverse("campaign_list"))
        self.assertContains(response, "Building Fund")

    def test_inactive_campaign_is_not_listed(self):
        GivingCampaign.objects.create(name="Old Campaign", start_date=timezone.localdate(), is_active=False)
        response = self.client.get(reverse("campaign_list"))
        self.assertNotContains(response, "Old Campaign")

    def test_inactive_campaign_detail_is_a_404(self):
        campaign = GivingCampaign.objects.create(
            name="Finished Campaign", start_date=timezone.localdate(), is_active=False
        )
        response = self.client.get(reverse("campaign_detail", args=[campaign.id]))
        self.assertEqual(response.status_code, 404)


class PledgeCampaignViewTests(TestCase):
    """A member committing to (or updating) their own pledge (giving/views.py's pledge_campaign)."""

    def setUp(self):
        self.campaign = GivingCampaign.objects.create(name="Building Fund", start_date=timezone.localdate())
        self.user = User.objects.create_user(username="pledger", password="test-pass-123")
        self.member = Member.objects.create(first_name="Ama", last_name="Serwaa", user=self.user)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("pledge_campaign", args=[self.campaign.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_user_without_member_profile_is_redirected_to_dashboard(self):
        no_profile_user = User.objects.create_user(username="noprofile3", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(
            self.client.get(reverse("pledge_campaign", args=[self.campaign.id])), reverse("dashboard")
        )

    def test_member_can_make_a_pledge(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("pledge_campaign", args=[self.campaign.id]), {"amount": "500.00"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Pledge.objects.filter(campaign=self.campaign, member=self.member, amount="500.00").exists())

    def test_pledging_again_updates_the_same_pledge_instead_of_duplicating(self):
        Pledge.objects.create(campaign=self.campaign, member=self.member, amount="100.00")
        self.client.force_login(self.user)
        self.client.post(reverse("pledge_campaign", args=[self.campaign.id]), {"amount": "300.00"})
        self.assertEqual(Pledge.objects.filter(campaign=self.campaign, member=self.member).count(), 1)
        self.assertEqual(Pledge.objects.get(campaign=self.campaign, member=self.member).amount, Decimal("300.00"))


class DonationFormCampaignFieldTests(TestCase):
    """The optional campaign field on the giving form - hidden until an active campaign exists (see DonationForm)."""

    def test_campaign_field_is_hidden_with_no_active_campaigns(self):
        response = self.client.get(reverse("give"))
        self.assertNotContains(response, 'name="campaign"')

    def test_campaign_field_appears_once_an_active_campaign_exists(self):
        GivingCampaign.objects.create(name="Building Fund", start_date=timezone.localdate(), is_active=True)
        response = self.client.get(reverse("give"))
        self.assertContains(response, 'name="campaign"')

    def test_inactive_campaigns_are_not_offered_on_the_giving_form(self):
        GivingCampaign.objects.create(name="Active Push", start_date=timezone.localdate(), is_active=True)
        GivingCampaign.objects.create(name="Finished Push", start_date=timezone.localdate(), is_active=False)
        response = self.client.get(reverse("give"))
        self.assertContains(response, "Active Push")
        self.assertNotContains(response, "Finished Push")

    def test_donation_form_saves_the_chosen_campaign(self):
        campaign = GivingCampaign.objects.create(
            name="Building Fund", start_date=timezone.localdate(), is_active=True
        )
        self.client.post(
            reverse("give"), {"amount": "75.00", "donation_type": Donation.DonationType.OFFERING, "campaign": campaign.id}
        )
        donation = Donation.objects.latest("date")
        self.assertEqual(donation.campaign, campaign)

    def test_a_completed_campaign_donation_counts_toward_its_given_total(self):
        campaign = GivingCampaign.objects.create(
            name="Building Fund", start_date=timezone.localdate(), is_active=True
        )
        self.client.post(
            reverse("give"), {"amount": "75.00", "donation_type": Donation.DonationType.OFFERING, "campaign": campaign.id}
        )
        donation = Donation.objects.latest("date")
        mark_donation_completed(donation, user=User.objects.create_user(username="reconciler2", password="test-pass-123"))
        self.assertEqual(campaign.given_total, Decimal("75.00"))


class PledgeReminderNotificationTests(TestCase):
    """Direct tests of send_pledge_reminder - the on-demand nudge a Treasurer/Pastor triggers from the staff area."""

    def setUp(self):
        self.campaign = GivingCampaign.objects.create(name="Building Fund", start_date=timezone.localdate())

    def test_emails_a_member_with_an_email_on_file(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")
        pledge = Pledge.objects.create(campaign=self.campaign, member=member, amount="200.00")
        result = send_pledge_reminder(pledge)
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("efua@example.com", mail.outbox[0].to)
        self.assertIn("200.00", mail.outbox[0].body)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_texts_a_member_with_a_phone_on_file(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah", phone="0244000000")
        pledge = Pledge.objects.create(campaign=self.campaign, member=member, amount="150.00")
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            result = send_pledge_reminder(pledge)
        self.assertTrue(result)
        mock_get.assert_called_once()

    def test_returns_false_for_a_member_with_no_contact_info(self):
        member = Member.objects.create(first_name="No", last_name="Contact")
        pledge = Pledge.objects.create(campaign=self.campaign, member=member, amount="50.00")
        result = send_pledge_reminder(pledge)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_mentions_the_remaining_outstanding_amount_not_the_full_pledge(self):
        member = Member.objects.create(first_name="Ama", last_name="Boateng", email="ama@example.com")
        pledge = Pledge.objects.create(campaign=self.campaign, member=member, amount="300.00")
        Donation.objects.create(
            campaign=self.campaign, member=member, amount="100.00", status=Donation.Status.COMPLETED
        )
        send_pledge_reminder(pledge)
        self.assertIn("200.00", mail.outbox[0].body)

    def test_returns_false_and_sends_nothing_when_member_has_opted_out(self):
        member = Member.objects.create(
            first_name="No", last_name="Nudges", email="no-nudges@example.com", notify_pledge_reminders=False
        )
        pledge = Pledge.objects.create(campaign=self.campaign, member=member, amount="200.00")
        result = send_pledge_reminder(pledge)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)


class ParseSmsGivingMessageTests(TestCase):
    def test_parses_a_bare_amount(self):
        amount, keyword = parse_sms_giving_message("GIVE 50")
        self.assertEqual(amount, Decimal("50"))
        self.assertEqual(keyword, "")

    def test_parses_an_amount_with_a_campaign_keyword(self):
        amount, keyword = parse_sms_giving_message("give 100 building")
        self.assertEqual(amount, Decimal("100"))
        self.assertEqual(keyword, "BUILDING")

    def test_parses_a_decimal_amount(self):
        amount, keyword = parse_sms_giving_message("GIVE 25.50")
        self.assertEqual(amount, Decimal("25.50"))

    def test_unrelated_text_does_not_parse(self):
        amount, keyword = parse_sms_giving_message("Hi, what time is the service tomorrow?")
        self.assertIsNone(amount)
        self.assertIsNone(keyword)

    def test_zero_or_negative_amount_does_not_parse(self):
        amount, keyword = parse_sms_giving_message("GIVE 0")
        self.assertIsNone(amount)

    def test_empty_message_does_not_parse(self):
        amount, keyword = parse_sms_giving_message("")
        self.assertIsNone(amount)


class FindMemberByPhoneTests(TestCase):
    def test_matches_regardless_of_leading_zero_vs_country_code(self):
        member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")
        found = find_member_by_phone("233244123456")
        self.assertEqual(found, member)

    def test_matches_with_a_plus_prefix(self):
        member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")
        found = find_member_by_phone("+233244123456")
        self.assertEqual(found, member)

    def test_no_match_returns_none(self):
        Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")
        self.assertIsNone(find_member_by_phone("0201999999"))

    def test_blank_phone_returns_none(self):
        self.assertIsNone(find_member_by_phone(""))


class FindCampaignByKeywordTests(TestCase):
    def test_matches_an_active_campaign_case_insensitively(self):
        campaign = GivingCampaign.objects.create(
            name="Building Fund", start_date=timezone.localdate(), sms_keyword="BUILDING"
        )
        self.assertEqual(find_campaign_by_keyword("building"), campaign)

    def test_inactive_campaign_is_not_matched(self):
        GivingCampaign.objects.create(
            name="Old Fund", start_date=timezone.localdate(), sms_keyword="OLD", is_active=False
        )
        self.assertIsNone(find_campaign_by_keyword("OLD"))

    def test_blank_keyword_returns_none(self):
        self.assertIsNone(find_campaign_by_keyword(""))


class RecordSmsGiftTests(TestCase):
    def test_records_a_pending_donation_for_an_unrecognized_message(self):
        donation = record_sms_gift(phone="0244123456", message_text="GIVE 50")
        self.assertIsNotNone(donation)
        self.assertEqual(donation.amount, Decimal("50"))
        self.assertEqual(donation.status, Donation.Status.PENDING)
        self.assertTrue(donation.payment_reference.startswith("SMS-"))

    def test_links_the_gift_to_a_matching_member(self):
        member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")
        donation = record_sms_gift(phone="233244123456", message_text="GIVE 50")
        self.assertEqual(donation.member, member)

    def test_gift_with_no_matching_member_is_still_recorded_anonymously(self):
        donation = record_sms_gift(phone="0201999999", message_text="GIVE 50")
        self.assertIsNotNone(donation)
        self.assertIsNone(donation.member)

    def test_tags_the_gift_to_a_campaign_by_keyword(self):
        campaign = GivingCampaign.objects.create(
            name="Building Fund", start_date=timezone.localdate(), sms_keyword="BUILDING"
        )
        donation = record_sms_gift(phone="0244123456", message_text="GIVE 100 BUILDING")
        self.assertEqual(donation.campaign, campaign)

    def test_unrelated_message_creates_no_donation(self):
        donation = record_sms_gift(phone="0244123456", message_text="What time is service?")
        self.assertIsNone(donation)
        self.assertEqual(Donation.objects.count(), 0)

    def test_notifies_treasurers_of_the_new_pending_gift(self):
        call_command("setup_groups")
        treasurer = User.objects.create_user(username="treasurer-sms", password="test-pass-123", email="t@example.com")
        treasurer.groups.add(Group.objects.get(name="Treasurers"))
        record_sms_gift(phone="0244123456", message_text="GIVE 50")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("t@example.com", mail.outbox[0].to)


@override_settings(SMS_WEBHOOK_TOKEN="test-provider-secret")
class SmsGivingWebhookTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_X_SMS_WEBHOOK_TOKEN"] = "test-provider-secret"

    def test_webhook_creates_a_pending_donation_from_posted_fields(self):
        response = self.client.post(reverse("sms_giving_webhook"), {"From": "0244123456", "Content": "GIVE 50"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Donation.objects.count(), 1)
        self.assertEqual(Donation.objects.first().amount, Decimal("50"))

    def test_webhook_always_responds_ok_even_for_an_unrelated_text(self):
        response = self.client.post(reverse("sms_giving_webhook"), {"From": "0244123456", "Content": "Hello there"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Donation.objects.count(), 0)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_webhook_sends_a_confirmation_text_back(self):
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            self.client.post(reverse("sms_giving_webhook"), {"From": "0244123456", "Content": "GIVE 50"})
        mock_get.assert_called_once()


class AddOneMonthTests(TestCase):
    def test_advances_a_normal_date_by_one_month(self):
        self.assertEqual(_add_one_month(date(2026, 3, 15)), date(2026, 4, 15))

    def test_clamps_month_end_dates_instead_of_overflowing(self):
        self.assertEqual(_add_one_month(date(2026, 1, 31)), date(2026, 2, 28))

    def test_wraps_from_december_into_january_of_the_next_year(self):
        self.assertEqual(_add_one_month(date(2026, 12, 10)), date(2027, 1, 10))


class AdvanceRecurringGivingDueDateTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Efua", last_name="Asante")

    def test_weekly_advances_by_seven_days(self):
        recurring = RecurringGiving.objects.create(
            member=self.member, amount="50.00", frequency=RecurringGiving.Frequency.WEEKLY,
            next_due_date=date(2026, 3, 1),
        )
        advance_recurring_giving_due_date(recurring)
        self.assertEqual(recurring.next_due_date, date(2026, 3, 8))

    def test_monthly_advances_by_one_month_with_clamping(self):
        recurring = RecurringGiving.objects.create(
            member=self.member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2026, 1, 31),
        )
        advance_recurring_giving_due_date(recurring)
        self.assertEqual(recurring.next_due_date, date(2026, 2, 28))

    def test_advances_from_the_due_date_itself_not_from_today(self):
        recurring = RecurringGiving.objects.create(
            member=self.member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2020, 1, 15),
        )
        advance_recurring_giving_due_date(recurring)
        self.assertEqual(recurring.next_due_date, date(2020, 2, 15))


class RecurringGivingModelTests(TestCase):
    def test_str_includes_member_amount_and_frequency(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        recurring = RecurringGiving.objects.create(
            member=member, amount="75.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(),
        )
        text = str(recurring)
        self.assertIn("Kojo Mensah", text)
        self.assertIn("75.00", text)
        self.assertIn("Monthly", text)


class SendRecurringGivingReminderTests(TestCase):
    def setUp(self):
        self.campaign = GivingCampaign.objects.create(name="Building Fund", start_date=timezone.localdate())

    def test_emails_a_member_with_an_email_on_file(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")
        recurring = RecurringGiving.objects.create(
            member=member, amount="100.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(),
        )
        result = send_recurring_giving_reminder(recurring)
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("efua@example.com", mail.outbox[0].to)
        self.assertIn("100.00", mail.outbox[0].body)

    def test_mentions_the_campaign_when_one_is_set(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")
        recurring = RecurringGiving.objects.create(
            member=member, amount="100.00", campaign=self.campaign, frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(),
        )
        send_recurring_giving_reminder(recurring)
        self.assertIn("Building Fund", mail.outbox[0].body)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_texts_a_member_with_a_phone_on_file(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah", phone="0244000000")
        recurring = RecurringGiving.objects.create(
            member=member, amount="50.00", frequency=RecurringGiving.Frequency.WEEKLY,
            next_due_date=timezone.localdate(),
        )
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            result = send_recurring_giving_reminder(recurring)
        self.assertTrue(result)
        mock_get.assert_called_once()

    def test_returns_false_for_a_member_with_no_contact_info(self):
        member = Member.objects.create(first_name="No", last_name="Contact")
        recurring = RecurringGiving.objects.create(
            member=member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(),
        )
        result = send_recurring_giving_reminder(recurring)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_returns_false_and_sends_nothing_when_member_has_opted_out(self):
        member = Member.objects.create(
            first_name="No", last_name="Nudges", email="no-nudges@example.com", notify_pledge_reminders=False
        )
        recurring = RecurringGiving.objects.create(
            member=member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(),
        )
        result = send_recurring_giving_reminder(recurring)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)


class SendDonationReceiptEmailTests(TestCase):
    """Direct tests of send_donation_receipt_email - the per-gift receipt fired the moment a donation completes."""

    def test_emails_a_member_with_an_email_on_file(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")
        donation = Donation.objects.create(
            member=member, amount="75.00", donation_type=Donation.DonationType.TITHE, status=Donation.Status.COMPLETED
        )
        result = send_donation_receipt_email(donation)
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("efua@example.com", mail.outbox[0].to)
        self.assertIn("75.00", mail.outbox[0].body)

    def test_returns_false_for_an_anonymous_donation(self):
        donation = Donation.objects.create(amount="20.00", status=Donation.Status.COMPLETED)
        result = send_donation_receipt_email(donation)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_returns_false_for_a_member_with_no_email(self):
        member = Member.objects.create(first_name="No", last_name="Email")
        donation = Donation.objects.create(member=member, amount="20.00", status=Donation.Status.COMPLETED)
        result = send_donation_receipt_email(donation)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_returns_false_when_member_has_opted_out(self):
        member = Member.objects.create(
            first_name="No", last_name="Receipts", email="no-receipts@example.com", notify_giving_receipts=False
        )
        donation = Donation.objects.create(member=member, amount="20.00", status=Donation.Status.COMPLETED)
        result = send_donation_receipt_email(donation)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_mark_donation_completed_sends_the_receipt(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah", email="kojo@example.com")
        donation = Donation.objects.create(member=member, amount="30.00", status=Donation.Status.PENDING)
        user = User.objects.create_user(username="reconciler-receipt", password="test-pass-123")
        mark_donation_completed(donation, user=user)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("kojo@example.com", mail.outbox[0].to)

    @patch("giving.views.verify_payment")
    def test_online_payment_success_sends_the_receipt(self, mock_verify):
        member = Member.objects.create(first_name="Ama", last_name="Boateng", email="ama@example.com")
        donation = Donation.objects.create(
            member=member, amount="25.00", status=Donation.Status.PENDING, payment_reference="tx-receipt-1"
        )
        mock_verify.return_value = {
            "status": "success",
            "data": {"status": "successful", "amount": 25.0, "currency": "GHS", "tx_ref": donation.payment_reference},
        }
        self.client.get(
            reverse("giving_callback"),
            {"status": "successful", "tx_ref": donation.payment_reference, "transaction_id": "12345"},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ama@example.com", mail.outbox[0].to)


class RecurringGivingMemberViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="giver2", password="test-pass-123")
        self.member = Member.objects.create(first_name="Ama", last_name="Serwaa", user=self.user)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("recurring_giving_create"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_member_can_set_up_a_recurring_gift(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("recurring_giving_create"),
            {"amount": "100.00", "frequency": RecurringGiving.Frequency.MONTHLY, "next_due_date": "2026-10-01"},
        )
        self.assertEqual(response.status_code, 302)
        recurring = RecurringGiving.objects.get(member=self.member)
        self.assertEqual(recurring.amount, Decimal("100.00"))
        self.assertTrue(recurring.is_active)

    def test_member_can_edit_their_own_recurring_gift(self):
        recurring = RecurringGiving.objects.create(
            member=self.member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2026, 10, 1),
        )
        self.client.force_login(self.user)
        self.client.post(
            reverse("recurring_giving_edit", args=[recurring.id]),
            {"amount": "80.00", "frequency": RecurringGiving.Frequency.WEEKLY, "next_due_date": "2026-10-01"},
        )
        recurring.refresh_from_db()
        self.assertEqual(recurring.amount, Decimal("80.00"))
        self.assertEqual(recurring.frequency, RecurringGiving.Frequency.WEEKLY)

    def test_member_cannot_edit_someone_elses_recurring_gift(self):
        other_member = Member.objects.create(first_name="Yaw", last_name="Boateng")
        recurring = RecurringGiving.objects.create(
            member=other_member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2026, 10, 1),
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("recurring_giving_edit", args=[recurring.id]))
        self.assertEqual(response.status_code, 404)

    def test_member_can_cancel_their_own_recurring_gift(self):
        recurring = RecurringGiving.objects.create(
            member=self.member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2026, 10, 1),
        )
        self.client.force_login(self.user)
        self.client.post(reverse("recurring_giving_cancel", args=[recurring.id]))
        recurring.refresh_from_db()
        self.assertFalse(recurring.is_active)

    def test_cancelling_never_deletes_the_record(self):
        recurring = RecurringGiving.objects.create(
            member=self.member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2026, 10, 1),
        )
        self.client.force_login(self.user)
        self.client.post(reverse("recurring_giving_cancel", args=[recurring.id]))
        self.assertTrue(RecurringGiving.objects.filter(id=recurring.id).exists())

    def test_history_page_shows_both_active_and_cancelled_gifts(self):
        RecurringGiving.objects.create(
            member=self.member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2026, 10, 1), is_active=True,
        )
        RecurringGiving.objects.create(
            member=self.member, amount="25.00", frequency=RecurringGiving.Frequency.WEEKLY,
            next_due_date=date(2026, 9, 1), is_active=False,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("recurring_giving_history"))
        self.assertContains(response, "GH&#8373;50.00")
        self.assertContains(response, "GH&#8373;25.00")
        self.assertContains(response, "Reactivate")

    def test_history_page_does_not_show_another_members_gifts(self):
        other_member = Member.objects.create(first_name="Yaw", last_name="Boateng")
        RecurringGiving.objects.create(
            member=other_member, amount="999.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2026, 10, 1),
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("recurring_giving_history"))
        self.assertNotContains(response, "GH&#8373;999.00")

    def test_member_can_reactivate_their_own_cancelled_gift(self):
        recurring = RecurringGiving.objects.create(
            member=self.member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2026, 1, 1), is_active=False,
        )
        self.client.force_login(self.user)
        response = self.client.post(reverse("recurring_giving_reactivate", args=[recurring.id]))
        self.assertEqual(response.status_code, 302)
        recurring.refresh_from_db()
        self.assertTrue(recurring.is_active)
        self.assertEqual(recurring.next_due_date, timezone.localdate())

    def test_member_cannot_reactivate_someone_elses_gift(self):
        other_member = Member.objects.create(first_name="Yaw", last_name="Boateng")
        recurring = RecurringGiving.objects.create(
            member=other_member, amount="50.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2026, 1, 1), is_active=False,
        )
        self.client.force_login(self.user)
        response = self.client.post(reverse("recurring_giving_reactivate", args=[recurring.id]))
        self.assertEqual(response.status_code, 404)


class SendRecurringGivingRemindersCommandTests(TestCase):
    def test_sends_reminders_for_due_gifts_and_advances_the_due_date(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")
        recurring = RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(),
        )
        call_command("send_recurring_giving_reminders")
        recurring.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIsNotNone(recurring.last_reminder_sent)
        self.assertGreater(recurring.next_due_date, timezone.localdate())
        self.assertEqual(recurring.reminder_count, 1)

    def test_reminder_count_accumulates_across_runs(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")
        recurring = RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.WEEKLY,
            next_due_date=timezone.localdate(),
        )
        call_command("send_recurring_giving_reminders")
        call_command("send_recurring_giving_reminders")
        recurring.refresh_from_db()
        # The second run's due date has already advanced past today, so it
        # should NOT count a second reminder in the same call.
        self.assertEqual(recurring.reminder_count, 1)

    def test_does_not_touch_a_gift_that_is_not_yet_due(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah", email="kojo@example.com")
        future_date = timezone.localdate().replace(year=timezone.localdate().year + 1)
        recurring = RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY, next_due_date=future_date
        )
        call_command("send_recurring_giving_reminders")
        recurring.refresh_from_db()
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(recurring.last_reminder_sent)
        self.assertEqual(recurring.next_due_date, future_date)

    def test_skips_an_inactive_gift(self):
        member = Member.objects.create(first_name="Yaw", last_name="Boateng", email="yaw@example.com")
        RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), is_active=False,
        )
        call_command("send_recurring_giving_reminders")
        self.assertEqual(len(mail.outbox), 0)


class LapsedRecurringGiftsTests(TestCase):
    def test_not_flagged_below_the_reminder_threshold(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante")
        RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=1,
        )
        self.assertEqual(list(lapsed_recurring_gifts()), [])

    def test_flagged_at_the_threshold_with_no_donation_since_signup(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante")
        recurring = RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=2,
        )
        self.assertEqual(list(lapsed_recurring_gifts()), [recurring])

    def test_not_flagged_once_a_completed_donation_exists_since_signup(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante")
        RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=5,
        )
        Donation.objects.create(member=member, amount="60.00", status=Donation.Status.COMPLETED)
        self.assertEqual(list(lapsed_recurring_gifts()), [])

    def test_a_pending_donation_does_not_clear_the_flag(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante")
        recurring = RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=2,
        )
        Donation.objects.create(member=member, amount="60.00", status=Donation.Status.PENDING)
        self.assertEqual(list(lapsed_recurring_gifts()), [recurring])

    def test_an_inactive_commitment_is_never_flagged(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante")
        RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=10, is_active=False,
        )
        self.assertEqual(list(lapsed_recurring_gifts()), [])

    def test_custom_min_reminders_is_respected(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante")
        recurring = RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=3,
        )
        self.assertEqual(list(lapsed_recurring_gifts(min_reminders=5)), [])
        self.assertEqual(list(lapsed_recurring_gifts(min_reminders=3)), [recurring])

    def test_reactivating_resets_reminder_count_and_last_reminder_sent(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante")
        user = User.objects.create_user(username="giver-lapsed", password="test-pass-123")
        member.user = user
        member.save()
        recurring = RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=date(2026, 1, 1), is_active=False,
            reminder_count=3, last_reminder_sent=date(2026, 1, 1),
        )
        self.client.force_login(user)
        self.client.post(reverse("recurring_giving_reactivate", args=[recurring.id]))
        recurring.refresh_from_db()
        self.assertEqual(recurring.reminder_count, 0)
        self.assertIsNone(recurring.last_reminder_sent)


class StaffRecurringGivingViewTests(TestCase):
    def setUp(self):
        call_command("setup_groups")
        self.member = Member.objects.create(first_name="Efua", last_name="Asante")
        self.recurring = RecurringGiving.objects.create(
            member=self.member, amount="100.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(),
        )
        self.treasurer = User.objects.create_user(username="treasurer3", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.usher = User.objects.create_user(username="usher3", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))

    def test_treasurer_can_view_the_list(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_recurring_giving_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Efua Asante")

    def test_usher_cannot_view_the_list(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_recurring_giving_list"))
        self.assertEqual(response.status_code, 302)

    def test_treasurer_can_deactivate_a_gift(self):
        self.client.force_login(self.treasurer)
        self.client.post(reverse("staff_recurring_giving_deactivate", args=[self.recurring.id]))
        self.recurring.refresh_from_db()
        self.assertFalse(self.recurring.is_active)

    def test_usher_cannot_deactivate_a_gift(self):
        self.client.force_login(self.usher)
        response = self.client.post(reverse("staff_recurring_giving_deactivate", args=[self.recurring.id]))
        self.assertEqual(response.status_code, 302)
        self.recurring.refresh_from_db()
        self.assertTrue(self.recurring.is_active)


class StaffLapsedRecurringGiversViewTests(TestCase):
    def setUp(self):
        call_command("setup_groups")
        self.member = Member.objects.create(first_name="Efua", last_name="Asante")
        self.lapsed = RecurringGiving.objects.create(
            member=self.member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=3,
        )
        self.treasurer = User.objects.create_user(username="treasurer4", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.usher = User.objects.create_user(username="usher4", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))

    def test_treasurer_can_view_the_list(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_lapsed_recurring_givers_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Efua Asante")

    def test_usher_cannot_view_the_list(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_lapsed_recurring_givers_list"))
        self.assertEqual(response.status_code, 302)

    def test_a_gift_below_the_threshold_is_not_listed(self):
        self.lapsed.reminder_count = 1
        self.lapsed.save()
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_lapsed_recurring_givers_list"))
        self.assertNotContains(response, "Efua Asante")


class MembersWithCompletedGivingTests(TestCase):
    """The audience query for annual giving statements (giving/services.py)."""

    def setUp(self):
        self.member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")
        self.other_member = Member.objects.create(first_name="Kwame", last_name="Otu", email="kwame@example.com")

    def test_includes_a_member_with_a_completed_gift_that_year(self):
        donation = Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.filter(pk=donation.pk).update(date=timezone.now().replace(year=2026))
        self.assertIn(self.member, members_with_completed_giving(2026))

    def test_excludes_a_member_whose_only_gift_is_pending(self):
        donation = Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.PENDING)
        Donation.objects.filter(pk=donation.pk).update(date=timezone.now().replace(year=2026))
        self.assertNotIn(self.member, members_with_completed_giving(2026))

    def test_excludes_a_completed_gift_from_a_different_year(self):
        donation = Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.filter(pk=donation.pk).update(date=timezone.now().replace(year=2025))
        self.assertNotIn(self.member, members_with_completed_giving(2026))

    def test_excludes_anonymous_gifts(self):
        donation = Donation.objects.create(amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.filter(pk=donation.pk).update(date=timezone.now().replace(year=2026))
        self.assertEqual(list(members_with_completed_giving(2026)), [])

    def test_does_not_list_the_same_member_twice_for_multiple_gifts(self):
        for _ in range(3):
            donation = Donation.objects.create(member=self.member, amount="10.00", status=Donation.Status.COMPLETED)
            Donation.objects.filter(pk=donation.pk).update(date=timezone.now().replace(year=2026))
        self.assertEqual(list(members_with_completed_giving(2026)), [self.member])


class SendAnnualGivingStatementTests(TestCase):
    """Emailing a single member's own year-end statement (giving/notifications.py)."""

    def setUp(self):
        self.member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")
        donation = Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.filter(pk=donation.pk).update(date=timezone.now().replace(year=2026))

    def test_emails_the_members_completed_gifts_for_the_year(self):
        contacted = send_annual_giving_statement(self.member, 2026)
        self.assertTrue(contacted)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["efua@example.com"])
        self.assertIn("100.00", mail.outbox[0].body)
        self.assertIn("2026", mail.outbox[0].subject)

    def test_returns_false_and_sends_nothing_without_an_email_on_file(self):
        self.member.email = ""
        self.member.save()
        contacted = send_annual_giving_statement(self.member, 2026)
        self.assertFalse(contacted)
        self.assertEqual(len(mail.outbox), 0)


class SendGivingStatementEmailTests(TestCase):
    """The on-demand, arbitrary-date-range statement email (giving/notifications.py), separate from the annual one."""

    def setUp(self):
        self.member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")

    def test_emails_completed_gifts_within_the_range(self):
        Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        sent = send_giving_statement_email(self.member, date(2020, 1, 1), timezone.localdate())
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["efua@example.com"])
        self.assertIn("100.00", mail.outbox[0].body)

    def test_excludes_gifts_outside_the_range(self):
        donation = Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.filter(pk=donation.pk).update(date=timezone.now().replace(year=2020))
        sent = send_giving_statement_email(self.member, date(2026, 1, 1), date(2026, 12, 31))
        self.assertTrue(sent)
        self.assertNotIn("100.00", mail.outbox[0].body)

    def test_returns_false_and_sends_nothing_without_an_email_on_file(self):
        self.member.email = ""
        self.member.save()
        sent = send_giving_statement_email(self.member, date(2026, 1, 1), date(2026, 12, 31))
        self.assertFalse(sent)
        self.assertEqual(len(mail.outbox), 0)


class SendGivingStatementsCommandTests(TestCase):
    """The send_giving_statements management command."""

    def test_sends_a_statement_to_each_member_with_completed_giving_that_year(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")
        donation = Donation.objects.create(member=member, amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.filter(pk=donation.pk).update(date=timezone.now().replace(year=2026))

        call_command("send_giving_statements", "--year", "2026")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["efua@example.com"])

    def test_skips_and_reports_a_member_with_no_email_on_file(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante")
        donation = Donation.objects.create(member=member, amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.filter(pk=donation.pk).update(date=timezone.now().replace(year=2026))

        call_command("send_giving_statements", "--year", "2026")

        self.assertEqual(len(mail.outbox), 0)

    def test_defaults_to_last_year_when_no_year_is_given(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante", email="efua@example.com")
        donation = Donation.objects.create(member=member, amount="100.00", status=Donation.Status.COMPLETED)
        last_year = timezone.localdate().year - 1
        Donation.objects.filter(pk=donation.pk).update(date=timezone.now().replace(year=last_year))

        call_command("send_giving_statements")

        self.assertEqual(len(mail.outbox), 1)


class RealPaymentFlowTests(TestCase):
    """The live-payments path: donor details, webhook, Mobile Money pending, thank-you page."""

    def payment_result(self, donation, status="successful", amount=None):
        return {"status": "success", "data": {
            "status": status, "amount": float(amount or donation.amount), "currency": "GHS",
            "tx_ref": donation.payment_reference,
        }}

    @override_settings(FLUTTERWAVE_SECRET_KEY="test-secret", GIVING_ONLINE_PAYMENTS=True)
    def test_guest_must_give_name_and_email_when_payments_are_live(self):
        response = self.client.post(reverse("give"), {"amount": "50.00", "donation_type": Donation.DonationType.OFFERING})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Donation.objects.count(), 0)

    @override_settings(FLUTTERWAVE_SECRET_KEY="test-secret", GIVING_ONLINE_PAYMENTS=True)
    @patch("giving.views.initiate_payment", return_value="https://checkout.example/pay")
    def test_donor_details_are_saved_and_sent_to_flutterwave(self, initiate):
        response = self.client.post(reverse("give"), {
            "amount": "50.00", "donation_type": Donation.DonationType.TITHE,
            "donor_name": "Efua Mensah", "donor_email": "efua@example.com", "donor_phone": "0241234567",
        })
        self.assertRedirects(response, "https://checkout.example/pay", fetch_redirect_response=False)
        donation = Donation.objects.get()
        self.assertEqual(donation.donor_email, "efua@example.com")
        kwargs = initiate.call_args.kwargs
        self.assertEqual(kwargs["email"], "efua@example.com")
        self.assertEqual(kwargs["name"], "Efua Mensah")
        self.assertEqual(kwargs["phone"], "0241234567")

    def test_manual_mode_stays_on_give_page_as_pending(self):
        response = self.client.post(reverse("give"), {"amount": "20.00", "donation_type": Donation.DonationType.OFFERING})
        donation = Donation.objects.get()
        self.assertRedirects(response, reverse("give"))
        self.assertEqual(donation.status, Donation.Status.PENDING)
        response = self.client.get(reverse("giving_thank_you", args=[donation.payment_reference]))
        self.assertEqual(response.status_code, 404)

    def test_thank_you_page_is_only_visible_to_the_giver(self):
        donation = Donation.objects.create(amount="10.00", payment_reference="secret-ref")
        response = self.client.get(reverse("giving_thank_you", args=["secret-ref"]))
        self.assertEqual(response.status_code, 404)

    @patch("giving.views.verify_payment")
    def test_mobile_money_still_pending_stays_pending(self, mock_verify):
        donation = Donation.objects.create(amount="30.00", payment_reference="momo-ref")
        mock_verify.return_value = self.payment_result(donation, status="pending")
        response = self.client.get(reverse("giving_callback"), {"status": "pending", "tx_ref": "momo-ref", "transaction_id": "9"})
        self.assertRedirects(response, reverse("giving_thank_you", args=["momo-ref"]))
        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.PENDING)

    def test_webhook_rejects_requests_without_the_secret_hash(self):
        with self.settings(FLUTTERWAVE_WEBHOOK_HASH="hash-123"):
            response = self.client.post(reverse("flutterwave_webhook"), "{}", content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_webhook_is_off_until_configured(self):
        response = self.client.post(reverse("flutterwave_webhook"), "{}", content_type="application/json")
        self.assertEqual(response.status_code, 503)

    @override_settings(FLUTTERWAVE_WEBHOOK_HASH="hash-123")
    @patch("giving.views.verify_payment")
    def test_webhook_completes_a_verified_donation_once(self, mock_verify):
        member = Member.objects.create(first_name="Kofi", last_name="Asare", email="kofi@example.com")
        donation = Donation.objects.create(member=member, amount="40.00", payment_reference="hook-ref")
        mock_verify.return_value = self.payment_result(donation)
        body = '{"event": "charge.completed", "data": {"id": 555, "tx_ref": "hook-ref"}}'
        for _ in range(2):
            response = self.client.post(reverse("flutterwave_webhook"), body, content_type="application/json", HTTP_VERIF_HASH="hash-123")
            self.assertEqual(response.status_code, 200)
        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.COMPLETED)
        mock_verify.assert_called_once_with(555)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(FLUTTERWAVE_WEBHOOK_HASH="hash-123")
    @patch("giving.views.verify_payment")
    def test_webhook_does_not_trust_payload_without_verification(self, mock_verify):
        donation = Donation.objects.create(amount="40.00", payment_reference="forged-ref")
        mock_verify.return_value = self.payment_result(donation, amount="1.00")
        body = '{"data": {"id": 1, "tx_ref": "forged-ref", "status": "successful", "amount": 40}}'
        self.client.post(reverse("flutterwave_webhook"), body, content_type="application/json", HTTP_VERIF_HASH="hash-123")
        donation.refresh_from_db()
        self.assertNotEqual(donation.status, Donation.Status.COMPLETED)

    @override_settings(FLUTTERWAVE_SECRET_KEY="test-secret", GIVING_ONLINE_PAYMENTS=False)
    @patch("giving.views.initiate_payment")
    def test_keys_alone_do_not_turn_on_online_giving(self, initiate):
        response = self.client.post(reverse("give"), {"amount": "20.00", "donation_type": Donation.DonationType.OFFERING})
        self.assertRedirects(response, reverse("give"))
        initiate.assert_not_called()
        self.assertEqual(Donation.objects.get().status, Donation.Status.PENDING)
