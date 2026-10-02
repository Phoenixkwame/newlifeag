"""
Check-in/check-out logic pulled out of the view so the pickup-code matching
(the actual safety check this feature exists for) can be tested directly,
independent of form validation or HTTP plumbing.
"""

import random

from django.utils import timezone

from .models import CheckIn


class WrongPickupCodeError(Exception):
    """Raised when a check-out is attempted with a code that doesn't match."""


def _generate_pickup_code():
    """
    A random 4-digit code, unique among currently-checked-in children (not
    globally unique across all history) - that's all that matters, since a
    code only ever needs to distinguish between kids who are *currently*
    on the floor waiting to be picked up.
    """
    while True:
        code = f"{random.randint(0, 9999):04d}"
        if not CheckIn.objects.filter(pickup_code=code, checked_out_at__isnull=True).exists():
            return code


def check_in_child(child, *, event=None, guardian_name, user, notes=""):
    """Creates a CheckIn with a freshly generated pickup code."""
    return CheckIn.objects.create(
        child=child,
        event=event,
        guardian_name=guardian_name,
        pickup_code=_generate_pickup_code(),
        checked_in_by=user,
        notes=notes,
    )


def check_out_child(check_in, *, code, user):
    """
    Completes a check-out, but only if `code` matches the pickup code
    recorded at check-in. Raises WrongPickupCodeError (without changing
    anything) if it doesn't, and is a no-op returning False if this child
    was already checked out - so re-submitting a check-out never overwrites
    who actually checked them out or when.
    """
    if check_in.checked_out_at is not None:
        return False

    if code != check_in.pickup_code:
        raise WrongPickupCodeError("That pickup code doesn't match this check-in.")

    check_in.checked_out_at = timezone.now()
    check_in.checked_out_by = user
    check_in.save(update_fields=["checked_out_at", "checked_out_by"])
    return True
