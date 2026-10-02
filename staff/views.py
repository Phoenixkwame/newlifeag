import calendar
import csv
import io
from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

import qrcode
from django.contrib import messages
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractDay, ExtractMonth, ExtractYear, TruncMonth, TruncWeek
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from churchapp.validation import optional_id

from announcements.models import Announcement, AnnouncementDelivery
from announcements.services import audience_queryset, send_announcement
from booking.models import Resource, ResourceBooking
from booking.services import conflicting_bookings
from care.models import CareRequest
from checkin.models import Child, CheckIn, SundaySchoolClass
from checkin.services import WrongPickupCodeError, check_in_child, check_out_child
from decisions.models import Decision
from decisions.services import record_decision
from equipment.models import Equipment, EquipmentCheckout
from library.models import LibraryItem, LibraryLoan
from events.models import Event, EventRegistration, EventServiceTime, EventTicket, VolunteerSlot
from events.services import generate_recurring_occurrences
from expenses.models import BudgetCategory, Expense
from flyers.models import Flyer
from followup.models import FollowUp, VisitorInfo
from followup.services import log_contact, stale_follow_ups, start_follow_up
from giving.forms import DonationForm
from governance.models import ActionItem, Meeting
from giving.models import Donation, GivingCampaign, RecurringGiving
from giving.notifications import notify_treasurers_of_pending_donation, send_pledge_reminder
from giving.services import lapsed_recurring_gifts, mark_donation_completed
from livestream.models import LiveStream
from maintenance.models import MaintenanceRequest
from members.models import Attendance, Campus, Group, GroupMembership, Household, Member, MemberNote
from members.pdfs import build_membership_certificate_pdf
from members.services import (
    ABSENTEE_WEEKS,
    absentee_members,
    bulk_set_household_active,
    bulk_set_household_campus,
    bulk_sync_household_phone,
)
from milestones.models import BabyDedication, BaptismRecord, FuneralRecord, TransferLetter, WeddingRecord
from pathway.models import PathwayStep
from pathway.services import mark_step_complete, mark_step_incomplete, progress_for_member
from prayer.models import PrayerRequest
from prayer.services import mark_prayed_for
from screening.models import BackgroundCheck, VolunteerTraining
from sermons.models import Devotional, Sermon, SermonSeries
from sermons.services import set_sermon_tags
from servicehours.models import ServiceHourLog
from servicehours.pdfs import build_service_hour_certificate_pdf
from suggestions.models import Suggestion
from suggestions.services import mark_reviewed
from testimonies.models import Testimony
from testimonies.services import approve_testimony
from surveys.models import Survey, SurveyChoice, SurveyQuestion
from surveys.services import aggregate_results

from .decorators import staff_member_required, staff_permission_required
from .forms import (
    StaffActionItemForm,
    StaffAnnouncementForm,
    StaffBabyDedicationForm,
    StaffBackgroundCheckForm,
    StaffBaptismRecordForm,
    StaffBudgetCategoryForm,
    StaffCampusForm,
    StaffCareRequestUpdateForm,
    StaffCheckInForm,
    StaffCheckOutForm,
    StaffChildForm,
    StaffContactAttemptForm,
    StaffDecisionForm,
    StaffDevotionalForm,
    StaffEquipmentCheckoutForm,
    StaffEquipmentForm,
    StaffEventForm,
    StaffEventServiceTimeForm,
    StaffEventTicketForm,
    StaffExpenseForm,
    StaffFlyerForm,
    StaffFollowUpStageForm,
    StaffFuneralRecordForm,
    StaffGivingCampaignForm,
    StaffGroupForm,
    StaffHouseholdForm,
    StaffLibraryItemForm,
    StaffLibraryLoanForm,
    StaffLiveStreamForm,
    StaffMaintenanceRequestForm,
    StaffMeetingForm,
    StaffMemberForm,
    StaffMemberNoteForm,
    StaffPathwayStepForm,
    StaffPrayerAssignForm,
    StaffResourceBookingForm,
    StaffResourceForm,
    StaffSermonForm,
    StaffSermonSeriesForm,
    StaffServiceHourLogForm,
    StaffSundaySchoolClassForm,
    StaffSundaySchoolLessonForm,
    StaffSurveyChoiceForm,
    StaffSurveyForm,
    StaffSurveyQuestionForm,
    StaffTransferLetterForm,
    StaffVisitorInfoForm,
    StaffVolunteerSlotForm,
    StaffVolunteerTrainingForm,
    StaffWeddingRecordForm,
)
from .services import (
    annual_statistics,
    backup_filename,
    build_full_backup_zip,
    import_members_csv,
    in_attendance_donation_scope,
    in_campus_scope,
    in_member_campus_scope,
    scope_attendance,
    scope_by_member_campus,
    scope_donations,
    scope_events,
    scope_giving_campaigns,
    scope_members,
    staff_campus_for,
    this_week_at_a_glance,
)


@staff_member_required
def staff_home(request):
    # A scoped staff account (see staff/services.py's staff_campus_for) only
    # counts its own campus's members/events/attendance/donations here -
    # None (the common case: single-campus churches, superusers, or a staff
    # account with no campus of its own) leaves every stat unrestricted.
    viewer_campus = staff_campus_for(request.user)
    stats = {
        "active_members": scope_members(Member.objects.filter(is_active=True), viewer_campus).count(),
        "upcoming_events": scope_events(
            Event.objects.filter(start_datetime__gte=timezone.now()), viewer_campus
        ).count(),
        "today_attendance": scope_attendance(
            Attendance.objects.filter(date=timezone.localdate(), present=True), viewer_campus
        ).count(),
    }
    # Donations are deliberately left out unless the viewer can actually see
    # them - Treasurers-only data shouldn't leak into a stat an Usher can
    # read just by opening the staff home page.
    if request.user.has_perm("giving.view_donation"):
        stats["pending_donations"] = scope_donations(
            Donation.objects.filter(status=Donation.Status.PENDING), viewer_campus
        ).count()
    if request.user.has_perm("checkin.view_checkin"):
        stats["children_checked_in"] = CheckIn.objects.filter(checked_out_at__isnull=True).count()

    # "This week at a glance" - built once (a handful of queries) and then
    # trimmed down to just what this viewer is allowed to see, the same
    # permission-gating approach already used for the stats row above (e.g.
    # pending_donations). A viewer with none of the underlying permissions
    # gets an empty dict, so the template simply doesn't render the card.
    glance = {}
    needs_glance = any(
        request.user.has_perm(perm)
        for perm in (
            "events.view_event",
            "members.view_servingassignment",
            "care.view_carerequest",
            "followup.view_followup",
            "members.view_attendance",
            "giving.view_recurringgiving",
        )
    )
    if needs_glance:
        weekly = this_week_at_a_glance(campus=viewer_campus)
        if request.user.has_perm("events.view_event"):
            glance["events_this_week"] = weekly["events_this_week"]
            glance["volunteer_gaps_this_week"] = weekly["volunteer_gaps_this_week"]
        if request.user.has_perm("members.view_servingassignment"):
            glance["serving_this_week"] = weekly["serving_this_week"]
        if request.user.has_perm("care.view_carerequest"):
            glance["pending_care_requests"] = weekly["pending_care_requests"]
        if request.user.has_perm("followup.view_followup"):
            glance["new_followups"] = weekly["new_followups"]
        if request.user.has_perm("members.view_attendance"):
            glance["absentees"] = weekly["absentees"]
        if request.user.has_perm("giving.view_recurringgiving"):
            glance["lapsed_givers"] = weekly["lapsed_givers"]

    return render(request, "staff/home.html", {"stats": stats, "glance": glance, "active_tab": "overview"})


# --- Members ----------------------------------------------------------------

@staff_permission_required("members.view_member")
def member_list(request):
    members_qs = Member.objects.select_related("household", "campus").prefetch_related("skills").order_by(
        "last_name", "first_name"
    )

    # A staff account restricted to one campus (see staff/services.py's
    # staff_campus_for) only ever sees that campus's members - applied
    # before the optional filter below so a scoped viewer can't use the
    # ?campus= param to reach another campus's data.
    viewer_campus = staff_campus_for(request.user)
    members_qs = scope_members(members_qs, viewer_campus)

    query = request.GET.get("q", "").strip()
    if query:
        members_qs = members_qs.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query))

    # Lets a Pastor find every member who's listed a given skill/spiritual
    # gift on their profile (see MemberProfileForm's skills_text field) -
    # e.g. everyone who's listed "Sound Engineering" when a slot needs
    # filling.
    skill_query = request.GET.get("skill", "").strip()
    if skill_query:
        members_qs = members_qs.filter(skills__name__icontains=skill_query).distinct()

    status = request.GET.get("status")
    if status == "inactive":
        members_qs = members_qs.filter(is_active=False)
    elif status == "active":
        members_qs = members_qs.filter(is_active=True)

    # Campus filtering only makes sense - and is only offered - once a
    # second campus actually exists, and only to an unrestricted viewer (a
    # campus-scoped viewer already sees just their own campus, so offering
    # them a filter that could only ever narrow to zero campuses beyond
    # their own would be pointless clutter, not a bypass - the mandatory
    # scope above already applies regardless of this param).
    show_campus_filter = viewer_campus is None and Campus.objects.count() > 1
    campus_id = request.GET.get("campus", "") if show_campus_filter else ""
    if campus_id:
        members_qs = members_qs.filter(campus_id=optional_id(campus_id))

    page_obj = Paginator(members_qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/member_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "skill_query": skill_query,
            "status": status,
            "campus_id": campus_id,
            "campuses": Campus.objects.all() if show_campus_filter else None,
            "can_add": request.user.has_perm("members.add_member"),
            "active_tab": "members",
        },
    )


@staff_permission_required("members.view_member")
def member_detail(request, member_id):
    member = get_object_or_404(
        Member.objects.select_related("household", "campus").prefetch_related("skills"), id=member_id
    )
    # A campus-scoped staff account (see staff_campus_for) can't view a
    # member outside their own campus - a 404 rather than a 403, same as a
    # nonexistent member, so a scoped viewer can't tell the difference
    # between "doesn't exist" and "not yours to see".
    if not in_campus_scope(member.campus, staff_campus_for(request.user)):
        raise Http404("Member not found.")
    attendance_records = member.attendance_records.select_related("event", "group").order_by("-date")[:15]

    pathway_progress = None
    if request.user.has_perm("pathway.view_memberpathwayprogress"):
        pathway_progress = progress_for_member(member)

    # Milestones (baby dedications, weddings) this member is part of - shown
    # as a read-only history card, same "only compute/show if permitted"
    # rule as pathway_progress above.
    dedications = None
    weddings = None
    if request.user.has_perm("milestones.view_babydedication"):
        dedications = member.baby_dedications.all()
    if request.user.has_perm("milestones.view_weddingrecord"):
        weddings = (member.weddings_as_spouse_one.all() | member.weddings_as_spouse_two.all()).order_by(
            "-wedding_date"
        )
    baptisms = None
    if request.user.has_perm("milestones.view_baptismrecord"):
        baptisms = member.baptism_records.all()

    transfer_letters = None
    if request.user.has_perm("milestones.view_transferletter"):
        transfer_letters = member.transfer_letters.all()

    member_decisions = None
    if request.user.has_perm("decisions.view_decision"):
        member_decisions = member.decisions.select_related("event")

    # Unlike dedications/weddings (querysets, where None vs. empty already
    # distinguishes "no permission" from "no records"), funeral_record is a
    # single object - getattr(..., None) is also how "no record yet" reads,
    # so can_view_funeral_record is passed separately to gate the card itself.
    can_view_funeral_record = request.user.has_perm("milestones.view_funeralrecord")
    funeral_record = getattr(member, "funeral_record", None) if can_view_funeral_record else None

    care_requests = None
    if request.user.has_perm("care.view_carerequest"):
        care_requests = member.care_requests.all()

    # Children's Ministry gets view-only here (to confirm a volunteer is
    # cleared before letting them serve with kids) - Pastors get full
    # view/add/change (see PASTOR_MODELS and setup_groups.py).
    background_checks = None
    if request.user.has_perm("screening.view_backgroundcheck"):
        background_checks = member.background_checks.all()

    # Same permission split as background checks just above.
    trainings = None
    if request.user.has_perm("screening.view_volunteertraining"):
        trainings = member.trainings.all()

    # Pastor-only private staff notes - see MemberNote's docstring for how
    # this differs from a care request. can_add_note is passed separately
    # from the notes themselves (rather than just checking "if notes is not
    # None") so the empty "no notes yet" state can still offer the form.
    member_notes = None
    can_add_note = request.user.has_perm("members.add_membernote")
    if request.user.has_perm("members.view_membernote"):
        member_notes = member.staff_notes.select_related("author")

    return render(
        request,
        "staff/member_detail.html",
        {
            "member": member,
            "attendance_records": attendance_records,
            "can_edit": request.user.has_perm("members.change_member"),
            "follow_up": getattr(member, "follow_up", None),
            "can_start_follow_up": request.user.has_perm("followup.add_followup"),
            "pathway_progress": pathway_progress,
            "can_change_pathway": request.user.has_perm("pathway.change_memberpathwayprogress"),
            "dedications": dedications,
            "weddings": weddings,
            "baptisms": baptisms,
            "can_add_baptism_record": request.user.has_perm("milestones.add_baptismrecord"),
            "transfer_letters": transfer_letters,
            "can_add_transfer_letter": request.user.has_perm("milestones.add_transferletter"),
            "member_decisions": member_decisions,
            "can_add_decision": request.user.has_perm("decisions.add_decision"),
            "funeral_record": funeral_record,
            "can_view_funeral_record": can_view_funeral_record,
            "can_add_funeral_record": request.user.has_perm("milestones.add_funeralrecord"),
            "care_requests": care_requests,
            "background_checks": background_checks,
            "can_add_background_check": request.user.has_perm("screening.add_backgroundcheck"),
            "trainings": trainings,
            "can_add_training": request.user.has_perm("screening.add_volunteertraining"),
            "member_notes": member_notes,
            "can_add_note": can_add_note,
            "note_form": StaffMemberNoteForm() if can_add_note else None,
            "active_tab": "members",
        },
    )


@staff_permission_required("members.view_member")
def member_id_card(request, member_id):
    """
    A printable member ID card - name, photo (or initials, same fallback as
    everywhere else a member's avatar shows), member-since date, and a QR
    code (member_id_card_qr below) linking back to this member's own staff
    detail page, so scanning the card at a check-in table pulls it straight
    up. Same view/print permission as member_detail itself - this is just a
    printable form of data already visible there.
    """
    member = get_object_or_404(Member, id=optional_id(member_id))
    return render(request, "staff/member_id_card.html", {"member": member})


@staff_permission_required("members.view_member")
def member_id_card_qr(request, member_id):
    """
    Renders a PNG QR code encoding this member's staff detail page URL -
    same server-side qrcode-library approach as events.views.event_qr_code,
    gated behind the same permission as the card itself since, unlike an
    event's public check-in link, this points at identifiable member data.
    """
    member = get_object_or_404(Member, id=optional_id(member_id))
    detail_url = request.build_absolute_uri(reverse("staff_member_detail", args=[member.id]))
    image = qrcode.make(detail_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")


@staff_permission_required("members.view_member")
def membership_certificate_pdf(request, member_id):
    """
    A downloadable "Certificate of Membership" PDF for a member who needs
    proof of church membership for something outside the church (a visa or
    school application, a loan, a new job) - see members/pdfs.py. Same
    view/print permission as member_detail and the ID card above - this is
    just another printable/downloadable form of data already visible there.
    """
    member = get_object_or_404(Member, id=optional_id(member_id))
    pdf_bytes = build_membership_certificate_pdf(member, timezone.localdate())
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    filename = f"membership-certificate-{member.last_name}-{member.first_name}.pdf".replace(" ", "-")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@staff_permission_required("members.add_membernote")
def member_note_create(request, member_id):
    member = get_object_or_404(Member, id=optional_id(member_id))
    if request.method == "POST":
        form = StaffMemberNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.member = member
            note.author = request.user
            note.save()
            messages.success(request, "Note added.")
    return redirect("staff_member_detail", member_id=member.id)


@staff_permission_required("pathway.change_memberpathwayprogress")
def mark_pathway_step(request, member_id, step_id):
    member = get_object_or_404(Member, id=optional_id(member_id))
    step = get_object_or_404(PathwayStep, id=step_id)
    if request.method == "POST":
        if request.POST.get("action") == "incomplete":
            mark_step_incomplete(member, step)
            messages.success(request, f"{step.name} was marked not yet completed for {member}.")
        else:
            mark_step_complete(member, step, user=request.user)
            messages.success(request, f"{step.name} was marked completed for {member}.")
    return redirect("staff_member_detail", member_id=member.id)


@staff_permission_required("pathway.view_pathwaystep")
def pathway_step_list(request):
    steps = PathwayStep.objects.all()
    return render(
        request,
        "staff/pathway_step_list.html",
        {"steps": steps, "can_add": request.user.has_perm("pathway.add_pathwaystep"), "active_tab": "members"},
    )


@staff_permission_required("pathway.add_pathwaystep")
def pathway_step_create(request):
    if request.method == "POST":
        form = StaffPathwayStepForm(request.POST)
        if form.is_valid():
            step = form.save()
            messages.success(request, f"{step.name} was added to the pathway.")
            return redirect("staff_pathway_step_list")
    else:
        form = StaffPathwayStepForm()
    return render(request, "staff/pathway_step_form.html", {"form": form, "is_new": True, "active_tab": "members"})


@staff_permission_required("pathway.change_pathwaystep")
def pathway_step_edit(request, step_id):
    step = get_object_or_404(PathwayStep, id=step_id)
    if request.method == "POST":
        form = StaffPathwayStepForm(request.POST, instance=step)
        if form.is_valid():
            form.save()
            messages.success(request, f"{step.name} was updated.")
            return redirect("staff_pathway_step_list")
    else:
        form = StaffPathwayStepForm(instance=step)
    return render(
        request, "staff/pathway_step_form.html", {"form": form, "is_new": False, "step": step, "active_tab": "members"}
    )


@staff_permission_required("members.add_member")
def member_create(request):
    if request.method == "POST":
        form = StaffMemberForm(request.POST, request.FILES)
        if form.is_valid():
            member = form.save()
            messages.success(request, f"{member} was added.")
            return redirect("staff_member_detail", member_id=member.id)
    else:
        initial = {}
        household_id = request.GET.get("household")
        if household_id:
            initial["household"] = household_id
        # A campus-scoped staff account (see staff_campus_for) gets their
        # own campus pre-filled - just a convenience default, not enforced,
        # since a scoped Usher may still legitimately need to register a
        # visitor from a different campus.
        viewer_campus = staff_campus_for(request.user)
        if viewer_campus is not None:
            initial["campus"] = viewer_campus.id
        form = StaffMemberForm(initial=initial)
    return render(request, "staff/member_form.html", {"form": form, "is_new": True, "active_tab": "members"})


@staff_permission_required("members.change_member")
def member_edit(request, member_id):
    member = get_object_or_404(Member, id=optional_id(member_id))
    # A campus-scoped staff account can't edit a member outside their own
    # campus - same 404-not-403 treatment as member_detail above.
    if not in_campus_scope(member.campus, staff_campus_for(request.user)):
        raise Http404("Member not found.")
    if request.method == "POST":
        form = StaffMemberForm(request.POST, request.FILES, instance=member)
        viewer_campus = staff_campus_for(request.user)
        if viewer_campus and member.user_id == request.user.pk:
            form.fields["campus"].queryset = Campus.objects.filter(pk=viewer_campus.pk)
            form.fields["campus"].required = True
        if form.is_valid():
            form.save()
            messages.success(request, f"{member} was updated.")
            return redirect("staff_member_detail", member_id=member.id)
    else:
        form = StaffMemberForm(instance=member)
    return render(
        request, "staff/member_form.html", {"form": form, "is_new": False, "member": member, "active_tab": "members"}
    )


@staff_permission_required("members.change_member")
def member_import(request):
    # Deliberately change_member, not add_member: Ushers have add_member so
    # they can enter one visitor at the door (see member_create above), but
    # a bulk CSV import - which can also set a role column for many members
    # at once - is a bigger, staff-admin-level action and stays Pastor-only.
    result = None
    if request.method == "POST" and request.FILES.get("csv_file"):
        result = import_members_csv(request.FILES["csv_file"])
        if result.created:
            messages.success(request, f"Imported {len(result.created)} member(s).")
        if result.errors:
            messages.warning(request, f"{len(result.errors)} row(s) had problems - see details below.")
        if not result.created and not result.errors:
            messages.info(request, "That file didn't have any rows to import.")
    return render(request, "staff/member_import.html", {"result": result, "active_tab": "members"})


@staff_permission_required("members.view_member")
def member_export(request):
    """
    Exports the same set of members the member list is currently showing -
    same search/status/campus filters, just as a CSV instead of a page - so
    "export what I'm looking at" does what it sounds like.
    """
    members_qs = Member.objects.select_related("household", "campus").order_by("last_name", "first_name")
    members_qs = scope_members(members_qs, staff_campus_for(request.user))

    query = request.GET.get("q", "").strip()
    if query:
        members_qs = members_qs.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query))

    status = request.GET.get("status")
    if status == "inactive":
        members_qs = members_qs.filter(is_active=False)
    elif status == "active":
        members_qs = members_qs.filter(is_active=True)

    campus_id = request.GET.get("campus", "")
    if campus_id:
        members_qs = members_qs.filter(campus_id=optional_id(campus_id))

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="members.csv"'
    writer = csv.writer(response)
    writer.writerow(
        ["first_name", "last_name", "email", "phone", "role", "household", "campus", "is_active", "date_joined"]
    )
    for member in members_qs:
        writer.writerow(
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
        )
    return response


@staff_permission_required("care.view_carerequest")
def full_backup_export(request):
    """
    A single ZIP download of CSVs covering the church's core data - beyond
    the members-only export above (see build_full_backup_zip in
    staff/services.py for exactly what's included and why). Gated on
    care.view_carerequest rather than a dedicated permission of its own -
    the one permission in this project that, by design (see
    setup_groups.py's PASTOR_MODELS), only Pastors ever hold - since this
    view can see everything a Pastor can and more, all bundled together.
    """
    zip_bytes = build_full_backup_zip()
    response = HttpResponse(zip_bytes, content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{backup_filename()}"'
    return response


@staff_permission_required("care.view_carerequest")
def directory_booklet(request):
    """
    A printable booklet of the opted-in member directory - same audience
    (active, share_in_directory=True) and same per-field privacy rules
    (phone/email only shown if that member separately opted into sharing it)
    as the online directory at /members/directory/ (see members/views.py's
    directory), just grouped by household and formatted for printing/handing
    out rather than browsing on-screen. Gated the same "Pastor-only" way as
    full_backup_export above - bundling everyone's shared contact details
    into one document is a bigger step than looking up one member at a time.
    """
    members = scope_members(
        Member.objects.filter(is_active=True, share_in_directory=True)
        .select_related("household")
        .order_by("household__name", "last_name", "first_name"),
        staff_campus_for(request.user),
    )
    # Grouped by household id (0 standing in for "no household set") rather
    # than by household name, so two different, unnamed, or same-named
    # households are never merged into one entry.
    households = OrderedDict()
    for member in members:
        key = member.household_id or 0
        group = households.setdefault(key, {"household": member.household, "members": []})
        group["members"].append(member)
    return render(
        request,
        "staff/directory_booklet.html",
        {"households": list(households.values()), "member_count": members.count()},
    )


@staff_permission_required("care.view_carerequest")
def activity_log(request):
    """
    A single chronological feed of notable staff actions across the whole
    project - who did what, when, to which record - built entirely on
    Django's own built-in LogEntry model rather than a new one of our own.
    /admin/ already writes a LogEntry for every add/change/delete made
    through it; this view just also reads that table, and a few services.py
    functions (see followup/services.py's start_follow_up and this file's
    equipment_checkout/equipment_checkin) now write to it too, so actions
    taken from the friendlier /staff/ screens show up here as well. Gated on
    care.view_carerequest, same "only Pastors hold this" reasoning as
    full_backup_export above - an activity log covering the whole church's
    data is exactly the kind of thing that shouldn't be scoped to Ushers or
    Treasurers.
    """
    entries = LogEntry.objects.select_related("user", "content_type").order_by("-action_time")
    paginator = Paginator(entries, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "staff/activity_log.html",
        {
            "page_obj": page_obj,
            "active_tab": "activity_log",
        },
    )


# --- Events -------------------------------------------------------------

@staff_permission_required("events.view_event")
def event_list(request):
    show = request.GET.get("show", "upcoming")
    events_qs = Event.objects.select_related("campus")

    # A campus-scoped staff account (see staff_campus_for) sees its own
    # campus's events plus every all-campus event (campus left unset) -
    # applied before the optional filter below, same non-bypassable
    # composition as member_list's mandatory + optional campus filters.
    viewer_campus = staff_campus_for(request.user)
    events_qs = scope_events(events_qs, viewer_campus)

    if show == "past":
        events_qs = events_qs.filter(start_datetime__lt=timezone.now()).order_by("-start_datetime")
    else:
        show = "upcoming"
        events_qs = events_qs.filter(start_datetime__gte=timezone.now()).order_by("start_datetime")

    query = request.GET.get("q", "").strip()
    if query:
        events_qs = events_qs.filter(Q(title__icontains=query) | Q(location__icontains=query))

    event_type = request.GET.get("type", "")
    if event_type in dict(Event.EventType.choices):
        events_qs = events_qs.filter(event_type=event_type)
    else:
        event_type = ""

    show_campus_filter = viewer_campus is None and Campus.objects.count() > 1
    campus_id = request.GET.get("campus", "") if show_campus_filter else ""
    if campus_id:
        events_qs = events_qs.filter(campus_id=optional_id(campus_id))

    page_obj = Paginator(events_qs, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/event_list.html",
        {
            "page_obj": page_obj,
            "show": show,
            "query": query,
            "event_type": event_type,
            "event_types": Event.EventType.choices,
            "campus_id": campus_id,
            "campuses": Campus.objects.all() if show_campus_filter else None,
            "can_add": request.user.has_perm("events.add_event"),
            "active_tab": "events",
        },
    )


@staff_permission_required("events.view_event")
def event_detail(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    if not in_campus_scope(event.campus, staff_campus_for(request.user)):
        raise Http404("Event not found.")
    slots = event.volunteer_slots.prefetch_related("signups__member")
    rsvps = event.rsvps.select_related("member", "service_time").order_by("member__last_name")
    tickets = event.tickets.prefetch_related("registrations__member")
    qr_checkin_count = Attendance.objects.filter(event=event, present=True).count()
    service_times = event.service_times.all()

    resource_bookings = None
    if request.user.has_perm("booking.view_resourcebooking"):
        resource_bookings = event.resource_bookings.select_related("resource")

    return render(
        request,
        "staff/event_detail.html",
        {
            "event": event,
            "slots": slots,
            "rsvps": rsvps,
            "tickets": tickets,
            "service_times": service_times,
            "can_add_ticket": request.user.has_perm("events.add_eventticket"),
            "can_edit": request.user.has_perm("events.change_event"),
            "can_add_slot": request.user.has_perm("events.add_volunteerslot"),
            "can_add_service_time": request.user.has_perm("events.add_eventservicetime"),
            "resource_bookings": resource_bookings,
            "can_add_booking": request.user.has_perm("booking.add_resourcebooking"),
            "qr_checkin_count": qr_checkin_count,
            "active_tab": "events",
        },
    )


@staff_permission_required("events.add_event")
def event_create(request):
    if request.method == "POST":
        form = StaffEventForm(request.POST)
        if form.is_valid():
            event = form.save()
            occurrences = form.cleaned_data.get("occurrences") or 1
            if event.recurrence != Event.Recurrence.NONE and occurrences > 1:
                generate_recurring_occurrences(event, frequency=event.recurrence, count=occurrences)
                messages.success(
                    request, f"{event.title} was created, plus {occurrences - 1} more occurrence(s)."
                )
            else:
                messages.success(request, f"{event.title} was created.")
            return redirect("staff_event_detail", event_id=event.id)
    else:
        # Convenience default for a campus-scoped staff account - see
        # member_create's identical treatment above.
        viewer_campus = staff_campus_for(request.user)
        initial = {"campus": viewer_campus.id} if viewer_campus is not None else {}
        form = StaffEventForm(initial=initial)
    return render(request, "staff/event_form.html", {"form": form, "is_new": True, "active_tab": "events"})


@staff_permission_required("events.change_event")
def event_edit(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    if not in_campus_scope(event.campus, staff_campus_for(request.user)):
        raise Http404("Event not found.")
    if request.method == "POST":
        form = StaffEventForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
            messages.success(request, f"{event.title} was updated.")
            return redirect("staff_event_detail", event_id=event.id)
    else:
        form = StaffEventForm(instance=event)
    return render(
        request, "staff/event_form.html", {"form": form, "is_new": False, "event": event, "active_tab": "events"}
    )


@staff_permission_required("events.view_event")
def roster_gaps(request):
    """
    Upcoming volunteer slots that still have open spots, across every
    upcoming event - so a scheduler can see understaffed services at a
    glance instead of opening each event's page one at a time.

    Gated on events.view_event (not events.view_volunteerslot) to match
    event_detail above, which already shows every slot on an event's page
    to anyone who can view the event - this is just that same data
    aggregated across events, with nothing member-identifying in it, so
    there's no reason to require a separate permission Ushers don't have.
    """
    slots = (
        VolunteerSlot.objects.filter(event__start_datetime__gte=timezone.now())
        .select_related("event", "event__campus")
        .order_by("event__start_datetime")
    )
    viewer_campus = staff_campus_for(request.user)
    gaps = [
        slot
        for slot in slots
        if slot.spots_remaining > 0 and in_campus_scope(slot.event.campus, viewer_campus)
    ]
    return render(request, "staff/roster_gaps.html", {"gaps": gaps, "active_tab": "events"})


@staff_permission_required("events.add_volunteerslot")
def volunteer_slot_create(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    if not in_campus_scope(event.campus, staff_campus_for(request.user)):
        raise Http404("Event not found.")
    if request.method == "POST":
        form = StaffVolunteerSlotForm(request.POST)
        if form.is_valid():
            slot = form.save(commit=False)
            slot.event = event
            slot.save()
            messages.success(request, f"Added the {slot.role_needed} slot.")
            return redirect("staff_event_detail", event_id=event.id)
    else:
        form = StaffVolunteerSlotForm()
    return render(
        request,
        "staff/volunteer_slot_form.html",
        {"form": form, "event": event, "is_new": True, "active_tab": "events"},
    )


@staff_permission_required("events.change_volunteerslot")
def volunteer_slot_edit(request, slot_id):
    slot = get_object_or_404(VolunteerSlot.objects.select_related("event"), id=slot_id)
    if not in_campus_scope(slot.event.campus, staff_campus_for(request.user)):
        raise Http404("Volunteer slot not found.")
    if request.method == "POST":
        form = StaffVolunteerSlotForm(request.POST, instance=slot)
        if form.is_valid():
            form.save()
            messages.success(request, f"{slot.role_needed} was updated.")
            return redirect("staff_event_detail", event_id=slot.event_id)
    else:
        form = StaffVolunteerSlotForm(instance=slot)
    return render(
        request,
        "staff/volunteer_slot_form.html",
        {"form": form, "event": slot.event, "is_new": False, "slot": slot, "active_tab": "events"},
    )


@staff_permission_required("events.add_eventservicetime")
def event_service_time_create(request, event_id):
    """
    Adds one more service time/location to an event - see
    events.EventServiceTime's docstring. Same Pastor-only permission as
    volunteer slots above (see setup_groups.py's PASTOR_MODELS) - no edit
    view, same as volunteer slots not having one either; a mistake is
    quickest to fix by adding the corrected one and leaving the old one
    (no staff role can delete anything anyway).
    """
    event = get_object_or_404(Event, id=event_id)
    if not in_campus_scope(event.campus, staff_campus_for(request.user)):
        raise Http404("Event not found.")
    if request.method == "POST":
        form = StaffEventServiceTimeForm(request.POST)
        if form.is_valid():
            service_time = form.save(commit=False)
            service_time.event = event
            service_time.save()
            messages.success(request, f"Added {service_time.label}.")
            return redirect("staff_event_detail", event_id=event.id)
    else:
        form = StaffEventServiceTimeForm()
    return render(
        request,
        "staff/event_service_time_form.html",
        {"form": form, "event": event, "active_tab": "events"},
    )


@staff_permission_required("events.add_eventticket")
def ticket_create(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    if not in_campus_scope(event.campus, staff_campus_for(request.user)):
        raise Http404("Event not found.")
    if request.method == "POST":
        form = StaffEventTicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.event = event
            ticket.save()
            messages.success(request, f"Added the {ticket.name} ticket type.")
            return redirect("staff_event_detail", event_id=event.id)
    else:
        form = StaffEventTicketForm()
    return render(
        request,
        "staff/ticket_form.html",
        {"form": form, "event": event, "is_new": True, "active_tab": "events"},
    )


@staff_permission_required("events.change_eventticket")
def ticket_edit(request, ticket_id):
    ticket = get_object_or_404(EventTicket.objects.select_related("event"), id=ticket_id)
    if not in_campus_scope(ticket.event.campus, staff_campus_for(request.user)):
        raise Http404("Ticket not found.")
    if request.method == "POST":
        form = StaffEventTicketForm(request.POST, instance=ticket)
        if form.is_valid():
            form.save()
            messages.success(request, f"{ticket.name} was updated.")
            return redirect("staff_event_detail", event_id=ticket.event_id)
    else:
        form = StaffEventTicketForm(instance=ticket)
    return render(
        request,
        "staff/ticket_form.html",
        {"form": form, "event": ticket.event, "is_new": False, "ticket": ticket, "active_tab": "events"},
    )


# --- Donations ------------------------------------------------------------

@staff_permission_required("giving.view_donation")
def donation_list(request):
    donations_qs = Donation.objects.select_related("member", "campus").order_by("-date")

    viewer_campus = staff_campus_for(request.user)
    donations_qs = scope_donations(donations_qs, viewer_campus)

    status = request.GET.get("status", "")
    if status in dict(Donation.Status.choices):
        donations_qs = donations_qs.filter(status=status)
    else:
        status = ""

    show_campus_filter = viewer_campus is None and Campus.objects.count() > 1
    campus_id = request.GET.get("campus", "") if show_campus_filter else ""
    if campus_id:
        donations_qs = donations_qs.filter(campus_id=optional_id(campus_id))

    page_obj = Paginator(donations_qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/donation_list.html",
        {
            "page_obj": page_obj,
            "status": status,
            "campus_id": campus_id,
            "campuses": Campus.objects.all() if show_campus_filter else None,
            "can_add": request.user.has_perm("giving.add_donation"),
            "can_change": request.user.has_perm("giving.change_donation"),
            "active_tab": "donations",
        },
    )


@staff_permission_required("giving.add_donation")
def donation_create(request):
    if request.method == "POST":
        form = DonationForm(request.POST)
        if form.is_valid():
            donation = form.save(commit=False)
            # Always starts pending, same as the public giving page - even a
            # gift a Treasurer is entering because they're holding the cash
            # right now goes through the one reconciliation path below, so
            # every "completed" gift has a logged confirmation behind it.
            donation.status = Donation.Status.PENDING
            donation.save()
            notify_treasurers_of_pending_donation(donation)
            messages.success(request, f"Logged {donation}. Mark it completed once you've confirmed it.")
            return redirect("staff_donation_list")
    else:
        # Convenience default for a campus-scoped staff account - see
        # member_create's identical treatment above.
        viewer_campus = staff_campus_for(request.user)
        initial = {"campus": viewer_campus.id} if viewer_campus is not None else {}
        form = DonationForm(initial=initial)
    return render(request, "staff/donation_form.html", {"form": form, "active_tab": "donations"})


@staff_permission_required("giving.change_donation")
def donation_mark_completed(request, donation_id):
    donation = get_object_or_404(Donation.objects.select_related("member"), id=donation_id)
    if not in_attendance_donation_scope(donation, staff_campus_for(request.user), anonymous_ok=True):
        raise Http404("Donation not found.")
    if request.method == "POST":
        if mark_donation_completed(donation, user=request.user):
            messages.success(request, f"Marked {donation} as completed.")
        else:
            messages.error(request, "That gift wasn't pending, so nothing was changed.")
    return redirect("staff_donation_list")


# --- Live stream (public "Watch Online" page) --------------------------------
# Public, site-wide content, same Pastor-only management as sermons/
# announcements below (see PASTOR_MODELS).


@staff_permission_required("livestream.view_livestream")
def livestream_list(request):
    streams = LiveStream.objects.all()
    return render(
        request,
        "staff/livestream_list.html",
        {
            "streams": streams,
            "can_add": request.user.has_perm("livestream.add_livestream"),
            "can_edit": request.user.has_perm("livestream.change_livestream"),
            "active_tab": "livestream",
        },
    )


@staff_permission_required("livestream.add_livestream")
def livestream_create(request):
    if request.method == "POST":
        form = StaffLiveStreamForm(request.POST)
        if form.is_valid():
            stream = form.save()
            messages.success(request, f"{stream} was posted.")
            return redirect("staff_livestream_list")
    else:
        form = StaffLiveStreamForm()
    return render(request, "staff/livestream_form.html", {"form": form, "is_new": True, "active_tab": "livestream"})


@staff_permission_required("livestream.change_livestream")
def livestream_edit(request, stream_id):
    stream = get_object_or_404(LiveStream, id=stream_id)
    if request.method == "POST":
        form = StaffLiveStreamForm(request.POST, instance=stream)
        if form.is_valid():
            form.save()
            messages.success(request, f"{stream} was updated.")
            return redirect("staff_livestream_list")
    else:
        form = StaffLiveStreamForm(instance=stream)
    return render(
        request,
        "staff/livestream_form.html",
        {"form": form, "is_new": False, "stream": stream, "active_tab": "livestream"},
    )


# --- Flyers (public homepage "What's Happening" strip) -----------------------
# Same Pastor-only management as Live Stream just above - public, site-wide
# content (see setup_groups.py's PASTOR_MODELS).


@staff_permission_required("flyers.view_flyer")
def flyer_list(request):
    flyers = Flyer.objects.all()
    return render(
        request,
        "staff/flyer_list.html",
        {
            "flyers": flyers,
            "can_add": request.user.has_perm("flyers.add_flyer"),
            "can_edit": request.user.has_perm("flyers.change_flyer"),
            "active_tab": "flyers",
        },
    )


@staff_permission_required("flyers.add_flyer")
def flyer_create(request):
    if request.method == "POST":
        form = StaffFlyerForm(request.POST, request.FILES)
        if form.is_valid():
            flyer = form.save()
            messages.success(request, f"{flyer} was added.")
            return redirect("staff_flyer_list")
    else:
        form = StaffFlyerForm()
    return render(request, "staff/flyer_form.html", {"form": form, "is_new": True, "active_tab": "flyers"})


@staff_permission_required("flyers.change_flyer")
def flyer_edit(request, flyer_id):
    flyer = get_object_or_404(Flyer, id=flyer_id)
    if request.method == "POST":
        form = StaffFlyerForm(request.POST, request.FILES, instance=flyer)
        if form.is_valid():
            form.save()
            messages.success(request, f"{flyer} was updated.")
            return redirect("staff_flyer_list")
    else:
        form = StaffFlyerForm(instance=flyer)
    return render(
        request,
        "staff/flyer_form.html",
        {"form": form, "is_new": False, "flyer": flyer, "active_tab": "flyers"},
    )


# --- Sermons & Devotionals --------------------------------------------------

@staff_permission_required("sermons.view_sermon")
def sermon_list_staff(request):
    sermons_qs = Sermon.objects.order_by("-date")

    query = request.GET.get("q", "").strip()
    if query:
        sermons_qs = sermons_qs.filter(Q(title__icontains=query) | Q(speaker__icontains=query))

    page_obj = Paginator(sermons_qs, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/sermon_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "can_add": request.user.has_perm("sermons.add_sermon"),
            "can_edit": request.user.has_perm("sermons.change_sermon"),
            "active_tab": "sermons",
        },
    )


@staff_permission_required("sermons.add_sermon")
def sermon_create(request):
    if request.method == "POST":
        form = StaffSermonForm(request.POST, request.FILES)
        if form.is_valid():
            sermon = form.save()
            set_sermon_tags(sermon, form.cleaned_data.get("tags_input", ""))
            messages.success(request, f"{sermon.title} was posted.")
            return redirect("staff_sermon_list")
    else:
        form = StaffSermonForm()
    return render(request, "staff/sermon_form.html", {"form": form, "is_new": True, "active_tab": "sermons"})


@staff_permission_required("sermons.change_sermon")
def sermon_edit(request, sermon_id):
    sermon = get_object_or_404(Sermon, id=sermon_id)
    if request.method == "POST":
        form = StaffSermonForm(request.POST, request.FILES, instance=sermon)
        if form.is_valid():
            form.save()
            set_sermon_tags(sermon, form.cleaned_data.get("tags_input", ""))
            messages.success(request, f"{sermon.title} was updated.")
            return redirect("staff_sermon_list")
    else:
        form = StaffSermonForm(instance=sermon)
    return render(
        request,
        "staff/sermon_form.html",
        {"form": form, "is_new": False, "sermon": sermon, "active_tab": "sermons"},
    )


@staff_permission_required("sermons.view_sermonseries")
def series_list_staff(request):
    series_qs = SermonSeries.objects.annotate(sermon_count=Count("sermons")).order_by("name")
    return render(
        request,
        "staff/series_list.html",
        {
            "series_list": series_qs,
            "can_add": request.user.has_perm("sermons.add_sermonseries"),
            "active_tab": "sermons",
        },
    )


@staff_permission_required("sermons.add_sermonseries")
def series_create(request):
    if request.method == "POST":
        form = StaffSermonSeriesForm(request.POST)
        if form.is_valid():
            series = form.save()
            messages.success(request, f"{series.name} was created.")
            return redirect("staff_series_list")
    else:
        form = StaffSermonSeriesForm()
    return render(request, "staff/series_form.html", {"form": form, "is_new": True, "active_tab": "sermons"})


@staff_permission_required("sermons.change_sermonseries")
def series_edit(request, series_id):
    series = get_object_or_404(SermonSeries, id=series_id)
    if request.method == "POST":
        form = StaffSermonSeriesForm(request.POST, instance=series)
        if form.is_valid():
            form.save()
            messages.success(request, f"{series.name} was updated.")
            return redirect("staff_series_list")
    else:
        form = StaffSermonSeriesForm(instance=series)
    return render(
        request, "staff/series_form.html", {"form": form, "is_new": False, "series": series, "active_tab": "sermons"}
    )


@staff_permission_required("sermons.view_devotional")
def devotional_list_staff(request):
    devotionals_qs = Devotional.objects.order_by("-date")

    query = request.GET.get("q", "").strip()
    if query:
        devotionals_qs = devotionals_qs.filter(
            Q(title__icontains=query) | Q(scripture_reference__icontains=query)
        )

    page_obj = Paginator(devotionals_qs, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/devotional_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "can_add": request.user.has_perm("sermons.add_devotional"),
            "can_edit": request.user.has_perm("sermons.change_devotional"),
            "active_tab": "sermons",
        },
    )


@staff_permission_required("sermons.add_devotional")
def devotional_create(request):
    if request.method == "POST":
        form = StaffDevotionalForm(request.POST)
        if form.is_valid():
            devotional = form.save()
            messages.success(request, f"{devotional.title} was posted.")
            return redirect("staff_devotional_list")
    else:
        form = StaffDevotionalForm()
    return render(request, "staff/devotional_form.html", {"form": form, "is_new": True, "active_tab": "sermons"})


@staff_permission_required("sermons.change_devotional")
def devotional_edit(request, devotional_id):
    devotional = get_object_or_404(Devotional, id=devotional_id)
    if request.method == "POST":
        form = StaffDevotionalForm(request.POST, instance=devotional)
        if form.is_valid():
            form.save()
            messages.success(request, f"{devotional.title} was updated.")
            return redirect("staff_devotional_list")
    else:
        form = StaffDevotionalForm(instance=devotional)
    return render(
        request,
        "staff/devotional_form.html",
        {"form": form, "is_new": False, "devotional": devotional, "active_tab": "sermons"},
    )


# --- Households -------------------------------------------------------------

@staff_permission_required("members.view_household")
def household_list(request):
    households_qs = Household.objects.annotate(member_count=Count("members")).order_by("name")

    query = request.GET.get("q", "").strip()
    if query:
        households_qs = households_qs.filter(name__icontains=query)

    page_obj = Paginator(households_qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/household_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "can_add": request.user.has_perm("members.add_household"),
            "active_tab": "households",
        },
    )


@staff_permission_required("members.view_household")
def household_detail(request, household_id):
    household = get_object_or_404(Household, id=household_id)
    members = household.members.order_by("last_name", "first_name")
    can_manage_members = request.user.has_perm("members.change_member")
    other_members = None
    if can_manage_members:
        other_members = Member.objects.exclude(household=household).order_by("last_name", "first_name")
    return render(
        request,
        "staff/household_detail.html",
        {
            "household": household,
            "members": members,
            "other_members": other_members,
            "campuses": Campus.objects.all() if can_manage_members else None,
            "can_edit": request.user.has_perm("members.change_household"),
            "can_manage_members": can_manage_members,
            "active_tab": "households",
        },
    )


@staff_permission_required("members.change_member")
def household_bulk_action(request, household_id):
    """
    A handful of one-click actions that apply to every member of a household
    at once (see members/services.py's bulk_set_household_campus,
    bulk_sync_household_phone, and bulk_set_household_active for what each
    one actually does and why) - branches on a single `action` field the
    same way pathway_step_toggle above does, rather than giving each action
    its own URL/view for what's fundamentally the same "which household, do
    X to all its members" shape. Gated on members.change_member, same
    permission household_add_member/household_remove_member already use for
    editing who's in a household and what's true about them.
    """
    household = get_object_or_404(Household, id=household_id)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "set_campus":
            campus_id = request.POST.get("campus_id") or None
            campus = get_object_or_404(Campus, id=campus_id) if campus_id else None
            count = bulk_set_household_campus(household, campus)
            messages.success(request, f"Set campus for {count} household member(s).")
        elif action == "sync_phone":
            count = bulk_sync_household_phone(household)
            if count:
                messages.success(request, f"Copied the household phone number to {count} member(s) without one.")
            else:
                messages.error(request, "Nothing to sync - the household has no phone number on file, or every member already has one.")
        elif action == "set_active":
            count = bulk_set_household_active(household, True)
            messages.success(request, f"Marked {count} household member(s) active.")
        elif action == "set_inactive":
            count = bulk_set_household_active(household, False)
            messages.success(request, f"Marked {count} household member(s) inactive.")
    return redirect("staff_household_detail", household_id=household.id)


@staff_permission_required("members.add_household")
def household_create(request):
    if request.method == "POST":
        form = StaffHouseholdForm(request.POST)
        if form.is_valid():
            household = form.save()
            messages.success(request, f"{household} was added.")
            return redirect("staff_household_detail", household_id=household.id)
    else:
        form = StaffHouseholdForm()
    return render(request, "staff/household_form.html", {"form": form, "is_new": True, "active_tab": "households"})


@staff_permission_required("members.change_household")
def household_edit(request, household_id):
    household = get_object_or_404(Household, id=household_id)
    if request.method == "POST":
        form = StaffHouseholdForm(request.POST, instance=household)
        if form.is_valid():
            form.save()
            messages.success(request, f"{household} was updated.")
            return redirect("staff_household_detail", household_id=household.id)
    else:
        form = StaffHouseholdForm(instance=household)
    return render(
        request,
        "staff/household_form.html",
        {"form": form, "is_new": False, "household": household, "active_tab": "households"},
    )


@staff_permission_required("members.change_member")
def household_add_member(request, household_id):
    """
    Assigning a member to a household is really editing Member.household, so
    this (and the remove view below) is gated on members.change_member -
    the household-model permissions above only cover the household record
    itself (name/address/phone), not who belongs to it.
    """
    household = get_object_or_404(Household, id=household_id)
    if request.method == "POST":
        member = get_object_or_404(Member, id=request.POST.get("member_id"))
        member.household = household
        member.save(update_fields=["household"])
        messages.success(request, f"{member} was added to {household}.")
    return redirect("staff_household_detail", household_id=household.id)


@staff_permission_required("members.change_member")
def household_remove_member(request, household_id, member_id):
    household = get_object_or_404(Household, id=household_id)
    if request.method == "POST":
        member = get_object_or_404(Member, id=member_id, household=household)
        member.household = None
        member.save(update_fields=["household"])
        messages.success(request, f"{member} was removed from {household}.")
    return redirect("staff_household_detail", household_id=household.id)


# --- Groups (ministries, small groups, committees) --------------------------

@staff_permission_required("members.view_group")
def group_list(request):
    groups_qs = Group.objects.select_related("leader").annotate(
        member_count=Count("memberships", filter=Q(memberships__left_date__isnull=True))
    ).order_by("name")

    group_type = request.GET.get("type", "")
    if group_type in dict(Group.GroupType.choices):
        groups_qs = groups_qs.filter(group_type=group_type)
    else:
        group_type = ""

    page_obj = Paginator(groups_qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/group_list.html",
        {
            "page_obj": page_obj,
            "group_type": group_type,
            "can_add": request.user.has_perm("members.add_group"),
            "active_tab": "groups",
        },
    )


@staff_permission_required("members.view_group")
def group_detail(request, group_id):
    group = get_object_or_404(Group.objects.select_related("leader"), id=group_id)
    memberships = group.memberships.filter(left_date__isnull=True).select_related("member").order_by(
        "member__last_name", "member__first_name"
    )
    can_add_member = request.user.has_perm("members.add_groupmembership")
    other_members = None
    if can_add_member:
        current_member_ids = memberships.values_list("member_id", flat=True)
        other_members = Member.objects.exclude(id__in=current_member_ids).order_by("last_name", "first_name")

    # Recent meeting attendance, taken by the group's own leader from their
    # dashboard (see members/views.py's group_attendance) - only shown to
    # whoever can already see attendance data generally, same permission the
    # staff "Mark Attendance" tab itself is gated on.
    attendance_summary = None
    if request.user.has_perm("members.view_attendance"):
        attendance_summary = list(
            Attendance.objects.filter(group=group)
            .values("date")
            .annotate(present_count=Count("id", filter=Q(present=True)), total_count=Count("id"))
            .order_by("-date")[:8]
        )

    upcoming_serving = None
    if request.user.has_perm("members.view_servingassignment"):
        upcoming_serving = group.serving_assignments.filter(date__gte=timezone.localdate()).select_related("member")[
            :10
        ]

    recent_lessons = None
    if request.user.has_perm("members.view_grouplesson"):
        recent_lessons = group.lessons.select_related("posted_by")[:5]

    return render(
        request,
        "staff/group_detail.html",
        {
            "group": group,
            "memberships": memberships,
            "other_members": other_members,
            "can_edit": request.user.has_perm("members.change_group"),
            "can_add_member": can_add_member,
            "can_remove_member": request.user.has_perm("members.change_groupmembership"),
            "attendance_summary": attendance_summary,
            "upcoming_serving": upcoming_serving,
            "recent_lessons": recent_lessons,
            "active_tab": "groups",
        },
    )


@staff_permission_required("members.add_group")
def group_create(request):
    if request.method == "POST":
        form = StaffGroupForm(request.POST)
        if form.is_valid():
            group = form.save()
            messages.success(request, f"{group} was created.")
            return redirect("staff_group_detail", group_id=group.id)
    else:
        form = StaffGroupForm()
    return render(request, "staff/group_form.html", {"form": form, "is_new": True, "active_tab": "groups"})


@staff_permission_required("members.change_group")
def group_edit(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    if request.method == "POST":
        form = StaffGroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            messages.success(request, f"{group} was updated.")
            return redirect("staff_group_detail", group_id=group.id)
    else:
        form = StaffGroupForm(instance=group)
    return render(
        request, "staff/group_form.html", {"form": form, "is_new": False, "group": group, "active_tab": "groups"}
    )


@staff_permission_required("members.add_groupmembership")
def group_add_member(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    if request.method == "POST":
        member = get_object_or_404(Member, id=request.POST.get("member_id"))
        # update_or_create (rather than a plain create) so a member rejoining
        # a group they'd previously left reactivates that same row instead
        # of hitting the (member, group) unique constraint.
        GroupMembership.objects.update_or_create(member=member, group=group, defaults={"left_date": None})
        messages.success(request, f"{member} was added to {group}.")
    return redirect("staff_group_detail", group_id=group.id)


@staff_permission_required("members.change_groupmembership")
def group_remove_member(request, group_id, member_id):
    group = get_object_or_404(Group, id=group_id)
    if request.method == "POST":
        membership = get_object_or_404(GroupMembership, group=group, member_id=member_id, left_date__isnull=True)
        membership.left_date = timezone.localdate()
        membership.save(update_fields=["left_date"])
        messages.success(request, f"{membership.member} was removed from {group}.")
    return redirect("staff_group_detail", group_id=group.id)


# --- Global search ------------------------------------------------------

@staff_member_required
def staff_search(request):
    """
    One search box (see the header in base_staff.html) across everything a
    signed-in staff member has permission to see. Each section below is
    left out of `results` entirely - not just hidden in the template - when
    they lack the matching view permission, so this never reveals that a
    matching donation/household/etc. exists to someone who isn't supposed
    to see that kind of record at all.
    """
    query = request.GET.get("q", "").strip()
    results = {}
    viewer_campus = staff_campus_for(request.user)

    if query:
        if request.user.has_perm("members.view_member"):
            results["members"] = scope_members(
                Member.objects.filter(
                    Q(first_name__icontains=query)
                    | Q(last_name__icontains=query)
                    | Q(email__icontains=query)
                    | Q(phone__icontains=query)
                ),
                viewer_campus,
            ).order_by("last_name", "first_name")[:10]
        if request.user.has_perm("members.view_household"):
            results["households"] = Household.objects.filter(name__icontains=query).order_by("name")[:10]
        if request.user.has_perm("members.view_campus"):
            results["campuses"] = Campus.objects.filter(name__icontains=query).order_by("name")[:10]
        if request.user.has_perm("members.view_group"):
            results["groups"] = Group.objects.filter(name__icontains=query).order_by("name")[:10]
        if request.user.has_perm("giving.view_givingcampaign"):
            results["campaigns"] = scope_giving_campaigns(
                GivingCampaign.objects.filter(name__icontains=query), viewer_campus
            ).order_by("-start_date")[:10]
        if request.user.has_perm("events.view_event"):
            results["events"] = scope_events(
                Event.objects.filter(Q(title__icontains=query) | Q(location__icontains=query)), viewer_campus
            ).order_by("-start_datetime")[:10]
        if request.user.has_perm("giving.view_donation"):
            results["donations"] = scope_donations(
                Donation.objects.select_related("member").filter(
                    Q(member__first_name__icontains=query)
                    | Q(member__last_name__icontains=query)
                    | Q(payment_reference__icontains=query)
                ),
                viewer_campus,
            ).order_by("-date")[:10]
        if request.user.has_perm("sermons.view_sermon"):
            results["sermons"] = Sermon.objects.filter(
                Q(title__icontains=query) | Q(speaker__icontains=query)
            ).order_by("-date")[:10]
        if request.user.has_perm("sermons.view_devotional"):
            results["devotionals"] = Devotional.objects.filter(
                Q(title__icontains=query) | Q(scripture_reference__icontains=query)
            ).order_by("-date")[:10]
        if request.user.has_perm("checkin.view_child"):
            results["children"] = Child.objects.filter(
                Q(first_name__icontains=query) | Q(last_name__icontains=query)
            ).order_by("last_name", "first_name")[:10]
        if request.user.has_perm("followup.view_followup"):
            results["followups"] = FollowUp.objects.select_related("member").filter(
                Q(member__first_name__icontains=query) | Q(member__last_name__icontains=query)
            )[:10]
        if request.user.has_perm("announcements.view_announcement"):
            results["announcements"] = Announcement.objects.filter(
                Q(subject__icontains=query) | Q(body__icontains=query)
            )[:10]

    return render(
        request,
        "staff/search_results.html",
        {"query": query, "results": results, "active_tab": "search"},
    )


# --- Campuses (branches/service locations) -----------------------------

@staff_permission_required("members.view_campus")
def campus_list(request):
    """
    Always reachable by permission alone - unlike the campus fields on the
    member/event/donation forms, this screen is never hidden behind the
    "more than one campus" threshold, since a church has to be able to add
    its second campus somewhere before anything else can react to it.
    """
    campuses_qs = Campus.objects.annotate(member_count=Count("members")).order_by("name")
    return render(
        request,
        "staff/campus_list.html",
        {
            "campuses": campuses_qs,
            "can_add": request.user.has_perm("members.add_campus"),
            "active_tab": "campuses",
        },
    )


@staff_permission_required("members.view_campus")
def campus_detail(request, campus_id):
    campus = get_object_or_404(Campus, id=campus_id)
    members = campus.members.order_by("last_name", "first_name")[:25]
    return render(
        request,
        "staff/campus_detail.html",
        {
            "campus": campus,
            "members": members,
            "member_count": campus.members.count(),
            "can_edit": request.user.has_perm("members.change_campus"),
            "active_tab": "campuses",
        },
    )


@staff_permission_required("members.add_campus")
def campus_create(request):
    if request.method == "POST":
        form = StaffCampusForm(request.POST)
        if form.is_valid():
            campus = form.save()
            messages.success(request, f"{campus} was added.")
            return redirect("staff_campus_detail", campus_id=campus.id)
    else:
        form = StaffCampusForm()
    return render(request, "staff/campus_form.html", {"form": form, "is_new": True, "active_tab": "campuses"})


@staff_permission_required("members.change_campus")
def campus_edit(request, campus_id):
    campus = get_object_or_404(Campus, id=campus_id)
    if request.method == "POST":
        form = StaffCampusForm(request.POST, instance=campus)
        if form.is_valid():
            form.save()
            messages.success(request, f"{campus} was updated.")
            return redirect("staff_campus_detail", campus_id=campus.id)
    else:
        form = StaffCampusForm(instance=campus)
    return render(
        request,
        "staff/campus_form.html",
        {"form": form, "is_new": False, "campus": campus, "active_tab": "campuses"},
    )


# --- Prayer requests ------------------------------------------------------

@staff_permission_required("prayer.view_prayerrequest")
def prayer_list(request):
    requests_qs = PrayerRequest.objects.select_related("member").order_by("prayed_for", "-created_at")

    show = request.GET.get("show", "")
    if show == "prayed":
        requests_qs = requests_qs.filter(prayed_for=True)
    elif show == "pending":
        requests_qs = requests_qs.filter(prayed_for=False)
    elif show == "awaiting":
        requests_qs = requests_qs.filter(is_public=True, approved_for_public=False)
    else:
        show = ""

    page_obj = Paginator(requests_qs, 25).get_page(request.GET.get("page"))
    # Attached directly to each row rather than passed as a separate
    # dict, since the template can't look a per-row form up by a dynamic
    # dict key - {{ prayer_request.assign_form }} just works.
    for prayer_request in page_obj:
        prayer_request.assign_form = StaffPrayerAssignForm(instance=prayer_request)
    return render(
        request,
        "staff/prayer_list.html",
        {
            "page_obj": page_obj,
            "show": show,
            "can_change": request.user.has_perm("prayer.change_prayerrequest"),
            "awaiting_count": PrayerRequest.objects.filter(is_public=True, approved_for_public=False).count(),
            "active_tab": "prayer",
        },
    )


@staff_permission_required("prayer.change_prayerrequest")
def prayer_mark_prayed(request, prayer_request_id):
    prayer_request = get_object_or_404(PrayerRequest, id=prayer_request_id)
    if request.method == "POST":
        if mark_prayed_for(prayer_request, user=request.user):
            messages.success(request, "Marked as prayed for.")
        else:
            messages.info(request, "That request was already marked as prayed for.")
    return redirect("staff_prayer_list")


@staff_permission_required("prayer.change_prayerrequest")
def prayer_set_wall_approval(request, prayer_request_id):
    """
    Public prayer requests are held back from the prayer wall until staff
    approve them (see prayer/views.py's prayer_wall) - this approves one, or
    takes an approved one back off the wall. Only a request the person
    themselves marked is_public can be approved; staff can't publish a
    private request.
    """
    prayer_request = get_object_or_404(PrayerRequest, id=prayer_request_id)
    if request.method == "POST":
        approve = request.POST.get("approve") == "1"
        if approve and not prayer_request.is_public:
            messages.error(request, "That request was submitted privately, so it can't go on the prayer wall.")
        else:
            prayer_request.approved_for_public = approve
            prayer_request.save(update_fields=["approved_for_public"])
            messages.success(request, "Approved for the prayer wall." if approve else "Removed from the prayer wall.")
    return redirect("staff_prayer_list")


@staff_permission_required("prayer.change_prayerrequest")
def prayer_assign(request, prayer_request_id):
    prayer_request = get_object_or_404(PrayerRequest, id=prayer_request_id)
    if request.method == "POST":
        form = StaffPrayerAssignForm(request.POST, instance=prayer_request)
        if form.is_valid():
            form.save()
            if prayer_request.assigned_pastor:
                messages.success(request, f"Assigned to {prayer_request.assigned_pastor}.")
            else:
                messages.success(request, "Unassigned.")
    return redirect("staff_prayer_list")


# --- Suggestion box ----------------------------------------------------------
# Anonymous feedback to church leadership - Pastor-only, same reasoning as
# CareRequest (see PASTOR_MODELS).


@staff_permission_required("suggestions.view_suggestion")
def suggestion_list(request):
    suggestions_qs = Suggestion.objects.all()

    show = request.GET.get("show", "")
    if show == "reviewed":
        suggestions_qs = suggestions_qs.filter(is_reviewed=True)
    elif show == "pending":
        suggestions_qs = suggestions_qs.filter(is_reviewed=False)
    else:
        show = ""

    page_obj = Paginator(suggestions_qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/suggestion_list.html",
        {
            "page_obj": page_obj,
            "show": show,
            "can_change": request.user.has_perm("suggestions.change_suggestion"),
            "active_tab": "suggestions",
        },
    )


@staff_permission_required("suggestions.change_suggestion")
def suggestion_mark_reviewed(request, suggestion_id):
    suggestion = get_object_or_404(Suggestion, id=suggestion_id)
    if request.method == "POST":
        if mark_reviewed(suggestion, user=request.user):
            messages.success(request, "Marked as reviewed.")
        else:
            messages.info(request, "That suggestion was already marked as reviewed.")
    return redirect("staff_suggestion_list")


# --- Testimony wall ----------------------------------------------------------
# Member-submitted, but held for review before it can appear on the public
# testimony wall - Pastor-only, same reasoning as Suggestion.


@staff_permission_required("testimonies.view_testimony")
def testimony_list(request):
    testimonies_qs = Testimony.objects.select_related("member").all()

    show = request.GET.get("show", "")
    if show == "approved":
        testimonies_qs = testimonies_qs.filter(is_approved=True)
    elif show == "pending":
        testimonies_qs = testimonies_qs.filter(is_approved=False)
    else:
        show = ""

    page_obj = Paginator(testimonies_qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/testimony_list.html",
        {
            "page_obj": page_obj,
            "show": show,
            "can_change": request.user.has_perm("testimonies.change_testimony"),
            "active_tab": "testimonies",
        },
    )


@staff_permission_required("testimonies.change_testimony")
def testimony_approve(request, testimony_id):
    testimony = get_object_or_404(Testimony, id=testimony_id)
    if request.method == "POST":
        if approve_testimony(testimony, user=request.user):
            messages.success(request, "Approved for the public testimony wall.")
        else:
            messages.info(request, "That testimony was already approved.")
    return redirect("staff_testimony_list")


# --- Absentee alerts -------------------------------------------------------


@staff_permission_required("members.view_attendance")
def absentee_list(request):
    """
    Members who haven't attended anything in a while (see
    members/services.py's absentee_members) - same members.view_attendance
    permission the attendance trend chart on the reports page already
    requires, so an Usher sees this too, not just Pastors. Each row's
    "Start Follow-Up" button reuses the exact same followup_start view an
    established member's own detail page already offers - starting one for
    someone already being followed up with is a safe no-op there.
    """
    return render(
        request,
        "staff/absentee_list.html",
        {
            "absentees": absentee_members(campus=staff_campus_for(request.user)),
            "weeks": ABSENTEE_WEEKS,
            "can_follow_up": request.user.has_perm("followup.add_followup"),
            "active_tab": "absentees",
        },
    )


@staff_permission_required("giving.view_recurringgiving")
def lapsed_recurring_givers_list(request):
    """
    Recurring giving commitments that have been reminded repeatedly with
    nothing to show for it (see giving/services.py's lapsed_recurring_gifts)
    - the giving-side counterpart to the absentee list above. Gated on
    giving.view_recurringgiving, the same permission the dashboard's own
    recurring-giving views implicitly assume a Treasurer/Pastor has, rather
    than members.view_attendance - this is giving data, not attendance data.
    """
    return render(
        request,
        "staff/lapsed_recurring_givers_list.html",
        {
            "lapsed_gifts": lapsed_recurring_gifts(),
            "active_tab": "lapsed_recurring_givers",
        },
    )


# --- Reports --------------------------------------------------------------

REPORT_MONTHS = 6
ATTENDANCE_TREND_WEEKS = 8
GIVING_COMPARISON_YEARS = 3


@staff_member_required
def reports_overview(request):
    """
    Each section below is only computed - and only shown - if the signed-in
    user actually has permission to see that kind of record, same rule as
    the staff home page's stats and the global search box. An Usher (who
    can view attendance but not donations) sees the attendance section only;
    a Treasurer sees only giving; a Pastor sees both.
    """
    since = timezone.localdate().replace(day=1) - timedelta(days=30 * (REPORT_MONTHS - 1))
    viewer_campus = staff_campus_for(request.user)

    attendance_by_month = None
    attendance_by_week = None
    attendance_by_campus = None
    attendance_chart_max_month = 0
    attendance_chart_max_week = 0
    attendance_chart_max_campus = 0
    if request.user.has_perm("members.view_attendance"):
        attendance_by_month = list(
            scope_attendance(Attendance.objects.filter(present=True, date__gte=since), viewer_campus)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total=Count("id"))
            .order_by("month")
        )

        # A shorter, finer-grained trend alongside the monthly one above -
        # week-over-week movement can show a dip a monthly total would
        # smooth right over.
        since_weeks = timezone.localdate() - timedelta(weeks=ATTENDANCE_TREND_WEEKS)
        attendance_by_week = list(
            scope_attendance(Attendance.objects.filter(present=True, date__gte=since_weeks), viewer_campus)
            .annotate(week=TruncWeek("date"))
            .values("week")
            .annotate(total=Count("id"))
            .order_by("week")
        )

        # Same multi-campus progressive-disclosure rule as everywhere else a
        # campus field/filter appears in this project - see the Campus
        # model's docstring. A single-campus church has nothing to compare,
        # so this section simply doesn't exist for them - and neither does
        # it for a campus-scoped viewer, who by definition only has one
        # campus's worth of data to show, so a cross-campus comparison
        # would be either empty or a one-row non-comparison.
        if viewer_campus is None and Campus.objects.count() > 1:
            attendance_by_campus = list(
                Attendance.objects.filter(present=True, date__gte=since)
                .values("campus__name")
                .annotate(total=Count("id"))
                .order_by("-total")
            )
            for row in attendance_by_campus:
                row["label"] = row["campus__name"] or "No campus set"

        attendance_chart_max_month = max((row["total"] for row in attendance_by_month), default=0)
        attendance_chart_max_week = max((row["total"] for row in attendance_by_week), default=0)
        if attendance_by_campus:
            attendance_chart_max_campus = max(row["total"] for row in attendance_by_campus)

    giving_by_month = None
    giving_by_type = None
    if request.user.has_perm("giving.view_donation"):
        completed = scope_donations(Donation.objects.filter(status=Donation.Status.COMPLETED), viewer_campus)
        giving_by_month = list(
            completed.filter(date__gte=since)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total=Sum("amount"))
            .order_by("month")
        )
        giving_by_type = list(
            completed.values("donation_type").annotate(total=Sum("amount")).order_by("-total")
        )
        donation_type_labels = dict(Donation.DonationType.choices)
        for row in giving_by_type:
            row["label"] = donation_type_labels.get(row["donation_type"], row["donation_type"])

        # Multi-year comparison: how does this year's giving, month by
        # month, stack up against the same months in prior years? Unlike
        # giving_by_month above (a short rolling window meant to show
        # recent momentum), this is a fixed set of whole calendar years -
        # useful for spotting a seasonal pattern (e.g. a December dip or
        # spike) that repeats every year, which a rolling window would
        # never hold enough history to show.
        current_year = timezone.localdate().year
        giving_comparison_years = list(
            range(current_year - GIVING_COMPARISON_YEARS + 1, current_year + 1)
        )
        totals_by_year_month = {
            (row["year"], row["month"]): row["total"]
            for row in completed.filter(date__year__in=giving_comparison_years)
            .annotate(year=ExtractYear("date"), month=ExtractMonth("date"))
            .values("year", "month")
            .annotate(total=Sum("amount"))
        }
        giving_by_year_and_month = [
            {
                "month_label": date(current_year, month_num, 1).strftime("%b"),
                "cells": [
                    {"year": year, "total": totals_by_year_month.get((year, month_num))}
                    for year in giving_comparison_years
                ],
            }
            for month_num in range(1, 13)
        ]
        giving_year_comparison_totals = [
            {
                "year": year,
                "total": sum(
                    totals_by_year_month.get((year, month_num), 0) or 0 for month_num in range(1, 13)
                ),
            }
            for year in giving_comparison_years
        ]
    else:
        giving_comparison_years = None
        giving_by_year_and_month = None
        giving_year_comparison_totals = None

    # Income vs. expenses (the treasurer's financial dashboard) needs BOTH
    # giving.view_donation and expenses.view_expense - a Treasurer has both,
    # so this shows up for them even though neither section above is shown
    # to just anyone with only one of the two permissions.
    net_by_month = None
    if request.user.has_perm("giving.view_donation") and request.user.has_perm("expenses.view_expense"):
        completed = Donation.objects.filter(status=Donation.Status.COMPLETED)
        # Donation.date is a DateTimeField (auto_now_add) while Expense.date
        # is a plain DateField, so TruncMonth("date") hands back a datetime
        # for one and a date for the other. Normalize both to plain date
        # keys before merging them below, or sorting/unioning the two dicts'
        # keys raises a TypeError comparing datetime to date.
        income_by_month = {
            (row["month"].date() if hasattr(row["month"], "date") else row["month"]): row["total"]
            for row in completed.filter(date__gte=since)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total=Sum("amount"))
        }
        expenses_by_month = {
            (row["month"].date() if hasattr(row["month"], "date") else row["month"]): row["total"]
            for row in Expense.objects.filter(date__gte=since)
            .annotate(month=TruncMonth("date"))
            .values("month")
            .annotate(total=Sum("amount"))
        }
        months = sorted(set(income_by_month) | set(expenses_by_month))
        net_by_month = [
            {
                "month": month,
                "income": income_by_month.get(month, 0),
                "expenses": expenses_by_month.get(month, 0),
                "net": income_by_month.get(month, 0) - expenses_by_month.get(month, 0),
            }
            for month in months
        ]

    return render(
        request,
        "staff/reports.html",
        {
            "attendance_by_month": attendance_by_month,
            "attendance_by_week": attendance_by_week,
            "attendance_by_campus": attendance_by_campus,
            "attendance_chart_max_month": attendance_chart_max_month,
            "attendance_chart_max_week": attendance_chart_max_week,
            "attendance_chart_max_campus": attendance_chart_max_campus,
            "giving_by_month": giving_by_month,
            "giving_by_type": giving_by_type,
            "giving_comparison_years": giving_comparison_years,
            "giving_by_year_and_month": giving_by_year_and_month,
            "giving_year_comparison_totals": giving_year_comparison_totals,
            "net_by_month": net_by_month,
            "can_backup": request.user.has_perm("care.view_carerequest"),
            "active_tab": "reports",
        },
    )


@staff_permission_required("care.view_carerequest")
def annual_statistics_report(request):
    """
    A single chosen calendar year's headline numbers - baptisms, weddings,
    funerals, baby dedications, transfer letters, altar-call decisions by
    type, new members, average attendance, and total giving - the kind of
    year-end summary a Pastor pulls together for reporting up to district or
    national Assemblies of God leadership. See staff/services.py's
    annual_statistics for exactly how each figure is computed.

    Gated on care.view_carerequest, the same "the one permission only
    Pastors ever hold" convention full_backup_export above uses - this
    report rolls up data across milestones, decisions, members, and giving
    all at once, so it needs to see everything a Pastor can.
    """
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
    except ValueError:
        year = today.year

    available_years = sorted(set(range(today.year - 9, today.year + 1)) | {year}, reverse=True)

    return render(
        request,
        "staff/annual_statistics.html",
        {
            "stats": annual_statistics(year),
            "available_years": available_years,
            "active_tab": "reports",
        },
    )


# --- Giving campaigns & pledges ---------------------------------------------

@staff_permission_required("giving.view_givingcampaign")
def campaign_list_staff(request):
    """
    Every campaign, active or not - unlike the public campaign_list (see
    giving/views.py), which only ever shows active ones. Staff need to see
    a finished or not-yet-launched campaign too, to manage it.
    """
    campaigns_qs = scope_giving_campaigns(
        GivingCampaign.objects.select_related("campus").order_by("-start_date"), staff_campus_for(request.user)
    )
    return render(
        request,
        "staff/campaign_list.html",
        {
            "campaigns": campaigns_qs,
            "can_add": request.user.has_perm("giving.add_givingcampaign"),
            "active_tab": "campaigns_giving",
        },
    )


@staff_permission_required("giving.view_givingcampaign")
def campaign_detail_staff(request, campaign_id):
    campaign = get_object_or_404(GivingCampaign.objects.select_related("campus"), id=campaign_id)
    if not in_campus_scope(campaign.campus, staff_campus_for(request.user)):
        raise Http404("Campaign not found.")
    pledges = campaign.pledges.select_related("member").order_by("member__last_name", "member__first_name")
    return render(
        request,
        "staff/campaign_detail.html",
        {
            "campaign": campaign,
            "pledges": pledges,
            "can_edit": request.user.has_perm("giving.change_givingcampaign"),
            "active_tab": "campaigns_giving",
        },
    )


@staff_permission_required("giving.add_givingcampaign")
def campaign_create_staff(request):
    if request.method == "POST":
        form = StaffGivingCampaignForm(request.POST)
        if form.is_valid():
            campaign = form.save()
            messages.success(request, f"{campaign} was created.")
            return redirect("staff_campaign_detail", campaign_id=campaign.id)
    else:
        # Convenience default for a campus-scoped staff account - see
        # member_create's identical treatment above.
        viewer_campus = staff_campus_for(request.user)
        initial = {"campus": viewer_campus.id} if viewer_campus is not None else {}
        form = StaffGivingCampaignForm(initial=initial)
    return render(
        request, "staff/campaign_form.html", {"form": form, "is_new": True, "active_tab": "campaigns_giving"}
    )


@staff_permission_required("giving.change_givingcampaign")
def campaign_edit_staff(request, campaign_id):
    campaign = get_object_or_404(GivingCampaign, id=campaign_id)
    if not in_campus_scope(campaign.campus, staff_campus_for(request.user)):
        raise Http404("Campaign not found.")
    if request.method == "POST":
        form = StaffGivingCampaignForm(request.POST, instance=campaign)
        if form.is_valid():
            form.save()
            messages.success(request, f"{campaign} was updated.")
            return redirect("staff_campaign_detail", campaign_id=campaign.id)
    else:
        form = StaffGivingCampaignForm(instance=campaign)
    return render(
        request,
        "staff/campaign_form.html",
        {"form": form, "is_new": False, "campaign": campaign, "active_tab": "campaigns_giving"},
    )


@staff_permission_required("giving.change_pledge")
def campaign_send_reminders(request, campaign_id):
    """
    On-demand nudge to every member whose pledge to this campaign isn't
    fully given toward yet - never automatic, always a deliberate action a
    Treasurer/Pastor takes from the campaign's page. A pledge already fully
    (or over-)given toward is left alone.
    """
    campaign = get_object_or_404(GivingCampaign, id=campaign_id)
    if not in_campus_scope(campaign.campus, staff_campus_for(request.user)):
        raise Http404("Campaign not found.")
    if request.method == "POST":
        outstanding = [p for p in campaign.pledges.select_related("member") if p.given_toward_pledge < p.amount]
        sent = skipped = 0
        for pledge in outstanding:
            if send_pledge_reminder(pledge):
                sent += 1
            else:
                skipped += 1

        if sent:
            messages.success(request, f"Sent a reminder to {sent} member(s) with an outstanding pledge.")
        if skipped:
            messages.warning(request, f"Skipped {skipped} member(s) with no email or phone on file.")
        if not outstanding:
            messages.info(request, "Every pledge to this campaign has already been fully given toward.")

    return redirect("staff_campaign_detail", campaign_id=campaign.id)


@staff_permission_required("giving.view_recurringgiving")
def recurring_giving_list(request):
    """
    Read-only oversight for Treasurers/Pastors - a recurring gift is always
    set up by the member themselves (see giving/views.py's
    recurring_giving_create), so there's no staff "create" flow here, only
    viewing and deactivating one on a member's request (e.g. a phone call).
    """
    recurring_gifts = scope_by_member_campus(
        RecurringGiving.objects.select_related("member", "campaign").order_by("-is_active", "next_due_date"),
        staff_campus_for(request.user),
    )
    return render(
        request,
        "staff/recurring_giving_list.html",
        {
            "recurring_gifts": recurring_gifts,
            "can_change": request.user.has_perm("giving.change_recurringgiving"),
            "active_tab": "campaigns_giving",
        },
    )


@staff_permission_required("giving.change_recurringgiving")
def recurring_giving_deactivate(request, recurring_id):
    recurring = get_object_or_404(RecurringGiving.objects.select_related("member"), id=recurring_id)
    if not in_member_campus_scope(recurring.member, staff_campus_for(request.user)):
        raise Http404("Recurring gift not found.")
    if request.method == "POST":
        recurring.is_active = False
        recurring.save(update_fields=["is_active"])
        messages.success(request, f"{recurring} was deactivated.")
    return redirect("staff_recurring_giving_list")


@staff_permission_required("giving.view_donation")
def giving_by_member_report(request):
    """A per-member annual giving summary, browsable without exporting anything."""
    current_year = timezone.localdate().year
    try:
        year = int(request.GET.get("year", current_year))
    except ValueError:
        year = current_year

    completed = scope_donations(
        Donation.objects.filter(status=Donation.Status.COMPLETED, date__year=year), staff_campus_for(request.user)
    )
    by_member = list(
        completed.exclude(member__isnull=True)
        .values("member__id", "member__first_name", "member__last_name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )
    anonymous_total = completed.filter(member__isnull=True).aggregate(total=Sum("amount"))["total"]

    # A simple list of a few recent years for the dropdown - no need to
    # query the database for the actual range of years with donations.
    available_years = list(range(current_year, current_year - 5, -1))

    return render(
        request,
        "staff/giving_by_member.html",
        {
            "year": year,
            "available_years": available_years,
            "by_member": by_member,
            "anonymous_total": anonymous_total,
            "active_tab": "reports",
        },
    )


@staff_permission_required("giving.view_donation")
def annual_giving_statement(request, member_id):
    """
    A printable year-end giving statement for any member, for a Treasurer or
    Pastor generating tax-deductible statements in bulk each January - the
    same underlying data as a member's own /give/statement/ page, just for a
    full calendar year and reachable for any member from the Giving by
    Member report above, without that member needing to log in and pull it
    themselves.
    """
    member = get_object_or_404(Member, id=optional_id(member_id))
    if not in_campus_scope(member.campus, staff_campus_for(request.user)):
        raise Http404("Member not found.")
    current_year = timezone.localdate().year
    try:
        year = int(request.GET.get("year", current_year))
    except ValueError:
        year = current_year

    start = date(year, 1, 1)
    end = date(year, 12, 31)
    donations = Donation.objects.filter(
        member=member,
        status=Donation.Status.COMPLETED,
        date__date__gte=start,
        date__date__lte=end,
    ).order_by("date")
    total = donations.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    available_years = list(range(current_year, current_year - 5, -1))

    return render(
        request,
        "staff/member_giving_statement.html",
        {
            "member": member,
            "donations": donations,
            "year": year,
            "available_years": available_years,
            "total": total,
            "active_tab": "reports",
        },
    )


# --- Children's ministry check-in --------------------------------------------

@staff_permission_required("checkin.view_child")
def child_list(request):
    children_qs = Child.objects.select_related("household").order_by("last_name", "first_name")

    query = request.GET.get("q", "").strip()
    if query:
        children_qs = children_qs.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query))

    page_obj = Paginator(children_qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/child_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "can_add": request.user.has_perm("checkin.add_child"),
            "active_tab": "children",
        },
    )


@staff_permission_required("checkin.view_child")
def child_detail(request, child_id):
    child = get_object_or_404(Child.objects.select_related("household"), id=child_id)
    check_ins = child.check_ins.select_related("event")[:15]
    return render(
        request,
        "staff/child_detail.html",
        {
            "child": child,
            "check_ins": check_ins,
            "can_edit": request.user.has_perm("checkin.change_child"),
            "active_tab": "children",
        },
    )


@staff_permission_required("checkin.add_child")
def child_create(request):
    if request.method == "POST":
        form = StaffChildForm(request.POST)
        if form.is_valid():
            child = form.save()
            messages.success(request, f"{child} was added.")
            return redirect("staff_child_detail", child_id=child.id)
    else:
        initial = {}
        household_id = request.GET.get("household")
        if household_id:
            initial["household"] = household_id
        form = StaffChildForm(initial=initial)
    return render(request, "staff/child_form.html", {"form": form, "is_new": True, "active_tab": "children"})


@staff_permission_required("checkin.change_child")
def child_edit(request, child_id):
    child = get_object_or_404(Child, id=child_id)
    if request.method == "POST":
        form = StaffChildForm(request.POST, instance=child)
        if form.is_valid():
            form.save()
            messages.success(request, f"{child} was updated.")
            return redirect("staff_child_detail", child_id=child.id)
    else:
        form = StaffChildForm(instance=child)
    return render(
        request, "staff/child_form.html", {"form": form, "is_new": False, "child": child, "active_tab": "children"}
    )


@staff_permission_required("checkin.view_checkin")
def checkin_dashboard(request):
    """Everyone currently checked in - not yet picked up - across every event/day."""
    active_checkins = (
        CheckIn.objects.filter(checked_out_at__isnull=True).select_related("child", "event").order_by("checked_in_at")
    )
    return render(
        request,
        "staff/checkin_dashboard.html",
        {
            "active_checkins": active_checkins,
            "can_add": request.user.has_perm("checkin.add_checkin"),
            "can_check_out": request.user.has_perm("checkin.change_checkin"),
            "active_tab": "children",
        },
    )


@staff_permission_required("checkin.add_checkin")
def checkin_create(request):
    if request.method == "POST":
        form = StaffCheckInForm(request.POST)
        if form.is_valid():
            check_in = check_in_child(
                form.cleaned_data["child"],
                event=form.cleaned_data["event"],
                guardian_name=form.cleaned_data["guardian_name"],
                user=request.user,
                notes=form.cleaned_data.get("notes", ""),
            )
            messages.success(request, f"{check_in.child} was checked in.")
            return redirect("staff_checkin_confirmation", checkin_id=check_in.id)
    else:
        form = StaffCheckInForm()
    return render(request, "staff/checkin_form.html", {"form": form, "active_tab": "children"})


@staff_permission_required("checkin.view_checkin")
def checkin_confirmation(request, checkin_id):
    check_in = get_object_or_404(CheckIn.objects.select_related("child", "event"), id=checkin_id)
    return render(request, "staff/checkin_confirmation.html", {"check_in": check_in, "active_tab": "children"})


@staff_permission_required("checkin.view_checkin")
def checkin_badge(request, checkin_id):
    """
    A printable name-tag/claim-ticket pair for a single check-in - the
    child's half (worn or clipped to a bag, showing anything a helper needs
    to know at a glance) and the guardian's matching claim ticket, both
    carrying the same pickup code so check-out (see checkin_check_out
    above) can actually verify the two halves against each other, instead
    of staff copying the code onto blank tags by hand as checkin_confirmation
    currently asks them to.
    """
    check_in = get_object_or_404(CheckIn.objects.select_related("child", "child__household", "event"), id=checkin_id)
    return render(request, "staff/checkin_badge.html", {"check_in": check_in, "active_tab": "children"})


@staff_permission_required("checkin.change_checkin")
def checkin_check_out(request, checkin_id):
    check_in = get_object_or_404(CheckIn.objects.select_related("child"), id=checkin_id)
    if check_in.checked_out_at is not None:
        messages.info(request, f"{check_in.child} was already checked out.")
        return redirect("staff_checkin_dashboard")

    error = None
    if request.method == "POST":
        form = StaffCheckOutForm(request.POST)
        if form.is_valid():
            try:
                check_out_child(check_in, code=form.cleaned_data["code"], user=request.user)
                messages.success(request, f"{check_in.child} was checked out.")
                return redirect("staff_checkin_dashboard")
            except WrongPickupCodeError:
                error = "That pickup code doesn't match. Please check the tag and try again."
    else:
        form = StaffCheckOutForm()
    return render(
        request,
        "staff/checkin_checkout_form.html",
        {"form": form, "check_in": check_in, "error": error, "active_tab": "children"},
    )


# --- Birthdays & anniversaries -----------------------------------------------

@staff_permission_required("members.view_member")
def birthdays_anniversaries(request):
    """
    Who has a birthday or wedding anniversary in a given month - defaults to
    the current month. Ordered by day-of-month via ExtractDay, since
    ordering by the raw date field would sort by year first (member records
    span many birth years, but all that matters here is the day within the
    chosen month).
    """
    today = timezone.localdate()
    try:
        month = int(request.GET.get("month", today.month))
    except ValueError:
        month = today.month
    if not 1 <= month <= 12:
        month = today.month

    birthdays = (
        Member.objects.filter(is_active=True, date_of_birth__month=month)
        .annotate(day=ExtractDay("date_of_birth"))
        .order_by("day", "last_name", "first_name")
    )
    anniversaries = (
        Member.objects.filter(is_active=True, anniversary_date__month=month)
        .annotate(day=ExtractDay("anniversary_date"))
        .order_by("day", "last_name", "first_name")
    )
    return render(
        request,
        "staff/birthdays.html",
        {
            "birthdays": birthdays,
            "anniversaries": anniversaries,
            "month": month,
            "month_name": calendar.month_name[month],
            "available_months": [(i, calendar.month_name[i]) for i in range(1, 13)],
            "active_tab": "birthdays",
        },
    )


# --- New member follow-up ----------------------------------------------------

@staff_permission_required("followup.view_followup")
def followup_list(request):
    stage = request.GET.get("stage", "")
    show_stale_only = request.GET.get("stale") == "1"
    # Computed once and reused both for the "Stale Only" filter itself and
    # for badging a stale row when browsing by stage instead - so a follow-up
    # that's gone quiet stands out no matter which view someone's looking at.
    stale = stale_follow_ups()
    if show_stale_only:
        follow_ups = stale
    else:
        follow_ups = FollowUp.objects.select_related("member", "assigned_to").all()
        if stage:
            follow_ups = follow_ups.filter(stage=stage)
    return render(
        request,
        "staff/followup_list.html",
        {
            "follow_ups": follow_ups,
            "stage": stage,
            "stages": FollowUp.Stage.choices,
            "show_stale_only": show_stale_only,
            "stale_count": len(stale),
            "stale_ids": {f.id for f in stale},
            "active_tab": "followup",
        },
    )


@staff_permission_required("followup.view_followup")
def followup_detail(request, follow_up_id):
    follow_up = get_object_or_404(FollowUp.objects.select_related("member", "assigned_to"), id=follow_up_id)
    return render(
        request,
        "staff/followup_detail.html",
        {
            "follow_up": follow_up,
            "contact_attempts": follow_up.contact_attempts.select_related("contacted_by")[:20],
            "stage_form": StaffFollowUpStageForm(instance=follow_up),
            "note_form": StaffContactAttemptForm(),
            "can_change": request.user.has_perm("followup.change_followup"),
            "can_log_contact": request.user.has_perm("followup.add_contactattempt"),
            "active_tab": "followup",
        },
    )


@staff_permission_required("followup.change_followup")
def followup_update_stage(request, follow_up_id):
    follow_up = get_object_or_404(FollowUp, id=follow_up_id)
    if request.method == "POST":
        form = StaffFollowUpStageForm(request.POST, instance=follow_up)
        if form.is_valid():
            form.save()
            messages.success(request, "Follow-up updated.")
    return redirect("staff_followup_detail", follow_up_id=follow_up.id)


@staff_permission_required("followup.add_contactattempt")
def followup_log_contact(request, follow_up_id):
    follow_up = get_object_or_404(FollowUp, id=follow_up_id)
    if request.method == "POST":
        form = StaffContactAttemptForm(request.POST)
        if form.is_valid():
            log_contact(follow_up, user=request.user, note=form.cleaned_data.get("note", ""))
            messages.success(request, "Contact logged.")
    return redirect("staff_followup_detail", follow_up_id=follow_up.id)


@staff_permission_required("followup.add_followup")
def followup_start(request, member_id):
    member = get_object_or_404(Member, id=optional_id(member_id))
    if request.method == "POST":
        follow_up = start_follow_up(member, user=request.user)
        messages.success(request, f"Started following up with {member}.")
        return redirect("staff_followup_detail", follow_up_id=follow_up.id)
    return redirect("staff_member_detail", member_id=member.id)


@staff_permission_required("followup.change_visitorinfo")
def visitor_info_edit(request):
    """
    Pastor-only editing of the single VisitorInfo row shown on the public
    /connect/welcome/ page (see followup/views.py's visitor_info) - service
    times, address, wifi, and a welcome note, kept up to date without
    anyone needing to touch a template or redeploy the site.
    """
    info = VisitorInfo.get_current()
    if request.method == "POST":
        form = StaffVisitorInfoForm(request.POST, instance=info)
        if form.is_valid():
            form.save()
            messages.success(request, "Visitor info updated.")
            return redirect("staff_visitor_info_edit")
    else:
        form = StaffVisitorInfoForm(instance=info)
    return render(request, "staff/visitor_info_form.html", {"form": form, "active_tab": "visitor_info"})


# --- Altar call / salvation decisions -----------------------------------------
# Distinct from the FollowUp pipeline above - a Decision is a dated,
# one-time record of what happened at the altar during a service, while a
# FollowUp tracks an ongoing relationship. Ushers get the same view/add/
# change access as FollowUp itself (see setup_groups.py), since they're
# usually the ones at the altar; Treasurers get nothing.


@staff_permission_required("decisions.view_decision")
def decision_list(request):
    decisions_qs = Decision.objects.select_related("member", "event")
    decision_type = request.GET.get("type", "")
    if decision_type in Decision.DecisionType.values:
        decisions_qs = decisions_qs.filter(decision_type=decision_type)
    else:
        decision_type = ""
    return render(
        request,
        "staff/decision_list.html",
        {
            "decisions": decisions_qs,
            "decision_type": decision_type,
            "decision_types": Decision.DecisionType.choices,
            "can_add": request.user.has_perm("decisions.add_decision"),
            "active_tab": "decisions",
        },
    )


@staff_permission_required("decisions.add_decision")
def decision_create(request):
    initial = {}
    member_id = request.GET.get("member")
    if member_id:
        initial = {"member": member_id}
    if request.method == "POST":
        form = StaffDecisionForm(request.POST)
        if form.is_valid():
            decision = record_decision(
                form.cleaned_data["member"],
                decision_type=form.cleaned_data["decision_type"],
                date=form.cleaned_data["date"],
                event=form.cleaned_data.get("event"),
                notes=form.cleaned_data.get("notes", ""),
                user=request.user,
            )
            messages.success(request, f"{decision} was recorded.")
            return redirect("staff_decision_list")
    else:
        form = StaffDecisionForm(initial=initial)
    return render(request, "staff/decision_form.html", {"form": form, "is_new": True, "active_tab": "decisions"})


@staff_permission_required("decisions.change_decision")
def decision_edit(request, decision_id):
    decision = get_object_or_404(Decision, id=decision_id)
    if request.method == "POST":
        form = StaffDecisionForm(request.POST, instance=decision)
        if form.is_valid():
            form.save()
            messages.success(request, f"{decision} was updated.")
            return redirect("staff_decision_list")
    else:
        form = StaffDecisionForm(instance=decision)
    return render(
        request,
        "staff/decision_form.html",
        {"form": form, "is_new": False, "decision": decision, "active_tab": "decisions"},
    )


# --- Announcements ------------------------------------------------------------

@staff_permission_required("announcements.view_announcement")
def announcement_list(request):
    announcements = Announcement.objects.all()
    return render(
        request,
        "staff/announcement_list.html",
        {
            "announcements": announcements,
            "can_add": request.user.has_perm("announcements.add_announcement"),
            "active_tab": "announcements",
        },
    )


@staff_permission_required("announcements.add_announcement")
def announcement_create(request):
    if request.method == "POST":
        form = StaffAnnouncementForm(request.POST)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.created_by = request.user
            announcement.save()
            messages.success(request, "Announcement drafted - review the recipient count, then send it.")
            return redirect("staff_announcement_detail", announcement_id=announcement.id)
    else:
        form = StaffAnnouncementForm()
    return render(
        request, "staff/announcement_form.html", {"form": form, "is_new": True, "active_tab": "announcements"}
    )


@staff_permission_required("announcements.change_announcement")
def announcement_edit(request, announcement_id):
    announcement = get_object_or_404(Announcement, id=announcement_id)
    if announcement.is_sent:
        messages.error(request, "This announcement has already been sent and can't be edited.")
        return redirect("staff_announcement_detail", announcement_id=announcement.id)

    if request.method == "POST":
        form = StaffAnnouncementForm(request.POST, instance=announcement)
        if form.is_valid():
            form.save()
            messages.success(request, "Announcement updated.")
            return redirect("staff_announcement_detail", announcement_id=announcement.id)
    else:
        form = StaffAnnouncementForm(instance=announcement)
    return render(
        request,
        "staff/announcement_form.html",
        {"form": form, "is_new": False, "announcement": announcement, "active_tab": "announcements"},
    )


@staff_permission_required("announcements.view_announcement")
def announcement_detail(request, announcement_id):
    announcement = get_object_or_404(Announcement, id=announcement_id)
    recipient_count = None if announcement.is_sent else audience_queryset(announcement).count()
    return render(
        request,
        "staff/announcement_detail.html",
        {
            "announcement": announcement,
            "recipient_count": recipient_count,
            "can_edit": request.user.has_perm("announcements.change_announcement") and not announcement.is_sent,
            "can_send": request.user.has_perm("announcements.change_announcement") and not announcement.is_sent,
            "active_tab": "announcements",
        },
    )


@staff_permission_required("announcements.view_announcement")
def announcement_delivery_report(request, announcement_id):
    """
    Per-member, per-channel detail behind an already-sent announcement's two
    aggregate counters (email_sent_count/sms_sent_count) - exactly who was
    emailed, texted, skipped for having opted out, or skipped for having no
    contact info on file at all, straight from the AnnouncementDelivery rows
    send_announcement wrote at send time. Gated on the same permission as
    the announcement detail page itself, since this is just a more detailed
    view of the same record, not a separate resource.
    """
    announcement = get_object_or_404(Announcement, id=announcement_id)
    deliveries = announcement.deliveries.select_related("member")

    status_filter = request.GET.get("status", "")
    if status_filter in AnnouncementDelivery.Status.values:
        deliveries = deliveries.filter(status=status_filter)
    else:
        status_filter = ""

    status_counts = {
        row["status"]: row["total"]
        for row in announcement.deliveries.values("status").annotate(total=Count("id"))
    }
    status_options = [
        {"value": value, "label": label, "count": status_counts.get(value, 0)}
        for value, label in AnnouncementDelivery.Status.choices
    ]

    return render(
        request,
        "staff/announcement_delivery_report.html",
        {
            "announcement": announcement,
            "deliveries": deliveries,
            "status_options": status_options,
            "status_filter": status_filter,
            "total_deliveries": announcement.deliveries.count(),
            "active_tab": "announcements",
        },
    )


@staff_permission_required("announcements.change_announcement")
def announcement_send(request, announcement_id):
    announcement = get_object_or_404(Announcement, id=announcement_id)
    if request.method == "POST":
        if announcement.is_sent:
            messages.info(request, "This announcement was already sent.")
        else:
            send_announcement(announcement)
            messages.success(
                request,
                f"Sent to {announcement.email_sent_count} email address(es) and "
                f"{announcement.sms_sent_count} phone number(s).",
            )
    return redirect("staff_announcement_detail", announcement_id=announcement.id)


# --- Room/resource booking -------------------------------------------------


@staff_permission_required("booking.view_resource")
def resource_list(request):
    resources = Resource.objects.all()
    return render(
        request,
        "staff/resource_list.html",
        {"resources": resources, "can_add": request.user.has_perm("booking.add_resource"), "active_tab": "booking"},
    )


@staff_permission_required("booking.add_resource")
def resource_create(request):
    if request.method == "POST":
        form = StaffResourceForm(request.POST)
        if form.is_valid():
            resource = form.save()
            messages.success(request, f"{resource} was added.")
            return redirect("staff_resource_list")
    else:
        form = StaffResourceForm()
    return render(request, "staff/resource_form.html", {"form": form, "is_new": True, "active_tab": "booking"})


@staff_permission_required("booking.change_resource")
def resource_edit(request, resource_id):
    resource = get_object_or_404(Resource, id=resource_id)
    if request.method == "POST":
        form = StaffResourceForm(request.POST, instance=resource)
        if form.is_valid():
            form.save()
            messages.success(request, f"{resource} was updated.")
            return redirect("staff_resource_list")
    else:
        form = StaffResourceForm(instance=resource)
    return render(
        request, "staff/resource_form.html", {"form": form, "is_new": False, "resource": resource, "active_tab": "booking"}
    )


@staff_permission_required("booking.view_resourcebooking")
def booking_list(request):
    bookings = ResourceBooking.objects.select_related("resource", "booked_by", "event").filter(
        end_datetime__gte=timezone.now()
    )
    resource_id = request.GET.get("resource")
    if resource_id:
        bookings = bookings.filter(resource_id=resource_id)
    return render(
        request,
        "staff/booking_list.html",
        {
            "bookings": bookings,
            "resources": Resource.objects.filter(is_active=True),
            "selected_resource": int(resource_id) if resource_id else None,
            "can_add": request.user.has_perm("booking.add_resourcebooking"),
            "active_tab": "booking",
        },
    )


@staff_permission_required("booking.view_resourcebooking")
def booking_calendar(request):
    """
    A week-at-a-glance grid: one row per active resource, one column per day
    of the selected week, so staff can see at a glance which rooms/vehicles
    are free on a given day - something the plain list above (booking_list)
    can't show without filtering to one resource at a time. A booking that
    spans multiple days (e.g. the church van reserved for a weekend retreat)
    appears in every day's column it actually covers.
    """
    today = timezone.localdate()
    try:
        anchor = date.fromisoformat(request.GET.get("week", "")) if request.GET.get("week") else today
    except ValueError:
        anchor = today
    week_start = anchor - timedelta(days=anchor.weekday())  # Monday of the selected week
    week_days = [week_start + timedelta(days=offset) for offset in range(7)]
    week_end = week_days[-1]

    resources = Resource.objects.filter(is_active=True)
    bookings = ResourceBooking.objects.filter(
        resource__in=resources,
        start_datetime__date__lte=week_end,
        end_datetime__date__gte=week_start,
    ).select_related("resource", "event")

    bookings_by_resource_and_day = {}
    for booking in bookings:
        first_day = max(booking.start_datetime.date(), week_start)
        last_day = min(booking.end_datetime.date(), week_end)
        day = first_day
        while day <= last_day:
            bookings_by_resource_and_day.setdefault((booking.resource_id, day), []).append(booking)
            day += timedelta(days=1)

    rows = [
        {
            "resource": resource,
            "cells": [bookings_by_resource_and_day.get((resource.id, day), []) for day in week_days],
        }
        for resource in resources
    ]

    return render(
        request,
        "staff/booking_calendar.html",
        {
            "week_days": week_days,
            "rows": rows,
            "week_start": week_start,
            "week_end": week_end,
            "previous_week": (week_start - timedelta(days=7)).isoformat(),
            "next_week": (week_start + timedelta(days=7)).isoformat(),
            "this_week": today.isoformat(),
            "today": today,
            "active_tab": "booking",
        },
    )


@staff_permission_required("booking.add_resourcebooking")
def booking_create(request):
    if request.method == "POST":
        form = StaffResourceBookingForm(request.POST)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.booked_by = getattr(request.user, "member_profile", None)
            booking.save()
            messages.success(request, f"{booking.resource} was booked for {booking.title}.")
            return redirect("staff_booking_list")
    else:
        initial = {}
        event_id = request.GET.get("event")
        if event_id:
            event = Event.objects.filter(id=event_id).first()
            if event:
                initial = {
                    "event": event.id,
                    "title": event.title,
                    "start_datetime": event.start_datetime,
                    "end_datetime": event.end_datetime or event.start_datetime,
                }
        form = StaffResourceBookingForm(initial=initial)
    return render(request, "staff/booking_form.html", {"form": form, "is_new": True, "active_tab": "booking"})


@staff_permission_required("booking.change_resourcebooking")
def booking_edit(request, booking_id):
    booking = get_object_or_404(ResourceBooking, id=booking_id)
    if request.method == "POST":
        form = StaffResourceBookingForm(request.POST, instance=booking)
        if form.is_valid():
            form.save()
            messages.success(request, f"The booking for {booking.resource} was updated.")
            return redirect("staff_booking_list")
    else:
        form = StaffResourceBookingForm(instance=booking)
    return render(
        request, "staff/booking_form.html", {"form": form, "is_new": False, "booking": booking, "active_tab": "booking"}
    )


# --- Pastoral care requests --------------------------------------------------
# Every view below is gated on a care.* permission, which only the Pastors
# group is ever granted (see PASTOR_MODELS in setup_groups.py) - so these
# requests never reach an Usher or Treasurer account, by design.


@staff_permission_required("care.view_carerequest")
def care_request_list(request):
    requests_qs = CareRequest.objects.select_related("member", "assigned_pastor").order_by(
        "status", "-created_at"
    )
    show = request.GET.get("show", "")
    if show in (CareRequest.Status.SUBMITTED, CareRequest.Status.SCHEDULED, CareRequest.Status.COMPLETED):
        requests_qs = requests_qs.filter(status=show)
    else:
        show = ""
    page_obj = Paginator(requests_qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "staff/care_request_list.html",
        {"page_obj": page_obj, "show": show, "active_tab": "care"},
    )


@staff_permission_required("care.view_carerequest")
def care_request_detail(request, care_request_id):
    care_request = get_object_or_404(CareRequest, id=care_request_id)
    can_change = request.user.has_perm("care.change_carerequest")
    if request.method == "POST" and can_change:
        form = StaffCareRequestUpdateForm(request.POST, instance=care_request)
        if form.is_valid():
            form.save()
            messages.success(request, "The care request was updated.")
            return redirect("staff_care_request_detail", care_request_id=care_request.id)
    else:
        form = StaffCareRequestUpdateForm(instance=care_request)
    return render(
        request,
        "staff/care_request_detail.html",
        {"care_request": care_request, "form": form, "can_change": can_change, "active_tab": "care"},
    )


# --- Church-wide surveys/polls ----------------------------------------------


@staff_permission_required("surveys.view_survey")
def survey_list(request):
    surveys = Survey.objects.all()
    return render(
        request,
        "staff/survey_list.html",
        {"surveys": surveys, "can_add": request.user.has_perm("surveys.add_survey"), "active_tab": "surveys"},
    )


@staff_permission_required("surveys.add_survey")
def survey_create(request):
    if request.method == "POST":
        form = StaffSurveyForm(request.POST)
        if form.is_valid():
            survey = form.save(commit=False)
            survey.created_by = request.user
            survey.save()
            messages.success(request, f"{survey.title} was created - add some questions below.")
            return redirect("staff_survey_detail", survey_id=survey.id)
    else:
        form = StaffSurveyForm()
    return render(request, "staff/survey_form.html", {"form": form, "is_new": True, "active_tab": "surveys"})


@staff_permission_required("surveys.change_survey")
def survey_edit(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id)
    if request.method == "POST":
        form = StaffSurveyForm(request.POST, instance=survey)
        if form.is_valid():
            form.save()
            messages.success(request, f"{survey.title} was updated.")
            return redirect("staff_survey_detail", survey_id=survey.id)
    else:
        form = StaffSurveyForm(instance=survey)
    return render(
        request, "staff/survey_form.html", {"form": form, "is_new": False, "survey": survey, "active_tab": "surveys"}
    )


@staff_permission_required("surveys.view_survey")
def survey_detail(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id)
    questions = survey.questions.prefetch_related("choices")
    response_count = survey.responses.count()
    results = aggregate_results(survey) if response_count else None
    return render(
        request,
        "staff/survey_detail.html",
        {
            "survey": survey,
            "questions": questions,
            "response_count": response_count,
            "results": results,
            "question_form": StaffSurveyQuestionForm(),
            "choice_form": StaffSurveyChoiceForm(),
            "can_change": request.user.has_perm("surveys.change_survey"),
            "can_add_question": request.user.has_perm("surveys.add_surveyquestion"),
            "can_add_choice": request.user.has_perm("surveys.add_surveychoice"),
            "active_tab": "surveys",
        },
    )


@staff_permission_required("surveys.add_surveyquestion")
def survey_question_add(request, survey_id):
    survey = get_object_or_404(Survey, id=survey_id)
    if request.method == "POST":
        form = StaffSurveyQuestionForm(request.POST)
        if form.is_valid():
            question = form.save(commit=False)
            question.survey = survey
            question.save()
            messages.success(request, f"\"{question.text}\" was added to {survey.title}.")
        else:
            messages.error(request, "Couldn't add that question - please try again.")
    return redirect("staff_survey_detail", survey_id=survey.id)


@staff_permission_required("surveys.add_surveychoice")
def survey_choice_add(request, survey_id, question_id):
    question = get_object_or_404(SurveyQuestion, id=question_id, survey_id=survey_id)
    if request.method == "POST":
        form = StaffSurveyChoiceForm(request.POST)
        if form.is_valid():
            choice = form.save(commit=False)
            choice.question = question
            choice.save()
            messages.success(request, f"\"{choice.text}\" was added to \"{question.text}\".")
        else:
            messages.error(request, "Couldn't add that choice - please try again.")
    return redirect("staff_survey_detail", survey_id=survey_id)


# --- Baby dedication & wedding records --------------------------------------


@staff_permission_required("milestones.view_babydedication")
def dedication_list(request):
    dedications = BabyDedication.objects.prefetch_related("parents")
    return render(
        request,
        "staff/dedication_list.html",
        {
            "dedications": dedications,
            "can_add": request.user.has_perm("milestones.add_babydedication"),
            "active_tab": "milestones",
        },
    )


@staff_permission_required("milestones.add_babydedication")
def dedication_create(request):
    if request.method == "POST":
        form = StaffBabyDedicationForm(request.POST)
        if form.is_valid():
            dedication = form.save()
            messages.success(request, f"{dedication} was recorded.")
            return redirect("staff_dedication_list")
    else:
        form = StaffBabyDedicationForm()
    return render(request, "staff/dedication_form.html", {"form": form, "is_new": True, "active_tab": "milestones"})


@staff_permission_required("milestones.change_babydedication")
def dedication_edit(request, dedication_id):
    dedication = get_object_or_404(BabyDedication, id=dedication_id)
    if request.method == "POST":
        form = StaffBabyDedicationForm(request.POST, instance=dedication)
        if form.is_valid():
            form.save()
            messages.success(request, f"{dedication} was updated.")
            return redirect("staff_dedication_list")
    else:
        form = StaffBabyDedicationForm(instance=dedication)
    return render(
        request,
        "staff/dedication_form.html",
        {"form": form, "is_new": False, "dedication": dedication, "active_tab": "milestones"},
    )


@staff_permission_required("milestones.view_babydedication")
def dedication_certificate(request, dedication_id):
    dedication = get_object_or_404(BabyDedication.objects.prefetch_related("parents"), id=dedication_id)
    return render(request, "staff/dedication_certificate.html", {"dedication": dedication})


@staff_permission_required("milestones.view_weddingrecord")
def wedding_list(request):
    weddings = WeddingRecord.objects.select_related("spouse_one", "spouse_two")
    return render(
        request,
        "staff/wedding_list.html",
        {
            "weddings": weddings,
            "can_add": request.user.has_perm("milestones.add_weddingrecord"),
            "active_tab": "milestones",
        },
    )


@staff_permission_required("milestones.add_weddingrecord")
def wedding_create(request):
    if request.method == "POST":
        form = StaffWeddingRecordForm(request.POST)
        if form.is_valid():
            wedding = form.save()
            messages.success(request, f"{wedding} was recorded.")
            return redirect("staff_wedding_list")
    else:
        form = StaffWeddingRecordForm()
    return render(request, "staff/wedding_form.html", {"form": form, "is_new": True, "active_tab": "milestones"})


@staff_permission_required("milestones.change_weddingrecord")
def wedding_edit(request, wedding_id):
    wedding = get_object_or_404(WeddingRecord, id=wedding_id)
    if request.method == "POST":
        form = StaffWeddingRecordForm(request.POST, instance=wedding)
        if form.is_valid():
            form.save()
            messages.success(request, f"{wedding} was updated.")
            return redirect("staff_wedding_list")
    else:
        form = StaffWeddingRecordForm(instance=wedding)
    return render(
        request, "staff/wedding_form.html", {"form": form, "is_new": False, "wedding": wedding, "active_tab": "milestones"}
    )


@staff_permission_required("milestones.view_weddingrecord")
def wedding_certificate(request, wedding_id):
    wedding = get_object_or_404(WeddingRecord.objects.select_related("spouse_one", "spouse_two"), id=wedding_id)
    return render(request, "staff/wedding_certificate.html", {"wedding": wedding})


# --- Baptism records -----------------------------------------------------------
# The third milestone type, same Pastor-only management as baby dedications
# and weddings above (see PASTOR_MODELS). Unlike the others, a member can
# have more than one record here (see BaptismRecord's docstring), so there's
# no "already has one" guard in baptism_create.


@staff_permission_required("milestones.view_baptismrecord")
def baptism_list(request):
    baptisms = BaptismRecord.objects.select_related("member")
    return render(
        request,
        "staff/baptism_list.html",
        {
            "baptisms": baptisms,
            "can_add": request.user.has_perm("milestones.add_baptismrecord"),
            "active_tab": "milestones",
        },
    )


@staff_permission_required("milestones.add_baptismrecord")
def baptism_create(request):
    initial = {}
    member_id = request.GET.get("member")
    if member_id:
        initial = {"member": member_id}
    if request.method == "POST":
        form = StaffBaptismRecordForm(request.POST)
        if form.is_valid():
            baptism = form.save()
            messages.success(request, f"{baptism} was recorded.")
            return redirect("staff_baptism_list")
    else:
        form = StaffBaptismRecordForm(initial=initial)
    return render(request, "staff/baptism_form.html", {"form": form, "is_new": True, "active_tab": "milestones"})


@staff_permission_required("milestones.change_baptismrecord")
def baptism_edit(request, baptism_id):
    baptism = get_object_or_404(BaptismRecord, id=baptism_id)
    if request.method == "POST":
        form = StaffBaptismRecordForm(request.POST, instance=baptism)
        if form.is_valid():
            form.save()
            messages.success(request, f"{baptism} was updated.")
            return redirect("staff_baptism_list")
    else:
        form = StaffBaptismRecordForm(instance=baptism)
    return render(
        request,
        "staff/baptism_form.html",
        {"form": form, "is_new": False, "baptism": baptism, "active_tab": "milestones"},
    )


@staff_permission_required("milestones.view_baptismrecord")
def baptism_certificate(request, baptism_id):
    baptism = get_object_or_404(BaptismRecord.objects.select_related("member"), id=baptism_id)
    return render(request, "staff/baptism_certificate.html", {"baptism": baptism})


# --- Funeral / bereavement records --------------------------------------------
# The fourth milestone type, same Pastor-only management as baby dedications,
# weddings, and baptisms above (see PASTOR_MODELS).


@staff_permission_required("milestones.view_funeralrecord")
def funeral_list(request):
    funerals = FuneralRecord.objects.select_related("member").prefetch_related("family_contacts")
    return render(
        request,
        "staff/funeral_list.html",
        {
            "funerals": funerals,
            "can_add": request.user.has_perm("milestones.add_funeralrecord"),
            "active_tab": "milestones",
        },
    )


@staff_permission_required("milestones.add_funeralrecord")
def funeral_create(request):
    initial = {}
    member_id = request.GET.get("member")
    if member_id:
        initial = {"member": member_id}
    if request.method == "POST":
        form = StaffFuneralRecordForm(request.POST)
        if form.is_valid():
            funeral = form.save()
            messages.success(request, f"{funeral} was recorded.")
            return redirect("staff_funeral_list")
    else:
        form = StaffFuneralRecordForm(initial=initial)
    return render(request, "staff/funeral_form.html", {"form": form, "is_new": True, "active_tab": "milestones"})


@staff_permission_required("milestones.change_funeralrecord")
def funeral_edit(request, funeral_id):
    funeral = get_object_or_404(FuneralRecord, id=funeral_id)
    if request.method == "POST":
        form = StaffFuneralRecordForm(request.POST, instance=funeral)
        if form.is_valid():
            form.save()
            messages.success(request, f"{funeral} was updated.")
            return redirect("staff_funeral_list")
    else:
        form = StaffFuneralRecordForm(instance=funeral)
    return render(
        request,
        "staff/funeral_form.html",
        {"form": form, "is_new": False, "funeral": funeral, "active_tab": "milestones"},
    )


@staff_permission_required("milestones.view_funeralrecord")
def funeral_program(request, funeral_id):
    funeral = get_object_or_404(
        FuneralRecord.objects.select_related("member").prefetch_related("family_contacts"), id=funeral_id
    )
    return render(request, "staff/funeral_program.html", {"funeral": funeral})


# --- Membership transfer letters -----------------------------------------------
# The fifth milestone type, same Pastor-only management as the other four
# above (see PASTOR_MODELS). Like BaptismRecord, a member can have more than
# one over the years, so there's no "already has one" guard in the create view.


@staff_permission_required("milestones.view_transferletter")
def transfer_letter_list(request):
    transfer_letters = TransferLetter.objects.select_related("member")
    return render(
        request,
        "staff/transfer_letter_list.html",
        {
            "transfer_letters": transfer_letters,
            "can_add": request.user.has_perm("milestones.add_transferletter"),
            "active_tab": "milestones",
        },
    )


@staff_permission_required("milestones.add_transferletter")
def transfer_letter_create(request):
    initial = {}
    member_id = request.GET.get("member")
    if member_id:
        initial = {"member": member_id}
    if request.method == "POST":
        form = StaffTransferLetterForm(request.POST)
        if form.is_valid():
            transfer_letter = form.save()
            messages.success(request, f"{transfer_letter} was recorded.")
            return redirect("staff_transfer_letter_list")
    else:
        form = StaffTransferLetterForm(initial=initial)
    return render(
        request, "staff/transfer_letter_form.html", {"form": form, "is_new": True, "active_tab": "milestones"}
    )


@staff_permission_required("milestones.change_transferletter")
def transfer_letter_edit(request, transfer_letter_id):
    transfer_letter = get_object_or_404(TransferLetter, id=transfer_letter_id)
    if request.method == "POST":
        form = StaffTransferLetterForm(request.POST, instance=transfer_letter)
        if form.is_valid():
            form.save()
            messages.success(request, f"{transfer_letter} was updated.")
            return redirect("staff_transfer_letter_list")
    else:
        form = StaffTransferLetterForm(instance=transfer_letter)
    return render(
        request,
        "staff/transfer_letter_form.html",
        {"form": form, "is_new": False, "transfer_letter": transfer_letter, "active_tab": "milestones"},
    )


@staff_permission_required("milestones.view_transferletter")
def transfer_letter_view(request, transfer_letter_id):
    transfer_letter = get_object_or_404(TransferLetter.objects.select_related("member"), id=transfer_letter_id)
    return render(request, "staff/transfer_letter_view.html", {"transfer_letter": transfer_letter})


# --- Volunteer background checks ---------------------------------------------
# Pastors get full view/add/change (see PASTOR_MODELS); Children's Ministry
# gets view-only, so they can confirm a volunteer is cleared without being
# able to change a check's status themselves (see setup_groups.py).


@staff_permission_required("screening.view_backgroundcheck")
def background_check_list(request):
    checks = BackgroundCheck.objects.select_related("member").all()
    show = request.GET.get("show", "")
    if show == "expiring":
        checks = [check for check in checks if check.is_expiring_soon]
    elif show in BackgroundCheck.Status.values:
        checks = checks.filter(status=show)
    else:
        show = ""
    return render(
        request,
        "staff/background_check_list.html",
        {
            "checks": checks,
            "show": show,
            "can_add": request.user.has_perm("screening.add_backgroundcheck"),
            "active_tab": "screening",
        },
    )


@staff_permission_required("screening.add_backgroundcheck")
def background_check_create(request):
    initial = {}
    member_id = request.GET.get("member")
    if member_id:
        initial = {"member": member_id}
    if request.method == "POST":
        form = StaffBackgroundCheckForm(request.POST)
        if form.is_valid():
            background_check = form.save()
            messages.success(request, f"Background check added for {background_check.member}.")
            return redirect("staff_background_check_list")
    else:
        form = StaffBackgroundCheckForm(initial=initial)
    return render(
        request, "staff/background_check_form.html", {"form": form, "is_new": True, "active_tab": "screening"}
    )


@staff_permission_required("screening.change_backgroundcheck")
def background_check_edit(request, background_check_id):
    background_check = get_object_or_404(BackgroundCheck, id=background_check_id)
    if request.method == "POST":
        form = StaffBackgroundCheckForm(request.POST, instance=background_check)
        if form.is_valid():
            form.save()
            messages.success(request, f"The background check for {background_check.member} was updated.")
            return redirect("staff_background_check_list")
    else:
        form = StaffBackgroundCheckForm(instance=background_check)
    return render(
        request,
        "staff/background_check_form.html",
        {"form": form, "is_new": False, "background_check": background_check, "active_tab": "screening"},
    )


# --- Volunteer training/certification tracking --------------------------------
# Same permission split as background checks above (see setup_groups.py):
# Pastors get full view/add/change; Children's Ministry gets view-only, so
# they can confirm a volunteer's completed a required training (e.g. Child
# Safety) without being able to log a completion themselves.


@staff_permission_required("screening.view_volunteertraining")
def training_list(request):
    trainings = VolunteerTraining.objects.select_related("member").all()
    show = request.GET.get("show", "")
    if show == "expiring":
        trainings = [training for training in trainings if training.is_expiring_soon]
    elif show in VolunteerTraining.Status.values:
        trainings = trainings.filter(status=show)
    else:
        show = ""
    return render(
        request,
        "staff/training_list.html",
        {
            "trainings": trainings,
            "show": show,
            "can_add": request.user.has_perm("screening.add_volunteertraining"),
            "active_tab": "screening",
        },
    )


@staff_permission_required("screening.add_volunteertraining")
def training_create(request):
    initial = {}
    member_id = request.GET.get("member")
    if member_id:
        initial = {"member": member_id}
    if request.method == "POST":
        form = StaffVolunteerTrainingForm(request.POST)
        if form.is_valid():
            training = form.save()
            messages.success(request, f"{training.training_name} training added for {training.member}.")
            return redirect("staff_training_list")
    else:
        form = StaffVolunteerTrainingForm(initial=initial)
    return render(request, "staff/training_form.html", {"form": form, "is_new": True, "active_tab": "screening"})


@staff_permission_required("screening.change_volunteertraining")
def training_edit(request, training_id):
    training = get_object_or_404(VolunteerTraining, id=training_id)
    if request.method == "POST":
        form = StaffVolunteerTrainingForm(request.POST, instance=training)
        if form.is_valid():
            form.save()
            messages.success(request, f"The {training.training_name} training for {training.member} was updated.")
            return redirect("staff_training_list")
    else:
        form = StaffVolunteerTrainingForm(instance=training)
    return render(
        request,
        "staff/training_form.html",
        {"form": form, "is_new": False, "training": training, "active_tab": "screening"},
    )


# --- Facility maintenance requests --------------------------------------------
# Ushers get view/add (they're usually first to notice something's broken);
# resolving/closing a ticket stays Pastor-only change permission (see
# setup_groups.py).


@staff_permission_required("maintenance.view_maintenancerequest")
def maintenance_list(request):
    requests_qs = MaintenanceRequest.objects.select_related("resource", "reported_by").all()
    return render(
        request,
        "staff/maintenance_list.html",
        {
            "open_requests": requests_qs.filter(status=MaintenanceRequest.Status.OPEN),
            "in_progress_requests": requests_qs.filter(status=MaintenanceRequest.Status.IN_PROGRESS),
            "done_requests": requests_qs.filter(status=MaintenanceRequest.Status.DONE)[:15],
            "can_add": request.user.has_perm("maintenance.add_maintenancerequest"),
            "can_change": request.user.has_perm("maintenance.change_maintenancerequest"),
            "active_tab": "maintenance",
        },
    )


@staff_permission_required("maintenance.add_maintenancerequest")
def maintenance_create(request):
    if request.method == "POST":
        form = StaffMaintenanceRequestForm(request.POST)
        if form.is_valid():
            maintenance_request = form.save(commit=False)
            maintenance_request.reported_by = getattr(request.user, "member_profile", None)
            maintenance_request.save()
            messages.success(request, f"\"{maintenance_request.title}\" was logged.")
            return redirect("staff_maintenance_list")
    else:
        form = StaffMaintenanceRequestForm()
    return render(request, "staff/maintenance_form.html", {"form": form, "active_tab": "maintenance"})


@staff_permission_required("maintenance.change_maintenancerequest")
def maintenance_update_status(request, maintenance_request_id):
    maintenance_request = get_object_or_404(MaintenanceRequest, id=maintenance_request_id)
    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status in MaintenanceRequest.Status.values:
            notes = request.POST.get("resolution_notes", "").strip()
            if notes:
                maintenance_request.resolution_notes = notes
                maintenance_request.save(update_fields=["resolution_notes"])
            maintenance_request.mark_status(new_status)
            messages.success(
                request, f"\"{maintenance_request.title}\" marked {maintenance_request.get_status_display()}."
            )
    return redirect("staff_maintenance_list")


# --- Equipment / asset inventory ---------------------------------------------
# Separate from booking.Resource (a room/vehicle reserved for a time block) -
# see equipment/models.py's Equipment docstring. Managing the catalog itself
# (add/edit an item) is Pastor-only, same as booking.Resource, but checking
# an item in/out is also open to Ushers - they're the ones actually handling
# the gear week to week.

@staff_permission_required("equipment.view_equipment")
def equipment_list(request):
    items = Equipment.objects.filter(is_active=True).select_related("campus")
    return render(
        request,
        "staff/equipment_list.html",
        {
            "items": items,
            "can_add": request.user.has_perm("equipment.add_equipment"),
            "active_tab": "equipment",
        },
    )


@staff_permission_required("equipment.add_equipment")
def equipment_create(request):
    if request.method == "POST":
        form = StaffEquipmentForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f"{item} added.")
            return redirect("staff_equipment_detail", item_id=item.id)
    else:
        form = StaffEquipmentForm()
    return render(request, "staff/equipment_form.html", {"form": form, "is_new": True, "active_tab": "equipment"})


@staff_permission_required("equipment.change_equipment")
def equipment_edit(request, item_id):
    item = get_object_or_404(Equipment, id=item_id)
    if request.method == "POST":
        form = StaffEquipmentForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f"{item} updated.")
            return redirect("staff_equipment_detail", item_id=item.id)
    else:
        form = StaffEquipmentForm(instance=item)
    return render(
        request, "staff/equipment_form.html", {"form": form, "item": item, "is_new": False, "active_tab": "equipment"}
    )


@staff_permission_required("equipment.view_equipment")
def equipment_detail(request, item_id):
    item = get_object_or_404(Equipment, id=item_id)
    return render(
        request,
        "staff/equipment_detail.html",
        {
            "item": item,
            "checkouts": item.checkouts.select_related("checked_out_to"),
            "maintenance_requests": item.maintenance_requests.all(),
            "checkout_form": StaffEquipmentCheckoutForm(),
            "can_edit": request.user.has_perm("equipment.change_equipment"),
            "can_checkout": request.user.has_perm("equipment.add_equipmentcheckout"),
            "can_checkin": request.user.has_perm("equipment.change_equipmentcheckout"),
            "active_tab": "equipment",
        },
    )


@staff_permission_required("equipment.add_equipmentcheckout")
def equipment_checkout(request, item_id):
    item = get_object_or_404(Equipment, id=item_id)
    if item.is_checked_out:
        messages.error(request, f"{item} is already checked out.")
        return redirect("staff_equipment_detail", item_id=item.id)

    if request.method == "POST":
        form = StaffEquipmentCheckoutForm(request.POST)
        if form.is_valid():
            checkout = form.save(commit=False)
            checkout.equipment = item
            checkout.save()
            LogEntry.objects.log_action(
                user_id=request.user.pk,
                content_type_id=ContentType.objects.get_for_model(checkout).pk,
                object_id=checkout.pk,
                object_repr=str(checkout),
                action_flag=ADDITION,
                change_message=f"Checked out {item} to {checkout.checked_out_to}.",
            )
            messages.success(request, f"{item} checked out to {checkout.checked_out_to}.")
    return redirect("staff_equipment_detail", item_id=item.id)


@staff_permission_required("equipment.change_equipmentcheckout")
def equipment_checkin(request, checkout_id):
    checkout = get_object_or_404(EquipmentCheckout, id=checkout_id, checked_in_at__isnull=True)
    if request.method == "POST":
        checkout.checked_in_at = timezone.now()
        checkout.save(update_fields=["checked_in_at"])
        LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ContentType.objects.get_for_model(checkout).pk,
            object_id=checkout.pk,
            object_repr=str(checkout),
            action_flag=CHANGE,
            change_message=f"Checked {checkout.equipment} back in.",
        )
        messages.success(request, f"{checkout.equipment} checked back in.")
    return redirect("staff_equipment_detail", item_id=checkout.equipment_id)


# --- Church library / resource lending -----------------------------------
# Books, DVDs, CDs and curriculum kits the church lends out - same
# "catalog + loan" shape as Equipment/EquipmentCheckout above, just with a
# due date on each loan. Managing the catalog itself (add/edit an item) is
# Pastor-only, same as Equipment, but checking an item out/in is also open
# to Ushers - same split as equipment.


@staff_permission_required("library.view_libraryitem")
def library_list(request):
    items = LibraryItem.objects.filter(is_active=True)

    show = request.GET.get("show", "")
    if show == "overdue":
        items = [item for item in items if item.current_loan and item.current_loan.is_overdue]
    elif show == "on_loan":
        items = [item for item in items if item.is_on_loan]

    return render(
        request,
        "staff/library_list.html",
        {
            "items": items,
            "show": show,
            "can_add": request.user.has_perm("library.add_libraryitem"),
            "active_tab": "library",
        },
    )


@staff_permission_required("library.add_libraryitem")
def library_item_create(request):
    if request.method == "POST":
        form = StaffLibraryItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f"{item} added.")
            return redirect("staff_library_item_detail", item_id=item.id)
    else:
        form = StaffLibraryItemForm()
    return render(request, "staff/library_item_form.html", {"form": form, "is_new": True, "active_tab": "library"})


@staff_permission_required("library.change_libraryitem")
def library_item_edit(request, item_id):
    item = get_object_or_404(LibraryItem, id=item_id)
    if request.method == "POST":
        form = StaffLibraryItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f"{item} updated.")
            return redirect("staff_library_item_detail", item_id=item.id)
    else:
        form = StaffLibraryItemForm(instance=item)
    return render(
        request,
        "staff/library_item_form.html",
        {"form": form, "item": item, "is_new": False, "active_tab": "library"},
    )


@staff_permission_required("library.view_libraryitem")
def library_item_detail(request, item_id):
    item = get_object_or_404(LibraryItem, id=item_id)
    return render(
        request,
        "staff/library_item_detail.html",
        {
            "item": item,
            "loans": item.loans.select_related("borrower"),
            "loan_form": StaffLibraryLoanForm(),
            "can_edit": request.user.has_perm("library.change_libraryitem"),
            "can_checkout": request.user.has_perm("library.add_libraryloan"),
            "can_return": request.user.has_perm("library.change_libraryloan"),
            "active_tab": "library",
        },
    )


@staff_permission_required("library.add_libraryloan")
def library_checkout(request, item_id):
    item = get_object_or_404(LibraryItem, id=item_id)
    if item.is_on_loan:
        messages.error(request, f"{item} is already on loan.")
        return redirect("staff_library_item_detail", item_id=item.id)

    if request.method == "POST":
        form = StaffLibraryLoanForm(request.POST)
        if form.is_valid():
            loan = form.save(commit=False)
            loan.item = item
            loan.save()
            LogEntry.objects.log_action(
                user_id=request.user.pk,
                content_type_id=ContentType.objects.get_for_model(loan).pk,
                object_id=loan.pk,
                object_repr=str(loan),
                action_flag=ADDITION,
                change_message=f"Loaned {item} to {loan.borrower}.",
            )
            messages.success(request, f"{item} loaned to {loan.borrower}.")
    return redirect("staff_library_item_detail", item_id=item.id)


@staff_permission_required("library.change_libraryloan")
def library_return(request, loan_id):
    loan = get_object_or_404(LibraryLoan, id=loan_id, returned_date__isnull=True)
    if request.method == "POST":
        loan.returned_date = timezone.localdate()
        loan.save(update_fields=["returned_date"])
        LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ContentType.objects.get_for_model(loan).pk,
            object_id=loan.pk,
            object_repr=str(loan),
            action_flag=CHANGE,
            change_message=f"Returned {loan.item}.",
        )
        messages.success(request, f"{loan.item} returned.")
    return redirect("staff_library_item_detail", item_id=loan.item_id)


# --- Sunday school / kids curriculum tracker ---------------------------------
# Staff-only (Children's Ministry/Pastors) - unlike a small group's own
# leader (see members/views.py's group_lessons), a Sunday school teacher
# doesn't get a separate self-service portal here.


@staff_permission_required("checkin.view_sundayschoolclass")
def sunday_school_class_list(request):
    classes = SundaySchoolClass.objects.select_related("teacher").prefetch_related("children")
    return render(
        request,
        "staff/sunday_school_class_list.html",
        {
            "classes": classes,
            "can_add": request.user.has_perm("checkin.add_sundayschoolclass"),
            "active_tab": "children",
        },
    )


@staff_permission_required("checkin.add_sundayschoolclass")
def sunday_school_class_create(request):
    if request.method == "POST":
        form = StaffSundaySchoolClassForm(request.POST)
        if form.is_valid():
            sunday_school_class = form.save()
            messages.success(request, f"{sunday_school_class} was added.")
            return redirect("staff_sunday_school_class_detail", class_id=sunday_school_class.id)
    else:
        form = StaffSundaySchoolClassForm()
    return render(
        request, "staff/sunday_school_class_form.html", {"form": form, "is_new": True, "active_tab": "children"}
    )


@staff_permission_required("checkin.change_sundayschoolclass")
def sunday_school_class_edit(request, class_id):
    sunday_school_class = get_object_or_404(SundaySchoolClass, id=class_id)
    if request.method == "POST":
        form = StaffSundaySchoolClassForm(request.POST, instance=sunday_school_class)
        if form.is_valid():
            form.save()
            messages.success(request, f"{sunday_school_class} was updated.")
            return redirect("staff_sunday_school_class_detail", class_id=sunday_school_class.id)
    else:
        form = StaffSundaySchoolClassForm(instance=sunday_school_class)
    return render(
        request,
        "staff/sunday_school_class_form.html",
        {"form": form, "is_new": False, "sunday_school_class": sunday_school_class, "active_tab": "children"},
    )


@staff_permission_required("checkin.view_sundayschoolclass")
def sunday_school_class_detail(request, class_id):
    sunday_school_class = get_object_or_404(
        SundaySchoolClass.objects.select_related("teacher"), id=class_id
    )
    roster = sunday_school_class.children.filter(is_active=True).order_by("last_name", "first_name")
    lessons = sunday_school_class.lessons.select_related("posted_by")
    can_add_lesson = request.user.has_perm("checkin.add_sundayschoollesson")

    can_manage_roster = request.user.has_perm("checkin.change_sundayschoolclass")
    other_children = None
    if can_manage_roster:
        current_child_ids = roster.values_list("id", flat=True)
        other_children = Child.objects.filter(is_active=True).exclude(id__in=current_child_ids).order_by(
            "last_name", "first_name"
        )

    if request.method == "POST" and can_add_lesson:
        lesson_form = StaffSundaySchoolLessonForm(request.POST)
        if lesson_form.is_valid():
            lesson = lesson_form.save(commit=False)
            lesson.sunday_school_class = sunday_school_class
            lesson.posted_by = getattr(request.user, "member_profile", None)
            lesson.save()
            messages.success(request, f"\"{lesson.title}\" was posted for {sunday_school_class}.")
            return redirect("staff_sunday_school_class_detail", class_id=sunday_school_class.id)
    else:
        lesson_form = StaffSundaySchoolLessonForm()

    return render(
        request,
        "staff/sunday_school_class_detail.html",
        {
            "sunday_school_class": sunday_school_class,
            "roster": roster,
            "lessons": lessons,
            "lesson_form": lesson_form,
            "can_add_lesson": can_add_lesson,
            "can_edit": request.user.has_perm("checkin.change_sundayschoolclass"),
            "can_manage_roster": can_manage_roster,
            "other_children": other_children,
            "active_tab": "children",
        },
    )


@staff_permission_required("checkin.change_sundayschoolclass")
def sunday_school_class_add_child(request, class_id):
    sunday_school_class = get_object_or_404(SundaySchoolClass, id=class_id)
    if request.method == "POST":
        child = get_object_or_404(Child, id=request.POST.get("child_id"))
        sunday_school_class.children.add(child)
        messages.success(request, f"{child} was added to {sunday_school_class}.")
    return redirect("staff_sunday_school_class_detail", class_id=sunday_school_class.id)


@staff_permission_required("checkin.change_sundayschoolclass")
def sunday_school_class_remove_child(request, class_id, child_id):
    sunday_school_class = get_object_or_404(SundaySchoolClass, id=class_id)
    if request.method == "POST":
        child = get_object_or_404(Child, id=child_id)
        sunday_school_class.children.remove(child)
        messages.success(request, f"{child} was removed from {sunday_school_class}.")
    return redirect("staff_sunday_school_class_detail", class_id=sunday_school_class.id)


# --- Volunteer service-hour tracking ------------------------------------------


@staff_permission_required("servicehours.view_servicehourlog")
def service_hour_report(request):
    """
    Per-member and per-group service-hour totals for a year, plus the raw
    log underneath - browsable without exporting anything, same style as
    giving_by_member_report above.
    """
    current_year = timezone.localdate().year
    try:
        year = int(request.GET.get("year", current_year))
    except ValueError:
        year = current_year

    logs = ServiceHourLog.objects.filter(date__year=year)
    by_member = list(
        logs.values("member__id", "member__first_name", "member__last_name")
        .annotate(total_hours=Sum("hours"))
        .order_by("-total_hours")
    )
    by_group = list(
        logs.exclude(group__isnull=True)
        .values("group__id", "group__name")
        .annotate(total_hours=Sum("hours"))
        .order_by("-total_hours")
    )
    available_years = list(range(current_year, current_year - 5, -1))
    page_obj = Paginator(
        logs.select_related("member", "group", "event").order_by("-date"), 25
    ).get_page(request.GET.get("page"))

    return render(
        request,
        "staff/service_hour_report.html",
        {
            "year": year,
            "available_years": available_years,
            "by_member": by_member,
            "by_group": by_group,
            "page_obj": page_obj,
            "can_add": request.user.has_perm("servicehours.add_servicehourlog"),
            "can_change": request.user.has_perm("servicehours.change_servicehourlog"),
            "active_tab": "service_hours",
        },
    )


@staff_permission_required("servicehours.add_servicehourlog")
def service_hour_create(request):
    if request.method == "POST":
        form = StaffServiceHourLogForm(request.POST)
        if form.is_valid():
            log = form.save()
            messages.success(request, f"Logged {log.hours}h for {log.member}.")
            return redirect("staff_service_hour_report")
    else:
        form = StaffServiceHourLogForm()
    return render(
        request, "staff/service_hour_form.html", {"form": form, "is_new": True, "active_tab": "service_hours"}
    )


@staff_permission_required("servicehours.change_servicehourlog")
def service_hour_edit(request, log_id):
    log = get_object_or_404(ServiceHourLog, id=log_id)
    if request.method == "POST":
        form = StaffServiceHourLogForm(request.POST, instance=log)
        if form.is_valid():
            form.save()
            messages.success(request, "The log was updated.")
            return redirect("staff_service_hour_report")
    else:
        form = StaffServiceHourLogForm(instance=log)
    return render(
        request,
        "staff/service_hour_form.html",
        {"form": form, "is_new": False, "log": log, "active_tab": "service_hours"},
    )


@staff_permission_required("servicehours.view_servicehourlog")
def service_hour_certificate_pdf(request, member_id, year):
    """
    A downloadable "Certificate of Volunteer Service" PDF totaling one
    member's logged hours for a given year, with the underlying log
    itemized beneath it - see servicehours/pdfs.py. Reachable from the
    "Totals by Member" list on service_hour_report above. Same permission
    as that report - servicehourlog is Pastor-only (see PASTOR_MODELS).
    """
    member = get_object_or_404(Member, id=optional_id(member_id))
    logs = ServiceHourLog.objects.filter(member=member, date__year=year).order_by("date")
    total_hours = logs.aggregate(total=Sum("hours"))["total"] or Decimal("0.00")
    pdf_bytes = build_service_hour_certificate_pdf(member, year, logs, total_hours)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    filename = f"service-hours-{member.last_name}-{member.first_name}-{year}.pdf".replace(" ", "-")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# --- Church expense tracking / budgeting --------------------------------------
# Granted the same way as giving campaigns/donations - Treasurers manage this
# day to day, Pastors get it too via PASTOR_MODELS.


@staff_permission_required("expenses.view_expense")
def expense_report(request):
    """Budget categories with spend-vs-budget for a year, plus the raw expense log underneath."""
    current_year = timezone.localdate().year
    try:
        year = int(request.GET.get("year", current_year))
    except ValueError:
        year = current_year

    categories = BudgetCategory.objects.all()
    category_rows = [
        {"category": category, "spent": category.spent_total(year=year), "percent": category.percent_of_budget}
        for category in categories
    ]
    expenses_qs = Expense.objects.filter(date__year=year).select_related("category", "campus")
    total_spent = expenses_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    available_years = list(range(current_year, current_year - 5, -1))
    page_obj = Paginator(expenses_qs.order_by("-date"), 25).get_page(request.GET.get("page"))

    return render(
        request,
        "staff/expense_report.html",
        {
            "year": year,
            "available_years": available_years,
            "category_rows": category_rows,
            "total_spent": total_spent,
            "page_obj": page_obj,
            "can_add": request.user.has_perm("expenses.add_expense"),
            "can_change": request.user.has_perm("expenses.change_expense"),
            "can_manage_categories": request.user.has_perm("expenses.add_budgetcategory"),
            "active_tab": "expenses",
        },
    )


@staff_permission_required("expenses.add_expense")
def expense_create(request):
    if request.method == "POST":
        form = StaffExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.recorded_by = request.user
            expense.save()
            messages.success(request, f"Logged GH₵{expense.amount} to {expense.paid_to or 'expenses'}.")
            return redirect("staff_expense_report")
    else:
        form = StaffExpenseForm()
    return render(request, "staff/expense_form.html", {"form": form, "is_new": True, "active_tab": "expenses"})


@staff_permission_required("expenses.change_expense")
def expense_edit(request, expense_id):
    expense = get_object_or_404(Expense, id=expense_id)
    if request.method == "POST":
        form = StaffExpenseForm(request.POST, request.FILES, instance=expense)
        if form.is_valid():
            form.save()
            messages.success(request, "The expense was updated.")
            return redirect("staff_expense_report")
    else:
        form = StaffExpenseForm(instance=expense)
    return render(
        request, "staff/expense_form.html", {"form": form, "is_new": False, "expense": expense, "active_tab": "expenses"}
    )


@staff_permission_required("expenses.view_budgetcategory")
def budget_category_list(request):
    categories = BudgetCategory.objects.all()
    return render(
        request,
        "staff/budget_category_list.html",
        {
            "categories": categories,
            "can_add": request.user.has_perm("expenses.add_budgetcategory"),
            "active_tab": "expenses",
        },
    )


@staff_permission_required("expenses.add_budgetcategory")
def budget_category_create(request):
    if request.method == "POST":
        form = StaffBudgetCategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            messages.success(request, f"{category} was added.")
            return redirect("staff_budget_category_list")
    else:
        form = StaffBudgetCategoryForm()
    return render(
        request, "staff/budget_category_form.html", {"form": form, "is_new": True, "active_tab": "expenses"}
    )


@staff_permission_required("expenses.change_budgetcategory")
def budget_category_edit(request, category_id):
    category = get_object_or_404(BudgetCategory, id=category_id)
    if request.method == "POST":
        form = StaffBudgetCategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, f"{category} was updated.")
            return redirect("staff_budget_category_list")
    else:
        form = StaffBudgetCategoryForm(instance=category)
    return render(
        request,
        "staff/budget_category_form.html",
        {"form": form, "is_new": False, "category": category, "active_tab": "expenses"},
    )


# --- Leadership meeting minutes -----------------------------------------------
# Pastor-only, same reasoning as CareRequest/MemberNote elsewhere in this
# project - no Usher/Treasurer/Children's Ministry grant ever touches the
# governance app's models (see setup_groups.py's PASTOR_MODELS).


@staff_permission_required("governance.view_meeting")
def meeting_list(request):
    meetings = Meeting.objects.all()
    return render(
        request,
        "staff/meeting_list.html",
        {
            "meetings": meetings,
            "can_add": request.user.has_perm("governance.add_meeting"),
            "active_tab": "governance",
        },
    )


@staff_permission_required("governance.add_meeting")
def meeting_create(request):
    if request.method == "POST":
        form = StaffMeetingForm(request.POST)
        if form.is_valid():
            meeting = form.save(commit=False)
            meeting.created_by = request.user
            meeting.save()
            form.save_m2m()
            messages.success(request, f"{meeting} was recorded.")
            return redirect("staff_meeting_detail", meeting_id=meeting.id)
    else:
        form = StaffMeetingForm()
    return render(request, "staff/meeting_form.html", {"form": form, "is_new": True, "active_tab": "governance"})


@staff_permission_required("governance.change_meeting")
def meeting_edit(request, meeting_id):
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if request.method == "POST":
        form = StaffMeetingForm(request.POST, instance=meeting)
        if form.is_valid():
            form.save()
            messages.success(request, f"{meeting} was updated.")
            return redirect("staff_meeting_detail", meeting_id=meeting.id)
    else:
        form = StaffMeetingForm(instance=meeting)
    return render(
        request,
        "staff/meeting_form.html",
        {"form": form, "is_new": False, "meeting": meeting, "active_tab": "governance"},
    )


@staff_permission_required("governance.view_meeting")
def meeting_detail(request, meeting_id):
    meeting = get_object_or_404(Meeting.objects.prefetch_related("attendees"), id=meeting_id)
    can_add_item = request.user.has_perm("governance.add_actionitem")
    return render(
        request,
        "staff/meeting_detail.html",
        {
            "meeting": meeting,
            "action_items": meeting.action_items.select_related("owner"),
            "can_edit": request.user.has_perm("governance.change_meeting"),
            "can_add_item": can_add_item,
            "can_change_item": request.user.has_perm("governance.change_actionitem"),
            "item_form": StaffActionItemForm() if can_add_item else None,
            "active_tab": "governance",
        },
    )


@staff_permission_required("governance.add_actionitem")
def action_item_create(request, meeting_id):
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if request.method == "POST":
        form = StaffActionItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.meeting = meeting
            item.save()
            messages.success(request, f"\"{item.description}\" was added.")
    return redirect("staff_meeting_detail", meeting_id=meeting.id)


@staff_permission_required("governance.change_actionitem")
def action_item_toggle(request, meeting_id, item_id):
    meeting = get_object_or_404(Meeting, id=meeting_id)
    item = get_object_or_404(ActionItem, id=item_id, meeting=meeting)
    if request.method == "POST":
        item.mark_done(not item.is_done)
    return redirect("staff_meeting_detail", meeting_id=meeting.id)
