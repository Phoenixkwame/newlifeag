from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from members.models import Member

from .models import LibraryItem, LibraryLoan


class LibraryItemModelTests(TestCase):
    def setUp(self):
        self.item = LibraryItem.objects.create(title="Mere Christianity", category=LibraryItem.Category.BOOK)
        self.member = Member.objects.create(first_name="Ama", last_name="Owusu")

    def test_str_is_the_title(self):
        self.assertEqual(str(self.item), "Mere Christianity")

    def test_not_on_loan_by_default(self):
        self.assertFalse(self.item.is_on_loan)
        self.assertIsNone(self.item.current_loan)

    def test_is_on_loan_once_an_open_loan_exists(self):
        loan = LibraryLoan.objects.create(
            item=self.item, borrower=self.member, due_date=timezone.localdate() + timedelta(days=14)
        )
        self.assertTrue(self.item.is_on_loan)
        self.assertEqual(self.item.current_loan, loan)

    def test_not_on_loan_once_the_loan_is_returned(self):
        LibraryLoan.objects.create(
            item=self.item,
            borrower=self.member,
            due_date=timezone.localdate() + timedelta(days=14),
            returned_date=timezone.localdate(),
        )
        self.assertFalse(self.item.is_on_loan)
        self.assertIsNone(self.item.current_loan)


class LibraryLoanModelTests(TestCase):
    def setUp(self):
        self.item = LibraryItem.objects.create(title="The Case for Christ", category=LibraryItem.Category.BOOK)
        self.member = Member.objects.create(first_name="Kofi", last_name="Boateng")

    def test_str_when_on_loan(self):
        loan = LibraryLoan.objects.create(
            item=self.item, borrower=self.member, due_date=timezone.localdate() + timedelta(days=14)
        )
        self.assertIn("on loan to", str(loan))
        self.assertIn(self.member.first_name, str(loan))

    def test_str_when_returned(self):
        loan = LibraryLoan.objects.create(
            item=self.item,
            borrower=self.member,
            due_date=timezone.localdate() + timedelta(days=14),
            returned_date=timezone.localdate(),
        )
        self.assertIn("returned", str(loan))

    def test_is_overdue_when_past_due_date_and_not_returned(self):
        loan = LibraryLoan.objects.create(
            item=self.item, borrower=self.member, due_date=timezone.localdate() - timedelta(days=1)
        )
        self.assertTrue(loan.is_overdue)

    def test_not_overdue_when_returned_even_if_past_due_date(self):
        loan = LibraryLoan.objects.create(
            item=self.item,
            borrower=self.member,
            due_date=timezone.localdate() - timedelta(days=1),
            returned_date=timezone.localdate(),
        )
        self.assertFalse(loan.is_overdue)

    def test_not_overdue_before_due_date(self):
        loan = LibraryLoan.objects.create(
            item=self.item, borrower=self.member, due_date=timezone.localdate() + timedelta(days=14)
        )
        self.assertFalse(loan.is_overdue)
