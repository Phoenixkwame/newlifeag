from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import BackgroundCheck


@admin.register(BackgroundCheck)
class BackgroundCheckAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "status", "cleared_date", "expiry_date")
    list_filter = ("status",)
    search_fields = ("member__first_name", "member__last_name")
