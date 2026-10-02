from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import Announcement, AnnouncementDelivery


@admin.register(Announcement)
class AnnouncementAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("subject", "audience", "created_by", "created_at", "sent_at")
    list_filter = ("audience",)
    search_fields = ("subject", "body")
    readonly_fields = ("created_at", "sent_at", "email_sent_count", "sms_sent_count")


@admin.register(AnnouncementDelivery)
class AnnouncementDeliveryAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("announcement", "member", "channel", "status")
    list_filter = ("channel", "status")
    search_fields = ("member__first_name", "member__last_name", "announcement__subject")
