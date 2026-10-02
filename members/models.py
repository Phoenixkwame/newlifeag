from django.conf import settings
from django.db import models


class Campus(models.Model):
    """
    A branch/campus of the church. Most churches only ever have one, so
    every campus field and filter across the app (member/event/donation
    forms, list filters, the public events page) stays hidden until a
    second Campus row exists - see the `Campus.objects.count() > 1` checks
    in staff/forms.py, giving/forms.py, staff/views.py, and events/views.py.
    This management screen itself is never hidden that way - it's reachable
    any time by the normal members.view_campus/add_campus/change_campus
    permissions (see setup_groups.py), so a church can set up its second
    campus before anything else notices it exists.
    """

    name = models.CharField(max_length=150, help_text="e.g. 'Tema Main' or 'Spintex Branch'")
    address = models.CharField(max_length=255, blank=True)
    service_times = models.CharField(
        max_length=255, blank=True, help_text="e.g. 'Sundays 8:00am & 10:30am'"
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Campuses"

    def __str__(self):
        return self.name


class Household(models.Model):
    name = models.CharField(max_length=150, blank=True, help_text="e.g. 'The Mensah Family'")
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.name or f"Household #{self.pk}"


class Skill(models.Model):
    """
    A skill or spiritual gift a member can list on their profile (e.g.
    "Music", "Hospitality", "Teaching") - set from a free-text comma-
    separated field on the member's own profile form, not managed on its
    own, same pattern as sermons.Tag. See members/services.py's
    set_member_skills.
    """

    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Member(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"
        MEMBER = "member", "Member"

    # Optional link to a login account. Not every member needs to log in
    # (e.g. children, or members who never use the app themselves).
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="member_profile",
        help_text="Linked login account, if this member has one.",
    )
    household = models.ForeignKey(
        Household, on_delete=models.SET_NULL, null=True, blank=True, related_name="members"
    )
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
        help_text="Which branch/campus this member belongs to (only relevant once there's more than one).",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    date_joined = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    photo = models.ImageField(
        upload_to="member_photos/",
        null=True,
        blank=True,
        help_text="A profile photo, shown on the dashboard and in the staff area.",
    )
    # Both optional and both null=True (not just blank=True) - unlike the
    # meeting_day/meeting_location CharFields on Group, a nullable DateField
    # needs no explicit default for makemigrations to apply cleanly against
    # existing rows, since NULL is already a valid value for every one of
    # them. Used by the staff "Birthdays & Anniversaries" dashboard below.
    date_of_birth = models.DateField(null=True, blank=True, help_text="Used for the staff birthdays dashboard.")
    anniversary_date = models.DateField(
        null=True, blank=True, help_text="Wedding anniversary, if applicable - used for the same dashboard."
    )
    # Tracks the date (not just a boolean) an automatic greeting was last
    # sent, so send_birthday_greetings/send_anniversary_greetings (see
    # members/management/commands/) can run daily without ever double-
    # greeting the same person on the same birthday/anniversary if it's
    # accidentally run more than once in a day.
    last_birthday_greeting_sent = models.DateField(null=True, blank=True)
    last_anniversary_greeting_sent = models.DateField(null=True, blank=True)
    # Opt-in member directory (see members/views.py's member_directory) - off
    # by default for everyone, same privacy-first default as is_public on
    # PrayerRequest. The phone/email flags are independent of each other and
    # of share_in_directory itself, so a member can appear in the directory
    # with just their name/photo and share nothing else. default=False on
    # all three (rather than leaving Django to ask) means this applies
    # cleanly against a table that already has Member rows in it.
    share_in_directory = models.BooleanField(
        default=False, help_text="Show me in the member directory other logged-in members can browse."
    )
    share_phone_in_directory = models.BooleanField(
        default=False, help_text="Also show my phone number to other members in the directory."
    )
    share_email_in_directory = models.BooleanField(
        default=False, help_text="Also show my email address to other members in the directory."
    )
    # Opt-out of bulk staff Announcements (see announcements/services.py's
    # send_announcement, which skips a member on the channel they've turned
    # off) - default=True since these are the same broadcast messages
    # sending SMS/email at all already implies consent to. Deliberately
    # scoped to Announcements specifically, not every notification this app
    # sends: an announcement is the one genuinely optional "the whole church
    # gets this" broadcast; a reminder tied to something the member did
    # themselves (an RSVP, a serving assignment, a recurring gift) isn't
    # touched by this - see "Member self-service account settings" in the
    # README for the reasoning.
    notify_by_email = models.BooleanField(
        default=True, help_text="Email me church-wide announcements."
    )
    notify_by_sms = models.BooleanField(
        default=True, help_text="Text me church-wide announcements."
    )
    # The four flags below extend the opt-out above from "announcements
    # only" to a handful of other outbound categories - but each one is
    # scoped to a proactive nudge the church sends *unprompted* after the
    # fact, never an immediate confirmation of something the member just
    # did. An RSVP confirmation, a volunteer sign-up confirmation, and a
    # ticket registration confirmation stay untouched by any of these -
    # opting out of "volunteer reminders" turns off the day-before nudge,
    # not the confirmation you get the moment you sign up. See "Member
    # communication preferences" in the README for the full reasoning.
    notify_volunteer_reminders = models.BooleanField(
        default=True, help_text="Remind me by email/text the day before I'm scheduled to volunteer."
    )
    notify_pledge_reminders = models.BooleanField(
        default=True,
        help_text="Remind me by email/text about an outstanding pledge or a recurring gift that's due.",
    )
    notify_giving_receipts = models.BooleanField(
        default=True, help_text="Email me a receipt whenever a gift of mine is recorded as completed."
    )
    notify_prayer_updates = models.BooleanField(
        default=True, help_text="Email/text me when the pastoral team has prayed for a request I submitted."
    )
    # Free-text-managed, same "reuse case-insensitively, create if new" story
    # as sermons.Tag/set_sermon_tags - see members/services.py's
    # set_member_skills. blank=True since most members won't fill this in
    # right away.
    skills = models.ManyToManyField(
        "Skill",
        blank=True,
        related_name="members",
        help_text="Skills or spiritual gifts (e.g. music, hospitality, teaching) - lets staff find a volunteer for a specific need.",
    )
    # Left unset (null, not "") for almost every member until they first
    # open their own personal calendar feed - see members/services.py's
    # get_or_create_calendar_token, which lazily generates one, and
    # members/views.py's member_calendar_feed, the no-login .ics feed it
    # authenticates. null=True (not just blank=True) is deliberate: with a
    # unique constraint, every not-yet-generated member needs SQL NULL here
    # rather than "", since a plain CharField default of "" would collide
    # with every other member who also hasn't generated one yet.
    calendar_token = models.CharField(max_length=40, null=True, blank=True, unique=True, editable=False)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def initials(self):
        """Fallback shown wherever a photo would go, for a member with none."""
        return f"{self.first_name[:1]}{self.last_name[:1]}".upper()


class Group(models.Model):
    class GroupType(models.TextChoices):
        MINISTRY = "ministry", "Ministry"
        SMALL_GROUP = "small_group", "Small Group"
        COMMITTEE = "committee", "Committee"

    class MeetingDay(models.TextChoices):
        MONDAY = "mon", "Monday"
        TUESDAY = "tue", "Tuesday"
        WEDNESDAY = "wed", "Wednesday"
        THURSDAY = "thu", "Thursday"
        FRIDAY = "fri", "Friday"
        SATURDAY = "sat", "Saturday"
        SUNDAY = "sun", "Sunday"

    name = models.CharField(max_length=150)
    group_type = models.CharField(max_length=20, choices=GroupType.choices, default=GroupType.SMALL_GROUP)
    description = models.TextField(blank=True)
    leader = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="groups_led"
    )
    # Optional meeting schedule - mainly useful for small groups/cell groups,
    # but left open to any group type since ministries and committees have
    # regular meetings too. All three are blank/optional, and a group with
    # none of them set just shows no schedule anywhere. default="" on the two
    # CharFields (rather than leaving Django to ask for one) means running
    # makemigrations against a database that already has Group rows in it
    # doesn't stop to prompt for a default value.
    meeting_day = models.CharField(max_length=3, choices=MeetingDay.choices, blank=True, default="")
    meeting_time = models.TimeField(null=True, blank=True, help_text="When this group typically meets.")
    meeting_location = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Where this group typically meets, e.g. a room or a member's home.",
    )
    # Lets a Pastor tag a group with the skills/interests it's looking for
    # (from the same Skill pool a member lists on their own profile - see
    # set_member_skills), so the interest survey can suggest "Worship Team"
    # to a member who listed "Music" without any other matching logic.
    interest_skills = models.ManyToManyField(
        Skill,
        blank=True,
        related_name="interested_groups",
        help_text="Skills/interests this group is looking for - used to suggest it to a member who's listed a matching one.",
    )
    # Optional, same "blank means no limit" convention as the ticketed
    # event's own nullable `capacity` field (events/models.py) - rather than
    # forcing every existing group to suddenly have a cap. Only
    # ever enforced against a member joining *themselves* (see
    # members/views.py's join_group) - a Pastor/leader adding someone from
    # the staff area (staff/views.py's group_add_member) can always go over
    # it, the same "staff can override a member-facing limit" reasoning as
    # event ticketing.
    max_members = models.PositiveIntegerField(
        null=True, blank=True, help_text="Optional cap on active members. Leave blank for no limit."
    )

    def __str__(self):
        return self.name

    @property
    def active_member_count(self):
        return self.memberships.filter(left_date__isnull=True).count()

    @property
    def is_full(self):
        return self.max_members is not None and self.active_member_count >= self.max_members


class GroupMembership(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="memberships")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="memberships")
    joined_date = models.DateField(auto_now_add=True)
    # Set (not deleted) when someone leaves a group - staff roles are
    # deliberately never given delete permission on anything (see
    # setup_groups), so "removing" a member from a group here means marking
    # when they left, not erasing the record of their ever having been in it.
    left_date = models.DateField(
        null=True, blank=True, help_text="Left blank while the member is still active in this group."
    )

    class Meta:
        unique_together = ("member", "group")
        ordering = ["-joined_date"]

    @property
    def is_active(self):
        return self.left_date is None

    def __str__(self):
        return f"{self.member} in {self.group}"


class Attendance(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="attendance_records")
    date = models.DateField()
    event = models.ForeignKey(
        "events.Event",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
    )
    # Which specific service this attendance was for, on a multi-service
    # event - see events.EventServiceTime. Left blank for a single-service
    # event (the overwhelming majority) and always blank when this is
    # general or group attendance rather than tied to a specific event.
    service_time = models.ForeignKey(
        "events.EventServiceTime",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
    )
    # Set instead of event when this is a small group/ministry meeting's
    # attendance rather than a Sunday service - taken by the group's own
    # leader from their dashboard (see members/views.py's group_attendance),
    # not in the staff area. A row never has both event and group set.
    group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
        help_text="The small group/ministry this attendance was taken for, if any.",
    )
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_records",
        help_text="Which campus this attendance record was taken at, if tracked by campus.",
    )
    present = models.BooleanField(default=True)

    class Meta:
        # group added alongside event so a member's Sunday-service record and
        # any small-group-meeting record for the same date never collide -
        # see the group_isnull=True/event_isnull=True disambiguation in the
        # two update_or_create() call sites (members/views.py's
        # mark_attendance and group_attendance) that rely on this.
        unique_together = ("member", "date", "event", "group")
        ordering = ["-date"]

    def __str__(self):
        status = "present" if self.present else "absent"
        return f"{self.member} - {self.date} ({status})"


class MemberNote(models.Model):
    """
    A private, staff-only running log of notes on a member - pastoral
    conversations, follow-up context, anything worth remembering for next
    time - shown chronologically on their staff detail page. Deliberately
    separate from care.CareRequest: a care request is the member's own
    submitted request for prayer/counseling, with its own status/assignment
    workflow, while this is staff's own free-form journal about a member,
    never seen by the member themselves. Pastor-only (see setup_groups.py's
    PASTOR_MODELS) - the same sensitivity as pastoral care requests, just a
    different, simpler shape (no status, no assignment - just an
    append-only timeline).
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="staff_notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
        help_text="Which staff member wrote this note.",
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Note on {self.member} ({self.created_at:%Y-%m-%d})"


class ServingAssignment(models.Model):
    """
    A member scheduled to serve in a specific role on a specific date for a
    ministry team - the existing Group model above (e.g. "Worship Team",
    "Ushering Team"), reused here rather than a new team model. This is
    deliberately separate from events/models.py's VolunteerSlot/
    VolunteerSignup, which cover one-off volunteer needs tied to a specific
    Event (e.g. extra hands for a Christmas program); this is for the
    ordinary, recurring weekly lineup of who's serving on a team - often for
    a regular Sunday service that was never itself created as an Event row.
    """

    class ConfirmationStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        DECLINED = "declined", "Declined"

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="serving_assignments")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="serving_assignments")
    role = models.CharField(max_length=100, help_text='e.g. "Vocals", "Sound", "Usher".')
    date = models.DateField(help_text="Which service date this assignment is for.")
    notes = models.TextField(blank=True)
    # Mirrors VolunteerSignup.reminder_sent_at - a date, not just a boolean,
    # so the daily send_serving_reminders command can run more than once
    # without ever double-reminding the same assignment.
    reminder_sent_at = models.DateField(null=True, blank=True)
    # Set by the member replying YES/CONFIRM or NO/DECLINE to their reminder
    # text (see members/services.py's record_sms_serving_response and the
    # sms_serving_response_webhook it's called from) - a reminder they
    # simply can't reply to otherwise. Never reset automatically once set,
    # so a leader can trust that a Confirmed/Declined status reflects the
    # member's own most recent word on it.
    confirmation_status = models.CharField(
        max_length=10, choices=ConfirmationStatus.choices, default=ConfirmationStatus.PENDING
    )

    class Meta:
        ordering = ["date"]
        unique_together = ("group", "member", "role", "date")

    def __str__(self):
        return f"{self.member} - {self.role} ({self.group}, {self.date})"


class GroupLesson(models.Model):
    """
    A week's lesson/discussion questions a small group's own leader posts for
    their group - viewable by any current member of that group (not just the
    leader), from /members/groups/<id>/lessons/ (see members/views.py's
    group_lessons). Same leader-self-service pattern as group_attendance and
    serving_schedule above.
    """

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=200)
    week_of = models.DateField(help_text="Which week this lesson is for.")
    content = models.TextField(help_text="Lesson notes and/or discussion questions.")
    posted_by = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-week_of"]

    def __str__(self):
        return f"{self.title} ({self.group}, week of {self.week_of})"


class TeamShoutout(models.Model):
    """
    A quick thank-you or heads-up a group's own leader (or a Pastor) posts
    to just that group's own active members - from
    /members/groups/<id>/shoutouts/ (see members/views.py's
    group_shoutouts). Same leader-self-service permission pattern as
    GroupLesson above, but distinct from it in purpose: a lesson is
    something a member checks when they visit the group's page; a shoutout
    is actively pushed out by email/SMS the moment it's posted (see
    members/notifications.py's notify_group_of_shoutout), the way the
    church-wide Announcement model pushes to everyone/a campus/a group -
    this is that same idea scoped down to one team, postable by the team's
    own leader rather than a Pastor only.
    """

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="shoutouts")
    message = models.TextField(help_text="Keep it short - this goes out by email/SMS to the whole team.")
    posted_by = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Shoutout to {self.group} ({self.created_at:%Y-%m-%d})"


class SongSetList(models.Model):
    """
    A single service's song lineup that a worship team's own leader plans
    ahead of time - viewable by any current member of the team, same
    leader-self-service pattern as GroupLesson/TeamShoutout above. A set
    list groups several ordered songs (see SetListSong below) under one
    date, so - unlike GroupLesson, which is one flat row per week's
    lesson - it needs a small container/detail pair rather than a single
    model. One per group per date (see unique_together): re-planning the
    same Sunday replaces that date's set list rather than creating a
    second one (see members/views.py's group_set_list).
    """

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="song_set_lists")
    date = models.DateField(help_text="Which service date this set list is for.")
    notes = models.TextField(blank=True, help_text="Notes for the team - theme, transitions, anything else.")
    posted_by = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]
        unique_together = ["group", "date"]

    def __str__(self):
        return f"{self.group} set list ({self.date})"


class SetListSong(models.Model):
    """One ordered song within a SongSetList - see that model's docstring."""

    set_list = models.ForeignKey(SongSetList, on_delete=models.CASCADE, related_name="songs")
    order = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=200)
    key = models.CharField(max_length=10, blank=True, help_text='Musical key, e.g. "G", "D".')
    ccli_number = models.CharField(max_length=20, blank=True, help_text="CCLI song number, if known.")

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class StaffLoginAttempt(models.Model):
    """Shared across workers/sessions so restarting login cannot reset guesses."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token = models.CharField(max_length=64)
    started_at = models.DateTimeField()
    failures = models.PositiveSmallIntegerField(default=0)
    consumed = models.BooleanField(default=False)
