from django.urls import path

from . import views

urlpatterns = [
    path("submit/", views.submit_maintenance_request, name="submit_maintenance_request"),
]
