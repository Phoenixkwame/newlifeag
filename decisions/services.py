"""
Shared logic for recording an altar-call decision - a first-time salvation
decision automatically starts a FollowUp (reusing followup/services.py's
start_follow_up, the same function the "Start Follow-Up" button on a
member's staff detail page already calls), so nobody who responds to an
altar call is lost track of afterward. A rededication or other decision
type never touches FollowUp - that pipeline is specifically for
first-time visitors becoming established members, not an established
member's ongoing walk.
"""

from django.utils import timezone

from followup.services import start_follow_up

from .models import Decision


def record_decision(member, *, decision_type, date=None, event=None, notes="", user=None):
    decision = Decision.objects.create(
        member=member,
        decision_type=decision_type,
        date=date or timezone.localdate(),
        event=event,
        notes=notes,
        recorded_by=user,
    )
    if decision_type == Decision.DecisionType.SALVATION:
        start_follow_up(member, user=user)
    return decision
