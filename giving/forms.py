from django import forms
from django.utils import timezone

from members.models import Campus, Member

from .models import Donation, GivingCampaign, Pledge, RecurringGiving


class DonationForm(forms.ModelForm):
    class Meta:
        model = Donation
        fields = ["member", "amount", "donation_type", "campus", "campaign"]

    def __init__(self, *args, public_member=None, restrict_member=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].queryset = Member.objects.filter(is_active=True)
        self.fields["member"].required = False
        self.fields["member"].empty_label = "Anonymous"
        if restrict_member:
            self.fields["member"].queryset = Member.objects.filter(pk=public_member.pk, is_active=True) if public_member else Member.objects.none()
            if public_member is None:
                self.fields["member"].widget = forms.HiddenInput()
        # Shown on both the public giving page and the staff "log a gift"
        # form - hidden on both until a second campus actually exists (see
        # the Campus model's docstring in members/models.py).
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]
        # Same idea for campaigns - only worth showing while at least one
        # is actually running (see the GivingCampaign model's docstring).
        active_campaigns = GivingCampaign.objects.filter(is_active=True)
        if active_campaigns.exists():
            self.fields["campaign"].queryset = active_campaigns
            self.fields["campaign"].required = False
            self.fields["campaign"].empty_label = "General fund (no campaign)"
        else:
            del self.fields["campaign"]

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount


class PublicDonationForm(DonationForm):
    """
    The public giving page's form - DonationForm plus the giver's own
    contact details. With require_contact (online payments switched on),
    a name and email are required, since Flutterwave needs a real email to
    send its payment confirmation and we need some way to follow up on a
    gift from someone without a member profile.
    """

    class Meta(DonationForm.Meta):
        fields = DonationForm.Meta.fields + ["donor_name", "donor_email", "donor_phone"]
        labels = {"donor_name": "Full name", "donor_email": "Email address", "donor_phone": "Phone number"}
        widgets = {
            "donor_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "donor_email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "donor_phone": forms.TextInput(attrs={"autocomplete": "tel", "inputmode": "tel", "placeholder": "024 000 0000"}),
        }

    def __init__(self, *args, require_contact=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["donor_name"].required = require_contact
        self.fields["donor_email"].required = require_contact
        self.fields["donor_phone"].required = False


class RecurringGivingForm(forms.ModelForm):
    """
    A member setting up (or editing) their own recurring giving commitment -
    see giving/views.py's recurring_giving_create/recurring_giving_edit,
    which set the member themselves, so this form never asks for it.
    """

    class Meta:
        model = RecurringGiving
        fields = ["amount", "frequency", "campaign", "next_due_date"]
        widgets = {"next_due_date": forms.DateInput(attrs={"type": "date"})}
        labels = {"next_due_date": "Start date"}
        help_texts = {"next_due_date": "The first reminder to give goes out on this date."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["next_due_date"].input_formats = ["%Y-%m-%d"]
        if not self.instance.pk:
            self.fields["next_due_date"].initial = timezone.localdate()
        # Same progressive-disclosure rule as DonationForm above - only worth
        # offering while at least one campaign is actually running.
        active_campaigns = GivingCampaign.objects.filter(is_active=True)
        if active_campaigns.exists():
            self.fields["campaign"].queryset = active_campaigns
            self.fields["campaign"].required = False
            self.fields["campaign"].empty_label = "General fund (no campaign)"
        else:
            del self.fields["campaign"]

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount


class PledgeForm(forms.ModelForm):
    """
    A member committing to (or updating) their own pledge toward a
    campaign - see giving/views.py's pledge_campaign, which sets the
    campaign and member itself, so this form only ever asks for the amount.
    """

    class Meta:
        model = Pledge
        fields = ["amount"]

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount
