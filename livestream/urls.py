from django.urls import path

from . import views

urlpatterns = [
    path("", views.watch_online, name="watch_online"),
]
