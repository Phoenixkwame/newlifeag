from django.db import models

from members.models import Campus, Member


class BabyDedication(models.Model):
    """
    A baby dedication service record. child_name is free text (deliberately
    not a Member or checkin.Child record - a dedicated baby is rarely
    already in either system, and doesn't need to be for this to be a
    useful record) while parents links to existing Member rows so a
    dedication shows up on their member_detail page.
    """

    child_name = models.CharField(max_length=150, help_text="The child being dedicated.")
    parents = models.ManyToManyField(
        Member, related_name="baby_dedications", blank=True, help_text="Parent(s) who are members here."
    )
    dedication_date = models.DateField()
    officiated_by = models.CharField(max_length=150, blank=True, help_text="Which pastor/minister officiated.")
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="baby_dedications",
        help_text="Which campus this dedication took place at (only relevant once there's more than one).",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-dedication_date"]

    def __str__(self):
        # Plain interpolation rather than a :%Y-%m-%d format spec - a date
        # object's own str() is already "YYYY-MM-DD", and a format spec
        # errors out if dedication_date hasn't gone through model
        # validation yet and is still a plain string (e.g. bulk-created
        # from an ISO date string rather than via a form's cleaned_data).
        return f"{self.child_name} ({self.dedication_date})"


class WeddingRecord(models.Model):
    """A wedding performed at the church, recorded as a formal record - certificates are printed from staff/views.py's wedding_certificate."""

    spouse_one = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="weddings_as_spouse_one")
    spouse_two = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="weddings_as_spouse_two")
    wedding_date = models.DateField()
    officiated_by = models.CharField(max_length=150, blank=True, help_text="Which pastor/minister officiated.")
    location = models.CharField(max_length=200, blank=True)
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wedding_records",
        help_text="Which campus this wedding took place at (only relevant once there's more than one).",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-wedding_date"]

    def __str__(self):
        # See BabyDedication.__str__ above for why this avoids a
        # :%Y-%m-%d format spec.
        return f"{self.spouse_one} & {self.spouse_two} ({self.wedding_date})"


class BaptismRecord(models.Model):
    """
    A water baptism record - the fourth milestone type alongside
    BabyDedication, WeddingRecord, and FuneralRecord, same Pastor-only
    management (see setup_groups.py's PASTOR_MODELS). A plain ForeignKey
    (not a OneToOneField like FuneralRecord) - unlike a home-going service,
    a member being baptized more than once isn't an error to guard
    against (e.g. an adult believer's baptism after having only been
    dedicated as a baby, or a member re-baptized after rededicating their
    life), so this deliberately allows more than one record per member.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="baptism_records")
    baptism_date = models.DateField()
    officiated_by = models.CharField(max_length=150, blank=True, help_text="Which pastor/minister officiated.")
    location = models.CharField(
        max_length=200, blank=True, help_text="e.g. the church baptistry, a river, or the beach."
    )
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="baptism_records",
        help_text="Which campus this baptism took place at (only relevant once there's more than one).",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-baptism_date"]

    def __str__(self):
        # See BabyDedication.__str__ above for why this avoids a
        # :%Y-%m-%d format spec.
        return f"{self.member} ({self.baptism_date})"


class FuneralRecord(models.Model):
    """
    A home-going/funeral service record for a member who has passed away -
    the third milestone type alongside BabyDedication and WeddingRecord,
    same Pastor-only management (see setup_groups.py's PASTOR_MODELS). A
    OneToOneField rather than a plain ForeignKey to Member, since a member
    only ever has one funeral record.
    """

    member = models.OneToOneField(
        Member, on_delete=models.CASCADE, related_name="funeral_record", help_text="The member who passed away."
    )
    date_of_death = models.DateField(null=True, blank=True)
    service_date = models.DateField()
    officiated_by = models.CharField(max_length=150, blank=True, help_text="Which pastor/minister officiated.")
    location = models.CharField(max_length=200, blank=True, help_text="Funeral home, church, or burial site.")
    family_contacts = models.ManyToManyField(
        Member,
        related_name="funerals_as_family_contact",
        blank=True,
        help_text="Surviving family members who are also members here.",
    )
    campus = models.ForeignKey(
        Campus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="funeral_records",
        help_text="Which campus this service took place at (only relevant once there's more than one).",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-service_date"]

    def __str__(self):
        # See BabyDedication.__str__ above for why this avoids a
        # :%Y-%m-%d format spec.
        return f"{self.member} ({self.service_date})"


class TransferLetter(models.Model):
    """
    A formal letter of transfer issued when a member is relocating and
    joining another church - common Assemblies of God practice, confirming
    the member was in good standing here. The fifth milestone type, same
    Pastor-only management as the other four (see PASTOR_MODELS). A plain
    ForeignKey, not a OneToOneField - a member could transfer out, later
    transfer back in, and move away again years later, so more than one
    letter per member over time is normal (same reasoning as BaptismRecord
    above, not FuneralRecord).
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="transfer_letters")
    destination_church = models.CharField(max_length=200, help_text="The church the member is transferring to.")
    destination_location = models.CharField(
        max_length=200, blank=True, help_text="City/town of the destination church, if known."
    )
    transfer_date = models.DateField()
    issued_by = models.CharField(max_length=150, blank=True, help_text="Which pastor/minister issued this letter.")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-transfer_date"]

    def __str__(self):
        # See BabyDedication.__str__ above for why this avoids a
        # :%Y-%m-%d format spec.
        return f"{self.member} to {self.destination_church} ({self.transfer_date})"
