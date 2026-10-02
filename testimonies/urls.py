from django.urls import path

from . import views

urlpatterns = [
    path("submit/", views.submit_testimony, name="submit_testimony"),
    path("wall/", views.testimony_wall, name="testimony_wall"),
]
