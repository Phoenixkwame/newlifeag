from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import BabyDedication, BaptismRecord, FuneralRecord, TransferLetter, WeddingRecord


@admin.register(BabyDedication)
class BabyDedicationAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("child_name", "dedication_date", "officiated_by", "campus")
    list_filter = ("campus",)
    search_fields = ("child_name",)
    autocomplete_fields = ["parents"]


@admin.register(WeddingRecord)
class WeddingRecordAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("spouse_one", "spouse_two", "wedding_date", "officiated_by", "campus")
    list_filter = ("campus",)
    search_fields = ("spouse_one__first_name", "spouse_one__last_name", "spouse_two__first_name", "spouse_two__last_name")
    autocomplete_fields = ["spouse_one", "spouse_two"]


@admin.register(BaptismRecord)
class BaptismRecordAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "baptism_date", "officiated_by", "campus")
    list_filter = ("campus",)
    search_fields = ("member__first_name", "member__last_name")
    autocomplete_fields = ["member"]


@admin.register(FuneralRecord)
class FuneralRecordAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "service_date", "date_of_death", "officiated_by", "campus")
    list_filter = ("campus",)
    search_fields = ("member__first_name", "member__last_name")
    autocomplete_fields = ["member", "family_contacts"]


@admin.register(TransferLetter)
class TransferLetterAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "destination_church", "transfer_date", "issued_by")
    search_fields = ("member__first_name", "member__last_name", "destination_church")
    autocomplete_fields = ["member"]
