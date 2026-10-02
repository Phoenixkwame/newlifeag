from django.db import models
from django.utils import timezone

from members.models import Member


class LibraryItem(models.Model):
    """
    A book, DVD, CD, or curriculum kit the church lends out to members -
    same "catalog + loan" shape as equipment.Equipment/EquipmentCheckout,
    just for the church library/resource room rather than sound/video gear.
    Kept as its own app rather than folded into equipment, since a due date
    on a loan (see LibraryLoan.due_date/is_overdue) doesn't apply to
    equipment checkouts at all.
    """

    class Category(models.TextChoices):
        BOOK = "book", "Book"
        DVD = "dvd", "DVD"
        CD = "cd", "CD"
        CURRICULUM = "curriculum", "Curriculum"
        OTHER = "other", "Other"

    title = models.CharField(max_length=200)
    author = models.CharField(max_length=150, blank=True, help_text="Author, speaker, or publisher, if applicable.")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.BOOK)
    notes = models.TextField(blank=True)
    # Retired rather than deleted, same soft-delete reasoning as
    # equipment.Equipment.is_active - no staff role has delete permission on
    # anything (see setup_groups.py).
    is_active = models.BooleanField(
        default=True, help_text="Turn off once an item is retired/lost, rather than deleting it."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title

    @property
    def current_loan(self):
        """The open loan for this item, if any - see LibraryLoan.returned_date."""
        return self.loans.filter(returned_date__isnull=True).first()

    @property
    def is_on_loan(self):
        return self.current_loan is not None


class LibraryLoan(models.Model):
    """
    One loan of a LibraryItem to a member - open (returned_date is still
    blank) or closed. An item can only ever have one open loan at a time
    (enforced in staff/views.py's library_checkout, the same way
    equipment_checkout enforces "one open checkout at a time" for
    EquipmentCheckout) - not a database constraint, since a closed loan for
    the same item is perfectly normal history to keep.
    """

    item = models.ForeignKey(LibraryItem, on_delete=models.CASCADE, related_name="loans")
    borrower = models.ForeignKey(Member, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    borrowed_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    returned_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, help_text="What it's being used for, or condition notes on return.")

    class Meta:
        ordering = ["-borrowed_date"]

    def __str__(self):
        status = "returned" if self.returned_date else "on loan"
        return f"{self.item} {status} to {self.borrower or 'someone'}"

    @property
    def is_overdue(self):
        return self.returned_date is None and self.due_date < timezone.localdate()
