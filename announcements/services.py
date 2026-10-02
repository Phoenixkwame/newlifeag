"""
Shared logic for computing and messaging an Announcement's audience - used
by both the staff view (to preview a recipient count before sending) and the
actual send action, so the two can never disagree about who "everyone in
this announcement's audience" actually is.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from churchapp.sms import send_sms
from giving.services import lapsed_recurring_gifts
from members.models import Member
from members.services import absentee_members

from .models import Announcement, AnnouncementDelivery

logger = logging.getLogger(__name__)


def audience_queryset(announcement):
    """
    Computed fresh every time (never stored as a fixed list of members), so
    a recipient-count preview shown before sending always reflects who's
    active/in-group right up to the moment Send is actually clicked. The
    same applies to the two saved-segment audiences below - ABSENTEES and
    LAPSED_GIVERS are never snapshotted onto the Announcement itself, just
    recomputed from the same helpers the dedicated staff pages for each
    already use (members/services.py's absentee_members, giving/services.py's
    lapsed_recurring_gifts), so "everyone currently absent/lapsed" is always
    exactly who those pages would show right now, not who matched when the
    announcement was first drafted.
    """
    members = Member.objects.filter(is_active=True)
    if announcement.audience == Announcement.Audience.CAMPUS and announcement.campus_id:
        members = members.filter(campus=announcement.campus)
    elif announcement.audience == Announcement.Audience.GROUP and announcement.group_id:
        members = members.filter(memberships__group=announcement.group, memberships__left_date__isnull=True)
    elif announcement.audience == Announcement.Audience.ABSENTEES:
        member_ids = [member.id for member, _ in absentee_members()]
        members = members.filter(id__in=member_ids)
    elif announcement.audience == Announcement.Audience.LAPSED_GIVERS:
        member_ids = [recurring.member_id for recurring in lapsed_recurring_gifts()]
        members = members.filter(id__in=member_ids)
    # A member who's turned off *both* channels (see Member's
    # notify_by_email/notify_by_sms, set from their own account settings
    # page) is excluded from the audience/preview entirely - there'd be no
    # way to reach them anyway. A member who's only opted out of one
    # channel still counts (they're still reachable on the other), and
    # send_announcement below is what actually skips the disabled channel.
    members = members.filter(Q(notify_by_email=True) | Q(notify_by_sms=True))
    return members.distinct()


def send_announcement(announcement):
    """
    Sends once, ever - a second call on an already-sent announcement is a
    no-op (returns False) so a doubled click on "Send" can never double-
    message the whole church. Best-effort per member, same pattern as every
    other notification in this app (see members/notifications.py,
    giving/notifications.py): one member's failed email/SMS never stops the
    rest of the announcement from going out.

    Also writes one AnnouncementDelivery row per member per channel (sent,
    failed, or skipped and why) - the per-member detail behind the
    email_sent_count/sms_sent_count totals stored on the announcement
    itself, so a Pastor can audit exactly who this announcement reached
    afterward (see staff/views.py's announcement_delivery_report) rather
    than only ever seeing the two aggregate numbers.
    """
    # Claim in one committed UPDATE, before any external side effect. A stale
    # object or simultaneous worker cannot send the same announcement again.
    claimed_at = timezone.now()
    if not Announcement.objects.filter(pk=announcement.pk, sent_at__isnull=True).update(sent_at=claimed_at):
        announcement.refresh_from_db()
        return False
    announcement.refresh_from_db()

    sms_text = announcement.sms_body or announcement.body[:300]
    email_count = 0
    sms_count = 0
    deliveries = []
    for member in audience_queryset(announcement):
        if not member.email:
            status = AnnouncementDelivery.Status.SKIPPED_NO_CONTACT
        elif not member.notify_by_email:
            status = AnnouncementDelivery.Status.SKIPPED_OPTED_OUT
        else:
            try:
                send_mail(
                    announcement.subject,
                    announcement.body,
                    settings.DEFAULT_FROM_EMAIL,
                    [member.email],
                    fail_silently=False,
                )
                email_count += 1
                status = AnnouncementDelivery.Status.SENT
            except Exception:
                logger.exception("Couldn't email the announcement to %s.", member)
                status = AnnouncementDelivery.Status.FAILED
        deliveries.append(
            AnnouncementDelivery(announcement=announcement, member=member, channel=AnnouncementDelivery.Channel.EMAIL, status=status)
        )

        if not member.phone:
            status = AnnouncementDelivery.Status.SKIPPED_NO_CONTACT
        elif not member.notify_by_sms:
            status = AnnouncementDelivery.Status.SKIPPED_OPTED_OUT
        elif send_sms(member.phone, sms_text):
            sms_count += 1
            status = AnnouncementDelivery.Status.SENT
        else:
            status = AnnouncementDelivery.Status.FAILED
        deliveries.append(
            AnnouncementDelivery(announcement=announcement, member=member, channel=AnnouncementDelivery.Channel.SMS, status=status)
        )

    AnnouncementDelivery.objects.bulk_create(deliveries)
    announcement.email_sent_count = email_count
    announcement.sms_sent_count = sms_count
    announcement.save(update_fields=["email_sent_count", "sms_sent_count"])
    return True
