from datetime import timedelta

from django import forms
from django.contrib.auth.models import User
from django.utils import timezone

from announcements.models import Announcement
from booking.models import Resource, ResourceBooking
from booking.services import conflicting_bookings
from care.models import CareRequest
from checkin.models import Child, SundaySchoolClass, SundaySchoolLesson
from decisions.models import Decision
from equipment.models import Equipment, EquipmentCheckout
from expenses.models import BudgetCategory, Expense
from events.models import Event, EventServiceTime, EventTicket, VolunteerSlot
from flyers.models import Flyer
from followup.models import ContactAttempt, FollowUp, VisitorInfo
from giving.models import GivingCampaign
from governance.models import ActionItem, Meeting
from library.models import LibraryItem, LibraryLoan
from livestream.models import LiveStream
from maintenance.models import MaintenanceRequest
from members.models import Campus, Group, Household, Member, MemberNote
from milestones.models import BabyDedication, BaptismRecord, FuneralRecord, TransferLetter, WeddingRecord
from pathway.models import PathwayStep
from prayer.models import PrayerRequest
from screening.models import BackgroundCheck, VolunteerTraining
from servicehours.models import ServiceHourLog
from sermons.models import Devotional, Sermon, SermonSeries
from surveys.models import Survey, SurveyChoice, SurveyQuestion

# The HTML5 "datetime-local" input always sends/expects this exact shape
# (e.g. "2026-04-05T09:30"), which isn't in Django's default
# DATETIME_INPUT_FORMATS (those use a space, not "T"). Setting both the
# widget's display format AND the field's input_formats to match is
# required for the date/time picker to work in both directions - showing
# the current value when editing, and actually parsing what's submitted.
DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"

# Same reasoning as above, for the plain HTML5 "date" input (e.g.
# "2026-04-05"). Django's locale-aware default formats aren't guaranteed to
# match this exactly, so pin it explicitly rather than rely on it.
DATE_LOCAL_FORMAT = "%Y-%m-%d"


class StaffCampusForm(forms.ModelForm):
    class Meta:
        model = Campus
        fields = ["name", "address", "service_times"]


class StaffHouseholdForm(forms.ModelForm):
    class Meta:
        model = Household
        fields = ["name", "address", "phone"]


class StaffGroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = [
            "name",
            "group_type",
            "description",
            "leader",
            "meeting_day",
            "meeting_time",
            "meeting_location",
            "interest_skills",
            "max_members",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "meeting_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["leader"].queryset = Member.objects.filter(is_active=True).order_by("last_name", "first_name")
        self.fields["leader"].required = False
        self.fields["meeting_day"].required = False
        self.fields["meeting_time"].required = False
        self.fields["interest_skills"].required = False


class StaffMemberForm(forms.ModelForm):
    class Meta:
        model = Member
        fields = [
            "first_name",
            "last_name",
            "email",
            "phone",
            "photo",
            "household",
            "campus",
            "role",
            "is_active",
            "date_of_birth",
            "anniversary_date",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "anniversary_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["household"].queryset = Household.objects.all().order_by("name")
        self.fields["household"].required = False
        self.fields["date_of_birth"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["date_of_birth"].required = False
        self.fields["anniversary_date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["anniversary_date"].required = False
        # The campus field only makes sense once a church actually has more
        # than one - otherwise it's just noise on every member's form. See
        # the Campus model's docstring in members/models.py.
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]


class StaffEventForm(forms.ModelForm):
    # Not a model field - only used right after creating a new event to
    # decide how many occurrences to generate (see staff/views.py's
    # event_create and events/services.py's generate_recurring_occurrences).
    # Ignored when repeat is left as "Does not repeat", and ignored entirely
    # when editing an existing event.
    occurrences = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=52,
        initial=1,
        help_text="Only used when repeating - total events to create in the series, including this one.",
    )

    class Meta:
        model = Event
        fields = [
            "title",
            "description",
            "event_type",
            "start_datetime",
            "end_datetime",
            "location",
            "campus",
            "recurrence",
        ]
        widgets = {
            "start_datetime": forms.DateTimeInput(format=DATETIME_LOCAL_FORMAT, attrs={"type": "datetime-local"}),
            "end_datetime": forms.DateTimeInput(format=DATETIME_LOCAL_FORMAT, attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_datetime"].input_formats = [DATETIME_LOCAL_FORMAT]
        self.fields["end_datetime"].input_formats = [DATETIME_LOCAL_FORMAT]
        # required=False here (rather than the model field itself being
        # blank=True) so the dropdown has no confusing empty "---" option -
        # clean_recurrence below maps a not-submitted value to NONE anyway.
        self.fields["recurrence"].required = False
        # Same reasoning as StaffMemberForm above - hidden until there's a
        # second campus to actually choose between.
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]

    def clean_recurrence(self):
        return self.cleaned_data.get("recurrence") or Event.Recurrence.NONE


class StaffVolunteerSlotForm(forms.ModelForm):
    class Meta:
        model = VolunteerSlot
        fields = ["role_needed", "capacity"]


class StaffEventServiceTimeForm(forms.ModelForm):
    class Meta:
        model = EventServiceTime
        fields = ["label", "start_time", "location"]
        widgets = {"start_time": forms.TimeInput(attrs={"type": "time"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_time"].required = False
        self.fields["location"].required = False


class StaffEventTicketForm(forms.ModelForm):
    class Meta:
        model = EventTicket
        fields = ["name", "price", "capacity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["capacity"].required = False


class StaffLiveStreamForm(forms.ModelForm):
    class Meta:
        model = LiveStream
        fields = ["title", "stream_url", "scheduled_for", "notes", "featured_on_homepage"]
        widgets = {
            "scheduled_for": forms.DateTimeInput(format=DATETIME_LOCAL_FORMAT, attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["scheduled_for"].input_formats = [DATETIME_LOCAL_FORMAT]
        self.fields["featured_on_homepage"].required = False


class StaffFlyerForm(forms.ModelForm):
    class Meta:
        model = Flyer
        fields = ["title", "image", "link_url", "is_active", "order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["link_url"].required = False

    def clean_image(self):
        # Same 5MB limit as a member's own photo upload (see
        # MemberPhotoForm in members/forms.py) - a flyer is shown at a
        # similar homepage-card size, so there's no reason to allow a much
        # larger file here.
        image = self.cleaned_data.get("image")
        if image and image.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Please choose an image smaller than 5MB.")
        return image


class StaffSermonForm(forms.ModelForm):
    # Not a model field - a friendlier comma-separated text box than a
    # multi-select of Tag objects. See sermons/services.py's set_sermon_tags,
    # which the staff sermon_create/sermon_edit views call with this value
    # after saving the sermon itself.
    tags_input = forms.CharField(
        required=False,
        label="Tags",
        help_text='Comma-separated, e.g. "Faith, Family" - existing tags are reused, new ones are created.',
    )

    class Meta:
        model = Sermon
        fields = [
            "title",
            "speaker",
            "date",
            "scripture_reference",
            "series",
            "media_url",
            "audio_file",
            "study_guide",
            "discussion_guide",
            "notes",
        ]
        widgets = {
            "date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["series"].required = False
        self.fields["series"].queryset = SermonSeries.objects.order_by("name")
        self.fields["study_guide"].required = False
        self.fields["discussion_guide"].required = False
        if self.instance.pk:
            self.fields["tags_input"].initial = ", ".join(self.instance.tags.values_list("name", flat=True))

    def clean_study_guide(self):
        study_guide = self.cleaned_data.get("study_guide")
        if study_guide and hasattr(study_guide, "size") and study_guide.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Please choose a file smaller than 10MB.")
        return study_guide

    def clean_discussion_guide(self):
        discussion_guide = self.cleaned_data.get("discussion_guide")
        if discussion_guide and hasattr(discussion_guide, "size") and discussion_guide.size > 10 * 1024 * 1024:
            raise forms.ValidationError("Please choose a file smaller than 10MB.")
        return discussion_guide


class StaffSermonSeriesForm(forms.ModelForm):
    class Meta:
        model = SermonSeries
        fields = ["name", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class StaffPathwayStepForm(forms.ModelForm):
    class Meta:
        model = PathwayStep
        fields = ["name", "order", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class StaffDevotionalForm(forms.ModelForm):
    class Meta:
        model = Devotional
        fields = ["date", "title", "scripture_reference", "body"]
        widgets = {
            "date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "body": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = [DATE_LOCAL_FORMAT]


class StaffGivingCampaignForm(forms.ModelForm):
    class Meta:
        model = GivingCampaign
        fields = [
            "name",
            "description",
            "goal_amount",
            "start_date",
            "end_date",
            "campus",
            "is_active",
            "sms_keyword",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "start_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "end_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["end_date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["end_date"].required = False
        self.fields["goal_amount"].required = False
        # Same reasoning as StaffMemberForm above - hidden until there's a
        # second campus to actually choose between.
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]


class StaffChildForm(forms.ModelForm):
    class Meta:
        model = Child
        fields = ["household", "first_name", "last_name", "date_of_birth", "allergies_or_medical_notes", "is_active"]
        widgets = {
            "date_of_birth": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "allergies_or_medical_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date_of_birth"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["date_of_birth"].required = False
        self.fields["household"].queryset = Household.objects.all().order_by("name")


class StaffCheckInForm(forms.Form):
    """
    Plain Form, not a ModelForm - pickup_code and checked_in_by are set by
    checkin/services.py's check_in_child, never entered by hand here.
    """

    child = forms.ModelChoiceField(queryset=Child.objects.none())
    event = forms.ModelChoiceField(
        queryset=Event.objects.none(), required=False, empty_label="Not tied to a specific event"
    )
    guardian_name = forms.CharField(max_length=150, help_text="Who's dropping this child off today.")
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["child"].queryset = Child.objects.filter(is_active=True).order_by("last_name", "first_name")
        # A reasonable window of events to offer - recent enough to cover a
        # service that's already started, and everything coming up soon.
        self.fields["event"].queryset = Event.objects.filter(
            start_datetime__gte=timezone.now() - timedelta(hours=6)
        ).order_by("start_datetime")


class StaffCheckOutForm(forms.Form):
    code = forms.CharField(max_length=6, label="Pickup code")


class StaffFollowUpStageForm(forms.ModelForm):
    class Meta:
        model = FollowUp
        fields = ["stage", "assigned_to"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(is_staff=True).order_by("username")
        self.fields["assigned_to"].required = False


class StaffContactAttemptForm(forms.ModelForm):
    class Meta:
        model = ContactAttempt
        fields = ["note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3, "placeholder": "What happened when you reached out?"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["note"].required = False


class StaffDecisionForm(forms.ModelForm):
    class Meta:
        model = Decision
        fields = ["member", "decision_type", "date", "event", "notes"]
        widgets = {
            "date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["event"].required = False
        self.fields["event"].queryset = Event.objects.order_by("-start_datetime")
        self.fields["notes"].required = False


class StaffMemberNoteForm(forms.ModelForm):
    class Meta:
        model = MemberNote
        fields = ["note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3, "placeholder": "A private note for staff only..."})}


class StaffAnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["subject", "body", "sms_body", "audience", "campus", "group"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 6}),
            "sms_body": forms.Textarea(attrs={"rows": 2, "maxlength": 300}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sms_body"].required = False
        self.fields["campus"].required = False
        self.fields["group"].required = False
        self.fields["group"].queryset = Group.objects.order_by("name")
        # Same progressive-disclosure rule as everywhere else Campus shows up
        # (see StaffMemberForm above) - "One Campus" targeting only makes
        # sense, and is only offered, once a second campus actually exists.
        if Campus.objects.count() > 1:
            self.fields["audience"].choices = Announcement.Audience.choices
        else:
            self.fields["audience"].choices = [
                choice for choice in Announcement.Audience.choices if choice[0] != Announcement.Audience.CAMPUS
            ]
            del self.fields["campus"]

    def clean(self):
        cleaned_data = super().clean()
        audience = cleaned_data.get("audience")
        if audience == Announcement.Audience.CAMPUS and not cleaned_data.get("campus"):
            self.add_error("campus", "Choose a campus for a campus-targeted announcement.")
        if audience == Announcement.Audience.GROUP and not cleaned_data.get("group"):
            self.add_error("group", "Choose a group for a group-targeted announcement.")
        return cleaned_data


class StaffResourceForm(forms.ModelForm):
    class Meta:
        model = Resource
        fields = ["name", "resource_type", "campus", "notes", "is_active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same progressive-disclosure rule as StaffMemberForm's campus field.
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]


class StaffResourceBookingForm(forms.ModelForm):
    class Meta:
        model = ResourceBooking
        fields = ["resource", "title", "event", "start_datetime", "end_datetime", "notes"]
        widgets = {
            "start_datetime": forms.DateTimeInput(format=DATETIME_LOCAL_FORMAT, attrs={"type": "datetime-local"}),
            "end_datetime": forms.DateTimeInput(format=DATETIME_LOCAL_FORMAT, attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        # The booking being edited, if any - excluded from its own conflict
        # check in clean() so saving a booking without changing its time
        # doesn't reject it as conflicting with itself.
        super().__init__(*args, **kwargs)
        self.fields["resource"].queryset = Resource.objects.filter(is_active=True)
        self.fields["event"].required = False
        self.fields["start_datetime"].input_formats = [DATETIME_LOCAL_FORMAT]
        self.fields["end_datetime"].input_formats = [DATETIME_LOCAL_FORMAT]

    def clean(self):
        cleaned_data = super().clean()
        resource = cleaned_data.get("resource")
        start = cleaned_data.get("start_datetime")
        end = cleaned_data.get("end_datetime")
        if resource and start and end:
            if end <= start:
                self.add_error("end_datetime", "End time must be after the start time.")
            else:
                conflicts = conflicting_bookings(resource, start, end, exclude_booking_id=self.instance.id)
                if conflicts.exists():
                    conflict = conflicts.first()
                    self.add_error(
                        None,
                        f"{resource} is already booked for \"{conflict.title}\" from "
                        f"{conflict.start_datetime:%b j, Y g:i A} to {conflict.end_datetime:%b j, Y g:i A}.",
                    )
        return cleaned_data


class StaffCareRequestUpdateForm(forms.ModelForm):
    class Meta:
        model = CareRequest
        fields = ["status", "assigned_pastor", "scheduled_date", "pastor_notes"]
        widgets = {
            "scheduled_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "pastor_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_pastor"].queryset = User.objects.filter(groups__name="Pastors").order_by("username")
        self.fields["assigned_pastor"].required = False
        self.fields["scheduled_date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["scheduled_date"].required = False


class StaffPrayerAssignForm(forms.ModelForm):
    class Meta:
        model = PrayerRequest
        fields = ["assigned_pastor"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_pastor"].queryset = User.objects.filter(groups__name="Pastors").order_by("username")
        self.fields["assigned_pastor"].required = False


class StaffSurveyForm(forms.ModelForm):
    class Meta:
        model = Survey
        fields = ["title", "description", "is_open"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class StaffSurveyQuestionForm(forms.ModelForm):
    class Meta:
        model = SurveyQuestion
        fields = ["text", "question_type", "order"]


class StaffSurveyChoiceForm(forms.ModelForm):
    class Meta:
        model = SurveyChoice
        fields = ["text", "order"]


class StaffBabyDedicationForm(forms.ModelForm):
    class Meta:
        model = BabyDedication
        fields = ["child_name", "parents", "dedication_date", "officiated_by", "campus", "notes"]
        widgets = {
            "dedication_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parents"].required = False
        self.fields["dedication_date"].input_formats = [DATE_LOCAL_FORMAT]
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]


class StaffWeddingRecordForm(forms.ModelForm):
    class Meta:
        model = WeddingRecord
        fields = ["spouse_one", "spouse_two", "wedding_date", "officiated_by", "location", "campus", "notes"]
        widgets = {
            "wedding_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["wedding_date"].input_formats = [DATE_LOCAL_FORMAT]
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]

    def clean(self):
        cleaned_data = super().clean()
        spouse_one = cleaned_data.get("spouse_one")
        spouse_two = cleaned_data.get("spouse_two")
        if spouse_one and spouse_two and spouse_one == spouse_two:
            self.add_error("spouse_two", "The two spouses can't be the same member.")
        return cleaned_data


class StaffBaptismRecordForm(forms.ModelForm):
    class Meta:
        model = BaptismRecord
        fields = ["member", "baptism_date", "officiated_by", "location", "campus", "notes"]
        widgets = {
            "baptism_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["baptism_date"].input_formats = [DATE_LOCAL_FORMAT]
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]


class StaffFuneralRecordForm(forms.ModelForm):
    class Meta:
        model = FuneralRecord
        fields = [
            "member",
            "date_of_death",
            "service_date",
            "officiated_by",
            "location",
            "family_contacts",
            "campus",
            "notes",
        ]
        widgets = {
            "date_of_death": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "service_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date_of_death"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["date_of_death"].required = False
        self.fields["service_date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["family_contacts"].required = False
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]


class StaffTransferLetterForm(forms.ModelForm):
    class Meta:
        model = TransferLetter
        fields = ["member", "destination_church", "destination_location", "transfer_date", "issued_by", "notes"]
        widgets = {
            "transfer_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["transfer_date"].input_formats = [DATE_LOCAL_FORMAT]


class StaffBackgroundCheckForm(forms.ModelForm):
    class Meta:
        model = BackgroundCheck
        fields = ["member", "status", "submitted_date", "cleared_date", "expiry_date", "notes"]
        widgets = {
            "submitted_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "cleared_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "expiry_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].queryset = Member.objects.filter(is_active=True).order_by("last_name", "first_name")
        for date_field in ("submitted_date", "cleared_date", "expiry_date"):
            self.fields[date_field].input_formats = [DATE_LOCAL_FORMAT]
            self.fields[date_field].required = False


class StaffVolunteerTrainingForm(forms.ModelForm):
    class Meta:
        model = VolunteerTraining
        fields = ["member", "training_name", "status", "completed_date", "expiry_date", "notes"]
        widgets = {
            "completed_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "expiry_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].queryset = Member.objects.filter(is_active=True).order_by("last_name", "first_name")
        for date_field in ("completed_date", "expiry_date"):
            self.fields[date_field].input_formats = [DATE_LOCAL_FORMAT]
            self.fields[date_field].required = False


class StaffMaintenanceRequestForm(forms.ModelForm):
    """A Pastor logging an issue directly (e.g. one phoned in) - same fields a member/Usher submits from their own side."""

    class Meta:
        model = MaintenanceRequest
        fields = ["title", "description", "location", "resource", "equipment"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["resource"].required = False
        self.fields["equipment"].required = False
        self.fields["resource"].queryset = Resource.objects.filter(is_active=True)


class StaffSundaySchoolClassForm(forms.ModelForm):
    class Meta:
        model = SundaySchoolClass
        fields = ["name", "description", "teacher"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["teacher"].required = False
        self.fields["teacher"].queryset = Member.objects.filter(is_active=True).order_by("last_name", "first_name")


class StaffSundaySchoolLessonForm(forms.ModelForm):
    class Meta:
        model = SundaySchoolLesson
        fields = ["title", "week_of", "scripture_reference", "content"]
        widgets = {
            "week_of": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "content": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["week_of"].input_formats = [DATE_LOCAL_FORMAT]


class StaffServiceHourLogForm(forms.ModelForm):
    """A Pastor logging (or correcting) a volunteer's hours on their behalf."""

    class Meta:
        model = ServiceHourLog
        fields = ["member", "date", "hours", "role", "group", "event", "notes"]
        widgets = {
            "date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].queryset = Member.objects.filter(is_active=True).order_by("last_name", "first_name")
        self.fields["date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["group"].required = False
        self.fields["event"].required = False
        self.fields["notes"].required = False


class StaffBudgetCategoryForm(forms.ModelForm):
    class Meta:
        model = BudgetCategory
        fields = ["name", "annual_budget"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["annual_budget"].required = False


class StaffExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["category", "amount", "date", "paid_to", "description", "receipt", "campus"]
        widgets = {
            "date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["category"].required = False
        self.fields["category"].queryset = BudgetCategory.objects.order_by("name")
        self.fields["paid_to"].required = False
        self.fields["description"].required = False
        self.fields["receipt"].required = False
        # Same progressive-disclosure rule as StaffMemberForm's campus field.
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]

    def clean_receipt(self):
        # Same size-limit pattern as StaffSermonForm's clean_study_guide -
        # a receipt photo is small, so 5MB (same cap as a member photo)
        # rather than the 10MB allowed for a study guide PDF.
        receipt = self.cleaned_data.get("receipt")
        if receipt and hasattr(receipt, "size") and receipt.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Please choose a file smaller than 5MB.")
        return receipt


class StaffVisitorInfoForm(forms.ModelForm):
    class Meta:
        model = VisitorInfo
        fields = [
            "service_times",
            "address",
            "wifi_network",
            "wifi_password",
            "what_to_expect",
            "welcome_video_url",
        ]
        widgets = {
            "service_times": forms.Textarea(attrs={"rows": 3}),
            "what_to_expect": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False


class StaffEquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = ["name", "category", "condition", "serial_number", "campus", "notes", "is_active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["serial_number"].required = False
        self.fields["notes"].required = False
        # Same progressive-disclosure rule as StaffMemberForm's campus field.
        if Campus.objects.count() > 1:
            self.fields["campus"].required = False
        else:
            del self.fields["campus"]


class StaffEquipmentCheckoutForm(forms.ModelForm):
    class Meta:
        model = EquipmentCheckout
        fields = ["checked_out_to", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["checked_out_to"].queryset = Member.objects.filter(is_active=True)
        self.fields["notes"].required = False


class StaffLibraryItemForm(forms.ModelForm):
    class Meta:
        model = LibraryItem
        fields = ["title", "author", "category", "notes", "is_active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["author"].required = False
        self.fields["notes"].required = False


class StaffLibraryLoanForm(forms.ModelForm):
    class Meta:
        model = LibraryLoan
        fields = ["borrower", "due_date", "notes"]
        widgets = {
            "due_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due_date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["borrower"].queryset = Member.objects.filter(is_active=True)
        self.fields["notes"].required = False


class StaffMeetingForm(forms.ModelForm):
    class Meta:
        model = Meeting
        fields = ["date", "title", "attendees", "agenda", "minutes"]
        widgets = {
            "date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "agenda": forms.Textarea(attrs={"rows": 4}),
            "minutes": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["attendees"].queryset = Member.objects.filter(is_active=True).order_by("last_name", "first_name")
        self.fields["attendees"].required = False
        self.fields["title"].required = False
        self.fields["agenda"].required = False
        self.fields["minutes"].required = False


class StaffActionItemForm(forms.ModelForm):
    class Meta:
        model = ActionItem
        fields = ["description", "owner", "due_date"]
        widgets = {"due_date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["due_date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["due_date"].required = False
        self.fields["owner"].required = False
        self.fields["owner"].queryset = Member.objects.filter(is_active=True).order_by("last_name", "first_name")
