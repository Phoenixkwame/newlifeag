from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .forms import CareRequestForm
from .notifications import notify_pastors_of_new_care_request


@login_required
def submit_care_request(request):
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
        form = CareRequestForm(request.POST)
        if form.is_valid():
            care_request = form.save(commit=False)
            care_request.member = member
            care_request.save()
            notify_pastors_of_new_care_request(care_request)
            messages.success(request, "Your request has been sent to the pastoral team.")
        else:
            messages.error(request, "Couldn't submit that - please try again.")
    return redirect("dashboard")
