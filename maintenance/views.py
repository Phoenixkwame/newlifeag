from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .forms import MaintenanceRequestForm


@login_required
def submit_maintenance_request(request):
    """
    Posted from the member's own dashboard (see members/templates/members/
    dashboard.html) - there's no separate page for this, just an inline
    form, same pattern as prayer/views.py's submit_prayer_request.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    if request.method == "POST":
        form = MaintenanceRequestForm(request.POST)
        if form.is_valid():
            maintenance_request = form.save(commit=False)
            maintenance_request.reported_by = member
            maintenance_request.save()
            messages.success(request, "Thanks - your report has been sent to the facilities team.")
        else:
            messages.error(request, "Couldn't submit that - please try again.")
    return redirect("dashboard")
