import secrets
from functools import wraps

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


def authenticated_sms_webhook(view):
    """Accept only POSTs from the configured SMS provider or trusted gateway."""
    @csrf_exempt
    @require_POST
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        expected = settings.SMS_WEBHOOK_TOKEN
        if not expected:
            return HttpResponse("SMS intake is not configured.", status=503)
        supplied = request.headers.get("X-SMS-Webhook-Token", "")
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            return HttpResponse("Unauthorized", status=403)
        return view(request, *args, **kwargs)
    return wrapped
