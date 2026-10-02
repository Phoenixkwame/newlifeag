from django.urls import path

from . import views

urlpatterns = [
    path("submit/", views.submit_care_request, name="submit_care_request"),
]
