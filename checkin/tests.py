from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from members.models import Household

from .models import CheckIn, Child, SundaySchoolClass, SundaySchoolLesson
from .services import WrongPickupCodeError, check_in_child, check_out_child


class ChildAgeTests(TestCase):
    """
    Pins "today" via mocking rather than using a relative date computed from
    the real today - that keeps these deterministic year-round instead of
    depending on leap days or the test happening to run on Dec 31.
    """

    def setUp(self):
        self.household = Household.objects.create(name="The Mensah Family")

    @patch("checkin.models.timezone.localdate", return_value=date(2026, 6, 15))
    def test_age_is_computed_from_date_of_birth(self, mock_localdate):
        child = Child.objects.create(
            household=self.household, first_name="Efua", last_name="Mensah", date_of_birth=date(2016, 6, 15)
        )
        self.assertEqual(child.age, 10)

    @patch("checkin.models.timezone.localdate", return_value=date(2026, 6, 15))
    def test_age_accounts_for_birthday_not_yet_reached_this_year(self, mock_localdate):
        # Born June 20th - by June 15th this year, that birthday hasn't
        # happened yet, so the child is still one year younger than a
        # naive year-subtraction would suggest.
        child = Child.objects.create(
            household=self.household, first_name="Kojo", last_name="Mensah", date_of_birth=date(2018, 6, 20)
        )
        self.assertEqual(child.age, 7)

    def test_age_is_none_without_a_date_of_birth(self):
        child = Child.objects.create(household=self.household, first_name="Ama", last_name="Mensah")
        self.assertIsNone(child.age)


class CheckInServiceTests(TestCase):
    def setUp(self):
        self.household = Household.objects.create(name="The Owusu Family")
        self.child = Child.objects.create(household=self.household, first_name="Yaw", last_name="Owusu")
        self.user = User.objects.create_user(username="checkin-staff", password="test-pass-123")

    def test_check_in_creates_a_record_with_a_pickup_code(self):
        check_in = check_in_child(self.child, guardian_name="Auntie Efua", user=self.user)
        self.assertEqual(check_in.child, self.child)
        self.assertEqual(check_in.guardian_name, "Auntie Efua")
        self.assertEqual(check_in.checked_in_by, self.user)
        self.assertEqual(len(check_in.pickup_code), 4)
        self.assertTrue(check_in.pickup_code.isdigit())
        self.assertTrue(check_in.is_checked_in)

    def test_pickup_codes_are_unique_among_currently_checked_in_children(self):
        other_child = Child.objects.create(household=self.household, first_name="Abena", last_name="Owusu")
        check_in_one = check_in_child(self.child, guardian_name="Auntie Efua", user=self.user)
        check_in_two = check_in_child(other_child, guardian_name="Uncle Kwesi", user=self.user)
        self.assertNotEqual(check_in_one.pickup_code, check_in_two.pickup_code)

    def test_check_out_with_correct_code_succeeds(self):
        check_in = check_in_child(self.child, guardian_name="Auntie Efua", user=self.user)
        result = check_out_child(check_in, code=check_in.pickup_code, user=self.user)
        check_in.refresh_from_db()
        self.assertTrue(result)
        self.assertFalse(check_in.is_checked_in)
        self.assertEqual(check_in.checked_out_by, self.user)
        self.assertIsNotNone(check_in.checked_out_at)

    def test_check_out_with_wrong_code_raises_and_changes_nothing(self):
        check_in = check_in_child(self.child, guardian_name="Auntie Efua", user=self.user)
        wrong_code = "0000" if check_in.pickup_code != "0000" else "1111"
        with self.assertRaises(WrongPickupCodeError):
            check_out_child(check_in, code=wrong_code, user=self.user)
        check_in.refresh_from_db()
        self.assertTrue(check_in.is_checked_in)
        self.assertIsNone(check_in.checked_out_by)

    def test_checking_out_an_already_checked_out_child_is_a_no_op(self):
        check_in = check_in_child(self.child, guardian_name="Auntie Efua", user=self.user)
        check_out_child(check_in, code=check_in.pickup_code, user=self.user)
        first_checkout_time = check_in.checked_out_at
        result = check_out_child(check_in, code=check_in.pickup_code, user=self.user)
        check_in.refresh_from_db()
        self.assertFalse(result)
        self.assertEqual(check_in.checked_out_at, first_checkout_time)

    def test_a_checked_out_childs_pickup_code_can_be_reused(self):
        check_in = check_in_child(self.child, guardian_name="Auntie Efua", user=self.user)
        check_out_child(check_in, code=check_in.pickup_code, user=self.user)
        # Once picked up, that code is free again - only kids still on the
        # floor need distinguishable codes.
        other_child = Child.objects.create(household=self.household, first_name="Abena", last_name="Owusu")
        new_check_in = CheckIn.objects.create(
            child=other_child, guardian_name="Uncle Kwesi", pickup_code=check_in.pickup_code, checked_in_by=self.user
        )
        self.assertEqual(new_check_in.pickup_code, check_in.pickup_code)


class SundaySchoolClassModelTests(TestCase):
    def setUp(self):
        self.household = Household.objects.create(name="Owusu Family")
        self.child = Child.objects.create(household=self.household, first_name="Kofi", last_name="Owusu")

    def test_str_is_the_class_name(self):
        sunday_school_class = SundaySchoolClass.objects.create(name="Toddlers")
        self.assertEqual(str(sunday_school_class), "Toddlers")

    def test_a_class_can_have_a_roster_of_children(self):
        sunday_school_class = SundaySchoolClass.objects.create(name="Toddlers")
        sunday_school_class.children.add(self.child)
        self.assertIn(self.child, sunday_school_class.children.all())
        self.assertIn(sunday_school_class, self.child.sunday_school_classes.all())

    def test_lesson_str_mentions_class_and_week(self):
        sunday_school_class = SundaySchoolClass.objects.create(name="Toddlers")
        lesson = SundaySchoolLesson.objects.create(
            sunday_school_class=sunday_school_class, title="Noah's Ark", week_of="2027-05-02", content="Genesis 6-9"
        )
        self.assertIn("Noah's Ark", str(lesson))
        self.assertIn("Toddlers", str(lesson))
