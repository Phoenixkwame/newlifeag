from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import CareRequest


@admin.register(CareRequest)
class CareRequestAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "request_type", "status", "assigned_pastor", "created_at")
    list_filter = ("request_type", "status")
    search_fields = ("member__first_name", "member__last_name", "details")
