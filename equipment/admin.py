from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import Equipment, EquipmentCheckout


@admin.register(Equipment)
class EquipmentAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "category", "condition", "campus", "is_active")
    list_filter = ("category", "condition", "is_active")
    search_fields = ("name", "serial_number")


@admin.register(EquipmentCheckout)
class EquipmentCheckoutAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("equipment", "checked_out_to", "checked_out_at", "checked_in_at")
    list_filter = ("checked_in_at",)
    search_fields = ("equipment__name",)
