"""
Plain iCalendar (.ics, RFC 5545) building for a member's personal schedule
feed - see views.py's member_calendar_feed. Hand-written rather than a
third-party dependency, the same "Django's own tools are enough" choice
already made for the sermon podcast feed (sermons/feeds.py, built on
Django's syndication framework rather than adding a dependency there
either) - a personal calendar feed only ever needs a handful of VEVENT
blocks, well within what a few plain functions can build correctly.
"""

from datetime import timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone


def _escape(text):
    """Escapes the handful of characters RFC 5545 requires escaped in a text value."""
    return (text or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def _utc_stamp(dt):
    """
    RFC 5545's UTC datetime format: YYYYMMDDTHHMMSSZ. Uses Python's stdlib
    datetime.timezone.utc rather than django.utils.timezone.utc - newer
    Django versions dropped that alias in favor of the stdlib one.
    """
    return timezone.localtime(dt, dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_event(*, uid, start, end=None, summary, location="", description=""):
    """One VEVENT block for something with a real start_datetime (an events.Event)."""
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_utc_stamp(timezone.now())}",
        f"DTSTART:{_utc_stamp(start)}",
    ]
    if end:
        lines.append(f"DTEND:{_utc_stamp(end)}")
    lines.append(f"SUMMARY:{_escape(summary)}")
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    lines.append("END:VEVENT")
    return lines


def build_all_day_event(*, uid, date, summary, description=""):
    """
    One VEVENT block for a date with no specific time - a ServingAssignment
    only ever records which service *date* someone's scheduled for, never a
    time. DTSTART/DTEND use RFC 5545's VALUE=DATE form for an all-day event,
    with DTEND set to the following day per that format's own
    exclusive-end-date convention.
    """
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_utc_stamp(timezone.now())}",
        f"DTSTART;VALUE=DATE:{date.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(date + timedelta(days=1)).strftime('%Y%m%d')}",
        f"SUMMARY:{_escape(summary)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    lines.append("END:VEVENT")
    return lines


def build_calendar(vevent_blocks):
    """Wraps a list of already-built VEVENT line-lists in the VCALENDAR envelope, CRLF-joined per the spec."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Newlife AG//Member Calendar//EN", "CALSCALE:GREGORIAN"]
    for block in vevent_blocks:
        lines.extend(block)
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
