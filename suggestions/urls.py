from django.urls import path

from . import views

urlpatterns = [
    path("", views.submit_suggestion, name="submit_suggestion"),
    path("thanks/", views.suggestion_confirmation, name="suggestion_confirmation"),
]
