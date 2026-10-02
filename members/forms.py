from django import forms

from .models import Member


class MemberPhotoForm(forms.ModelForm):
    """Just the photo field, for a member updating their own profile picture."""

    class Meta:
        model = Member
        fields = ["photo"]

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and photo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Please choose an image smaller than 5MB.")
        return photo


class MemberProfileForm(forms.ModelForm):
    """
    A member editing their own contact details from the dashboard.
    Deliberately excludes role, campus, household, is_active, and photo
    (which has its own dedicated upload flow) - those stay staff-only (see
    StaffMemberForm in staff/forms.py), so a member can't grant themselves
    admin access or move themselves between campuses/households on their own.
    date_of_birth and anniversary_date are included here too - harmless for
    a member to set about themselves, unlike everything excluded above.
    """

    # Not a model field - a friendlier comma-separated text box than a
    # multi-select of Skill objects, same pattern as sermons' tags_input.
    # See members/services.py's set_member_skills, which edit_profile calls
    # with this value after saving the profile itself.
    skills_text = forms.CharField(
        required=False,
        label="Skills / spiritual gifts",
        help_text='Comma-separated, e.g. "Music, Hospitality" - lets staff find you for a matching need.',
    )

    class Meta:
        model = Member
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "date_of_birth",
            "anniversary_date",
            "share_in_directory",
            "share_phone_in_directory",
            "share_email_in_directory",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "anniversary_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "share_in_directory": "List me in the member directory",
            "share_phone_in_directory": "Show my phone number in the directory",
            "share_email_in_directory": "Show my email address in the directory",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same HTML5 "date" input format story as staff/forms.py's
        # DATE_LOCAL_FORMAT - this form lives in a different app and only
        # needs it for these two fields, so it's set inline here rather than
        # importing that constant across app boundaries.
        self.fields["date_of_birth"].input_formats = ["%Y-%m-%d"]
        self.fields["date_of_birth"].required = False
        self.fields["anniversary_date"].input_formats = ["%Y-%m-%d"]
        self.fields["anniversary_date"].required = False
        if self.instance.pk:
            self.fields["skills_text"].initial = ", ".join(self.instance.skills.values_list("name", flat=True))


class NotificationPreferencesForm(forms.ModelForm):
    """
    A member's own opt-out center, on the new account settings page -
    deliberately its own small form, separate from MemberProfileForm above,
    so "how do I reach you" (contact details) and "should I bother you"
    (notification preferences) aren't mixed into one long profile form.

    Started out as just the two Announcements flags (see
    announcements/services.py's send_announcement); now also covers a
    handful of other proactive nudges - see Member's docstring comment
    above notify_volunteer_reminders for exactly which notifications each
    flag does (and deliberately doesn't) touch.
    """

    class Meta:
        model = Member
        fields = [
            "notify_by_email",
            "notify_by_sms",
            "notify_volunteer_reminders",
            "notify_pledge_reminders",
            "notify_giving_receipts",
            "notify_prayer_updates",
        ]
        labels = {
            "notify_by_email": "Email me church-wide announcements",
            "notify_by_sms": "Text me church-wide announcements",
            "notify_volunteer_reminders": "Remind me the day before I'm scheduled to volunteer",
            "notify_pledge_reminders": "Remind me about an outstanding pledge or a recurring gift that's due",
            "notify_giving_receipts": "Email me a receipt when a gift of mine is recorded as completed",
            "notify_prayer_updates": "Let me know when my prayer request has been prayed for",
        }


class InterestSurveyForm(forms.Form):
    """
    A standalone, shorter cousin of MemberProfileForm's skills_text field -
    just the one question, for the dedicated "tell us your interests" page
    aimed at a new member who hasn't filled in their profile yet, rather
    than sending them to the full profile form. Uses the exact same
    set_member_skills service on save, so a skill entered here and one
    entered on the profile page are handled identically.
    """

    skills_text = forms.CharField(
        required=False,
        label="What are you interested in or good at?",
        help_text='Comma-separated, e.g. "Music, Hospitality, Children\'s Ministry".',
        widget=forms.Textarea(attrs={"rows": 2}),
    )
