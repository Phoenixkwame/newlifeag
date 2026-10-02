from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .forms import ServiceHourLogForm


@login_required
def log_service_hours(request):
    """
    Posted from the member's own dashboard (see members/templates/members/
    dashboard.html) - same inline-form pattern as care/views.py's
    submit_care_request.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    if request.method == "POST":
        form = ServiceHourLogForm(request.POST)
        if form.is_valid():
            log = form.save(commit=False)
            log.member = member
            log.save()
            messages.success(request, f"Logged {log.hours} hour(s) for {log.date}.")
        else:
            messages.error(request, "Couldn't log those hours - please check the form and try again.")
    return redirect("dashboard")
