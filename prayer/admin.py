from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin, messages

from .models import PrayerRequest
from .services import mark_prayed_for


@admin.register(PrayerRequest)
class PrayerRequestAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "guest_name", "is_public", "approved_for_public", "prayed_for", "created_at")
    list_filter = ("is_public", "approved_for_public", "prayed_for")
    search_fields = ("member__first_name", "member__last_name", "guest_name", "request_text")
    readonly_fields = ("created_at", "prayed_for_at")
    date_hierarchy = "created_at"
    actions = ["mark_as_prayed_for", "approve_for_wall", "remove_from_wall"]

    @admin.action(description="Approve selected public requests for the prayer wall")
    def approve_for_wall(self, request, queryset):
        # Never publishes a request the person submitted privately.
        updated = queryset.filter(is_public=True).update(approved_for_public=True)
        self.message_user(request, f"Approved {updated} request(s) for the prayer wall.", level=messages.SUCCESS)

    @admin.action(description="Remove selected requests from the prayer wall")
    def remove_from_wall(self, request, queryset):
        updated = queryset.update(approved_for_public=False)
        self.message_user(request, f"Removed {updated} request(s) from the prayer wall.", level=messages.SUCCESS)

    @admin.action(description="Mark selected requests as prayed for")
    def mark_as_prayed_for(self, request, queryset):
        updated = skipped = 0
        for prayer_request in queryset:
            if mark_prayed_for(prayer_request, user=request.user):
                updated += 1
            else:
                skipped += 1

        if updated:
            self.message_user(request, f"Marked {updated} request(s) as prayed for.", level=messages.SUCCESS)
        if skipped:
            self.message_user(
                request, f"Skipped {skipped} request(s) already marked as prayed for.", level=messages.WARNING
            )
