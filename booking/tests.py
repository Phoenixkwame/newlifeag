from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from members.models import Member

from .models import Resource, ResourceBooking
from .services import conflicting_bookings


def _dt(*args):
    return timezone.make_aware(datetime(*args))


class ResourceModelTests(TestCase):
    def test_str_is_the_resource_name(self):
        resource = Resource.objects.create(name="Main Sanctuary")
        self.assertEqual(str(resource), "Main Sanctuary")

    def test_default_type_is_room(self):
        resource = Resource.objects.create(name="Main Sanctuary")
        self.assertEqual(resource.resource_type, Resource.ResourceType.ROOM)


class ResourceBookingModelTests(TestCase):
    def setUp(self):
        self.resource = Resource.objects.create(name="Conference Room")

    def test_overlaps_true_for_an_overlapping_window(self):
        booking = ResourceBooking.objects.create(
            resource=self.resource, title="Meeting", start_datetime=_dt(2026, 5, 1, 9, 0), end_datetime=_dt(2026, 5, 1, 11, 0)
        )
        self.assertTrue(booking.overlaps(_dt(2026, 5, 1, 10, 0), _dt(2026, 5, 1, 12, 0)))

    def test_overlaps_false_for_a_non_overlapping_window(self):
        booking = ResourceBooking.objects.create(
            resource=self.resource, title="Meeting", start_datetime=_dt(2026, 5, 1, 9, 0), end_datetime=_dt(2026, 5, 1, 11, 0)
        )
        self.assertFalse(booking.overlaps(_dt(2026, 5, 1, 11, 0), _dt(2026, 5, 1, 12, 0)))


class ConflictingBookingsTests(TestCase):
    def setUp(self):
        self.resource = Resource.objects.create(name="Conference Room")
        self.other_resource = Resource.objects.create(name="Youth Hall")
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        self.booking = ResourceBooking.objects.create(
            resource=self.resource,
            title="Deacons Meeting",
            booked_by=self.member,
            start_datetime=_dt(2026, 5, 1, 9, 0),
            end_datetime=_dt(2026, 5, 1, 11, 0),
        )

    def test_finds_an_overlapping_booking_on_the_same_resource(self):
        conflicts = conflicting_bookings(self.resource, _dt(2026, 5, 1, 10, 0), _dt(2026, 5, 1, 12, 0))
        self.assertIn(self.booking, conflicts)

    def test_ignores_a_non_overlapping_time(self):
        conflicts = conflicting_bookings(self.resource, _dt(2026, 5, 1, 11, 0), _dt(2026, 5, 1, 12, 0))
        self.assertNotIn(self.booking, conflicts)

    def test_ignores_a_different_resource_entirely(self):
        conflicts = conflicting_bookings(self.other_resource, _dt(2026, 5, 1, 9, 0), _dt(2026, 5, 1, 11, 0))
        self.assertEqual(conflicts.count(), 0)

    def test_exclude_booking_id_ignores_itself(self):
        conflicts = conflicting_bookings(
            self.resource, _dt(2026, 5, 1, 9, 0), _dt(2026, 5, 1, 11, 0), exclude_booking_id=self.booking.id
        )
        self.assertNotIn(self.booking, conflicts)
