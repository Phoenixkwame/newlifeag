"""Opt-in settings for fast, isolated tests; never use to run the website.

    python manage.py test --settings=churchapp.fast_test_settings

Only test password hashing is changed. Application authentication, permissions,
webhook checks, and payment verification still run normally.
"""
from .settings import *  # noqa: F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
