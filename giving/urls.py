from django.urls import path

from . import views

urlpatterns = [
    path("", views.give, name="give"),
    path("callback/", views.giving_callback, name="giving_callback"),
    path("webhook/", views.flutterwave_webhook, name="flutterwave_webhook"),
    path("thank-you/<str:reference>/", views.giving_thank_you, name="giving_thank_you"),
    path("sms/", views.sms_giving_webhook, name="sms_giving_webhook"),
    path("statement/", views.giving_statement, name="giving_statement"),
    path("statement/pdf/", views.giving_statement_pdf, name="giving_statement_pdf"),
    path("donations/<int:donation_id>/receipt/", views.donation_receipt, name="donation_receipt"),
    path("campaigns/", views.campaign_list, name="campaign_list"),
    path("campaigns/<int:campaign_id>/", views.campaign_detail, name="campaign_detail"),
    path("campaigns/<int:campaign_id>/pledge/", views.pledge_campaign, name="pledge_campaign"),
    path("recurring/new/", views.recurring_giving_create, name="recurring_giving_create"),
    path("recurring/history/", views.recurring_giving_history, name="recurring_giving_history"),
    path("recurring/<int:recurring_id>/edit/", views.recurring_giving_edit, name="recurring_giving_edit"),
    path("recurring/<int:recurring_id>/cancel/", views.recurring_giving_cancel, name="recurring_giving_cancel"),
    path(
        "recurring/<int:recurring_id>/reactivate/",
        views.recurring_giving_reactivate,
        name="recurring_giving_reactivate",
    ),
]
