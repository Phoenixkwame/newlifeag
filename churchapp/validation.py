from django.http import Http404


def optional_id(value):
    """Validate an optional database ID before passing it to the ORM."""
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise Http404("Invalid selection.")
    if not 0 < number <= 9223372036854775807:
        raise Http404("Invalid selection.")
    return number
