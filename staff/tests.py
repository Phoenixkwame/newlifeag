import io
import os
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import AnonymousUser, Group, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from announcements.models import Announcement
from booking.models import Resource, ResourceBooking
from care.models import CareRequest
from suggestions.models import Suggestion
from testimonies.models import Testimony
from checkin.models import CheckIn, Child, SundaySchoolClass, SundaySchoolLesson
from checkin.services import check_in_child
from equipment.models import Equipment, EquipmentCheckout
from library.models import LibraryItem, LibraryLoan
from events.models import RSVP, Event, EventRegistration, EventServiceTime, EventTicket, VolunteerSignup, VolunteerSlot
from expenses.models import BudgetCategory, Expense
from decisions.models import Decision
from flyers.models import Flyer
from followup.models import FollowUp, VisitorInfo
from followup.services import start_follow_up
from giving.models import Donation, GivingCampaign, Pledge, RecurringGiving
from governance.models import ActionItem, Meeting
from maintenance.models import MaintenanceRequest
from members.models import Attendance, Campus, GroupMembership, Household, Member, MemberNote, ServingAssignment, Skill
from members.models import Group as ChurchGroup
from livestream.models import LiveStream
from milestones.models import BabyDedication, BaptismRecord, FuneralRecord, TransferLetter, WeddingRecord
from pathway.models import MemberPathwayProgress, PathwayStep
from prayer.models import PrayerRequest
from screening.models import BackgroundCheck, VolunteerTraining
from sermons.models import Devotional, Sermon, SermonSeries
from servicehours.models import ServiceHourLog
from surveys.models import Survey, SurveyAnswer, SurveyChoice, SurveyQuestion, SurveyResponse

from .digest import build_weekly_digest
from .services import (
    annual_statistics,
    in_attendance_donation_scope,
    in_campus_scope,
    in_member_campus_scope,
    scope_attendance,
    scope_by_member_campus,
    scope_donations,
    scope_events,
    scope_giving_campaigns,
    scope_members,
    staff_campus_for,
)

# A minimal valid 1x1 GIF, same tiny fixture used for ImageField tests
# elsewhere in this project (see members/tests.py's SMALL_GIF).
TINY_GIF = b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"


class StaffAccessTests(TestCase):
    """
    The staff area re-uses the same Ushers/Treasurers/Pastors permissions
    that setup_groups creates for the Django admin - these tests make sure
    that separation actually holds here too, not just in /admin/.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher1", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer1", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.pastor = User.objects.create_user(username="pastor1", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.regular = User.objects.create_user(username="member1", password="test-pass-123")

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("staff_home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_non_staff_cannot_reach_staff_home(self):
        self.client.force_login(self.regular)
        response = self.client.get(reverse("staff_home"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_usher_can_view_members_and_add_but_not_edit(self):
        """
        Ushers gained add_member (previously view-only) alongside the new
        member follow-up feature - see setup_groups.py's _setup_ushers - so
        an usher greeting a first-time visitor can enter their basic details
        themselves, but still can't edit an existing member's record.
        """
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_list"))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse("staff_member_create"))
        self.assertEqual(response.status_code, 200)

        member = Member.objects.create(first_name="Efua", last_name="Asare")
        response = self.client.get(reverse("staff_member_edit", args=[member.id]))
        self.assertRedirects(response, reverse("dashboard"))

    def test_treasurer_cannot_view_members_or_events(self):
        self.client.force_login(self.treasurer)
        self.assertRedirects(self.client.get(reverse("staff_member_list")), reverse("dashboard"))
        self.assertRedirects(self.client.get(reverse("staff_event_list")), reverse("dashboard"))

    def test_pastor_can_add_member(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_member_create"),
            {"first_name": "Efua", "last_name": "Asare", "role": Member.Role.MEMBER, "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Member.objects.filter(first_name="Efua", last_name="Asare").exists())

    def test_pending_donations_stat_hidden_from_usher(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_home"))
        self.assertNotContains(response, "Pending gifts")

    def test_pending_donations_stat_shown_to_pastor(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_home"))
        self.assertContains(response, "Pending gifts")

    def test_usher_cannot_add_a_ticket_type(self):
        """Event tickets/registrations are Pastor-only (see PASTOR_MODELS) - no Usher grant touches them."""
        event = Event.objects.create(
            title="Youth Retreat", start_datetime=timezone.now() + timezone.timedelta(days=10)
        )
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_ticket_create", args=[event.id]),
            {"name": "Adult", "price": "150.00"},
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(EventTicket.objects.filter(event=event).exists())


class StaffHomeGlanceWidgetTests(TestCase):
    """The staff_home "This Week at a Glance" card - each row gated on its own permission."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher-glance", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor-glance", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_pastor_sees_the_glance_card(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_home"))
        self.assertContains(response, "This Week at a Glance")

    def test_events_this_week_are_counted_but_a_further_out_event_is_not(self):
        Event.objects.create(title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=2))
        Event.objects.create(title="Christmas Service", start_datetime=timezone.now() + timezone.timedelta(days=30))
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_home"))
        self.assertContains(response, "Sunday Service")
        self.assertNotContains(response, "Christmas Service")

    def test_a_pending_care_request_is_counted_for_a_pastor(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante")
        CareRequest.objects.create(member=member, details="Please pray with me.")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_home"))
        self.assertContains(response, "1</strong> care request")

    def test_care_requests_row_hidden_from_an_usher(self):
        member = Member.objects.create(first_name="Efua", last_name="Asante")
        CareRequest.objects.create(member=member, details="Please pray with me.")
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_home"))
        self.assertNotContains(response, "care request")

    def test_glance_card_is_hidden_for_a_viewer_with_none_of_the_underlying_permissions(self):
        # setup_groups doesn't grant Children's Ministry any of the six
        # permissions the widget checks, so its card should simply not render.
        childrens_worker = User.objects.create_user(
            username="cworker-glance", password="test-pass-123", is_staff=True
        )
        childrens_worker.groups.add(Group.objects.get(name="Children's Ministry"))
        self.client.force_login(childrens_worker)
        response = self.client.get(reverse("staff_home"))
        self.assertNotContains(response, "This Week at a Glance")


class StaffEventManagementTests(TestCase):
    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor2", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.client.force_login(self.pastor)

    def test_pastor_can_create_event(self):
        """
        Also exercises the datetime-local input format fix in staff/forms.py -
        this is exactly the "2026-01-15T09:00" shape a browser's date/time
        picker actually submits.
        """
        response = self.client.post(
            reverse("staff_event_create"),
            {
                "title": "Youth Camp",
                "description": "",
                "event_type": Event.EventType.OUTREACH,
                "start_datetime": "2027-01-15T09:00",
                "end_datetime": "",
                "location": "Camp Grounds",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Event.objects.filter(title="Youth Camp").exists())

    def test_pastor_can_add_volunteer_slot_to_event(self):
        event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=3)
        )
        response = self.client.post(
            reverse("staff_slot_create", args=[event.id]),
            {"role_needed": "Usher", "capacity": 3},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(VolunteerSlot.objects.filter(event=event, role_needed="Usher", capacity=3).exists())

    def test_pastor_can_add_a_service_time_to_event(self):
        event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=3)
        )
        response = self.client.post(
            reverse("staff_event_service_time_create", args=[event.id]),
            {"label": "8:00 AM Service", "start_time": "08:00", "location": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(EventServiceTime.objects.filter(event=event, label="8:00 AM Service").exists())

    def test_usher_cannot_add_a_service_time_to_event(self):
        event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=3)
        )
        usher = User.objects.create_user(username="usher-service-time", password="test-pass-123", is_staff=True)
        usher.groups.add(Group.objects.get(name="Ushers"))
        self.client.force_login(usher)
        response = self.client.post(
            reverse("staff_event_service_time_create", args=[event.id]),
            {"label": "8:00 AM Service", "start_time": "08:00", "location": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(EventServiceTime.objects.filter(event=event).exists())

    def test_pastor_can_add_ticket_type_to_event(self):
        event = Event.objects.create(
            title="Youth Retreat", start_datetime=timezone.now() + timezone.timedelta(days=10)
        )
        response = self.client.post(
            reverse("staff_ticket_create", args=[event.id]),
            {"name": "Adult", "price": "150.00", "capacity": 50},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(EventTicket.objects.filter(event=event, name="Adult", price="150.00").exists())

    def test_pastor_can_edit_a_ticket_type(self):
        event = Event.objects.create(
            title="Youth Retreat", start_datetime=timezone.now() + timezone.timedelta(days=10)
        )
        ticket = EventTicket.objects.create(event=event, name="Adult", price="150.00")
        response = self.client.post(
            reverse("staff_ticket_edit", args=[ticket.id]),
            {"name": "Adult", "price": "175.00", "capacity": ""},
        )
        self.assertEqual(response.status_code, 302)
        ticket.refresh_from_db()
        self.assertEqual(str(ticket.price), "175.00")

    def test_event_detail_shows_ticket_registrants(self):
        event = Event.objects.create(
            title="Youth Retreat", start_datetime=timezone.now() + timezone.timedelta(days=10)
        )
        ticket = EventTicket.objects.create(event=event, name="Adult", price="150.00")
        member = Member.objects.create(first_name="Kofi", last_name="Addo")
        EventRegistration.objects.create(
            ticket=ticket, member=member, status=EventRegistration.Status.COMPLETED
        )
        response = self.client.get(reverse("staff_event_detail", args=[event.id]))
        self.assertContains(response, "Kofi Addo")
        self.assertContains(response, "Adult")

    def test_event_detail_shows_the_qr_checkin_card_and_count(self):
        event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=3)
        )
        member = Member.objects.create(first_name="Kofi", last_name="Addo")
        Attendance.objects.create(member=member, date=timezone.localdate(), event=event, present=True)
        response = self.client.get(reverse("staff_event_detail", args=[event.id]))
        self.assertContains(response, "QR Check-In")
        self.assertContains(response, reverse("event_qr_code", args=[event.id]))
        self.assertContains(response, reverse("event_qr_checkin", args=[event.id]))
        self.assertContains(response, "1 checked in via QR so far")

    def test_event_detail_shows_an_initials_avatar_for_an_rsvp_without_a_photo(self):
        event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=3)
        )
        member = Member.objects.create(first_name="Adjoa", last_name="Mensah")
        RSVP.objects.create(event=event, member=member, status=RSVP.Status.GOING)
        response = self.client.get(reverse("staff_event_detail", args=[event.id]))
        self.assertContains(response, '<span class="avatar">AM</span>')

    def test_event_detail_links_to_kiosk_mode(self):
        event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=3)
        )
        response = self.client.get(reverse("staff_event_detail", args=[event.id]))
        self.assertContains(response, "Open kiosk mode")
        self.assertContains(response, reverse("event_kiosk_checkin", args=[event.id]))

    def test_creating_a_weekly_event_generates_the_rest_of_the_series(self):
        response = self.client.post(
            reverse("staff_event_create"),
            {
                "title": "Sunday Service",
                "description": "",
                "event_type": Event.EventType.SERVICE,
                "start_datetime": "2027-03-07T09:00",
                "end_datetime": "",
                "location": "Main Hall",
                "recurrence": Event.Recurrence.WEEKLY,
                "occurrences": 4,
            },
        )
        self.assertEqual(response.status_code, 302)
        parent = Event.objects.get(title="Sunday Service", series_parent__isnull=True)
        self.assertEqual(Event.objects.filter(series_parent=parent).count(), 3)

    def test_leaving_repeat_as_none_creates_only_one_event(self):
        self.client.post(
            reverse("staff_event_create"),
            {
                "title": "One-off Meeting",
                "description": "",
                "event_type": Event.EventType.MEETING,
                "start_datetime": "2027-03-10T09:00",
                "end_datetime": "",
                "location": "",
            },
        )
        self.assertEqual(Event.objects.filter(title="One-off Meeting").count(), 1)


class StaffDonationManagementTests(TestCase):
    """The donations side of the staff area - Treasurers and Pastors only."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher2", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer2", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))

    def test_usher_cannot_view_donations(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_donation_list")), reverse("dashboard"))

    def test_treasurer_can_log_a_gift(self):
        self.client.force_login(self.treasurer)
        response = self.client.post(
            reverse("staff_donation_create"), {"amount": "75.00", "donation_type": Donation.DonationType.TITHE}
        )
        self.assertEqual(response.status_code, 302)
        donation = Donation.objects.latest("date")
        self.assertEqual(str(donation.amount), "75.00")
        # Logging a gift never skips the reconciliation step, even for staff.
        self.assertEqual(donation.status, Donation.Status.PENDING)

    def test_treasurer_can_mark_a_pending_gift_completed(self):
        donation = Donation.objects.create(amount="30.00", status=Donation.Status.PENDING)
        self.client.force_login(self.treasurer)
        response = self.client.post(reverse("staff_donation_complete", args=[donation.id]))
        self.assertEqual(response.status_code, 302)
        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.COMPLETED)

    def test_logging_a_gift_notifies_treasurers(self):
        # Covers a Pastor logging a gift too, not just a Treasurer logging
        # their own - notification only depends on who's in the group.
        self.treasurer.email = "treasurer2@example.com"
        self.treasurer.save()
        self.client.force_login(self.treasurer)
        self.client.post(
            reverse("staff_donation_create"), {"amount": "75.00", "donation_type": Donation.DonationType.TITHE}
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("treasurer2@example.com", mail.outbox[0].to)


class StaffHouseholdManagementTests(TestCase):
    """
    Households - Pastors only, same as sermons. Assigning/removing a member
    from a household is gated on members.change_member (it edits Member,
    not Household), so these also confirm that permission is what actually
    controls it, not household add/change alone.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher4", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor4", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_usher_cannot_view_households(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_household_list")), reverse("dashboard"))

    def test_pastor_can_create_household(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_household_create"), {"name": "The Osei Family", "address": "12 Ring Rd", "phone": ""}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Household.objects.filter(name="The Osei Family").exists())

    def test_pastor_can_add_member_to_household(self):
        household = Household.objects.create(name="The Boateng Family")
        member = Member.objects.create(first_name="Kwesi", last_name="Boateng")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_household_add_member", args=[household.id]), {"member_id": member.id}
        )
        self.assertEqual(response.status_code, 302)
        member.refresh_from_db()
        self.assertEqual(member.household, household)

    def test_pastor_can_remove_member_from_household(self):
        household = Household.objects.create(name="The Owusu Family")
        member = Member.objects.create(first_name="Abena", last_name="Owusu", household=household)
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_household_remove_member", args=[household.id, member.id]))
        self.assertEqual(response.status_code, 302)
        member.refresh_from_db()
        self.assertIsNone(member.household)


class StaffHouseholdBulkActionTests(TestCase):
    """
    The "Bulk Actions" card on the household detail page (view/permission
    layer on top of members/tests.py's HouseholdBulkActionsTests, which
    covers the underlying services.py functions themselves) - gated on
    members.change_member, same as adding/removing a household member.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher-hh-bulk", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor-hh-bulk", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.household = Household.objects.create(name="The Amoah Family", phone="0244999999")
        self.member = Member.objects.create(first_name="Kwaku", last_name="Amoah", household=self.household)

    def test_usher_cannot_perform_a_bulk_action(self):
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_household_bulk_action", args=[self.household.id]), {"action": "set_inactive"}
        )
        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    def test_pastor_can_set_campus_for_the_whole_household(self):
        campus = Campus.objects.create(name="East Legon Campus")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_household_bulk_action", args=[self.household.id]),
            {"action": "set_campus", "campus_id": campus.id},
        )
        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.assertEqual(self.member.campus, campus)

    def test_pastor_can_sync_household_phone(self):
        self.client.force_login(self.pastor)
        self.client.post(reverse("staff_household_bulk_action", args=[self.household.id]), {"action": "sync_phone"})
        self.member.refresh_from_db()
        self.assertEqual(self.member.phone, "0244999999")

    def test_pastor_can_mark_the_whole_household_inactive_and_active_again(self):
        self.client.force_login(self.pastor)
        self.client.post(reverse("staff_household_bulk_action", args=[self.household.id]), {"action": "set_inactive"})
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)

        self.client.post(reverse("staff_household_bulk_action", args=[self.household.id]), {"action": "set_active"})
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    def test_household_detail_shows_the_bulk_actions_card_to_a_pastor_but_not_an_usher(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_household_detail", args=[self.household.id]))
        self.assertContains(response, "Bulk Actions")

        # Ushers don't have members.view_household at all (see
        # _setup_ushers), so they're redirected away from the page entirely
        # rather than seeing it with the card merely hidden - assertNotContains
        # assumes a 200 response, so check the redirect directly instead.
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_household_detail", args=[self.household.id]))
        self.assertEqual(response.status_code, 302)


class StaffGroupManagementTests(TestCase):
    """
    Ministries/small groups/committees - Pastors only, same as households.
    Removing a member marks GroupMembership.left_date rather than deleting
    the row (no staff role has delete permission on anything - see
    setup_groups), which these tests confirm directly.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher5", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor5", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_usher_cannot_view_groups(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_group_list")), reverse("dashboard"))

    def test_pastor_can_create_group(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_group_create"),
            {"name": "Youth Ministry", "group_type": "ministry", "description": "", "leader": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ChurchGroup.objects.filter(name="Youth Ministry").exists())

    def test_pastor_can_tag_a_group_with_interest_skills(self):
        skill = Skill.objects.create(name="Music")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_group_create"),
            {
                "name": "Worship Team",
                "group_type": "ministry",
                "description": "",
                "leader": "",
                "interest_skills": [skill.id],
            },
        )
        self.assertEqual(response.status_code, 302)
        group = ChurchGroup.objects.get(name="Worship Team")
        self.assertIn(skill, group.interest_skills.all())

    def test_pastor_can_add_member_to_group(self):
        group = ChurchGroup.objects.create(name="Choir", group_type="ministry")
        member = Member.objects.create(first_name="Adjoa", last_name="Mensah")
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_group_add_member", args=[group.id]), {"member_id": member.id})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            GroupMembership.objects.filter(group=group, member=member, left_date__isnull=True).exists()
        )

    def test_group_detail_shows_an_initials_avatar_for_leader_and_members_without_a_photo(self):
        member = Member.objects.create(first_name="Adjoa", last_name="Mensah")
        group = ChurchGroup.objects.create(name="Choir", group_type="ministry", leader=member)
        GroupMembership.objects.create(group=group, member=member)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_group_detail", args=[group.id]))
        # "AM" appears twice - once for the leader row, once for the roster row.
        self.assertContains(response, '<span class="avatar">AM</span>', count=2)

    def test_pastor_can_remove_member_from_group_without_deleting_the_record(self):
        group = ChurchGroup.objects.create(name="Ushering Team", group_type="ministry")
        member = Member.objects.create(first_name="Yaw", last_name="Darko")
        membership = GroupMembership.objects.create(group=group, member=member)
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_group_remove_member", args=[group.id, member.id]))
        self.assertEqual(response.status_code, 302)
        membership.refresh_from_db()
        self.assertIsNotNone(membership.left_date)
        self.assertFalse(membership.is_active)

    def test_pastor_can_set_a_member_cap_on_a_group(self):
        group = ChurchGroup.objects.create(name="Youth Ministry", group_type="ministry")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_group_edit", args=[group.id]),
            {"name": "Youth Ministry", "group_type": "ministry", "description": "", "leader": "", "max_members": "10"},
        )
        self.assertEqual(response.status_code, 302)
        group.refresh_from_db()
        self.assertEqual(group.max_members, 10)

    def test_staff_can_add_a_member_over_the_cap(self):
        """
        The self-service join_group view enforces max_members (see
        members/tests.py's GroupSelfServiceTests) - staff adding someone
        from the group's own page is deliberately exempt, same as a
        Pastor's other admin overrides in this project.
        """
        group = ChurchGroup.objects.create(name="Small Group", group_type="small_group", max_members=1)
        existing = Member.objects.create(first_name="Ama", last_name="Owusu")
        GroupMembership.objects.create(group=group, member=existing)
        new_member = Member.objects.create(first_name="Kojo", last_name="Mensah")

        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_group_add_member", args=[group.id]), {"member_id": new_member.id})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            GroupMembership.objects.filter(group=group, member=new_member, left_date__isnull=True).exists()
        )

    def test_group_detail_shows_full_badge_once_capped(self):
        group = ChurchGroup.objects.create(name="Small Group", group_type="small_group", max_members=1)
        member = Member.objects.create(first_name="Ama", last_name="Owusu")
        GroupMembership.objects.create(group=group, member=member)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_group_detail", args=[group.id]))
        self.assertContains(response, "Full")


class StaffReportsTests(TestCase):
    """
    The reports page shows each section only if the signed-in user has
    permission to see that kind of record - same rule as the staff home
    page's stats and the global search box (see staff/views.py's
    reports_overview).
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher10", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer10", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.pastor = User.objects.create_user(username="pastor10", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.member = Member.objects.create(first_name="Adjoa", last_name="Frimpong")

    def test_usher_sees_attendance_but_not_giving(self):
        Donation.objects.create(member=self.member, amount="50.00", status=Donation.Status.COMPLETED)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_reports"))
        self.assertContains(response, "Attendance")
        self.assertNotContains(response, "Giving (completed gifts")

    def test_treasurer_sees_giving_but_not_attendance(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_reports"))
        self.assertContains(response, "Giving (completed gifts")
        self.assertNotContains(response, "Attendance (present")

    def test_usher_sees_the_weekly_attendance_trend(self):
        Attendance.objects.create(member=self.member, date=timezone.localdate(), present=True)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_reports"))
        self.assertContains(response, "Attendance Trend (present, by week)")

    def test_no_campus_breakdown_shown_with_only_one_campus(self):
        Attendance.objects.create(member=self.member, date=timezone.localdate(), present=True)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_reports"))
        self.assertNotContains(response, "Attendance by Campus")

    def test_campus_breakdown_shown_once_a_second_campus_exists(self):
        main = Campus.objects.create(name="Main Campus")
        second = Campus.objects.create(name="East Campus")
        self.member.campus = main
        self.member.save()
        Attendance.objects.create(member=self.member, date=timezone.localdate(), present=True, campus=main)
        other_member = Member.objects.create(first_name="Kojo", last_name="Boateng", campus=second)
        Attendance.objects.create(member=other_member, date=timezone.localdate(), present=True, campus=second)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_reports"))
        self.assertContains(response, "Attendance by Campus")
        self.assertContains(response, "Main Campus")
        self.assertContains(response, "East Campus")

    def test_treasurer_sees_income_vs_expenses_with_correct_net(self):
        Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        category = BudgetCategory.objects.create(name="Utilities")
        Expense.objects.create(category=category, amount="30.00", date=timezone.localdate())
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_reports"))
        self.assertContains(response, "Income vs. expenses")
        self.assertContains(response, "100.00")
        self.assertContains(response, "30.00")
        self.assertContains(response, "70.00")

    def test_usher_does_not_see_income_vs_expenses(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_reports"))
        self.assertNotContains(response, "Income vs. expenses")

    def test_treasurer_sees_the_year_over_year_giving_comparison(self):
        # Donation.date is auto_now_add, so a custom date passed to create()
        # is silently ignored - back-date with a queryset .update() instead,
        # the same pattern giving/tests.py already uses for this.
        this_year = timezone.localdate().year
        this_year_gift = Donation.objects.create(
            member=self.member, amount="100.00", status=Donation.Status.COMPLETED,
        )
        Donation.objects.filter(pk=this_year_gift.pk).update(date=date(this_year, 1, 15))
        last_year_gift = Donation.objects.create(
            member=self.member, amount="75.00", status=Donation.Status.COMPLETED,
        )
        Donation.objects.filter(pk=last_year_gift.pk).update(date=date(this_year - 1, 1, 15))
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_reports"))
        self.assertContains(response, "Giving Comparison, Year Over Year")
        self.assertContains(response, str(this_year))
        self.assertContains(response, str(this_year - 1))
        self.assertContains(response, "100.00")
        self.assertContains(response, "75.00")

    def test_usher_does_not_see_the_giving_comparison(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_reports"))
        self.assertNotContains(response, "Giving Comparison, Year Over Year")

    def test_giving_comparison_excludes_gifts_older_than_the_comparison_window(self):
        # Donation.date is auto_now_add, so a custom date passed to create()
        # is silently ignored - back-date with a queryset .update() instead,
        # the same pattern used above in the year-over-year comparison test.
        this_year = timezone.localdate().year
        old_gift = Donation.objects.create(
            member=self.member, amount="500.00", status=Donation.Status.COMPLETED,
        )
        Donation.objects.filter(pk=old_gift.pk).update(date=date(this_year - 5, 6, 1))
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_reports"))
        self.assertNotContains(response, str(this_year - 5))
        # Not a page-wide assertNotContains("500.00") - the page's separate
        # "Giving by type (all time)" card intentionally totals every
        # completed gift regardless of age, so the old gift legitimately
        # shows up there. Check the year-over-year comparison data itself
        # (the thing this test is actually about) instead of scanning the
        # whole page's text.
        comparison_years = [row["year"] for row in response.context["giving_year_comparison_totals"]]
        self.assertNotIn(this_year - 5, comparison_years)
        self.assertEqual(sum(row["total"] for row in response.context["giving_year_comparison_totals"]), 0)

    def test_only_pastor_sees_the_backup_download_link(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_reports"))
        self.assertContains(response, "Full Data Backup")

        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_reports"))
        self.assertNotContains(response, "Full Data Backup")

    def test_usher_cannot_download_the_full_backup(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_full_backup"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_pastor_can_download_a_full_backup_zip_with_every_csv(self):
        Donation.objects.create(member=self.member, amount="50.00", status=Donation.Status.COMPLETED)
        category = BudgetCategory.objects.create(name="Utilities")
        Expense.objects.create(category=category, amount="20.00", date=timezone.localdate())
        Event.objects.create(title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=1))
        Attendance.objects.create(member=self.member, date=timezone.localdate(), present=True)

        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_full_backup"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")

        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
            names = set(zip_file.namelist())
            self.assertEqual(
                names, {"members.csv", "households.csv", "attendance.csv", "donations.csv", "expenses.csv", "events.csv"}
            )
            # first_name/last_name are separate CSV columns (matching the
            # member import format), not a single combined name column.
            self.assertIn("Adjoa,Frimpong", zip_file.read("members.csv").decode())
            self.assertIn("50.00", zip_file.read("donations.csv").decode())
            self.assertIn("20.00", zip_file.read("expenses.csv").decode())
            self.assertIn("Sunday Service", zip_file.read("events.csv").decode())

    def test_giving_by_member_totals_are_correct(self):
        # Donation.date is auto_now_add, so both gifts land in the current
        # year automatically - exactly what this test needs.
        Donation.objects.create(member=self.member, amount="60.00", status=Donation.Status.COMPLETED)
        Donation.objects.create(member=self.member, amount="40.00", status=Donation.Status.PENDING)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_giving_by_member"), {"year": timezone.now().year})
        self.assertContains(response, "Adjoa Frimpong")
        self.assertContains(response, "60.00")
        self.assertNotContains(response, "40.00")


class StaffDirectoryBookletTests(TestCase):
    """
    The printable directory booklet - gated the same "Pastor-only" way as
    the full data backup export (care.view_carerequest), since it bundles
    everyone's shared directory info into one document at once.
    """

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-booklet", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-booklet", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))

    def test_usher_cannot_view_the_booklet(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_directory_booklet"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_only_pastor_sees_the_booklet_link_on_the_member_list(self):
        self.client.force_login(self.pastor)
        self.assertContains(self.client.get(reverse("staff_member_list")), "Directory Booklet")

        self.client.force_login(self.usher)
        self.assertNotContains(self.client.get(reverse("staff_member_list")), "Directory Booklet")

    def test_only_members_who_opted_in_appear(self):
        Member.objects.create(first_name="Kojo", last_name="Mensah", share_in_directory=True)
        Member.objects.create(first_name="Ama", last_name="Boateng", share_in_directory=False)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_directory_booklet"))
        self.assertContains(response, "Kojo Mensah")
        self.assertNotContains(response, "Ama Boateng")

    def test_an_inactive_member_is_never_shown_even_if_opted_in(self):
        Member.objects.create(
            first_name="Yaw", last_name="Osei", share_in_directory=True, is_active=False
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_directory_booklet"))
        self.assertNotContains(response, "Yaw Osei")

    def test_phone_and_email_only_show_when_separately_shared(self):
        Member.objects.create(
            first_name="Kojo", last_name="Mensah", share_in_directory=True,
            phone="0244000000", share_phone_in_directory=True,
            email="kojo@example.com", share_email_in_directory=False,
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_directory_booklet"))
        self.assertContains(response, "0244000000")
        self.assertNotContains(response, "kojo@example.com")

    def test_members_are_grouped_by_household(self):
        household = Household.objects.create(name="The Mensah Family")
        Member.objects.create(
            first_name="Kojo", last_name="Mensah", share_in_directory=True, household=household
        )
        Member.objects.create(
            first_name="Ama", last_name="Mensah", share_in_directory=True, household=household
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_directory_booklet"))
        self.assertContains(response, "The Mensah Family")
        [group] = [g for g in response.context["households"] if g["household"] == household]
        self.assertEqual({m.first_name for m in group["members"]}, {"Kojo", "Ama"})

    def test_a_member_with_no_household_is_grouped_separately(self):
        Member.objects.create(first_name="Yaw", last_name="Osei", share_in_directory=True)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_directory_booklet"))
        self.assertContains(response, "No Household on File")


class StaffAbsenteeListTests(TestCase):
    """The absentee list - same members.view_attendance permission as the reports page's attendance section."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher-absent", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer-absent", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.pastor = User.objects.create_user(username="pastor-absent", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_treasurer_cannot_view_the_absentee_list(self):
        self.client.force_login(self.treasurer)
        self.assertRedirects(self.client.get(reverse("staff_absentee_list")), reverse("dashboard"))

    def test_usher_sees_an_absentee_member(self):
        member = Member.objects.create(first_name="Kwame", last_name="Ansah")
        Member.objects.filter(pk=member.pk).update(date_joined=timezone.localdate() - timezone.timedelta(weeks=10))
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_absentee_list"))
        self.assertContains(response, "Kwame Ansah")
        self.assertContains(response, "Never attended")

    def test_a_recently_active_member_is_not_listed(self):
        member = Member.objects.create(first_name="Kwame", last_name="Ansah")
        Member.objects.filter(pk=member.pk).update(date_joined=timezone.localdate() - timezone.timedelta(weeks=10))
        Attendance.objects.create(member=member, date=timezone.localdate(), present=True)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_absentee_list"))
        self.assertContains(response, "Nobody's fallen off the radar")

    def test_usher_can_start_a_follow_up_from_the_list(self):
        member = Member.objects.create(first_name="Kwame", last_name="Ansah")
        Member.objects.filter(pk=member.pk).update(date_joined=timezone.localdate() - timezone.timedelta(weeks=10))
        self.client.force_login(self.usher)
        response = self.client.post(reverse("staff_followup_start", args=[member.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(FollowUp.objects.filter(member=member).exists())


class AnnualStatisticsServiceTests(TestCase):
    """Direct tests of staff/services.py's annual_statistics - the year-end rollup behind the report page."""

    def test_milestones_are_counted_for_the_chosen_year_only(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        other_member = Member.objects.create(first_name="Ama", last_name="Boateng")
        BaptismRecord.objects.create(member=member, baptism_date=date(2026, 3, 1))
        BaptismRecord.objects.create(member=other_member, baptism_date=date(2025, 3, 1))
        WeddingRecord.objects.create(spouse_one=member, spouse_two=other_member, wedding_date=date(2026, 6, 1))
        BabyDedication.objects.create(child_name="Baby Mensah", dedication_date=date(2026, 1, 15))
        TransferLetter.objects.create(
            member=member, destination_church="Grace Chapel", transfer_date=date(2026, 8, 1)
        )
        deceased = Member.objects.create(first_name="Yaw", last_name="Osei")
        FuneralRecord.objects.create(member=deceased, service_date=date(2026, 9, 1))

        stats = annual_statistics(2026)
        self.assertEqual(stats["baptisms"], 1)
        self.assertEqual(stats["weddings"], 1)
        self.assertEqual(stats["baby_dedications"], 1)
        self.assertEqual(stats["transfer_letters"], 1)
        self.assertEqual(stats["funerals"], 1)

        earlier_year_stats = annual_statistics(2025)
        self.assertEqual(earlier_year_stats["baptisms"], 1)
        self.assertEqual(earlier_year_stats["weddings"], 0)

    def test_decisions_are_broken_out_by_type_and_totalled(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        Decision.objects.create(member=member, decision_type=Decision.DecisionType.SALVATION, date=date(2026, 2, 1))
        Decision.objects.create(member=member, decision_type=Decision.DecisionType.SALVATION, date=date(2026, 4, 1))
        Decision.objects.create(
            member=member, decision_type=Decision.DecisionType.REDEDICATION, date=date(2026, 5, 1)
        )
        Decision.objects.create(member=member, decision_type=Decision.DecisionType.SALVATION, date=date(2025, 2, 1))

        stats = annual_statistics(2026)
        self.assertEqual(stats["total_decisions"], 3)
        by_label = {row["label"]: row["count"] for row in stats["decisions_by_type"]}
        self.assertEqual(by_label[Decision.DecisionType.SALVATION.label], 2)
        self.assertEqual(by_label[Decision.DecisionType.REDEDICATION.label], 1)

    def test_new_members_counts_members_joined_that_year(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        Member.objects.filter(pk=member.pk).update(date_joined=date(2026, 1, 10))
        other = Member.objects.create(first_name="Ama", last_name="Boateng")
        Member.objects.filter(pk=other.pk).update(date_joined=date(2025, 1, 10))

        stats = annual_statistics(2026)
        self.assertEqual(stats["new_members"], 1)

    def test_average_attendance_is_averaged_across_recorded_service_dates_only(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        other = Member.objects.create(first_name="Ama", last_name="Boateng")
        third = Member.objects.create(first_name="Yaw", last_name="Osei")
        # Two service dates in 2026: one with 2 present, one with 1 present -
        # average should be 1.5, rounded to 2, not divided by 52 weeks.
        Attendance.objects.create(member=member, date=date(2026, 1, 4), present=True)
        Attendance.objects.create(member=other, date=date(2026, 1, 4), present=True)
        Attendance.objects.create(member=third, date=date(2026, 1, 11), present=True)

        stats = annual_statistics(2026)
        self.assertEqual(stats["service_dates_recorded"], 2)
        self.assertEqual(stats["average_attendance"], 2)

    def test_a_group_meetings_attendance_is_excluded_from_the_average(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        group = ChurchGroup.objects.create(name="Youth Group")
        Attendance.objects.create(member=member, date=date(2026, 1, 4), present=True, group=group)

        stats = annual_statistics(2026)
        self.assertEqual(stats["service_dates_recorded"], 0)
        self.assertEqual(stats["average_attendance"], 0)

    def test_absent_attendance_rows_are_not_counted(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        Attendance.objects.create(member=member, date=date(2026, 1, 4), present=False)

        stats = annual_statistics(2026)
        self.assertEqual(stats["service_dates_recorded"], 0)

    def test_total_giving_only_counts_completed_gifts_in_the_year(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        this_year = Donation.objects.create(member=member, amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.filter(pk=this_year.pk).update(date=date(2026, 3, 1))
        pending = Donation.objects.create(member=member, amount="999.00", status=Donation.Status.PENDING)
        Donation.objects.filter(pk=pending.pk).update(date=date(2026, 3, 1))
        last_year = Donation.objects.create(member=member, amount="50.00", status=Donation.Status.COMPLETED)
        Donation.objects.filter(pk=last_year.pk).update(date=date(2025, 3, 1))

        stats = annual_statistics(2026)
        self.assertEqual(stats["total_giving"], Decimal("100.00"))

    def test_a_year_with_nothing_recorded_returns_all_zeroes(self):
        stats = annual_statistics(2030)
        self.assertEqual(stats["baptisms"], 0)
        self.assertEqual(stats["total_decisions"], 0)
        self.assertEqual(stats["new_members"], 0)
        self.assertEqual(stats["average_attendance"], 0)
        self.assertEqual(stats["total_giving"], Decimal("0.00"))


class StaffAnnualStatisticsReportTests(TestCase):
    """The annual statistics report page - Pastor-only, same care.view_carerequest gate as full_backup_export."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-annual", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-annual", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))

    def test_usher_cannot_view_the_report(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_annual_statistics"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_pastor_can_view_the_report_for_the_current_year_by_default(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_annual_statistics"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["stats"]["year"], timezone.localdate().year)

    def test_pastor_can_choose_a_different_year(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        BaptismRecord.objects.create(member=member, baptism_date=date(2020, 5, 1))
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_annual_statistics"), {"year": "2020"})
        self.assertEqual(response.context["stats"]["year"], 2020)
        self.assertEqual(response.context["stats"]["baptisms"], 1)

    def test_an_invalid_year_falls_back_to_the_current_year(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_annual_statistics"), {"year": "not-a-year"})
        self.assertEqual(response.context["stats"]["year"], timezone.localdate().year)

    def test_only_pastor_sees_the_annual_statistics_link_on_reports(self):
        self.client.force_login(self.pastor)
        self.assertContains(self.client.get(reverse("staff_reports")), "Annual Statistics")

        self.client.force_login(self.usher)
        self.assertNotContains(self.client.get(reverse("staff_reports")), "Annual Statistics")

    def test_report_shows_the_decision_type_breakdown(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        Decision.objects.create(
            member=member, decision_type=Decision.DecisionType.SALVATION, date=timezone.localdate()
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_annual_statistics"))
        self.assertContains(response, "Salvation")


class StaffMemberImportExportTests(TestCase):
    """CSV bulk import/export of members - see staff/services.py's import_members_csv."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher9", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor9", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def _csv_file(self, content):
        return SimpleUploadedFile("members.csv", content.encode("utf-8"), content_type="text/csv")

    def test_usher_cannot_import_members(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_member_import")), reverse("dashboard"))

    def test_pastor_can_import_valid_rows(self):
        csv_content = "first_name,last_name,email,role\nEsi,Danso,esi@example.com,member\n"
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_member_import"), {"csv_file": self._csv_file(csv_content)})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Member.objects.filter(first_name="Esi", last_name="Danso").exists())

    def test_row_missing_a_required_field_is_reported_and_skipped(self):
        csv_content = "first_name,last_name\n,NoFirstName\nKofi,Mensah\n"
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_member_import"), {"csv_file": self._csv_file(csv_content)})
        self.assertContains(response, "Row 2")
        self.assertTrue(Member.objects.filter(first_name="Kofi", last_name="Mensah").exists())
        self.assertFalse(Member.objects.filter(last_name="NoFirstName").exists())

    def test_import_matches_an_existing_household_by_name(self):
        household = Household.objects.create(name="The Appiah Family")
        csv_content = f"first_name,last_name,household\nAma,Appiah,{household.name}\n"
        self.client.force_login(self.pastor)
        self.client.post(reverse("staff_member_import"), {"csv_file": self._csv_file(csv_content)})
        member = Member.objects.get(first_name="Ama", last_name="Appiah")
        self.assertEqual(member.household, household)

    def test_export_returns_a_csv_with_member_data(self):
        Member.objects.create(first_name="Yaw", last_name="Osei", email="yaw@example.com")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_export"))
        self.assertEqual(response["Content-Type"], "text/csv")
        content = response.content.decode()
        self.assertIn("Yaw", content)
        self.assertIn("Osei", content)


class StaffCampusManagementTests(TestCase):
    """
    Campuses/branches - Pastors only, same as households and groups. The
    campus field itself only shows up on the member/event/donation forms
    once a second campus exists (see StaffMemberForm etc. in staff/forms.py) -
    the campus management screens are always reachable by permission alone,
    which is what most of these tests check.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher7", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor7", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_usher_cannot_view_campuses(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_campus_list")), reverse("dashboard"))

    def test_pastor_can_create_campus(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_campus_create"),
            {"name": "Tema Branch", "address": "Tema Community 5", "service_times": "Sundays 8am & 10am"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Campus.objects.filter(name="Tema Branch").exists())

    def test_campus_field_is_hidden_from_member_form_with_one_or_no_campus(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_create"))
        self.assertNotContains(response, 'name="campus"')

    def test_campus_field_appears_on_member_form_once_a_second_campus_exists(self):
        Campus.objects.create(name="Main Campus")
        Campus.objects.create(name="Tema Branch")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_create"))
        self.assertContains(response, 'name="campus"')

    def test_campus_detail_lists_its_members(self):
        campus = Campus.objects.create(name="Main Campus")
        Member.objects.create(first_name="Abena", last_name="Nkrumah", campus=campus)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_campus_detail", args=[campus.id]))
        self.assertContains(response, "Abena Nkrumah")


class StaffLiveStreamTests(TestCase):
    """The public "Watch Online" page's content - Pastors only, per setup_groups."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher-stream", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor-stream", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_usher_cannot_view_livestream_in_staff_area(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_livestream_list")), reverse("dashboard"))

    def test_pastor_can_post_a_stream_link(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_livestream_create"),
            {
                "title": "Sunday Service - June 1",
                "stream_url": "https://youtube.com/watch?v=abc123",
                "scheduled_for": "2027-06-01T09:00",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(LiveStream.objects.filter(title="Sunday Service - June 1").exists())

    def test_pastor_can_edit_a_stream_link(self):
        stream = LiveStream.objects.create(
            title="Sunday Service", stream_url="https://youtube.com/watch?v=abc123", scheduled_for="2027-06-01T09:00"
        )
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_livestream_edit", args=[stream.id]),
            {
                "title": "Sunday Service (Updated)",
                "stream_url": "https://youtube.com/watch?v=abc123",
                "scheduled_for": "2027-06-01T09:00",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        stream.refresh_from_db()
        self.assertEqual(stream.title, "Sunday Service (Updated)")

    def test_livestream_list_links_to_the_public_page(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_livestream_list"))
        self.assertContains(response, reverse("watch_online"))

    def test_pastor_can_feature_a_stream_on_the_homepage(self):
        stream = LiveStream.objects.create(
            title="Sunday Service", stream_url="https://youtube.com/watch?v=abc123", scheduled_for=timezone.now()
        )
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_livestream_edit", args=[stream.id]),
            {
                "title": stream.title,
                "stream_url": stream.stream_url,
                "scheduled_for": "2027-06-01T09:00",
                "notes": "",
                "featured_on_homepage": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        stream.refresh_from_db()
        self.assertTrue(stream.featured_on_homepage)


class StaffFlyerTests(TestCase):
    """The homepage flyer strip - Pastors only, per setup_groups."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher-flyer", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor-flyer", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_usher_cannot_view_flyers_in_staff_area(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_flyer_list")), reverse("dashboard"))

    def test_pastor_can_add_a_flyer(self):
        self.client.force_login(self.pastor)
        image = SimpleUploadedFile("flyer.gif", TINY_GIF, content_type="image/gif")
        response = self.client.post(
            reverse("staff_flyer_create"),
            {"title": "Vacation Bible School", "image": image, "link_url": "", "is_active": "on", "order": "0"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Flyer.objects.filter(title="Vacation Bible School").exists())

    def test_flyer_image_over_5mb_is_rejected(self):
        from PIL import Image

        # Genuine random pixel data, same approach as members/tests.py's
        # own 5MB-limit test - more reliable than padding a tiny image with
        # junk bytes, which risks failing image validation for the wrong
        # reason before the size check ever runs.
        image = Image.frombytes("RGB", (1400, 1400), os.urandom(1400 * 1400 * 3))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        big_image = SimpleUploadedFile("big.png", buf.read(), content_type="image/png")

        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_flyer_create"),
            {"title": "Too Big", "image": big_image, "link_url": "", "order": "0"},
        )
        self.assertContains(response, "smaller than 5MB")
        self.assertFalse(Flyer.objects.filter(title="Too Big").exists())

    def test_pastor_can_deactivate_a_flyer(self):
        image = SimpleUploadedFile("flyer.gif", TINY_GIF, content_type="image/gif")
        flyer = Flyer.objects.create(title="Old Promo", image=image)
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_flyer_edit", args=[flyer.id]),
            {"title": "Old Promo", "image": "", "link_url": "", "order": "0"},
        )
        self.assertEqual(response.status_code, 302)
        flyer.refresh_from_db()
        self.assertFalse(flyer.is_active)


class StaffSermonManagementTests(TestCase):
    """Sermons/devotionals in the staff area - Pastors only, per setup_groups."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher3", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor3", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_usher_cannot_view_sermons_in_staff_area(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_sermon_list")), reverse("dashboard"))

    def test_pastor_can_post_a_sermon(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_sermon_create"),
            {"title": "Faith That Moves", "speaker": "Pastor Kojo", "date": "2027-02-01", "scripture_reference": "", "media_url": "", "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Sermon.objects.filter(title="Faith That Moves").exists())

    def test_pastor_can_upload_a_study_guide(self):
        guide = SimpleUploadedFile("guide.pdf", b"fake pdf bytes", content_type="application/pdf")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_sermon_create"),
            {
                "title": "Faith That Moves",
                "speaker": "Pastor Kojo",
                "date": "2027-02-01",
                "scripture_reference": "",
                "media_url": "",
                "notes": "",
                "study_guide": guide,
            },
        )
        self.assertEqual(response.status_code, 302)
        sermon = Sermon.objects.get(title="Faith That Moves")
        self.assertTrue(sermon.study_guide)

    def test_study_guide_over_10mb_is_rejected(self):
        oversized = SimpleUploadedFile("guide.pdf", b"x" * (10 * 1024 * 1024 + 1), content_type="application/pdf")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_sermon_create"),
            {
                "title": "Faith That Moves",
                "speaker": "",
                "date": "2027-02-01",
                "scripture_reference": "",
                "media_url": "",
                "notes": "",
                "study_guide": oversized,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "smaller than 10MB")

    def test_pastor_can_upload_a_discussion_guide(self):
        guide = SimpleUploadedFile("questions.pdf", b"fake pdf bytes", content_type="application/pdf")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_sermon_create"),
            {
                "title": "Faith That Moves",
                "speaker": "Pastor Kojo",
                "date": "2027-02-01",
                "scripture_reference": "",
                "media_url": "",
                "notes": "",
                "discussion_guide": guide,
            },
        )
        self.assertEqual(response.status_code, 302)
        sermon = Sermon.objects.get(title="Faith That Moves")
        self.assertTrue(sermon.discussion_guide)

    def test_discussion_guide_over_10mb_is_rejected(self):
        oversized = SimpleUploadedFile("questions.pdf", b"x" * (10 * 1024 * 1024 + 1), content_type="application/pdf")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_sermon_create"),
            {
                "title": "Faith That Moves",
                "speaker": "",
                "date": "2027-02-01",
                "scripture_reference": "",
                "media_url": "",
                "notes": "",
                "discussion_guide": oversized,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "smaller than 10MB")
        self.assertFalse(Sermon.objects.filter(title="Faith That Moves").exists())

    def test_pastor_can_post_a_devotional(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_devotional_create"),
            {"date": "2027-02-01", "title": "Morning Grace", "scripture_reference": "Lam 3:22-23", "body": "His mercies are new every morning."},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Devotional.objects.filter(title="Morning Grace").exists())


class StaffGlobalSearchTests(TestCase):
    """
    The site-wide search box in the staff area header (staff/views.py's
    staff_search) - each section is only included in results (and so only
    ever rendered) when the signed-in user has that model's view permission.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher6", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor6", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.member = Member.objects.create(first_name="Kwame", last_name="Mensah")

    def test_usher_sees_matching_members_but_no_donations_section(self):
        Donation.objects.create(member=self.member, amount="40.00", status=Donation.Status.COMPLETED)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_search"), {"q": "mensah"})
        self.assertContains(response, "Kwame Mensah")
        self.assertNotContains(response, "Donations")

    def test_pastor_sees_donation_results(self):
        Donation.objects.create(member=self.member, amount="40.00", status=Donation.Status.COMPLETED)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_search"), {"q": "mensah"})
        self.assertContains(response, "Donations")
        self.assertContains(response, "40.00")

    def test_blank_query_shows_a_prompt_not_results(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_search"))
        self.assertContains(response, "Type something")


class StaffCampaignManagementTests(TestCase):
    """
    Giving campaigns and pledges - Treasurers and Pastors get the same
    access as donations (see setup_groups); Ushers can't see them at all.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher11", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer11", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))

    def test_usher_cannot_view_campaigns(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_campaign_list")), reverse("dashboard"))

    def test_treasurer_can_create_campaign(self):
        self.client.force_login(self.treasurer)
        response = self.client.post(
            reverse("staff_campaign_create"),
            {
                "name": "Building Fund",
                "description": "",
                "goal_amount": "10000",
                "start_date": "2027-01-01",
                "end_date": "",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(GivingCampaign.objects.filter(name="Building Fund").exists())

    def test_campaign_detail_lists_its_pledges(self):
        campaign = GivingCampaign.objects.create(name="Missions Push", start_date=timezone.localdate())
        member = Member.objects.create(first_name="Efua", last_name="Boateng")
        Pledge.objects.create(campaign=campaign, member=member, amount="100.00")
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_campaign_detail", args=[campaign.id]))
        self.assertContains(response, "Efua Boateng")
        self.assertContains(response, "100.00")

    def test_treasurer_can_edit_campaign(self):
        campaign = GivingCampaign.objects.create(name="Old Name", start_date=timezone.localdate())
        self.client.force_login(self.treasurer)
        response = self.client.post(
            reverse("staff_campaign_edit", args=[campaign.id]),
            {
                "name": "New Name",
                "description": "",
                "goal_amount": "",
                "start_date": "2027-01-01",
                "end_date": "",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.name, "New Name")


class StaffGroupScheduleFormTests(TestCase):
    """The optional meeting-schedule fields added to groups (see the Group model and StaffGroupForm)."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor12", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_pastor_can_set_a_meeting_schedule_on_a_group(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_group_create"),
            {
                "name": "Young Adults Cell",
                "group_type": "small_group",
                "description": "",
                "leader": "",
                "meeting_day": "wed",
                "meeting_time": "18:30",
                "meeting_location": "Room 4",
            },
        )
        self.assertEqual(response.status_code, 302)
        group = ChurchGroup.objects.get(name="Young Adults Cell")
        self.assertEqual(group.meeting_day, "wed")
        self.assertEqual(group.meeting_location, "Room 4")

    def test_group_list_shows_the_meeting_schedule(self):
        ChurchGroup.objects.create(
            name="Sunrise Cell", group_type="small_group", meeting_day="sun", meeting_location="The Mensah home"
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_group_list"))
        self.assertContains(response, "Sunday")
        self.assertContains(response, "The Mensah home")


class StaffRosterGapsTests(TestCase):
    """The Roster Gaps view - upcoming volunteer slots that still have open spots (staff/views.py's roster_gaps)."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher12", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=2)
        )

    def test_a_slot_with_open_spots_is_listed(self):
        VolunteerSlot.objects.create(event=self.event, role_needed="Usher", capacity=3)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_roster_gaps"))
        self.assertContains(response, "Usher")
        self.assertContains(response, "3 of 3 open")

    def test_a_fully_staffed_slot_is_not_listed(self):
        slot = VolunteerSlot.objects.create(event=self.event, role_needed="Media Team", capacity=1)
        member = Member.objects.create(first_name="Efua", last_name="Danso")
        VolunteerSignup.objects.create(slot=slot, member=member)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_roster_gaps"))
        self.assertNotContains(response, "Media Team")

    def test_a_past_events_slot_is_not_listed(self):
        past_event = Event.objects.create(
            title="Old Service", start_datetime=timezone.now() - timezone.timedelta(days=2)
        )
        VolunteerSlot.objects.create(event=past_event, role_needed="Greeter", capacity=2)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_roster_gaps"))
        self.assertNotContains(response, "Greeter")


class StaffCampaignReminderTests(TestCase):
    """Sending pledge-fulfillment reminders on demand (staff/views.py's campaign_send_reminders)."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher13", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer13", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.campaign = GivingCampaign.objects.create(name="Building Fund", start_date=timezone.localdate())

    def test_usher_cannot_send_reminders(self):
        member = Member.objects.create(first_name="Kojo", last_name="Amoah", email="kojo@example.com")
        Pledge.objects.create(campaign=self.campaign, member=member, amount="100.00")
        self.client.force_login(self.usher)
        response = self.client.post(reverse("staff_campaign_send_reminders", args=[self.campaign.id]))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(len(mail.outbox), 0)

    def test_treasurer_can_send_reminders_to_unfulfilled_pledges_only(self):
        unfulfilled_member = Member.objects.create(first_name="Kojo", last_name="Amoah", email="kojo@example.com")
        fulfilled_member = Member.objects.create(first_name="Ama", last_name="Serwaa", email="ama@example.com")
        Pledge.objects.create(campaign=self.campaign, member=unfulfilled_member, amount="100.00")
        fulfilled_pledge = Pledge.objects.create(campaign=self.campaign, member=fulfilled_member, amount="50.00")
        Donation.objects.create(
            campaign=self.campaign, member=fulfilled_member, amount="50.00", status=Donation.Status.COMPLETED
        )
        self.client.force_login(self.treasurer)
        response = self.client.post(reverse("staff_campaign_send_reminders", args=[self.campaign.id]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("kojo@example.com", mail.outbox[0].to)
        self.assertNotIn(fulfilled_pledge.member.email, mail.outbox[0].to)


class StaffChildrenMinistryTests(TestCase):
    """
    Children's check-in - gated to the new "Children's Ministry" group (and
    Pastors, via PASTOR_MODELS) rather than Ushers/Treasurers, per
    setup_groups.py's _setup_childrens_ministry.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher14", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.childrens_worker = User.objects.create_user(username="cworker14", password="test-pass-123", is_staff=True)
        self.childrens_worker.groups.add(Group.objects.get(name="Children's Ministry"))
        self.pastor = User.objects.create_user(username="pastor14", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.household = Household.objects.create(name="The Boateng Family")
        self.child = Child.objects.create(household=self.household, first_name="Nana", last_name="Boateng")

    def test_usher_cannot_view_children(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_child_list")), reverse("dashboard"))

    def test_childrens_worker_can_view_children(self):
        self.client.force_login(self.childrens_worker)
        response = self.client.get(reverse("staff_child_list"))
        self.assertContains(response, "Nana Boateng")

    def test_pastor_can_also_view_children(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_child_list"))
        self.assertContains(response, "Nana Boateng")

    def test_childrens_worker_can_add_a_child(self):
        self.client.force_login(self.childrens_worker)
        response = self.client.post(
            reverse("staff_child_create"),
            {
                "household": self.household.id,
                "first_name": "Kwabena",
                "last_name": "Boateng",
                "date_of_birth": "",
                "allergies_or_medical_notes": "",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Child.objects.filter(first_name="Kwabena", last_name="Boateng").exists())

    def test_childrens_worker_can_check_in_a_child(self):
        self.client.force_login(self.childrens_worker)
        response = self.client.post(
            reverse("staff_checkin_create"),
            {"child": self.child.id, "event": "", "guardian_name": "Auntie Adjoa", "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        check_in = CheckIn.objects.get(child=self.child)
        self.assertEqual(check_in.guardian_name, "Auntie Adjoa")
        self.assertTrue(check_in.is_checked_in)

    def test_checkin_confirmation_shows_the_pickup_code(self):
        self.client.force_login(self.childrens_worker)
        check_in = check_in_child(self.child, guardian_name="Auntie Adjoa", user=self.childrens_worker)
        response = self.client.get(reverse("staff_checkin_confirmation", args=[check_in.id]))
        self.assertContains(response, check_in.pickup_code)

    def test_badge_shows_the_childs_name_and_pickup_code_twice(self):
        self.client.force_login(self.childrens_worker)
        check_in = check_in_child(self.child, guardian_name="Auntie Adjoa", user=self.childrens_worker)
        response = self.client.get(reverse("staff_checkin_badge", args=[check_in.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nana Boateng")
        self.assertContains(response, "Auntie Adjoa")
        # Once for the child's tag, once for the guardian's claim ticket.
        self.assertContains(response, check_in.pickup_code, count=2)

    def test_badge_shows_allergy_notes_when_present(self):
        self.child.allergies_or_medical_notes = "Peanut allergy - EpiPen in bag"
        self.child.save()
        self.client.force_login(self.childrens_worker)
        check_in = check_in_child(self.child, guardian_name="Auntie Adjoa", user=self.childrens_worker)
        response = self.client.get(reverse("staff_checkin_badge", args=[check_in.id]))
        self.assertContains(response, "Peanut allergy")

    def test_badge_omits_allergy_line_when_none_on_file(self):
        self.client.force_login(self.childrens_worker)
        check_in = check_in_child(self.child, guardian_name="Auntie Adjoa", user=self.childrens_worker)
        response = self.client.get(reverse("staff_checkin_badge", args=[check_in.id]))
        self.assertNotContains(response, "&#9888;")

    def test_usher_cannot_view_a_badge(self):
        check_in = check_in_child(self.child, guardian_name="Auntie Adjoa", user=self.childrens_worker)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_checkin_badge", args=[check_in.id]))
        self.assertEqual(response.status_code, 302)

    def test_check_out_with_correct_code_succeeds(self):
        self.client.force_login(self.childrens_worker)
        check_in = check_in_child(self.child, guardian_name="Auntie Adjoa", user=self.childrens_worker)
        response = self.client.post(
            reverse("staff_checkin_check_out", args=[check_in.id]), {"code": check_in.pickup_code}
        )
        self.assertRedirects(response, reverse("staff_checkin_dashboard"))
        check_in.refresh_from_db()
        self.assertFalse(check_in.is_checked_in)

    def test_check_out_with_wrong_code_shows_an_error_and_stays_checked_in(self):
        self.client.force_login(self.childrens_worker)
        check_in = check_in_child(self.child, guardian_name="Auntie Adjoa", user=self.childrens_worker)
        wrong_code = "0000" if check_in.pickup_code != "0000" else "1111"
        response = self.client.post(reverse("staff_checkin_check_out", args=[check_in.id]), {"code": wrong_code})
        self.assertEqual(response.status_code, 200)
        # The template auto-escapes the apostrophe (doesn&#x27;t), so check
        # for the HTML-escaped form rather than the literal straight quote.
        self.assertContains(response, escape("That pickup code doesn't match."))
        check_in.refresh_from_db()
        self.assertTrue(check_in.is_checked_in)

    def test_dashboard_lists_currently_checked_in_children(self):
        check_in_child(self.child, guardian_name="Auntie Adjoa", user=self.childrens_worker)
        self.client.force_login(self.childrens_worker)
        response = self.client.get(reverse("staff_checkin_dashboard"))
        self.assertContains(response, "Nana Boateng")

    def test_global_search_finds_children_for_childrens_worker_but_not_usher(self):
        self.client.force_login(self.childrens_worker)
        response = self.client.get(reverse("staff_search"), {"q": "boateng"})
        self.assertContains(response, "Nana Boateng")

        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_search"), {"q": "boateng"})
        self.assertNotContains(response, "Nana Boateng")


class StaffSundaySchoolTests(TestCase):
    """Sunday school classes/lessons - Children's Ministry and Pastors only, staff-managed, no leader self-service."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher-ss", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.childrens_worker = User.objects.create_user(username="cworker-ss", password="test-pass-123", is_staff=True)
        self.childrens_worker.groups.add(Group.objects.get(name="Children's Ministry"))
        self.household = Household.objects.create(name="The Boateng Family")
        self.child = Child.objects.create(household=self.household, first_name="Nana", last_name="Boateng")

    def test_usher_cannot_view_sunday_school(self):
        self.client.force_login(self.usher)
        self.assertRedirects(
            self.client.get(reverse("staff_sunday_school_class_list")), reverse("dashboard")
        )

    def test_childrens_worker_can_create_a_class(self):
        self.client.force_login(self.childrens_worker)
        response = self.client.post(
            reverse("staff_sunday_school_class_create"), {"name": "Toddlers", "description": "", "teacher": ""}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SundaySchoolClass.objects.filter(name="Toddlers").exists())

    def test_childrens_worker_can_add_a_child_to_the_roster(self):
        sunday_school_class = SundaySchoolClass.objects.create(name="Toddlers")
        self.client.force_login(self.childrens_worker)
        response = self.client.post(
            reverse("staff_sunday_school_class_add_child", args=[sunday_school_class.id]),
            {"child_id": self.child.id},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.child, sunday_school_class.children.all())

    def test_childrens_worker_can_remove_a_child_from_the_roster(self):
        sunday_school_class = SundaySchoolClass.objects.create(name="Toddlers")
        sunday_school_class.children.add(self.child)
        self.client.force_login(self.childrens_worker)
        response = self.client.post(
            reverse("staff_sunday_school_class_remove_child", args=[sunday_school_class.id, self.child.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(self.child, sunday_school_class.children.all())

    def test_childrens_worker_can_post_a_lesson(self):
        sunday_school_class = SundaySchoolClass.objects.create(name="Toddlers")
        self.client.force_login(self.childrens_worker)
        response = self.client.post(
            reverse("staff_sunday_school_class_detail", args=[sunday_school_class.id]),
            {"title": "Noah's Ark", "week_of": "2027-05-02", "scripture_reference": "Genesis 6-9", "content": "..."},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SundaySchoolLesson.objects.filter(sunday_school_class=sunday_school_class, title="Noah's Ark").exists())


class StaffFollowUpTests(TestCase):
    """
    New member follow-up - Ushers and Pastors get it (see setup_groups.py's
    _setup_ushers/_setup_pastors); Treasurers don't, same as everything else
    outside giving.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher16", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer16", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.pastor = User.objects.create_user(username="pastor16", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.visitor = Member.objects.create(first_name="Efua", last_name="Owusu")

    def test_treasurer_cannot_view_follow_ups(self):
        self.client.force_login(self.treasurer)
        self.assertRedirects(self.client.get(reverse("staff_followup_list")), reverse("dashboard"))

    def test_usher_can_start_a_follow_up_from_the_member_page(self):
        self.client.force_login(self.usher)
        response = self.client.post(reverse("staff_followup_start", args=[self.visitor.id]))
        self.assertEqual(response.status_code, 302)
        follow_up = FollowUp.objects.get(member=self.visitor)
        self.assertEqual(follow_up.stage, FollowUp.Stage.NEW)

    def test_starting_follow_up_twice_does_not_create_a_duplicate(self):
        self.client.force_login(self.usher)
        self.client.post(reverse("staff_followup_start", args=[self.visitor.id]))
        self.client.post(reverse("staff_followup_start", args=[self.visitor.id]))
        self.assertEqual(FollowUp.objects.filter(member=self.visitor).count(), 1)

    def test_usher_can_update_the_stage(self):
        follow_up = start_follow_up(self.visitor)
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_followup_update_stage", args=[follow_up.id]), {"stage": FollowUp.Stage.INVITED}
        )
        self.assertEqual(response.status_code, 302)
        follow_up.refresh_from_db()
        self.assertEqual(follow_up.stage, FollowUp.Stage.INVITED)

    def test_usher_can_log_a_contact_attempt(self):
        follow_up = start_follow_up(self.visitor)
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_followup_log_contact", args=[follow_up.id]), {"note": "Called to say hi."}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(follow_up.contact_attempts.count(), 1)
        self.assertEqual(follow_up.contact_attempts.first().note, "Called to say hi.")

    def test_follow_up_list_can_be_filtered_by_stage(self):
        new_visitor = Member.objects.create(first_name="Kojo", last_name="Mensah")
        start_follow_up(self.visitor)
        invited = start_follow_up(new_visitor)
        invited.stage = FollowUp.Stage.INVITED
        invited.save()

        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_followup_list"), {"stage": FollowUp.Stage.INVITED})
        self.assertContains(response, "Kojo Mensah")
        self.assertNotContains(response, "Efua Owusu")

    def test_follow_up_list_can_be_filtered_to_stale_only(self):
        stale_visitor = Member.objects.create(first_name="Kojo", last_name="Mensah")
        FollowUp.objects.create(
            member=stale_visitor, first_visit_date=timezone.localdate() - timezone.timedelta(days=30)
        )
        start_follow_up(self.visitor)  # first visit today - not stale

        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_followup_list"), {"stale": "1"})
        self.assertContains(response, "Kojo Mensah")
        self.assertNotContains(response, "Efua Owusu")

    def test_a_stale_follow_up_is_badged_when_browsing_by_stage(self):
        FollowUp.objects.create(
            member=self.visitor, first_visit_date=timezone.localdate() - timezone.timedelta(days=30)
        )
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_followup_list"), {"stage": FollowUp.Stage.NEW})
        self.assertContains(response, "Stale")

    def test_member_detail_offers_to_start_follow_up_when_not_already_following_up(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_detail", args=[self.visitor.id]))
        self.assertContains(response, "Start Follow-Up")

    def test_member_detail_shows_the_stage_once_follow_up_has_started(self):
        start_follow_up(self.visitor)
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_detail", args=[self.visitor.id]))
        self.assertContains(response, "New Visitor")

    def test_usher_can_now_add_a_new_member_for_follow_up(self):
        """
        Ushers gained add_member alongside this feature (see
        setup_groups.py) so they can enter a first-time visitor's details
        themselves before starting a follow-up.
        """
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_member_create"),
            {"first_name": "Yaw", "last_name": "Asare", "role": Member.Role.MEMBER, "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Member.objects.filter(first_name="Yaw", last_name="Asare").exists())


class StaffDecisionTests(TestCase):
    """
    Altar call decisions - same Usher/Pastor access as FollowUp above (see
    setup_groups.py's _setup_ushers/_setup_pastors); Treasurers get nothing.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher-dec", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer-dec", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.childrens_ministry = User.objects.create_user(
            username="cm-dec", password="test-pass-123", is_staff=True
        )
        self.childrens_ministry.groups.add(Group.objects.get(name="Children's Ministry"))
        self.member = Member.objects.create(first_name="Kwesi", last_name="Adjei")

    def test_treasurer_cannot_view_decisions(self):
        self.client.force_login(self.treasurer)
        self.assertRedirects(self.client.get(reverse("staff_decision_list")), reverse("dashboard"))

    def test_usher_can_record_a_decision(self):
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_decision_create"),
            {
                "member": self.member.id,
                "decision_type": Decision.DecisionType.SALVATION,
                "date": "2027-01-10",
                "event": "",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        decision = Decision.objects.get(member=self.member)
        self.assertEqual(decision.decision_type, Decision.DecisionType.SALVATION)

    def test_recording_a_salvation_decision_starts_a_follow_up(self):
        self.client.force_login(self.usher)
        self.client.post(
            reverse("staff_decision_create"),
            {
                "member": self.member.id,
                "decision_type": Decision.DecisionType.SALVATION,
                "date": "2027-01-10",
                "event": "",
                "notes": "",
            },
        )
        self.assertTrue(FollowUp.objects.filter(member=self.member).exists())

    def test_decision_list_can_be_filtered_by_type(self):
        Decision.objects.create(
            member=self.member, decision_type=Decision.DecisionType.SALVATION, date=timezone.localdate()
        )
        other_member = Member.objects.create(first_name="Ama", last_name="Boateng")
        Decision.objects.create(
            member=other_member, decision_type=Decision.DecisionType.REDEDICATION, date=timezone.localdate()
        )
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_decision_list"), {"type": Decision.DecisionType.REDEDICATION})
        self.assertContains(response, "Ama Boateng")
        self.assertNotContains(response, "Kwesi Adjei")

    def test_member_detail_shows_decisions_to_a_permitted_role_only(self):
        Decision.objects.create(
            member=self.member, decision_type=Decision.DecisionType.SALVATION, date=timezone.localdate()
        )
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertContains(response, "Altar Call Decisions")

        # Children's Ministry can view the member page itself (view_member)
        # but has no permission on Decision at all, so the card should be
        # absent rather than just empty.
        self.client.force_login(self.childrens_ministry)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Altar Call Decisions")


class StaffVisitorInfoEditTests(TestCase):
    """Pastor-only editing of the public "Plan Your Visit" page's content."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher17", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor17", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_usher_cannot_view_the_edit_form(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_visitor_info_edit")), reverse("dashboard"))

    def test_pastor_can_update_visitor_info(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_visitor_info_edit"),
            {
                "service_times": "Sundays at 9am and 11am",
                "address": "",
                "wifi_network": "NewlifeGuest",
                "wifi_password": "welcome123",
                "what_to_expect": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        info = VisitorInfo.get_current()
        self.assertEqual(info.service_times, "Sundays at 9am and 11am")
        self.assertEqual(info.wifi_network, "NewlifeGuest")

    def test_editing_twice_updates_the_same_row_not_a_new_one(self):
        self.client.force_login(self.pastor)
        self.client.post(reverse("staff_visitor_info_edit"), {"service_times": "Sundays at 9am"})
        self.client.post(reverse("staff_visitor_info_edit"), {"service_times": "Sundays at 10am"})
        self.assertEqual(VisitorInfo.objects.count(), 1)
        self.assertEqual(VisitorInfo.get_current().service_times, "Sundays at 10am")

    def test_pastor_can_set_the_homepage_welcome_video(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_visitor_info_edit"),
            {"welcome_video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            VisitorInfo.get_current().welcome_video_url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )


class StaffGroupAttendanceSummaryTests(TestCase):
    """The "Recent Meeting Attendance" card on a group's staff detail page."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor17", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.group = ChurchGroup.objects.create(name="Men's Fellowship")
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah")

    def test_shows_a_summary_line_per_meeting_date(self):
        Attendance.objects.create(member=self.member, date=timezone.localdate(), group=self.group, present=True)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_group_detail", args=[self.group.id]))
        self.assertContains(response, "1 of 1 present")

    def test_shows_an_empty_state_with_no_meeting_attendance_yet(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_group_detail", args=[self.group.id]))
        self.assertContains(response, "No meeting attendance recorded")


@override_settings(HUBTEL_CLIENT_ID="", HUBTEL_CLIENT_SECRET="", HUBTEL_SENDER_ID="")
class StaffAnnouncementTests(TestCase):
    """
    Bulk email/SMS announcements - Pastor-only (see setup_groups.py's
    PASTOR_MODELS), same as every other broad, church-wide capability.
    """

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher18", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer18", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.pastor = User.objects.create_user(username="pastor18", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.member = Member.objects.create(first_name="Ama", last_name="Owusu", email="ama@example.com")

    def client_login_and_get(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def test_usher_cannot_view_announcements(self):
        self.assertRedirects(
            self.client_login_and_get(self.usher, reverse("staff_announcement_list")), reverse("dashboard")
        )

    def test_treasurer_cannot_view_announcements(self):
        self.assertRedirects(
            self.client_login_and_get(self.treasurer, reverse("staff_announcement_list")), reverse("dashboard")
        )

    def test_pastor_can_draft_an_announcement(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_announcement_create"),
            {"subject": "Service moved", "body": "This Sunday moves to 9am.", "audience": Announcement.Audience.ALL},
        )
        self.assertEqual(response.status_code, 302)
        announcement = Announcement.objects.get(subject="Service moved")
        self.assertEqual(announcement.created_by, self.pastor)
        self.assertFalse(announcement.is_sent)

    def test_detail_page_previews_the_recipient_count_before_sending(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello", created_by=self.pastor)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_announcement_detail", args=[announcement.id]))
        self.assertContains(response, "1 active member")

    def test_pastor_can_send_an_announcement(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello", created_by=self.pastor)
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_announcement_send", args=[announcement.id]))
        self.assertEqual(response.status_code, 302)
        announcement.refresh_from_db()
        self.assertTrue(announcement.is_sent)
        self.assertEqual(announcement.email_sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_sent_announcement_cannot_be_edited(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello", created_by=self.pastor, sent_at=timezone.now())
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_announcement_edit", args=[announcement.id]))
        self.assertRedirects(response, reverse("staff_announcement_detail", args=[announcement.id]))

    def test_sending_twice_does_not_double_send(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello", created_by=self.pastor)
        self.client.force_login(self.pastor)
        self.client.post(reverse("staff_announcement_send", args=[announcement.id]))
        mail.outbox.clear()
        self.client.post(reverse("staff_announcement_send", args=[announcement.id]))
        self.assertEqual(len(mail.outbox), 0)

    def test_pastor_can_draft_and_send_to_the_lapsed_givers_segment(self):
        """
        The two reusable saved-segment audiences (Absentees, Lapsed
        Recurring Givers - see announcements/models.py's Audience choices)
        are drafted and sent exactly like any other audience; only who
        ends up in audience_queryset differs.
        """
        RecurringGiving.objects.create(
            member=self.member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=3,
        )
        other_member = Member.objects.create(first_name="Kofi", last_name="Addo", email="kofi@example.com")

        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_announcement_create"),
            {
                "subject": "We miss your giving",
                "body": "Just checking in.",
                "audience": Announcement.Audience.LAPSED_GIVERS,
            },
        )
        self.assertEqual(response.status_code, 302)
        announcement = Announcement.objects.get(subject="We miss your giving")

        self.client.post(reverse("staff_announcement_send", args=[announcement.id]))
        announcement.refresh_from_db()
        self.assertTrue(announcement.is_sent)
        self.assertEqual(announcement.email_sent_count, 1)
        self.assertEqual(mail.outbox[0].to, ["ama@example.com"])
        self.assertNotIn("kofi@example.com", mail.outbox[0].to)

    def test_delivery_report_lists_every_member_and_channel(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello", created_by=self.pastor)
        self.client.force_login(self.pastor)
        self.client.post(reverse("staff_announcement_send", args=[announcement.id]))

        response = self.client.get(reverse("staff_announcement_delivery_report", args=[announcement.id]))
        self.assertContains(response, "Ama Owusu")
        self.assertContains(response, "Email")
        self.assertContains(response, "Sent")

    def test_delivery_report_can_be_filtered_by_status(self):
        # self.member (Ama) has no phone number, so she'd otherwise still
        # show up here via her own skipped SMS row - give her one so she's
        # fully reachable and this filter's exclusion is actually meaningful.
        self.member.phone = "0244000000"
        self.member.save()
        no_contact = Member.objects.create(first_name="Kojo", last_name="Mensah")
        announcement = Announcement.objects.create(subject="Hi", body="Hello", created_by=self.pastor)
        self.client.force_login(self.pastor)
        self.client.post(reverse("staff_announcement_send", args=[announcement.id]))

        response = self.client.get(
            reverse("staff_announcement_delivery_report", args=[announcement.id]),
            {"status": "skipped_no_contact"},
        )
        self.assertContains(response, "Kojo Mensah")
        self.assertNotContains(response, "Ama Owusu")

    def test_usher_cannot_view_the_delivery_report(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello", created_by=self.pastor, sent_at=timezone.now())
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_announcement_delivery_report", args=[announcement.id]))
        self.assertEqual(response.status_code, 302)


class StaffSermonSeriesManagementTests(TestCase):
    """Sermon series CRUD in the staff area - Pastors only, per setup_groups."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher4", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.pastor = User.objects.create_user(username="pastor4", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

    def test_usher_cannot_view_the_series_list(self):
        self.client.force_login(self.usher)
        self.assertRedirects(self.client.get(reverse("staff_series_list")), reverse("dashboard"))

    def test_pastor_can_view_the_series_list(self):
        SermonSeries.objects.create(name="Rooted")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_series_list"))
        self.assertContains(response, "Rooted")

    def test_series_list_shows_the_sermon_count(self):
        series = SermonSeries.objects.create(name="Rooted")
        Sermon.objects.create(title="Week 1", date=timezone.localdate(), series=series)
        Sermon.objects.create(title="Week 2", date=timezone.localdate(), series=series)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_series_list"))
        self.assertContains(response, "2 sermon(s)")

    def test_pastor_can_create_a_series(self):
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_series_create"), {"name": "Overflow", "description": "A study on generosity."})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SermonSeries.objects.filter(name="Overflow").exists())

    def test_usher_cannot_create_a_series(self):
        self.client.force_login(self.usher)
        response = self.client.post(reverse("staff_series_create"), {"name": "Overflow", "description": ""})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SermonSeries.objects.filter(name="Overflow").exists())

    def test_pastor_can_edit_a_series(self):
        series = SermonSeries.objects.create(name="Rooted")
        self.client.force_login(self.pastor)
        self.client.post(reverse("staff_series_edit", args=[series.id]), {"name": "Rooted Deeper", "description": ""})
        series.refresh_from_db()
        self.assertEqual(series.name, "Rooted Deeper")

    def test_pastor_can_assign_a_series_and_tags_when_posting_a_sermon(self):
        series = SermonSeries.objects.create(name="Rooted")
        self.client.force_login(self.pastor)
        self.client.post(
            reverse("staff_sermon_create"),
            {
                "title": "Week 1",
                "speaker": "",
                "date": "2027-02-01",
                "scripture_reference": "",
                "series": series.id,
                "media_url": "",
                "notes": "",
                "tags_input": "Faith, Family",
            },
        )
        sermon = Sermon.objects.get(title="Week 1")
        self.assertEqual(sermon.series, series)
        self.assertEqual(sorted(sermon.tags.values_list("name", flat=True)), ["Faith", "Family"])


class StaffAnnualGivingStatementTests(TestCase):
    """A Treasurer/Pastor pulling any member's year-end statement (staff/views.py's annual_giving_statement)."""

    def setUp(self):
        call_command("setup_groups")
        self.treasurer = User.objects.create_user(username="treasurer11", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.usher = User.objects.create_user(username="usher11", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Adjoa", last_name="Frimpong")

    def test_usher_cannot_view_a_statement(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_annual_giving_statement", args=[self.member.id]))
        self.assertEqual(response.status_code, 302)

    def test_treasurer_sees_only_completed_gifts_within_the_chosen_year(self):
        Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        Donation.objects.create(member=self.member, amount="50.00", status=Donation.Status.PENDING)
        self.client.force_login(self.treasurer)
        response = self.client.get(
            reverse("staff_annual_giving_statement", args=[self.member.id]), {"year": timezone.now().year}
        )
        self.assertContains(response, "Adjoa Frimpong")
        self.assertContains(response, "100.00")
        self.assertNotContains(response, "50.00")

    def test_a_different_year_shows_no_gifts_from_this_year(self):
        Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        self.client.force_login(self.treasurer)
        other_year = timezone.now().year - 1
        response = self.client.get(
            reverse("staff_annual_giving_statement", args=[self.member.id]), {"year": other_year}
        )
        self.assertNotContains(response, "100.00")


class StaffGroupServingScheduleDisplayTests(TestCase):
    """A group's upcoming serving schedule shown read-only on its staff detail page."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor11", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher12", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.group = ChurchGroup.objects.create(name="Worship Team")
        self.member = Member.objects.create(first_name="Ama", last_name="Serwaa")

    def test_pastor_sees_upcoming_serving_assignments(self):
        ServingAssignment.objects.create(
            group=self.group, member=self.member, role="Vocals", date=timezone.localdate() + timezone.timedelta(days=2)
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_group_detail", args=[self.group.id]))
        self.assertContains(response, "Vocals")

    def test_usher_does_not_see_the_serving_section(self):
        # Ushers don't have members.view_group at all (Groups are
        # Pastor-only - see PASTOR_MODELS), so they're redirected away from
        # the page entirely rather than seeing it with the section hidden -
        # assertNotContains assumes a 200 response, so check the redirect
        # directly instead.
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_group_detail", args=[self.group.id]))
        self.assertEqual(response.status_code, 302)


class StaffPathwayStepManagementTests(TestCase):
    """Pathway step definitions - Pastor-only, per setup_groups."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor12", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher13", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))

    def test_usher_cannot_view_the_step_list(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_pathway_step_list"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_create_a_step(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_pathway_step_create"), {"name": "Water Baptism", "order": 1, "description": ""}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PathwayStep.objects.filter(name="Water Baptism").exists())

    def test_usher_cannot_create_a_step(self):
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_pathway_step_create"), {"name": "Water Baptism", "order": 1, "description": ""}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PathwayStep.objects.filter(name="Water Baptism").exists())

    def test_pastor_can_edit_a_step(self):
        step = PathwayStep.objects.create(name="Water Baptism", order=1)
        self.client.force_login(self.pastor)
        self.client.post(
            reverse("staff_pathway_step_edit", args=[step.id]),
            {"name": "Water Baptism Class", "order": 1, "description": ""},
        )
        step.refresh_from_db()
        self.assertEqual(step.name, "Water Baptism Class")


class StaffMarkPathwayStepTests(TestCase):
    """Ushers and Pastors marking a member's pathway progress from their detail page."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor13", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher14", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer12", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        self.step = PathwayStep.objects.create(name="Water Baptism", order=1)

    def test_usher_can_mark_a_step_complete(self):
        self.client.force_login(self.usher)
        self.client.post(reverse("staff_mark_pathway_step", args=[self.member.id, self.step.id]))
        progress = MemberPathwayProgress.objects.get(member=self.member, step=self.step)
        self.assertTrue(progress.is_completed)
        self.assertEqual(progress.marked_by, self.usher)

    def test_treasurer_cannot_mark_a_step(self):
        self.client.force_login(self.treasurer)
        response = self.client.post(reverse("staff_mark_pathway_step", args=[self.member.id, self.step.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MemberPathwayProgress.objects.filter(member=self.member, step=self.step).exists())

    def test_marking_incomplete_clears_the_completed_date(self):
        MemberPathwayProgress.objects.create(member=self.member, step=self.step, completed_date=timezone.localdate())
        self.client.force_login(self.pastor)
        self.client.post(
            reverse("staff_mark_pathway_step", args=[self.member.id, self.step.id]), {"action": "incomplete"}
        )
        progress = MemberPathwayProgress.objects.get(member=self.member, step=self.step)
        self.assertFalse(progress.is_completed)

    def test_member_detail_page_shows_the_pathway_section(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertContains(response, "Water Baptism")
        self.assertContains(response, "Not yet completed")


# --- Room/resource booking ---------------------------------------------------


class StaffResourceBookingTests(TestCase):
    """Pastors manage resources and bookings (see PASTOR_MODELS); Ushers/Treasurers don't."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-book", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-book", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.resource = Resource.objects.create(name="Conference Room")

    def test_usher_cannot_view_resources(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_resource_list"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_create_a_resource(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_resource_create"),
            {"name": "Church Van", "resource_type": "vehicle", "notes": "", "is_active": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Resource.objects.filter(name="Church Van").exists())

    def test_pastor_can_book_a_resource(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_booking_create"),
            {
                "resource": self.resource.id,
                "title": "Deacons Meeting",
                "event": "",
                "start_datetime": "2027-05-01T09:00",
                "end_datetime": "2027-05-01T11:00",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ResourceBooking.objects.filter(title="Deacons Meeting").exists())

    def test_overlapping_booking_is_rejected(self):
        ResourceBooking.objects.create(
            resource=self.resource,
            title="Existing Meeting",
            start_datetime=timezone.make_aware(timezone.datetime(2027, 5, 1, 9, 0)),
            end_datetime=timezone.make_aware(timezone.datetime(2027, 5, 1, 11, 0)),
        )
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_booking_create"),
            {
                "resource": self.resource.id,
                "title": "Conflicting Meeting",
                "event": "",
                "start_datetime": "2027-05-01T10:00",
                "end_datetime": "2027-05-01T12:00",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ResourceBooking.objects.filter(title="Conflicting Meeting").exists())
        self.assertContains(response, "already booked")

    def test_editing_a_booking_without_changing_its_time_does_not_conflict_with_itself(self):
        booking = ResourceBooking.objects.create(
            resource=self.resource,
            title="Deacons Meeting",
            start_datetime=timezone.make_aware(timezone.datetime(2027, 5, 1, 9, 0)),
            end_datetime=timezone.make_aware(timezone.datetime(2027, 5, 1, 11, 0)),
        )
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_booking_edit", args=[booking.id]),
            {
                "resource": self.resource.id,
                "title": "Deacons Meeting (updated)",
                "event": "",
                "start_datetime": "2027-05-01T09:00",
                "end_datetime": "2027-05-01T11:00",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.title, "Deacons Meeting (updated)")

    def test_event_detail_shows_resource_bookings_to_a_pastor_only(self):
        event = Event.objects.create(title="Christmas Program", start_datetime=timezone.now())
        ResourceBooking.objects.create(
            resource=self.resource,
            title="Christmas Program",
            event=event,
            start_datetime=timezone.now(),
            end_datetime=timezone.now() + timezone.timedelta(hours=2),
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_event_detail", args=[event.id]))
        self.assertContains(response, "Resource Bookings")
        self.assertContains(response, "Conference Room")

        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_event_detail", args=[event.id]))
        self.assertNotContains(response, "Resource Bookings")


class StaffBookingCalendarTests(TestCase):
    """
    The week-at-a-glance facility calendar (see staff/views.py's
    booking_calendar) - gated on the same booking.view_resourcebooking
    permission as the plain list, since it's just another view of the same
    data.
    """

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-cal", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-cal", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.room = Resource.objects.create(name="Conference Room")
        self.van = Resource.objects.create(name="Church Van", resource_type=Resource.ResourceType.VEHICLE)

    def test_usher_cannot_view_the_calendar(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_booking_calendar"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_sees_every_active_resource_as_a_row(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_booking_calendar"))
        self.assertContains(response, "Conference Room")
        self.assertContains(response, "Church Van")

    def test_inactive_resource_is_not_shown(self):
        Resource.objects.create(name="Retired Projector", is_active=False)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_booking_calendar"))
        self.assertNotContains(response, "Retired Projector")

    def test_a_booking_appears_on_the_correct_day_of_its_week(self):
        # 2027-05-03 is a Monday - anchoring the request to that same week
        # keeps this test stable regardless of which "today" it happens to
        # run on.
        ResourceBooking.objects.create(
            resource=self.room,
            title="Deacons Meeting",
            start_datetime=timezone.make_aware(timezone.datetime(2027, 5, 5, 9, 0)),
            end_datetime=timezone.make_aware(timezone.datetime(2027, 5, 5, 11, 0)),
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_booking_calendar"), {"week": "2027-05-03"})
        self.assertContains(response, "Deacons Meeting")

    def test_a_booking_outside_the_selected_week_does_not_appear(self):
        ResourceBooking.objects.create(
            resource=self.room,
            title="Next Month's Meeting",
            start_datetime=timezone.make_aware(timezone.datetime(2027, 6, 1, 9, 0)),
            end_datetime=timezone.make_aware(timezone.datetime(2027, 6, 1, 11, 0)),
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_booking_calendar"), {"week": "2027-05-03"})
        self.assertNotContains(response, "Next Month's Meeting")

    def test_a_multi_day_booking_appears_on_every_day_it_spans(self):
        ResourceBooking.objects.create(
            resource=self.van,
            title="Youth Retreat",
            start_datetime=timezone.make_aware(timezone.datetime(2027, 5, 7, 8, 0)),
            end_datetime=timezone.make_aware(timezone.datetime(2027, 5, 9, 18, 0)),
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_booking_calendar"), {"week": "2027-05-03"})
        content = response.content.decode()
        self.assertEqual(content.count("Youth Retreat"), 3)

    def test_previous_and_next_week_links_are_seven_days_apart(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_booking_calendar"), {"week": "2027-05-03"})
        self.assertContains(response, "week=2027-04-26")
        self.assertContains(response, "week=2027-05-10")

    def test_an_invalid_week_parameter_falls_back_to_the_current_week(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_booking_calendar"), {"week": "not-a-date"})
        self.assertEqual(response.status_code, 200)


# --- Pastoral care requests ---------------------------------------------------


class StaffCareRequestTests(TestCase):
    """CareRequest is Pastor-only - the one model no other role gets any permission on."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-care", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-care", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer-care", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu")
        self.care_request = CareRequest.objects.create(member=self.member, details="Please visit.")

    def test_usher_cannot_view_the_care_request_list(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_care_request_list"))
        self.assertEqual(response.status_code, 302)

    def test_treasurer_cannot_view_the_care_request_list(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_care_request_list"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_view_the_care_request_list(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_care_request_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Efua")

    def test_pastor_can_update_status_and_notes(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_care_request_detail", args=[self.care_request.id]),
            {
                "status": "scheduled",
                "assigned_pastor": self.pastor.id,
                "scheduled_date": "2027-05-01",
                "pastor_notes": "Visiting Saturday.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.care_request.refresh_from_db()
        self.assertEqual(self.care_request.status, "scheduled")
        self.assertEqual(self.care_request.assigned_pastor, self.pastor)

    def test_member_detail_shows_care_requests_to_a_pastor_only(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertContains(response, "Pastoral Care Requests")

        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertNotContains(response, "Pastoral Care Requests")


class StaffSuggestionTests(TestCase):
    """Suggestion is Pastor-only, same reasoning as CareRequest above."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-sugg2", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-sugg", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.suggestion = Suggestion.objects.create(message="Please add more parking.")

    def test_usher_cannot_view_the_suggestion_list(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_suggestion_list"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_view_the_suggestion_list(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_suggestion_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please add more parking.")

    def test_pastor_can_mark_a_suggestion_reviewed(self):
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_suggestion_mark_reviewed", args=[self.suggestion.id]))
        self.assertEqual(response.status_code, 302)
        self.suggestion.refresh_from_db()
        self.assertTrue(self.suggestion.is_reviewed)

    def test_usher_cannot_mark_a_suggestion_reviewed(self):
        self.client.force_login(self.usher)
        response = self.client.post(reverse("staff_suggestion_mark_reviewed", args=[self.suggestion.id]))
        self.assertEqual(response.status_code, 302)
        self.suggestion.refresh_from_db()
        self.assertFalse(self.suggestion.is_reviewed)

    def test_filtering_by_pending_and_reviewed(self):
        reviewed = Suggestion.objects.create(message="Add a bookstore.", is_reviewed=True)
        self.client.force_login(self.pastor)

        response = self.client.get(reverse("staff_suggestion_list"), {"show": "pending"})
        self.assertContains(response, "Please add more parking.")
        self.assertNotContains(response, "Add a bookstore.")

        response = self.client.get(reverse("staff_suggestion_list"), {"show": "reviewed"})
        self.assertContains(response, "Add a bookstore.")
        self.assertNotContains(response, "Please add more parking.")


class StaffTestimonyTests(TestCase):
    """Testimony is Pastor-only, same reasoning as Suggestion above."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-testi", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-testi", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Yaa", last_name="Darko")
        self.testimony = Testimony.objects.create(member=self.member, testimony_text="God healed my mother.")

    def test_usher_cannot_view_the_testimony_list(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_testimony_list"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_view_the_testimony_list(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_testimony_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "God healed my mother.")

    def test_pastor_can_approve_a_testimony(self):
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_testimony_approve", args=[self.testimony.id]))
        self.assertEqual(response.status_code, 302)
        self.testimony.refresh_from_db()
        self.assertTrue(self.testimony.is_approved)

    def test_usher_cannot_approve_a_testimony(self):
        self.client.force_login(self.usher)
        response = self.client.post(reverse("staff_testimony_approve", args=[self.testimony.id]))
        self.assertEqual(response.status_code, 302)
        self.testimony.refresh_from_db()
        self.assertFalse(self.testimony.is_approved)

    def test_filtering_by_pending_and_approved(self):
        approved = Testimony.objects.create(
            member=self.member, testimony_text="Got a new job.", is_approved=True
        )
        self.client.force_login(self.pastor)

        response = self.client.get(reverse("staff_testimony_list"), {"show": "pending"})
        self.assertContains(response, "God healed my mother.")
        self.assertNotContains(response, "Got a new job.")

        response = self.client.get(reverse("staff_testimony_list"), {"show": "approved"})
        self.assertContains(response, "Got a new job.")
        self.assertNotContains(response, "God healed my mother.")


class StaffMemberIdCardTests(TestCase):
    """Same view permission as member_detail itself - Ushers, Children's Ministry, and Pastors all get view_member."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher-idcard", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu")

    def test_login_required(self):
        response = self.client.get(reverse("staff_member_id_card", args=[self.member.id]))
        self.assertEqual(response.status_code, 302)

    def test_id_card_shows_the_members_name_and_role(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_id_card", args=[self.member.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Efua Owusu")
        self.assertContains(response, "Member since")

    def test_id_card_qr_code_is_a_png(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_id_card_qr", args=[self.member.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_id_card_link_shown_on_member_detail_page(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertContains(response, reverse("staff_member_id_card", args=[self.member.id]))


class StaffMembershipCertificateTests(TestCase):
    """Same view permission as member_detail/the ID card - Ushers, Children's Ministry, and Pastors all get view_member."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher-cert", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu")

    def test_login_required(self):
        response = self.client.get(reverse("staff_membership_certificate_pdf", args=[self.member.id]))
        self.assertEqual(response.status_code, 302)

    def test_downloads_a_pdf(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_membership_certificate_pdf", args=[self.member.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("attachment", response["Content-Disposition"])

    def test_certificate_link_shown_on_member_detail_page(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertContains(response, reverse("staff_membership_certificate_pdf", args=[self.member.id]))


class StaffMemberNoteTests(TestCase):
    """
    MemberNote is Pastor-only, same reasoning as CareRequest above - private
    staff notes on a member's staff detail page (see
    staff/views.py's member_detail/member_note_create).
    """

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-note", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-note", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu")

    def test_member_detail_shows_staff_notes_to_a_pastor_only(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertContains(response, "Staff Notes")

        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertNotContains(response, "Staff Notes")

    def test_pastor_can_add_a_note(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_member_note_create", args=[self.member.id]),
            {"note": "Called to check in after surgery recovery - doing well."},
        )
        self.assertEqual(response.status_code, 302)
        note = MemberNote.objects.get(member=self.member)
        self.assertEqual(note.author, self.pastor)
        self.assertIn("Called to check in", note.note)

    def test_usher_cannot_add_a_note(self):
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_member_note_create", args=[self.member.id]),
            {"note": "Sneaky note"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MemberNote.objects.filter(member=self.member).exists())

    def test_notes_show_up_on_the_member_detail_page_newest_first(self):
        older = MemberNote.objects.create(member=self.member, author=self.pastor, note="First conversation.")
        newer = MemberNote.objects.create(member=self.member, author=self.pastor, note="Follow-up call.")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        content = response.content.decode()
        self.assertLess(content.index("Follow-up call."), content.index("First conversation."))


# --- Church-wide surveys/polls -----------------------------------------------


class StaffSurveyManagementTests(TestCase):
    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-survey", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-survey", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))

    def test_usher_cannot_view_surveys(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_survey_list"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_create_a_survey(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_survey_create"), {"title": "Service Times", "description": "", "is_open": "on"}
        )
        self.assertEqual(response.status_code, 302)
        survey = Survey.objects.get(title="Service Times")
        self.assertEqual(survey.created_by, self.pastor)

    def test_pastor_can_add_a_choice_question_and_a_choice(self):
        survey = Survey.objects.create(title="Service Times", created_by=self.pastor)
        self.client.force_login(self.pastor)
        self.client.post(
            reverse("staff_survey_question_add", args=[survey.id]),
            {"text": "Preferred time?", "question_type": "choice", "order": 1},
        )
        question = SurveyQuestion.objects.get(survey=survey)
        self.client.post(reverse("staff_survey_choice_add", args=[survey.id, question.id]), {"text": "8am", "order": 1})
        self.assertTrue(SurveyChoice.objects.filter(question=question, text="8am").exists())

    def test_survey_detail_shows_response_count_and_results(self):
        survey = Survey.objects.create(title="Feedback")
        question = SurveyQuestion.objects.create(survey=survey, text="Anything else?")
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        response = SurveyResponse.objects.create(survey=survey, member=member)
        SurveyAnswer.objects.create(response=response, question=question, text_answer="Great service!")

        self.client.force_login(self.pastor)
        page = self.client.get(reverse("staff_survey_detail", args=[survey.id]))
        self.assertContains(page, "1 response")
        self.assertContains(page, "Great service!")


# --- Baby dedication & wedding records ---------------------------------------


class StaffMilestonesTests(TestCase):
    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-mile", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-mile", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.spouse_one = Member.objects.create(first_name="Kojo", last_name="Mensah")
        self.spouse_two = Member.objects.create(first_name="Ama", last_name="Boateng")

    def test_usher_cannot_view_dedications_or_weddings(self):
        self.client.force_login(self.usher)
        self.assertEqual(self.client.get(reverse("staff_dedication_list")).status_code, 302)
        self.assertEqual(self.client.get(reverse("staff_wedding_list")).status_code, 302)

    def test_pastor_can_record_a_dedication(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_dedication_create"),
            {
                "child_name": "Baby Mensah",
                "parents": [self.spouse_one.id],
                "dedication_date": "2027-05-01",
                "officiated_by": "Pastor John",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        dedication = BabyDedication.objects.get(child_name="Baby Mensah")
        self.assertIn(self.spouse_one, dedication.parents.all())

    def test_pastor_can_record_a_wedding(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_wedding_create"),
            {
                "spouse_one": self.spouse_one.id,
                "spouse_two": self.spouse_two.id,
                "wedding_date": "2027-05-01",
                "officiated_by": "Pastor John",
                "location": "Main Sanctuary",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(WeddingRecord.objects.filter(spouse_one=self.spouse_one, spouse_two=self.spouse_two).exists())

    def test_wedding_cannot_have_the_same_member_as_both_spouses(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_wedding_create"),
            {
                "spouse_one": self.spouse_one.id,
                "spouse_two": self.spouse_one.id,
                "wedding_date": "2027-05-01",
                "officiated_by": "",
                "location": "",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(WeddingRecord.objects.filter(spouse_one=self.spouse_one, spouse_two=self.spouse_one).exists())

    def test_dedication_certificate_page_renders(self):
        dedication = BabyDedication.objects.create(child_name="Baby Mensah", dedication_date="2027-05-01")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_dedication_certificate", args=[dedication.id]))
        self.assertContains(response, "Baby Mensah")

    def test_wedding_certificate_page_renders(self):
        wedding = WeddingRecord.objects.create(
            spouse_one=self.spouse_one, spouse_two=self.spouse_two, wedding_date="2027-05-01"
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_wedding_certificate", args=[wedding.id]))
        self.assertContains(response, "Kojo Mensah")
        self.assertContains(response, "Ama Boateng")

    def test_member_detail_shows_milestones(self):
        WeddingRecord.objects.create(spouse_one=self.spouse_one, spouse_two=self.spouse_two, wedding_date="2027-05-01")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_detail", args=[self.spouse_one.id]))
        self.assertContains(response, "Milestones")
        self.assertContains(response, "Ama Boateng")


class StaffBaptismRecordTests(TestCase):
    """Third milestone type, same Pastor-only pattern as dedications/weddings above - unlike funerals, a member can have more than one record."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-bap", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-bap", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Kwesi", last_name="Adjei")

    def test_usher_cannot_view_baptisms(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_baptism_list"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_record_a_baptism(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_baptism_create"),
            {
                "member": self.member.id,
                "baptism_date": "2027-05-01",
                "officiated_by": "Pastor John",
                "location": "Main Sanctuary baptistry",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BaptismRecord.objects.filter(member=self.member).exists())

    def test_a_member_can_have_two_baptism_records(self):
        BaptismRecord.objects.create(member=self.member, baptism_date="2015-05-01")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_baptism_create"),
            {"member": self.member.id, "baptism_date": "2027-05-01", "officiated_by": "", "location": "", "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BaptismRecord.objects.filter(member=self.member).count(), 2)

    def test_pastor_can_edit_a_baptism_record(self):
        baptism = BaptismRecord.objects.create(member=self.member, baptism_date="2027-05-01")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_baptism_edit", args=[baptism.id]),
            {
                "member": self.member.id,
                "baptism_date": "2027-05-01",
                "officiated_by": "Pastor Jane",
                "location": "",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        baptism.refresh_from_db()
        self.assertEqual(baptism.officiated_by, "Pastor Jane")

    def test_baptism_certificate_page_renders(self):
        baptism = BaptismRecord.objects.create(member=self.member, baptism_date="2027-05-01")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_baptism_certificate", args=[baptism.id]))
        self.assertContains(response, "Kwesi Adjei")

    def test_member_detail_shows_baptisms_to_a_pastor_not_an_usher(self):
        BaptismRecord.objects.create(member=self.member, baptism_date="2027-05-01")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertContains(response, "Baptism")

        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertNotContains(response, "Baptism")


class StaffTransferLetterTests(TestCase):
    """Fifth milestone type, same Pastor-only pattern as the other four - a member can have more than one letter."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-transfer", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-transfer", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Abena", last_name="Owusu")

    def test_usher_cannot_view_transfer_letters(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_transfer_letter_list"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_issue_a_transfer_letter(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_transfer_letter_create"),
            {
                "member": self.member.id,
                "destination_church": "Grace AG",
                "destination_location": "Kumasi",
                "transfer_date": "2027-05-01",
                "issued_by": "Pastor John",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TransferLetter.objects.filter(member=self.member, destination_church="Grace AG").exists())

    def test_a_member_can_have_two_transfer_letters(self):
        TransferLetter.objects.create(member=self.member, destination_church="Grace AG", transfer_date="2015-05-01")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_transfer_letter_create"),
            {
                "member": self.member.id,
                "destination_church": "Newlife AG",
                "destination_location": "",
                "transfer_date": "2027-05-01",
                "issued_by": "",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TransferLetter.objects.filter(member=self.member).count(), 2)

    def test_pastor_can_edit_a_transfer_letter(self):
        letter = TransferLetter.objects.create(
            member=self.member, destination_church="Grace AG", transfer_date="2027-05-01"
        )
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_transfer_letter_edit", args=[letter.id]),
            {
                "member": self.member.id,
                "destination_church": "Grace AG",
                "destination_location": "Kumasi",
                "transfer_date": "2027-05-01",
                "issued_by": "Pastor Jane",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        letter.refresh_from_db()
        self.assertEqual(letter.issued_by, "Pastor Jane")

    def test_transfer_letter_view_page_renders(self):
        letter = TransferLetter.objects.create(
            member=self.member, destination_church="Grace AG", transfer_date="2027-05-01"
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_transfer_letter_view", args=[letter.id]))
        self.assertContains(response, "Abena Owusu")
        self.assertContains(response, "Grace AG")

    def test_member_detail_shows_transfer_letters_to_a_pastor_not_an_usher(self):
        TransferLetter.objects.create(member=self.member, destination_church="Grace AG", transfer_date="2027-05-01")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertContains(response, "Grace AG")

        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertNotContains(response, "Grace AG")


class StaffFuneralRecordTests(TestCase):
    """Third milestone type, same Pastor-only pattern as dedications/weddings above."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-fun", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-fun", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Kwame", last_name="Asante")
        self.family_member = Member.objects.create(first_name="Ama", last_name="Asante")

    def test_usher_cannot_view_funerals(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_funeral_list"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_record_a_funeral(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_funeral_create"),
            {
                "member": self.member.id,
                "date_of_death": "2027-04-20",
                "service_date": "2027-05-01",
                "officiated_by": "Pastor John",
                "location": "Main Sanctuary",
                "family_contacts": [self.family_member.id],
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        funeral = FuneralRecord.objects.get(member=self.member)
        self.assertIn(self.family_member, funeral.family_contacts.all())

    def test_a_member_cannot_have_two_funeral_records(self):
        FuneralRecord.objects.create(member=self.member, service_date="2027-05-01")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_funeral_create"),
            {
                "member": self.member.id,
                "date_of_death": "",
                "service_date": "2027-06-01",
                "officiated_by": "",
                "location": "",
                "family_contacts": [],
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FuneralRecord.objects.filter(member=self.member).count(), 1)

    def test_pastor_can_edit_a_funeral_record(self):
        funeral = FuneralRecord.objects.create(member=self.member, service_date="2027-05-01")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_funeral_edit", args=[funeral.id]),
            {
                "member": self.member.id,
                "date_of_death": "",
                "service_date": "2027-05-01",
                "officiated_by": "Pastor Jane",
                "location": "",
                "family_contacts": [],
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        funeral.refresh_from_db()
        self.assertEqual(funeral.officiated_by, "Pastor Jane")

    def test_funeral_program_page_renders(self):
        funeral = FuneralRecord.objects.create(member=self.member, service_date="2027-05-01")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_funeral_program", args=[funeral.id]))
        self.assertContains(response, "Kwame Asante")

    def test_member_detail_shows_the_funeral_record_to_a_pastor_not_an_usher(self):
        funeral = FuneralRecord.objects.create(member=self.member, service_date="2027-05-01")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertContains(response, "Funeral service")

        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_member_detail", args=[self.member.id]))
        self.assertNotContains(response, "Funeral service")


# --- Volunteer background checks ---------------------------------------------


class StaffBackgroundCheckTests(TestCase):
    """Pastors get full access; Children's Ministry gets view-only; Ushers get nothing."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-screen", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.cm_worker = User.objects.create_user(username="cm-screen", password="test-pass-123", is_staff=True)
        self.cm_worker.groups.add(Group.objects.get(name="Children's Ministry"))
        self.usher = User.objects.create_user(username="usher-screen", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Yaw", last_name="Owusu")

    def test_usher_cannot_view_background_checks(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_background_check_list"))
        self.assertEqual(response.status_code, 302)

    def test_childrens_ministry_can_view_but_not_add(self):
        self.client.force_login(self.cm_worker)
        response = self.client.get(reverse("staff_background_check_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse("staff_background_check_create")).status_code, 302)

    def test_pastor_can_create_a_background_check(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_background_check_create"),
            {"member": self.member.id, "status": "pending", "submitted_date": "2027-05-01", "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BackgroundCheck.objects.filter(member=self.member, status="pending").exists())

    def test_pastor_can_clear_a_check(self):
        check = BackgroundCheck.objects.create(member=self.member)
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_background_check_edit", args=[check.id]),
            {
                "member": self.member.id,
                "status": "cleared",
                "submitted_date": "",
                "cleared_date": "2027-05-01",
                "expiry_date": "2029-05-01",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        check.refresh_from_db()
        self.assertEqual(check.status, "cleared")

    def test_childrens_ministry_cannot_change_a_check(self):
        check = BackgroundCheck.objects.create(member=self.member)
        self.client.force_login(self.cm_worker)
        response = self.client.get(reverse("staff_background_check_edit", args=[check.id]))
        self.assertEqual(response.status_code, 302)

    def test_expiring_soon_filter(self):
        from datetime import timedelta

        from django.utils import timezone

        soon = BackgroundCheck.objects.create(
            member=self.member, status="cleared", expiry_date=timezone.localdate() + timedelta(days=5)
        )
        BackgroundCheck.objects.create(
            member=Member.objects.create(first_name="Ama", last_name="Danso"),
            status="cleared",
            expiry_date=timezone.localdate() + timedelta(days=300),
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_background_check_list"), {"show": "expiring"})
        self.assertContains(response, "Yaw")
        self.assertNotContains(response, "Ama Danso")

    def test_member_detail_shows_background_checks_to_pastor_and_childrens_ministry_not_ushers(self):
        BackgroundCheck.objects.create(member=self.member, status="cleared")
        self.client.force_login(self.pastor)
        self.assertContains(self.client.get(reverse("staff_member_detail", args=[self.member.id])), "Background Checks")

        self.client.force_login(self.cm_worker)
        self.assertContains(self.client.get(reverse("staff_member_detail", args=[self.member.id])), "Background Checks")

        self.client.force_login(self.usher)
        self.assertNotContains(
            self.client.get(reverse("staff_member_detail", args=[self.member.id])), "Background Checks"
        )


class StaffVolunteerTrainingTests(TestCase):
    """Same permission split as background checks: Pastors get full access; Children's Ministry gets view-only; Ushers get nothing."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-train", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.cm_worker = User.objects.create_user(username="cm-train", password="test-pass-123", is_staff=True)
        self.cm_worker.groups.add(Group.objects.get(name="Children's Ministry"))
        self.usher = User.objects.create_user(username="usher-train", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Yaw", last_name="Owusu")

    def test_usher_cannot_view_trainings(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_training_list"))
        self.assertEqual(response.status_code, 302)

    def test_childrens_ministry_can_view_but_not_add(self):
        self.client.force_login(self.cm_worker)
        response = self.client.get(reverse("staff_training_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse("staff_training_create")).status_code, 302)

    def test_pastor_can_create_a_training(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_training_create"),
            {"member": self.member.id, "training_name": "Child Safety", "status": "in_progress", "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            VolunteerTraining.objects.filter(member=self.member, training_name="Child Safety").exists()
        )

    def test_pastor_can_mark_a_training_completed(self):
        training = VolunteerTraining.objects.create(member=self.member, training_name="Child Safety")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_training_edit", args=[training.id]),
            {
                "member": self.member.id,
                "training_name": "Child Safety",
                "status": "completed",
                "completed_date": "2027-05-01",
                "expiry_date": "2029-05-01",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        training.refresh_from_db()
        self.assertEqual(training.status, "completed")

    def test_childrens_ministry_cannot_change_a_training(self):
        training = VolunteerTraining.objects.create(member=self.member, training_name="Child Safety")
        self.client.force_login(self.cm_worker)
        response = self.client.get(reverse("staff_training_edit", args=[training.id]))
        self.assertEqual(response.status_code, 302)

    def test_expiring_soon_filter(self):
        from datetime import timedelta

        from django.utils import timezone

        soon = VolunteerTraining.objects.create(
            member=self.member,
            training_name="First Aid",
            status="completed",
            expiry_date=timezone.localdate() + timedelta(days=5),
        )
        VolunteerTraining.objects.create(
            member=Member.objects.create(first_name="Ama", last_name="Danso"),
            training_name="First Aid",
            status="completed",
            expiry_date=timezone.localdate() + timedelta(days=300),
        )
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_training_list"), {"show": "expiring"})
        self.assertContains(response, "Yaw")
        self.assertNotContains(response, "Ama Danso")

    def test_member_detail_shows_trainings_to_pastor_and_childrens_ministry_not_ushers(self):
        VolunteerTraining.objects.create(member=self.member, training_name="Child Safety", status="completed")
        self.client.force_login(self.pastor)
        self.assertContains(self.client.get(reverse("staff_member_detail", args=[self.member.id])), "Trainings")

        self.client.force_login(self.cm_worker)
        self.assertContains(self.client.get(reverse("staff_member_detail", args=[self.member.id])), "Trainings")

        self.client.force_login(self.usher)
        self.assertNotContains(
            self.client.get(reverse("staff_member_detail", args=[self.member.id])), "Trainings"
        )


# --- Facility maintenance requests --------------------------------------------


class StaffMaintenanceTests(TestCase):
    """Ushers get view/add only; resolving a ticket is Pastor-only."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-maint", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-maint", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer-maint", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))

    def test_treasurer_cannot_view_maintenance_requests(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_maintenance_list"))
        self.assertEqual(response.status_code, 302)

    def test_usher_can_log_an_issue(self):
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_maintenance_create"),
            {"title": "Flickering light", "description": "Sanctuary, back row.", "location": "Main Sanctuary"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(MaintenanceRequest.objects.filter(title="Flickering light").exists())

    def test_usher_cannot_change_a_ticket_status(self):
        maintenance_request = MaintenanceRequest.objects.create(title="Flickering light")
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_maintenance_update_status", args=[maintenance_request.id]), {"status": "done"}
        )
        self.assertEqual(response.status_code, 302)
        maintenance_request.refresh_from_db()
        self.assertEqual(maintenance_request.status, MaintenanceRequest.Status.OPEN)

    def test_pastor_can_resolve_a_ticket(self):
        maintenance_request = MaintenanceRequest.objects.create(title="Flickering light")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_maintenance_update_status", args=[maintenance_request.id]),
            {"status": "done", "resolution_notes": "Bulb replaced."},
        )
        self.assertEqual(response.status_code, 302)
        maintenance_request.refresh_from_db()
        self.assertEqual(maintenance_request.status, MaintenanceRequest.Status.DONE)
        self.assertEqual(maintenance_request.resolution_notes, "Bulb replaced.")
        self.assertIsNotNone(maintenance_request.resolved_at)


class StaffEquipmentTests(TestCase):
    """
    Pastors manage the catalog (add/edit/retire); Ushers get view plus
    checkout/checkin but can't add or edit an item itself; Treasurers get
    nothing, same shape as StaffMaintenanceTests above.
    """

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-equip", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-equip", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer-equip", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        self.item = Equipment.objects.create(name="Shure SM58 Mic #3", category=Equipment.Category.SOUND)

    def test_treasurer_cannot_view_equipment(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_equipment_list"))
        self.assertEqual(response.status_code, 302)

    def test_usher_can_view_but_not_add_equipment(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_equipment_list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "+ Add Equipment")

        response = self.client.get(reverse("staff_equipment_create"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_add_equipment(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_equipment_create"),
            {
                "name": "Yamaha Keyboard",
                "category": "instrument",
                "condition": "good",
                "serial_number": "",
                "notes": "",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Equipment.objects.filter(name="Yamaha Keyboard").exists())

    def test_usher_can_check_out_an_item(self):
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_equipment_checkout", args=[self.item.id]),
            {"checked_out_to": self.member.id, "notes": "Sunday service"},
        )
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_checked_out)
        self.assertEqual(self.item.current_checkout.checked_out_to, self.member)

    def test_checking_out_an_item_writes_an_activity_log_entry(self):
        self.client.force_login(self.usher)
        self.client.post(
            reverse("staff_equipment_checkout", args=[self.item.id]),
            {"checked_out_to": self.member.id, "notes": "Sunday service"},
        )
        entry = LogEntry.objects.get()
        self.assertEqual(entry.user, self.usher)
        self.assertIn(str(self.item), entry.change_message)

    def test_cannot_check_out_an_already_checked_out_item(self):
        EquipmentCheckout.objects.create(equipment=self.item, checked_out_to=self.member)
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_equipment_checkout", args=[self.item.id]),
            {"checked_out_to": self.member.id, "notes": "Another event"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.item.checkouts.count(), 1)

    def test_usher_can_check_in_an_item(self):
        checkout = EquipmentCheckout.objects.create(equipment=self.item, checked_out_to=self.member)
        self.client.force_login(self.usher)
        response = self.client.post(reverse("staff_equipment_checkin", args=[checkout.id]))
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_checked_out)
        checkout.refresh_from_db()
        self.assertIsNotNone(checkout.checked_in_at)

    def test_checking_in_an_item_writes_an_activity_log_entry(self):
        checkout = EquipmentCheckout.objects.create(equipment=self.item, checked_out_to=self.member)
        self.client.force_login(self.usher)
        self.client.post(reverse("staff_equipment_checkin", args=[checkout.id]))
        entry = LogEntry.objects.get()
        self.assertEqual(entry.user, self.usher)
        self.assertIn(str(self.item), entry.change_message)


class StaffLibraryTests(TestCase):
    """
    Same split as StaffEquipmentTests above: Pastors manage the catalog,
    Ushers get view plus checkout/return but can't add or edit an item
    itself, Treasurers get nothing.
    """

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-lib", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-lib", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer-lib", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        self.item = LibraryItem.objects.create(title="Mere Christianity", category=LibraryItem.Category.BOOK)

    def test_treasurer_cannot_view_the_library(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_library_list"))
        self.assertEqual(response.status_code, 302)

    def test_usher_can_view_but_not_add_a_library_item(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_library_list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "+ Add Item")

        response = self.client.get(reverse("staff_library_item_create"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_add_a_library_item(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_library_item_create"),
            {
                "title": "The Case for Christ",
                "author": "Lee Strobel",
                "category": "book",
                "notes": "",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(LibraryItem.objects.filter(title="The Case for Christ").exists())

    def test_usher_can_check_out_an_item(self):
        self.client.force_login(self.usher)
        due_date = timezone.localdate() + timedelta(days=14)
        response = self.client.post(
            reverse("staff_library_checkout", args=[self.item.id]),
            {"borrower": self.member.id, "due_date": due_date.strftime("%Y-%m-%d"), "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_on_loan)
        self.assertEqual(self.item.current_loan.borrower, self.member)

    def test_checking_out_an_item_writes_an_activity_log_entry(self):
        self.client.force_login(self.usher)
        due_date = timezone.localdate() + timedelta(days=14)
        self.client.post(
            reverse("staff_library_checkout", args=[self.item.id]),
            {"borrower": self.member.id, "due_date": due_date.strftime("%Y-%m-%d"), "notes": ""},
        )
        entry = LogEntry.objects.get()
        self.assertEqual(entry.user, self.usher)
        self.assertIn(str(self.item), entry.change_message)

    def test_cannot_check_out_an_already_loaned_item(self):
        LibraryLoan.objects.create(
            item=self.item, borrower=self.member, due_date=timezone.localdate() + timedelta(days=14)
        )
        self.client.force_login(self.usher)
        response = self.client.post(
            reverse("staff_library_checkout", args=[self.item.id]),
            {"borrower": self.member.id, "due_date": timezone.localdate().strftime("%Y-%m-%d"), "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.item.loans.count(), 1)

    def test_usher_can_return_an_item(self):
        loan = LibraryLoan.objects.create(
            item=self.item, borrower=self.member, due_date=timezone.localdate() + timedelta(days=14)
        )
        self.client.force_login(self.usher)
        response = self.client.post(reverse("staff_library_return", args=[loan.id]))
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_on_loan)
        loan.refresh_from_db()
        self.assertIsNotNone(loan.returned_date)

    def test_returning_an_item_writes_an_activity_log_entry(self):
        loan = LibraryLoan.objects.create(
            item=self.item, borrower=self.member, due_date=timezone.localdate() + timedelta(days=14)
        )
        self.client.force_login(self.usher)
        self.client.post(reverse("staff_library_return", args=[loan.id]))
        entry = LogEntry.objects.get()
        self.assertEqual(entry.user, self.usher)
        self.assertIn(str(self.item), entry.change_message)


class StaffActivityLogTests(TestCase):
    """
    Gated on care.view_carerequest, same "only Pastors hold this" reasoning
    as full_backup_export - see staff/views.py's activity_log.
    """

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-log", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-log", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Ama", last_name="Serwaa")

    def test_usher_cannot_view_the_activity_log(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_activity_log"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_view_the_activity_log(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_activity_log"))
        self.assertEqual(response.status_code, 200)

    def test_shows_a_logged_action(self):
        start_follow_up(self.member, user=self.pastor)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_activity_log"))
        self.assertContains(response, "Ama Serwaa")


class StaffServiceHourTests(TestCase):
    """Pastors get full management; nobody else gets any permission on ServiceHourLog."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-hours", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-hours", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.member = Member.objects.create(first_name="Kwesi", last_name="Appiah")

    def test_usher_cannot_view_service_hours(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_service_hour_report"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_log_hours_for_a_member(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_service_hour_create"),
            {"member": self.member.id, "date": "2027-05-02", "hours": "4", "role": "Parking", "group": "", "event": "", "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ServiceHourLog.objects.filter(member=self.member, role="Parking").exists())

    def test_report_totals_hours_by_member(self):
        ServiceHourLog.objects.create(member=self.member, date="2027-05-02", hours="3", role="Usher")
        ServiceHourLog.objects.create(member=self.member, date="2027-05-09", hours="2", role="Usher")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_service_hour_report"), {"year": 2027})
        self.assertContains(response, "5.00")

    def test_pastor_can_edit_a_log(self):
        log = ServiceHourLog.objects.create(member=self.member, date="2027-05-02", hours="3", role="Usher")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_service_hour_edit", args=[log.id]),
            {"member": self.member.id, "date": "2027-05-02", "hours": "3.5", "role": "Usher", "group": "", "event": "", "notes": ""},
        )
        self.assertEqual(response.status_code, 302)
        log.refresh_from_db()
        self.assertEqual(str(log.hours), "3.50")

    def test_usher_cannot_download_a_certificate(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_service_hour_certificate_pdf", args=[self.member.id, 2027]))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_download_a_certificate(self):
        ServiceHourLog.objects.create(member=self.member, date="2027-05-02", hours="3", role="Usher")
        ServiceHourLog.objects.create(member=self.member, date="2027-05-09", hours="2", role="Usher")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_service_hour_certificate_pdf", args=[self.member.id, 2027]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertIn("attachment", response["Content-Disposition"])

    def test_certificate_link_shown_next_to_the_members_total(self):
        ServiceHourLog.objects.create(member=self.member, date="2027-05-02", hours="3", role="Usher")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_service_hour_report"), {"year": 2027})
        self.assertContains(
            response, reverse("staff_service_hour_certificate_pdf", args=[self.member.id, 2027])
        )


class StaffExpenseTests(TestCase):
    """Treasurers and Pastors manage expenses/budget categories; Ushers get nothing."""

    def setUp(self):
        call_command("setup_groups")
        self.treasurer = User.objects.create_user(username="treasurer-exp", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.usher = User.objects.create_user(username="usher-exp", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))

    def test_usher_cannot_view_expenses(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_expense_report"))
        self.assertEqual(response.status_code, 302)

    def test_treasurer_can_create_a_budget_category(self):
        self.client.force_login(self.treasurer)
        response = self.client.post(
            reverse("staff_budget_category_create"), {"name": "Utilities", "annual_budget": "1200"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BudgetCategory.objects.filter(name="Utilities").exists())

    def test_treasurer_can_log_an_expense(self):
        category = BudgetCategory.objects.create(name="Utilities")
        self.client.force_login(self.treasurer)
        response = self.client.post(
            reverse("staff_expense_create"),
            {"category": category.id, "amount": "150.00", "date": "2027-01-05", "paid_to": "ECG", "description": ""},
        )
        self.assertEqual(response.status_code, 302)
        expense = Expense.objects.get(paid_to="ECG")
        self.assertEqual(expense.recorded_by, self.treasurer)

    def test_report_shows_total_spent_for_the_year(self):
        Expense.objects.create(amount="200.00", date="2027-01-05", paid_to="ECG")
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_expense_report"), {"year": 2027})
        self.assertContains(response, "200.00")

    def test_treasurer_can_attach_a_receipt(self):
        receipt = SimpleUploadedFile("receipt.jpg", b"fake image bytes", content_type="image/jpeg")
        self.client.force_login(self.treasurer)
        response = self.client.post(
            reverse("staff_expense_create"),
            {
                "category": "",
                "amount": "150.00",
                "date": "2027-01-05",
                "paid_to": "ECG",
                "description": "",
                "receipt": receipt,
            },
        )
        self.assertEqual(response.status_code, 302)
        expense = Expense.objects.get(paid_to="ECG")
        self.assertTrue(expense.receipt)

    def test_receipt_over_5mb_is_rejected(self):
        oversized = SimpleUploadedFile("receipt.jpg", b"x" * (5 * 1024 * 1024 + 1), content_type="image/jpeg")
        self.client.force_login(self.treasurer)
        response = self.client.post(
            reverse("staff_expense_create"),
            {
                "category": "",
                "amount": "150.00",
                "date": "2027-01-05",
                "paid_to": "ECG",
                "description": "",
                "receipt": oversized,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Expense.objects.filter(paid_to="ECG").exists())

    def test_receipt_link_shown_in_the_log_when_attached(self):
        receipt = SimpleUploadedFile("receipt.jpg", b"fake image bytes", content_type="image/jpeg")
        expense = Expense.objects.create(amount="150.00", date="2027-01-05", paid_to="ECG", receipt=receipt)
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_expense_report"), {"year": 2027})
        self.assertContains(response, "View Receipt")
        expense.receipt.delete(save=False)


class BuildWeeklyDigestTests(TestCase):
    """Direct tests of the digest's underlying counts (staff/digest.py), independent of email sending."""

    def test_counts_a_member_who_joined_this_week(self):
        Member.objects.create(first_name="Kwesi", last_name="Amoah")  # date_joined defaults to today
        digest = build_weekly_digest()
        self.assertEqual(len(digest["new_members"]), 1)

    def test_does_not_count_a_member_who_joined_over_a_week_ago(self):
        member = Member.objects.create(first_name="Kwesi", last_name="Amoah")
        Member.objects.filter(pk=member.pk).update(date_joined=timezone.localdate() - timezone.timedelta(days=10))
        digest = build_weekly_digest()
        self.assertEqual(len(digest["new_members"]), 0)

    def test_counts_pending_donations_but_not_completed_ones(self):
        Donation.objects.create(amount="50.00", status=Donation.Status.PENDING)
        Donation.objects.create(amount="30.00", status=Donation.Status.COMPLETED)
        digest = build_weekly_digest()
        self.assertEqual(len(digest["pending_donations"]), 1)
        self.assertEqual(digest["pending_total"], 50)

    def test_counts_an_upcoming_slot_with_room_but_not_a_full_one(self):
        event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=3)
        )
        open_slot = VolunteerSlot.objects.create(event=event, role_needed="Usher", capacity=2)
        full_slot = VolunteerSlot.objects.create(event=event, role_needed="Media", capacity=1)
        member = Member.objects.create(first_name="Ama", last_name="Boateng")
        VolunteerSignup.objects.create(slot=full_slot, member=member)
        digest = build_weekly_digest()
        self.assertEqual(digest["volunteer_gaps"], [open_slot])

    def test_does_not_count_a_slot_more_than_two_weeks_out(self):
        far_event = Event.objects.create(
            title="Christmas Service", start_datetime=timezone.now() + timezone.timedelta(days=30)
        )
        VolunteerSlot.objects.create(event=far_event, role_needed="Usher", capacity=2)
        digest = build_weekly_digest()
        self.assertEqual(digest["volunteer_gaps"], [])

    def test_counts_an_open_prayer_request_but_not_a_prayed_for_one(self):
        member = Member.objects.create(first_name="Yaw", last_name="Mensah")
        PrayerRequest.objects.create(member=member, request_text="Please pray for my exams.")
        PrayerRequest.objects.create(
            member=member, request_text="Thank you!", prayed_for=True, prayed_for_at=timezone.now()
        )
        digest = build_weekly_digest()
        self.assertEqual(len(digest["open_prayer_requests"]), 1)

    def test_counts_a_member_who_has_gone_quiet(self):
        member = Member.objects.create(first_name="Efua", last_name="Danso")
        Member.objects.filter(pk=member.pk).update(date_joined=timezone.localdate() - timezone.timedelta(weeks=10))
        digest = build_weekly_digest()
        self.assertEqual([m for m, _ in digest["absentees"]], [member])

    def test_does_not_count_a_member_who_attended_recently(self):
        member = Member.objects.create(first_name="Efua", last_name="Danso")
        Member.objects.filter(pk=member.pk).update(date_joined=timezone.localdate() - timezone.timedelta(weeks=10))
        Attendance.objects.create(member=member, date=timezone.localdate(), present=True)
        digest = build_weekly_digest()
        self.assertEqual(digest["absentees"], [])

    def test_counts_a_lapsed_recurring_giver(self):
        member = Member.objects.create(first_name="Yaw", last_name="Osei")
        RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=2,
        )
        digest = build_weekly_digest()
        self.assertEqual(len(digest["lapsed_givers"]), 1)

    def test_does_not_count_a_recurring_giver_below_the_reminder_threshold(self):
        member = Member.objects.create(first_name="Yaw", last_name="Osei")
        RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=1,
        )
        digest = build_weekly_digest()
        self.assertEqual(digest["lapsed_givers"], [])

    def test_counts_a_follow_up_that_has_gone_quiet(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        follow_up = FollowUp.objects.create(
            member=member, first_visit_date=timezone.localdate() - timezone.timedelta(days=30)
        )
        digest = build_weekly_digest()
        self.assertEqual(digest["stale_followups"], [follow_up])

    def test_does_not_count_a_recently_started_follow_up(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        FollowUp.objects.create(member=member, first_visit_date=timezone.localdate())
        digest = build_weekly_digest()
        self.assertEqual(digest["stale_followups"], [])


class SendWeeklyDigestCommandTests(TestCase):
    """The send_weekly_digest management command - emails Pastors, no one else."""

    def setUp(self):
        call_command("setup_groups")

    def test_sends_to_every_pastor_with_an_email_on_file(self):
        pastor = User.objects.create_user(
            username="pastor1", email="pastor@example.com", password="test-pass-123", is_staff=True
        )
        pastor.groups.add(Group.objects.get(name="Pastors"))
        User.objects.create_user(username="usher1", password="test-pass-123", is_staff=True)  # not a Pastor
        Donation.objects.create(amount="50.00", status=Donation.Status.PENDING)

        call_command("send_weekly_digest")

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["pastor@example.com"])
        self.assertIn("50", mail.outbox[0].body)

    def test_does_not_send_when_no_pastor_has_an_email_on_file(self):
        pastor = User.objects.create_user(username="pastor1", password="test-pass-123", is_staff=True)
        pastor.groups.add(Group.objects.get(name="Pastors"))
        call_command("send_weekly_digest")
        self.assertEqual(len(mail.outbox), 0)

    def test_does_not_send_to_a_treasurer_or_usher(self):
        treasurer = User.objects.create_user(
            username="treasurer1", email="treasurer@example.com", password="test-pass-123", is_staff=True
        )
        treasurer.groups.add(Group.objects.get(name="Treasurers"))
        call_command("send_weekly_digest")
        self.assertEqual(len(mail.outbox), 0)

    def test_mentions_a_lapsed_recurring_giver_in_the_email_body(self):
        pastor = User.objects.create_user(
            username="pastor2", email="pastor2@example.com", password="test-pass-123", is_staff=True
        )
        pastor.groups.add(Group.objects.get(name="Pastors"))
        member = Member.objects.create(first_name="Yaw", last_name="Osei")
        RecurringGiving.objects.create(
            member=member, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=2,
        )
        call_command("send_weekly_digest")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Yaw Osei", mail.outbox[0].body)
        self.assertIn("Lapsed recurring givers", mail.outbox[0].body)


# --- Leadership meeting minutes ------------------------------------------------


class StaffMeetingTests(TestCase):
    """Pastor-only, same narrowest permission pattern as CareRequest/MemberNote - no other group ever touches this."""

    def setUp(self):
        call_command("setup_groups")
        self.pastor = User.objects.create_user(username="pastor-meet", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))
        self.usher = User.objects.create_user(username="usher-meet", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(
            username="treasurer-meet", password="test-pass-123", is_staff=True
        )
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))
        self.member = Member.objects.create(first_name="Kwesi", last_name="Boateng")

    def test_usher_cannot_view_meetings(self):
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_meeting_list"))
        self.assertEqual(response.status_code, 302)

    def test_treasurer_cannot_view_meetings(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("staff_meeting_list"))
        self.assertEqual(response.status_code, 302)

    def test_pastor_can_view_meeting_list(self):
        Meeting.objects.create(date=timezone.localdate(), title="Monthly Elders Meeting")
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_meeting_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monthly Elders Meeting")

    def test_pastor_can_record_a_meeting(self):
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_meeting_create"),
            {
                "date": "2027-05-01",
                "title": "Monthly Elders Meeting",
                "attendees": [self.member.id],
                "agenda": "Budget review",
                "minutes": "Approved the new budget.",
            },
        )
        self.assertEqual(response.status_code, 302)
        meeting = Meeting.objects.get(title="Monthly Elders Meeting")
        self.assertEqual(meeting.created_by, self.pastor)
        self.assertIn(self.member, meeting.attendees.all())

    def test_pastor_can_edit_a_meeting(self):
        meeting = Meeting.objects.create(date=timezone.localdate(), title="Old Title")
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_meeting_edit", args=[meeting.id]),
            {"date": "2027-05-01", "title": "New Title", "attendees": [], "agenda": "", "minutes": ""},
        )
        self.assertEqual(response.status_code, 302)
        meeting.refresh_from_db()
        self.assertEqual(meeting.title, "New Title")

    def test_usher_cannot_view_meeting_detail(self):
        meeting = Meeting.objects.create(date=timezone.localdate())
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_meeting_detail", args=[meeting.id]))
        self.assertEqual(response.status_code, 302)

    def test_meeting_detail_shows_agenda_minutes_and_attendees(self):
        meeting = Meeting.objects.create(
            date=timezone.localdate(), agenda="Discuss the roof repair", minutes="Approved GH₵5,000 for repairs."
        )
        meeting.attendees.add(self.member)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_meeting_detail", args=[meeting.id]))
        self.assertContains(response, "Discuss the roof repair")
        self.assertContains(response, "Approved")
        self.assertContains(response, "Kwesi Boateng")

    def test_pastor_can_add_an_action_item(self):
        meeting = Meeting.objects.create(date=timezone.localdate())
        self.client.force_login(self.pastor)
        response = self.client.post(
            reverse("staff_action_item_create", args=[meeting.id]),
            {"description": "Book the venue for the retreat", "owner": self.member.id, "due_date": "2027-06-01"},
        )
        self.assertEqual(response.status_code, 302)
        item = ActionItem.objects.get(meeting=meeting)
        self.assertEqual(item.description, "Book the venue for the retreat")
        self.assertEqual(item.owner, self.member)

    def test_pastor_can_toggle_an_action_item_done(self):
        meeting = Meeting.objects.create(date=timezone.localdate())
        item = ActionItem.objects.create(meeting=meeting, description="Book the venue")
        self.client.force_login(self.pastor)
        response = self.client.post(reverse("staff_action_item_toggle", args=[meeting.id, item.id]))
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertTrue(item.is_done)
        self.assertIsNotNone(item.completed_at)

        response = self.client.post(reverse("staff_action_item_toggle", args=[meeting.id, item.id]))
        item.refresh_from_db()
        self.assertFalse(item.is_done)
        self.assertIsNone(item.completed_at)

    def test_usher_cannot_toggle_an_action_item(self):
        meeting = Meeting.objects.create(date=timezone.localdate())
        item = ActionItem.objects.create(meeting=meeting, description="Book the venue")
        self.client.force_login(self.usher)
        response = self.client.post(reverse("staff_action_item_toggle", args=[meeting.id, item.id]))
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertFalse(item.is_done)

    def test_nav_link_shown_only_to_pastors(self):
        self.client.force_login(self.pastor)
        self.assertContains(self.client.get(reverse("staff_home")), "Meetings")

        self.client.force_login(self.usher)
        self.assertNotContains(self.client.get(reverse("staff_home")), ">Meetings<")


class CampusScopingServiceTests(TestCase):
    """
    Direct, no-HTTP tests of the campus-restriction helpers in
    staff/services.py - staff_campus_for's fail-open rules, and every
    scope_*()/in_*_scope() helper's filtering/fallback logic. The view-level
    behavior these helpers power is covered separately below in
    CampusRestrictionViewTests.
    """

    def setUp(self):
        self.main = Campus.objects.create(name="Main Campus")
        self.east = Campus.objects.create(name="East Campus")

    # --- staff_campus_for ---------------------------------------------------

    def test_staff_campus_for_none_with_only_one_campus(self):
        self.east.delete()
        member = Member.objects.create(first_name="Ama", last_name="Owusu", campus=self.main)
        user = User.objects.create_user(username="u1", password="x")
        member.user = user
        member.save()
        self.assertIsNone(staff_campus_for(user))

    def test_staff_campus_for_none_for_superuser(self):
        member = Member.objects.create(first_name="Ama", last_name="Owusu", campus=self.main)
        user = User.objects.create_superuser(username="admin1", password="x", email="a@example.com")
        member.user = user
        member.save()
        self.assertIsNone(staff_campus_for(user))

    def test_staff_campus_for_none_with_no_linked_member(self):
        user = User.objects.create_user(username="u2", password="x")
        self.assertIsNone(staff_campus_for(user))

    def test_staff_campus_for_none_when_linked_member_has_no_campus(self):
        member = Member.objects.create(first_name="Kojo", last_name="Boateng")
        user = User.objects.create_user(username="u3", password="x")
        member.user = user
        member.save()
        self.assertIsNone(staff_campus_for(user))

    def test_staff_campus_for_returns_the_linked_members_campus(self):
        member = Member.objects.create(first_name="Efua", last_name="Asare", campus=self.main)
        user = User.objects.create_user(username="u4", password="x")
        member.user = user
        member.save()
        self.assertEqual(staff_campus_for(user), self.main)

    def test_staff_campus_for_none_for_anonymous_user(self):
        self.assertIsNone(staff_campus_for(AnonymousUser()))

    # --- scope_members / in_campus_scope (fail-open on unset campus) -------

    def test_scope_members_keeps_own_campus_and_unset_campus_hides_other_campus(self):
        mine = Member.objects.create(first_name="A", last_name="One", campus=self.main)
        theirs = Member.objects.create(first_name="B", last_name="Two", campus=self.east)
        unset = Member.objects.create(first_name="C", last_name="Three")
        result = set(scope_members(Member.objects.all(), self.main))
        self.assertEqual(result, {mine, unset})
        self.assertNotIn(theirs, result)

    def test_scope_members_unrestricted_when_campus_is_none(self):
        Member.objects.create(first_name="A", last_name="One", campus=self.main)
        Member.objects.create(first_name="B", last_name="Two", campus=self.east)
        self.assertEqual(scope_members(Member.objects.all(), None).count(), 2)

    def test_in_campus_scope(self):
        self.assertTrue(in_campus_scope(self.main, None))  # unrestricted viewer
        self.assertTrue(in_campus_scope(self.main, self.main))  # matches
        self.assertTrue(in_campus_scope(None, self.main))  # unset - fail open
        self.assertFalse(in_campus_scope(self.east, self.main))  # other campus

    # --- scope_events / scope_giving_campaigns (null = all-campus) ---------

    def test_scope_events_shows_all_campus_events_to_everyone(self):
        mine = Event.objects.create(title="Main service", start_datetime=timezone.now(), campus=self.main)
        theirs = Event.objects.create(title="East service", start_datetime=timezone.now(), campus=self.east)
        everyone = Event.objects.create(title="Church-wide picnic", start_datetime=timezone.now())
        result = set(scope_events(Event.objects.all(), self.main))
        self.assertEqual(result, {mine, everyone})
        self.assertNotIn(theirs, result)

    def test_scope_giving_campaigns_shows_all_campus_campaigns_to_everyone(self):
        today = timezone.localdate()
        mine = GivingCampaign.objects.create(name="Main Building Fund", start_date=today, campus=self.main)
        theirs = GivingCampaign.objects.create(name="East Building Fund", start_date=today, campus=self.east)
        everyone = GivingCampaign.objects.create(name="Missions Push", start_date=today)
        result = set(scope_giving_campaigns(GivingCampaign.objects.all(), self.main))
        self.assertEqual(result, {mine, everyone})
        self.assertNotIn(theirs, result)

    # --- scope_attendance / scope_donations (member-campus fallback) -------

    def test_scope_attendance_falls_back_to_member_campus(self):
        member_main = Member.objects.create(first_name="A", last_name="One", campus=self.main)
        member_east = Member.objects.create(first_name="B", last_name="Two", campus=self.east)
        member_unset = Member.objects.create(first_name="C", last_name="Three")
        today = timezone.localdate()
        own_campus_set = Attendance.objects.create(member=member_main, date=today, present=True, campus=self.main)
        fallback_via_member = Attendance.objects.create(member=member_main, date=today, present=True)
        other_campus = Attendance.objects.create(member=member_east, date=today, present=True, campus=self.east)
        other_via_member = Attendance.objects.create(member=member_east, date=today, present=True)
        doubly_unknown = Attendance.objects.create(member=member_unset, date=today, present=True)

        result = set(scope_attendance(Attendance.objects.all(), self.main))
        self.assertEqual(result, {own_campus_set, fallback_via_member, doubly_unknown})
        self.assertNotIn(other_campus, result)
        self.assertNotIn(other_via_member, result)

    def test_scope_donations_shows_anonymous_gifts_to_everyone(self):
        member_main = Member.objects.create(first_name="A", last_name="One", campus=self.main)
        member_east = Member.objects.create(first_name="B", last_name="Two", campus=self.east)
        mine = Donation.objects.create(member=member_main, amount="10.00", campus=self.main)
        fallback = Donation.objects.create(member=member_main, amount="10.00")
        theirs = Donation.objects.create(member=member_east, amount="10.00", campus=self.east)
        anonymous = Donation.objects.create(member=None, amount="10.00")

        result = set(scope_donations(Donation.objects.all(), self.main))
        self.assertEqual(result, {mine, fallback, anonymous})
        self.assertNotIn(theirs, result)

    def test_in_attendance_donation_scope_matches_queryset_scoping(self):
        member_main = Member.objects.create(first_name="A", last_name="One", campus=self.main)
        member_unset = Member.objects.create(first_name="C", last_name="Three")
        donation_anonymous = Donation.objects.create(member=None, amount="10.00")
        donation_fallback = Donation.objects.create(member=member_main, amount="10.00")
        donation_doubly_unknown = Donation.objects.create(member=member_unset, amount="10.00")

        self.assertTrue(in_attendance_donation_scope(donation_anonymous, self.main, anonymous_ok=True))
        self.assertFalse(in_attendance_donation_scope(donation_anonymous, self.main, anonymous_ok=False))
        self.assertTrue(in_attendance_donation_scope(donation_fallback, self.main))
        self.assertTrue(in_attendance_donation_scope(donation_doubly_unknown, self.main))
        self.assertTrue(in_attendance_donation_scope(donation_anonymous, None))  # unrestricted viewer

    # --- scope_by_member_campus / in_member_campus_scope (Pledge/Recurring) -

    def test_scope_by_member_campus_fails_open_on_unset_member_campus(self):
        member_main = Member.objects.create(first_name="A", last_name="One", campus=self.main)
        member_east = Member.objects.create(first_name="B", last_name="Two", campus=self.east)
        member_unset = Member.objects.create(first_name="C", last_name="Three")
        today = timezone.localdate()
        mine = RecurringGiving.objects.create(member=member_main, amount="10.00", next_due_date=today)
        theirs = RecurringGiving.objects.create(member=member_east, amount="10.00", next_due_date=today)
        unset = RecurringGiving.objects.create(member=member_unset, amount="10.00", next_due_date=today)

        result = set(scope_by_member_campus(RecurringGiving.objects.all(), self.main))
        self.assertEqual(result, {mine, unset})
        self.assertNotIn(theirs, result)

    def test_in_member_campus_scope(self):
        member_main = Member.objects.create(first_name="A", last_name="One", campus=self.main)
        member_unset = Member.objects.create(first_name="C", last_name="Three")
        self.assertTrue(in_member_campus_scope(member_main, None))
        self.assertTrue(in_member_campus_scope(member_main, self.main))
        self.assertTrue(in_member_campus_scope(member_unset, self.main))


class CampusRestrictionViewTests(TestCase):
    """
    End-to-end tests for task #38 "Restrict staff to their own campus" - a
    staff account linked to a Member with a campus set (see
    staff_campus_for) only sees that campus's members, attendance/events,
    and giving in the views below; an unscoped account (superuser, no
    linked Member, or a Pastor with no campus of their own) still sees
    everything, and a single-campus church is entirely unaffected (already
    covered by every other test in this file, none of which link their
    staff users to a Member).
    """

    def setUp(self):
        call_command("setup_groups")
        self.main = Campus.objects.create(name="Main Campus")
        self.east = Campus.objects.create(name="East Campus")

        self.member_main = Member.objects.create(first_name="Ama", last_name="Owusu", campus=self.main)
        self.member_east = Member.objects.create(first_name="Kojo", last_name="Boateng", campus=self.east)
        self.member_unset = Member.objects.create(first_name="Efua", last_name="Asare")

        self.usher_main = User.objects.create_user(username="usher-main", password="test-pass-123", is_staff=True)
        self.usher_main.groups.add(Group.objects.get(name="Ushers"))
        self.member_main.user = self.usher_main
        self.member_main.save()

        self.usher_east = User.objects.create_user(username="usher-east", password="test-pass-123", is_staff=True)
        self.usher_east.groups.add(Group.objects.get(name="Ushers"))
        member_for_east_usher = Member.objects.create(first_name="Kwame", last_name="Mensah", campus=self.east)
        member_for_east_usher.user = self.usher_east
        member_for_east_usher.save()

        # Unscoped Pastor - no linked Member at all, so staff_campus_for
        # fails open and this account sees everything, same as every
        # pre-existing test's pastor/usher/treasurer accounts.
        self.pastor = User.objects.create_user(username="pastor-unscoped", password="test-pass-123", is_staff=True)
        self.pastor.groups.add(Group.objects.get(name="Pastors"))

        self.treasurer_main = User.objects.create_user(
            username="treasurer-main", password="test-pass-123", is_staff=True
        )
        self.treasurer_main.groups.add(Group.objects.get(name="Treasurers"))
        member_for_treasurer = Member.objects.create(first_name="Yaw", last_name="Darko", campus=self.main)
        member_for_treasurer.user = self.treasurer_main
        member_for_treasurer.save()

        self.pastor_main = User.objects.create_user(username="pastor-main", password="test-pass-123", is_staff=True)
        self.pastor_main.groups.add(Group.objects.get(name="Pastors"))
        member_for_pastor = Member.objects.create(first_name="Nana", last_name="Adjei", campus=self.main)
        member_for_pastor.user = self.pastor_main
        member_for_pastor.save()

    # --- Members --------------------------------------------------------

    def test_member_list_only_shows_own_campus_and_unset_campus(self):
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_member_list"))
        self.assertContains(response, "Owusu")
        self.assertContains(response, "Asare")  # unset campus - fail open
        self.assertNotContains(response, "Boateng")

    def test_member_list_campus_filter_hidden_from_scoped_viewer(self):
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_member_list"))
        self.assertIsNone(response.context["campuses"])

    def test_unscoped_pastor_sees_every_campus_in_member_list(self):
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_member_list"))
        self.assertContains(response, "Owusu")
        self.assertContains(response, "Boateng")

    def test_member_detail_404s_for_another_campus(self):
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_member_detail", args=[self.member_east.id]))
        self.assertEqual(response.status_code, 404)

    def test_member_detail_allows_own_campus_and_unset_campus(self):
        self.client.force_login(self.usher_main)
        self.assertEqual(
            self.client.get(reverse("staff_member_detail", args=[self.member_main.id])).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("staff_member_detail", args=[self.member_unset.id])).status_code, 200
        )

    def test_member_edit_404s_for_another_campus(self):
        self.client.force_login(self.pastor_main)
        response = self.client.get(reverse("staff_member_edit", args=[self.member_east.id]))
        self.assertEqual(response.status_code, 404)

    def test_member_edit_allows_own_campus_member(self):
        self.client.force_login(self.pastor_main)
        response = self.client.get(reverse("staff_member_edit", args=[self.member_main.id]))
        self.assertEqual(response.status_code, 200)

    def test_member_create_defaults_campus_for_scoped_viewer(self):
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_member_create"))
        self.assertEqual(response.context["form"].initial.get("campus"), self.main.id)

    def test_member_export_excludes_another_campus(self):
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_member_export"))
        content = response.content.decode()
        self.assertIn("Owusu", content)
        self.assertNotIn("Boateng", content)

    def test_absentee_list_excludes_another_campus(self):
        cutoff = timezone.localdate() - timedelta(weeks=10)
        self.member_main.date_joined = cutoff
        self.member_main.save(update_fields=["date_joined"])
        self.member_east.date_joined = cutoff
        self.member_east.save(update_fields=["date_joined"])
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_absentee_list"))
        self.assertContains(response, "Owusu")
        self.assertNotContains(response, "Boateng")

    # --- Attendance & events ---------------------------------------------

    def test_event_list_shows_own_campus_and_all_campus_events(self):
        soon = timezone.now() + timezone.timedelta(days=3)
        Event.objects.create(title="Main Sunday Service", start_datetime=soon, campus=self.main)
        Event.objects.create(title="East Sunday Service", start_datetime=soon, campus=self.east)
        Event.objects.create(title="Church-wide Picnic", start_datetime=soon)
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_event_list"))
        self.assertContains(response, "Main Sunday Service")
        self.assertContains(response, "Church-wide Picnic")
        self.assertNotContains(response, "East Sunday Service")

    def test_event_detail_404s_for_another_campus(self):
        event = Event.objects.create(title="East Sunday Service", start_datetime=timezone.now(), campus=self.east)
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_event_detail", args=[event.id]))
        self.assertEqual(response.status_code, 404)

    def test_event_detail_allows_all_campus_event(self):
        event = Event.objects.create(title="Church-wide Picnic", start_datetime=timezone.now())
        self.client.force_login(self.usher_main)
        self.assertEqual(self.client.get(reverse("staff_event_detail", args=[event.id])).status_code, 200)

    def test_event_create_defaults_campus_for_scoped_viewer(self):
        self.client.force_login(self.pastor_main)
        response = self.client.get(reverse("staff_event_create"))
        self.assertEqual(response.context["form"].initial.get("campus"), self.main.id)

    def test_volunteer_slot_create_404s_for_another_campus_event(self):
        event = Event.objects.create(title="East Sunday Service", start_datetime=timezone.now(), campus=self.east)
        self.client.force_login(self.pastor_main)
        response = self.client.get(reverse("staff_slot_create", args=[event.id]))
        self.assertEqual(response.status_code, 404)

    def test_volunteer_slot_create_allows_own_campus_event(self):
        event = Event.objects.create(title="Main Sunday Service", start_datetime=timezone.now(), campus=self.main)
        self.client.force_login(self.pastor_main)
        response = self.client.get(reverse("staff_slot_create", args=[event.id]))
        self.assertEqual(response.status_code, 200)

    def test_attendance_by_campus_breakdown_hidden_from_scoped_viewer(self):
        Attendance.objects.create(member=self.member_main, date=timezone.localdate(), present=True, campus=self.main)
        Attendance.objects.create(member=self.member_east, date=timezone.localdate(), present=True, campus=self.east)
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_reports"))
        self.assertNotContains(response, "Attendance by Campus")

    def test_attendance_by_campus_breakdown_shown_to_unscoped_pastor(self):
        Attendance.objects.create(member=self.member_main, date=timezone.localdate(), present=True, campus=self.main)
        Attendance.objects.create(member=self.member_east, date=timezone.localdate(), present=True, campus=self.east)
        self.client.force_login(self.pastor)
        response = self.client.get(reverse("staff_reports"))
        self.assertContains(response, "Attendance by Campus")

    # --- Giving & donations ------------------------------------------------

    def test_donation_list_only_shows_own_campus(self):
        Donation.objects.create(member=self.member_main, amount="50.00", campus=self.main)
        Donation.objects.create(member=self.member_east, amount="75.00", campus=self.east)
        self.client.force_login(self.treasurer_main)
        response = self.client.get(reverse("staff_donation_list"))
        self.assertContains(response, "50.00")
        self.assertNotContains(response, "75.00")

    def test_donation_mark_completed_404s_for_another_campus(self):
        donation = Donation.objects.create(
            member=self.member_east, amount="75.00", campus=self.east, status=Donation.Status.PENDING
        )
        self.client.force_login(self.treasurer_main)
        response = self.client.post(reverse("staff_donation_complete", args=[donation.id]))
        self.assertEqual(response.status_code, 404)

    def test_donation_mark_completed_allows_own_campus_gift(self):
        donation = Donation.objects.create(
            member=self.member_main, amount="50.00", campus=self.main, status=Donation.Status.PENDING
        )
        self.client.force_login(self.treasurer_main)
        response = self.client.post(reverse("staff_donation_complete", args=[donation.id]))
        self.assertEqual(response.status_code, 302)
        donation.refresh_from_db()
        self.assertEqual(donation.status, Donation.Status.COMPLETED)

    def test_campaign_list_shows_own_campus_and_all_campus_campaigns(self):
        today = timezone.localdate()
        GivingCampaign.objects.create(name="Main Building Fund", start_date=today, campus=self.main)
        GivingCampaign.objects.create(name="East Building Fund", start_date=today, campus=self.east)
        GivingCampaign.objects.create(name="Missions Push", start_date=today)
        self.client.force_login(self.treasurer_main)
        response = self.client.get(reverse("staff_campaign_list"))
        self.assertContains(response, "Main Building Fund")
        self.assertContains(response, "Missions Push")
        self.assertNotContains(response, "East Building Fund")

    def test_campaign_detail_404s_for_another_campus(self):
        campaign = GivingCampaign.objects.create(
            name="East Building Fund", start_date=timezone.localdate(), campus=self.east
        )
        self.client.force_login(self.treasurer_main)
        response = self.client.get(reverse("staff_campaign_detail", args=[campaign.id]))
        self.assertEqual(response.status_code, 404)

    def test_recurring_giving_list_fails_open_on_unset_member_campus(self):
        today = timezone.localdate()
        RecurringGiving.objects.create(member=self.member_main, amount="10.00", next_due_date=today)
        RecurringGiving.objects.create(member=self.member_east, amount="10.00", next_due_date=today)
        RecurringGiving.objects.create(member=self.member_unset, amount="10.00", next_due_date=today)
        self.client.force_login(self.treasurer_main)
        response = self.client.get(reverse("staff_recurring_giving_list"))
        self.assertContains(response, "Owusu")
        self.assertContains(response, "Asare")
        self.assertNotContains(response, "Boateng")

    def test_annual_giving_statement_404s_for_another_campus_member(self):
        self.client.force_login(self.treasurer_main)
        response = self.client.get(reverse("staff_annual_giving_statement", args=[self.member_east.id]))
        self.assertEqual(response.status_code, 404)

    # --- Staff home & search ------------------------------------------------

    def test_staff_home_stats_scoped_to_own_campus(self):
        self.client.force_login(self.usher_main)
        before = self.client.get(reverse("staff_home")).context["stats"]["active_members"]
        # Adding another East-campus member shouldn't move usher_main's own
        # active_members count at all - only adding one to Main (or with no
        # campus, per the fail-open rule) should.
        Member.objects.create(first_name="New", last_name="EastMember", campus=self.east)
        after_east = self.client.get(reverse("staff_home")).context["stats"]["active_members"]
        self.assertEqual(before, after_east)

        Member.objects.create(first_name="New", last_name="MainMember", campus=self.main)
        after_main = self.client.get(reverse("staff_home")).context["stats"]["active_members"]
        self.assertEqual(after_main, before + 1)

    def test_staff_search_excludes_another_campus_member(self):
        # "members" is still in results (the viewer has view_member - see
        # staff_search's docstring: a section is left out entirely only for
        # missing *permission*, not because scoping filtered every match
        # out) - it's just an empty queryset, same as any search with no
        # hits.
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_search"), {"q": "Boateng"})
        self.assertEqual(list(response.context["results"]["members"]), [])

    def test_staff_search_includes_own_campus_member(self):
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_search"), {"q": "Owusu"})
        self.assertIn("members", response.context["results"])
        self.assertEqual(len(response.context["results"]["members"]), 1)

    def test_single_campus_church_is_entirely_unaffected(self):
        """
        The whole feature is opt-in - a single-campus church (the default,
        and every other test class in this file) never triggers any of this,
        even for a staff account that happens to be linked to a Member.
        """
        self.east.delete()
        self.client.force_login(self.usher_main)
        response = self.client.get(reverse("staff_member_list"))
        self.assertContains(response, "Owusu")
        self.assertContains(response, "Boateng")  # now visible - restriction never engaged
        self.assertContains(response, "Asare")
