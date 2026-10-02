from django import forms

from .models import Suggestion


class SuggestionForm(forms.ModelForm):
    class Meta:
        model = Suggestion
        fields = ["message"]
        widgets = {
            "message": forms.Textarea(
                attrs={"rows": 5, "placeholder": "Share your feedback or suggestion for church leadership..."}
            )
        }
        labels = {"message": ""}
