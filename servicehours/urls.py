from django.urls import path

from . import views

urlpatterns = [
    path("log/", views.log_service_hours, name="log_service_hours"),
]
