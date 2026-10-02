from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from churchapp.validation import optional_id

from .models import Devotional, Sermon, SermonProgress, SermonSeries, Tag
from .services import toggle_sermon_watched


def podcast(request):
    episodes = Sermon.objects.filter(audio_file__isnull=False).exclude(audio_file="").order_by("-date", "-pk")
    from django.urls import reverse
    return render(request, "sermons/podcast.html", {
        "page_obj": Paginator(episodes, 10).get_page(request.GET.get("page")),
        "feed_url": request.build_absolute_uri(reverse("sermon_podcast_feed")),
    })


def sermon_list(request):
    sermons_qs = Sermon.objects.select_related("series").order_by("-date", "-pk")

    query = request.GET.get("q", "").strip()
    if query:
        # scripture_reference and notes together are what make this a real
        # Bible-verse search, not just a title/speaker search - a sermon
        # tagged "John 3:16" in its own reference field matches, and so does
        # one where a verse is only mentioned in the notes but the reference
        # field itself was left blank.
        sermons_qs = sermons_qs.filter(
            Q(title__icontains=query)
            | Q(speaker__icontains=query)
            | Q(scripture_reference__icontains=query)
            | Q(notes__icontains=query)
        )

    series_id = request.GET.get("series", "")
    if series_id:
        sermons_qs = sermons_qs.filter(series_id=optional_id(series_id))

    tag_id = request.GET.get("tag", "")
    if tag_id:
        sermons_qs = sermons_qs.filter(tags__id=optional_id(tag_id))

    page_obj = Paginator(sermons_qs, 10).get_page(request.GET.get("page"))
    return render(
        request,
        "sermons/sermon_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "series_list": SermonSeries.objects.all(),
            "selected_series_id": series_id,
            "tag_list": Tag.objects.all(),
            "selected_tag_id": tag_id,
        },
    )


def sermon_detail(request, sermon_id):
    """
    A page of its own for one sermon - mainly so the podcast feed (see
    feeds.py) has somewhere real to link each episode back to, rather than
    just the general listing page. A signed-in member also sees a "Mark as
    Watched" toggle here (see sermon_toggle_watched) - this is the page
    where the sermon is actually listened to/watched (the audio player or
    the media_url link), so marking progress belongs here rather than on
    the series listing.
    """
    sermon = get_object_or_404(Sermon.objects.select_related("series").prefetch_related("tags"), id=sermon_id)
    member = getattr(request.user, "member_profile", None)
    is_watched = member is not None and SermonProgress.objects.filter(member=member, sermon=sermon).exists()
    return render(
        request,
        "sermons/sermon_detail.html",
        {"sermon": sermon, "signed_in_member": member, "is_watched": is_watched},
    )


@login_required
def sermon_toggle_watched(request, sermon_id):
    """
    A member marking/unmarking one sermon as watched from that sermon's own
    detail page. Always sends the member back there (this is only ever
    reached from sermon_detail.html's own toggle form, not a generic
    "next"-style redirect anyone could point elsewhere).
    """
    sermon = get_object_or_404(Sermon, id=sermon_id)
    member = getattr(request.user, "member_profile", None)
    if member and request.method == "POST":
        now_watched = toggle_sermon_watched(member=member, sermon=sermon)
        messages.success(request, "Marked as watched." if now_watched else "Marked as not watched.")
    return redirect("sermon_detail", sermon_id=sermon.id)


def series_detail(request, series_id):
    """
    The series landing page - every sermon in the series, plus (for a
    signed-in member) how far through it they've gotten, via the same
    SermonProgress rows sermon_detail's toggle button creates/deletes. A
    visitor who isn't signed in (or isn't yet linked to a Member record)
    simply sees the sermon list with no progress bar - see
    sermon_progress_shown in the template.
    """
    series = get_object_or_404(SermonSeries, id=series_id)
    sermons = series.sermons.order_by("date")
    member = getattr(request.user, "member_profile", None)
    watched_sermon_ids = set()
    total_count = sermons.count()
    if member:
        watched_sermon_ids = set(
            SermonProgress.objects.filter(member=member, sermon__in=sermons).values_list("sermon_id", flat=True)
        )
    watched_count = len(watched_sermon_ids)
    progress_percent = int(watched_count * 100 / total_count) if total_count else 0
    return render(
        request,
        "sermons/series_detail.html",
        {
            "series": series,
            "sermons": sermons,
            "signed_in_member": member,
            "watched_sermon_ids": watched_sermon_ids,
            "watched_count": watched_count,
            "total_count": total_count,
            "progress_percent": progress_percent,
        },
    )


def devotional_list(request):
    today = timezone.localdate()
    todays_devotional = Devotional.objects.filter(date=today).first()
    devotionals_qs = Devotional.objects.exclude(date=today)

    query = request.GET.get("q", "").strip()
    if query:
        devotionals_qs = devotionals_qs.filter(
            Q(title__icontains=query) | Q(scripture_reference__icontains=query) | Q(body__icontains=query)
        )
        # A search is about finding a past devotional, not today's - once
        # someone's searching, showing today's card too is just clutter.
        todays_devotional = None

    page_obj = Paginator(devotionals_qs, 15).get_page(request.GET.get("page"))
    return render(
        request,
        "sermons/devotional_list.html",
        {"todays_devotional": todays_devotional, "page_obj": page_obj, "query": query},
    )
