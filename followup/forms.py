from django import forms


class ConnectCardForm(forms.Form):
    """
    A plain Form rather than a ModelForm, since one submission touches two
    models (a Member gets found-or-created, then a FollowUp is started for
    them - see followup/views.py's connect_card and followup/services.py's
    find_or_create_guest/start_follow_up).
    """

    first_name = forms.CharField(max_length=100)
    last_name = forms.CharField(max_length=100)
    phone = forms.CharField(max_length=20, required=False)
    email = forms.EmailField(required=False)
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Anything you'd like us to know or pray about?",
    )

    def clean(self):
        cleaned_data = super().clean()
        phone = cleaned_data.get("phone")
        email = cleaned_data.get("email")
        if not phone and not email:
            raise forms.ValidationError("Please leave a phone number or email so we can follow up with you.")
        return cleaned_data
