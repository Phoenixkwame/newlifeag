from django.test import TestCase

from members.models import Member

from .models import BabyDedication, BaptismRecord, FuneralRecord, TransferLetter, WeddingRecord


class BabyDedicationModelTests(TestCase):
    def test_str_includes_child_name_and_date(self):
        dedication = BabyDedication.objects.create(child_name="Baby Mensah", dedication_date="2026-06-01")
        self.assertIn("Baby Mensah", str(dedication))
        self.assertIn("2026-06-01", str(dedication))

    def test_parents_is_optional(self):
        dedication = BabyDedication.objects.create(child_name="Baby Mensah", dedication_date="2026-06-01")
        self.assertEqual(dedication.parents.count(), 0)

    def test_parents_can_be_linked_to_existing_members(self):
        parent = Member.objects.create(first_name="Kojo", last_name="Mensah")
        dedication = BabyDedication.objects.create(child_name="Baby Mensah", dedication_date="2026-06-01")
        dedication.parents.add(parent)
        self.assertIn(dedication, parent.baby_dedications.all())


class WeddingRecordModelTests(TestCase):
    def setUp(self):
        self.spouse_one = Member.objects.create(first_name="Kojo", last_name="Mensah")
        self.spouse_two = Member.objects.create(first_name="Ama", last_name="Boateng")

    def test_str_includes_both_spouses(self):
        wedding = WeddingRecord.objects.create(
            spouse_one=self.spouse_one, spouse_two=self.spouse_two, wedding_date="2026-06-01"
        )
        self.assertIn("Kojo Mensah", str(wedding))
        self.assertIn("Ama Boateng", str(wedding))

    def test_shows_up_on_both_spouses(self):
        wedding = WeddingRecord.objects.create(
            spouse_one=self.spouse_one, spouse_two=self.spouse_two, wedding_date="2026-06-01"
        )
        self.assertIn(wedding, self.spouse_one.weddings_as_spouse_one.all())
        self.assertIn(wedding, self.spouse_two.weddings_as_spouse_two.all())


class BaptismRecordModelTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kwesi", last_name="Adjei")

    def test_str_includes_member_and_date(self):
        baptism = BaptismRecord.objects.create(member=self.member, baptism_date="2026-06-01")
        self.assertIn("Kwesi Adjei", str(baptism))
        self.assertIn("2026-06-01", str(baptism))

    def test_shows_up_on_the_member(self):
        baptism = BaptismRecord.objects.create(member=self.member, baptism_date="2026-06-01")
        self.assertIn(baptism, self.member.baptism_records.all())

    def test_a_member_can_have_more_than_one_baptism_record(self):
        BaptismRecord.objects.create(member=self.member, baptism_date="2015-06-01")
        BaptismRecord.objects.create(member=self.member, baptism_date="2026-06-01")
        self.assertEqual(self.member.baptism_records.count(), 2)


class FuneralRecordModelTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kwame", last_name="Asante")

    def test_str_includes_member_and_date(self):
        funeral = FuneralRecord.objects.create(member=self.member, service_date="2026-06-01")
        self.assertIn("Kwame Asante", str(funeral))
        self.assertIn("2026-06-01", str(funeral))

    def test_shows_up_on_the_member(self):
        funeral = FuneralRecord.objects.create(member=self.member, service_date="2026-06-01")
        self.assertEqual(self.member.funeral_record, funeral)

    def test_a_member_can_only_have_one_funeral_record(self):
        FuneralRecord.objects.create(member=self.member, service_date="2026-06-01")
        with self.assertRaises(Exception):
            FuneralRecord.objects.create(member=self.member, service_date="2026-06-02")

    def test_family_contacts_can_be_linked_to_existing_members(self):
        family_member = Member.objects.create(first_name="Ama", last_name="Asante")
        funeral = FuneralRecord.objects.create(member=self.member, service_date="2026-06-01")
        funeral.family_contacts.add(family_member)
        self.assertIn(funeral, family_member.funerals_as_family_contact.all())

    def test_family_contacts_is_optional(self):
        funeral = FuneralRecord.objects.create(member=self.member, service_date="2026-06-01")
        self.assertEqual(funeral.family_contacts.count(), 0)


class TransferLetterModelTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Abena", last_name="Owusu")

    def test_str_includes_member_destination_and_date(self):
        letter = TransferLetter.objects.create(
            member=self.member, destination_church="Grace AG", transfer_date="2026-06-01"
        )
        self.assertIn("Abena Owusu", str(letter))
        self.assertIn("Grace AG", str(letter))
        self.assertIn("2026-06-01", str(letter))

    def test_shows_up_on_the_member(self):
        letter = TransferLetter.objects.create(
            member=self.member, destination_church="Grace AG", transfer_date="2026-06-01"
        )
        self.assertIn(letter, self.member.transfer_letters.all())

    def test_a_member_can_have_more_than_one_transfer_letter(self):
        TransferLetter.objects.create(member=self.member, destination_church="Grace AG", transfer_date="2020-06-01")
        TransferLetter.objects.create(member=self.member, destination_church="Newlife AG", transfer_date="2026-06-01")
        self.assertEqual(self.member.transfer_letters.count(), 2)
