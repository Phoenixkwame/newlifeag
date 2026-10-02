from django.shortcuts import redirect, render

from .forms import SuggestionForm


def submit_suggestion(request):
    """
    The public suggestion box - no login required, and nothing collected
    here ties a submission back to whoever wrote it (see Suggestion's
    docstring). Same submit-then-redirect-to-a-thank-you-page shape as
    followup/views.py's connect_card.
    """
    if request.method == "POST":
        form = SuggestionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("suggestion_confirmation")
    else:
        form = SuggestionForm()
    return render(request, "suggestions/submit.html", {"form": form})


def suggestion_confirmation(request):
    return render(request, "suggestions/confirmation.html")
