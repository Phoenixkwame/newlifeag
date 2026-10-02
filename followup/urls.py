from django.urls import path

from . import views

urlpatterns = [
    path("", views.connect_card, name="connect_card"),
    path("thanks/", views.connect_card_confirmation, name="connect_card_confirmation"),
    path("welcome/", views.visitor_info, name="visitor_info"),
]
