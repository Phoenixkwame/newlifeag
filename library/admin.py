from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import LibraryItem, LibraryLoan


@admin.register(LibraryItem)
class LibraryItemAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "author", "category", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("title", "author")


@admin.register(LibraryLoan)
class LibraryLoanAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("item", "borrower", "borrowed_date", "due_date", "returned_date")
    list_filter = ("returned_date",)
    search_fields = ("item__title", "borrower__first_name", "borrower__last_name")
