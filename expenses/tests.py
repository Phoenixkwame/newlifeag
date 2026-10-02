from decimal import Decimal

from django.test import TestCase

from .models import BudgetCategory, Expense


class BudgetCategoryModelTests(TestCase):
    def test_str_is_the_category_name(self):
        category = BudgetCategory.objects.create(name="Utilities")
        self.assertEqual(str(category), "Utilities")

    def test_spent_total_sums_its_own_expenses_only(self):
        category = BudgetCategory.objects.create(name="Utilities")
        other_category = BudgetCategory.objects.create(name="Missions")
        Expense.objects.create(category=category, amount=Decimal("100.00"), date="2027-01-05")
        Expense.objects.create(category=category, amount=Decimal("50.00"), date="2027-02-05")
        Expense.objects.create(category=other_category, amount=Decimal("500.00"), date="2027-01-05")
        self.assertEqual(category.spent_total(), Decimal("150.00"))

    def test_spent_total_can_be_narrowed_to_a_year(self):
        category = BudgetCategory.objects.create(name="Utilities")
        Expense.objects.create(category=category, amount=Decimal("100.00"), date="2026-01-05")
        Expense.objects.create(category=category, amount=Decimal("50.00"), date="2027-01-05")
        self.assertEqual(category.spent_total(year=2027), Decimal("50.00"))

    def test_spent_total_with_no_expenses_is_zero(self):
        category = BudgetCategory.objects.create(name="Utilities")
        self.assertEqual(category.spent_total(), Decimal("0.00"))

    def test_percent_of_budget_is_none_with_no_budget_set(self):
        category = BudgetCategory.objects.create(name="Utilities")
        Expense.objects.create(category=category, amount=Decimal("100.00"), date="2027-01-05")
        self.assertIsNone(category.percent_of_budget)

    def test_percent_of_budget_is_capped_at_100(self):
        category = BudgetCategory.objects.create(name="Utilities", annual_budget=Decimal("100.00"))
        from django.utils import timezone

        Expense.objects.create(category=category, amount=Decimal("500.00"), date=timezone.localdate())
        self.assertEqual(category.percent_of_budget, 100)


class ExpenseModelTests(TestCase):
    def test_str_includes_amount_and_payee(self):
        expense = Expense.objects.create(amount=Decimal("75.00"), date="2027-01-05", paid_to="ECG")
        self.assertIn("75.00", str(expense))
        self.assertIn("ECG", str(expense))
