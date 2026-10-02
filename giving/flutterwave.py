"""
A small, direct client for the Flutterwave payments API - just the two
calls this app needs. See https://developer.flutterwave.com/docs for the
full API reference.

Get test API keys by creating a free account at https://dashboard.flutterwave.com/signup,
then find them under Settings > API Keys. Test keys start with FLWSECK_TEST-
and FLWPUBK_TEST- - use those while developing. Switch to the live keys
only once you're ready to accept real payments.
"""

import secrets

import requests
from django.conf import settings

FLW_BASE_URL = "https://api.flutterwave.com/v3"
REQUEST_TIMEOUT = 15  # seconds


class FlutterwaveError(Exception):
    """Raised when Flutterwave rejects a request or can't be reached."""


def initiate_payment(*, tx_ref, amount, email, redirect_url, name="", phone="", description="", meta=None):
    """Ask Flutterwave for a hosted payment page link for this transaction."""
    if not settings.FLUTTERWAVE_SECRET_KEY:
        raise FlutterwaveError("FLUTTERWAVE_SECRET_KEY is not configured.")

    try:
        response = requests.post(
            f"{FLW_BASE_URL}/payments",
            json={
                "tx_ref": tx_ref,
                "amount": str(amount),
                "currency": "GHS",
                "redirect_url": redirect_url,
                # Card and Ghana Mobile Money (MTN, Telecel, AirtelTigo).
                "payment_options": "card,mobilemoneyghana",
                "customer": {"email": email, "name": name, "phonenumber": phone},
                "customizations": {
                    "title": "Newlife AG",
                    "description": description or "Church giving",
                },
                "meta": meta or {},
            },
            headers={"Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}"},
            timeout=REQUEST_TIMEOUT,
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise FlutterwaveError(f"Could not reach Flutterwave: {exc}") from exc

    if data.get("status") != "success":
        raise FlutterwaveError(data.get("message", "Flutterwave could not start this payment."))

    return data["data"]["link"]


def verify_payment(transaction_id):
    """
    Ask Flutterwave to confirm what actually happened for a transaction id.

    Never trust the status/amount that comes back in the browser redirect -
    always re-check with this server-to-server call before marking a
    donation as completed.
    """
    try:
        response = requests.get(
            f"{FLW_BASE_URL}/transactions/{transaction_id}/verify",
            headers={"Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}"},
            timeout=REQUEST_TIMEOUT,
        )
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise FlutterwaveError(f"Could not verify payment with Flutterwave: {exc}") from exc


def webhook_signature_valid(request):
    """
    Flutterwave signs each webhook by echoing back the "Secret hash" set in
    the dashboard (Settings > Webhooks) in a verif-hash header. Anything
    without the right hash is rejected - and even a correctly signed webhook
    is only treated as a hint: callers still re-verify the transaction with
    verify_payment() before trusting it.
    """
    expected = settings.FLUTTERWAVE_WEBHOOK_HASH
    if not expected:
        return False
    supplied = request.headers.get("verif-hash", "")
    return secrets.compare_digest(supplied.encode(), expected.encode())
