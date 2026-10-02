from django import forms

from members.models import Group

from .models import ServiceHourLog

DATE_LOCAL_FORMAT = "%Y-%m-%d"


class ServiceHourLogForm(forms.ModelForm):
    """A volunteer logging their own hours from the dashboard - member is set in the view, not chosen here."""

    class Meta:
        model = ServiceHourLog
        fields = ["date", "hours", "role", "group", "event", "notes"]
        widgets = {
            "date": forms.DateInput(format=DATE_LOCAL_FORMAT, attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].input_formats = [DATE_LOCAL_FORMAT]
        self.fields["group"].required = False
        self.fields["group"].queryset = Group.objects.order_by("name")
        self.fields["event"].required = False
        self.fields["notes"].required = False
