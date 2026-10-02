from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import Flyer


@admin.register(Flyer)
class FlyerAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "is_active", "order", "created_at")
    list_filter = ("is_active",)
    search_fields = ("title",)
