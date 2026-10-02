"""
Django settings for the churchapp project.

This is a starter configuration meant for local development. Before
deploying anywhere public, see the "Going to production" section of the
README for the changes you must make (SECRET_KEY, DEBUG, ALLOWED_HOSTS,
database, static files).
"""

import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep this value secret in production.
# Reads from the DJANGO_SECRET_KEY environment variable when set (e.g. in
# production), and falls back to an insecure default for local development
# only. Generate a real one for production with:
#   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-REPLACE-ME-BEFORE-DEPLOYING")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
# Render sets this to the site's own *.onrender.com address automatically,
# so the default URL works without having to set DJANGO_ALLOWED_HOSTS by hand.
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
if not DEBUG:
    if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith("django-insecure-"):
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to a strong random secret before disabling DEBUG.")
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS to your production host names.")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local apps
    "members",
    "events",
    "sermons",
    "giving",
    "prayer",
    "checkin",
    "followup",
    "announcements",
    "pathway",
    "booking",
    "care",
    "surveys",
    "milestones",
    "decisions",
    "screening",
    "maintenance",
    "servicehours",
    "expenses",
    "equipment",
    "library",
    "governance",
    "livestream",
    "suggestions",
    "testimonies",
    "flyers",
    "staff",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Must come after SessionMiddleware (it can read the language from the
    # session) and before CommonMiddleware (which needs the active language
    # already resolved) - this is Django's own documented ordering. It picks
    # the active language from, in order: a saved session value, the
    # django_language cookie (set by the language switcher in base.html via
    # Django's built-in set_language view - see churchapp/urls.py's
    # "i18n/" include), the browser's Accept-Language header, then falls
    # back to LANGUAGE_CODE below. No URL path prefix is used (no
    # i18n_patterns) - every existing URL in this project keeps working
    # unchanged, in either language.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "churchapp.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
            ],
        },
    },
]

WSGI_APPLICATION = "churchapp.wsgi.application"


# Database
# Local development uses SQLite with zero setup. In production, set the
# DATABASE_URL environment variable (most hosts - Render, Railway, Heroku -
# provide a managed Postgres instance and set this for you automatically),
# and it's used instead. Format:
#   postgres://USER:PASSWORD@HOST:PORT/DBNAME
_database_url = os.environ.get("DATABASE_URL")
if _database_url:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(_database_url, conn_max_age=600)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Accra"
USE_I18N = True
USE_TZ = True

# Twi/English toggle on the public pages (see the language switcher in
# templates/base.html) - "tw" is Twi's real ISO 639-1 code. Translated
# strings live in locale/tw/LC_MESSAGES/django.po (compiled to django.mo);
# LOCALE_PATHS points Django at this project's own locale/ directory since
# there's no per-app locale/ folder split here.
LANGUAGES = [
    ("en", "English"),
    ("tw", "Twi"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

# Static files - served directly by the app via WhiteNoise, so no separate
# web server (nginx, etc.) is needed even in production. Run
# `python manage.py collectstatic` before deploying (it populates STATIC_ROOT).
#
# The "Manifest" storage below renames each static file with a content hash
# for cache-busting, but that only works once `collectstatic` has actually
# run and written a manifest file - which never happens in local development
# or in the test suite. Using it unconditionally would make any page that
# references a static file (including Django's own admin templates) crash
# with "Missing staticfiles manifest entry" until you'd run collectstatic -
# so it's only turned on once DEBUG is off (i.e. in production, where your
# deploy step runs collectstatic first).
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Member photo uploads. Locally and on a host with a persistent disk, this
# just works. IMPORTANT: most free/hobby hosting tiers (Render, Railway,
# Heroku) use an *ephemeral* filesystem - anything written here disappears
# on every redeploy or restart. Before relying on member photos in
# production, switch to real object storage (e.g. an S3-compatible bucket
# via django-storages) instead of this local-disk default.
MEDIA_URL = "media/"
# Override with MEDIA_ROOT to point at a persistent disk in production (e.g.
# a Render disk mounted at /var/data, with MEDIA_ROOT=/var/data/media).
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
# With DEBUG off, uploaded files are only served by the app itself when this
# is True - fine for a small church site; switch to object storage if
# traffic ever grows enough to need a CDN.
SERVE_MEDIA = os.environ.get("SERVE_MEDIA", "False") == "True"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "whitenoise.storage.CompressedStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CSRF needs to know your real domain(s) once deployed behind HTTPS, e.g.
# "https://newlifeag.org,https://www.newlifeag.org"
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

if not DEBUG:
    # Most hosts (Render, Railway, etc.) terminate HTTPS at a proxy in front
    # of the app, so Django needs this header to know the original request
    # was secure.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "3600"))

# Email - used for password reset links (and could send donation receipts
# later). Defaults to printing emails to the console in development, so
# password reset works out of the box with zero setup while DEBUG=True. Set
# real SMTP credentials via environment variables before going to production.
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True") == "True"
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@newlifeag.org")

# Where to send someone after logging in / when LoginRequiredMixin redirects them
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# Flutterwave (giving). Leave blank to keep the giving page in manual/pending
# mode. Get test keys at https://dashboard.flutterwave.com (Settings > API Keys) -
# they start with FLWSECK_TEST- / FLWPUBK_TEST-. Never commit real keys to
# source control; set these as real environment variables.
FLUTTERWAVE_SECRET_KEY = os.environ.get("FLUTTERWAVE_SECRET_KEY", "")
FLUTTERWAVE_PUBLIC_KEY = os.environ.get("FLUTTERWAVE_PUBLIC_KEY", "")
# The "Secret hash" you choose under Settings > Webhooks in the Flutterwave
# dashboard - point the webhook URL at https://<your-domain>/give/webhook/.
# Leave blank to disable the webhook (the browser callback still works).
FLUTTERWAVE_WEBHOOK_HASH = os.environ.get("FLUTTERWAVE_WEBHOOK_HASH", "")
# The giving page has its own switch, separate from the keys above (which
# event ticketing also uses): gifts are only recorded as pending for the
# finance team to follow up until this is set to True AND the keys are set.
GIVING_ONLINE_PAYMENTS = os.environ.get("GIVING_ONLINE_PAYMENTS", "False") == "True"

# SMS (Hubtel) - an extra channel alongside email for RSVP/volunteer
# confirmations and pending-gift alerts, since not every member checks email
# regularly. Leave all three blank to keep SMS off entirely (nothing breaks -
# see churchapp/sms.py). Get credentials at https://hubtel.com by creating a
# Quick SMS/SMS API app; HUBTEL_SENDER_ID is the short "from" name Hubtel
# approves for your account (max 11 characters, e.g. "NewlifeAG").
HUBTEL_CLIENT_ID = os.environ.get("HUBTEL_CLIENT_ID", "")
HUBTEL_CLIENT_SECRET = os.environ.get("HUBTEL_CLIENT_SECRET", "")
HUBTEL_SENDER_ID = os.environ.get("HUBTEL_SENDER_ID", "")
SMS_WEBHOOK_TOKEN = os.environ.get("SMS_WEBHOOK_TOKEN", "")

# The actual phone number/shortcode members text to give via SMS (see
# giving/views.py's sms_giving_webhook and "Text/SMS giving" in the README).
# Purely for display on the giving/campaign pages - Hubtel (or whichever
# provider) is configured separately, in their own dashboard, to forward
# incoming texts to that number to this app's webhook URL. Leave blank to
# hide the "text to give" hint entirely.
CHURCH_SMS_GIVING_NUMBER = os.environ.get("CHURCH_SMS_GIVING_NUMBER", "")
