"""
Creates the standard admin groups with sensible, restricted permissions, so
not every staff account can see everything (giving records especially).

Run this once after your first migrate:
    python manage.py setup_groups

Then, for each real staff member: in the admin's Users page, check "Staff
status" (so they can log into /admin/ at all) and add them to the
appropriate group under "Groups". Safe to re-run any time - it only
updates the three groups below, never touches individual users.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

# (app_label, model_name) pairs a "Pastors" super-admin-but-not-quite role
# gets view/add/change on. Deliberately excludes delete everywhere - only
# real superusers should be able to permanently delete records.
PASTOR_MODELS = [
    ("members", "member"),
    ("members", "campus"),
    ("members", "household"),
    ("members", "group"),
    ("members", "groupmembership"),
    ("members", "attendance"),
    ("members", "servingassignment"),
    ("events", "event"),
    ("events", "rsvp"),
    ("events", "volunteerslot"),
    ("events", "eventservicetime"),
    ("events", "volunteersignup"),
    ("events", "volunteerwaitlistentry"),
    ("sermons", "sermon"),
    ("sermons", "devotional"),
    ("sermons", "sermonseries"),
    ("sermons", "tag"),
    # Public, site-wide content (the "Watch Online" page), same Pastor-only
    # reasoning as sermons/announcements above.
    ("livestream", "livestream"),
    # The homepage flyer strip - same public, site-wide content reasoning.
    ("flyers", "flyer"),
    ("giving", "donation"),
    ("giving", "givingcampaign"),
    ("giving", "pledge"),
    ("giving", "recurringgiving"),
    ("prayer", "prayerrequest"),
    ("checkin", "child"),
    ("checkin", "checkin"),
    ("followup", "followup"),
    ("followup", "contactattempt"),
    # Same Usher access as FollowUp above (see _setup_ushers) - Ushers are
    # usually the ones at the altar to record a decision.
    ("decisions", "decision"),
    ("announcements", "announcement"),
    ("pathway", "pathwaystep"),
    ("pathway", "memberpathwayprogress"),
    ("booking", "resource"),
    ("booking", "resourcebooking"),
    # CareRequest is deliberately Pastor-only - no _setup_ushers()/
    # _setup_treasurers() grant touches it, so it's the one model in this
    # project only the Pastors group can see at all.
    ("care", "carerequest"),
    # Suggestion is Pastor-only for the same reason - anonymous feedback to
    # church leadership, same as CareRequest above.
    ("suggestions", "suggestion"),
    # Testimony is Pastor-only too - unlike prayer.PrayerRequest (a member
    # can publish their own request to the wall with no review), a
    # testimony needs a Pastor's approval before it can appear on the
    # public wall, so moderating it is a leadership decision like
    # Suggestion above, not an Usher/Treasurer task.
    ("testimonies", "testimony"),
    ("surveys", "survey"),
    ("surveys", "surveyquestion"),
    ("surveys", "surveychoice"),
    ("surveys", "surveyresponse"),
    ("surveys", "surveyanswer"),
    ("milestones", "babydedication"),
    ("milestones", "weddingrecord"),
    ("milestones", "baptismrecord"),
    ("milestones", "funeralrecord"),
    ("milestones", "transferletter"),
    ("members", "skill"),
    ("members", "grouplesson"),
    ("members", "teamshoutout"),
    ("members", "songsetlist"),
    ("members", "setlistsong"),
    # MemberNote is deliberately Pastor-only, same reasoning as CareRequest
    # above - no _setup_ushers()/_setup_treasurers() grant touches it.
    ("members", "membernote"),
    # Leadership meeting minutes/action items are deliberately Pastor-only,
    # same reasoning as CareRequest/MemberNote above.
    ("governance", "meeting"),
    ("governance", "actionitem"),
    ("screening", "backgroundcheck"),
    ("screening", "volunteertraining"),
    ("maintenance", "maintenancerequest"),
    ("checkin", "sundayschoolclass"),
    ("checkin", "sundayschoollesson"),
    ("servicehours", "servicehourlog"),
    ("expenses", "budgetcategory"),
    ("expenses", "expense"),
    # Ticket sales/registrations are Pastor-only, same reasoning as
    # CareRequest above - no _setup_ushers()/_setup_treasurers()/
    # _setup_childrens_ministry() grant touches these.
    ("events", "eventticket"),
    ("events", "eventregistration"),
    # The public "Plan Your Visit" page's content - service times, wifi,
    # welcome note - is site-wide, shared content, same as an announcement,
    # so editing it is Pastor-only rather than opened up to every role.
    ("followup", "visitorinfo"),
    # Managing the equipment catalog itself (adding/retiring/editing an item's
    # condition) is Pastor-only; Ushers separately get view + checkout/checkin
    # rights below, the same split as maintenance requests above.
    ("equipment", "equipment"),
    ("equipment", "equipmentcheckout"),
    # Same split as equipment above - Pastor-only for managing the library
    # catalog itself, Ushers separately get view + checkout/return rights
    # below.
    ("library", "libraryitem"),
    ("library", "libraryloan"),
]


class Command(BaseCommand):
    help = (
        "Creates/updates the Ushers, Treasurers, Pastors, and Children's Ministry "
        "admin groups with restricted permissions."
    )

    def handle(self, *args, **options):
        self._setup_ushers()
        self._setup_treasurers()
        self._setup_pastors()
        self._setup_childrens_ministry()
        self.stdout.write(
            self.style.SUCCESS("Groups created/updated: Ushers, Treasurers, Pastors, Children's Ministry.")
        )

    @staticmethod
    def _perms(app_label, model_name, actions):
        return Permission.objects.filter(
            content_type__app_label=app_label,
            content_type__model=model_name,
            codename__in=[f"{action}_{model_name}" for action in actions],
        )

    def _setup_ushers(self):
        """
        Can mark attendance and see the member list and event schedule -
        nothing about giving. Also handles new member follow-up: since
        greeting a first-time visitor and starting their follow-up naturally
        falls to whoever's already at the door, Ushers also get add_member
        (previously view-only) so they can enter a new visitor's basic
        details themselves rather than needing a Pastor to do it first -
        still no change_member or delete_member, so they can't edit an
        existing member's details or role. Gets view/add/change on discipleship
        pathway *progress* (marking a member's steps complete as they go
        through follow-up), but not on the pathway steps themselves - which
        classes/steps exist at all is a Pastor-only decision (see PASTOR_MODELS).
        Also gets view/add on facility maintenance requests - Ushers are
        usually the first to notice something's broken during a service -
        but not change, so resolving/closing a ticket stays Pastor-only.
        Also gets view on the equipment catalog plus add/change on equipment
        checkouts - Ushers are the ones actually handing out and collecting
        mics/cables/etc. week to week - but not add/change on Equipment
        itself, so adding a new item or retiring one stays Pastor-only.
        """
        group, _ = Group.objects.get_or_create(name="Ushers")
        perms = list(self._perms("members", "attendance", ["view", "add", "change"]))
        perms += list(self._perms("members", "member", ["view", "add"]))
        perms += list(self._perms("events", "event", ["view"]))
        perms += list(self._perms("followup", "followup", ["view", "add", "change"]))
        perms += list(self._perms("followup", "contactattempt", ["view", "add"]))
        # Same reasoning as FollowUp above - Ushers are usually the ones at
        # the altar to record a decision, so they can view/add/change it
        # without needing a Pastor login.
        perms += list(self._perms("decisions", "decision", ["view", "add", "change"]))
        perms += list(self._perms("pathway", "memberpathwayprogress", ["view", "add", "change"]))
        perms += list(self._perms("maintenance", "maintenancerequest", ["view", "add"]))
        perms += list(self._perms("equipment", "equipment", ["view"]))
        perms += list(self._perms("equipment", "equipmentcheckout", ["view", "add", "change"]))
        # Same split as equipment above - Ushers can see the library catalog
        # and check items out/in, but adding or retiring a catalog item
        # stays Pastor-only.
        perms += list(self._perms("library", "libraryitem", ["view"]))
        perms += list(self._perms("library", "libraryloan", ["view", "add", "change"]))
        group.permissions.set(perms)

    def _setup_treasurers(self):
        """
        Can manage donations, giving campaigns, and pledges - nothing about
        member personal details or attendance. Gets view/change (not add) on
        recurring giving commitments - those are always set up by the member
        themselves (see giving/views.py's recurring_giving_create), so a
        Treasurer can only see them for planning and deactivate one on a
        member's request, never create one on someone's behalf. Also gets
        full view/add/change on budget categories and expenses - the outflow
        side of church finances, alongside the giving (inflow) side above.
        """
        group, _ = Group.objects.get_or_create(name="Treasurers")
        perms = list(self._perms("giving", "donation", ["view", "add", "change"]))
        perms += list(self._perms("giving", "givingcampaign", ["view", "add", "change"]))
        perms += list(self._perms("giving", "pledge", ["view", "add", "change"]))
        perms += list(self._perms("giving", "recurringgiving", ["view", "change"]))
        perms += list(self._perms("expenses", "budgetcategory", ["view", "add", "change"]))
        perms += list(self._perms("expenses", "expense", ["view", "add", "change"]))
        group.permissions.set(perms)

    def _setup_pastors(self):
        """Broad view/add/change access across all church data, but never delete."""
        group, _ = Group.objects.get_or_create(name="Pastors")
        perms = []
        for app_label, model_name in PASTOR_MODELS:
            perms += list(self._perms(app_label, model_name, ["view", "add", "change"]))
        group.permissions.set(perms)

    def _setup_childrens_ministry(self):
        """
        Can manage children's records and check-ins - view-only on
        households (to link kids to families). Also gets view-only on
        background checks and volunteer trainings, so a children's ministry
        worker can confirm a volunteer is cleared and trained (e.g. Child
        Safety) before letting them serve with kids, without being able to
        change either record themselves - only a Pastor records the outcome
        of a check or logs a completed training (see PASTOR_MODELS). Needs
        view-only on Member itself too, for that same reason - both statuses
        show up on a member's staff detail page, which is useless to look at
        if you can't open the page in the first place. Also gets full
        view/add/change on Sunday school classes and lessons - the
        children's-ministry equivalent of a small group's own leader posting
        lessons, except there's no separate self-service portal here.
        """
        group, _ = Group.objects.get_or_create(name="Children's Ministry")
        perms = list(self._perms("checkin", "child", ["view", "add", "change"]))
        perms += list(self._perms("checkin", "checkin", ["view", "add", "change"]))
        perms += list(self._perms("members", "member", ["view"]))
        perms += list(self._perms("members", "household", ["view"]))
        perms += list(self._perms("screening", "backgroundcheck", ["view"]))
        perms += list(self._perms("screening", "volunteertraining", ["view"]))
        perms += list(self._perms("checkin", "sundayschoolclass", ["view", "add", "change"]))
        perms += list(self._perms("checkin", "sundayschoollesson", ["view", "add", "change"]))
        group.permissions.set(perms)
