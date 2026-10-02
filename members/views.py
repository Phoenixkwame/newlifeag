from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from datetime import datetime

from care.forms import CareRequestForm
from churchapp.sms import send_sms
from churchapp.webhooks import authenticated_sms_webhook
from churchapp.validation import optional_id
from events.models import RSVP, Event
from events.services import cancel_volunteer_signup, conflicting_commitments_on
from giving.models import Donation, RecurringGiving
from maintenance.forms import MaintenanceRequestForm
from pathway.services import progress_for_member
from prayer.forms import PrayerRequestForm
from servicehours.forms import ServiceHourLogForm
from servicehours.models import ServiceHourLog
from servicehours.services import total_volunteer_hours, volunteer_badge
from sermons.models import Sermon
from surveys.forms import SurveyResponseForm
from surveys.models import Survey, SurveyAnswer, SurveyResponse
from testimonies.forms import TestimonyForm

from .feeds import build_all_day_event, build_calendar, build_event
from .forms import InterestSurveyForm, MemberPhotoForm, MemberProfileForm, NotificationPreferencesForm
from .models import (
    Attendance,
    Campus,
    Group,
    GroupLesson,
    GroupMembership,
    Member,
    ServingAssignment,
    SetListSong,
    Skill,
    SongSetList,
    TeamShoutout,
)
from .notifications import notify_group_of_shoutout
from .services import (
    attendance_streak_weeks,
    get_or_create_calendar_token,
    record_sms_checkin,
    record_sms_serving_response,
    regenerate_calendar_token,
    set_member_skills,
    streak_badge,
    suggested_groups_for,
)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_songs(raw):
    """
    Turns the set-list textarea's raw text into (title, key, ccli_number)
    tuples - one song per line, fields separated by "|" (key and CCLI are
    both optional, e.g. "Great Are You Lord | G | 6460220" or just
    "Great Are You Lord"). Blank lines are skipped; a line with no title at
    all (just stray "|" characters) is dropped rather than saved as an
    empty song.
    """
    songs = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        title = parts[0] if parts else ""
        if not title:
            continue
        key = parts[1] if len(parts) > 1 else ""
        ccli_number = parts[2] if len(parts) > 2 else ""
        songs.append((title, key, ccli_number))
    return songs


@login_required
def member_directory(request):
    """
    An opt-in directory of members who've chosen to be listed (see
    Member.share_in_directory) - separate from the staff-only member list in
    staff/views.py, which shows everyone regardless of this setting. A
    member's phone/email only shows here if they've separately opted into
    each one - being listed at all doesn't imply sharing contact details.

    Filterable by group/ministry, skill, and (once there's more than one)
    campus - same progressive-disclosure rule as every other campus filter
    in this project (Campus.objects.count() > 1), so a single-campus church
    never sees a campus dropdown with nothing useful to filter by.
    """
    directory_qs = Member.objects.filter(is_active=True, share_in_directory=True).prefetch_related("skills")

    query = request.GET.get("q", "").strip()
    if query:
        directory_qs = directory_qs.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query))

    group_id = request.GET.get("group", "").strip()
    if group_id:
        directory_qs = directory_qs.filter(
            memberships__group_id=group_id, memberships__left_date__isnull=True
        )

    skill_id = request.GET.get("skill", "").strip()
    if skill_id:
        directory_qs = directory_qs.filter(skills__id=optional_id(skill_id))

    show_campus_filter = Campus.objects.count() > 1
    campus_id = request.GET.get("campus", "").strip()
    if show_campus_filter and campus_id:
        directory_qs = directory_qs.filter(campus_id=optional_id(campus_id))

    return render(
        request,
        "members/directory.html",
        {
            "members": directory_qs.distinct(),
            "query": query,
            "groups": Group.objects.order_by("name"),
            "selected_group_id": group_id,
            "skills": Skill.objects.order_by("name"),
            "selected_skill_id": skill_id,
            "campuses": Campus.objects.all() if show_campus_filter else None,
            "selected_campus_id": campus_id,
        },
    )


@login_required
def dashboard(request):
    member = getattr(request.user, "member_profile", None)
    signups = []
    waitlist_entries = []
    rsvps = []
    donations = []
    prayer_requests = []
    my_groups = []
    pledges = []
    led_groups = []
    attendance_history = []
    recurring_gifts = []
    serving_assignments = []
    pathway_progress = []
    open_surveys = []
    service_hour_logs = []
    suggested_groups = []
    has_listed_interests = True
    current_streak_weeks = 0
    current_streak_badge = None
    testimonies = []
    member_total_volunteer_hours = 0
    member_volunteer_badge = None
    if member:
        signups = member.volunteer_signups.select_related("slot", "slot__event")
        waitlist_entries = member.volunteer_waitlist_entries.select_related("slot", "slot__event")
        rsvps = member.rsvps.select_related("event")
        # Only ever this member's own gifts - never another member's giving
        # history, which is exactly the kind of thing role-based admin
        # access (see the Treasurers group) exists to keep private too.
        donations = Donation.objects.filter(member=member).order_by("-date")[:10]
        prayer_requests = member.prayer_requests.all()[:10]
        my_groups = member.memberships.filter(left_date__isnull=True).select_related("group", "group__leader")
        pledges = member.pledges.select_related("campaign")
        # Groups this member leads get a "Take Attendance" link below -
        # nothing else about being a leader changes what the dashboard shows.
        led_groups = Group.objects.filter(leader=member)
        attendance_history = member.attendance_records.select_related("event", "group").order_by("-date")[:10]
        recurring_gifts = member.recurring_gifts.filter(is_active=True).select_related("campaign")
        serving_assignments = member.serving_assignments.filter(
            date__gte=timezone.localdate()
        ).select_related("group")[:5]
        pathway_progress = progress_for_member(member)
        # Surveys still open that this member hasn't already responded to -
        # once they respond, it drops off this list (see survey_respond
        # below and SurveyResponse's unique_together).
        open_surveys = Survey.objects.filter(is_open=True).exclude(responses__member=member)
        service_hour_logs = member.service_hour_logs.select_related("group", "event")[:10]
        suggested_groups = suggested_groups_for(member)[:3]
        has_listed_interests = member.skills.exists()
        current_streak_weeks = attendance_streak_weeks(member)
        current_streak_badge = streak_badge(current_streak_weeks)
        testimonies = member.testimonies.all()[:10]
        member_total_volunteer_hours = total_volunteer_hours(member)
        member_volunteer_badge = volunteer_badge(member_total_volunteer_hours)

    return render(
        request,
        "members/dashboard.html",
        {
            "member": member,
            "signups": signups,
            "waitlist_entries": waitlist_entries,
            "rsvps": rsvps,
            "donations": donations,
            "prayer_requests": prayer_requests,
            "prayer_form": PrayerRequestForm(),
            "care_form": CareRequestForm(),
            "maintenance_form": MaintenanceRequestForm(),
            "my_groups": my_groups,
            "pledges": pledges,
            "led_groups": led_groups,
            "attendance_history": attendance_history,
            "recurring_gifts": recurring_gifts,
            "serving_assignments": serving_assignments,
            "pathway_progress": pathway_progress,
            "open_surveys": open_surveys,
            "service_hour_logs": service_hour_logs,
            "service_hour_form": ServiceHourLogForm(),
            "suggested_groups": suggested_groups,
            "has_listed_interests": has_listed_interests,
            "current_streak_weeks": current_streak_weeks,
            "current_streak_badge": current_streak_badge,
            "testimonies": testimonies,
            "testimony_form": TestimonyForm(),
            "total_volunteer_hours": member_total_volunteer_hours,
            "volunteer_badge": member_volunteer_badge,
        },
    )


@login_required
def volunteer_signup_cancel(request, signup_id):
    """
    A member cancelling their own upcoming volunteer sign-up from their
    dashboard. Lives here (not events/views.py) since it's reached only from
    the member dashboard's own sign-ups list, the same "member's own
    self-service page" reasoning as the recurring giving cancel/reactivate
    views nearby. Reuses events/services.py's cancel_volunteer_signup, which
    also automatically promotes the next person on that slot's waitlist -
    see "Event waitlists" in the README.
    """
    member = getattr(request.user, "member_profile", None)
    if not member or request.method != "POST":
        return redirect("dashboard")

    cancelled, promoted_signup = cancel_volunteer_signup(signup_id=signup_id, member=member)
    if cancelled:
        messages.success(request, "Your volunteer sign-up was cancelled.")
        if promoted_signup is not None:
            messages.info(request, f"{promoted_signup.member} was automatically moved off the waitlist to fill the spot.")
    return redirect("dashboard")


@login_required
def edit_profile(request):
    """
    A member updating their own contact details. Only the fields on
    MemberProfileForm can change this way - role/campus/household/is_active
    stay staff-only (see StaffMemberForm), so this never lets a member grant
    themselves elevated access.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    if request.method == "POST":
        form = MemberProfileForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            set_member_skills(member, form.cleaned_data.get("skills_text", ""))
            messages.success(request, "Your profile was updated.")
            return redirect("edit_profile")
    else:
        form = MemberProfileForm(instance=member)

    return render(request, "members/edit_profile.html", {"form": form, "member": member})


@login_required
def account_settings(request):
    """
    A single page for the account-level things that don't belong on
    edit_profile (contact/directory details): notification preferences,
    a link to change your password (Django's own PasswordChangeView, see
    churchapp/urls.py), a link to download your own data
    (member_data_export below), and this member's personal calendar feed
    URL (member_calendar_feed below) - generated the first time this page
    is loaded (see get_or_create_calendar_token) so there's always
    something to show/copy here even before the member has ever opened it
    in a calendar app.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    if request.method == "POST":
        form = NotificationPreferencesForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            messages.success(request, "Your notification preferences were updated.")
            return redirect("account_settings")
    else:
        form = NotificationPreferencesForm(instance=member)

    calendar_feed_url = request.build_absolute_uri(
        reverse("member_calendar_feed", args=[get_or_create_calendar_token(member)])
    )
    return render(
        request,
        "members/account_settings.html",
        {"form": form, "member": member, "calendar_feed_url": calendar_feed_url},
    )


@login_required
def regenerate_calendar_link(request):
    """
    Issues this member a brand-new calendar_token, immediately invalidating
    whatever calendar app was subscribed to the old feed URL - for someone
    who's shared or exposed their old link and wants it to stop working.
    """
    member = getattr(request.user, "member_profile", None)
    if member and request.method == "POST":
        regenerate_calendar_token(member)
        messages.success(request, "Your calendar link was reset - update any calendar app subscribed to the old one.")
    return redirect("account_settings")


def member_calendar_feed(request, token):
    """
    A personal, no-login .ics feed of this member's own upcoming volunteer
    sign-ups, ministry-team serving assignments, and RSVP'd events - meant
    to be subscribed to once from a calendar app (Google Calendar, Apple
    Calendar, Outlook) rather than checked from the dashboard by hand.
    Looked up by the member's own calendar_token (see
    get_or_create_calendar_token) rather than a login, since a calendar app
    fetches a subscription URL on its own schedule with no session or
    credentials attached - the token itself is what makes the URL private.
    Declining to RSVP (RSVP.Status.NOT_GOING) is the one RSVP status
    deliberately excluded - nobody wants a "not going" show up on their own
    calendar.
    """
    member = get_object_or_404(Member, calendar_token=token)
    now = timezone.now()
    today = timezone.localdate()

    blocks = []
    for assignment in member.serving_assignments.filter(date__gte=today).select_related("group"):
        blocks.append(
            build_all_day_event(
                uid=f"serving-{assignment.id}@newlifeag",
                date=assignment.date,
                summary=f"Serving: {assignment.role} ({assignment.group})",
                description=assignment.notes,
            )
        )

    for signup in member.volunteer_signups.filter(slot__event__start_datetime__gte=now).select_related(
        "slot__event"
    ):
        event = signup.slot.event
        blocks.append(
            build_event(
                uid=f"volunteer-signup-{signup.id}@newlifeag",
                start=event.start_datetime,
                end=event.end_datetime,
                summary=f"Volunteering: {signup.slot.role_needed} - {event.title}",
                location=event.location,
                description=event.description,
            )
        )

    for rsvp in member.rsvps.exclude(status=RSVP.Status.NOT_GOING).filter(
        event__start_datetime__gte=now
    ).select_related("event"):
        event = rsvp.event
        blocks.append(
            build_event(
                uid=f"rsvp-{rsvp.id}@newlifeag",
                start=event.start_datetime,
                end=event.end_datetime,
                summary=event.title,
                location=event.location,
                description=event.description,
            )
        )

    response = HttpResponse(build_calendar(blocks), content_type="text/calendar")
    response["Content-Disposition"] = 'attachment; filename="my-schedule.ics"'
    return response


@login_required
def member_data_export(request):
    """
    Lets a member download a plain-text snapshot of their own data on
    file - profile details plus everything else this app tracks about them
    (giving, attendance, RSVPs, volunteering, pledges, prayer requests) -
    without needing to ask a Pastor to pull it for them. Deliberately a
    single flat text file rather than a formal per-model export: the point
    is transparency about what's on file, not a machine-readable backup
    (staff/services.py's full_backup_export already covers that, for every
    member at once, Pastor-only).
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    lines = [
        "Newlife AG - Your Data",
        f"Exported {timezone.localdate():%B %d, %Y}",
        "",
        "== Profile ==",
        f"Name: {member}",
        f"Email: {member.email or '(none on file)'}",
        f"Phone: {member.phone or '(none on file)'}",
        f"Household: {member.household or '(none)'}",
        f"Campus: {member.campus or '(none)'}",
        f"Member since: {member.date_joined:%B %d, %Y}",
        "",
        "== Completed Gifts ==",
    ]
    for donation in Donation.objects.filter(member=member, status=Donation.Status.COMPLETED).order_by("date"):
        lines.append(f"  {donation.date:%b %d, %Y} - GHS {donation.amount} ({donation.get_donation_type_display()})")
    if not member.donations.filter(status=Donation.Status.COMPLETED).exists():
        lines.append("  (none)")

    lines.append("")
    lines.append("== Attendance ==")
    for record in member.attendance_records.order_by("-date")[:100]:
        where = record.event or record.group or "General"
        lines.append(f"  {record.date:%b %d, %Y} - {where} - {'Present' if record.present else 'Absent'}")
    if not member.attendance_records.exists():
        lines.append("  (none)")

    lines.append("")
    lines.append("== Event RSVPs ==")
    for rsvp in member.rsvps.select_related("event").order_by("-event__start_datetime"):
        lines.append(f"  {rsvp.event} - {rsvp.get_status_display()}")
    if not member.rsvps.exists():
        lines.append("  (none)")

    lines.append("")
    lines.append("== Volunteer Sign-ups ==")
    for signup in member.volunteer_signups.select_related("slot", "slot__event"):
        lines.append(f"  {signup.slot.role_needed} for {signup.slot.event}")
    if not member.volunteer_signups.exists():
        lines.append("  (none)")

    lines.append("")
    lines.append("== Pledges ==")
    for pledge in member.pledges.select_related("campaign"):
        lines.append(f"  {pledge.campaign} - GHS {pledge.amount}")
    if not member.pledges.exists():
        lines.append("  (none)")

    lines.append("")
    lines.append("== Recurring Giving ==")
    for recurring in member.recurring_gifts.all():
        status = "Active" if recurring.is_active else "Cancelled"
        lines.append(f"  GHS {recurring.amount} {recurring.get_frequency_display()} - {status}")
    if not member.recurring_gifts.exists():
        lines.append("  (none)")

    lines.append("")
    lines.append("== Prayer Requests ==")
    for prayer_request in member.prayer_requests.order_by("-created_at"):
        lines.append(f"  {prayer_request.created_at:%b %d, %Y} - {prayer_request.request_text[:80]}")
    if not member.prayer_requests.exists():
        lines.append("  (none)")

    content = "\n".join(lines)
    response = HttpResponse(content, content_type="text/plain")
    response["Content-Disposition"] = f'attachment; filename="{member.first_name}_{member.last_name}_data.txt"'
    return response


@login_required
def interest_survey(request):
    """
    A short, standalone "tell us your interests" page aimed at a new member
    who hasn't filled anything in on their full profile yet (see
    edit_profile above, which has the same skills question buried further
    down a longer form). Saving here uses the exact same set_member_skills
    service, so it's just a friendlier front door to the same data - a
    member who's already listed skills on their profile sees them
    pre-filled here too. Immediately shows matching group suggestions below
    the form, using Group.interest_skills (see suggested_groups_for).
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    if request.method == "POST":
        form = InterestSurveyForm(request.POST)
        if form.is_valid():
            set_member_skills(member, form.cleaned_data.get("skills_text", ""))
            messages.success(request, "Thanks! Here's what we'd suggest based on your interests.")
            return redirect("interest_survey")
    else:
        form = InterestSurveyForm(initial={"skills_text": ", ".join(member.skills.values_list("name", flat=True))})

    return render(
        request,
        "members/interest_survey.html",
        {"form": form, "member": member, "suggested_groups": suggested_groups_for(member)},
    )


@login_required
def update_photo(request):
    """
    A member updating their own profile photo from the dashboard. Staff can
    also set/change a member's photo from the staff area's member form
    (see staff/forms.py's StaffMemberForm) - this is just the self-service
    path.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    if request.method == "POST":
        form = MemberPhotoForm(request.POST, request.FILES, instance=member)
        if form.is_valid():
            form.save()
            messages.success(request, "Your photo was updated.")
        else:
            messages.error(request, " ".join(form.errors.get("photo", ["Couldn't update your photo."])))
    return redirect("dashboard")


@login_required
def mark_attendance(request):
    from staff.services import scope_events, scope_members, staff_campus_for

    if not request.user.is_staff or not request.user.has_perms(("members.add_attendance", "members.change_attendance")):
        messages.error(request, "You don't have permission to mark attendance.")
        return redirect("dashboard")

    viewer_campus = staff_campus_for(request.user)
    events_qs = scope_events(Event.objects.all(), viewer_campus)
    events = events_qs.order_by("-start_datetime")[:20]
    event_id = optional_id(request.POST.get("event_id") or request.GET.get("event_id"))
    selected_event = get_object_or_404(events_qs, id=event_id) if event_id else None
    attendance_date = selected_event.start_datetime.date() if selected_event else timezone.localdate()

    # The campus selector only appears (and only matters) once a second
    # campus actually exists - see the Campus model's docstring.
    show_campus_filter = viewer_campus is None and Campus.objects.count() > 1
    campus_id = None
    if show_campus_filter:
        campus_id = optional_id(request.POST.get("campus_id") or request.GET.get("campus_id"))
    selected_campus = viewer_campus or (get_object_or_404(Campus, id=campus_id) if campus_id else None)

    members = scope_members(Member.objects.filter(is_active=True), viewer_campus)
    if selected_campus:
        members = members.filter(campus=selected_campus)

    # group__isnull=True excludes small-group-meeting attendance taken from
    # the portal (see group_attendance below) - those always have event=None
    # too, so without this a group's meeting attendance for today would
    # otherwise leak into "already marked present" here whenever this page's
    # event filter is also left as "general attendance" (event=None).
    already_present_ids = set(
        Attendance.objects.filter(
            event=selected_event, date=attendance_date, present=True, group__isnull=True
        ).values_list("member_id", flat=True)
    )

    if request.method == "POST" and "submit_attendance" in request.POST:
        present_ids = {optional_id(i) for i in request.POST.getlist("present_members")}
        for member in members:
            # group=None is passed explicitly (not just left to the model
            # default) so this lookup can never match a small-group-meeting
            # attendance row for the same member/date/event=None - see the
            # comment on already_present_ids just above.
            Attendance.objects.update_or_create(
                member=member,
                date=attendance_date,
                event=selected_event,
                group=None,
                defaults={"present": member.id in present_ids, "campus": selected_campus},
            )
        messages.success(request, f"Attendance saved for {attendance_date}.")
        params = []
        if event_id:
            params.append(f"event_id={event_id}")
        if campus_id:
            params.append(f"campus_id={campus_id}")
        if params:
            return redirect("/members/attendance/?" + "&".join(params))
        return redirect("mark_attendance")

    return render(
        request,
        "members/mark_attendance.html",
        {
            "events": events,
            "selected_event": selected_event,
            "members": members,
            "attendance_date": attendance_date,
            "already_present_ids": already_present_ids,
            "campuses": Campus.objects.all() if show_campus_filter else None,
            "selected_campus": selected_campus,
        },
    )


@authenticated_sms_webhook
def sms_checkin_webhook(request):
    """
    Called by the SMS provider whenever someone texts the church's number -
    same "read a handful of common field-name spellings" approach as
    giving/views.py's sms_giving_webhook, since exactly which field names a
    provider uses for the sender's number and message text isn't
    consistently documented. Always responds 200 OK, whether or not the
    text was a recognized check-in attempt, so a provider never retries a
    message it already delivered.
    """
    data = request.POST or request.GET
    phone = (
        data.get("From")
        or data.get("from")
        or data.get("Sender")
        or data.get("sender")
        or data.get("msisdn")
        or data.get("MSISDN")
        or ""
    )
    message_text = (
        data.get("Content")
        or data.get("content")
        or data.get("Text")
        or data.get("text")
        or data.get("Body")
        or data.get("message")
        or ""
    )

    attendance, error = record_sms_checkin(phone=phone, message_text=message_text)

    if attendance is not None:
        send_sms(phone, f"Newlife AG: You're checked in for today, {attendance.member.first_name}! Great to have you.")
    elif error == "no_matching_member":
        send_sms(
            phone,
            "Newlife AG: We couldn't match that number to a member on file - "
            "please contact the church office to check in, or update your phone number.",
        )
    # error == "not_a_checkin_message" is silently ignored, same as an
    # unrelated text to the giving number - not every text to this number
    # is meant for us.

    return HttpResponse("OK")


@authenticated_sms_webhook
def sms_serving_response_webhook(request):
    """
    Called by the SMS provider whenever a serving-team member replies
    YES/CONFIRM or NO/DECLINE to their serving reminder text (see
    members/notifications.py's send_serving_reminder and
    members/services.py's record_sms_serving_response) - same "read a
    handful of common field-name spellings" approach as this app's own
    sms_checkin_webhook above. Always responds 200 OK.
    """
    data = request.POST or request.GET
    phone = (
        data.get("From")
        or data.get("from")
        or data.get("Sender")
        or data.get("sender")
        or data.get("msisdn")
        or data.get("MSISDN")
        or ""
    )
    message_text = (
        data.get("Content")
        or data.get("content")
        or data.get("Text")
        or data.get("text")
        or data.get("Body")
        or data.get("message")
        or ""
    )

    assignment, error = record_sms_serving_response(phone=phone, message_text=message_text)

    if assignment is not None:
        if assignment.confirmation_status == assignment.ConfirmationStatus.CONFIRMED:
            reply = f"Newlife AG: Thanks, {assignment.member.first_name} - you're confirmed for {assignment.role} on {assignment.date:%b %d}."
        else:
            reply = f"Newlife AG: Got it, {assignment.member.first_name} - we've marked you as unable to serve on {assignment.date:%b %d}. Thanks for letting us know."
        send_sms(phone, reply)
    elif error == "no_matching_member":
        send_sms(phone, "Newlife AG: We couldn't match that number to a member on file - please contact the church office.")
    elif error == "no_pending_assignment":
        send_sms(phone, "Newlife AG: We couldn't find an upcoming serving assignment awaiting your reply.")
    # error == "not_a_response_message" is silently ignored, same as an
    # unrelated text to this project's other SMS keywords.

    return HttpResponse("OK")


def public_group_finder(request):
    """
    A public, no-login "find a small group" page - unlike browse_groups
    below (which needs a login so it can offer Join/Leave), this is meant
    for a visitor deciding whether to get involved at all. Only small
    groups are listed here (not every ministry/committee - see
    Group.GroupType) since those are what a newcomer is actually looking
    for; filterable by meeting day and a free-text match against
    meeting_location, since that's the closest thing this project has to a
    neighborhood/area field without adding a new one just for this. Shows
    no join/leave action - just enough to decide, with a nudge to sign up
    or log in to actually join.
    """
    groups = Group.objects.filter(group_type=Group.GroupType.SMALL_GROUP).select_related("leader").order_by("name")

    meeting_day = request.GET.get("day", "")
    if meeting_day in dict(Group.MeetingDay.choices):
        groups = groups.filter(meeting_day=meeting_day)
    else:
        meeting_day = ""

    area = request.GET.get("area", "").strip()
    if area:
        groups = groups.filter(meeting_location__icontains=area)

    return render(
        request,
        "members/public_group_finder.html",
        {
            "groups": groups,
            "meeting_day": meeting_day,
            "area": area,
            "meeting_days": Group.MeetingDay.choices,
        },
    )


@login_required
def browse_groups(request):
    """
    Self-service group directory - any logged-in member can see every
    ministry/small group/committee and join or leave one themselves, rather
    than needing a Pastor to add them from the staff area (staff can still
    do that too - see staff/views.py's group_add_member).
    """
    member = getattr(request.user, "member_profile", None)
    groups = (
        Group.objects.select_related("leader")
        .annotate(member_count=Count("memberships", filter=Q(memberships__left_date__isnull=True)))
        .order_by("name")
    )
    my_group_ids = set()
    if member:
        my_group_ids = set(
            member.memberships.filter(left_date__isnull=True).values_list("group_id", flat=True)
        )
    return render(
        request,
        "members/browse_groups.html",
        {"groups": groups, "my_group_ids": my_group_ids, "member": member},
    )


@login_required
def join_group(request, group_id):
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("browse_groups")

    group = get_object_or_404(Group, id=group_id)
    if request.method == "POST":
        # A member already in the group re-submitting (or a stale page)
        # should never be turned away by their own group being full - the
        # capacity check below only applies to someone not already active
        # in it. Staff adding someone over the phone (staff/views.py's
        # group_add_member) never runs this check at all - it's only ever
        # enforced against a member joining themselves.
        already_active = GroupMembership.objects.filter(
            member=member, group=group, left_date__isnull=True
        ).exists()
        if not already_active and group.is_full:
            messages.error(request, f"{group} is full - contact the group leader if you'd still like to join.")
            return redirect("browse_groups")
        # update_or_create (not a plain create) so rejoining a group left
        # earlier reactivates that same row instead of hitting the
        # (member, group) unique constraint - same reasoning as
        # staff/views.py's group_add_member.
        GroupMembership.objects.update_or_create(member=member, group=group, defaults={"left_date": None})
        messages.success(request, f"You joined {group}.")
    return redirect("browse_groups")


@login_required
def leave_group(request, group_id):
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("browse_groups")

    if request.method == "POST":
        membership = GroupMembership.objects.filter(
            member=member, group_id=group_id, left_date__isnull=True
        ).first()
        if membership:
            membership.left_date = timezone.localdate()
            membership.save(update_fields=["left_date"])
            messages.success(request, "You left the group.")
    return redirect("browse_groups")


@login_required
def group_attendance(request, group_id):
    """
    Lets a group's own leader take attendance for their weekly meeting
    straight from their dashboard - no staff access needed. Staff who can
    already mark attendance in the staff area (members.add_attendance, e.g.
    Ushers/Pastors) can use this too, since nothing about the staff-side
    "Mark Attendance" page lets them filter down to just one group's members.
    """
    group = get_object_or_404(Group, id=group_id)
    member = getattr(request.user, "member_profile", None)
    is_leader = member is not None and group.leader_id == member.id
    if not (is_leader or request.user.has_perm("members.add_attendance")):
        messages.error(request, "Only this group's leader can take its attendance.")
        return redirect("dashboard")

    attendance_date = timezone.localdate()
    memberships = group.memberships.filter(left_date__isnull=True).select_related("member").order_by(
        "member__last_name", "member__first_name"
    )
    already_present_ids = set(
        Attendance.objects.filter(group=group, date=attendance_date, present=True).values_list(
            "member_id", flat=True
        )
    )

    if request.method == "POST" and "submit_attendance" in request.POST:
        present_ids = {int(i) for i in request.POST.getlist("present_members")}
        for membership in memberships:
            # event=None is explicit here too, for the same reason group=None
            # is explicit in mark_attendance above - it keeps this lookup
            # from ever colliding with a Sunday-service attendance row for
            # the same member/date.
            Attendance.objects.update_or_create(
                member=membership.member,
                date=attendance_date,
                event=None,
                group=group,
                defaults={"present": membership.member_id in present_ids},
            )
        messages.success(request, f"Attendance saved for {group} on {attendance_date}.")
        return redirect("group_attendance", group_id=group.id)

    return render(
        request,
        "members/group_attendance.html",
        {
            "group": group,
            "memberships": memberships,
            "attendance_date": attendance_date,
            "already_present_ids": already_present_ids,
        },
    )


@login_required
def serving_schedule(request, group_id):
    """
    Lets a group's own leader schedule who's serving in what role on which
    upcoming date - the same "leader self-service, no staff access needed"
    pattern as group_attendance above, for recurring weekly team lineups
    (e.g. the worship or ushering team) rather than one-off event volunteer
    slots (see events/models.py's VolunteerSlot for those).
    """
    group = get_object_or_404(Group, id=group_id)
    member = getattr(request.user, "member_profile", None)
    is_leader = member is not None and group.leader_id == member.id
    if not (is_leader or request.user.has_perm("members.add_servingassignment")):
        messages.error(request, "Only this group's leader can manage its serving schedule.")
        return redirect("dashboard")

    roster = (
        Member.objects.filter(memberships__group=group, memberships__left_date__isnull=True)
        .distinct()
        .order_by("last_name", "first_name")
    )

    if request.method == "POST":
        # member_id can arrive as an empty string (no member chosen in the
        # dropdown yet), which .filter(id=...) can't coerce to a number -
        # treat that the same as "no member selected" below.
        member_id = request.POST.get("member_id") or ""
        assigned_member = roster.filter(id=optional_id(member_id)).first() if member_id else None
        role = request.POST.get("role", "").strip()
        assignment_date = _parse_date(request.POST.get("date", ""))
        notes = request.POST.get("notes", "").strip()
        if not assigned_member or not role or not assignment_date:
            messages.error(request, "Please choose a member, a role, and a valid date.")
        else:
            assignment, created = ServingAssignment.objects.get_or_create(
                group=group,
                member=assigned_member,
                role=role,
                date=assignment_date,
                defaults={"notes": notes},
            )
            messages.success(request, f"{assigned_member} was scheduled to serve as {role} on {assignment_date}.")
            if created:
                for conflict in conflicting_commitments_on(
                    assigned_member, assignment_date, exclude_assignment_id=assignment.id
                ):
                    messages.warning(request, conflict)
        return redirect("serving_schedule", group_id=group.id)

    upcoming = group.serving_assignments.filter(date__gte=timezone.localdate()).select_related("member")
    return render(
        request,
        "members/serving_schedule.html",
        {"group": group, "roster": roster, "upcoming": upcoming},
    )


@login_required
def survey_respond(request, survey_id):
    """
    A member answering every question on one open Survey in a single POST -
    the field set is built per-survey by SurveyResponseForm (see
    surveys/forms.py), since a static form class can't know a survey's
    questions ahead of time. One SurveyResponse (and one SurveyAnswer per
    question) is created per member per survey - see SurveyResponse's
    unique_together, which is why this redirects home once already answered
    rather than letting a second submission through.
    """
    member = getattr(request.user, "member_profile", None)
    if not member:
        messages.error(request, "No member profile is linked to your login yet.")
        return redirect("dashboard")

    survey = get_object_or_404(Survey, id=survey_id, is_open=True)
    if SurveyResponse.objects.filter(survey=survey, member=member).exists():
        messages.info(request, "You've already responded to this survey.")
        return redirect("dashboard")

    if request.method == "POST":
        form = SurveyResponseForm(survey, request.POST)
        if form.is_valid():
            response = SurveyResponse.objects.create(survey=survey, member=member)
            for question in survey.questions.all():
                field_name = form.question_field_names[question.id]
                value = form.cleaned_data.get(field_name)
                if question.question_type == question.QuestionType.CHOICE:
                    SurveyAnswer.objects.create(response=response, question=question, choice=value)
                else:
                    SurveyAnswer.objects.create(response=response, question=question, text_answer=value or "")
            messages.success(request, f"Thanks for responding to \"{survey.title}\".")
            return redirect("dashboard")
    else:
        form = SurveyResponseForm(survey)
    return render(request, "members/survey_respond.html", {"survey": survey, "form": form})


@login_required
def group_lessons(request, group_id):
    """
    A group's weekly lesson/discussion questions - viewable by any current
    member of the group, posted only by the group's own leader (or staff
    with the matching permission), same leader-self-service pattern as
    group_attendance and serving_schedule above.
    """
    group = get_object_or_404(Group, id=group_id)
    member = getattr(request.user, "member_profile", None)
    is_leader = member is not None and group.leader_id == member.id
    is_member = member is not None and group.memberships.filter(member=member, left_date__isnull=True).exists()
    can_post = is_leader or request.user.has_perm("members.add_grouplesson")

    if not (is_member or is_leader or request.user.has_perm("members.view_grouplesson")):
        messages.error(request, "Only this group's own members can view its lessons.")
        return redirect("dashboard")

    if request.method == "POST":
        if not can_post:
            messages.error(request, "Only this group's leader can post a lesson.")
            return redirect("group_lessons", group_id=group.id)
        title = request.POST.get("title", "").strip()
        week_of = _parse_date(request.POST.get("week_of", ""))
        content = request.POST.get("content", "").strip()
        if not title or not week_of or not content:
            messages.error(request, "Please fill in a title, week, and the lesson content.")
        else:
            GroupLesson.objects.create(group=group, title=title, week_of=week_of, content=content, posted_by=member)
            messages.success(request, f"\"{title}\" was posted for {group}.")
        return redirect("group_lessons", group_id=group.id)

    lessons = group.lessons.select_related("posted_by")
    latest_discussion_guide_sermon = Sermon.objects.exclude(discussion_guide="").order_by("-date").first()
    return render(
        request,
        "members/group_lessons.html",
        {
            "group": group,
            "lessons": lessons,
            "can_post": can_post,
            "latest_discussion_guide_sermon": latest_discussion_guide_sermon,
        },
    )


@login_required
def group_set_list(request, group_id):
    """
    A worship (or any) team's planned song lineup for an upcoming service -
    viewable by any current member of the group, postable only by the
    group's own leader (or staff with the matching permission), same
    leader-self-service pattern as group_lessons above. Re-posting for a
    date that already has a set list replaces its songs entirely, rather
    than appending to them - simplest to reason about for a leader
    adjusting the lineup during the week.
    """
    group = get_object_or_404(Group, id=group_id)
    member = getattr(request.user, "member_profile", None)
    is_leader = member is not None and group.leader_id == member.id
    is_member = member is not None and group.memberships.filter(member=member, left_date__isnull=True).exists()
    can_post = is_leader or request.user.has_perm("members.add_songsetlist")

    if not (is_member or is_leader or request.user.has_perm("members.view_songsetlist")):
        messages.error(request, "Only this group's own members can view its set lists.")
        return redirect("dashboard")

    if request.method == "POST":
        if not can_post:
            messages.error(request, "Only this group's leader can plan its set list.")
            return redirect("group_set_list", group_id=group.id)
        date = _parse_date(request.POST.get("date", ""))
        notes = request.POST.get("notes", "").strip()
        songs = _parse_songs(request.POST.get("songs", ""))
        if not date or not songs:
            messages.error(request, "Please pick a date and list at least one song.")
        else:
            set_list, _created = SongSetList.objects.update_or_create(
                group=group, date=date, defaults={"notes": notes, "posted_by": member}
            )
            set_list.songs.all().delete()
            SetListSong.objects.bulk_create(
                [
                    SetListSong(set_list=set_list, order=index, title=title, key=key, ccli_number=ccli_number)
                    for index, (title, key, ccli_number) in enumerate(songs)
                ]
            )
            messages.success(request, f"Set list for {date} saved.")
        return redirect("group_set_list", group_id=group.id)

    set_lists = group.song_set_lists.prefetch_related("songs")
    return render(
        request,
        "members/group_set_list.html",
        {"group": group, "set_lists": set_lists, "can_post": can_post},
    )


@login_required
def group_shoutouts(request, group_id):
    """
    A quick thank-you/heads-up a group's own leader posts to just that
    group's active members - pushed out by email/SMS the moment it's
    posted (see members/notifications.py's notify_group_of_shoutout),
    unlike group_lessons above which a member only sees by visiting the
    page. Same leader-self-service permission pattern as group_lessons.
    """
    group = get_object_or_404(Group, id=group_id)
    member = getattr(request.user, "member_profile", None)
    is_leader = member is not None and group.leader_id == member.id
    is_member = member is not None and group.memberships.filter(member=member, left_date__isnull=True).exists()
    can_post = is_leader or request.user.has_perm("members.add_teamshoutout")

    if not (is_member or is_leader or request.user.has_perm("members.view_teamshoutout")):
        messages.error(request, "Only this group's own members can view its shoutouts.")
        return redirect("dashboard")

    if request.method == "POST":
        if not can_post:
            messages.error(request, "Only this group's leader can post a shoutout.")
            return redirect("group_shoutouts", group_id=group.id)
        text = request.POST.get("message", "").strip()
        if not text:
            messages.error(request, "Please write a message before posting.")
        else:
            shoutout = TeamShoutout.objects.create(group=group, message=text, posted_by=member)
            contacted = notify_group_of_shoutout(shoutout)
            messages.success(request, f"Shoutout posted and sent to {contacted} team member(s).")
        return redirect("group_shoutouts", group_id=group.id)

    shoutouts = group.shoutouts.select_related("posted_by")
    return render(
        request, "members/group_shoutouts.html", {"group": group, "shoutouts": shoutouts, "can_post": can_post}
    )
