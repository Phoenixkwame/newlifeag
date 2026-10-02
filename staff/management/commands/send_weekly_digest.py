"""
Sends the weekly staff digest email to Pastors - meant to run once a week
(e.g. Friday morning via Windows Task Scheduler or a cron job), not
manually:

    python manage.py send_weekly_digest

See staff/digest.py's build_weekly_digest/send_weekly_digest for exactly
what's in the email and why. Safe to run more than once in the same week -
there's no "already sent" flag to worry about, since this is just a
point-in-time snapshot each time, not something that could double-notify
anyone the way a per-record reminder would.
"""

from django.core.management.base import BaseCommand

from staff.digest import send_weekly_digest


class Command(BaseCommand):
    help = "Emails the weekly staff digest (new members, pending gifts, volunteer gaps, prayer requests) to Pastors."

    def handle(self, *args, **options):
        sent_to = send_weekly_digest()
        if sent_to:
            self.stdout.write(self.style.SUCCESS(f"Weekly digest sent to {sent_to} Pastor(s)."))
        else:
            self.stdout.write(
                self.style.WARNING("Weekly digest not sent - no Pastors with an email on file yet.")
            )
