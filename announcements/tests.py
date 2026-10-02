from datetime import date

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from giving.models import RecurringGiving
from members.models import Campus, Group, GroupMembership, Member

from .models import Announcement, AnnouncementDelivery
from .services import audience_queryset, send_announcement


class AudienceQuerysetTests(TestCase):
    def setUp(self):
        self.main = Campus.objects.create(name="Main Campus")
        self.branch = Campus.objects.create(name="Spintex Branch")
        self.group = Group.objects.create(name="Young Adults")
        self.main_member = Member.objects.create(first_name="Ama", last_name="Owusu", campus=self.main)
        self.branch_member = Member.objects.create(first_name="Kojo", last_name="Mensah", campus=self.branch)
        self.inactive_member = Member.objects.create(
            first_name="Efua", last_name="Boateng", campus=self.main, is_active=False
        )
        GroupMembership.objects.create(member=self.main_member, group=self.group)

    def test_all_audience_includes_every_active_member(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello everyone", audience=Announcement.Audience.ALL)
        recipients = audience_queryset(announcement)
        self.assertIn(self.main_member, recipients)
        self.assertIn(self.branch_member, recipients)
        self.assertNotIn(self.inactive_member, recipients)

    def test_campus_audience_is_restricted_to_that_campus(self):
        announcement = Announcement.objects.create(
            subject="Hi", body="Hello", audience=Announcement.Audience.CAMPUS, campus=self.main
        )
        recipients = audience_queryset(announcement)
        self.assertIn(self.main_member, recipients)
        self.assertNotIn(self.branch_member, recipients)

    def test_group_audience_is_restricted_to_active_group_members(self):
        left_member = Member.objects.create(first_name="Yaw", last_name="Asare")
        GroupMembership.objects.create(member=left_member, group=self.group, left_date=date(2020, 1, 1))
        announcement = Announcement.objects.create(
            subject="Hi", body="Hello", audience=Announcement.Audience.GROUP, group=self.group
        )
        recipients = audience_queryset(announcement)
        self.assertIn(self.main_member, recipients)
        self.assertNotIn(self.branch_member, recipients)
        self.assertNotIn(left_member, recipients)

    def test_absentees_audience_is_the_same_segment_as_the_absentee_list(self):
        gone_quiet = Member.objects.create(first_name="Yaw", last_name="Asare")
        Member.objects.filter(pk=gone_quiet.pk).update(
            date_joined=timezone.localdate() - timezone.timedelta(weeks=10)
        )
        announcement = Announcement.objects.create(subject="Hi", body="Hello", audience=Announcement.Audience.ABSENTEES)
        recipients = audience_queryset(announcement)
        self.assertIn(gone_quiet, recipients)
        self.assertNotIn(self.main_member, recipients)  # joined too recently to count as absent

    def test_lapsed_givers_audience_is_the_same_segment_as_the_lapsed_givers_list(self):
        lapsed_giver = Member.objects.create(first_name="Yaw", last_name="Asare")
        RecurringGiving.objects.create(
            member=lapsed_giver, amount="60.00", frequency=RecurringGiving.Frequency.MONTHLY,
            next_due_date=timezone.localdate(), reminder_count=3,
        )
        announcement = Announcement.objects.create(
            subject="Hi", body="Hello", audience=Announcement.Audience.LAPSED_GIVERS
        )
        recipients = audience_queryset(announcement)
        self.assertIn(lapsed_giver, recipients)
        self.assertNotIn(self.main_member, recipients)

    def test_a_member_opted_out_of_both_channels_is_excluded_entirely(self):
        self.main_member.notify_by_email = False
        self.main_member.notify_by_sms = False
        self.main_member.save()
        announcement = Announcement.objects.create(subject="Hi", body="Hello", audience=Announcement.Audience.ALL)
        recipients = audience_queryset(announcement)
        self.assertNotIn(self.main_member, recipients)

    def test_a_member_opted_out_of_only_one_channel_still_counts(self):
        self.main_member.notify_by_email = False
        self.main_member.save()
        announcement = Announcement.objects.create(subject="Hi", body="Hello", audience=Announcement.Audience.ALL)
        recipients = audience_queryset(announcement)
        self.assertIn(self.main_member, recipients)


@override_settings(HUBTEL_CLIENT_ID="", HUBTEL_CLIENT_SECRET="", HUBTEL_SENDER_ID="")
class SendAnnouncementTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(
            first_name="Ama", last_name="Owusu", email="ama@example.com", phone="0244000000"
        )
        self.no_contact_member = Member.objects.create(first_name="Kojo", last_name="Mensah")

    def test_sends_email_to_every_member_with_an_email_address(self):
        announcement = Announcement.objects.create(subject="Service moved", body="This Sunday's service moves to 9am.")
        send_announcement(announcement)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.member.email])
        self.assertEqual(mail.outbox[0].subject, "Service moved")

    def test_stamps_sent_at_and_counts(self):
        announcement = Announcement.objects.create(subject="Service moved", body="Details here.")
        send_announcement(announcement)
        announcement.refresh_from_db()
        self.assertIsNotNone(announcement.sent_at)
        self.assertEqual(announcement.email_sent_count, 1)
        # SMS isn't configured in this test (HUBTEL_* is blank), so send_sms
        # always returns False and nothing counts as sent by text.
        self.assertEqual(announcement.sms_sent_count, 0)

    def test_a_member_who_opted_out_of_email_is_skipped_on_that_channel_only(self):
        self.member.notify_by_email = False
        self.member.save()
        announcement = Announcement.objects.create(subject="Service moved", body="Details here.")
        send_announcement(announcement)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_member_with_no_contact_info_is_simply_skipped(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello", audience=Announcement.Audience.ALL)
        send_announcement(announcement)
        announcement.refresh_from_db()
        self.assertEqual(announcement.email_sent_count, 1)  # only self.member, not self.no_contact_member

    def test_sending_twice_is_a_no_op_the_second_time(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello")
        first_result = send_announcement(announcement)
        mail.outbox.clear()
        second_result = send_announcement(announcement)
        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertEqual(len(mail.outbox), 0)  # nothing re-sent

    def test_records_a_sent_delivery_row_for_a_member_who_was_emailed(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello")
        send_announcement(announcement)
        delivery = AnnouncementDelivery.objects.get(
            announcement=announcement, member=self.member, channel=AnnouncementDelivery.Channel.EMAIL
        )
        self.assertEqual(delivery.status, AnnouncementDelivery.Status.SENT)

    def test_records_a_skipped_no_contact_delivery_row_for_sms_with_no_phone_configured_sms(self):
        # HUBTEL_* is blank in this test class, so send_sms always returns
        # False - the member does have a phone on file, so this is a FAILED
        # send, not a skipped one (see the next test for the no-phone case).
        announcement = Announcement.objects.create(subject="Hi", body="Hello")
        send_announcement(announcement)
        delivery = AnnouncementDelivery.objects.get(
            announcement=announcement, member=self.member, channel=AnnouncementDelivery.Channel.SMS
        )
        self.assertEqual(delivery.status, AnnouncementDelivery.Status.FAILED)

    def test_records_skipped_no_contact_for_a_member_missing_both_channels(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello", audience=Announcement.Audience.ALL)
        send_announcement(announcement)
        email_delivery = AnnouncementDelivery.objects.get(
            announcement=announcement, member=self.no_contact_member, channel=AnnouncementDelivery.Channel.EMAIL
        )
        sms_delivery = AnnouncementDelivery.objects.get(
            announcement=announcement, member=self.no_contact_member, channel=AnnouncementDelivery.Channel.SMS
        )
        self.assertEqual(email_delivery.status, AnnouncementDelivery.Status.SKIPPED_NO_CONTACT)
        self.assertEqual(sms_delivery.status, AnnouncementDelivery.Status.SKIPPED_NO_CONTACT)

    def test_records_skipped_opted_out_for_a_member_who_turned_off_email(self):
        self.member.notify_by_email = False
        self.member.save()
        announcement = Announcement.objects.create(subject="Hi", body="Hello")
        send_announcement(announcement)
        delivery = AnnouncementDelivery.objects.get(
            announcement=announcement, member=self.member, channel=AnnouncementDelivery.Channel.EMAIL
        )
        self.assertEqual(delivery.status, AnnouncementDelivery.Status.SKIPPED_OPTED_OUT)


class AnnouncementModelTests(TestCase):
    def test_str_returns_subject(self):
        announcement = Announcement.objects.create(subject="Building Fund Update", body="...")
        self.assertEqual(str(announcement), "Building Fund Update")

    def test_is_sent_reflects_sent_at(self):
        announcement = Announcement.objects.create(subject="Hi", body="Hello")
        self.assertFalse(announcement.is_sent)
        send_announcement(announcement)
        self.assertTrue(announcement.is_sent)
