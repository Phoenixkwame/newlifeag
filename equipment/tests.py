from django.test import TestCase

from members.models import Member

from .models import Equipment, EquipmentCheckout


class EquipmentModelTests(TestCase):
    def setUp(self):
        self.item = Equipment.objects.create(name="Shure SM58 Mic #3", category=Equipment.Category.SOUND)
        self.member = Member.objects.create(first_name="Ama", last_name="Owusu")

    def test_str_is_the_name(self):
        self.assertEqual(str(self.item), "Shure SM58 Mic #3")

    def test_not_checked_out_by_default(self):
        self.assertFalse(self.item.is_checked_out)
        self.assertIsNone(self.item.current_checkout)

    def test_is_checked_out_once_an_open_checkout_exists(self):
        checkout = EquipmentCheckout.objects.create(equipment=self.item, checked_out_to=self.member)
        self.assertTrue(self.item.is_checked_out)
        self.assertEqual(self.item.current_checkout, checkout)

    def test_not_checked_out_once_the_checkout_is_closed(self):
        from django.utils import timezone

        EquipmentCheckout.objects.create(
            equipment=self.item, checked_out_to=self.member, checked_in_at=timezone.now()
        )
        self.assertFalse(self.item.is_checked_out)
        self.assertIsNone(self.item.current_checkout)

    def test_only_the_most_recent_open_checkout_counts_as_current(self):
        from django.utils import timezone

        EquipmentCheckout.objects.create(
            equipment=self.item, checked_out_to=self.member, checked_in_at=timezone.now()
        )
        open_checkout = EquipmentCheckout.objects.create(equipment=self.item, checked_out_to=self.member)
        self.assertEqual(self.item.current_checkout, open_checkout)


class EquipmentCheckoutModelTests(TestCase):
    def setUp(self):
        self.item = Equipment.objects.create(name="Yamaha Keyboard", category=Equipment.Category.INSTRUMENT)
        self.member = Member.objects.create(first_name="Kofi", last_name="Boateng")

    def test_str_when_checked_out(self):
        checkout = EquipmentCheckout.objects.create(equipment=self.item, checked_out_to=self.member)
        self.assertIn("checked out to", str(checkout))
        self.assertIn(self.member.first_name, str(checkout))

    def test_str_when_checked_in(self):
        from django.utils import timezone

        checkout = EquipmentCheckout.objects.create(
            equipment=self.item, checked_out_to=self.member, checked_in_at=timezone.now()
        )
        self.assertIn("checked in", str(checkout))
