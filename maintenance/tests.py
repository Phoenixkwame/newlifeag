from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from equipment.models import Equipment
from members.models import Member

from .models import MaintenanceRequest


class MaintenanceRequestModelTests(TestCase):
    def test_str_is_the_title(self):
        maintenance_request = MaintenanceRequest.objects.create(title="Leaking roof")
        self.assertEqual(str(maintenance_request), "Leaking roof")

    def test_can_link_to_a_specific_equipment_item(self):
        item = Equipment.objects.create(name="Shure SM58 Mic #3", category=Equipment.Category.SOUND)
        maintenance_request = MaintenanceRequest.objects.create(title="Mic keeps cutting out", equipment=item)
        self.assertEqual(maintenance_request.equipment, item)
        self.assertIn(maintenance_request, item.maintenance_requests.all())

    def test_default_status_is_open(self):
        maintenance_request = MaintenanceRequest.objects.create(title="Leaking roof")
        self.assertEqual(maintenance_request.status, MaintenanceRequest.Status.OPEN)
        self.assertIsNone(maintenance_request.resolved_at)

    def test_mark_status_done_stamps_resolved_at(self):
        maintenance_request = MaintenanceRequest.objects.create(title="Leaking roof")
        maintenance_request.mark_status(MaintenanceRequest.Status.DONE)
        self.assertEqual(maintenance_request.status, MaintenanceRequest.Status.DONE)
        self.assertIsNotNone(maintenance_request.resolved_at)

    def test_mark_status_away_from_done_clears_resolved_at(self):
        maintenance_request = MaintenanceRequest.objects.create(title="Leaking roof")
        maintenance_request.mark_status(MaintenanceRequest.Status.DONE)
        maintenance_request.mark_status(MaintenanceRequest.Status.OPEN)
        self.assertIsNone(maintenance_request.resolved_at)


class SubmitMaintenanceRequestTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="reporter", password="test-pass-123")
        self.member = Member.objects.create(first_name="Kojo", last_name="Asante", user=self.user)

    def test_member_can_submit_a_report(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("submit_maintenance_request"),
            {"title": "Broken chair", "description": "Third row, main sanctuary.", "location": "Main Sanctuary"},
        )
        self.assertEqual(response.status_code, 302)
        maintenance_request = MaintenanceRequest.objects.get(title="Broken chair")
        self.assertEqual(maintenance_request.reported_by, self.member)
        self.assertEqual(maintenance_request.status, MaintenanceRequest.Status.OPEN)

    def test_user_without_member_profile_is_redirected(self):
        no_profile_user = User.objects.create_user(username="noprofile-maint", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(
            self.client.post(reverse("submit_maintenance_request"), {"title": "Broken chair"}),
            reverse("dashboard"),
        )

    def test_blank_title_is_not_saved(self):
        self.client.force_login(self.user)
        self.client.post(reverse("submit_maintenance_request"), {"title": "", "description": "Nothing"})
        self.assertFalse(MaintenanceRequest.objects.exists())
