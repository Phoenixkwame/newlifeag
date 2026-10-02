from django.shortcuts import redirect, render

from .forms import ConnectCardForm
from .models import VisitorInfo
from .notifications import notify_followup_team_of_new_connection
from .services import find_or_create_guest, start_follow_up


def connect_card(request):
    """
    The public "I'm New Here" form, linked from the site nav (see
    templates/base.html) and meant to also be reachable from a QR code on
    physical signage at the church. No login required - most people filling
    this out are visiting for the first time and don't have an account.
    """
    if request.method == "POST":
        form = ConnectCardForm(request.POST)
        if form.is_valid():
            member = find_or_create_guest(
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                phone=form.cleaned_data["phone"],
                email=form.cleaned_data["email"],
            )
            follow_up = start_follow_up(member)
            notes = form.cleaned_data.get("notes")
            if notes:
                # Append rather than overwrite - a repeat visitor's second
                # connect card shouldn't erase what an earlier one (or a
                # staff member) already wrote down.
                stamp = f"Connect card ({follow_up.first_visit_date}): {notes}"
                follow_up.notes = f"{follow_up.notes}\n\n{stamp}".strip() if follow_up.notes else stamp
                follow_up.save(update_fields=["notes"])
            notify_followup_team_of_new_connection(follow_up)
            return redirect("connect_card_confirmation")
    else:
        form = ConnectCardForm()

    return render(request, "followup/connect_card.html", {"form": form})


def connect_card_confirmation(request):
    return render(request, "followup/connect_card_confirmation.html")


def visitor_info(request):
    """
    A public, no-login "planning your visit" page - service times, address,
    wifi, and a short welcome note - meant to be reachable from a QR code on
    signage or a link shared ahead of someone's first visit, separate from
    the full site and from the "I'm New Here" connect card above (that one
    collects a visitor's own details; this one only gives them information).
    Kept up to date by Pastors from the staff area (see staff/views.py's
    visitor_info_edit) rather than a developer editing a template.
    """
    return render(request, "followup/visitor_info.html", {"info": VisitorInfo.get_current()})
