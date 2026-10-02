from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import RSVP, Event, EventRegistration, EventTicket, VolunteerSignup, VolunteerSlot


class VolunteerSlotInline(CampusScopedAdminMixin, admin.TabularInline):
    model = VolunteerSlot
    extra = 1


class EventTicketInline(CampusScopedAdminMixin, admin.TabularInline):
    model = EventTicket
    extra = 0


@admin.register(Event)
class EventAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "event_type", "start_datetime", "location", "campus")
    list_filter = ("event_type", "campus")
    search_fields = ("title", "location")
    date_hierarchy = "start_datetime"
    inlines = [VolunteerSlotInline, EventTicketInline]


@admin.register(RSVP)
class RSVPAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "event", "status")
    list_filter = ("status",)


@admin.register(VolunteerSlot)
class VolunteerSlotAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("role_needed", "event", "capacity", "spots_filled", "spots_remaining")


@admin.register(VolunteerSignup)
class VolunteerSignupAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "slot", "signed_up_at")


@admin.register(EventTicket)
class EventTicketAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "event", "price", "capacity", "registered_count")


@admin.register(EventRegistration)
class EventRegistrationAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("member", "ticket", "status", "registered_at")
    list_filter = ("status",)
