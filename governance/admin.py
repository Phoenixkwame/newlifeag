from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import ActionItem, Meeting


class ActionItemInline(CampusScopedAdminMixin, admin.TabularInline):
    model = ActionItem
    extra = 1


@admin.register(Meeting)
class MeetingAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("__str__", "date", "created_by")
    list_filter = ("date",)
    inlines = [ActionItemInline]


@admin.register(ActionItem)
class ActionItemAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("description", "meeting", "owner", "due_date", "is_done")
    list_filter = ("is_done",)
