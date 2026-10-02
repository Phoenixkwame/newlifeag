from django.test import TestCase
from django.utils import timezone

from followup.models import FollowUp
from members.models import Member

from .models import Decision
from .services import record_decision


class DecisionModelTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kwesi", last_name="Adjei")

    def test_str_includes_member_type_and_date(self):
        decision = Decision.objects.create(
            member=self.member, decision_type=Decision.DecisionType.SALVATION, date=timezone.localdate()
        )
        text = str(decision)
        self.assertIn("Kwesi Adjei", text)
        self.assertIn("Salvation", text)

    def test_a_member_can_have_more_than_one_decision(self):
        Decision.objects.create(
            member=self.member, decision_type=Decision.DecisionType.SALVATION, date=timezone.localdate()
        )
        Decision.objects.create(
            member=self.member, decision_type=Decision.DecisionType.REDEDICATION, date=timezone.localdate()
        )
        self.assertEqual(self.member.decisions.count(), 2)


class RecordDecisionServiceTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Ama", last_name="Boateng")

    def test_creates_a_decision(self):
        decision = record_decision(self.member, decision_type=Decision.DecisionType.SALVATION)
        self.assertEqual(decision.member, self.member)
        self.assertEqual(decision.decision_type, Decision.DecisionType.SALVATION)

    def test_a_first_time_salvation_decision_starts_a_follow_up(self):
        record_decision(self.member, decision_type=Decision.DecisionType.SALVATION)
        self.assertTrue(FollowUp.objects.filter(member=self.member).exists())

    def test_a_rededication_does_not_start_a_follow_up(self):
        record_decision(self.member, decision_type=Decision.DecisionType.REDEDICATION)
        self.assertFalse(FollowUp.objects.filter(member=self.member).exists())

    def test_defaults_to_todays_date(self):
        decision = record_decision(self.member, decision_type=Decision.DecisionType.SALVATION)
        self.assertEqual(decision.date, timezone.localdate())
