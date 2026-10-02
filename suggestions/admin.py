from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import Suggestion


@admin.register(Suggestion)
class SuggestionAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("__str__", "is_reviewed", "submitted_at")
    list_filter = ("is_reviewed",)
