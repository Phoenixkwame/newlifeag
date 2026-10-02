from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from giving.flutterwave import FlutterwaveError
from members.models import Attendance, Campus, Member, ServingAssignment
from members.models import Group as ChurchGroup

from .forms import QrCheckinForm, RSVPForm
from .models import (
    RSVP,
    Event,
    EventRegistration,
    EventServiceTime,
    EventTicket,
    VolunteerSignup,
    VolunteerSlot,
    VolunteerWaitlistEntry,
)
from .services import (
    SlotFullError,
    TicketFullError,
    cancel_volunteer_signup,
    check_in_via_qr,
    conflicting_commitments_on,
    generate_recurring_occurrences,
    join_waitlist,
    register_for_ticket,
    sign_up_for_slot,
)


def login_member(client, member):
    """Exercise member actions as the owner of the active member profile."""
    if member.user_id is None:
        member.user = User.objects.create_user(username=f"event-member-{member.pk}")
        member.save(update_fields=["user"])
    client.force_login(member.user)


class VolunteerSlotTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Test Service",
            start_datetime=timezone.now() + timezone.timedelta(days=1),
        )
        self.slot = VolunteerSlot.objects.create(event=self.event, role_needed="Usher", capacity=1)
        self.member = Member.objects.create(first_name="Kofi", last_name="Addo")
        login_member(self.client, self.member)

    def test_slot_starts_with_full_capacity_open(self):
        self.assertEqual(self.slot.spots_remaining, 1)

    def test_signup_fills_the_slot(self):
        VolunteerSignup.objects.create(slot=self.slot, member=self.member)
        self.assertEqual(self.slot.spots_remaining, 0)

    def test_signing_up_via_the_event_page_creates_a_signup(self):
        url = reverse("event_detail", args=[self.event.id])
        response = self.client.post(
            url,
            {"form_type": "volunteer", "member": self.member.id, "slot": self.slot.id},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(VolunteerSignup.objects.filter(slot=self.slot, member=self.member).exists())

    def test_full_slot_remains_available_to_join_the_waitlist(self):
        other = Member.objects.create(first_name="Ama", last_name="Mensah")
        VolunteerSignup.objects.create(slot=self.slot, member=other)
        url = reverse("event_detail", args=[self.event.id])
        response = self.client.get(url)
        self.assertContains(response, "Sign up or join the waitlist")
        self.assertIn(self.slot, response.context["volunteer_form"].fields["slot"].queryset)
        self.client.post(url, {"form_type": "volunteer", "member": self.member.pk, "slot": self.slot.pk})
        self.assertTrue(VolunteerWaitlistEntry.objects.filter(slot=self.slot, member=self.member).exists())
        self.assertEqual(self.slot.signups.count(), 1)


class SignUpForSlotServiceTests(TestCase):
    """
    Direct tests of the locked check-and-create used by the volunteer sign-up
    view (events/services.py). These test the actual fix for the last-spot
    race condition. Full slots remain selectable for the waitlist. These
    cases include a slot filling between form validation and the locked
    check, as can happen with two simultaneous requests.
    """

    def setUp(self):
        self.event = Event.objects.create(
            title="Test Service",
            start_datetime=timezone.now() + timezone.timedelta(days=1),
        )
        self.slot = VolunteerSlot.objects.create(event=self.event, role_needed="Usher", capacity=1)
        self.member = Member.objects.create(first_name="Kofi", last_name="Addo")
        self.other_member = Member.objects.create(first_name="Efua", last_name="Owusu")
        login_member(self.client, self.member)

    def test_signs_up_when_a_spot_is_open(self):
        signup, created = sign_up_for_slot(slot_id=self.slot.id, member=self.member)
        self.assertTrue(created)
        self.assertEqual(signup.member, self.member)

    def test_raises_slot_full_error_once_capacity_is_reached(self):
        sign_up_for_slot(slot_id=self.slot.id, member=self.member)  # fills the only spot
        with self.assertRaises(SlotFullError):
            sign_up_for_slot(slot_id=self.slot.id, member=self.other_member)
        # The rejected attempt must not have created a second signup.
        self.assertEqual(VolunteerSignup.objects.filter(slot=self.slot).count(), 1)

    def test_signing_up_twice_for_the_same_slot_is_a_no_op_not_an_error(self):
        sign_up_for_slot(slot_id=self.slot.id, member=self.member)
        signup, created = sign_up_for_slot(slot_id=self.slot.id, member=self.member)
        self.assertFalse(created)
        self.assertEqual(VolunteerSignup.objects.filter(slot=self.slot, member=self.member).count(), 1)

    def test_view_adds_member_to_the_waitlist_when_the_slot_fills_before_the_locked_check(self):
        """
        Same race-condition scenario the class docstring above describes -
        forced here with a mock rather than genuine concurrency, since the
        form's own dropdown already excludes a truly-full slot (see
        VolunteerSignupForm), so this is the only way to reach the view's
        SlotFullError branch (events/views.py's event_detail) outside of a
        real simultaneous request.
        """
        with patch("events.views.sign_up_for_slot", side_effect=SlotFullError("full")):
            response = self.client.post(
                reverse("event_detail", args=[self.event.id]),
                {"form_type": "volunteer", "member": self.member.id, "slot": self.slot.id},
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(VolunteerWaitlistEntry.objects.filter(slot=self.slot, member=self.member).exists())


class JoinWaitlistTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(title="Test Service", start_datetime=timezone.now() + timezone.timedelta(days=1))
        self.slot = VolunteerSlot.objects.create(event=self.event, role_needed="Usher", capacity=1)
        self.member = Member.objects.create(first_name="Kofi", last_name="Addo")

    def test_joining_creates_an_entry(self):
        entry, created = join_waitlist(slot_id=self.slot.id, member=self.member)
        self.assertTrue(created)
        self.assertEqual(entry.member, self.member)

    def test_joining_twice_is_a_no_op_not_a_duplicate(self):
        join_waitlist(slot_id=self.slot.id, member=self.member)
        entry, created = join_waitlist(slot_id=self.slot.id, member=self.member)
        self.assertFalse(created)
        self.assertEqual(VolunteerWaitlistEntry.objects.filter(slot=self.slot, member=self.member).count(), 1)


class CancelVolunteerSignupTests(TestCase):
    """events/services.py's cancel_volunteer_signup - the "Event waitlists" auto-promotion mechanism."""

    def setUp(self):
        self.event = Event.objects.create(title="Test Service", start_datetime=timezone.now() + timezone.timedelta(days=1))
        self.slot = VolunteerSlot.objects.create(event=self.event, role_needed="Usher", capacity=1)
        self.member = Member.objects.create(first_name="Kofi", last_name="Addo", email="kofi@example.com")
        self.waitlisted = Member.objects.create(first_name="Efua", last_name="Owusu", email="efua@example.com")
        self.signup, _ = sign_up_for_slot(slot_id=self.slot.id, member=self.member)

    def test_cancelling_removes_the_signup(self):
        cancelled, promoted = cancel_volunteer_signup(signup_id=self.signup.id, member=self.member)
        self.assertTrue(cancelled)
        self.assertFalse(VolunteerSignup.objects.filter(id=self.signup.id).exists())

    def test_cancelling_promotes_the_earliest_waitlisted_member(self):
        join_waitlist(slot_id=self.slot.id, member=self.waitlisted)
        cancelled, promoted = cancel_volunteer_signup(signup_id=self.signup.id, member=self.member)
        self.assertTrue(cancelled)
        self.assertIsNotNone(promoted)
        self.assertEqual(promoted.member, self.waitlisted)
        self.assertTrue(VolunteerSignup.objects.filter(slot=self.slot, member=self.waitlisted).exists())
        self.assertFalse(VolunteerWaitlistEntry.objects.filter(slot=self.slot, member=self.waitlisted).exists())

    def test_cancelling_notifies_the_promoted_member(self):
        join_waitlist(slot_id=self.slot.id, member=self.waitlisted)
        cancel_volunteer_signup(signup_id=self.signup.id, member=self.member)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("efua@example.com", mail.outbox[0].to)

    def test_cancelling_with_no_one_waitlisted_promotes_no_one(self):
        cancelled, promoted = cancel_volunteer_signup(signup_id=self.signup.id, member=self.member)
        self.assertTrue(cancelled)
        self.assertIsNone(promoted)
        self.assertEqual(len(mail.outbox), 0)

    def test_cancelling_someone_elses_signup_is_a_no_op(self):
        other_member = Member.objects.create(first_name="Yaw", last_name="Boateng")
        cancelled, promoted = cancel_volunteer_signup(signup_id=self.signup.id, member=other_member)
        self.assertFalse(cancelled)
        self.assertTrue(VolunteerSignup.objects.filter(id=self.signup.id).exists())

    def test_waitlist_is_promoted_in_first_come_first_served_order(self):
        second_waitlisted = Member.objects.create(first_name="Ama", last_name="Serwaa", email="ama@example.com")
        join_waitlist(slot_id=self.slot.id, member=self.waitlisted)
        join_waitlist(slot_id=self.slot.id, member=second_waitlisted)
        cancelled, promoted = cancel_volunteer_signup(signup_id=self.signup.id, member=self.member)
        self.assertEqual(promoted.member, self.waitlisted)
        # The second person is still waiting - the slot only had one spot.
        self.assertTrue(VolunteerWaitlistEntry.objects.filter(slot=self.slot, member=second_waitlisted).exists())


class ConflictingCommitmentsOnTests(TestCase):
    """
    events/services.py's conflicting_commitments_on - the volunteer
    scheduling conflict warning shared by the public event volunteer
    sign-up (events/views.py's event_detail) and a group leader's serving
    schedule (members/views.py's serving_schedule).
    """

    def setUp(self):
        self.member = Member.objects.create(first_name="Kofi", last_name="Addo")
        self.on_date = timezone.localdate() + timezone.timedelta(days=7)
        login_member(self.client, self.member)

    def test_no_conflicts_for_a_member_with_no_other_commitments(self):
        self.assertEqual(conflicting_commitments_on(self.member, self.on_date), [])

    def test_flags_a_serving_assignment_on_the_same_date_for_a_different_group(self):
        group = ChurchGroup.objects.create(name="Ushering Team")
        ServingAssignment.objects.create(group=group, member=self.member, role="Usher", date=self.on_date)
        conflicts = conflicting_commitments_on(self.member, self.on_date)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("Ushering Team", conflicts[0])

    def test_exclude_assignment_id_leaves_out_that_one_assignment(self):
        group = ChurchGroup.objects.create(name="Ushering Team")
        assignment = ServingAssignment.objects.create(
            group=group, member=self.member, role="Usher", date=self.on_date
        )
        self.assertEqual(
            conflicting_commitments_on(self.member, self.on_date, exclude_assignment_id=assignment.id), []
        )

    def test_flags_a_volunteer_signup_for_an_event_on_the_same_date(self):
        event = Event.objects.create(
            title="Christmas Program",
            start_datetime=timezone.make_aware(
                timezone.datetime.combine(self.on_date, timezone.datetime.min.time().replace(hour=18))
            ),
        )
        slot = VolunteerSlot.objects.create(event=event, role_needed="Media", capacity=1)
        VolunteerSignup.objects.create(slot=slot, member=self.member)
        conflicts = conflicting_commitments_on(self.member, self.on_date)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("Christmas Program", conflicts[0])

    def test_exclude_event_id_leaves_out_that_one_events_signup(self):
        event = Event.objects.create(
            title="Christmas Program",
            start_datetime=timezone.make_aware(
                timezone.datetime.combine(self.on_date, timezone.datetime.min.time().replace(hour=18))
            ),
        )
        slot = VolunteerSlot.objects.create(event=event, role_needed="Media", capacity=1)
        VolunteerSignup.objects.create(slot=slot, member=self.member)
        self.assertEqual(
            conflicting_commitments_on(self.member, self.on_date, exclude_event_id=event.id), []
        )

    def test_flags_both_kinds_of_conflict_at_once(self):
        group = ChurchGroup.objects.create(name="Ushering Team")
        ServingAssignment.objects.create(group=group, member=self.member, role="Usher", date=self.on_date)
        event = Event.objects.create(
            title="Christmas Program",
            start_datetime=timezone.make_aware(
                timezone.datetime.combine(self.on_date, timezone.datetime.min.time().replace(hour=18))
            ),
        )
        slot = VolunteerSlot.objects.create(event=event, role_needed="Media", capacity=1)
        VolunteerSignup.objects.create(slot=slot, member=self.member)
        self.assertEqual(len(conflicting_commitments_on(self.member, self.on_date)), 2)

    def test_signing_up_for_a_slot_on_the_event_page_shows_a_conflict_warning(self):
        group = ChurchGroup.objects.create(name="Ushering Team")
        event = Event.objects.create(
            title="Christmas Program",
            start_datetime=timezone.make_aware(
                timezone.datetime.combine(self.on_date, timezone.datetime.min.time().replace(hour=18))
            ),
        )
        ServingAssignment.objects.create(group=group, member=self.member, role="Usher", date=self.on_date)
        slot = VolunteerSlot.objects.create(event=event, role_needed="Media", capacity=1)
        response = self.client.post(
            reverse("event_detail", args=[event.id]),
            {"form_type": "volunteer", "member": self.member.id, "slot": slot.id},
            follow=True,
        )
        self.assertContains(response, "already scheduled to serve as Usher")


class EventNotificationTests(TestCase):
    """Confirmation emails for RSVPs and volunteer sign-ups (events/notifications.py)."""

    def setUp(self):
        self.event = Event.objects.create(
            title="Sunday Service",
            start_datetime=timezone.now() + timezone.timedelta(days=2),
            location="Main Auditorium",
        )
        self.member = Member.objects.create(first_name="Ama", last_name="Serwaa", email="ama@example.com")
        login_member(self.client, self.member)

    def test_rsvp_sends_a_confirmation_email(self):
        self.client.post(
            reverse("event_detail", args=[self.event.id]),
            {"form_type": "rsvp", "member": self.member.id, "status": "going"},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.member.email, mail.outbox[0].to)
        self.assertIn("RSVP confirmed", mail.outbox[0].subject)

    def test_no_email_sent_when_member_has_no_email_on_file(self):
        member_no_email = Member.objects.create(first_name="Yaw", last_name="Boateng")
        login_member(self.client, member_no_email)
        self.client.post(
            reverse("event_detail", args=[self.event.id]),
            {"form_type": "rsvp", "member": member_no_email.id, "status": "going"},
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_volunteer_signup_sends_a_confirmation_email_only_once(self):
        slot = VolunteerSlot.objects.create(event=self.event, role_needed="Usher", capacity=2)
        url = reverse("event_detail", args=[self.event.id])
        self.client.post(url, {"form_type": "volunteer", "member": self.member.id, "slot": slot.id})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("signed up to volunteer", mail.outbox[0].subject)

        # Re-submitting the same signup is a no-op and must not resend it.
        self.client.post(url, {"form_type": "volunteer", "member": self.member.id, "slot": slot.id})
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_rsvp_also_sends_an_sms_when_sms_is_configured_and_member_has_a_phone(self):
        self.member.phone = "0244000000"
        self.member.save()
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            self.client.post(
                reverse("event_detail", args=[self.event.id]),
                {"form_type": "rsvp", "member": self.member.id, "status": "going"},
            )
        mock_get.assert_called_once()

    def test_no_sms_is_attempted_when_sms_isnt_configured(self):
        # No HUBTEL_* settings are configured in the test environment by
        # default - this confirms that state truly costs nothing here too.
        self.member.phone = "0244000000"
        self.member.save()
        with patch("churchapp.sms.requests.get") as mock_get:
            self.client.post(
                reverse("event_detail", args=[self.event.id]),
                {"form_type": "rsvp", "member": self.member.id, "status": "going"},
            )
        mock_get.assert_not_called()


class UpcomingEventsViewTests(TestCase):
    def test_future_events_are_listed(self):
        Event.objects.create(
            title="Future Service", start_datetime=timezone.now() + timezone.timedelta(days=1)
        )
        response = self.client.get(reverse("upcoming_events"))
        self.assertContains(response, "Future Service")

    def test_past_events_are_not_listed(self):
        Event.objects.create(
            title="Old Service", start_datetime=timezone.now() - timezone.timedelta(days=1)
        )
        response = self.client.get(reverse("upcoming_events"))
        self.assertNotContains(response, "Old Service")

    def test_search_filters_by_title(self):
        Event.objects.create(title="Youth Camp", start_datetime=timezone.now() + timezone.timedelta(days=1))
        Event.objects.create(title="Choir Rehearsal", start_datetime=timezone.now() + timezone.timedelta(days=2))
        response = self.client.get(reverse("upcoming_events"), {"q": "youth"})
        self.assertContains(response, "Youth Camp")
        self.assertNotContains(response, "Choir Rehearsal")

    def test_filter_by_event_type(self):
        Event.objects.create(
            title="Sunday Service",
            event_type=Event.EventType.SERVICE,
            start_datetime=timezone.now() + timezone.timedelta(days=1),
        )
        Event.objects.create(
            title="Community Outreach",
            event_type=Event.EventType.OUTREACH,
            start_datetime=timezone.now() + timezone.timedelta(days=2),
        )
        response = self.client.get(reverse("upcoming_events"), {"type": "outreach"})
        self.assertContains(response, "Community Outreach")
        self.assertNotContains(response, "Sunday Service")


class EventCampusFilterTests(TestCase):
    """The public events page's campus filter - hidden until a second campus exists (see events/views.py)."""

    def test_campus_filter_is_hidden_with_one_or_no_campus(self):
        response = self.client.get(reverse("upcoming_events"))
        self.assertNotContains(response, 'name="campus"')

    def test_campus_filter_appears_and_filters_once_a_second_campus_exists(self):
        main = Campus.objects.create(name="Main Campus")
        tema = Campus.objects.create(name="Tema Branch")
        Event.objects.create(
            title="Main Service", campus=main, start_datetime=timezone.now() + timezone.timedelta(days=1)
        )
        Event.objects.create(
            title="Tema Service", campus=tema, start_datetime=timezone.now() + timezone.timedelta(days=1)
        )
        response = self.client.get(reverse("upcoming_events"))
        self.assertContains(response, 'name="campus"')

        response = self.client.get(reverse("upcoming_events"), {"campus": tema.id})
        self.assertContains(response, "Tema Service")
        self.assertNotContains(response, "Main Service")


class RecurringEventTests(TestCase):
    """Direct tests of the recurring-occurrence generator (events/services.py)."""

    def test_weekly_recurrence_creates_events_seven_days_apart(self):
        parent = Event.objects.create(
            title="Sunday Service",
            start_datetime=timezone.datetime(2027, 1, 3, 9, 0, tzinfo=timezone.get_current_timezone()),
            recurrence=Event.Recurrence.WEEKLY,
        )
        created = generate_recurring_occurrences(parent, frequency=Event.Recurrence.WEEKLY, count=4)
        self.assertEqual(len(created), 3)
        self.assertEqual(Event.objects.filter(series_parent=parent).count(), 3)
        self.assertEqual(created[0].start_datetime, parent.start_datetime + timezone.timedelta(weeks=1))
        self.assertEqual(created[1].start_datetime, parent.start_datetime + timezone.timedelta(weeks=2))
        # Occurrences are their own independent events, not repeaters themselves.
        self.assertEqual(created[0].recurrence, Event.Recurrence.NONE)

    def test_monthly_recurrence_clamps_end_of_month_dates(self):
        # Jan 31 + 1 month has no Feb 31 - this must land on Feb 28 (2027 is
        # not a leap year), not raise or silently roll into March.
        parent = Event.objects.create(
            title="Monthly Meeting",
            start_datetime=timezone.datetime(2027, 1, 31, 18, 0, tzinfo=timezone.get_current_timezone()),
            recurrence=Event.Recurrence.MONTHLY,
        )
        created = generate_recurring_occurrences(parent, frequency=Event.Recurrence.MONTHLY, count=2)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].start_datetime.date().isoformat(), "2027-02-28")

    def test_end_datetime_offset_is_preserved(self):
        start = timezone.datetime(2027, 3, 7, 9, 0, tzinfo=timezone.get_current_timezone())
        parent = Event.objects.create(
            title="Bible Study",
            start_datetime=start,
            end_datetime=start + timezone.timedelta(hours=2),
            recurrence=Event.Recurrence.WEEKLY,
        )
        created = generate_recurring_occurrences(parent, frequency=Event.Recurrence.WEEKLY, count=2)
        self.assertEqual(created[0].end_datetime - created[0].start_datetime, timezone.timedelta(hours=2))

    def test_count_of_one_creates_no_extra_occurrences(self):
        parent = Event.objects.create(
            title="One-off", start_datetime=timezone.now() + timezone.timedelta(days=1)
        )
        created = generate_recurring_occurrences(parent, frequency=Event.Recurrence.WEEKLY, count=1)
        self.assertEqual(created, [])


class VolunteerReminderCommandTests(TestCase):
    """
    The send_volunteer_reminders management command - meant to be run daily
    (see the command's own docstring), so these tests focus on it never
    double-sending and never reaching outside its window.
    """

    def _make_signup(self, *, hours_until_event, email="volunteer@example.com"):
        event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(hours=hours_until_event)
        )
        slot = VolunteerSlot.objects.create(event=event, role_needed="Usher", capacity=2)
        member = Member.objects.create(first_name="Kwesi", last_name="Amoah", email=email)
        return VolunteerSignup.objects.create(slot=slot, member=member)

    def test_reminder_is_sent_for_a_signup_within_the_window(self):
        signup = self._make_signup(hours_until_event=30)
        call_command("send_volunteer_reminders")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("volunteer@example.com", mail.outbox[0].to)
        signup.refresh_from_db()
        self.assertIsNotNone(signup.reminder_sent_at)

    def test_reminder_is_not_sent_for_a_signup_outside_the_window(self):
        signup = self._make_signup(hours_until_event=24 * 10)
        call_command("send_volunteer_reminders")
        self.assertEqual(len(mail.outbox), 0)
        signup.refresh_from_db()
        self.assertIsNone(signup.reminder_sent_at)

    def test_reminder_is_not_sent_for_a_past_event(self):
        signup = self._make_signup(hours_until_event=-2)
        call_command("send_volunteer_reminders")
        self.assertEqual(len(mail.outbox), 0)

    def test_running_the_command_twice_does_not_double_send(self):
        self._make_signup(hours_until_event=10)
        call_command("send_volunteer_reminders")
        call_command("send_volunteer_reminders")
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_reminder_also_sends_sms_when_configured_and_member_has_a_phone(self):
        signup = self._make_signup(hours_until_event=10)
        signup.member.phone = "0244000000"
        signup.member.save()
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            call_command("send_volunteer_reminders")
        mock_get.assert_called_once()

    def test_no_email_sent_when_member_has_turned_this_reminder_off(self):
        signup = self._make_signup(hours_until_event=10)
        signup.member.notify_volunteer_reminders = False
        signup.member.save()
        call_command("send_volunteer_reminders")
        self.assertEqual(len(mail.outbox), 0)

    def test_reminder_sent_at_is_still_marked_when_the_member_has_opted_out(self):
        """
        Opting out shouldn't cause the daily command to keep retrying the
        same signup forever - reminder_sent_at is marked either way (see
        send_volunteer_reminder's docstring).
        """
        signup = self._make_signup(hours_until_event=10)
        signup.member.notify_volunteer_reminders = False
        signup.member.save()
        call_command("send_volunteer_reminders")
        signup.refresh_from_db()
        self.assertIsNotNone(signup.reminder_sent_at)

    def test_signup_confirmation_is_unaffected_by_the_reminder_opt_out(self):
        """
        send_volunteer_signup_confirmation - the immediate confirmation of
        the member's own sign-up - is never gated on
        notify_volunteer_reminders, unlike the later reminder above.
        """
        event = Event.objects.create(title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=3))
        slot = VolunteerSlot.objects.create(event=event, role_needed="Usher", capacity=2)
        member = Member.objects.create(
            first_name="Kwesi", last_name="Amoah", email="volunteer@example.com", notify_volunteer_reminders=False
        )
        login_member(self.client, member)
        response = self.client.post(
            reverse("event_detail", args=[event.id]),
            {"form_type": "volunteer", "member": member.id, "slot": slot.id},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("volunteer@example.com", mail.outbox[0].to)


class EventTicketModelTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Youth Retreat", start_datetime=timezone.now() + timezone.timedelta(days=10)
        )
        self.ticket = EventTicket.objects.create(event=self.event, name="Adult", price="150.00", capacity=1)
        self.member = Member.objects.create(first_name="Kofi", last_name="Addo")
        self.other_member = Member.objects.create(first_name="Efua", last_name="Owusu")

    def test_registered_count_counts_pending_and_completed(self):
        EventRegistration.objects.create(
            ticket=self.ticket, member=self.member, status=EventRegistration.Status.PENDING
        )
        self.assertEqual(self.ticket.registered_count, 1)
        self.assertTrue(self.ticket.is_full)

    def test_failed_registration_does_not_count_against_capacity(self):
        EventRegistration.objects.create(
            ticket=self.ticket, member=self.member, status=EventRegistration.Status.FAILED
        )
        self.assertEqual(self.ticket.registered_count, 0)
        self.assertFalse(self.ticket.is_full)

    def test_no_capacity_means_never_full(self):
        unlimited = EventTicket.objects.create(event=self.event, name="General", price="50.00")
        EventRegistration.objects.create(
            ticket=unlimited, member=self.member, status=EventRegistration.Status.COMPLETED
        )
        self.assertFalse(unlimited.is_full)


class RegisterForTicketServiceTests(TestCase):
    """
    Direct tests of the locked check-and-create used by paid event
    registration (events/services.py) - same race-condition-safe pattern
    already proven for sign_up_for_slot above.
    """

    def setUp(self):
        self.event = Event.objects.create(
            title="Youth Retreat", start_datetime=timezone.now() + timezone.timedelta(days=10)
        )
        self.ticket = EventTicket.objects.create(event=self.event, name="Adult", price="150.00", capacity=1)
        self.member = Member.objects.create(first_name="Kofi", last_name="Addo")
        self.other_member = Member.objects.create(first_name="Efua", last_name="Owusu")

    def test_registers_when_a_spot_is_open(self):
        registration, created = register_for_ticket(ticket_id=self.ticket.id, member=self.member)
        self.assertTrue(created)
        self.assertEqual(registration.member, self.member)
        self.assertEqual(registration.status, EventRegistration.Status.PENDING)

    def test_raises_ticket_full_error_once_capacity_is_reached(self):
        register_for_ticket(ticket_id=self.ticket.id, member=self.member)  # fills the only spot
        with self.assertRaises(TicketFullError):
            register_for_ticket(ticket_id=self.ticket.id, member=self.other_member)
        self.assertEqual(EventRegistration.objects.filter(ticket=self.ticket).count(), 1)

    def test_registering_twice_for_the_same_ticket_is_a_no_op_not_an_error(self):
        register_for_ticket(ticket_id=self.ticket.id, member=self.member)
        registration, created = register_for_ticket(ticket_id=self.ticket.id, member=self.member)
        self.assertFalse(created)
        self.assertEqual(
            EventRegistration.objects.filter(ticket=self.ticket, member=self.member).count(), 1
        )

    def test_a_previously_failed_registration_frees_the_spot_for_a_new_attempt(self):
        first = register_for_ticket(ticket_id=self.ticket.id, member=self.member)[0]
        first.status = EventRegistration.Status.FAILED
        first.save(update_fields=["status"])
        registration, created = register_for_ticket(ticket_id=self.ticket.id, member=self.other_member)
        self.assertTrue(created)
        self.assertEqual(registration.member, self.other_member)


class EventRegistrationViewTests(TestCase):
    """
    Registering via the public event page. FLUTTERWAVE_SECRET_KEY is blank
    in the test environment, so a paid ticket takes the same
    fallback-to-confirmed-for-staff-follow-up path as giving's manual-mode
    donations (see events/views.py's _start_registration_payment) - these
    tests exercise exactly that path, without any network mocking.
    """

    def setUp(self):
        self.event = Event.objects.create(
            title="Youth Retreat", start_datetime=timezone.now() + timezone.timedelta(days=10)
        )
        self.member = Member.objects.create(first_name="Ama", last_name="Serwaa", email="ama@example.com")
        login_member(self.client, self.member)

    def test_registering_for_a_free_ticket_completes_immediately(self):
        ticket = EventTicket.objects.create(event=self.event, name="General", price="0.00")
        response = self.client.post(
            reverse("event_detail", args=[self.event.id]),
            {"form_type": "register", "member": self.member.id, "ticket": ticket.id},
        )
        self.assertEqual(response.status_code, 302)
        registration = EventRegistration.objects.get(ticket=ticket, member=self.member)
        self.assertEqual(registration.status, EventRegistration.Status.COMPLETED)
        self.assertEqual(len(mail.outbox), 1)

    def test_registering_for_a_paid_ticket_without_payments_configured_stays_confirmed_pending_followup(self):
        ticket = EventTicket.objects.create(event=self.event, name="Adult", price="150.00")
        response = self.client.post(
            reverse("event_detail", args=[self.event.id]),
            {"form_type": "register", "member": self.member.id, "ticket": ticket.id},
        )
        self.assertEqual(response.status_code, 302)
        registration = EventRegistration.objects.get(ticket=ticket, member=self.member)
        self.assertEqual(registration.status, EventRegistration.Status.COMPLETED)

    def test_full_ticket_rejects_a_new_reservation(self):
        ticket = EventTicket.objects.create(event=self.event, name="Adult", price="150.00", capacity=1)
        other = Member.objects.create(first_name="Kofi", last_name="Mensah")
        EventRegistration.objects.create(
            ticket=ticket, member=other, status=EventRegistration.Status.COMPLETED
        )
        url = reverse("event_detail", args=[self.event.id])
        self.assertContains(self.client.get(url), "Sold out")
        response = self.client.post(
            url, {"form_type": "register", "member": self.member.pk, "ticket": ticket.pk}, follow=True
        )
        self.assertContains(response, "Sorry, that ticket type just sold out.")
        self.assertFalse(EventRegistration.objects.filter(ticket=ticket, member=self.member).exists())
        self.assertEqual(ticket.registered_count, 1)

    def test_registering_twice_shows_an_info_message_and_does_not_duplicate(self):
        ticket = EventTicket.objects.create(event=self.event, name="General", price="0.00")
        url = reverse("event_detail", args=[self.event.id])
        self.client.post(url, {"form_type": "register", "member": self.member.id, "ticket": ticket.id})
        self.client.post(url, {"form_type": "register", "member": self.member.id, "ticket": ticket.id})
        self.assertEqual(EventRegistration.objects.filter(ticket=ticket, member=self.member).count(), 1)

    @override_settings(FLUTTERWAVE_SECRET_KEY="test-secret")
    @patch("events.views.initiate_payment")
    def test_registering_for_a_paid_ticket_with_payments_enabled_redirects_to_checkout(self, mock_initiate):
        mock_initiate.return_value = "https://checkout.flutterwave.com/fake-link"
        ticket = EventTicket.objects.create(event=self.event, name="Adult", price="150.00")
        response = self.client.post(
            reverse("event_detail", args=[self.event.id]),
            {"form_type": "register", "member": self.member.id, "ticket": ticket.id},
        )
        self.assertRedirects(response, "https://checkout.flutterwave.com/fake-link", fetch_redirect_response=False)
        registration = EventRegistration.objects.get(ticket=ticket, member=self.member)
        self.assertEqual(registration.status, EventRegistration.Status.PENDING)
        self.assertTrue(registration.payment_reference)

    @override_settings(FLUTTERWAVE_SECRET_KEY="test-secret")
    @patch("events.views.initiate_payment")
    def test_flutterwave_error_starting_checkout_marks_registration_failed(self, mock_initiate):
        mock_initiate.side_effect = FlutterwaveError("could not reach Flutterwave")
        ticket = EventTicket.objects.create(event=self.event, name="Adult", price="150.00")
        self.client.post(
            reverse("event_detail", args=[self.event.id]),
            {"form_type": "register", "member": self.member.id, "ticket": ticket.id},
        )
        registration = EventRegistration.objects.get(ticket=ticket, member=self.member)
        self.assertEqual(registration.status, EventRegistration.Status.FAILED)


class EventRegistrationCallbackTests(TestCase):
    """
    Same shape as giving/tests.py's GivingCallbackTests: mocks the
    Flutterwave API entirely and exercises the callback view's own
    verify-then-trust logic directly against a registration that already
    has a payment_reference (as it would once a real checkout had started).
    """

    def setUp(self):
        event = Event.objects.create(
            title="Youth Retreat", start_datetime=timezone.now() + timezone.timedelta(days=10)
        )
        self.ticket = EventTicket.objects.create(event=event, name="Adult", price="150.00")
        self.member = Member.objects.create(first_name="Ama", last_name="Serwaa", email="ama@example.com")
        self.registration = EventRegistration.objects.create(
            ticket=self.ticket,
            member=self.member,
            status=EventRegistration.Status.PENDING,
            payment_reference="test-ref-123",
        )

    @patch("events.views.verify_payment")
    def test_verified_payment_marks_registration_completed(self, mock_verify):
        mock_verify.return_value = {
            "status": "success",
            "data": {"status": "successful", "amount": 150.0, "currency": "GHS", "tx_ref": self.registration.payment_reference},
        }
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.get(
                reverse("event_registration_callback"),
                {"status": "successful", "tx_ref": self.registration.payment_reference, "transaction_id": "12345"},
            )
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, EventRegistration.Status.COMPLETED)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    @patch("events.views.verify_payment")
    def test_mismatched_amount_preserves_reservation(self, mock_verify):
        mock_verify.return_value = {
            "status": "success",
            "data": {"status": "successful", "amount": 5.0, "currency": "GHS", "tx_ref": self.registration.payment_reference},  # wrong amount
        }
        self.client.get(
            reverse("event_registration_callback"),
            {"status": "successful", "tx_ref": self.registration.payment_reference, "transaction_id": "12345"},
        )
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, EventRegistration.Status.PENDING)
        self.assertTrue(self.registration.ticket.registered_count)
        self.assertEqual(len(mail.outbox), 0)

    def test_browser_cancellation_preserves_reservation(self):
        self.client.get(
            reverse("event_registration_callback"),
            {"status": "cancelled", "tx_ref": self.registration.payment_reference},
        )
        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, EventRegistration.Status.PENDING)
        self.assertTrue(self.registration.ticket.registered_count)
        self.assertEqual(len(mail.outbox), 0)


class CheckInViaQrServiceTests(TestCase):
    """Direct tests of the phone-matching check-in used by the QR check-in page below."""

    def setUp(self):
        self.event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=1)
        )
        self.member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")

    def test_checks_in_a_matching_member_for_the_specific_event(self):
        attendance, error = check_in_via_qr(event=self.event, phone="233244123456")
        self.assertIsNone(error)
        self.assertEqual(attendance.member, self.member)
        self.assertEqual(attendance.event, self.event)
        self.assertTrue(attendance.present)
        self.assertEqual(attendance.date, self.event.start_datetime.date())

    def test_no_matching_member_reports_the_specific_error(self):
        attendance, error = check_in_via_qr(event=self.event, phone="0209999999")
        self.assertIsNone(attendance)
        self.assertEqual(error, "no_matching_member")
        self.assertEqual(Attendance.objects.count(), 0)

    def test_scanning_twice_does_not_duplicate(self):
        check_in_via_qr(event=self.event, phone="0244123456")
        check_in_via_qr(event=self.event, phone="0244123456")
        self.assertEqual(Attendance.objects.filter(member=self.member, event=self.event).count(), 1)

    def test_does_not_collide_with_a_general_sms_checkin_for_the_same_day(self):
        # SMS check-in (members/services.py's record_sms_checkin) leaves
        # event=None; QR check-in ties the row to a specific event - the
        # unique_together on Attendance (which includes event) keeps these
        # from colliding, so both can exist for the same member/date.
        Attendance.objects.create(member=self.member, date=self.event.start_datetime.date(), present=True)
        check_in_via_qr(event=self.event, phone="0244123456")
        self.assertEqual(Attendance.objects.filter(member=self.member).count(), 2)

    def test_tags_attendance_with_the_given_service_time(self):
        service_time = EventServiceTime.objects.create(event=self.event, label="8:00 AM Service")
        attendance, error = check_in_via_qr(event=self.event, phone="0244123456", service_time=service_time)
        self.assertIsNone(error)
        self.assertEqual(attendance.service_time, service_time)


class MultiServiceEventTests(TestCase):
    """EventServiceTime - RSVPs and QR/kiosk attendance tagged to one specific service on a multi-service event."""

    def setUp(self):
        self.event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=1)
        )
        self.member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")

    def test_str_includes_the_event(self):
        service_time = EventServiceTime.objects.create(event=self.event, label="8:00 AM Service")
        self.assertEqual(str(service_time), f"8:00 AM Service - {self.event}")

    def test_rsvp_form_has_no_service_time_field_for_a_single_service_event(self):
        form = RSVPForm(event=self.event)
        self.assertNotIn("service_time", form.fields)

    def test_rsvp_form_offers_service_times_once_the_event_has_more_than_one(self):
        first = EventServiceTime.objects.create(event=self.event, label="8:00 AM Service")
        second = EventServiceTime.objects.create(event=self.event, label="10:30 AM Service")
        form = RSVPForm(event=self.event)
        self.assertIn("service_time", form.fields)
        self.assertEqual(set(form.fields["service_time"].queryset), {first, second})

    def test_rsvp_form_only_offers_this_events_own_service_times(self):
        other_event = Event.objects.create(title="Wednesday Bible Study", start_datetime=timezone.now())
        EventServiceTime.objects.create(event=other_event, label="7:00 PM")
        EventServiceTime.objects.create(event=self.event, label="8:00 AM Service")
        form = RSVPForm(event=self.event)
        self.assertEqual(form.fields["service_time"].queryset.count(), 1)

    def test_rsvp_saved_with_a_service_time_via_event_detail(self):
        service_time = EventServiceTime.objects.create(event=self.event, label="8:00 AM Service")
        login_member(self.client, self.member)
        response = self.client.post(
            reverse("event_detail", args=[self.event.id]),
            {"form_type": "rsvp", "member": self.member.id, "status": "going", "service_time": service_time.id},
        )
        self.assertEqual(response.status_code, 302)
        rsvp = RSVP.objects.get(event=self.event, member=self.member)
        self.assertEqual(rsvp.service_time, service_time)

    def test_qr_checkin_form_has_no_service_time_field_for_a_single_service_event(self):
        form = QrCheckinForm(event=self.event)
        self.assertNotIn("service_time", form.fields)

    def test_qr_checkin_tags_attendance_with_the_chosen_service_time(self):
        service_time = EventServiceTime.objects.create(event=self.event, label="8:00 AM Service")
        response = self.client.post(
            reverse("event_qr_checkin", args=[self.event.id]),
            {"phone": "0244123456", "service_time": service_time.id},
        )
        self.assertEqual(response.status_code, 200)
        attendance = Attendance.objects.get(member=self.member, event=self.event)
        self.assertEqual(attendance.service_time, service_time)

    def test_kiosk_checkin_tags_attendance_with_the_chosen_service_time(self):
        service_time = EventServiceTime.objects.create(event=self.event, label="8:00 AM Service")
        response = self.client.post(
            reverse("event_kiosk_checkin", args=[self.event.id]),
            {"phone": "0244123456", "service_time": service_time.id},
        )
        self.assertEqual(response.status_code, 200)
        attendance = Attendance.objects.get(member=self.member, event=self.event)
        self.assertEqual(attendance.service_time, service_time)


class EventQrCheckinViewTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=1)
        )
        self.member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")

    def test_get_shows_the_checkin_form_with_no_login_required(self):
        response = self.client.get(reverse("event_qr_checkin", args=[self.event.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Check In")

    def test_post_with_a_matching_phone_checks_in_and_shows_success(self):
        response = self.client.post(
            reverse("event_qr_checkin", args=[self.event.id]), {"phone": "0244123456"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "checked in")
        self.assertTrue(Attendance.objects.filter(member=self.member, event=self.event, present=True).exists())

    def test_post_with_an_unmatched_phone_shows_the_not_found_message(self):
        response = self.client.post(
            reverse("event_qr_checkin", args=[self.event.id]), {"phone": "0209999999"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "to a member on file")
        self.assertEqual(Attendance.objects.count(), 0)


class EventKioskCheckinViewTests(TestCase):
    """The large-button, no-navigation kiosk check-in page."""

    def setUp(self):
        self.event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=1)
        )
        self.member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")

    def test_get_shows_the_kiosk_form_with_no_login_required(self):
        response = self.client.get(reverse("event_kiosk_checkin", args=[self.event.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Check In")
        self.assertNotContains(response, "<nav>")  # no site navigation on the kiosk page

    def test_post_with_a_matching_phone_checks_in_and_shows_success(self):
        response = self.client.post(
            reverse("event_kiosk_checkin", args=[self.event.id]), {"phone": "0244123456"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "checked in")
        self.assertTrue(Attendance.objects.filter(member=self.member, event=self.event, present=True).exists())

    def test_post_with_an_unmatched_phone_shows_the_not_found_message(self):
        response = self.client.post(
            reverse("event_kiosk_checkin", args=[self.event.id]), {"phone": "0209999999"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "couldn't find that number")
        self.assertEqual(Attendance.objects.count(), 0)

    def test_result_page_auto_refreshes_back_to_a_blank_kiosk(self):
        response = self.client.post(
            reverse("event_kiosk_checkin", args=[self.event.id]), {"phone": "0244123456"}
        )
        self.assertContains(response, "http-equiv=\"refresh\"")


class EventQrCodeViewTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=1)
        )

    def test_returns_a_png_image_with_no_login_required(self):
        response = self.client.get(reverse("event_qr_code", args=[self.event.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))
