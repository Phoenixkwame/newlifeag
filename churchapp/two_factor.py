"""
Two-factor login for staff accounts: after a staff member (is_staff=True)
enters the right username/password, they aren't logged in immediately -
instead a 6-digit code is emailed to them and they're sent to
verify_login_code to enter it before the login actually completes. An
ordinary member's login is completely unaffected - see
StaffTwoFactorLoginView.form_valid below, which only intercepts is_staff
accounts.

The code is stored in the session, not a database model: it's short-lived
(CODE_EXPIRY_MINUTES), single-use, and never needs to be looked up by
anything other than the one request that's completing this one login, so a
session key is enough and needs no migration. Email rather than SMS,
mirroring the existing "forgot password" reset flow (see
registration/password_reset_form.html) - it works out of the box with zero
setup while DEBUG=True (EMAIL_BACKEND prints to the console, see
settings.py), whereas SMS needs Hubtel credentials many dev/staging
environments won't have configured (see churchapp/sms.py).

A staff account without an email address cannot complete login. An
administrator must add an email address so the code can be delivered;
missing contact details never bypass the second factor.
"""

import logging
import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.contrib.auth import views as auth_views

from .forms import LoginCodeForm

logger = logging.getLogger(__name__)

CODE_EXPIRY_MINUTES = 10

# Session keys used to carry a pending login across the two requests
# (password step, then code step) without a database model.
SESSION_USER_ID = "2fa_user_id"
SESSION_CODE = "2fa_code"
SESSION_EXPIRES = "2fa_expires"
SESSION_NEXT = "2fa_next"
SESSION_CHALLENGE = "2fa_challenge"
SESSION_AUTH_HASH = "2fa_auth_hash"
MAX_CODE_ATTEMPTS = 5


def generate_login_code():
    """A cryptographically random 6-digit string, e.g. "042917" - zero-padded, so it's always 6 digits long."""
    return f"{secrets.randbelow(1_000_000):06d}"


def send_login_code(user, code):
    """
    Best-effort, same "never raises, just logs and returns False" pattern as
    churchapp/sms.py's send_sms and every notifications.py in this project.
    Returns False (without trying to send anything) if the user has no
    email on file. StaffTwoFactorLoginView blocks login when an address is
    missing or the code cannot be sent.
    """
    if not user.email:
        return False

    subject = "Your Newlife AG staff login code"
    message = (
        f"Your login code is: {code}\n\n"
        f"This code expires in {CODE_EXPIRY_MINUTES} minutes and can only be used once. "
        "If you didn't just try to log in, you can safely ignore this email."
    )
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        return True
    except Exception:
        logger.exception("Couldn't send the staff login code email to %s.", user.email)
        return False


def _clear_pending_login(request):
    for key in (SESSION_USER_ID, SESSION_CODE, SESSION_EXPIRES, SESSION_NEXT, SESSION_CHALLENGE, SESSION_AUTH_HASH):
        request.session.pop(key, None)


class StaffTwoFactorLoginView(auth_views.LoginView):
    """
    Drop-in replacement for django.contrib.auth.views.LoginView (see
    churchapp/urls.py's "accounts/login/") - behaves identically for an
    ordinary member. Staff credentials require an emailed code before
    login can finish; an account without an email address is blocked.
    """

    def form_valid(self, form):
        from members.models import StaffLoginAttempt

        user = form.get_user()
        _clear_pending_login(self.request)
        if user.is_staff:
            if not user.email:
                form.add_error(None, "Staff login requires an email address. Please contact an administrator.")
                return self.form_invalid(form)
            now = timezone.now()
            token = secrets.token_hex(32)
            with transaction.atomic():
                attempt, _ = StaffLoginAttempt.objects.select_for_update().get_or_create(
                    user=user, defaults={"token": token, "started_at": now},
                )
                if now >= attempt.started_at + timedelta(minutes=CODE_EXPIRY_MINUTES):
                    attempt.failures = 0
                    attempt.started_at = now
                if attempt.failures >= MAX_CODE_ATTEMPTS:
                    form.add_error(None, "Too many incorrect codes. Please wait ten minutes before trying again.")
                    return self.form_invalid(form)
                attempt.token = token
                attempt.consumed = False
                attempt.save()
            success_url = self.get_success_url()
            code = generate_login_code()
            self.request.session.cycle_key()
            self.request.session[SESSION_CHALLENGE] = token
            self.request.session[SESSION_AUTH_HASH] = user.get_session_auth_hash()
            self.request.session[SESSION_USER_ID] = user.id
            self.request.session[SESSION_CODE] = code
            self.request.session[SESSION_EXPIRES] = (
                timezone.now() + timedelta(minutes=CODE_EXPIRY_MINUTES)
            ).isoformat()
            self.request.session[SESSION_NEXT] = success_url
            if not send_login_code(user, code):
                _clear_pending_login(self.request)
                form.add_error(None, "We couldn't send your login code. Please try again later.")
                return self.form_invalid(form)
            return redirect("verify_login_code")
        return super().form_valid(form)


def verify_login_code(request):
    """
    The second step of StaffTwoFactorLoginView above - reached only via the
    redirect it issues, never linked to directly. A GET with no pending
    login in the session (nothing to verify, or the session's since
    expired/been cleared) just sends the user back to the login page rather
    than showing a confusing empty form.
    """
    user_id = request.session.get(SESSION_USER_ID)
    if not user_id:
        return redirect("login")

    if request.method == "POST":
        from members.models import StaffLoginAttempt

        form = LoginCodeForm(request.POST)
        with transaction.atomic():
            attempt = StaffLoginAttempt.objects.select_for_update().filter(
                user_id=user_id, token=request.session.get(SESSION_CHALLENGE), consumed=False,
            ).first()
            if attempt is None or attempt.failures >= MAX_CODE_ATTEMPTS:
                _clear_pending_login(request)
                return redirect("login")
            expires = datetime.fromisoformat(request.session[SESSION_EXPIRES])
            if timezone.now() > expires:
                messages.error(request, "That code has expired. Please log in again.")
                _clear_pending_login(request)
                return redirect("login")

            if not form.is_valid() or not secrets.compare_digest(form.cleaned_data["code"], request.session.get(SESSION_CODE, "")):
                attempt.failures += 1
                attempt.save(update_fields=["failures"])
                if attempt.failures >= MAX_CODE_ATTEMPTS:
                    _clear_pending_login(request)
                    messages.error(request, "Too many incorrect codes. Please wait ten minutes before trying again.")
                    return redirect("login")
                messages.error(request, "That code wasn't right. Please try again.")
            else:
                User = get_user_model()
                try:
                    user = User.objects.get(id=user_id, is_active=True, is_staff=True)
                except User.DoesNotExist:
                    _clear_pending_login(request)
                    return redirect("login")
                if not secrets.compare_digest(user.get_session_auth_hash(), request.session.get(SESSION_AUTH_HASH, "")):
                    _clear_pending_login(request)
                    return redirect("login")
                attempt.consumed = True
                attempt.failures = 0
                attempt.save(update_fields=["consumed", "failures"])
                next_url = request.session.get(SESSION_NEXT) or settings.LOGIN_REDIRECT_URL
                _clear_pending_login(request)
                login(request, user)
                return redirect(next_url)
    else:
        form = LoginCodeForm()

    return render(request, "registration/verify_login_code.html", {"form": form})
