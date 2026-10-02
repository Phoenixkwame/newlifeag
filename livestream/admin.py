from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import LiveStream


@admin.register(LiveStream)
class LiveStreamAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "scheduled_for", "stream_url")
    list_filter = ("scheduled_for",)
    search_fields = ("title", "notes")
