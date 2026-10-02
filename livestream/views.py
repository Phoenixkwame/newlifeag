from django.core.paginator import Paginator
from django.shortcuts import render

from .models import LiveStream
from .youtube import youtube_embed_url


def watch_online(request):
    """
    Public "Watch Online" page - the most recently posted stream (whichever
    of "upcoming" or "already streamed" it is - see LiveStream.is_upcoming)
    is shown prominently as "Watch Now"/"Watch the Replay", and every
    earlier one is listed below as a browsable, paginated history, same
    pattern as sermons/views.py's sermon_list.
    """
    latest = LiveStream.objects.first()
    past_qs = LiveStream.objects.all()
    if latest:
        past_qs = past_qs.exclude(id=latest.id)
    page_obj = Paginator(past_qs, 10).get_page(request.GET.get("page"))
    return render(request, "livestream/watch_online.html", {"latest": latest, "page_obj": page_obj,
        "latest_embed_url": youtube_embed_url(latest.stream_url) if latest else None})
