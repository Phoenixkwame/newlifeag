from django.urls import path

from . import views

urlpatterns = [
    path("request/", views.public_prayer_request, name="public_prayer_request"),
    path("received/", views.prayer_request_received, name="prayer_request_received"),
    path("submit/", views.submit_prayer_request, name="submit_prayer_request"),
    path("wall/", views.prayer_wall, name="prayer_wall"),
    path("sms/", views.sms_prayer_webhook, name="sms_prayer_webhook"),
]
