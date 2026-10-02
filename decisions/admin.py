from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import Decision


@admin.register(Decision)
class DecisionAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "decision_type", "date", "event", "recorded_by")
    list_filter = ("decision_type",)
    search_fields = ("member__first_name", "member__last_name")
    autocomplete_fields = ["member"]
