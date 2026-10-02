from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import CheckIn, Child, SundaySchoolClass, SundaySchoolLesson


@admin.register(Child)
class ChildAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("first_name", "last_name", "household", "age", "is_active")
    list_filter = ("is_active",)
    search_fields = ("first_name", "last_name")


@admin.register(CheckIn)
class CheckInAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("child", "event", "guardian_name", "checked_in_at", "checked_out_at", "is_checked_in")
    list_filter = ("event",)
    search_fields = ("child__first_name", "child__last_name", "guardian_name")
    readonly_fields = ("pickup_code", "checked_in_at")


class SundaySchoolLessonInline(CampusScopedAdminMixin, admin.TabularInline):
    model = SundaySchoolLesson
    extra = 0


@admin.register(SundaySchoolClass)
class SundaySchoolClassAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "teacher")
    search_fields = ("name",)
    inlines = [SundaySchoolLessonInline]


@admin.register(SundaySchoolLesson)
class SundaySchoolLessonAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "sunday_school_class", "week_of", "posted_by")
    list_filter = ("sunday_school_class",)
    date_hierarchy = "week_of"
