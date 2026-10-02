from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import ServiceHourLog


@admin.register(ServiceHourLog)
class ServiceHourLogAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "date", "hours", "role", "group", "event")
    list_filter = ("group",)
    search_fields = ("member__first_name", "member__last_name", "role")
    date_hierarchy = "date"
