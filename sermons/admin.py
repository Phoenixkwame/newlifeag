from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import Devotional, Sermon, SermonProgress, SermonSeries, Tag


@admin.register(Sermon)
class SermonAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "speaker", "date", "series", "scripture_reference")
    list_filter = ("speaker", "series")
    search_fields = ("title", "speaker", "scripture_reference")
    date_hierarchy = "date"


@admin.register(Devotional)
class DevotionalAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("date", "title", "scripture_reference")
    search_fields = ("title", "scripture_reference")
    date_hierarchy = "date"


@admin.register(SermonSeries)
class SermonSeriesAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Tag)
class TagAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(SermonProgress)
class SermonProgressAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "sermon", "watched_date")
    list_filter = ("watched_date",)
    search_fields = ("member__first_name", "member__last_name", "sermon__title")
