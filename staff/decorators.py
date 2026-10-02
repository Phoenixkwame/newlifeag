from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.http import Http404


def staff_permission_required(perm):
    """
    Like Django's built-in permission_required, but redirects to the
    member's own dashboard with a friendly message instead of showing a
    bare 403 page - consistent with how members.views.mark_attendance()
    already handles a similar check.

    Superusers pass every check, as usual. Everyone else needs the named
    permission, which in practice means being in the right group (Ushers,
    Treasurers, or Pastors - see members/management/commands/setup_groups.py).
    """

    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_staff or not request.user.has_perm(perm):
                messages.error(request, "You don't have permission to do that.")
                return redirect("dashboard")
            # Printable cards and auxiliary actions must obey the same scope
            # as member_detail, including direct requests with guessed IDs.
            if "member_id" in kwargs:
                from members.models import Member
                from .services import scope_members, staff_campus_for
                if not scope_members(Member.objects.all(), staff_campus_for(request.user)).filter(pk=kwargs["member_id"]).exists():
                    raise Http404("Member not found.")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def staff_member_required(view_func):
    """Just requires is_staff=True - for hub pages anyone with admin access can open."""

    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, "You don't have permission to do that.")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)

    return wrapped
