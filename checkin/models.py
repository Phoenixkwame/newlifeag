from django.conf import settings
from django.db import models
from django.utils import timezone

from members.models import Household, Member


class Child(models.Model):
    """
    A child in children's ministry. Deliberately NOT a Member - children
    don't get their own login - but linked to a Household so the family
    (and a phone number to call, via the household or its members) can be
    found at pickup time.
    """

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="children")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    allergies_or_medical_notes = models.TextField(
        blank=True,
        help_text="Shown to children's ministry staff at check-in - allergies, medical conditions, anything they need to know.",
    )
    is_active = models.BooleanField(
        default=True, help_text="Turn off once a child has aged out or the family has left, rather than deleting them."
    )

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def age(self):
        """Whole years old as of today, or None if no birth date is on file."""
        if not self.date_of_birth:
            return None
        today = timezone.localdate()
        years = today.year - self.date_of_birth.year
        if (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day):
            years -= 1
        return years


class CheckIn(models.Model):
    """
    One drop-off-to-pickup record for a child. pickup_code is generated at
    check-in (see checkin/services.py) and must be typed back in correctly
    to check the child back out - the safety check that ties this feature
    together, so only whoever holds the matching tag can pick the child up.
    """

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="check_ins")
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_check_ins",
        help_text="Which service/event this check-in was for, if it was tied to one.",
    )
    guardian_name = models.CharField(
        max_length=150, help_text="Whoever dropped this child off - in case it's not a parent already on file."
    )
    pickup_code = models.CharField(max_length=6, editable=False)
    checked_in_at = models.DateTimeField(auto_now_add=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_check_ins_recorded",
    )
    checked_out_at = models.DateTimeField(null=True, blank=True)
    checked_out_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_check_outs_recorded",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-checked_in_at"]

    @property
    def is_checked_in(self):
        return self.checked_out_at is None

    def __str__(self):
        return f"{self.child} checked in {self.checked_in_at:%Y-%m-%d %H:%M}"


class SundaySchoolClass(models.Model):
    """
    A children's ministry class (e.g. "Toddlers", "Ages 5-7") - deliberately
    separate from the small-group `Group` model in members/models.py, since
    children aren't Members and don't have a login. Managed entirely from the
    staff area (Children's Ministry/Pastors only, see setup_groups.py) -
    unlike a small group's own leader, a Sunday school teacher doesn't get a
    separate self-service portal here.
    """

    name = models.CharField(max_length=100, help_text='e.g. "Toddlers", "Ages 5-7"')
    description = models.TextField(blank=True)
    teacher = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="taught_sunday_school_classes",
    )
    children = models.ManyToManyField(Child, blank=True, related_name="sunday_school_classes")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SundaySchoolLesson(models.Model):
    """A week's curriculum/lesson plan for one Sunday school class - same shape as members.GroupLesson."""

    sunday_school_class = models.ForeignKey(SundaySchoolClass, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=200)
    week_of = models.DateField(help_text="Which week this lesson is for.")
    scripture_reference = models.CharField(max_length=200, blank=True)
    content = models.TextField(help_text="Lesson plan/curriculum notes for teachers.")
    posted_by = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-week_of"]

    def __str__(self):
        return f"{self.title} ({self.sunday_school_class}, week of {self.week_of})"
