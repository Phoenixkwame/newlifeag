import re

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client, TestCase
from django.urls import reverse


class LogoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="logout-member")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def test_navigation_logout_forms_end_session_and_redirect_to_login(self):
        for page in ("home", "watch_online"):
            with self.subTest(page=page):
                self.client.force_login(self.user)
                response = self.client.get(reverse(page))
                forms = re.findall(
                    r'<form class="logout-form" method="post" action="([^"]+)">(.*?)</form>',
                    response.content.decode(), re.S,
                )
                self.assertTrue(forms)
                action, body = forms[0]
                self.assertEqual(action, reverse("logout"))
                token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', body).group(1)
                response = self.client.post(action, {"csrfmiddlewaretoken": token})
                self.assertRedirects(response, reverse("login"))
                self.assertNotIn(SESSION_KEY, self.client.session)

    def test_get_does_not_log_out(self):
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertIn(SESSION_KEY, self.client.session)

    def test_post_without_csrf_does_not_log_out(self):
        self.assertEqual(self.client.post(reverse("logout")).status_code, 403)
        self.assertIn(SESSION_KEY, self.client.session)
