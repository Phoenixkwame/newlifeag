"""
Creates Newlife AG's regular weekly meetings - as small groups (for the
public group finder) and as weekly events for the next 12 weeks (for the
events page). Safe to re-run on every deploy: a group that already exists is
left alone, and a meeting's events are only generated if it has no upcoming
event at all - so nothing is ever duplicated or overwritten once staff start
editing these in the admin.

    python manage.py seed_church_schedule
"""

from datetime import datetime, timedelta, time

from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Event
from events.services import generate_recurring_occurrences
from members.models import Group

LOCATION = "Newlife Church Auditorium"
WEEKS = 12

# (name, description, weekday 0=Monday, start time)
MEETINGS = [
    ("Youth Meeting", "Our weekly gathering for the youth - worship, the Word and fellowship.", 0, time(18, 30)),
    (
        "Convert Class",
        "For new believers - learn the foundations of the Christian faith and take your next steps with Christ.",
        0,
        time(19, 0),
    ),
    ("Women's Ministry Meeting", "The women of Newlife AG meeting for prayer, the Word and encouragement.", 1, time(17, 0)),
    ("Men's Ministry Meeting", "The men of Newlife AG meeting for prayer, the Word and fellowship.", 1, time(18, 30)),
]

DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Command(BaseCommand):
    help = "Create the church's weekly meetings as small groups and upcoming weekly events (idempotent)."

    def handle(self, *args, **options):
        now = timezone.localtime()
        for name, description, weekday, start in MEETINGS:
            _, created = Group.objects.get_or_create(
                name=name,
                defaults={
                    "group_type": Group.GroupType.SMALL_GROUP,
                    "description": description,
                    "meeting_day": DAY_CODES[weekday],
                    "meeting_time": start,
                    "meeting_location": LOCATION,
                },
            )
            if created:
                self.stdout.write(f"Created group: {name}")

            if Event.objects.filter(title=name, start_datetime__gte=now).exists():
                continue
            days_ahead = (weekday - now.weekday()) % 7
            first = timezone.make_aware(datetime.combine(now.date() + timedelta(days=days_ahead), start))
            if first <= now:
                first += timedelta(weeks=1)
            event = Event.objects.create(
                title=name,
                description=description,
                event_type=Event.EventType.MEETING,
                start_datetime=first,
                location=LOCATION,
                recurrence=Event.Recurrence.WEEKLY,
            )
            generate_recurring_occurrences(event, frequency=Event.Recurrence.WEEKLY, count=WEEKS)
            self.stdout.write(f"Scheduled {WEEKS} weekly events: {name} from {first:%a %d %b %Y}")
