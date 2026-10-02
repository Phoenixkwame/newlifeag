from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from members.models import Group, Member

from .models import ServiceHourLog
from .pdfs import build_service_hour_certificate_pdf
from .services import total_volunteer_hours, volunteer_badge


class ServiceHourLogModelTests(TestCase):
    def test_str_includes_member_hours_and_date(self):
        member = Member.objects.create(first_name="Kofi", last_name="Mensah")
        log = ServiceHourLog.objects.create(member=member, date=date(2027, 5, 2), hours=Decimal("2.50"), role="Usher")
        self.assertIn("Kofi", str(log))
        self.assertIn("2.50", str(log))


class VolunteerBadgeServiceTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Yaw", last_name="Appiah")

    def test_total_volunteer_hours_with_no_logs_is_zero(self):
        self.assertEqual(total_volunteer_hours(self.member), 0)

    def test_total_volunteer_hours_sums_all_logs(self):
        ServiceHourLog.objects.create(member=self.member, date=date(2027, 1, 1), hours=Decimal("4"), role="Usher")
        ServiceHourLog.objects.create(
            member=self.member, date=date(2027, 1, 8), hours=Decimal("6.50"), role="Sound tech"
        )
        self.assertEqual(total_volunteer_hours(self.member), Decimal("10.50"))

    def test_volunteer_badge_below_first_threshold_is_none(self):
        self.assertIsNone(volunteer_badge(5))

    def test_volunteer_badge_returns_the_highest_threshold_met(self):
        self.assertEqual(volunteer_badge(10), "10 Hour Volunteer")
        self.assertEqual(volunteer_badge(75), "50 Hour Volunteer")
        self.assertEqual(volunteer_badge(500), "500 Hour Legend")


class LogServiceHoursViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="volunteer1", password="test-pass-123")
        self.member = Member.objects.create(first_name="Ama", last_name="Serwaa", user=self.user)

    def test_member_can_log_their_own_hours(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("log_service_hours"),
            {"date": "2027-05-02", "hours": "3", "role": "Sound tech", "group": "", "event": "", "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        log = ServiceHourLog.objects.get(member=self.member)
        self.assertEqual(log.role, "Sound tech")

    def test_hours_can_be_tagged_to_a_group(self):
        group = Group.objects.create(name="Worship Team")
        self.client.force_login(self.user)
        self.client.post(
            reverse("log_service_hours"),
            {"date": "2027-05-02", "hours": "1.5", "role": "Vocals", "group": group.id, "event": "", "notes": ""},
        )
        log = ServiceHourLog.objects.get(member=self.member)
        self.assertEqual(log.group, group)

    def test_user_without_member_profile_is_redirected(self):
        no_profile_user = User.objects.create_user(username="noprofile-hours", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(
            self.client.post(reverse("log_service_hours"), {"date": "2027-05-02", "hours": "1", "role": "Usher"}),
            reverse("dashboard"),
        )

    def test_dashboard_shows_recent_logs(self):
        ServiceHourLog.objects.create(member=self.member, date=date(2027, 5, 2), hours=Decimal("2"), role="Usher")
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Usher")


class BuildServiceHourCertificatePdfTests(TestCase):
    """Unit tests on the PDF builder itself (staff/tests.py's StaffServiceHourTests covers the view/permission)."""

    def setUp(self):
        self.member = Member.objects.create(first_name="Kofi", last_name="Mensah")

    def test_returns_pdf_bytes(self):
        logs = [ServiceHourLog.objects.create(member=self.member, date=date(2027, 5, 2), hours=Decimal("3"), role="Usher")]
        pdf_bytes = build_service_hour_certificate_pdf(self.member, 2027, logs, 3)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_renders_with_no_logged_hours(self):
        pdf_bytes = build_service_hour_certificate_pdf(self.member, 2027, [], 0)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
