from django import forms


class LoginCodeForm(forms.Form):
    """The 6-digit code form for churchapp/two_factor.py's verify_login_code."""

    code = forms.CharField(
        label="Login code",
        max_length=6,
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "one-time-code", "inputmode": "numeric"}),
    )
