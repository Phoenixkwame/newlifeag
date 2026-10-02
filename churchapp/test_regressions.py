"""Regression coverage for the security and reliability review."""
import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from PIL import Image
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from announcements.models import Announcement
from announcements.services import send_announcement
from events.models import Event, EventRegistration, EventTicket, VolunteerSlot, VolunteerSignup, VolunteerWaitlistEntry
from events.services import generate_recurring_occurrences, register_for_ticket
from giving.models import Donation
from members.models import Attendance, Campus, Member, StaffLoginAttempt
from staff.services import import_members_csv
from churchapp.two_factor import SESSION_CODE, SESSION_USER_ID


class ReviewRegressionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('review-member', password='review-password')
        self.member = Member.objects.create(user=self.user, first_name='Own', last_name='Member')
        self.other = Member.objects.create(first_name='Private', last_name='Person', share_in_directory=False, phone='0244000000')
        self.event = Event.objects.create(title='Review Event', start_datetime=timezone.now() + timedelta(days=1))
        self.ticket = EventTicket.objects.create(event=self.event, name='Admission', price='25.00', capacity=1)

    def test_anonymous_forms_do_not_expose_private_members_or_accept_signups(self):
        for url in [reverse('event_detail', args=[self.event.pk]), reverse('give')]:
            self.assertNotContains(self.client.get(url), 'Private Person')
        response = self.client.post(reverse('event_detail', args=[self.event.pk]), {
            'form_type': 'rsvp', 'member': self.other.pk, 'status': 'going',
        })
        self.assertIn('/accounts/login/', response.url)
        self.assertFalse(self.event.rsvps.exists())

    def test_logged_in_member_cannot_impersonate_another_member(self):
        self.client.force_login(self.user)
        url = reverse('event_detail', args=[self.event.pk])
        self.client.post(url, {'form_type': 'rsvp', 'member': self.other.pk, 'status': 'going'})
        self.assertFalse(self.event.rsvps.exists())
        self.client.post(url, {'form_type': 'rsvp', 'member': self.member.pk, 'status': 'going'})
        self.assertEqual(self.event.rsvps.get().member, self.member)

    def test_full_slot_adds_member_to_waitlist(self):
        slot = VolunteerSlot.objects.create(event=self.event, role_needed='Usher', capacity=1)
        VolunteerSignup.objects.create(slot=slot, member=self.other)
        self.client.force_login(self.user)
        self.client.post(reverse('event_detail', args=[self.event.pk]), {
            'form_type': 'volunteer', 'member': self.member.pk, 'slot': slot.pk,
        })
        self.assertTrue(VolunteerWaitlistEntry.objects.filter(slot=slot, member=self.member).exists())

    def test_zero_capacity_is_full_but_null_is_unlimited(self):
        self.ticket.capacity = 0
        self.assertTrue(self.ticket.is_full)
        self.ticket.capacity = None
        self.assertFalse(self.ticket.is_full)

    @override_settings(FLUTTERWAVE_SECRET_KEY='test')
    @patch('events.views.initiate_payment', return_value='https://example.invalid/checkout')
    def test_pending_checkout_resumes_without_new_charge_or_reservation(self, initiate):
        self.client.force_login(self.user)
        url = reverse('event_detail', args=[self.event.pk])
        data = {'form_type': 'register', 'member': self.member.pk, 'ticket': self.ticket.pk}
        first = self.client.post(url, data)
        second = self.client.post(url, data)
        self.assertEqual(first.url, second.url)
        initiate.assert_called_once()
        self.assertEqual(EventRegistration.objects.count(), 1)

    def test_expired_reservation_releases_capacity(self):
        old, _ = register_for_ticket(ticket_id=self.ticket.pk, member=self.member)
        EventRegistration.objects.filter(pk=old.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertFalse(self.ticket.is_full)
        new, created = register_for_ticket(ticket_id=self.ticket.pk, member=self.other)
        self.assertTrue(created)
        old.refresh_from_db()
        self.assertEqual(old.status, EventRegistration.Status.FAILED)
        self.assertEqual(new.amount_due, Decimal('25.00'))

    def payment_result(self, reference, amount='25.00'):
        return {'status': 'success', 'data': {
            'status': 'successful', 'amount': amount, 'currency': 'GHS', 'tx_ref': reference,
        }}

    def test_payment_reference_binding_and_immutable_completed_state(self):
        cases = [
            (Donation.objects.create(amount='25.00', payment_reference='donation-review'), 'giving_callback', 'giving.views'),
            (EventRegistration.objects.create(ticket=self.ticket, member=self.member, payment_reference='ticket-review'), 'event_registration_callback', 'events.views'),
        ]
        for obj, route, module in cases:
            with self.subTest(route=route):
                url = reverse(route)
                params = {'status': 'successful', 'tx_ref': obj.payment_reference, 'transaction_id': '123'}
                with patch(module + '.verify_payment', return_value=self.payment_result('unrelated')):
                    self.client.get(url, params)
                obj.refresh_from_db()
                self.assertNotEqual(obj.status, 'completed')
                notification = 'send_donation_receipt_email' if route == 'giving_callback' else 'send_registration_confirmation'
                with patch(module + '.verify_payment', return_value=self.payment_result(obj.payment_reference)), patch(module + '.' + notification) as notify:
                    with self.captureOnCommitCallbacks(execute=True):
                        self.client.get(url, params)
                    self.client.get(url, params)
                    self.client.get(url, {'status': 'cancelled', 'tx_ref': obj.payment_reference})
                    notify.assert_called_once()
                obj.refresh_from_db()
                self.assertEqual(obj.status, 'completed')

    def test_ticket_price_change_does_not_change_checkout_amount(self):
        reg = EventRegistration.objects.create(ticket=self.ticket, member=self.member, payment_reference='price-review')
        self.ticket.price = Decimal('80.00')
        self.ticket.save()
        with patch('events.views.verify_payment', return_value=self.payment_result(reg.payment_reference)):
            self.client.get(reverse('event_registration_callback'), {'status': 'successful', 'tx_ref': reg.payment_reference, 'transaction_id': '123'})
        reg.refresh_from_db()
        self.assertEqual(reg.status, 'completed')
        self.assertEqual(reg.amount_due, Decimal('25.00'))

    def test_late_payment_does_not_overbook_a_reallocated_spot(self):
        reg = EventRegistration.objects.create(ticket=self.ticket, member=self.member, payment_reference='late-review', expires_at=timezone.now() - timedelta(seconds=1))
        register_for_ticket(ticket_id=self.ticket.pk, member=self.other)
        with patch('events.views.verify_payment', return_value=self.payment_result(reg.payment_reference)):
            self.client.get(reverse('event_registration_callback'), {'status': 'successful', 'tx_ref': reg.payment_reference, 'transaction_id': '123'})
        reg.refresh_from_db()
        self.assertEqual(reg.status, EventRegistration.Status.REVIEW)
        self.assertEqual(self.ticket.registered_count, 1)

    def test_recurring_events_keep_the_parent_campus(self):
        self.event.campus = Campus.objects.create(name='Main')
        self.event.save()
        children = generate_recurring_occurrences(self.event, frequency=Event.Recurrence.WEEKLY, count=3)
        self.assertTrue(all(child.campus_id == self.event.campus_id for child in children))

    def test_invalid_filters_return_404_instead_of_server_errors(self):
        Campus.objects.create(name='A')
        Campus.objects.create(name='B')
        for route, key in [('upcoming_events', 'campus'), ('sermon_list', 'series'), ('sermon_list', 'tag')]:
            for value in ['abc', '99999999999999999999999999999999999', '-1']:
                with self.subTest(route=route, key=key, value=value):
                    self.assertEqual(self.client.get(reverse(route), {key: value}).status_code, 404)

    def test_invalid_csv_encoding_makes_no_partial_import(self):
        before = Member.objects.count()
        data = b'first_name,last_name\nValid,Person\n' + b'x' * 10000 + b'\xff,Invalid'
        result = import_members_csv(SimpleUploadedFile('members.csv', data))
        self.assertTrue(result.errors)
        self.assertEqual(Member.objects.count(), before)

    def test_stale_announcement_instance_cannot_send_twice(self):
        self.member.email = 'member@example.invalid'
        self.member.save()
        notice = Announcement.objects.create(subject='Review', body='Review')
        stale = Announcement.objects.get(pk=notice.pk)
        with patch('announcements.services.send_mail', return_value=1) as mailer, patch('announcements.services.send_sms', return_value=True):
            self.assertTrue(send_announcement(notice))
            self.assertFalse(send_announcement(stale))
        mailer.assert_called_once()


class StaffAccessRegressionTests(TestCase):
    def setUp(self):
        self.a = Campus.objects.create(name='A')
        self.b = Campus.objects.create(name='B')
        self.staff = User.objects.create_user('scoped-staff', password='review-password', is_staff=True, email='staff@example.invalid')
        self.staff.user_permissions.add(*Permission.objects.filter(codename__in=['view_member', 'change_member', 'add_member']))
        self.member = Member.objects.create(user=self.staff, first_name='Staff', last_name='A', campus=self.a)
        self.other = Member.objects.create(first_name='Private', last_name='B', campus=self.b)
        self.client.force_login(self.staff)

    def test_cross_campus_member_auxiliary_pages_are_blocked(self):
        for route in ['staff_member_detail', 'staff_member_id_card', 'staff_member_id_card_qr', 'staff_membership_certificate_pdf']:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route, args=[self.other.pk])).status_code, 404)

    def test_admin_cannot_expose_or_edit_another_campus_member(self):
        self.assertNotContains(self.client.get('/admin/members/member/'), 'Private B')
        response = self.client.get(f'/admin/members/member/{self.other.pk}/change/')
        self.assertNotEqual(response.status_code, 200)
        self.client.post(f'/admin/members/member/{self.other.pk}/change/', {'first_name': 'Changed'})
        self.other.refresh_from_db()
        self.assertEqual(self.other.first_name, 'Private')

    def test_removing_own_campus_cannot_remove_access_restrictions(self):
        response = self.client.post(reverse('staff_member_edit', args=[self.member.pk]), {
            'first_name': 'Staff', 'last_name': 'A', 'role': 'member', 'is_active': 'on', 'campus': '',
        })
        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertEqual(self.member.campus, self.a)

    def test_attendance_requires_permissions_and_limits_members_and_events(self):
        url = reverse('mark_attendance')
        self.client.post(url, {'submit_attendance': '1', 'present_members': [self.other.pk]})
        self.assertFalse(Attendance.objects.exists())
        self.staff.user_permissions.add(*Permission.objects.filter(codename__in=['add_attendance', 'change_attendance']))
        self.client.post(url, {'submit_attendance': '1', 'present_members': [self.member.pk, self.other.pk], 'campus_id': self.b.pk})
        self.assertTrue(Attendance.objects.filter(member=self.member, present=True).exists())
        self.assertFalse(Attendance.objects.filter(member=self.other).exists())
        event = Event.objects.create(title='Other campus', campus=self.b, start_datetime=timezone.now())
        self.assertEqual(self.client.get(url, {'event_id': event.pk}).status_code, 404)

    def test_nonstaff_with_retained_permission_cannot_enter_staff_pages(self):
        self.staff.is_staff = False
        self.staff.save()
        response = self.client.get(reverse('staff_member_list'))
        self.assertRedirects(response, reverse('dashboard'))

    def test_staff_photo_upload_is_saved(self):
        import tempfile
        image = io.BytesIO()
        Image.new('RGB', (2, 2)).save(image, format='PNG')
        with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            response = self.client.post(reverse('staff_member_edit', args=[self.member.pk]), {
                'first_name': 'Staff', 'last_name': 'A', 'role': 'member', 'is_active': 'on', 'campus': self.a.pk,
                'photo': SimpleUploadedFile('photo.png', image.getvalue(), content_type='image/png'),
            })
            self.assertEqual(response.status_code, 302)
            self.member.refresh_from_db()
            self.assertTrue(self.member.photo.storage.exists(self.member.photo.name))


class AuthenticationRegressionTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('staff-login', password='review-password', is_staff=True, email='staff@example.invalid')

    def test_admin_login_requires_the_code(self):
        response = self.client.post('/admin/login/', {'username': self.staff.username, 'password': 'review-password'})
        self.assertRedirects(response, reverse('verify_login_code'))
        self.assertNotIn('_auth_user_id', self.client.session)
        response = self.client.post(reverse('verify_login_code'), {'code': self.client.session[SESSION_CODE]})
        self.assertRedirects(response, reverse('admin:index'))

    def test_code_attempt_limit_survives_a_new_session(self):
        self.client.post(reverse('login'), {'username': self.staff.username, 'password': 'review-password'})
        code = self.client.session[SESSION_CODE]
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            self.client.post(reverse('verify_login_code'), {'code': wrong})
        self.assertNotIn(SESSION_USER_ID, self.client.session)
        self.client.post(reverse('verify_login_code'), {'code': code})
        self.assertNotIn('_auth_user_id', self.client.session)
        other = Client()
        other.post(reverse('login'), {'username': self.staff.username, 'password': 'review-password'})
        self.assertNotIn(SESSION_USER_ID, other.session)
        StaffLoginAttempt.objects.filter(user=self.staff).update(started_at=timezone.now() - timedelta(minutes=11))
        other.post(reverse('login'), {'username': self.staff.username, 'password': 'review-password'})
        self.assertIn(SESSION_USER_ID, other.session)

    def test_password_change_invalidates_pending_login(self):
        self.client.post(reverse('login'), {'username': self.staff.username, 'password': 'review-password'})
        code = self.client.session[SESSION_CODE]
        self.staff.set_password('new-password')
        self.staff.save()
        self.client.post(reverse('verify_login_code'), {'code': code})
        self.assertNotIn('_auth_user_id', self.client.session)


@override_settings(SMS_WEBHOOK_TOKEN='test-provider-secret')
class SmsAuthenticationRegressionTests(TestCase):
    def test_all_sms_endpoints_require_authenticated_post_and_not_browser_csrf(self):
        client = Client(enforce_csrf_checks=True)
        for route in ['sms_giving_webhook', 'sms_checkin_webhook', 'sms_serving_response_webhook', 'sms_prayer_webhook']:
            url = reverse(route)
            with self.subTest(route=route):
                self.assertEqual(client.get(url).status_code, 405)
                self.assertEqual(client.post(url, {}).status_code, 403)
                self.assertEqual(client.post(url, {}, HTTP_X_SMS_WEBHOOK_TOKEN='wrong').status_code, 403)
                self.assertEqual(client.post(url, {}, HTTP_X_SMS_WEBHOOK_TOKEN='test-provider-secret').status_code, 200)
                with override_settings(SMS_WEBHOOK_TOKEN=''):
                    self.assertEqual(client.post(url, {}, HTTP_X_SMS_WEBHOOK_TOKEN='test-provider-secret').status_code, 503)
