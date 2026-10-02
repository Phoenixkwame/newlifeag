"""Campus restrictions shared by staff views and Django admin."""
from django.db.models import Q


def scope_queryset(queryset, campus):
    if campus is None:
        return queryset
    from .services import scope_attendance, scope_donations

    label = queryset.model._meta.label_lower
    if label == "members.attendance":
        return scope_attendance(queryset, campus)
    if label == "giving.donation":
        return scope_donations(queryset, campus)
    if label == "members.campus":
        return queryset.filter(pk=campus.pk)
    paths = {
        "events.volunteerslot": ["event__campus"],
        "events.eventticket": ["event__campus"],
        "events.eventservicetime": ["event__campus"],
        "events.eventregistration": ["ticket__event__campus", "member__campus"],
        "events.volunteersignup": ["slot__event__campus", "member__campus"],
        "events.volunteerwaitlistentry": ["slot__event__campus", "member__campus"],
        "members.household": ["members__campus"],
        "followup.contactattempt": ["follow_up__member__campus"],
    }.get(label)
    if paths is None:
        names = {field.name for field in queryset.model._meta.fields}
        paths = []
        if "campus" in names:
            paths.append("campus")
        if "member" in names:
            paths.append("member__campus")
        if "event" in names:
            paths.append("event__campus")
    for path in paths:
        queryset = queryset.filter(Q(**{path: campus}) | Q(**{path + "__isnull": True}))
    return queryset.distinct()


class CampusScopedAdminMixin:
    def get_queryset(self, request):
        from .services import staff_campus_for
        return scope_queryset(super().get_queryset(request), staff_campus_for(request.user))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        from .services import staff_campus_for
        queryset = kwargs.get("queryset", db_field.remote_field.model._default_manager.all())
        kwargs["queryset"] = scope_queryset(queryset, staff_campus_for(request.user))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        from .services import staff_campus_for
        queryset = kwargs.get("queryset", db_field.remote_field.model._default_manager.all())
        kwargs["queryset"] = scope_queryset(queryset, staff_campus_for(request.user))
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        from .services import staff_campus_for
        form = super().get_form(request, obj, **kwargs)
        campus = staff_campus_for(request.user)
        if campus and obj and self.model._meta.label_lower == "members.member" and obj.user_id == request.user.pk:
            if "campus" in form.base_fields:
                form.base_fields["campus"].required = True
        return form
