"""
Volunteer recognition badges - a lightweight, encouraging counterpart to
members/services.py's attendance streak badges, just measuring total hours
served instead of consecutive weeks attended. Computed only, from the
existing ServiceHourLog rows - no new model, no new permissions, same as the
streak badges above it.
"""

from django.db.models import Sum

VOLUNTEER_BADGES = [
    (500, "500 Hour Legend"),
    (250, "250 Hour Champion"),
    (100, "100 Hour Milestone"),
    (50, "50 Hour Volunteer"),
    (10, "10 Hour Volunteer"),
]


def total_volunteer_hours(member):
    """The sum of every hour this member has ever logged, across all groups/events."""
    return member.service_hour_logs.aggregate(total=Sum("hours"))["total"] or 0


def volunteer_badge(total_hours):
    """The highest badge earned by a given total, or None if it hasn't reached the first threshold yet."""
    for threshold, label in VOLUNTEER_BADGES:
        if total_hours >= threshold:
            return label
    return None
