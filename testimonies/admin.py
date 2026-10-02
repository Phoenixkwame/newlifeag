from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import Testimony


@admin.register(Testimony)
class TestimonyAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "is_approved", "share_name_publicly", "created_at")
    list_filter = ("is_approved",)
    search_fields = ("member__first_name", "member__last_name", "testimony_text")
