"""
Emails every member with at least one completed gift in a given year their
own year-end giving statement - meant to run once a year (early January,
once the previous year has fully closed out), not manually for each member
the way staff/views.py's annual_giving_statement page requires one at a
time:

    python manage.py send_giving_statements
    python manage.py send_giving_statements --year 2026

Defaults to last year (today's year minus one), since this is normally run
shortly after a year ends. Safe to re-run - each run just re-sends the same
statement for that year, so re-running it (say, to catch a member who's
since added an email address) simply re-emails everyone else too.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from giving.notifications import send_annual_giving_statement
from giving.services import members_with_completed_giving


class Command(BaseCommand):
    help = "Emails year-end giving statements to every member with a completed gift in the given year."

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            default=None,
            help="Which year to send statements for (defaults to last year).",
        )

    def handle(self, *args, **options):
        year = options["year"] or timezone.localdate().year - 1

        sent = 0
        skipped = 0
        for member in members_with_completed_giving(year):
            if send_annual_giving_statement(member, year):
                sent += 1
            else:
                skipped += 1

        message = f"Sent {sent} giving statement(s) for {year}."
        if skipped:
            message += f" Skipped {skipped} member(s) with no email on file."
        self.stdout.write(self.style.SUCCESS(message))
