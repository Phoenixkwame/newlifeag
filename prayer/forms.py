from django import forms

from .models import PrayerRequest


class PrayerRequestForm(forms.ModelForm):
    class Meta:
        model = PrayerRequest
        fields = ["request_text", "is_public", "share_name_publicly"]
        widgets = {
            "request_text": forms.Textarea(
                attrs={"rows": 3, "placeholder": "What would you like the church to pray with you about?"}
            ),
        }
        labels = {
            "is_public": "Allow this request on the public prayer wall after staff review",
            "share_name_publicly": "Show my name on the wall (otherwise it's shown anonymously)",
        }


class PublicPrayerRequestForm(PrayerRequestForm):
    request_text = forms.CharField(max_length=5000, label="Your prayer request", widget=forms.Textarea(attrs={"rows": 5}))

    class Meta(PrayerRequestForm.Meta):
        fields = ["request_text", "guest_name", "guest_email", "guest_phone", "is_public", "share_name_publicly"]
        labels = {
            **PrayerRequestForm.Meta.labels,
            "guest_name": "Your name (optional)",
            "guest_email": "Email (optional)",
            "guest_phone": "Phone (optional)",
        }

    def clean(self):
        data = super().clean()
        if not data.get("is_public"):
            data["share_name_publicly"] = False
        return data
