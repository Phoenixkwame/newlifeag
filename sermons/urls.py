from django.urls import path

from . import views
from .feeds import SermonPodcastFeed

urlpatterns = [
    path("", views.sermon_list, name="sermon_list"),
    path("podcast.xml", SermonPodcastFeed(), name="sermon_podcast_feed"),
    path("podcast/", views.podcast, name="sermon_podcast"),
    path("series/<int:series_id>/", views.series_detail, name="sermon_series_detail"),
    path("<int:sermon_id>/", views.sermon_detail, name="sermon_detail"),
    path("<int:sermon_id>/toggle-watched/", views.sermon_toggle_watched, name="sermon_toggle_watched"),
    path("devotionals/", views.devotional_list, name="devotional_list"),
]
