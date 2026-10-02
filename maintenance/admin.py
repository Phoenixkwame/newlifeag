from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import MaintenanceRequest


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "status", "location", "reported_by", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "description", "location")
