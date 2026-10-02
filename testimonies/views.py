from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from .forms import TestimonyForm
from .models import Testimony


@login_required
def submit_testimony(request):
    """
    Posted from the member's own dashboard (see members/templates/members/
    dashboard.html) - there's no separate page for this, just an inline form,
    same pattern as prayer.views.submit_prayer_request.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    if request.method == "POST":
        form = TestimonyForm(request.POST)
        if form.is_valid():
            testimony = form.save(commit=False)
            testimony.member = member
            testimony.save()
            messages.success(request, "Thank you - your testimony has been submitted for review.")
        else:
            messages.error(request, "Couldn't submit that - please try again.")
    return redirect("dashboard")


def testimony_wall(request):
    """
    The public testimony wall - only testimonies a Pastor has approved show
    up here at all, and even then only with the member's name if they also
    chose share_name_publicly (see TestimonyForm).
    """
    testimonies_qs = Testimony.objects.filter(is_approved=True).select_related("member")
    page_obj = Paginator(testimonies_qs, 20).get_page(request.GET.get("page"))
    return render(request, "testimonies/wall.html", {"page_obj": page_obj})
