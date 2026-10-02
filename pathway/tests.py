from django.contrib.auth.models import User
from django.test import TestCase

from members.models import Member

from .models import MemberPathwayProgress, PathwayStep
from .services import mark_step_complete, mark_step_incomplete, progress_for_member


class PathwayStepModelTests(TestCase):
    def test_str_is_the_step_name(self):
        step = PathwayStep.objects.create(name="Water Baptism")
        self.assertEqual(str(step), "Water Baptism")

    def test_steps_are_ordered_by_order_then_name(self):
        PathwayStep.objects.create(name="Membership Class", order=2)
        PathwayStep.objects.create(name="New Believers Class", order=1)
        names = list(PathwayStep.objects.values_list("name", flat=True))
        self.assertEqual(names, ["New Believers Class", "Membership Class"])


class MemberPathwayProgressModelTests(TestCase):
    def test_is_completed_is_false_without_a_completed_date(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        step = PathwayStep.objects.create(name="Water Baptism")
        progress = MemberPathwayProgress.objects.create(member=member, step=step)
        self.assertFalse(progress.is_completed)

    def test_one_progress_row_per_member_per_step(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        step = PathwayStep.objects.create(name="Water Baptism")
        MemberPathwayProgress.objects.create(member=member, step=step)
        with self.assertRaises(Exception):
            MemberPathwayProgress.objects.create(member=member, step=step)


class ProgressForMemberTests(TestCase):
    def test_a_step_with_no_progress_row_shows_as_not_completed(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        step = PathwayStep.objects.create(name="Water Baptism")
        results = progress_for_member(member)
        self.assertEqual(results, [(step, None)])

    def test_returns_every_step_in_order_paired_with_its_progress(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        step1 = PathwayStep.objects.create(name="New Believers Class", order=1)
        step2 = PathwayStep.objects.create(name="Water Baptism", order=2)
        progress1 = MemberPathwayProgress.objects.create(member=member, step=step1, completed_date="2026-01-01")
        results = progress_for_member(member)
        self.assertEqual(results, [(step1, progress1), (step2, None)])

    def test_a_different_members_progress_never_leaks_in(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        other_member = Member.objects.create(first_name="Ama", last_name="Boateng")
        step = PathwayStep.objects.create(name="Water Baptism")
        MemberPathwayProgress.objects.create(member=other_member, step=step, completed_date="2026-01-01")
        results = progress_for_member(member)
        self.assertEqual(results, [(step, None)])


class MarkStepCompleteTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        self.step = PathwayStep.objects.create(name="Water Baptism")
        self.user = User.objects.create_user(username="marker", password="test-pass-123")

    def test_marks_a_step_complete_today(self):
        progress = mark_step_complete(self.member, self.step, user=self.user)
        self.assertTrue(progress.is_completed)
        self.assertEqual(progress.marked_by, self.user)

    def test_is_idempotent_for_an_already_completed_step(self):
        mark_step_complete(self.member, self.step, user=self.user)
        second_user = User.objects.create_user(username="marker2", password="test-pass-123")
        progress = mark_step_complete(self.member, self.step, user=second_user)
        self.assertEqual(MemberPathwayProgress.objects.filter(member=self.member, step=self.step).count(), 1)
        self.assertEqual(progress.marked_by, second_user)

    def test_mark_incomplete_clears_the_completed_date_without_deleting_the_row(self):
        mark_step_complete(self.member, self.step, user=self.user)
        result = mark_step_incomplete(self.member, self.step)
        self.assertTrue(result)
        progress = MemberPathwayProgress.objects.get(member=self.member, step=self.step)
        self.assertFalse(progress.is_completed)

    def test_mark_incomplete_on_a_never_started_step_does_nothing_and_returns_false(self):
        result = mark_step_incomplete(self.member, self.step)
        self.assertFalse(result)
        self.assertFalse(MemberPathwayProgress.objects.filter(member=self.member, step=self.step).exists())
