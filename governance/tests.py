from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from members.models import Member

from .models import ActionItem, Meeting


class MeetingModelTests(TestCase):
    def test_str_uses_the_title_and_date_when_a_title_is_set(self):
        meeting = Meeting.objects.create(date=timezone.localdate(), title="Monthly Elders Meeting")
        self.assertIn("Monthly Elders Meeting", str(meeting))
        self.assertIn(str(meeting.date), str(meeting))

    def test_str_falls_back_to_just_the_date_with_no_title(self):
        meeting = Meeting.objects.create(date=timezone.localdate())
        self.assertIn(str(meeting.date), str(meeting))

    def test_open_action_item_count_excludes_done_items(self):
        meeting = Meeting.objects.create(date=timezone.localdate())
        ActionItem.objects.create(meeting=meeting, description="Book the venue")
        done = ActionItem.objects.create(meeting=meeting, description="Send invites")
        done.mark_done(True)
        self.assertEqual(meeting.open_action_item_count, 1)

    def test_attendees_can_be_linked_to_existing_members(self):
        meeting = Meeting.objects.create(date=timezone.localdate())
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        meeting.attendees.add(member)
        self.assertIn(meeting, member.meetings_attended.all())


class ActionItemModelTests(TestCase):
    def setUp(self):
        self.meeting = Meeting.objects.create(date=timezone.localdate())

    def test_mark_done_stamps_completed_at(self):
        item = ActionItem.objects.create(meeting=self.meeting, description="Book the venue")
        self.assertIsNone(item.completed_at)
        item.mark_done(True)
        self.assertTrue(item.is_done)
        self.assertIsNotNone(item.completed_at)

    def test_mark_undone_clears_completed_at(self):
        item = ActionItem.objects.create(meeting=self.meeting, description="Book the venue")
        item.mark_done(True)
        item.mark_done(False)
        self.assertFalse(item.is_done)
        self.assertIsNone(item.completed_at)

    def test_is_overdue_true_for_a_past_due_date_not_yet_done(self):
        item = ActionItem.objects.create(
            meeting=self.meeting, description="Book the venue", due_date=timezone.localdate() - timedelta(days=1)
        )
        self.assertTrue(item.is_overdue)

    def test_is_overdue_false_once_marked_done(self):
        item = ActionItem.objects.create(
            meeting=self.meeting, description="Book the venue", due_date=timezone.localdate() - timedelta(days=1)
        )
        item.mark_done(True)
        self.assertFalse(item.is_overdue)

    def test_is_overdue_false_with_no_due_date(self):
        item = ActionItem.objects.create(meeting=self.meeting, description="Book the venue")
        self.assertFalse(item.is_overdue)

    def test_owner_can_be_a_member(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        item = ActionItem.objects.create(meeting=self.meeting, description="Book the venue", owner=member)
        self.assertIn(item, member.governance_action_items.all())
