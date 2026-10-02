from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import Attendance, Campus, Group, GroupMembership, Household, Member


@admin.register(Campus)
class CampusAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "address", "service_times")
    search_fields = ("name", "address")


@admin.register(Household)
class HouseholdAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "address", "phone")
    search_fields = ("name", "address")


@admin.register(Member)
class MemberAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("first_name", "last_name", "role", "household", "campus", "is_active", "date_joined")
    list_filter = ("role", "is_active", "campus")
    search_fields = ("first_name", "last_name", "email", "phone")
    list_editable = ("is_active",)
    date_hierarchy = "date_joined"


@admin.register(Group)
class GroupAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "group_type", "leader")
    list_filter = ("group_type",)


@admin.register(GroupMembership)
class GroupMembershipAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "group", "joined_date", "left_date", "is_active")
    list_filter = ("group",)


@admin.register(Attendance)
class AttendanceAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "date", "event", "campus", "present")
    list_filter = ("present", "date", "campus")
    date_hierarchy = "date"
