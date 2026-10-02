from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import Resource, ResourceBooking


@admin.register(Resource)
class ResourceAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "resource_type", "campus", "is_active")
    list_filter = ("resource_type", "campus", "is_active")
    search_fields = ("name",)


@admin.register(ResourceBooking)
class ResourceBookingAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("resource", "title", "start_datetime", "end_datetime", "booked_by")
    list_filter = ("resource",)
    search_fields = ("title",)
    autocomplete_fields = ["resource", "event", "booked_by"]
