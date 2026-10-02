from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from members.models import Campus


class BudgetCategory(models.Model):
    """
    A category to track expenses against (e.g. "Utilities", "Missions",
    "Building Maintenance"), optionally with an annual budget so a Treasurer
    can see actual spend vs. plan. This is the outflow side of church
    finances - separate from GivingCampaign (giving/models.py), which tracks
    money coming IN toward a goal.
    """

    name = models.CharField(max_length=150)
    annual_budget = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional planned spend for the year. Leave blank to track spend with no budget comparison.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Budget categories"

    def __str__(self):
        return self.name

    def spent_total(self, year=None):
        """Total expenses recorded against this category, optionally narrowed to one calendar year."""
        category_expenses = self.expenses.all()
        if year:
            category_expenses = category_expenses.filter(date__year=year)
        return category_expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def percent_of_budget(self):
        """Whole-number percent of this year's spend against the annual budget, capped at 100 - or None with no budget set."""
        if not self.annual_budget:
            return None
        spent = self.spent_total(year=timezone.localdate().year)
        return min(100, int((spent / self.annual_budget) * 100))


class Expense(models.Model):
    """
    An outgoing church payment - the flip side of giving.Donation. Never
    linked to a Donation; this app only tracks money going out, not money
    coming in.
    """

    category = models.ForeignKey(
        BudgetCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    paid_to = models.CharField(max_length=200, blank=True, help_text="Vendor/person paid, e.g. 'ECG', 'ABC Plumbing'.")
    description = models.TextField(blank=True)
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expenses",
        help_text="Which campus this expense is for (only relevant once there's more than one).",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses_recorded"
    )
    # A photo/scan of the receipt, for an audit trail behind the numbers in
    # the financial reports - same optional-file-upload pattern as
    # sermons.Sermon's study_guide (see StaffExpenseForm's clean_receipt for
    # the size limit).
    receipt = models.FileField(upload_to="expense_receipts/", null=True, blank=True, help_text="A photo or scan of the receipt, if you have one.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"GH₵{self.amount} - {self.paid_to or 'expense'} ({self.date})"
