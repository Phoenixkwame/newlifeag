from django import forms

from members.models import Member

from .models import RSVP, EventServiceTime, EventTicket, VolunteerSlot


class MemberEventForm(forms.Form):
    member = forms.ModelChoiceField(queryset=Member.objects.none(), widget=forms.HiddenInput)

    def __init__(self, *args, member=None, **kwargs):
        super().__init__(*args, **kwargs)
        if member is not None and member.is_active:
            self.fields["member"].queryset = Member.objects.filter(pk=member.pk, is_active=True)
            self.fields["member"].initial = member.pk


class RSVPForm(MemberEventForm):
    status = forms.ChoiceField(choices=RSVP.Status.choices, initial=RSVP.Status.GOING)
    # Only shown/populated for an event that actually has more than one
    # service time - see __init__ below and EventServiceTime's docstring.
    service_time = forms.ModelChoiceField(queryset=EventServiceTime.objects.none(), required=False)

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        if event is not None and event.service_times.exists():
            self.fields["service_time"].queryset = event.service_times.all()
        else:
            del self.fields["service_time"]


class VolunteerSignupForm(MemberEventForm):
    slot = forms.ModelChoiceField(queryset=VolunteerSlot.objects.none())

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        if event is not None:
            # Full slots remain selectable so the member can join their waitlist.
            self.fields["slot"].queryset = event.volunteer_slots.all()


class QrCheckinForm(forms.Form):
    """
    Just a phone number - the whole point of the QR check-in page
    (events/views.py's event_qr_checkin) is that it needs no login, so
    there's no member dropdown to pick from the way RSVPForm above has;
    the phone is matched to a member the same way SMS check-in does (see
    events/services.py's check_in_via_qr). Also picks up an optional
    service_time field, same "only shown once the event actually has more
    than one" rule as RSVPForm above - a member checking in for a single-
    service event never sees this at all.
    """

    phone = forms.CharField(label="Your phone number", max_length=20)
    service_time = forms.ModelChoiceField(
        queryset=EventServiceTime.objects.none(), required=False, label="Which service?"
    )

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        if event is not None and event.service_times.exists():
            self.fields["service_time"].queryset = event.service_times.all()
        else:
            del self.fields["service_time"]


class EventRegistrationForm(MemberEventForm):
    ticket = forms.ModelChoiceField(queryset=EventTicket.objects.none())

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        if event is not None:
            # Include full tickets: an existing reservation must be resumable.
            # register_for_ticket performs the authoritative capacity check.
            self.fields["ticket"].queryset = event.tickets.all()
