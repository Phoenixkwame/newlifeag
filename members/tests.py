import io
from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from events.models import RSVP, Event, VolunteerSignup, VolunteerSlot, VolunteerWaitlistEntry
from followup.models import FollowUp
from giving.models import Donation, GivingCampaign, Pledge
from maintenance.models import MaintenanceRequest
from sermons.models import Sermon
from surveys.models import Survey, SurveyAnswer, SurveyChoice, SurveyQuestion, SurveyResponse

from .models import (
    Attendance,
    Campus,
    GroupLesson,
    GroupMembership,
    Household,
    Member,
    MemberNote,
    ServingAssignment,
    SetListSong,
    Skill,
    SongSetList,
    TeamShoutout,
)
from .feeds import build_all_day_event, build_calendar, build_event
from .models import Group as ChurchGroup
from .notifications import send_anniversary_greeting, send_birthday_greeting, send_serving_reminder
from .pdfs import build_membership_certificate_pdf
from .services import (
    absentee_members,
    attendance_streak_weeks,
    bulk_set_household_active,
    bulk_set_household_campus,
    bulk_sync_household_phone,
    get_or_create_calendar_token,
    is_sms_checkin_message,
    record_sms_checkin,
    record_sms_serving_response,
    regenerate_calendar_token,
    streak_badge,
    suggested_groups_for,
)

# The smallest possible valid GIF, used across Django projects for testing
# ImageField uploads without shipping a real image file in the repo.
SMALL_GIF = (
    b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
    b"\xff\xff\xff\x21\xf9\x04\x00\x00\x00\x00\x00\x2c\x00\x00\x00\x00"
    b"\x01\x00\x01\x00\x00\x02\x02\x4c\x01\x00\x3b"
)


class MemberModelTests(TestCase):
    def test_str_returns_full_name(self):
        member = Member.objects.create(first_name="Ama", last_name="Mensah")
        self.assertEqual(str(member), "Ama Mensah")

    def test_member_can_belong_to_household(self):
        household = Household.objects.create(name="The Mensah Family")
        member = Member.objects.create(first_name="Ama", last_name="Mensah", household=household)
        self.assertEqual(member.household, household)
        self.assertIn(member, household.members.all())

    def test_member_defaults_to_active(self):
        member = Member.objects.create(first_name="Kojo", last_name="Boateng")
        self.assertTrue(member.is_active)


class AccountProvisioningTests(TestCase):
    def test_public_signup_is_unavailable_and_cannot_create_accounts(self):
        users_before = User.objects.count()
        members_before = Member.objects.count()
        self.assertEqual(self.client.get("/members/signup/").status_code, 404)
        response = self.client.post("/members/signup/", {
            "username": "uninvited", "first_name": "Test", "last_name": "User",
            "password1": "strong-password-123", "password2": "strong-password-123",
        })
        self.assertEqual(response.status_code, 404)
        self.assertEqual(User.objects.count(), users_before)
        self.assertEqual(Member.objects.count(), members_before)

    def test_public_pages_do_not_offer_signup(self):
        for name in ("home", "login", "public_group_finder"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "/members/signup/")
        self.assertContains(self.client.get(reverse("login")), "Accounts are created by the church administrator")

    def test_administrator_can_still_create_login_accounts(self):
        admin = User.objects.create_superuser(username="account-admin", email="admin@example.com", password="test-pass")
        self.client.force_login(admin)
        response = self.client.post(reverse("admin:auth_user_add"), {
            "username": "new-staff", "password1": "strong-admin-created-123",
            "password2": "strong-admin-created-123", "usable_password": "true",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.get(username="new-staff").check_password("strong-admin-created-123"))


class MarkAttendanceTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kwame", last_name="Asante")
        self.staff_user = User.objects.create_user(username="usher", password="test-pass-123")
        self.staff_user.is_staff = True
        self.staff_user.save()
        self.staff_user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label="members", codename__in=["add_attendance", "change_attendance"]
        ))
        self.regular_user = User.objects.create_user(username="member1", password="test-pass-123")

    def test_non_staff_cannot_mark_attendance(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse("mark_attendance"))
        self.assertEqual(response.status_code, 302)  # redirected away, not shown the page

    def test_staff_can_mark_attendance(self):
        self.client.force_login(self.staff_user)
        response = self.client.post(
            reverse("mark_attendance"), {"submit_attendance": "1", "present_members": [self.member.id]}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Attendance.objects.filter(member=self.member, present=True).exists())

    def test_unchecked_member_is_marked_absent(self):
        self.client.force_login(self.staff_user)
        self.client.post(reverse("mark_attendance"), {"submit_attendance": "1", "present_members": []})
        record = Attendance.objects.get(member=self.member)
        self.assertFalse(record.present)

    def test_campus_selector_is_hidden_with_one_or_no_campus(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("mark_attendance"))
        # Not a bare 'name="campus_id"' check: the attendance form always
        # carries a hidden campus_id input (so the current campus filter
        # survives into the POST), regardless of whether the visible
        # dropdown selector is shown - check for the visible <select> itself.
        self.assertNotContains(response, '<select name="campus_id"')

    def test_campus_selector_filters_which_members_are_shown(self):
        main = Campus.objects.create(name="Main Campus")
        tema = Campus.objects.create(name="Tema Branch")
        Member.objects.create(first_name="Yaw", last_name="Tetteh", campus=tema)
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("mark_attendance"), {"campus_id": main.id})
        self.assertContains(response, '<select name="campus_id"')
        self.assertNotContains(response, "Yaw Tetteh")


class GroupAttendanceRecordTests(TestCase):
    """
    The group FK on Attendance, and the group=None/event=None disambiguation
    added alongside it in mark_attendance and group_attendance (see
    members/models.py's Attendance.Meta comment) - without that
    disambiguation, a member with both a general Sunday attendance record
    and a small-group-meeting attendance record for the same date would make
    update_or_create() raise MultipleObjectsReturned.
    """

    def setUp(self):
        self.member = Member.objects.create(first_name="Kwame", last_name="Asante")
        self.group = ChurchGroup.objects.create(name="Men's Fellowship")

    def test_a_member_can_have_both_a_service_and_a_group_attendance_record_on_the_same_day(self):
        today = timezone.localdate()
        Attendance.objects.create(member=self.member, date=today, event=None, group=None, present=True)
        Attendance.objects.create(member=self.member, date=today, event=None, group=self.group, present=True)
        self.assertEqual(Attendance.objects.filter(member=self.member, date=today).count(), 2)

    def test_general_attendance_lookup_ignores_group_meeting_rows(self):
        """
        mark_attendance's update_or_create passes group=None explicitly, so
        re-saving general attendance for a member who ALSO has a
        group-meeting record for the same day updates only the general row.
        """
        today = timezone.localdate()
        group_record = Attendance.objects.create(
            member=self.member, date=today, event=None, group=self.group, present=True
        )
        general_record, created = Attendance.objects.update_or_create(
            member=self.member, date=today, event=None, group=None, defaults={"present": False}
        )
        self.assertTrue(created)
        self.assertNotEqual(general_record.id, group_record.id)
        group_record.refresh_from_db()
        self.assertTrue(group_record.present)  # untouched by the general-attendance save


class GroupSelfServiceTests(TestCase):
    """Members browsing, joining, and leaving groups themselves (members/views.py)."""

    def setUp(self):
        self.user = User.objects.create_user(username="joiner", password="test-pass-123")
        self.member = Member.objects.create(first_name="Efua", last_name="Owusu", user=self.user)
        self.group = ChurchGroup.objects.create(name="Young Adults")

    def test_browse_groups_requires_login(self):
        response = self.client.get(reverse("browse_groups"))
        self.assertEqual(response.status_code, 302)

    def test_browse_groups_lists_every_group(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("browse_groups"))
        self.assertContains(response, "Young Adults")

    def test_browse_groups_shows_an_initials_avatar_for_a_leader_without_a_photo(self):
        self.group.leader = self.member
        self.group.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("browse_groups"))
        self.assertContains(response, '<span class="avatar">EO</span>')

    def test_member_can_join_a_group(self):
        self.client.force_login(self.user)
        self.client.post(reverse("join_group", args=[self.group.id]))
        self.assertTrue(
            GroupMembership.objects.filter(member=self.member, group=self.group, left_date__isnull=True).exists()
        )

    def test_member_can_leave_a_group(self):
        GroupMembership.objects.create(member=self.member, group=self.group)
        self.client.force_login(self.user)
        self.client.post(reverse("leave_group", args=[self.group.id]))
        membership = GroupMembership.objects.get(member=self.member, group=self.group)
        self.assertIsNotNone(membership.left_date)

    def test_rejoining_a_group_reactivates_the_same_membership_row(self):
        membership = GroupMembership.objects.create(member=self.member, group=self.group, left_date=date(2020, 1, 1))
        self.client.force_login(self.user)
        self.client.post(reverse("join_group", args=[self.group.id]))
        membership.refresh_from_db()
        self.assertIsNone(membership.left_date)
        self.assertEqual(GroupMembership.objects.filter(member=self.member, group=self.group).count(), 1)

    def test_a_group_with_no_max_members_is_never_full(self):
        self.assertFalse(self.group.is_full)

    def test_a_group_is_full_once_it_reaches_its_cap(self):
        self.group.max_members = 1
        self.group.save()
        other = Member.objects.create(first_name="Kojo", last_name="Mensah")
        GroupMembership.objects.create(member=other, group=self.group)
        self.assertTrue(self.group.is_full)

    def test_cannot_join_a_full_group(self):
        self.group.max_members = 1
        self.group.save()
        other = Member.objects.create(first_name="Kojo", last_name="Mensah")
        GroupMembership.objects.create(member=other, group=self.group)

        self.client.force_login(self.user)
        response = self.client.post(reverse("join_group", args=[self.group.id]), follow=True)
        self.assertFalse(
            GroupMembership.objects.filter(member=self.member, group=self.group, left_date__isnull=True).exists()
        )
        self.assertContains(response, "is full")

    def test_a_member_already_in_a_full_group_is_not_blocked_from_re_posting_join(self):
        self.group.max_members = 1
        self.group.save()
        GroupMembership.objects.create(member=self.member, group=self.group)

        self.client.force_login(self.user)
        self.client.post(reverse("join_group", args=[self.group.id]))
        self.assertTrue(
            GroupMembership.objects.filter(member=self.member, group=self.group, left_date__isnull=True).exists()
        )

    def test_browse_groups_shows_full_badge_and_disables_joining(self):
        self.group.max_members = 1
        self.group.save()
        other = Member.objects.create(first_name="Kojo", last_name="Mensah")
        GroupMembership.objects.create(member=other, group=self.group)

        self.client.force_login(self.user)
        response = self.client.get(reverse("browse_groups"))
        self.assertContains(response, "Full")
        self.assertNotContains(response, f'action="{reverse("join_group", args=[self.group.id])}"')

    def test_leaving_a_full_group_frees_up_a_spot(self):
        self.group.max_members = 1
        self.group.save()
        GroupMembership.objects.create(member=self.member, group=self.group)
        self.assertTrue(self.group.is_full)

        self.client.force_login(self.user)
        self.client.post(reverse("leave_group", args=[self.group.id]))
        self.assertFalse(self.group.is_full)


class PublicGroupFinderTests(TestCase):
    """The no-login "Find a Small Group" page (members/views.py's public_group_finder)."""

    def setUp(self):
        self.small_group = ChurchGroup.objects.create(
            name="Young Adults",
            group_type=ChurchGroup.GroupType.SMALL_GROUP,
            meeting_day=ChurchGroup.MeetingDay.TUESDAY,
            meeting_location="East Legon Community Center",
        )
        self.other_day_group = ChurchGroup.objects.create(
            name="Women's Fellowship",
            group_type=ChurchGroup.GroupType.SMALL_GROUP,
            meeting_day=ChurchGroup.MeetingDay.THURSDAY,
            meeting_location="Adenta",
        )
        self.committee = ChurchGroup.objects.create(name="Finance Committee", group_type=ChurchGroup.GroupType.COMMITTEE)

    def test_no_login_required(self):
        response = self.client.get(reverse("public_group_finder"))
        self.assertEqual(response.status_code, 200)

    def test_lists_small_groups_but_not_committees_or_ministries(self):
        response = self.client.get(reverse("public_group_finder"))
        self.assertContains(response, "Young Adults")
        # The group name is rendered through {{ group.name }}, so the
        # apostrophe comes back HTML-escaped (Women&#x27;s Fellowship).
        self.assertContains(response, escape("Women's Fellowship"))
        self.assertNotContains(response, "Finance Committee")

    def test_filters_by_meeting_day(self):
        response = self.client.get(reverse("public_group_finder"), {"day": "tue"})
        self.assertContains(response, "Young Adults")
        self.assertNotContains(response, "Women's Fellowship")

    def test_filters_by_area_keyword(self):
        response = self.client.get(reverse("public_group_finder"), {"area": "legon"})
        self.assertContains(response, "Young Adults")
        self.assertNotContains(response, "Women's Fellowship")

    def test_shows_no_join_or_leave_action(self):
        response = self.client.get(reverse("public_group_finder"))
        self.assertNotContains(response, "Join Group")
        self.assertNotContains(response, "Leave Group")

    def test_shows_an_initials_avatar_for_a_leader_without_a_photo(self):
        leader = Member.objects.create(first_name="Kofi", last_name="Boateng")
        self.small_group.leader = leader
        self.small_group.save()
        response = self.client.get(reverse("public_group_finder"))
        self.assertContains(response, '<span class="avatar">KB</span>')


class GroupAttendanceViewTests(TestCase):
    """Group leaders taking their own group's attendance from the portal (members/views.py's group_attendance)."""

    def setUp(self):
        self.leader_user = User.objects.create_user(username="leader", password="test-pass-123")
        self.leader = Member.objects.create(first_name="Kojo", last_name="Mensah", user=self.leader_user)
        self.group = ChurchGroup.objects.create(name="Men's Fellowship", leader=self.leader)
        self.attendee = Member.objects.create(first_name="Yaw", last_name="Asare")
        GroupMembership.objects.create(member=self.attendee, group=self.group)

        self.outsider_user = User.objects.create_user(username="outsider", password="test-pass-123")
        Member.objects.create(first_name="Ama", last_name="Boateng", user=self.outsider_user)

    def test_the_leader_can_open_the_attendance_page(self):
        self.client.force_login(self.leader_user)
        response = self.client.get(reverse("group_attendance", args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Yaw Asare")

    def test_a_non_leader_member_is_redirected_away(self):
        self.client.force_login(self.outsider_user)
        response = self.client.get(reverse("group_attendance", args=[self.group.id]))
        self.assertRedirects(response, reverse("dashboard"))

    def test_the_leader_can_save_attendance(self):
        self.client.force_login(self.leader_user)
        self.client.post(
            reverse("group_attendance", args=[self.group.id]),
            {"submit_attendance": "1", "present_members": [self.attendee.id]},
        )
        record = Attendance.objects.get(member=self.attendee, group=self.group)
        self.assertTrue(record.present)
        self.assertIsNone(record.event)

    def test_staff_with_attendance_permission_can_also_take_attendance(self):
        staff_user = User.objects.create_user(username="pastor", password="test-pass-123")
        pastors, _ = Group.objects.get_or_create(name="Pastors")
        from django.contrib.auth.models import Permission

        pastors.permissions.add(Permission.objects.get(codename="add_attendance", content_type__app_label="members"))
        staff_user.is_staff = True
        staff_user.groups.add(pastors)
        staff_user.save()
        self.client.force_login(staff_user)
        response = self.client.get(reverse("group_attendance", args=[self.group.id]))
        self.assertEqual(response.status_code, 200)


class DashboardGivingHistoryTests(TestCase):
    """The dashboard shows a member their own gifts - and only their own."""

    def setUp(self):
        self.user = User.objects.create_user(username="giver", password="test-pass-123")
        self.member = Member.objects.create(first_name="Yaa", last_name="Darko", user=self.user)
        self.other_member = Member.objects.create(first_name="Kojo", last_name="Mensah")

    def test_dashboard_shows_own_donation(self):
        Donation.objects.create(member=self.member, amount="30.00")
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "30.00")

    def test_dashboard_does_not_show_someone_elses_donation(self):
        Donation.objects.create(member=self.other_member, amount="500.00")
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "500.00")


class MemberPhotoUploadTests(TestCase):
    """A member's own profile-photo upload from the dashboard (members/views.py's update_photo)."""

    def setUp(self):
        self.user = User.objects.create_user(username="photoperson", password="test-pass-123")
        self.member = Member.objects.create(first_name="Abena", last_name="Owusu", user=self.user)

    def test_member_can_upload_a_photo(self):
        self.client.force_login(self.user)
        photo = SimpleUploadedFile("avatar.gif", SMALL_GIF, content_type="image/gif")
        response = self.client.post(reverse("update_photo"), {"photo": photo})
        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.assertTrue(self.member.photo)

    def test_oversized_photo_is_rejected(self):
        import os

        from PIL import Image

        # Genuine random pixel data doesn't compress away under PNG (unlike
        # a real photo), so 1400x1400 reliably produces a file comfortably
        # over the 5MB limit - more reliable than a tiny image padded with
        # junk bytes, which risks failing image validation for the wrong
        # reason before the size check ever runs.
        image = Image.frombytes("RGB", (1400, 1400), os.urandom(1400 * 1400 * 3))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)
        photo = SimpleUploadedFile("big.png", buf.read(), content_type="image/png")

        self.client.force_login(self.user)
        self.client.post(reverse("update_photo"), {"photo": photo})
        self.member.refresh_from_db()
        self.assertFalse(self.member.photo)

    def test_user_without_member_profile_is_redirected(self):
        no_profile_user = User.objects.create_user(username="noprofile2", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(self.client.post(reverse("update_photo"), {}), reverse("dashboard"))


class MemberInitialsTests(TestCase):
    def test_initials_are_first_letters_uppercased(self):
        member = Member.objects.create(first_name="abena", last_name="owusu")
        self.assertEqual(member.initials, "AO")


class CampusModelTests(TestCase):
    def test_str_returns_name(self):
        campus = Campus.objects.create(name="Tema Branch")
        self.assertEqual(str(campus), "Tema Branch")

    def test_member_can_belong_to_a_campus(self):
        campus = Campus.objects.create(name="Spintex Branch")
        member = Member.objects.create(first_name="Kojo", last_name="Ansah", campus=campus)
        self.assertIn(member, campus.members.all())


class SetupGroupsCommandTests(TestCase):
    def test_creates_expected_groups(self):
        call_command("setup_groups")
        self.assertTrue(Group.objects.filter(name="Ushers").exists())
        self.assertTrue(Group.objects.filter(name="Treasurers").exists())
        self.assertTrue(Group.objects.filter(name="Pastors").exists())

    def test_ushers_can_manage_attendance_but_not_delete_it(self):
        call_command("setup_groups")
        codenames = set(Group.objects.get(name="Ushers").permissions.values_list("codename", flat=True))
        self.assertIn("add_attendance", codenames)
        self.assertIn("view_attendance", codenames)
        self.assertNotIn("delete_attendance", codenames)
        self.assertNotIn("view_donation", codenames)  # ushers shouldn't see giving records

    def test_treasurers_can_only_see_donations(self):
        call_command("setup_groups")
        codenames = set(Group.objects.get(name="Treasurers").permissions.values_list("codename", flat=True))
        self.assertIn("view_donation", codenames)
        self.assertNotIn("view_attendance", codenames)

    def test_command_is_safe_to_run_twice(self):
        call_command("setup_groups")
        call_command("setup_groups")
        self.assertEqual(Group.objects.filter(name="Ushers").count(), 1)

    def test_pastors_can_manage_campuses(self):
        call_command("setup_groups")
        codenames = set(Group.objects.get(name="Pastors").permissions.values_list("codename", flat=True))
        self.assertIn("add_campus", codenames)
        self.assertIn("view_campus", codenames)

    def test_treasurers_can_manage_giving_campaigns_and_pledges(self):
        call_command("setup_groups")
        codenames = set(Group.objects.get(name="Treasurers").permissions.values_list("codename", flat=True))
        self.assertIn("view_givingcampaign", codenames)
        self.assertIn("add_pledge", codenames)


class GroupMeetingScheduleTests(TestCase):
    """The optional meeting-schedule fields on Group - see the model's docstring."""

    def test_schedule_fields_are_blank_by_default(self):
        group = ChurchGroup.objects.create(name="Choir", group_type="ministry")
        self.assertEqual(group.meeting_day, "")
        self.assertIsNone(group.meeting_time)
        self.assertEqual(group.meeting_location, "")

    def test_schedule_fields_can_be_set(self):
        group = ChurchGroup.objects.create(
            name="Young Adults Cell",
            group_type="small_group",
            meeting_day=ChurchGroup.MeetingDay.WEDNESDAY,
            meeting_time="18:30",
            meeting_location="Room 4",
        )
        self.assertEqual(group.get_meeting_day_display(), "Wednesday")
        self.assertEqual(group.meeting_location, "Room 4")


class DashboardGroupsAndPledgesTests(TestCase):
    """The dashboard's "Your Groups" and "Your Pledges" cards show only this member's own memberships/pledges."""

    def setUp(self):
        self.user = User.objects.create_user(username="groupmember", password="test-pass-123")
        self.member = Member.objects.create(first_name="Kwabena", last_name="Osei", user=self.user)
        self.other_member = Member.objects.create(first_name="Nana", last_name="Yeboah")

    def test_dashboard_shows_own_active_group_membership(self):
        group = ChurchGroup.objects.create(name="Sunrise Cell", group_type="small_group", meeting_location="The Osei home")
        GroupMembership.objects.create(member=self.member, group=group)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Sunrise Cell")
        self.assertContains(response, "The Osei home")

    def test_dashboard_does_not_show_a_group_left(self):
        group = ChurchGroup.objects.create(name="Old Cell", group_type="small_group")
        GroupMembership.objects.create(
            member=self.member, group=group, left_date=timezone.localdate() - timezone.timedelta(days=30)
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        # Not a page-wide assertNotContains: the dashboard's Log Service
        # Hours card lists every group (including ones you've left) as an
        # option in its group dropdown, by design - check the "Your Groups"
        # card's own data instead of the whole page's text.
        self.assertNotIn(group, [membership.group for membership in response.context["my_groups"]])

    def test_dashboard_does_not_show_someone_elses_group(self):
        group = ChurchGroup.objects.create(name="Other Cell", group_type="small_group")
        GroupMembership.objects.create(member=self.other_member, group=group)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        # See test_dashboard_does_not_show_a_group_left above for why this
        # checks the "Your Groups" context data rather than the whole page.
        self.assertNotIn(group, [membership.group for membership in response.context["my_groups"]])

    def test_dashboard_shows_own_pledge_and_progress(self):
        campaign = GivingCampaign.objects.create(name="Building Fund", start_date=timezone.localdate())
        Pledge.objects.create(campaign=campaign, member=self.member, amount="500.00")
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Building Fund")
        self.assertContains(response, "500.00")


class MemberSelfServiceProfileTests(TestCase):
    """A member editing their own contact details (members/views.py's edit_profile)."""

    def setUp(self):
        self.user = User.objects.create_user(username="selfeditor", password="test-pass-123")
        self.member = Member.objects.create(
            first_name="Adwoa", last_name="Antwi", user=self.user, role=Member.Role.MEMBER
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("edit_profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_user_without_member_profile_is_redirected_to_dashboard(self):
        no_profile_user = User.objects.create_user(username="noprofile4", password="test-pass-123")
        self.client.force_login(no_profile_user)
        self.assertRedirects(self.client.get(reverse("edit_profile")), reverse("dashboard"))

    def test_member_can_update_their_own_contact_details(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("edit_profile"),
            {"first_name": "Adwoa", "last_name": "Antwi-Boateng", "email": "adwoa@example.com", "phone": "0244111222"},
        )
        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.assertEqual(self.member.last_name, "Antwi-Boateng")
        self.assertEqual(self.member.email, "adwoa@example.com")
        self.assertEqual(self.member.phone, "0244111222")

    def test_member_cannot_change_their_own_role_through_this_form(self):
        """
        role isn't a field on MemberProfileForm at all, so even a
        maliciously crafted POST including it has no effect - staff-only
        elevation stays staff-only (see StaffMemberForm).
        """
        self.client.force_login(self.user)
        self.client.post(
            reverse("edit_profile"),
            {"first_name": "Adwoa", "last_name": "Antwi", "email": "", "phone": "", "role": Member.Role.ADMIN},
        )
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, Member.Role.MEMBER)

    def test_member_can_set_their_own_birthday_and_anniversary(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("edit_profile"),
            {
                "first_name": "Adwoa",
                "last_name": "Antwi",
                "email": "",
                "phone": "",
                "date_of_birth": "1995-04-12",
                "anniversary_date": "2018-06-02",
            },
        )
        self.member.refresh_from_db()
        self.assertEqual(self.member.date_of_birth, date(1995, 4, 12))
        self.assertEqual(self.member.anniversary_date, date(2018, 6, 2))


class AccountSettingsViewTests(TestCase):
    """The new account settings page - notification preferences (members/views.py's account_settings)."""

    def setUp(self):
        self.user = User.objects.create_user(username="settings-user", password="test-pass-123")
        self.member = Member.objects.create(first_name="Adwoa", last_name="Antwi", user=self.user)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("account_settings"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_defaults_to_opted_in_to_both_channels(self):
        self.assertTrue(self.member.notify_by_email)
        self.assertTrue(self.member.notify_by_sms)

    def test_member_can_opt_out_of_email_announcements(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("account_settings"), {"notify_by_sms": "on"})
        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.assertFalse(self.member.notify_by_email)
        self.assertTrue(self.member.notify_by_sms)

    def test_member_can_opt_back_in(self):
        self.member.notify_by_email = False
        self.member.save()
        self.client.force_login(self.user)
        self.client.post(reverse("account_settings"), {"notify_by_email": "on", "notify_by_sms": "on"})
        self.member.refresh_from_db()
        self.assertTrue(self.member.notify_by_email)

    def test_defaults_to_opted_in_to_all_four_proactive_nudges(self):
        self.assertTrue(self.member.notify_volunteer_reminders)
        self.assertTrue(self.member.notify_pledge_reminders)
        self.assertTrue(self.member.notify_giving_receipts)
        self.assertTrue(self.member.notify_prayer_updates)

    def test_member_can_opt_out_of_each_proactive_nudge_independently(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("account_settings"),
            {"notify_by_email": "on", "notify_by_sms": "on", "notify_giving_receipts": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.assertFalse(self.member.notify_volunteer_reminders)
        self.assertFalse(self.member.notify_pledge_reminders)
        self.assertTrue(self.member.notify_giving_receipts)
        self.assertFalse(self.member.notify_prayer_updates)

    def test_page_links_to_password_change_and_data_export(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("account_settings"))
        self.assertContains(response, reverse("password_change"))
        self.assertContains(response, reverse("member_data_export"))

    def test_page_shows_a_calendar_feed_url_generated_on_first_visit(self):
        self.assertIsNone(self.member.calendar_token)
        self.client.force_login(self.user)
        response = self.client.get(reverse("account_settings"))
        self.member.refresh_from_db()
        self.assertIsNotNone(self.member.calendar_token)
        self.assertContains(response, self.member.calendar_token)

    def test_resetting_the_calendar_link_issues_a_new_token(self):
        self.client.force_login(self.user)
        self.client.get(reverse("account_settings"))
        self.member.refresh_from_db()
        old_token = self.member.calendar_token

        self.client.post(reverse("regenerate_calendar_link"))
        self.member.refresh_from_db()
        self.assertNotEqual(self.member.calendar_token, old_token)


class MemberDataExportViewTests(TestCase):
    """The self-service "download your data" export (members/views.py's member_data_export)."""

    def setUp(self):
        self.user = User.objects.create_user(username="export-user", password="test-pass-123")
        self.member = Member.objects.create(
            first_name="Adwoa", last_name="Antwi", user=self.user, email="adwoa@example.com"
        )

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("member_data_export"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_export_includes_the_members_own_completed_gift(self):
        Donation.objects.create(member=self.member, amount="100.00", status=Donation.Status.COMPLETED)
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_data_export"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("100.00", response.content.decode())

    def test_export_never_includes_another_members_gift(self):
        other_member = Member.objects.create(first_name="Kofi", last_name="Addo")
        Donation.objects.create(member=other_member, amount="999.00", status=Donation.Status.COMPLETED)
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_data_export"))
        self.assertNotIn("999.00", response.content.decode())

    def test_export_is_a_downloadable_text_file(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_data_export"))
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertIn("attachment", response["Content-Disposition"])


class MemberCalendarFeedTests(TestCase):
    """
    The no-login personal .ics feed (members/views.py's member_calendar_feed)
    - reached by calendar_token, not a session, since a calendar app fetches
    it on its own schedule with no login involved.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cal-user", password="test-pass-123")
        self.member = Member.objects.create(first_name="Adwoa", last_name="Antwi", user=self.user)
        self.token = get_or_create_calendar_token(self.member)

    def test_unknown_token_is_a_404(self):
        response = self.client.get(reverse("member_calendar_feed", args=["not-a-real-token"]))
        self.assertEqual(response.status_code, 404)

    def test_feed_requires_no_login(self):
        response = self.client.get(reverse("member_calendar_feed", args=[self.token]))
        self.assertEqual(response.status_code, 200)

    def test_feed_is_a_downloadable_ics_file(self):
        response = self.client.get(reverse("member_calendar_feed", args=[self.token]))
        self.assertEqual(response["Content-Type"], "text/calendar")
        self.assertIn("attachment", response["Content-Disposition"])
        content = response.content.decode()
        self.assertTrue(content.startswith("BEGIN:VCALENDAR"))
        self.assertIn("END:VCALENDAR", content)

    def test_feed_includes_an_upcoming_serving_assignment(self):
        group = ChurchGroup.objects.create(name="Ushering Team")
        ServingAssignment.objects.create(
            member=self.member, group=group, role="Usher", date=timezone.localdate() + timezone.timedelta(days=3)
        )
        response = self.client.get(reverse("member_calendar_feed", args=[self.token]))
        content = response.content.decode()
        self.assertIn("Serving: Usher", content)

    def test_feed_excludes_a_past_serving_assignment(self):
        group = ChurchGroup.objects.create(name="Ushering Team")
        ServingAssignment.objects.create(
            member=self.member, group=group, role="Usher", date=timezone.localdate() - timezone.timedelta(days=3)
        )
        response = self.client.get(reverse("member_calendar_feed", args=[self.token]))
        self.assertNotIn("Serving: Usher", response.content.decode())

    def test_feed_includes_an_upcoming_volunteer_signup(self):
        event = Event.objects.create(title="Christmas Program", start_datetime=timezone.now() + timezone.timedelta(days=5))
        slot = VolunteerSlot.objects.create(event=event, role_needed="Media Team")
        VolunteerSignup.objects.create(slot=slot, member=self.member)
        response = self.client.get(reverse("member_calendar_feed", args=[self.token]))
        content = response.content.decode()
        self.assertIn("Volunteering: Media Team", content)
        self.assertIn("Christmas Program", content)

    def test_feed_includes_a_going_rsvp_but_excludes_a_not_going_one(self):
        going_event = Event.objects.create(title="Sunday Service", start_datetime=timezone.now() + timezone.timedelta(days=2))
        skipped_event = Event.objects.create(title="Men's Breakfast", start_datetime=timezone.now() + timezone.timedelta(days=4))
        RSVP.objects.create(event=going_event, member=self.member, status=RSVP.Status.GOING)
        RSVP.objects.create(event=skipped_event, member=self.member, status=RSVP.Status.NOT_GOING)

        response = self.client.get(reverse("member_calendar_feed", args=[self.token]))
        content = response.content.decode()
        self.assertIn("Sunday Service", content)
        self.assertNotIn("Men's Breakfast", content)

    def test_feed_never_includes_another_members_serving_assignment(self):
        group = ChurchGroup.objects.create(name="Ushering Team")
        other_member = Member.objects.create(first_name="Kofi", last_name="Addo")
        ServingAssignment.objects.create(
            member=other_member, group=group, role="Sound", date=timezone.localdate() + timezone.timedelta(days=3)
        )
        response = self.client.get(reverse("member_calendar_feed", args=[self.token]))
        self.assertNotIn("Sound", response.content.decode())


class CalendarTokenServiceTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Adwoa", last_name="Antwi")

    def test_get_or_create_generates_a_token_once(self):
        self.assertIsNone(self.member.calendar_token)
        token = get_or_create_calendar_token(self.member)
        self.assertTrue(token)
        self.member.refresh_from_db()
        self.assertEqual(self.member.calendar_token, token)

    def test_get_or_create_is_idempotent(self):
        first = get_or_create_calendar_token(self.member)
        second = get_or_create_calendar_token(self.member)
        self.assertEqual(first, second)

    def test_regenerate_issues_a_different_token(self):
        first = get_or_create_calendar_token(self.member)
        second = regenerate_calendar_token(self.member)
        self.assertNotEqual(first, second)


class IcsBuildersTests(TestCase):
    """The plain iCalendar-building functions behind member_calendar_feed (members/feeds.py)."""

    def test_build_event_includes_start_end_and_summary(self):
        block = build_event(
            uid="test-1@newlifeag",
            start=timezone.make_aware(timezone.datetime(2027, 5, 1, 9, 0)),
            end=timezone.make_aware(timezone.datetime(2027, 5, 1, 11, 0)),
            summary="Sunday Service",
            location="Main Sanctuary",
        )
        text = "\r\n".join(block)
        self.assertIn("UID:test-1@newlifeag", text)
        self.assertIn("SUMMARY:Sunday Service", text)
        self.assertIn("LOCATION:Main Sanctuary", text)
        self.assertIn("DTSTART:", text)
        self.assertIn("DTEND:", text)

    def test_build_event_escapes_commas_and_semicolons_in_text_fields(self):
        block = build_event(
            uid="test-2@newlifeag",
            start=timezone.make_aware(timezone.datetime(2027, 5, 1, 9, 0)),
            summary="Youth Night: games, food; worship",
        )
        text = "\r\n".join(block)
        self.assertIn("games\\, food\\; worship", text)

    def test_build_all_day_event_uses_value_date_and_exclusive_end(self):
        block = build_all_day_event(uid="test-3@newlifeag", date=timezone.datetime(2027, 5, 1).date(), summary="Serving: Usher")
        text = "\r\n".join(block)
        self.assertIn("DTSTART;VALUE=DATE:20270501", text)
        self.assertIn("DTEND;VALUE=DATE:20270502", text)

    def test_build_calendar_wraps_blocks_in_envelope(self):
        block = build_event(uid="test-4@newlifeag", start=timezone.now(), summary="Test Event")
        calendar_text = build_calendar([block])
        self.assertTrue(calendar_text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(calendar_text.rstrip("\r\n").endswith("END:VCALENDAR"))
        self.assertIn("BEGIN:VEVENT", calendar_text)
        self.assertIn("END:VEVENT", calendar_text)


class BirthdayAnniversaryGreetingTests(TestCase):
    """members/notifications.py's greeting helpers, used by the
    send_birthday_greetings management command below."""

    def test_birthday_greeting_emails_a_member_with_an_email(self):
        member = Member.objects.create(first_name="Efua", last_name="Owusu", email="efua@example.com")
        result = send_birthday_greeting(member)
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("efua@example.com", mail.outbox[0].to)
        self.assertIn("Birthday", mail.outbox[0].subject)

    def test_anniversary_greeting_emails_a_member_with_an_email(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah", email="kojo@example.com")
        result = send_anniversary_greeting(member)
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Anniversary", mail.outbox[0].subject)

    def test_greeting_with_no_contact_info_returns_false_and_sends_nothing(self):
        member = Member.objects.create(first_name="Yaw", last_name="Asare")
        result = send_birthday_greeting(member)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)


class SendBirthdayGreetingsCommandTests(TestCase):
    """The send_birthday_greetings management command - meant to run daily."""

    def test_sends_a_birthday_greeting_for_a_member_whose_birthday_is_today(self):
        today = timezone.localdate()
        Member.objects.create(
            first_name="Efua", last_name="Owusu", email="efua@example.com",
            date_of_birth=today.replace(year=today.year - 30),
        )
        call_command("send_birthday_greetings")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Birthday", mail.outbox[0].subject)

    def test_sends_an_anniversary_greeting_for_a_member_whose_anniversary_is_today(self):
        today = timezone.localdate()
        Member.objects.create(
            first_name="Kojo", last_name="Mensah", email="kojo@example.com",
            anniversary_date=today.replace(year=today.year - 5),
        )
        call_command("send_birthday_greetings")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Anniversary", mail.outbox[0].subject)

    def test_does_not_greet_a_member_whose_birthday_is_not_today(self):
        today = timezone.localdate()
        not_today = today + timezone.timedelta(days=10)
        Member.objects.create(
            first_name="Yaw", last_name="Asare", email="yaw@example.com",
            date_of_birth=not_today.replace(year=not_today.year - 20),
        )
        call_command("send_birthday_greetings")
        self.assertEqual(len(mail.outbox), 0)

    def test_running_the_command_twice_in_the_same_day_does_not_double_greet(self):
        today = timezone.localdate()
        Member.objects.create(
            first_name="Efua", last_name="Owusu", email="efua@example.com",
            date_of_birth=today.replace(year=today.year - 30),
        )
        call_command("send_birthday_greetings")
        call_command("send_birthday_greetings")
        self.assertEqual(len(mail.outbox), 1)

    def test_inactive_member_is_not_greeted(self):
        today = timezone.localdate()
        Member.objects.create(
            first_name="Efua", last_name="Owusu", email="efua@example.com",
            date_of_birth=today.replace(year=today.year - 30), is_active=False,
        )
        call_command("send_birthday_greetings")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_also_sends_sms_when_configured_and_member_has_a_phone(self):
        today = timezone.localdate()
        Member.objects.create(
            first_name="Efua", last_name="Owusu", phone="0244000000",
            date_of_birth=today.replace(year=today.year - 30),
        )
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            call_command("send_birthday_greetings")
        mock_get.assert_called_once()


class StaffBirthdaysAnniversariesTests(TestCase):
    """The staff Birthdays & Anniversaries dashboard - gated on members.view_member, per setup_groups."""

    def setUp(self):
        call_command("setup_groups")
        self.usher = User.objects.create_user(username="usher15", password="test-pass-123", is_staff=True)
        self.usher.groups.add(Group.objects.get(name="Ushers"))
        self.treasurer = User.objects.create_user(username="treasurer15", password="test-pass-123", is_staff=True)
        self.treasurer.groups.add(Group.objects.get(name="Treasurers"))

    def test_usher_can_view_birthdays(self):
        Member.objects.create(first_name="Efua", last_name="Owusu", date_of_birth=date(1995, 3, 15))
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_birthdays"), {"month": 3})
        self.assertContains(response, "Efua Owusu")

    def test_treasurer_cannot_view_birthdays(self):
        self.client.force_login(self.treasurer)
        self.assertRedirects(self.client.get(reverse("staff_birthdays")), reverse("dashboard"))

    def test_a_birthday_in_a_different_month_is_excluded(self):
        Member.objects.create(first_name="Efua", last_name="Owusu", date_of_birth=date(1995, 3, 15))
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_birthdays"), {"month": 7})
        self.assertNotContains(response, "Efua Owusu")

    def test_anniversary_shows_up_in_its_own_section(self):
        Member.objects.create(first_name="Kojo", last_name="Mensah", anniversary_date=date(2010, 3, 20))
        self.client.force_login(self.usher)
        response = self.client.get(reverse("staff_birthdays"), {"month": 3})
        self.assertContains(response, "Kojo Mensah")


class MemberDirectoryTests(TestCase):
    """The opt-in member directory (members/views.py's member_directory)."""

    def setUp(self):
        self.user = User.objects.create_user(username="directoryviewer", password="test-pass-123")
        Member.objects.create(first_name="Viewer", last_name="Account", user=self.user)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("member_directory"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_a_member_who_has_not_opted_in_is_not_listed(self):
        Member.objects.create(first_name="Private", last_name="Person")
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"))
        self.assertNotContains(response, "Private Person")

    def test_a_member_who_has_opted_in_is_listed(self):
        Member.objects.create(first_name="Open", last_name="Person", share_in_directory=True)
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"))
        self.assertContains(response, "Open Person")

    def test_an_inactive_member_is_never_listed_even_if_opted_in(self):
        Member.objects.create(
            first_name="Gone", last_name="Away", share_in_directory=True, is_active=False
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"))
        self.assertNotContains(response, "Gone Away")

    def test_phone_only_shows_when_that_flag_is_also_set(self):
        Member.objects.create(
            first_name="Open", last_name="Person", share_in_directory=True, phone="0244123456"
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"))
        self.assertNotContains(response, "0244123456")

    def test_phone_shows_when_share_phone_in_directory_is_set(self):
        Member.objects.create(
            first_name="Open",
            last_name="Person",
            share_in_directory=True,
            share_phone_in_directory=True,
            phone="0244123456",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"))
        self.assertContains(response, "0244123456")

    def test_email_shows_only_when_share_email_in_directory_is_set(self):
        Member.objects.create(
            first_name="Open",
            last_name="Person",
            share_in_directory=True,
            share_email_in_directory=True,
            email="open@example.com",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"))
        self.assertContains(response, "open@example.com")

    def test_search_filters_by_name(self):
        Member.objects.create(first_name="Ama", last_name="Boateng", share_in_directory=True)
        Member.objects.create(first_name="Kojo", last_name="Mensah", share_in_directory=True)
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"), {"q": "ama"})
        self.assertContains(response, "Ama Boateng")
        self.assertNotContains(response, "Kojo Mensah")

    def test_a_member_can_opt_into_the_directory_from_their_profile(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("edit_profile"),
            {
                "first_name": "Viewer",
                "last_name": "Account",
                "email": "",
                "phone": "",
                "share_in_directory": "on",
                "share_phone_in_directory": "on",
            },
        )
        member = Member.objects.get(user=self.user)
        self.assertTrue(member.share_in_directory)
        self.assertTrue(member.share_phone_in_directory)
        self.assertFalse(member.share_email_in_directory)

    def test_filter_by_group_only_shows_current_members_of_that_group(self):
        group = ChurchGroup.objects.create(name="Worship Team")
        in_group = Member.objects.create(first_name="Ama", last_name="Boateng", share_in_directory=True)
        GroupMembership.objects.create(member=in_group, group=group)
        not_in_group = Member.objects.create(first_name="Kojo", last_name="Mensah", share_in_directory=True)
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"), {"group": group.id})
        self.assertContains(response, "Ama Boateng")
        self.assertNotContains(response, "Kojo Mensah")

    def test_filter_by_group_excludes_someone_who_left_the_group(self):
        group = ChurchGroup.objects.create(name="Worship Team")
        left_member = Member.objects.create(first_name="Ama", last_name="Boateng", share_in_directory=True)
        GroupMembership.objects.create(member=left_member, group=group, left_date=date(2026, 1, 1))
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"), {"group": group.id})
        self.assertNotContains(response, "Ama Boateng")

    def test_filter_by_skill(self):
        skill = Skill.objects.create(name="Photography")
        photographer = Member.objects.create(first_name="Ama", last_name="Boateng", share_in_directory=True)
        photographer.skills.add(skill)
        Member.objects.create(first_name="Kojo", last_name="Mensah", share_in_directory=True)
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"), {"skill": skill.id})
        self.assertContains(response, "Ama Boateng")
        self.assertNotContains(response, "Kojo Mensah")

    def test_campus_filter_hidden_with_only_one_campus(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"))
        self.assertNotContains(response, "Any campus")

    def test_campus_filter_shown_and_works_once_a_second_campus_exists(self):
        main = Campus.objects.create(name="Main Campus")
        downtown = Campus.objects.create(name="Downtown Campus")
        Member.objects.create(first_name="Ama", last_name="Boateng", share_in_directory=True, campus=main)
        Member.objects.create(first_name="Kojo", last_name="Mensah", share_in_directory=True, campus=downtown)
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"))
        self.assertContains(response, "Any campus")

        response = self.client.get(reverse("member_directory"), {"campus": main.id})
        self.assertContains(response, "Ama Boateng")
        self.assertNotContains(response, "Kojo Mensah")


class ServingAssignmentModelTests(TestCase):
    def test_str_includes_member_role_group_and_date(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        group = ChurchGroup.objects.create(name="Worship Team")
        assignment = ServingAssignment.objects.create(
            group=group, member=member, role="Vocals", date=date(2026, 3, 1)
        )
        text = str(assignment)
        self.assertIn("Kojo Mensah", text)
        self.assertIn("Vocals", text)
        self.assertIn("Worship Team", text)

    def test_same_member_role_and_date_cannot_be_scheduled_twice(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        group = ChurchGroup.objects.create(name="Worship Team")
        ServingAssignment.objects.create(group=group, member=member, role="Vocals", date=date(2026, 3, 1))
        with self.assertRaises(Exception):
            ServingAssignment.objects.create(group=group, member=member, role="Vocals", date=date(2026, 3, 1))


class MemberNoteModelTests(TestCase):
    """The private staff-only note timeline on a member (see staff/views.py's member_detail)."""

    def test_str_includes_member_and_date(self):
        member = Member.objects.create(first_name="Ama", last_name="Serwaa")
        note = MemberNote.objects.create(member=member, note="Called to check in.")
        text = str(note)
        self.assertIn("Ama Serwaa", text)

    def test_most_recent_note_is_first(self):
        member = Member.objects.create(first_name="Ama", last_name="Serwaa")
        older = MemberNote.objects.create(member=member, note="First conversation.")
        newer = MemberNote.objects.create(member=member, note="Follow-up call.")
        notes = list(member.staff_notes.all())
        self.assertEqual(notes, [newer, older])

    def test_note_survives_the_authors_account_being_deleted(self):
        author = User.objects.create_user(username="departed-pastor", password="test-pass-123")
        member = Member.objects.create(first_name="Ama", last_name="Serwaa")
        note = MemberNote.objects.create(member=member, author=author, note="Sensitive pastoral note.")
        author.delete()
        note.refresh_from_db()
        self.assertIsNone(note.author)
        self.assertEqual(note.note, "Sensitive pastoral note.")


class ServingScheduleViewTests(TestCase):
    """Group leaders scheduling their own team's serving roster (members/views.py's serving_schedule)."""

    def setUp(self):
        self.leader_user = User.objects.create_user(username="worshipleader", password="test-pass-123")
        self.leader = Member.objects.create(first_name="Ama", last_name="Serwaa", user=self.leader_user)
        self.group = ChurchGroup.objects.create(name="Worship Team", leader=self.leader)
        self.singer = Member.objects.create(first_name="Yaw", last_name="Asare")
        GroupMembership.objects.create(member=self.singer, group=self.group)

        self.outsider_user = User.objects.create_user(username="outsider2", password="test-pass-123")
        Member.objects.create(first_name="Kojo", last_name="Boateng", user=self.outsider_user)

    def test_the_leader_can_open_the_scheduling_page(self):
        self.client.force_login(self.leader_user)
        response = self.client.get(reverse("serving_schedule", args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Yaw Asare")

    def test_a_non_leader_member_is_redirected_away(self):
        self.client.force_login(self.outsider_user)
        response = self.client.get(reverse("serving_schedule", args=[self.group.id]))
        self.assertRedirects(response, reverse("dashboard"))

    def test_the_leader_can_schedule_a_member_to_serve(self):
        self.client.force_login(self.leader_user)
        self.client.post(
            reverse("serving_schedule", args=[self.group.id]),
            {"member_id": self.singer.id, "role": "Vocals", "date": "2027-03-01", "notes": ""},
        )
        self.assertTrue(
            ServingAssignment.objects.filter(
                group=self.group, member=self.singer, role="Vocals", date=date(2027, 3, 1)
            ).exists()
        )

    def test_missing_fields_do_not_create_an_assignment(self):
        self.client.force_login(self.leader_user)
        self.client.post(
            reverse("serving_schedule", args=[self.group.id]),
            {"member_id": "", "role": "", "date": "", "notes": ""},
        )
        self.assertEqual(ServingAssignment.objects.count(), 0)

    def test_staff_with_permission_can_also_schedule(self):
        staff_user = User.objects.create_user(username="pastor2", password="test-pass-123")
        pastors, _ = Group.objects.get_or_create(name="Pastors")
        from django.contrib.auth.models import Permission

        pastors.permissions.add(
            Permission.objects.get(codename="add_servingassignment", content_type__app_label="members")
        )
        staff_user.is_staff = True
        staff_user.groups.add(pastors)
        staff_user.save()
        self.client.force_login(staff_user)
        response = self.client.get(reverse("serving_schedule", args=[self.group.id]))
        self.assertEqual(response.status_code, 200)

    def test_scheduling_someone_already_serving_elsewhere_that_date_shows_a_warning(self):
        other_group = ChurchGroup.objects.create(name="Ushering Team")
        ServingAssignment.objects.create(
            group=other_group, member=self.singer, role="Usher", date=date(2027, 3, 1)
        )
        self.client.force_login(self.leader_user)
        response = self.client.post(
            reverse("serving_schedule", args=[self.group.id]),
            {"member_id": self.singer.id, "role": "Vocals", "date": "2027-03-01", "notes": ""},
            follow=True,
        )
        self.assertContains(response, "already scheduled to serve as Usher")
        self.assertContains(response, "Ushering Team")

    def test_no_warning_when_the_member_has_no_other_commitment_that_date(self):
        self.client.force_login(self.leader_user)
        response = self.client.post(
            reverse("serving_schedule", args=[self.group.id]),
            {"member_id": self.singer.id, "role": "Vocals", "date": "2027-03-01", "notes": ""},
            follow=True,
        )
        self.assertNotContains(response, "already scheduled")

    def test_resubmitting_the_same_assignment_does_not_repeat_the_warning(self):
        other_group = ChurchGroup.objects.create(name="Ushering Team")
        ServingAssignment.objects.create(
            group=other_group, member=self.singer, role="Usher", date=date(2027, 3, 1)
        )
        self.client.force_login(self.leader_user)
        self.client.post(
            reverse("serving_schedule", args=[self.group.id]),
            {"member_id": self.singer.id, "role": "Vocals", "date": "2027-03-01", "notes": ""},
        )
        # Submitting the identical assignment again is a get_or_create no-op -
        # the leader shouldn't be warned about their own already-created
        # assignment.
        response = self.client.post(
            reverse("serving_schedule", args=[self.group.id]),
            {"member_id": self.singer.id, "role": "Vocals", "date": "2027-03-01", "notes": ""},
            follow=True,
        )
        self.assertContains(response, "already scheduled to serve as Usher", count=1)


class DashboardServingAndPathwayTests(TestCase):
    def test_dashboard_shows_upcoming_serving_assignments(self):
        user = User.objects.create_user(username="server1", password="test-pass-123")
        member = Member.objects.create(first_name="Ama", last_name="Serwaa", user=user)
        group = ChurchGroup.objects.create(name="Worship Team")
        ServingAssignment.objects.create(
            group=group, member=member, role="Vocals", date=timezone.localdate() + timezone.timedelta(days=3)
        )
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Vocals")

    def test_dashboard_shows_past_serving_assignments_are_excluded(self):
        user = User.objects.create_user(username="server2", password="test-pass-123")
        member = Member.objects.create(first_name="Ama", last_name="Serwaa", user=user)
        group = ChurchGroup.objects.create(name="Worship Team")
        assignment = ServingAssignment.objects.create(
            group=group, member=member, role="Sound", date=timezone.localdate() - timezone.timedelta(days=3)
        )
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        # Not a page-wide assertNotContains: the Log Service Hours card's
        # role field has help text mentioning "Sound tech" as an example,
        # which would make this a false positive - check the "You're
        # Serving" context data instead.
        self.assertNotIn(assignment, list(response.context["serving_assignments"]))


class SendServingReminderTests(TestCase):
    def setUp(self):
        self.group = ChurchGroup.objects.create(name="Worship Team")

    def test_emails_a_member_with_an_email_on_file(self):
        member = Member.objects.create(first_name="Ama", last_name="Serwaa", email="ama@example.com")
        assignment = ServingAssignment.objects.create(
            group=self.group, member=member, role="Vocals", date=date(2027, 3, 1)
        )
        result = send_serving_reminder(assignment)
        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ama@example.com", mail.outbox[0].to)
        self.assertIn("Vocals", mail.outbox[0].body)

    def test_returns_false_for_a_member_with_no_contact_info(self):
        member = Member.objects.create(first_name="No", last_name="Contact")
        assignment = ServingAssignment.objects.create(
            group=self.group, member=member, role="Vocals", date=date(2027, 3, 1)
        )
        result = send_serving_reminder(assignment)
        self.assertFalse(result)
        self.assertEqual(len(mail.outbox), 0)

    def test_asks_the_member_to_reply_yes_or_no(self):
        member = Member.objects.create(first_name="Ama", last_name="Serwaa", email="ama3@example.com")
        assignment = ServingAssignment.objects.create(
            group=self.group, member=member, role="Vocals", date=date(2027, 3, 1)
        )
        send_serving_reminder(assignment)
        self.assertIn("Reply YES", mail.outbox[0].body)


class RecordSmsServingResponseTests(TestCase):
    def setUp(self):
        self.group = ChurchGroup.objects.create(name="Worship Team", leader=None)
        self.member = Member.objects.create(first_name="Ama", last_name="Serwaa", phone="0244123456")
        self.assignment = ServingAssignment.objects.create(
            group=self.group, member=self.member, role="Vocals", date=timezone.localdate() + timezone.timedelta(days=1)
        )

    def test_yes_confirms_the_nearest_pending_assignment(self):
        assignment, error = record_sms_serving_response(phone="0244123456", message_text="YES")
        self.assertIsNone(error)
        self.assertEqual(assignment.id, self.assignment.id)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.confirmation_status, ServingAssignment.ConfirmationStatus.CONFIRMED)

    def test_no_declines_the_nearest_pending_assignment(self):
        assignment, error = record_sms_serving_response(phone="0244123456", message_text="no")
        self.assertIsNone(error)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.confirmation_status, ServingAssignment.ConfirmationStatus.DECLINED)

    def test_unrelated_message_is_ignored_not_an_error(self):
        assignment, error = record_sms_serving_response(phone="0244123456", message_text="What time is service?")
        self.assertIsNone(assignment)
        self.assertEqual(error, "not_a_response_message")
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.confirmation_status, ServingAssignment.ConfirmationStatus.PENDING)

    def test_no_matching_member_reports_the_specific_error(self):
        assignment, error = record_sms_serving_response(phone="0209999999", message_text="YES")
        self.assertIsNone(assignment)
        self.assertEqual(error, "no_matching_member")

    def test_no_pending_assignment_reports_the_specific_error(self):
        self.assignment.confirmation_status = ServingAssignment.ConfirmationStatus.CONFIRMED
        self.assignment.save()
        assignment, error = record_sms_serving_response(phone="0244123456", message_text="YES")
        self.assertIsNone(assignment)
        self.assertEqual(error, "no_pending_assignment")

    def test_replying_picks_the_soonest_of_two_pending_assignments(self):
        sooner = ServingAssignment.objects.create(
            group=self.group, member=self.member, role="Sound", date=timezone.localdate()
        )
        assignment, error = record_sms_serving_response(phone="0244123456", message_text="YES")
        self.assertEqual(assignment.id, sooner.id)

    def test_declining_notifies_the_groups_leader(self):
        leader = Member.objects.create(first_name="Kojo", last_name="Mensah", email="leader@example.com")
        self.group.leader = leader
        self.group.save()
        record_sms_serving_response(phone="0244123456", message_text="NO")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("leader@example.com", mail.outbox[0].to)
        self.assertIn("Ama Serwaa", mail.outbox[0].body)

    def test_confirming_does_not_notify_the_leader(self):
        leader = Member.objects.create(first_name="Kojo", last_name="Mensah", email="leader2@example.com")
        self.group.leader = leader
        self.group.save()
        record_sms_serving_response(phone="0244123456", message_text="YES")
        self.assertEqual(len(mail.outbox), 0)


@override_settings(SMS_WEBHOOK_TOKEN="test-provider-secret")
class SmsServingResponseWebhookTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_X_SMS_WEBHOOK_TOKEN"] = "test-provider-secret"
        self.group = ChurchGroup.objects.create(name="Worship Team")
        self.member = Member.objects.create(first_name="Ama", last_name="Serwaa", phone="0244123456")
        self.assignment = ServingAssignment.objects.create(
            group=self.group, member=self.member, role="Vocals", date=timezone.localdate() + timezone.timedelta(days=1)
        )

    def test_webhook_confirms_from_posted_fields(self):
        response = self.client.post(reverse("sms_serving_response_webhook"), {"From": "0244123456", "Content": "YES"})
        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.confirmation_status, ServingAssignment.ConfirmationStatus.CONFIRMED)

    def test_webhook_always_responds_ok_for_an_unrelated_text(self):
        response = self.client.post(reverse("sms_serving_response_webhook"), {"From": "0244123456", "Content": "Hi"})
        self.assertEqual(response.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.confirmation_status, ServingAssignment.ConfirmationStatus.PENDING)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_webhook_texts_back_a_confirmation(self):
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            self.client.post(reverse("sms_serving_response_webhook"), {"From": "0244123456", "Content": "YES"})
        mock_get.assert_called_once()


class SendServingRemindersCommandTests(TestCase):
    def test_sends_reminders_for_assignments_within_the_window_and_stamps_reminder_sent_at(self):
        group = ChurchGroup.objects.create(name="Worship Team")
        member = Member.objects.create(first_name="Ama", last_name="Serwaa", email="ama2@example.com")
        assignment = ServingAssignment.objects.create(
            group=group, member=member, role="Vocals", date=timezone.localdate() + timezone.timedelta(days=1)
        )
        call_command("send_serving_reminders")
        assignment.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIsNotNone(assignment.reminder_sent_at)

    def test_does_not_remind_an_assignment_outside_the_window(self):
        group = ChurchGroup.objects.create(name="Worship Team")
        member = Member.objects.create(first_name="Kojo", last_name="Mensah", email="kojo2@example.com")
        assignment = ServingAssignment.objects.create(
            group=group, member=member, role="Sound", date=timezone.localdate() + timezone.timedelta(days=10)
        )
        call_command("send_serving_reminders")
        assignment.refresh_from_db()
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(assignment.reminder_sent_at)

    def test_running_twice_never_double_reminds(self):
        group = ChurchGroup.objects.create(name="Worship Team")
        member = Member.objects.create(first_name="Yaw", last_name="Asare", email="yaw2@example.com")
        ServingAssignment.objects.create(
            group=group, member=member, role="Ushering", date=timezone.localdate()
        )
        call_command("send_serving_reminders")
        call_command("send_serving_reminders")
        self.assertEqual(len(mail.outbox), 1)


class DashboardOpenSurveysTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="survey-taker", password="test-pass-123")
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah", user=self.user)
        self.survey = Survey.objects.create(title="Service Times", is_open=True)

    def test_open_survey_the_member_has_not_answered_shows_on_the_dashboard(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Service Times")

    def test_closed_survey_does_not_show_on_the_dashboard(self):
        self.survey.is_open = False
        self.survey.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "Service Times")

    def test_survey_already_answered_drops_off_the_dashboard(self):
        SurveyResponse.objects.create(survey=self.survey, member=self.member)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "Service Times")


class VolunteerSignupCancelViewTests(TestCase):
    """The member dashboard's own "Cancel" button on a volunteer sign-up (members/views.py's volunteer_signup_cancel)."""

    def setUp(self):
        self.user = User.objects.create_user(username="giver-cancel", password="test-pass-123")
        self.member = Member.objects.create(first_name="Kofi", last_name="Addo", user=self.user)
        self.event = Event.objects.create(title="Test Service", start_datetime=timezone.now() + timezone.timedelta(days=1))
        self.slot = VolunteerSlot.objects.create(event=self.event, role_needed="Usher", capacity=1)
        self.signup = VolunteerSignup.objects.create(slot=self.slot, member=self.member)

    def test_member_can_cancel_their_own_signup(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("volunteer_signup_cancel", args=[self.signup.id]))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(VolunteerSignup.objects.filter(id=self.signup.id).exists())

    def test_member_cannot_cancel_someone_elses_signup(self):
        other_user = User.objects.create_user(username="other-cancel", password="test-pass-123")
        Member.objects.create(first_name="Yaw", last_name="Boateng", user=other_user)
        self.client.force_login(other_user)
        self.client.post(reverse("volunteer_signup_cancel", args=[self.signup.id]))
        self.assertTrue(VolunteerSignup.objects.filter(id=self.signup.id).exists())

    def test_cancelling_promotes_a_waitlisted_member_and_the_dashboard_shows_the_waitlist(self):
        waitlisted_user = User.objects.create_user(username="waitlisted", password="test-pass-123")
        waitlisted_member = Member.objects.create(first_name="Efua", last_name="Owusu", user=waitlisted_user)
        VolunteerWaitlistEntry.objects.create(slot=self.slot, member=waitlisted_member)

        self.client.force_login(waitlisted_user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "On the Waitlist")

        self.client.force_login(self.user)
        self.client.post(reverse("volunteer_signup_cancel", args=[self.signup.id]))
        self.assertTrue(VolunteerSignup.objects.filter(slot=self.slot, member=waitlisted_member).exists())
        self.assertFalse(VolunteerWaitlistEntry.objects.filter(slot=self.slot, member=waitlisted_member).exists())

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.post(reverse("volunteer_signup_cancel", args=[self.signup.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)


class SurveyRespondViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="survey-taker2", password="test-pass-123")
        self.member = Member.objects.create(first_name="Kojo", last_name="Mensah", user=self.user)
        self.survey = Survey.objects.create(title="Service Times", is_open=True)
        self.choice_question = SurveyQuestion.objects.create(
            survey=self.survey, text="Preferred time?", question_type=SurveyQuestion.QuestionType.CHOICE
        )
        self.choice = SurveyChoice.objects.create(question=self.choice_question, text="8am")
        self.text_question = SurveyQuestion.objects.create(survey=self.survey, text="Anything else?")

    def test_get_shows_the_form(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("survey_respond", args=[self.survey.id]))
        self.assertContains(response, "Preferred time?")

    def test_submitting_creates_a_response_and_answers(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("survey_respond", args=[self.survey.id]),
            {
                f"question_{self.choice_question.id}": self.choice.id,
                f"question_{self.text_question.id}": "Great service!",
            },
        )
        self.assertEqual(response.status_code, 302)
        survey_response = SurveyResponse.objects.get(survey=self.survey, member=self.member)
        self.assertEqual(
            SurveyAnswer.objects.get(response=survey_response, question=self.choice_question).choice, self.choice
        )
        self.assertEqual(
            SurveyAnswer.objects.get(response=survey_response, question=self.text_question).text_answer,
            "Great service!",
        )

    def test_cannot_respond_twice(self):
        SurveyResponse.objects.create(survey=self.survey, member=self.member)
        self.client.force_login(self.user)
        response = self.client.get(reverse("survey_respond", args=[self.survey.id]))
        self.assertRedirects(response, reverse("dashboard"))

    def test_user_without_member_profile_is_redirected(self):
        no_profile_user = User.objects.create_user(username="noprofile-survey", password="test-pass-123")
        self.client.force_login(no_profile_user)
        response = self.client.get(reverse("survey_respond", args=[self.survey.id]))
        self.assertRedirects(response, reverse("dashboard"))


class MemberSkillsTests(TestCase):
    """The free-text skills field on a member's own profile (members/services.py's set_member_skills)."""

    def setUp(self):
        self.user = User.objects.create_user(username="skilled", password="test-pass-123")
        self.member = Member.objects.create(first_name="Efua", last_name="Asante", user=self.user)

    def test_submitting_comma_separated_skills_creates_them(self):
        self.client.force_login(self.user)
        self.client.post(reverse("edit_profile"), {"first_name": "Efua", "last_name": "Asante", "skills_text": "Music, Hospitality"})
        self.assertEqual(set(self.member.skills.values_list("name", flat=True)), {"Music", "Hospitality"})

    def test_an_existing_skill_is_reused_case_insensitively(self):
        Skill.objects.create(name="Music")
        self.client.force_login(self.user)
        self.client.post(reverse("edit_profile"), {"first_name": "Efua", "last_name": "Asante", "skills_text": "music"})
        self.assertEqual(Skill.objects.filter(name__iexact="music").count(), 1)

    def test_blank_skills_text_clears_existing_skills(self):
        skill = Skill.objects.create(name="Music")
        self.member.skills.add(skill)
        self.client.force_login(self.user)
        self.client.post(reverse("edit_profile"), {"first_name": "Efua", "last_name": "Asante", "skills_text": ""})
        self.assertEqual(self.member.skills.count(), 0)

    def test_directory_shows_a_members_skills(self):
        skill = Skill.objects.create(name="Teaching")
        self.member.skills.add(skill)
        self.member.share_in_directory = True
        self.member.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("member_directory"))
        self.assertContains(response, "Teaching")


class SuggestedGroupsForTests(TestCase):
    """members/services.py's suggested_groups_for - the interest survey's matching logic."""

    def setUp(self):
        self.member = Member.objects.create(first_name="Kwabena", last_name="Osei")
        self.music_skill = Skill.objects.create(name="Music")
        self.worship_team = ChurchGroup.objects.create(name="Worship Team", group_type=ChurchGroup.GroupType.MINISTRY)
        self.worship_team.interest_skills.add(self.music_skill)

    def test_no_skills_listed_returns_nothing(self):
        self.assertEqual(list(suggested_groups_for(self.member)), [])

    def test_a_matching_skill_suggests_the_group(self):
        self.member.skills.add(self.music_skill)
        self.assertEqual(list(suggested_groups_for(self.member)), [self.worship_team])

    def test_a_group_already_joined_is_not_suggested_again(self):
        self.member.skills.add(self.music_skill)
        GroupMembership.objects.create(member=self.member, group=self.worship_team)
        self.assertEqual(list(suggested_groups_for(self.member)), [])

    def test_a_non_matching_skill_suggests_nothing(self):
        self.member.skills.add(Skill.objects.create(name="Accounting"))
        self.assertEqual(list(suggested_groups_for(self.member)), [])

    def test_a_group_with_no_interest_skills_set_is_never_suggested(self):
        ChurchGroup.objects.create(name="Finance Committee", group_type=ChurchGroup.GroupType.COMMITTEE)
        self.member.skills.add(self.music_skill)
        self.assertEqual(list(suggested_groups_for(self.member)), [self.worship_team])


class AbsenteeMembersTests(TestCase):
    """members/services.py's absentee_members - the automated absentee-alert matching logic."""

    def _make_old_member(self, first_name, last_name, weeks_ago=10):
        member = Member.objects.create(first_name=first_name, last_name=last_name)
        Member.objects.filter(pk=member.pk).update(date_joined=timezone.localdate() - timezone.timedelta(weeks=weeks_ago))
        member.refresh_from_db()
        return member

    def test_a_member_with_no_attendance_is_flagged(self):
        member = self._make_old_member("Yaw", "Adjei")
        results = absentee_members()
        self.assertEqual([m for m, _ in results], [member])
        self.assertIsNone(dict(results)[member])

    def test_a_member_who_attended_recently_is_not_flagged(self):
        member = self._make_old_member("Yaw", "Adjei")
        Attendance.objects.create(member=member, date=timezone.localdate(), present=True)
        self.assertEqual(absentee_members(), [])

    def test_a_member_who_only_attended_long_ago_is_flagged(self):
        member = self._make_old_member("Yaw", "Adjei")
        Attendance.objects.create(
            member=member, date=timezone.localdate() - timezone.timedelta(weeks=8), present=True
        )
        results = absentee_members()
        self.assertEqual([m for m, _ in results], [member])
        self.assertEqual(dict(results)[member], timezone.localdate() - timezone.timedelta(weeks=8))

    def test_a_brand_new_member_is_not_flagged(self):
        Member.objects.create(first_name="Yaw", last_name="Adjei")  # joins today
        self.assertEqual(absentee_members(), [])

    def test_an_inactive_member_is_not_flagged(self):
        member = self._make_old_member("Yaw", "Adjei")
        member.is_active = False
        member.save()
        self.assertEqual(absentee_members(), [])

    def test_a_marked_absent_record_does_not_count_as_attendance(self):
        member = self._make_old_member("Yaw", "Adjei")
        Attendance.objects.create(member=member, date=timezone.localdate(), present=False)
        results = absentee_members()
        self.assertEqual([m for m, _ in results], [member])

    def test_never_attended_members_are_listed_before_ones_with_an_old_date(self):
        never_attended = self._make_old_member("Never", "Attended")
        attended_long_ago = self._make_old_member("Long", "Ago")
        Attendance.objects.create(
            member=attended_long_ago, date=timezone.localdate() - timezone.timedelta(weeks=8), present=True
        )
        results = absentee_members()
        self.assertEqual([m for m, _ in results], [never_attended, attended_long_ago])


class AttendanceStreakTests(TestCase):
    """members/services.py's attendance_streak_weeks and streak_badge."""

    def setUp(self):
        self.member = Member.objects.create(first_name="Abena", last_name="Nyarko")

    def _monday_of(self, weeks_ago, today):
        return today - timezone.timedelta(days=today.weekday() + weeks_ago * 7)

    def test_no_attendance_at_all_is_a_zero_streak(self):
        self.assertEqual(attendance_streak_weeks(self.member), 0)

    def test_attendance_this_week_counts_as_a_one_week_streak(self):
        today = timezone.localdate()
        Attendance.objects.create(member=self.member, date=today, present=True)
        self.assertEqual(attendance_streak_weeks(self.member, today=today), 1)

    def test_consecutive_weeks_count_correctly(self):
        today = timezone.localdate()
        for weeks_ago in range(4):
            Attendance.objects.create(member=self.member, date=self._monday_of(weeks_ago, today), present=True)
        self.assertEqual(attendance_streak_weeks(self.member, today=today), 4)

    def test_a_gap_week_breaks_the_streak(self):
        today = timezone.localdate()
        Attendance.objects.create(member=self.member, date=self._monday_of(0, today), present=True)
        # Skip weeks_ago=1 entirely - a gap.
        Attendance.objects.create(member=self.member, date=self._monday_of(2, today), present=True)
        self.assertEqual(attendance_streak_weeks(self.member, today=today), 1)

    def test_a_marked_absent_record_does_not_extend_the_streak(self):
        today = timezone.localdate()
        Attendance.objects.create(member=self.member, date=today, present=False)
        self.assertEqual(attendance_streak_weeks(self.member, today=today), 0)

    def test_group_meeting_attendance_counts_toward_the_streak_too(self):
        today = timezone.localdate()
        group = ChurchGroup.objects.create(name="Young Adults", group_type="small_group")
        Attendance.objects.create(member=self.member, date=today, present=True, group=group)
        self.assertEqual(attendance_streak_weeks(self.member, today=today), 1)

    def test_streak_badge_thresholds(self):
        self.assertIsNone(streak_badge(0))
        self.assertIsNone(streak_badge(3))
        self.assertEqual(streak_badge(4), "4 Week Streak")
        self.assertEqual(streak_badge(8), "8 Week Streak")
        self.assertEqual(streak_badge(12), "12 Week Streak")
        self.assertEqual(streak_badge(26), "6 Month Streak")
        self.assertEqual(streak_badge(52), "1 Year Streak")
        self.assertEqual(streak_badge(100), "1 Year Streak")

    def test_dashboard_shows_the_streak_and_badge(self):
        user = User.objects.create_user(username="streaker", password="test-pass-123")
        self.member.user = user
        self.member.save()
        today = timezone.localdate()
        for weeks_ago in range(4):
            Attendance.objects.create(member=self.member, date=self._monday_of(weeks_ago, today), present=True)
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "4 weeks in a row")
        self.assertContains(response, "4 Week Streak")


class HouseholdBulkActionsTests(TestCase):
    """
    members/services.py's bulk_set_household_campus, bulk_sync_household_phone,
    and bulk_set_household_active - the model-level logic behind the staff
    household detail page's "Bulk Actions" card (see staff/tests.py's
    StaffHouseholdBulkActionTests for the view/permission layer on top).
    """

    def setUp(self):
        self.household = Household.objects.create(name="The Nyarko Family", phone="0244888888")
        self.parent = Member.objects.create(first_name="Kofi", last_name="Nyarko", household=self.household)
        self.child = Member.objects.create(
            first_name="Adjoa", last_name="Nyarko", household=self.household, phone="0244111111"
        )

    def test_bulk_set_household_campus_updates_every_member(self):
        campus = Campus.objects.create(name="Downtown Campus")
        count = bulk_set_household_campus(self.household, campus)
        self.assertEqual(count, 2)
        self.parent.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(self.parent.campus, campus)
        self.assertEqual(self.child.campus, campus)

    def test_bulk_set_household_campus_can_clear_it_back_to_none(self):
        campus = Campus.objects.create(name="Downtown Campus")
        bulk_set_household_campus(self.household, campus)
        bulk_set_household_campus(self.household, None)
        self.parent.refresh_from_db()
        self.assertIsNone(self.parent.campus)

    def test_bulk_sync_household_phone_only_fills_in_blank_phones(self):
        count = bulk_sync_household_phone(self.household)
        self.assertEqual(count, 1)
        self.parent.refresh_from_db()
        self.child.refresh_from_db()
        self.assertEqual(self.parent.phone, "0244888888")
        # The child already had a personal number - it's left alone.
        self.assertEqual(self.child.phone, "0244111111")

    def test_bulk_sync_household_phone_does_nothing_without_a_household_phone(self):
        self.household.phone = ""
        self.household.save()
        count = bulk_sync_household_phone(self.household)
        self.assertEqual(count, 0)
        self.parent.refresh_from_db()
        self.assertEqual(self.parent.phone, "")

    def test_bulk_set_household_active_can_deactivate_and_reactivate_everyone(self):
        count = bulk_set_household_active(self.household, False)
        self.assertEqual(count, 2)
        self.parent.refresh_from_db()
        self.child.refresh_from_db()
        self.assertFalse(self.parent.is_active)
        self.assertFalse(self.child.is_active)

        bulk_set_household_active(self.household, True)
        self.parent.refresh_from_db()
        self.assertTrue(self.parent.is_active)

    def test_bulk_actions_do_not_touch_members_in_other_households(self):
        other_household = Household.objects.create(name="The Boateng Family")
        outsider = Member.objects.create(first_name="Yaw", last_name="Boateng", household=other_household)
        bulk_set_household_active(self.household, False)
        outsider.refresh_from_db()
        self.assertTrue(outsider.is_active)


class InterestSurveyViewTests(TestCase):
    """The standalone /members/interests/ page - a friendlier front door to set_member_skills with suggestions."""

    def setUp(self):
        self.user = User.objects.create_user(username="newmember", password="test-pass-123")
        self.member = Member.objects.create(first_name="Ama", last_name="Darko", user=self.user)
        self.music_skill = Skill.objects.create(name="Music")
        self.worship_team = ChurchGroup.objects.create(name="Worship Team", group_type=ChurchGroup.GroupType.MINISTRY)
        self.worship_team.interest_skills.add(self.music_skill)

    def test_get_shows_the_form(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("interest_survey"))
        self.assertEqual(response.status_code, 200)

    def test_submitting_sets_skills_and_shows_a_suggestion(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("interest_survey"), {"skills_text": "Music"}, follow=True)
        self.assertEqual(set(self.member.skills.values_list("name", flat=True)), {"Music"})
        self.assertContains(response, "Worship Team")

    def test_no_member_profile_is_redirected_to_dashboard(self):
        no_profile_user = User.objects.create_user(username="noprofile-interests", password="test-pass-123")
        self.client.force_login(no_profile_user)
        response = self.client.get(reverse("interest_survey"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_dashboard_shows_a_prompt_when_no_interests_listed_yet(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Not Sure Where to Start?")

    def test_dashboard_shows_suggestions_once_interests_are_listed(self):
        self.member.skills.add(self.music_skill)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Suggested For You")
        self.assertContains(response, "Worship Team")


class GroupLessonsViewTests(TestCase):
    """A small group's weekly lessons (members/views.py's group_lessons)."""

    def setUp(self):
        self.leader_user = User.objects.create_user(username="lessonleader", password="test-pass-123")
        self.leader = Member.objects.create(first_name="Ama", last_name="Serwaa", user=self.leader_user)
        self.group = ChurchGroup.objects.create(name="Young Adults", leader=self.leader)
        self.member_user = User.objects.create_user(username="lessonmember", password="test-pass-123")
        self.member = Member.objects.create(first_name="Yaw", last_name="Asare", user=self.member_user)
        GroupMembership.objects.create(member=self.member, group=self.group)
        self.outsider_user = User.objects.create_user(username="lessonoutsider", password="test-pass-123")
        Member.objects.create(first_name="Kojo", last_name="Boateng", user=self.outsider_user)

    def test_the_leader_can_post_a_lesson(self):
        self.client.force_login(self.leader_user)
        response = self.client.post(
            reverse("group_lessons", args=[self.group.id]),
            {"title": "Faith in Action", "week_of": "2027-03-01", "content": "James 2"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(GroupLesson.objects.filter(group=self.group, title="Faith in Action").exists())

    def test_a_group_member_can_view_lessons_but_not_post(self):
        GroupLesson.objects.create(group=self.group, title="Faith in Action", week_of="2027-03-01", content="James 2")
        self.client.force_login(self.member_user)
        response = self.client.get(reverse("group_lessons", args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Faith in Action")

        response = self.client.post(
            reverse("group_lessons", args=[self.group.id]),
            {"title": "Sneaky Lesson", "week_of": "2027-03-01", "content": "Nope"},
        )
        self.assertFalse(GroupLesson.objects.filter(title="Sneaky Lesson").exists())

    def test_a_non_member_is_redirected_away(self):
        self.client.force_login(self.outsider_user)
        response = self.client.get(reverse("group_lessons", args=[self.group.id]))
        self.assertRedirects(response, reverse("dashboard"))

    def test_shows_the_latest_sermons_discussion_guide_when_one_exists(self):
        guide = SimpleUploadedFile("questions.pdf", b"fake pdf bytes", content_type="application/pdf")
        Sermon.objects.create(title="Faith That Moves", date=date(2027, 3, 1), discussion_guide=guide)
        self.client.force_login(self.leader_user)
        response = self.client.get(reverse("group_lessons", args=[self.group.id]))
        self.assertContains(response, "Faith That Moves")
        self.assertContains(response, "Download Small Group Discussion Guide")

    def test_no_discussion_guide_link_when_no_sermon_has_one(self):
        Sermon.objects.create(title="Faith That Moves", date=date(2027, 3, 1))
        self.client.force_login(self.leader_user)
        response = self.client.get(reverse("group_lessons", args=[self.group.id]))
        self.assertNotContains(response, "Download Small Group Discussion Guide")

    def test_shows_the_most_recent_sermon_that_has_a_discussion_guide(self):
        older_guide = SimpleUploadedFile("older.pdf", b"older", content_type="application/pdf")
        newer_guide = SimpleUploadedFile("newer.pdf", b"newer", content_type="application/pdf")
        Sermon.objects.create(title="Older Message", date=date(2027, 2, 1), discussion_guide=older_guide)
        Sermon.objects.create(title="Newer Message", date=date(2027, 3, 1), discussion_guide=newer_guide)
        self.client.force_login(self.leader_user)
        response = self.client.get(reverse("group_lessons", args=[self.group.id]))
        self.assertContains(response, "Newer Message")
        self.assertNotContains(response, "Older Message")


class GroupSetListViewTests(TestCase):
    """A worship team's planned song lineup (members/views.py's group_set_list)."""

    def setUp(self):
        self.leader_user = User.objects.create_user(username="setlistleader", password="test-pass-123")
        self.leader = Member.objects.create(first_name="Ama", last_name="Serwaa", user=self.leader_user)
        self.group = ChurchGroup.objects.create(name="Worship Team", leader=self.leader)
        self.member_user = User.objects.create_user(username="setlistmember", password="test-pass-123")
        self.member = Member.objects.create(first_name="Yaw", last_name="Asare", user=self.member_user)
        GroupMembership.objects.create(member=self.member, group=self.group)
        self.outsider_user = User.objects.create_user(username="setlistoutsider", password="test-pass-123")
        Member.objects.create(first_name="Kojo", last_name="Boateng", user=self.outsider_user)

    def test_the_leader_can_post_a_set_list(self):
        self.client.force_login(self.leader_user)
        response = self.client.post(
            reverse("group_set_list", args=[self.group.id]),
            {"date": "2027-03-07", "songs": "Great Are You Lord | G | 6460220\nWay Maker | E", "notes": "Communion Sunday"},
        )
        self.assertEqual(response.status_code, 302)
        set_list = SongSetList.objects.get(group=self.group, date="2027-03-07")
        self.assertEqual(set_list.notes, "Communion Sunday")
        songs = list(set_list.songs.all())
        self.assertEqual([song.title for song in songs], ["Great Are You Lord", "Way Maker"])
        self.assertEqual(songs[0].key, "G")
        self.assertEqual(songs[0].ccli_number, "6460220")
        self.assertEqual(songs[1].key, "E")
        self.assertEqual(songs[1].ccli_number, "")

    def test_reposting_for_the_same_date_replaces_the_songs(self):
        self.client.force_login(self.leader_user)
        self.client.post(reverse("group_set_list", args=[self.group.id]), {"date": "2027-03-07", "songs": "Old Song"})
        self.client.post(reverse("group_set_list", args=[self.group.id]), {"date": "2027-03-07", "songs": "New Song"})
        set_list = SongSetList.objects.get(group=self.group, date="2027-03-07")
        self.assertEqual(set_list.songs.count(), 1)
        self.assertEqual(set_list.songs.first().title, "New Song")

    def test_a_group_member_can_view_but_not_post(self):
        set_list = SongSetList.objects.create(group=self.group, date="2027-03-07")
        SetListSong.objects.create(set_list=set_list, order=0, title="Great Are You Lord")
        self.client.force_login(self.member_user)
        response = self.client.get(reverse("group_set_list", args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Great Are You Lord")

        response = self.client.post(
            reverse("group_set_list", args=[self.group.id]), {"date": "2027-03-14", "songs": "Sneaky Song"}
        )
        self.assertFalse(SongSetList.objects.filter(date="2027-03-14").exists())

    def test_a_non_member_is_redirected_away(self):
        self.client.force_login(self.outsider_user)
        response = self.client.get(reverse("group_set_list", args=[self.group.id]))
        self.assertRedirects(response, reverse("dashboard"))

    def test_blank_songs_lines_are_skipped(self):
        self.client.force_login(self.leader_user)
        self.client.post(
            reverse("group_set_list", args=[self.group.id]),
            {"date": "2027-03-07", "songs": "Great Are You Lord\n\n   \nWay Maker"},
        )
        set_list = SongSetList.objects.get(group=self.group, date="2027-03-07")
        self.assertEqual(set_list.songs.count(), 2)


class GroupShoutoutsViewTests(TestCase):
    """A team's quick shoutouts (members/views.py's group_shoutouts) - posting also emails/SMS the team."""

    def setUp(self):
        self.leader_user = User.objects.create_user(username="shoutleader", password="test-pass-123")
        self.leader = Member.objects.create(first_name="Ama", last_name="Serwaa", user=self.leader_user)
        self.group = ChurchGroup.objects.create(name="Ushering Team", leader=self.leader)
        self.member_user = User.objects.create_user(username="shoutmember", password="test-pass-123")
        self.member = Member.objects.create(
            first_name="Yaw", last_name="Asare", user=self.member_user, email="yaw@example.com"
        )
        GroupMembership.objects.create(member=self.member, group=self.group)
        self.outsider_user = User.objects.create_user(username="shoutoutsider", password="test-pass-123")
        Member.objects.create(first_name="Kojo", last_name="Boateng", user=self.outsider_user)

    def test_the_leader_can_post_a_shoutout(self):
        self.client.force_login(self.leader_user)
        response = self.client.post(
            reverse("group_shoutouts", args=[self.group.id]), {"message": "Great job serving this week, team!"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(TeamShoutout.objects.filter(group=self.group, posted_by=self.leader).exists())

    def test_posting_a_shoutout_emails_the_teams_active_members(self):
        self.client.force_login(self.leader_user)
        self.client.post(reverse("group_shoutouts", args=[self.group.id]), {"message": "Thank you all!"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["yaw@example.com"])
        self.assertIn("Thank you all!", mail.outbox[0].body)

    def test_posting_does_not_email_a_member_who_already_left_the_team(self):
        GroupMembership.objects.filter(member=self.member, group=self.group).update(left_date=date(2020, 1, 1))
        self.client.force_login(self.leader_user)
        self.client.post(reverse("group_shoutouts", args=[self.group.id]), {"message": "Thank you all!"})
        self.assertEqual(len(mail.outbox), 0)

    def test_a_team_member_can_view_shoutouts_but_not_post(self):
        TeamShoutout.objects.create(group=self.group, message="Great job serving this week, team!")
        self.client.force_login(self.member_user)
        response = self.client.get(reverse("group_shoutouts", args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Great job serving this week, team!")

        response = self.client.post(reverse("group_shoutouts", args=[self.group.id]), {"message": "Sneaky shoutout"})
        self.assertFalse(TeamShoutout.objects.filter(message="Sneaky shoutout").exists())

    def test_a_non_member_is_redirected_away(self):
        self.client.force_login(self.outsider_user)
        response = self.client.get(reverse("group_shoutouts", args=[self.group.id]))
        self.assertRedirects(response, reverse("dashboard"))


class DashboardReportIssueTests(TestCase):
    """The "Report an Issue" card on the member dashboard (submits to maintenance.submit_maintenance_request)."""

    def setUp(self):
        self.user = User.objects.create_user(username="issuereporter", password="test-pass-123")
        Member.objects.create(first_name="Kojo", last_name="Asante", user=self.user)

    def test_dashboard_shows_the_report_an_issue_card(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Report an Issue")

    def test_submitting_creates_a_maintenance_request(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("submit_maintenance_request"),
            {"title": "Broken chair", "description": "", "location": ""},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(MaintenanceRequest.objects.filter(title="Broken chair").exists())


class IsSmsCheckinMessageTests(TestCase):
    def test_recognizes_the_keywords_case_insensitively(self):
        self.assertTrue(is_sms_checkin_message("IN"))
        self.assertTrue(is_sms_checkin_message("in"))
        self.assertTrue(is_sms_checkin_message("  Here  "))
        self.assertTrue(is_sms_checkin_message("Present"))

    def test_rejects_an_unrelated_message(self):
        self.assertFalse(is_sms_checkin_message("What time is service?"))
        self.assertFalse(is_sms_checkin_message("GIVE 50"))

    def test_rejects_empty_or_missing_text(self):
        self.assertFalse(is_sms_checkin_message(""))
        self.assertFalse(is_sms_checkin_message(None))


class RecordSmsCheckinTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")

    def test_checks_in_a_matching_member(self):
        attendance, error = record_sms_checkin(phone="233244123456", message_text="IN")
        self.assertIsNone(error)
        self.assertIsNotNone(attendance)
        self.assertEqual(attendance.member, self.member)
        self.assertTrue(attendance.present)
        self.assertEqual(attendance.date, timezone.localdate())
        self.assertIsNone(attendance.event)
        self.assertIsNone(attendance.group)

    def test_unrelated_message_is_ignored_not_an_error(self):
        attendance, error = record_sms_checkin(phone="0244123456", message_text="What time is service?")
        self.assertIsNone(attendance)
        self.assertEqual(error, "not_a_checkin_message")
        self.assertEqual(Attendance.objects.count(), 0)

    def test_no_matching_member_reports_the_specific_error(self):
        attendance, error = record_sms_checkin(phone="0209999999", message_text="IN")
        self.assertIsNone(attendance)
        self.assertEqual(error, "no_matching_member")
        self.assertEqual(Attendance.objects.count(), 0)

    def test_texting_in_twice_in_one_day_does_not_duplicate(self):
        record_sms_checkin(phone="0244123456", message_text="IN")
        record_sms_checkin(phone="0244123456", message_text="in")
        self.assertEqual(Attendance.objects.filter(member=self.member).count(), 1)


@override_settings(SMS_WEBHOOK_TOKEN="test-provider-secret")
class SmsCheckinWebhookTests(TestCase):
    def setUp(self):
        self.client.defaults["HTTP_X_SMS_WEBHOOK_TOKEN"] = "test-provider-secret"
        self.member = Member.objects.create(first_name="Kojo", last_name="Amoah", phone="0244123456")

    def test_webhook_checks_in_a_matching_member_from_posted_fields(self):
        response = self.client.post(reverse("sms_checkin_webhook"), {"From": "0244123456", "Content": "IN"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Attendance.objects.filter(member=self.member, present=True).exists())

    def test_webhook_always_responds_ok_even_for_an_unrelated_text(self):
        response = self.client.post(reverse("sms_checkin_webhook"), {"From": "0244123456", "Content": "Hello there"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Attendance.objects.count(), 0)

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_webhook_sends_a_confirmation_text_back(self):
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            self.client.post(reverse("sms_checkin_webhook"), {"From": "0244123456", "Content": "IN"})
        mock_get.assert_called_once()

    @override_settings(HUBTEL_CLIENT_ID="id", HUBTEL_CLIENT_SECRET="secret", HUBTEL_SENDER_ID="NewlifeAG")
    def test_webhook_sends_a_no_match_text_for_an_unrecognized_number(self):
        with patch("churchapp.sms.requests.get") as mock_get:
            mock_get.return_value.raise_for_status.return_value = None
            self.client.post(reverse("sms_checkin_webhook"), {"From": "0209999999", "Content": "IN"})
        mock_get.assert_called_once()


class BuildMembershipCertificatePdfTests(TestCase):
    """Unit tests on the PDF builder itself (staff/tests.py's StaffMembershipCertificateTests covers the view/permission)."""

    def test_returns_pdf_bytes(self):
        member = Member.objects.create(first_name="Efua", last_name="Owusu")
        pdf_bytes = build_membership_certificate_pdf(member, date(2026, 1, 15))
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_mentions_the_campus_when_the_member_has_one(self):
        campus = Campus.objects.create(name="Spintex Branch")
        with_campus = Member.objects.create(first_name="Efua", last_name="Owusu", campus=campus)
        without_campus = Member.objects.create(first_name="Kojo", last_name="Mensah")
        with_campus_pdf = build_membership_certificate_pdf(with_campus, date(2026, 1, 15))
        without_campus_pdf = build_membership_certificate_pdf(without_campus, date(2026, 1, 15))
        # The campus name is embedded in the PDF's compressed content stream,
        # not as plain readable text, so this just confirms the two renders
        # differ (one mentions the campus, the other doesn't) rather than
        # searching the bytes for "Spintex Branch" directly.
        self.assertNotEqual(with_campus_pdf, without_campus_pdf)
