from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin, messages

from .models import Donation, GivingCampaign, Pledge
from .services import mark_donation_completed


@admin.register(Donation)
class DonationAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "amount", "donation_type", "status", "campus", "campaign", "date")
    list_filter = ("donation_type", "status", "campus", "campaign")
    search_fields = ("member__first_name", "member__last_name", "payment_reference")
    readonly_fields = ("date",)
    date_hierarchy = "date"
    actions = ["mark_as_completed"]

    @admin.action(description="Mark selected pending gifts as completed (manual reconciliation)")
    def mark_as_completed(self, request, queryset):
        """
        For gifts given as cash or mobile money in person (or recorded while
        online payments were off) - lets a treasurer confirm the money was
        actually received before it counts as completed. Only touches
        donations that are currently pending; anything else is left alone.
        (The same check-and-log logic backs the staff area's donation list -
        see giving/services.py.)
        """
        updated = skipped = 0
        for donation in queryset:
            if mark_donation_completed(donation, user=request.user):
                updated += 1
            else:
                skipped += 1

        if updated:
            self.message_user(request, f"Marked {updated} donation(s) as completed.", level=messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} donation(s) that weren't pending - only pending gifts can be reconciled this way.",
                level=messages.WARNING,
            )


@admin.register(GivingCampaign)
class GivingCampaignAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "goal_amount", "given_total", "pledged_total", "start_date", "end_date", "is_active")
    list_filter = ("is_active", "campus")
    search_fields = ("name",)
    date_hierarchy = "start_date"


@admin.register(Pledge)
class PledgeAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "campaign", "amount", "given_toward_pledge", "date_pledged")
    list_filter = ("campaign",)
    search_fields = ("member__first_name", "member__last_name")
