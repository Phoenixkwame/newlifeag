"""
Sends a reminder to every volunteer whose slot starts soon and who hasn't
already been reminded - meant to be run daily (e.g. from Windows Task
Scheduler or a cron job), not manually:

    python manage.py send_volunteer_reminders

Safe to run as often as you like: VolunteerSignup.reminder_sent_at is set
the first time a reminder goes out and never cleared, so re-running this
(or running it more than once a day) never sends the same person the same
reminder twice. The window below is wider than "once a day" on purpose - if
the scheduled task doesn't run for a day or two, nobody who's still inside
the window gets missed.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import VolunteerSignup
from events.notifications import send_volunteer_reminder

# How far ahead of a volunteer's slot to remind them. 48 hours means anyone
# volunteering in the next two days who hasn't been reminded yet gets a
# reminder on today's run.
REMINDER_WINDOW = timedelta(hours=48)


class Command(BaseCommand):
    help = "Sends a reminder email/SMS to volunteers whose slot is coming up soon."

    def handle(self, *args, **options):
        now = timezone.now()
        due = VolunteerSignup.objects.filter(
            reminder_sent_at__isnull=True,
            slot__event__start_datetime__gte=now,
            slot__event__start_datetime__lte=now + REMINDER_WINDOW,
        ).select_related("member", "slot", "slot__event")

        sent = 0
        for signup in due:
            send_volunteer_reminder(signup)
            signup.reminder_sent_at = now
            signup.save(update_fields=["reminder_sent_at"])
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} volunteer reminder(s)."))
