from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Suggestion
from .services import mark_reviewed


class SuggestionModelTests(TestCase):
    def test_str_includes_the_submitted_date(self):
        suggestion = Suggestion.objects.create(message="Please add more parking.")
        self.assertIn(str(suggestion.submitted_at.date()), str(suggestion))

    def test_is_reviewed_defaults_to_false(self):
        suggestion = Suggestion.objects.create(message="Please add more parking.")
        self.assertFalse(suggestion.is_reviewed)


class SubmitSuggestionTests(TestCase):
    def test_anyone_can_submit_without_logging_in(self):
        response = self.client.post(reverse("submit_suggestion"), {"message": "Please add more parking."})
        self.assertRedirects(response, reverse("suggestion_confirmation"))
        suggestion = Suggestion.objects.get()
        self.assertEqual(suggestion.message, "Please add more parking.")

    def test_submission_is_not_linked_to_the_logged_in_user_who_submitted_it(self):
        # Even a logged-in member's submission carries no trace back to
        # them - Suggestion has no member/user field at all to set.
        user = User.objects.create_user(username="submitter1", password="test-pass-123")
        self.client.force_login(user)
        self.client.post(reverse("submit_suggestion"), {"message": "Please add a Wednesday service."})
        suggestion = Suggestion.objects.get()
        self.assertFalse(hasattr(suggestion, "member"))
        self.assertFalse(hasattr(suggestion, "user"))

    def test_blank_message_is_rejected(self):
        response = self.client.post(reverse("submit_suggestion"), {"message": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Suggestion.objects.count(), 0)


class MarkReviewedServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pastor-sugg", password="test-pass-123")

    def test_marks_reviewed_and_returns_true(self):
        suggestion = Suggestion.objects.create(message="Please add more parking.")
        result = mark_reviewed(suggestion, user=self.user)
        suggestion.refresh_from_db()
        self.assertTrue(result)
        self.assertTrue(suggestion.is_reviewed)
        self.assertIsNotNone(suggestion.reviewed_at)

    def test_marking_twice_is_a_no_op_the_second_time(self):
        suggestion = Suggestion.objects.create(message="Please add more parking.")
        mark_reviewed(suggestion, user=self.user)
        result = mark_reviewed(suggestion, user=self.user)
        self.assertFalse(result)
