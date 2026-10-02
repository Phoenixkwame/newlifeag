"""
CSV bulk-import logic for members, kept out of the view so it can be tested
directly without going through a real file upload. The single-model member
export doesn't need a service of its own - it's a straightforward
query-to-CSV in the view (see staff/views.py's member_export). The full
multi-model backup export below is complex enough to be worth its own
testable function instead.
"""

import csv
import io
import zipfile
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from care.models import CareRequest
from decisions.models import Decision
from events.models import Event, VolunteerSlot
from expenses.models import Expense
from followup.models import FollowUp
from giving.models import Donation
from giving.services import lapsed_recurring_gifts
from members.models import Attendance, Campus, Household, Member, ServingAssignment
from members.services import absentee_members
from milestones.models import BabyDedication, BaptismRecord, FuneralRecord, TransferLetter, WeddingRecord

TRUE_VALUES = {"yes", "y", "true", "1"}
FALSE_VALUES = {"no", "n", "false", "0"}


@dataclass
class ImportResult:
    created: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _parse_bool(value, default=True):
    value = (value or "").strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    return default


def import_members_csv(uploaded_file):
    """
    Expects a CSV with a header row. Only first_name and last_name are
    required - everything else is optional. household and campus are matched
    by exact (case-insensitive) name against existing records; a name that
    doesn't match anything existing is left blank rather than silently
    creating a new household/campus from a typo. Never overwrites or removes
    anything - every successful row is a brand-new Member, and a row that
    can't be created (missing name, bad data) is skipped and reported, not
    partially applied.
    """
    result = ImportResult()

    try:
        # Decode and parse before creating any rows: a bad byte near the end
        # must not leave a partially imported file behind.
        text_stream = io.StringIO(uploaded_file.read().decode("utf-8-sig"))
        reader = csv.DictReader(text_stream, strict=True)
        rows = list(reader)
    except (UnicodeDecodeError, AttributeError, csv.Error):
        result.errors.append("Couldn't read that file - please upload a plain CSV file.")
        return result

    if not reader.fieldnames:
        result.errors.append("That file doesn't look like a CSV - no header row was found.")
        return result

    households_by_name = {h.name.strip().lower(): h for h in Household.objects.all() if h.name}
    campuses_by_name = {c.name.strip().lower(): c for c in Campus.objects.all()}

    for row_number, row in enumerate(rows, start=2):  # row 1 is the header
        first_name = (row.get("first_name") or "").strip()
        last_name = (row.get("last_name") or "").strip()
        if not first_name or not last_name:
            result.errors.append(f"Row {row_number}: missing first_name or last_name - skipped.")
            continue

        role = (row.get("role") or "").strip().lower()
        if role not in dict(Member.Role.choices):
            role = Member.Role.MEMBER

        household = households_by_name.get((row.get("household") or "").strip().lower())
        campus = campuses_by_name.get((row.get("campus") or "").strip().lower())

        member = Member.objects.create(
            first_name=first_name,
            last_name=last_name,
            email=(row.get("email") or "").strip(),
            phone=(row.get("phone") or "").strip(),
            role=role,
            household=household,
            campus=campus,
            is_active=_parse_bool(row.get("is_active"), default=True),
        )
        result.created.append(member)

    return result


# --- Full data backup export -------------------------------------------------
#
# A single "Full Data Backup" download (see staff/views.py's
# full_backup_export, Pastor-only) bundling CSVs of the church's core data
# into one ZIP for offsite/manual backup - beyond the existing member-only
# CSV export above. Deliberately not a full-fidelity dump of every model in
# the project (background checks, care requests, prayer requests, surveys,
# and so on stay out) - this covers the data a church would most need to
# reconstruct after data loss: membership, households, attendance, and both
# sides of its finances. Django's own `dumpdata` management command already
# covers a full, exact JSON fixture of every table, for a developer who
# needs that instead.


def _csv_string(header, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue()


def _members_backup_csv():
    rows = (
        [
            member.first_name,
            member.last_name,
            member.email,
            member.phone,
            member.role,
            member.household.name if member.household else "",
            member.campus.name if member.campus else "",
            "yes" if member.is_active else "no",
            member.date_joined,
        ]
        for member in Member.objects.select_related("household", "campus").order_by("last_name", "first_name")
    )
    return _csv_string(
        ["first_name", "last_name", "email", "phone", "role", "household", "campus", "is_active", "date_joined"],
        rows,
    )


def _households_backup_csv():
    rows = ([household.name, household.address, household.phone] for household in Household.objects.order_by("name"))
    return _csv_string(["name", "address", "phone"], rows)


def _attendance_backup_csv():
    rows = (
        [
            str(record.member),
            record.date,
            str(record.event) if record.event else "",
            str(record.group) if record.group else "",
            str(record.campus) if record.campus else "",
            "yes" if record.present else "no",
        ]
        for record in Attendance.objects.select_related("member", "event", "group", "campus").order_by("-date")
    )
    return _csv_string(["member", "date", "event", "group", "campus", "present"], rows)


def _donations_backup_csv():
    rows = (
        [
            str(donation.member) if donation.member else "Anonymous",
            donation.amount,
            donation.donation_type,
            donation.status,
            str(donation.campaign) if donation.campaign else "",
            str(donation.campus) if donation.campus else "",
            donation.date,
        ]
        for donation in Donation.objects.select_related("member", "campaign", "campus").order_by("-date")
    )
    return _csv_string(["member", "amount", "donation_type", "status", "campaign", "campus", "date"], rows)


def _expenses_backup_csv():
    rows = (
        [
            expense.date,
            expense.amount,
            str(expense.category) if expense.category else "",
            expense.paid_to,
            expense.description,
            str(expense.campus) if expense.campus else "",
        ]
        for expense in Expense.objects.select_related("category", "campus").order_by("-date")
    )
    return _csv_string(["date", "amount", "category", "paid_to", "description", "campus"], rows)


def _events_backup_csv():
    rows = (
        [
            event.title,
            event.get_event_type_display(),
            event.start_datetime,
            event.end_datetime or "",
            event.location,
            str(event.campus) if event.campus else "",
        ]
        for event in Event.objects.select_related("campus").order_by("-start_datetime")
    )
    return _csv_string(["title", "event_type", "start_datetime", "end_datetime", "location", "campus"], rows)


def build_full_backup_zip():
    """
    Builds the full backup ZIP entirely in memory (nothing touches disk) and
    returns its bytes, ready to hand straight to an HttpResponse. Six CSVs:
    members, households, attendance, donations, expenses, events.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("members.csv", _members_backup_csv())
        zip_file.writestr("households.csv", _households_backup_csv())
        zip_file.writestr("attendance.csv", _attendance_backup_csv())
        zip_file.writestr("donations.csv", _donations_backup_csv())
        zip_file.writestr("expenses.csv", _expenses_backup_csv())
        zip_file.writestr("events.csv", _events_backup_csv())
    return buffer.getvalue()


def backup_filename():
    return f"newlife-ag-backup-{timezone.localdate():%Y-%m-%d}.zip"


# --- "This week at a glance" staff home widget -------------------------------
#
# One consolidated card on staff/home.html summarizing what needs attention
# in the next 7 days, so a staff member doesn't have to open half a dozen
# separate tabs (Events, Care Requests, Follow-Up, Absentees, Lapsed Givers)
# just to get their bearings for the week. Deliberately returns everything
# unconditionally, like build_weekly_digest() does - staff_home is what
# decides which pieces a given viewer is actually allowed to see (the same
# per-permission gating it already applies to the stats row above), rather
# than this function trying to know about permissions itself.
WEEK_AHEAD_WINDOW = timedelta(days=7)


def this_week_at_a_glance(campus=None):
    """
    campus, when given, restricts the Members/Attendance-and-Events/Giving
    pieces of this widget to that campus (see the campus-restriction helpers
    below) - serving assignments, care requests, and follow-ups are left
    unscoped, same as household_list/household_detail, since they aren't
    part of the three areas campus restriction covers.
    """
    now = timezone.now()
    week_from_now = now + WEEK_AHEAD_WINDOW

    events_this_week_qs = scope_events(
        Event.objects.filter(start_datetime__gte=now, start_datetime__lte=week_from_now), campus
    )
    events_this_week = list(events_this_week_qs.select_related("campus").order_by("start_datetime"))

    volunteer_gaps_this_week = [
        slot
        for slot in VolunteerSlot.objects.filter(
            event__in=events_this_week_qs
        ).select_related("event")
        if slot.spots_remaining > 0
    ]

    serving_this_week = list(
        ServingAssignment.objects.filter(
            date__gte=timezone.localdate(), date__lte=week_from_now.date()
        ).select_related("member", "group").order_by("date")
    )

    pending_care_requests = list(
        CareRequest.objects.exclude(status=CareRequest.Status.COMPLETED).select_related("member")
    )

    new_followups = list(FollowUp.objects.filter(stage=FollowUp.Stage.NEW).select_related("member"))

    return {
        "events_this_week": events_this_week,
        "volunteer_gaps_this_week": volunteer_gaps_this_week,
        "serving_this_week": serving_this_week,
        "pending_care_requests": pending_care_requests,
        "new_followups": new_followups,
        "absentees": absentee_members(campus=campus),
        "lapsed_givers": lapsed_recurring_gifts(campus=campus),
    }


# --- Annual denominational statistics report ---------------------------------
#
# The headline numbers a Pastor pulls together once a year for reporting up
# to district/national Assemblies of God leadership - milestones, salvation
# decisions, membership growth, average attendance, and total giving for one
# calendar year, all in one place instead of opening half a dozen separate
# staff pages and adding them up by hand. Purely a read-only rollup of data
# staff have already recorded elsewhere - it never creates or changes
# anything.


def annual_statistics(year):
    """
    Everything is filtered by the relevant date field's __year, so a record
    counts toward the year it actually happened in, not the year it was
    entered into the system.
    """
    baptisms = BaptismRecord.objects.filter(baptism_date__year=year).count()
    weddings = WeddingRecord.objects.filter(wedding_date__year=year).count()
    funerals = FuneralRecord.objects.filter(service_date__year=year).count()
    baby_dedications = BabyDedication.objects.filter(dedication_date__year=year).count()
    transfer_letters = TransferLetter.objects.filter(transfer_date__year=year).count()

    decision_type_labels = dict(Decision.DecisionType.choices)
    decision_counts = {
        row["decision_type"]: row["total"]
        for row in Decision.objects.filter(date__year=year)
        .values("decision_type")
        .annotate(total=Count("id"))
    }
    decisions_by_type = [
        {"label": label, "count": decision_counts.get(value, 0)} for value, label in decision_type_labels.items()
    ]
    total_decisions = sum(decision_counts.values())

    new_members = Member.objects.filter(date_joined__year=year).count()

    # Average attendance per church-wide service date recorded this year -
    # counts a Sunday-service-style Attendance row (event set or unset, but
    # never a small group's own meeting - see Attendance.group's docstring
    # for why a row never has both) grouped by date, then averages across
    # however many distinct dates were actually recorded, rather than
    # dividing by 52 - a church that didn't record attendance every single
    # week still gets an honest average of the weeks it did.
    attendance_by_date = (
        Attendance.objects.filter(present=True, date__year=year, group__isnull=True)
        .values("date")
        .annotate(total=Count("id"))
    )
    service_dates_recorded = len(attendance_by_date)
    total_attendance = sum(row["total"] for row in attendance_by_date)
    average_attendance = round(total_attendance / service_dates_recorded) if service_dates_recorded else 0

    total_giving = (
        Donation.objects.filter(status=Donation.Status.COMPLETED, date__year=year).aggregate(total=Sum("amount"))[
            "total"
        ]
        or Decimal("0.00")
    )

    return {
        "year": year,
        "baptisms": baptisms,
        "weddings": weddings,
        "funerals": funerals,
        "baby_dedications": baby_dedications,
        "transfer_letters": transfer_letters,
        "decisions_by_type": decisions_by_type,
        "total_decisions": total_decisions,
        "new_members": new_members,
        "service_dates_recorded": service_dates_recorded,
        "average_attendance": average_attendance,
        "total_giving": total_giving,
    }


# --- Campus-based staff restriction -------------------------------------------
#
# Multi-campus churches may want a Usher/Treasurer/Pastor account to only see
# their own campus's members, attendance/events, and giving - rather than
# every staff account seeing the whole church. This is opt-in in effect: it
# only ever kicks in once there's more than one Campus AND the staff user is
# actually linked to a Member with a campus assigned. Every other case
# deliberately "fails open" (sees everything) rather than risking locking
# someone out because of a data-setup gap:
#   - Single-campus churches (or no campuses at all) are entirely unaffected.
#   - A superuser always sees everything, regardless of their own campus.
#   - A staff account with no linked Member (member_profile), or a linked
#     Member with no campus set, sees everything - we don't know which
#     campus to restrict them to, so we don't guess.
#
# staff_campus_for() below returns either the Campus a user is restricted to,
# or None meaning "unrestricted - show everything". Every view that should
# respect this passes its result into the matching scope_*() helper.


def staff_campus_for(user):
    """
    Returns the Campus a staff user's data should be scoped to, or None if
    they should see everything (see module docstring above for exactly when
    that is).
    """
    if not user or not user.is_authenticated or user.is_superuser:
        return None
    if Campus.objects.count() <= 1:
        return None
    member = getattr(user, "member_profile", None)
    if member is None or member.campus_id is None:
        return None
    return member.campus


def _scope_with_all_campuses_fallback(queryset, campus):
    """
    Shows a record to a scoped viewer when it matches their campus, or when
    its own campus is unset. Used for two different reasons depending on the
    model: Event/GivingCampaign's null campus legitimately *means*
    "applies to every campus"; Member's null campus instead means "not yet
    assigned" (e.g. right after a church switches on multi-campus and hasn't
    finished sorting existing members into campuses yet) - but the same
    fail-open rule applies either way, so a data-setup gap never hides a
    member from every scoped staff account until someone gets around to
    assigning them a campus.
    """
    if campus is None:
        return queryset
    return queryset.filter(Q(campus=campus) | Q(campus__isnull=True))


def scope_members(queryset, campus):
    return _scope_with_all_campuses_fallback(queryset, campus)


def scope_events(queryset, campus):
    return _scope_with_all_campuses_fallback(queryset, campus)


def scope_giving_campaigns(queryset, campus):
    return _scope_with_all_campuses_fallback(queryset, campus)


def _scope_with_member_campus_fallback(queryset, campus, anonymous_ok=False):
    """
    For records (Attendance, Donation) whose own campus field is only set
    when a staff member actively chose one at entry time - meaning plenty of
    legitimate records have campus=None even at a multi-campus church. Falls
    back to the linked member's own campus in that case, rather than hiding
    the record from every campus's staff - and if that member's own campus
    is *also* unset (the same data-setup-gap case scope_members fails open
    on), the record stays visible rather than being hidden for a doubly
    unknown reason. anonymous_ok additionally shows a truly member-less
    null-campus record (e.g. an anonymous donation) to everyone, since
    there's no member to fall back to at all.
    """
    if campus is None:
        return queryset
    condition = (
        Q(campus=campus)
        | Q(campus__isnull=True, member__campus=campus)
        | Q(campus__isnull=True, member__campus__isnull=True)
    )
    if anonymous_ok:
        condition |= Q(campus__isnull=True, member__isnull=True)
    return queryset.filter(condition)


def scope_attendance(queryset, campus):
    return _scope_with_member_campus_fallback(queryset, campus)


def scope_donations(queryset, campus):
    return _scope_with_member_campus_fallback(queryset, campus, anonymous_ok=True)


def scope_by_member_campus(queryset, campus):
    """
    For Pledge/RecurringGiving, which have no campus field of their own -
    scoped entirely by the linked member's campus, failing open (matching
    in_member_campus_scope below) when that member has no campus set, or
    somehow has no member at all.
    """
    if campus is None:
        return queryset
    return queryset.filter(Q(member__campus=campus) | Q(member__campus__isnull=True) | Q(member__isnull=True))


def in_campus_scope(record_campus, campus):
    """
    Object-level check for a single record's own campus field (used on
    detail/edit pages, where a queryset filter isn't in play): True if the
    viewer is unrestricted, or the record's campus matches, or (matching the
    fallback rules above) the record's campus is unset.
    """
    if campus is None:
        return True
    return record_campus is None or record_campus == campus


def in_member_campus_scope(member, campus):
    """
    Object-level check for a record scoped by *its member's* campus (an
    Attendance/Donation row with no campus of its own, or a Pledge/
    RecurringGiving, which never has one) - mirrors the fallback rules in
    _scope_with_member_campus_fallback but for a single object.
    """
    if campus is None:
        return True
    if member is None:
        return True
    return member.campus_id is None or member.campus_id == campus.id


def in_attendance_donation_scope(record, campus, anonymous_ok=False):
    """
    Object-level check for a single Attendance or Donation record, mirroring
    _scope_with_member_campus_fallback's fallback-to-member-campus rule: in
    scope if the record's own campus matches, or its campus is unset and
    either it has no member (only meaningful when anonymous_ok, e.g. an
    anonymous Donation) or its member's own campus matches.
    """
    if campus is None:
        return True
    if record.campus_id is not None:
        return record.campus_id == campus.id
    member = getattr(record, "member", None)
    if member is None:
        return anonymous_ok
    return in_member_campus_scope(member, campus)
