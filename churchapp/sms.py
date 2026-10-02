"""
Minimal SMS sending via Hubtel's Quick SMS API (https://developers.hubtel.com/) -
a widely used Ghanaian SMS aggregator, so this works with local numbers
without needing an international SMS provider. Any other provider with a
simple HTTP API could be swapped in here without touching the call sites
below (events/notifications.py, giving/notifications.py) - they only ever
call send_sms().

Configured the same way as Flutterwave (see giving/flutterwave.py): stays
completely inert - not an error, just a no-op - until the environment
variables below are set, so the app works with zero SMS setup during
development and low-budget deployments, the same way email quietly falls
back to the console backend.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

HUBTEL_SEND_URL = "https://smsc.hubtel.com/v1/messages/send"
REQUEST_TIMEOUT = 10  # seconds


def sms_enabled():
    return bool(settings.HUBTEL_CLIENT_ID and settings.HUBTEL_CLIENT_SECRET and settings.HUBTEL_SENDER_ID)


def send_sms(to_phone, message):
    """
    Best-effort, like the email helpers in events/notifications.py and
    giving/notifications.py - never raises. Returns True only if SMS is
    configured, a phone number was given, and Hubtel accepted the message;
    False in every other case (not configured, no phone on file, or the
    request failed - which is logged, not raised, so a down SMS provider
    never blocks the RSVP/gift/etc. that triggered it).
    """
    if not sms_enabled() or not to_phone:
        return False

    try:
        response = requests.get(
            HUBTEL_SEND_URL,
            params={
                "clientid": settings.HUBTEL_CLIENT_ID,
                "clientsecret": settings.HUBTEL_CLIENT_SECRET,
                "from": settings.HUBTEL_SENDER_ID,
                "to": to_phone,
                "content": message,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception("Failed to send SMS to %s", to_phone)
        return False
