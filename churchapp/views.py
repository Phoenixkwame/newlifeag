from django.shortcuts import render
from django.utils import timezone

from events.models import Event
from flyers.models import Flyer
from followup.models import VisitorInfo
from giving.models import GivingCampaign
from livestream.models import LiveStream
from livestream.youtube import youtube_embed_url as _youtube_embed_url
from sermons.models import Sermon
from testimonies.models import Testimony


def _homepage_video(visitor_info):
    """
    The homepage's one video slot: the church's own live stream when staff
    have flagged one as featured (see LiveStream.featured_on_homepage),
    falling back to the standing "welcome video" from Visitor Info
    (welcome_video_url) when there isn't one - see the README's "Homepage
    flyer gallery & live stream/video section" for the full design.
    """
    featured_stream = LiveStream.objects.filter(featured_on_homepage=True).first()
    if featured_stream:
        return {
            "is_live": True,
            "title": featured_stream.title,
            "url": featured_stream.stream_url,
            "embed_url": _youtube_embed_url(featured_stream.stream_url),
            "is_upcoming": featured_stream.is_upcoming,
        }
    if visitor_info.welcome_video_url:
        return {
            "is_live": False,
            "title": "Get to Know Us",
            "url": visitor_info.welcome_video_url,
            "embed_url": _youtube_embed_url(visitor_info.welcome_video_url),
            "is_upcoming": False,
        }
    return None


def home(request):
    """
    Public landing page - a real "front door" for a first-time visitor, not
    just a card grid: the next event and latest sermon (as before), plus
    the church's own "planning your visit" info (service times/address,
    kept up to date by Pastors - see followup.models.VisitorInfo), a
    featured active giving campaign if one exists, a "get connected"
    section surfacing Small Groups, the Prayer Wall, and the Testimony Wall
    now that those have moved out of the main nav and into its "More" menu
    (see base.html), a "What's Happening" flyer strip (flyers.models.Flyer),
    and one video slot - the church's live stream when staff have featured
    one, falling back to a standing welcome video otherwise (see
    _homepage_video above).
    """
    next_event = Event.objects.filter(start_datetime__gte=timezone.now()).order_by("start_datetime").first()
    latest_sermon = Sermon.objects.order_by("-date").first()
    visitor_info = VisitorInfo.get_current()
    featured_campaign = GivingCampaign.objects.filter(is_active=True).order_by("-start_date").first()
    latest_testimony = Testimony.objects.filter(is_approved=True).select_related("member").first()
    flyers = Flyer.objects.filter(is_active=True)
    homepage_video = _homepage_video(visitor_info)
    return render(
        request,
        "home.html",
        {
            "next_event": next_event,
            "latest_sermon": latest_sermon,
            "visitor_info": visitor_info,
            "featured_campaign": featured_campaign,
            "flyers": flyers,
            "homepage_video": homepage_video,
            "latest_testimony": latest_testimony,
        },
    )
