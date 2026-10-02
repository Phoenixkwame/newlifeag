from django import forms

from .models import MaintenanceRequest


class MaintenanceRequestForm(forms.ModelForm):
    """A member (or an Usher) reporting an issue - just what's wrong and where, nothing about resolving it."""

    class Meta:
        model = MaintenanceRequest
        fields = ["title", "description", "location"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3, "placeholder": "What's wrong, and any other details."}),
        }
