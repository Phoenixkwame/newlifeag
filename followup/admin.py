from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import ContactAttempt, FollowUp


class ContactAttemptInline(CampusScopedAdminMixin, admin.TabularInline):
    model = ContactAttempt
    extra = 0
    readonly_fields = ("contacted_at",)


@admin.register(FollowUp)
class FollowUpAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "stage", "first_visit_date", "assigned_to")
    list_filter = ("stage",)
    search_fields = ("member__first_name", "member__last_name")
    inlines = [ContactAttemptInline]


@admin.register(ContactAttempt)
class ContactAttemptAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("follow_up", "contacted_at", "contacted_by")
    readonly_fields = ("contacted_at",)
