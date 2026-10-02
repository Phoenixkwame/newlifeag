"""
Sends a birthday greeting (email/SMS) to every active member whose birthday
is today, and a separate anniversary greeting to every active member whose
wedding anniversary is today. Meant to run once a day (Windows Task
Scheduler locally, cron on a Linux host) - see "Birthdays & anniversaries"
in the README.

Each member has their own last_birthday_greeting_sent/
last_anniversary_greeting_sent DateField (see members/models.py), stamped
the moment a greeting is sent, so running this command more than once on
the same day never sends the same person two greetings that day.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from members.models import Member
from members.notifications import send_anniversary_greeting, send_birthday_greeting


class Command(BaseCommand):
    help = "Sends birthday and wedding anniversary greetings to members whose date is today."

    # Known, deliberately-unhandled edge case: a member born/married on
    # Feb 29 only matches this command on an actual leap day, so they'd only
    # ever be greeted once every four years. Handling that "nearest day in a
    # non-leap year" question well is more complexity than this feature is
    # worth - flagged here rather than silently ignored.
    def handle(self, *args, **options):
        today = timezone.localdate()
        birthdays_sent = 0
        anniversaries_sent = 0

        birthday_members = Member.objects.filter(
            is_active=True,
            date_of_birth__month=today.month,
            date_of_birth__day=today.day,
        ).exclude(last_birthday_greeting_sent=today)
        for member in birthday_members:
            send_birthday_greeting(member)
            member.last_birthday_greeting_sent = today
            member.save(update_fields=["last_birthday_greeting_sent"])
            birthdays_sent += 1

        anniversary_members = Member.objects.filter(
            is_active=True,
            anniversary_date__month=today.month,
            anniversary_date__day=today.day,
        ).exclude(last_anniversary_greeting_sent=today)
        for member in anniversary_members:
            send_anniversary_greeting(member)
            member.last_anniversary_greeting_sent = today
            member.save(update_fields=["last_anniversary_greeting_sent"])
            anniversaries_sent += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {birthdays_sent} birthday greeting(s) and {anniversaries_sent} anniversary greeting(s)."
            )
        )
