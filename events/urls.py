from django.urls import path

from . import views

urlpatterns = [
    path("", views.upcoming_events, name="upcoming_events"),
    path("registration/callback/", views.event_registration_callback, name="event_registration_callback"),
    path("<int:event_id>/", views.event_detail, name="event_detail"),
    path("<int:event_id>/checkin/", views.event_qr_checkin, name="event_qr_checkin"),
    path("<int:event_id>/kiosk/", views.event_kiosk_checkin, name="event_kiosk_checkin"),
    path("<int:event_id>/qr/", views.event_qr_code, name="event_qr_code"),
]