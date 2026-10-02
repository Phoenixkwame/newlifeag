from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import BudgetCategory, Expense


@admin.register(BudgetCategory)
class BudgetCategoryAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "annual_budget")
    search_fields = ("name",)


@admin.register(Expense)
class ExpenseAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("paid_to", "category", "amount", "date", "campus")
    list_filter = ("category", "campus")
    search_fields = ("paid_to", "description")
    date_hierarchy = "date"
