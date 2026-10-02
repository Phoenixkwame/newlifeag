from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path, reverse_lazy
from django.views.static import serve

from . import views
from .two_factor import StaffTwoFactorLoginView, verify_login_code

admin.site.site_header = "Newlife AG Administration"
admin.site.site_title = "Newlife AG Admin"
admin.site.index_title = "Manage your church's data"

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/login/", StaffTwoFactorLoginView.as_view(template_name="registration/login.html", next_page="admin:index")),
    path("admin/", admin.site.urls),
    # Django's built-in set_language view (a POST target, see the language
    # switcher form in templates/base.html) - saves the chosen language to
    # the session/cookie so LocaleMiddleware picks it up on every later
    # request. No language-prefixed URLs (no i18n_patterns) - every URL in
    # this project keeps its existing path either way.
    path("i18n/", include("django.conf.urls.i18n")),
    path("events/", include("events.urls")),
    path("members/", include("members.urls")),
    path("sermons/", include("sermons.urls")),
    path("give/", include("giving.urls")),
    path("prayer/", include("prayer.urls")),
    path("connect/", include("followup.urls")),
    path("care/", include("care.urls")),
    path("maintenance/", include("maintenance.urls")),
    path("service-hours/", include("servicehours.urls")),
    path("watch/", include("livestream.urls")),
    path("suggestions/", include("suggestions.urls")),
    path("testimonies/", include("testimonies.urls")),
    path("staff/", include("staff.urls")),
    path("accounts/login/", StaffTwoFactorLoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/verify-code/", verify_login_code, name="verify_login_code"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "accounts/password-reset/",
        auth_views.PasswordResetView.as_view(template_name="registration/password_reset_form.html"),
        name="password_reset",
    ),
    path(
        "accounts/password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html"),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    # A logged-in member changing their own known password - separate from
    # the "forgot password" reset flow above, and linked from the new
    # account settings page (members/views.py's account_settings).
    path(
        "accounts/password-change/",
        auth_views.PasswordChangeView.as_view(
            template_name="registration/password_change_form.html",
            success_url=reverse_lazy("password_change_done"),
        ),
        name="password_change",
    ),
    path(
        "accounts/password-change/done/",
        auth_views.PasswordChangeDoneView.as_view(template_name="registration/password_change_done.html"),
        name="password_change_done",
    ),
]

if settings.DEBUG:
    # Serves uploaded member photos locally, the same way collectstatic'd
    # static files are served in production by WhiteNoise - this helper is
    # for local development only and is a no-op (returns []) when DEBUG is
    # off, so it's safe to leave in. See settings.py's MEDIA_ROOT comment
    # for what to use for uploads in production.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVE_MEDIA:
    # Production without separate file storage (e.g. a Render disk) - the
    # app serves uploads itself. static() above refuses to when DEBUG is off.
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
