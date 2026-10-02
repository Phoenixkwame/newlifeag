from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from members.models import Member

from .models import Testimony
from .services import approve_testimony


class TestimonyModelTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Yaa", last_name="Darko")

    def test_str_includes_member_and_date(self):
        testimony = Testimony.objects.create(member=self.member, testimony_text="God healed my mother.")
        self.assertIn("Yaa Darko", str(testimony))
        self.assertIn(str(testimony.created_at.date()), str(testimony))

    def test_is_approved_defaults_to_false(self):
        testimony = Testimony.objects.create(member=self.member, testimony_text="God healed my mother.")
        self.assertFalse(testimony.is_approved)

    def test_shows_up_on_the_member(self):
        testimony = Testimony.objects.create(member=self.member, testimony_text="God healed my mother.")
        self.assertIn(testimony, self.member.testimonies.all())


class SubmitTestimonyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testify-er", password="test-pass-123")
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu", user=self.user)

    def test_member_can_submit_a_testimony(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("submit_testimony"), {"testimony_text": "God provided a new job."})
        self.assertEqual(response.status_code, 302)
        testimony = Testimony.objects.get(member=self.member)
        self.assertEqual(testimony.testimony_text, "God provided a new job.")
        self.assertFalse(testimony.is_approved)

    def test_submitted_testimony_does_not_appear_on_the_wall_until_approved(self):
        self.client.force_login(self.user)
        self.client.post(reverse("submit_testimony"), {"testimony_text": "God provided a new job."})
        response = self.client.get(reverse("testimony_wall"))
        self.assertNotContains(response, "God provided a new job.")

    def test_user_without_member_profile_is_redirected(self):
        no_profile_user = User.objects.create_user(username="noprofile-testi", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(
            self.client.post(reverse("submit_testimony"), {"testimony_text": "God is good."}),
            reverse("dashboard"),
        )


class TestimonyWallTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah")

    def test_approved_testimony_appears_on_the_wall(self):
        Testimony.objects.create(member=self.member, testimony_text="God healed my father.", is_approved=True)
        response = self.client.get(reverse("testimony_wall"))
        self.assertContains(response, "God healed my father.")

    def test_unapproved_testimony_does_not_appear_on_the_wall(self):
        Testimony.objects.create(member=self.member, testimony_text="Still waiting on God.", is_approved=False)
        response = self.client.get(reverse("testimony_wall"))
        self.assertNotContains(response, "Still waiting on God.")

    def test_name_is_hidden_unless_shared(self):
        Testimony.objects.create(
            member=self.member, testimony_text="God provided.", is_approved=True, share_name_publicly=False
        )
        response = self.client.get(reverse("testimony_wall"))
        self.assertContains(response, "A church member")
        self.assertNotContains(response, "Kojo Mensah")

    def test_name_is_shown_when_shared(self):
        Testimony.objects.create(
            member=self.member, testimony_text="God provided a new job.", is_approved=True, share_name_publicly=True
        )
        response = self.client.get(reverse("testimony_wall"))
        self.assertContains(response, "Kojo Mensah")


class ApproveTestimonyServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pastor-testi2", password="test-pass-123")
        self.member = Member.objects.create(first_name="Yaa", last_name="Darko")

    def test_approves_and_returns_true(self):
        testimony = Testimony.objects.create(member=self.member, testimony_text="God healed my mother.")
        result = approve_testimony(testimony, user=self.user)
        testimony.refresh_from_db()
        self.assertTrue(result)
        self.assertTrue(testimony.is_approved)
        self.assertIsNotNone(testimony.approved_at)

    def test_approving_twice_is_a_no_op_the_second_time(self):
        testimony = Testimony.objects.create(member=self.member, testimony_text="God healed my mother.")
        approve_testimony(testimony, user=self.user)
        result = approve_testimony(testimony, user=self.user)
        self.assertFalse(result)
