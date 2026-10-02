"""
Sends a reminder (email/SMS) to everyone with an upcoming ServingAssignment
within the reminder window, then stamps reminder_sent_at so running this
more than once (even the same day) never double-reminds anyone. Meant to
run daily (Windows Task Scheduler locally, cron on a Linux host) - see
"Worship/ministry team scheduling" in the README.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from members.models import ServingAssignment
from members.notifications import send_serving_reminder

REMINDER_WINDOW_DAYS = 3


class Command(BaseCommand):
    help = "Sends reminders to members scheduled to serve within the next few days."

    def handle(self, *args, **options):
        today = timezone.localdate()
        due = ServingAssignment.objects.filter(
            reminder_sent_at__isnull=True,
            date__gte=today,
            date__lte=today + timedelta(days=REMINDER_WINDOW_DAYS),
        ).select_related("member", "group")

        sent = 0
        for assignment in due:
            send_serving_reminder(assignment)
            assignment.reminder_sent_at = today
            assignment.save(update_fields=["reminder_sent_at"])
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} serving reminder(s)."))
