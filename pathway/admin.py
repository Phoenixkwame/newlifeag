from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import MemberPathwayProgress, PathwayStep


@admin.register(PathwayStep)
class PathwayStepAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "order")
    ordering = ["order", "name"]


@admin.register(MemberPathwayProgress)
class MemberPathwayProgressAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "step", "completed_date", "marked_by")
    list_filter = ("step",)
    search_fields = ("member__first_name", "member__last_name")
