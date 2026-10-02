from decimal import Decimal

from django.db import models
from django.db.models import Sum

from members.models import Campus, Member


class Donation(models.Model):
    class DonationType(models.TextChoices):
        TITHE = "tithe", "Tithe"
        OFFERING = "offering", "Offering"
        PLEDGE = "pledge", "Pledge"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    # Left blank for anonymous giving.
    member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="donations",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="donations",
        help_text="Which campus this gift was given at (only relevant once there's more than one).",
    )
    # String reference, not an import, since GivingCampaign is defined lower
    # down in this same file (it needs Donation to exist first, for its own
    # given_total/pledged_total properties).
    campaign = models.ForeignKey(
        "GivingCampaign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="donations",
        help_text="Which giving campaign this gift counts toward, if any (only relevant while a campaign is running).",
    )
    donation_type = models.CharField(
        max_length=10, choices=DonationType.choices, default=DonationType.OFFERING
    )
    # Contact details typed in on the public giving page - needed by the
    # payment provider (it requires an email) and for following up on a gift
    # from someone without a member profile. Blank for staff-logged gifts.
    donor_name = models.CharField(max_length=150, blank=True)
    donor_email = models.EmailField(blank=True)
    donor_phone = models.CharField(max_length=30, blank=True)
    date = models.DateTimeField(auto_now_add=True)
    # Never store card numbers or other raw payment details here - only the
    # provider's own reference/transaction ID (e.g. from Paystack/Flutterwave).
    payment_reference = models.CharField(
        max_length=100, blank=True, help_text="Reference/transaction ID from the payment provider."
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        who = self.member if self.member else "Anonymous"
        return f"{who} - {self.amount} ({self.status})"


class GivingCampaign(models.Model):
    """
    A time-boxed giving push - a building fund, a missions offering, a
    Christmas project - that the church tracks progress toward. Separate
    from the everyday tithes/offerings a Donation normally represents:
    a campaign is optional context a gift can be tagged with (see
    Donation.campaign above), on top of its ordinary donation_type.
    """

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    goal_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional target amount. Leave blank for a campaign with no fixed goal.",
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive campaigns are hidden from the public giving page and the pledge/give forms.",
    )
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="giving_campaigns",
        help_text="Which campus this campaign is for (only relevant once there's more than one).",
    )
    # Optional - lets a member tag an SMS gift to this campaign by texting
    # e.g. "GIVE 100 BUILDING" instead of just "GIVE 100" (see
    # giving/services.py's record_sms_gift). blank=True/default="" like
    # Group.meeting_day above, since this is a new CharField on an existing
    # table.
    sms_keyword = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text='Optional word for text giving, e.g. "BUILDING" - a member texts "GIVE 100 BUILDING" to tag a gift to this campaign.',
    )

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return self.name

    @property
    def pledged_total(self):
        return self.pledges.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    @property
    def given_total(self):
        return self.donations.filter(status=Donation.Status.COMPLETED).aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0.00")

    @property
    def percent_of_goal(self):
        """Whole-number percent toward the goal, capped at 100 - or None if there's no goal to measure against."""
        if not self.goal_amount:
            return None
        # Decimal(str(...)) rather than a bare division - goal_amount can
        # still be a plain string on an unsaved/unrefreshed in-memory
        # instance (e.g. one just built with .create(goal_amount="1000.00")),
        # and a DecimalField only actually holds a Decimal once it's
        # round-tripped through the database.
        goal_amount = self.goal_amount if isinstance(self.goal_amount, Decimal) else Decimal(str(self.goal_amount))
        return min(100, int((self.given_total / goal_amount) * 100))


class Pledge(models.Model):
    """
    A member's commitment to give a certain amount toward a specific
    campaign - tracked separately from what they've actually given so far
    (see given_toward_pledge below, which looks at completed Donations
    tagged with the same campaign and member).
    """

    campaign = models.ForeignKey(GivingCampaign, on_delete=models.CASCADE, related_name="pledges")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="pledges")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date_pledged = models.DateField(auto_now_add=True)

    class Meta:
        # One pledge per member per campaign - a member updating their
        # pledge amount updates this same row rather than creating another.
        unique_together = ("campaign", "member")
        ordering = ["-date_pledged"]

    @property
    def given_toward_pledge(self):
        return Donation.objects.filter(
            campaign=self.campaign, member=self.member, status=Donation.Status.COMPLETED
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    def __str__(self):
        return f"{self.member} pledged GH₵{self.amount} to {self.campaign}"


class RecurringGiving(models.Model):
    """
    A member's own commitment to give a fixed amount on a repeating
    schedule - not a live recurring charge (Flutterwave is wired up for
    one-time payments only here - see the README's "Recurring giving"
    section for the deliberate scope decision), just a tracked commitment
    with reminders. The daily send_recurring_giving_reminders management
    command emails/texts the member when next_due_date arrives and advances
    it by one period (see giving/services.py's advance_recurring_giving_due_date) -
    actually giving still happens through the ordinary /give/ form.
    """

    class Frequency(models.TextChoices):
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="recurring_gifts")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.MONTHLY)
    campaign = models.ForeignKey(
        "GivingCampaign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recurring_gifts",
        help_text="Optional - leave blank for a recurring gift to the general fund rather than a specific campaign.",
    )
    next_due_date = models.DateField(help_text="The next date a reminder to give goes out.")
    # Turned off (never deleted) once a member cancels - same never-delete
    # policy as everywhere else in this app (e.g. an inactive GivingCampaign).
    is_active = models.BooleanField(default=True)
    created_at = models.DateField(auto_now_add=True)
    last_reminder_sent = models.DateField(null=True, blank=True)
    # How many reminders have gone out in total - separate from
    # last_reminder_sent (a date, so it can only ever say "reminded most
    # recently on X", never "how many times"). Used by
    # giving/services.py's lapsed_recurring_gifts to tell a brand new
    # commitment that simply hasn't hit its first due date yet apart from
    # one that's been reminded repeatedly with nothing to show for it.
    reminder_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.member} - GH₵{self.amount} {self.get_frequency_display()}"
