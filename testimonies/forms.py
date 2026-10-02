from django import forms

from .models import Testimony


class TestimonyForm(forms.ModelForm):
    class Meta:
        model = Testimony
        fields = ["testimony_text", "share_name_publicly"]
        widgets = {
            "testimony_text": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Share how God has worked in your life..."}
            ),
        }
        labels = {
            "share_name_publicly": "Show my name if this is approved for the wall (otherwise it's shown anonymously)",
        }
