from .models import ResourceBooking


def conflicting_bookings(resource, start, end, exclude_booking_id=None):
    """
    Every existing booking of `resource` that overlaps the [start, end) window
    - used both by StaffResourceBookingForm.clean() (see staff/forms.py) to
    reject a double-booking before it's saved, and by the booking list/form
    templates to show what's already on the calendar for a resource.
    exclude_booking_id lets an edit ignore the booking being edited itself.
    """
    conflicts = ResourceBooking.objects.filter(
        resource=resource, start_datetime__lt=end, end_datetime__gt=start
    )
    if exclude_booking_id:
        conflicts = conflicts.exclude(id=exclude_booking_id)
    return conflicts.select_related("resource", "booked_by")
