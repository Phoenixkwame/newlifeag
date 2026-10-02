from django import forms

from .models import CareRequest


class CareRequestForm(forms.ModelForm):
    class Meta:
        model = CareRequest
        fields = ["request_type", "details", "preferred_contact_method"]
        widgets = {
            "details": forms.Textarea(
                attrs={"rows": 3, "placeholder": "What would you like the pastoral team to know?"}
            ),
        }
        labels = {
            "preferred_contact_method": "Preferred contact method (optional)",
        }
