from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from members.models import Member

from .models import BackgroundCheck, VolunteerTraining


class BackgroundCheckModelTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kwame", last_name="Mensah")

    def test_str_mentions_member_and_status(self):
        check = BackgroundCheck.objects.create(member=self.member, status=BackgroundCheck.Status.CLEARED)
        self.assertIn("Kwame", str(check))
        self.assertIn("Cleared", str(check))

    def test_default_status_is_pending(self):
        check = BackgroundCheck.objects.create(member=self.member)
        self.assertEqual(check.status, BackgroundCheck.Status.PENDING)

    def test_is_expired_true_for_a_past_expiry_date(self):
        check = BackgroundCheck.objects.create(
            member=self.member,
            status=BackgroundCheck.Status.CLEARED,
            expiry_date=timezone.localdate() - timedelta(days=1),
        )
        self.assertTrue(check.is_expired)
        self.assertFalse(check.is_expiring_soon)

    def test_is_expiring_soon_within_30_days(self):
        check = BackgroundCheck.objects.create(
            member=self.member,
            status=BackgroundCheck.Status.CLEARED,
            expiry_date=timezone.localdate() + timedelta(days=10),
        )
        self.assertTrue(check.is_expiring_soon)
        self.assertFalse(check.is_expired)

    def test_is_expiring_soon_false_when_expiry_is_far_out(self):
        check = BackgroundCheck.objects.create(
            member=self.member,
            status=BackgroundCheck.Status.CLEARED,
            expiry_date=timezone.localdate() + timedelta(days=90),
        )
        self.assertFalse(check.is_expiring_soon)

    def test_is_expiring_soon_and_is_expired_false_with_no_expiry_date(self):
        check = BackgroundCheck.objects.create(member=self.member, status=BackgroundCheck.Status.PENDING)
        self.assertFalse(check.is_expiring_soon)
        self.assertFalse(check.is_expired)


class VolunteerTrainingModelTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kwame", last_name="Mensah")

    def test_str_mentions_member_training_and_status(self):
        training = VolunteerTraining.objects.create(
            member=self.member, training_name="Child Safety", status=VolunteerTraining.Status.COMPLETED
        )
        self.assertIn("Kwame", str(training))
        self.assertIn("Child Safety", str(training))
        self.assertIn("Completed", str(training))

    def test_default_status_is_in_progress(self):
        training = VolunteerTraining.objects.create(member=self.member, training_name="First Aid")
        self.assertEqual(training.status, VolunteerTraining.Status.IN_PROGRESS)

    def test_is_expired_true_for_a_past_expiry_date(self):
        training = VolunteerTraining.objects.create(
            member=self.member,
            training_name="First Aid",
            status=VolunteerTraining.Status.COMPLETED,
            expiry_date=timezone.localdate() - timedelta(days=1),
        )
        self.assertTrue(training.is_expired)
        self.assertFalse(training.is_expiring_soon)

    def test_is_expiring_soon_within_30_days(self):
        training = VolunteerTraining.objects.create(
            member=self.member,
            training_name="First Aid",
            status=VolunteerTraining.Status.COMPLETED,
            expiry_date=timezone.localdate() + timedelta(days=10),
        )
        self.assertTrue(training.is_expiring_soon)
        self.assertFalse(training.is_expired)

    def test_is_expiring_soon_false_when_expiry_is_far_out(self):
        training = VolunteerTraining.objects.create(
            member=self.member,
            training_name="First Aid",
            status=VolunteerTraining.Status.COMPLETED,
            expiry_date=timezone.localdate() + timedelta(days=90),
        )
        self.assertFalse(training.is_expiring_soon)

    def test_is_expiring_soon_and_is_expired_false_with_no_expiry_date(self):
        training = VolunteerTraining.objects.create(member=self.member, training_name="Child Safety")
        self.assertFalse(training.is_expiring_soon)
        self.assertFalse(training.is_expired)
