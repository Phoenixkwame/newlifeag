"""
Sends a reminder to give (email/SMS) to every member with an active
recurring giving commitment whose next_due_date has arrived (or passed),
then advances that commitment's next_due_date by one period - see
giving/services.py's advance_recurring_giving_due_date, which moves the date
forward from itself rather than from today, so re-running this (or running
it more than once a day) never double-reminds the same due date. Meant to
run daily (Windows Task Scheduler locally, cron on a Linux host) - see
"Recurring giving" in the README.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from giving.models import RecurringGiving
from giving.notifications import send_recurring_giving_reminder
from giving.services import advance_recurring_giving_due_date


class Command(BaseCommand):
    help = "Sends reminders for active recurring gifts that are due (or overdue), and schedules the next one."

    def handle(self, *args, **options):
        today = timezone.localdate()
        due = RecurringGiving.objects.filter(is_active=True, next_due_date__lte=today).select_related(
            "member", "campaign"
        )

        sent = 0
        for recurring in due:
            send_recurring_giving_reminder(recurring)
            recurring.last_reminder_sent = today
            recurring.reminder_count += 1
            recurring.save(update_fields=["last_reminder_sent", "reminder_count"])
            advance_recurring_giving_due_date(recurring)
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} recurring-giving reminder(s)."))
