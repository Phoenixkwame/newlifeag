from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("photo/", views.update_photo, name="update_photo"),
    path("profile/", views.edit_profile, name="edit_profile"),
    path("account/", views.account_settings, name="account_settings"),
    path("account/export/", views.member_data_export, name="member_data_export"),
    path("account/calendar-link/regenerate/", views.regenerate_calendar_link, name="regenerate_calendar_link"),
    path("calendar/<str:token>.ics", views.member_calendar_feed, name="member_calendar_feed"),
    path("interests/", views.interest_survey, name="interest_survey"),
    path("directory/", views.member_directory, name="member_directory"),
    path(
        "volunteer-signups/<int:signup_id>/cancel/",
        views.volunteer_signup_cancel,
        name="volunteer_signup_cancel",
    ),
    path("attendance/", views.mark_attendance, name="mark_attendance"),
    path("sms/", views.sms_checkin_webhook, name="sms_checkin_webhook"),
    path("sms/serving-response/", views.sms_serving_response_webhook, name="sms_serving_response_webhook"),
    path("groups/find/", views.public_group_finder, name="public_group_finder"),
    path("groups/", views.browse_groups, name="browse_groups"),
    path("groups/<int:group_id>/join/", views.join_group, name="join_group"),
    path("groups/<int:group_id>/leave/", views.leave_group, name="leave_group"),
    path("groups/<int:group_id>/attendance/", views.group_attendance, name="group_attendance"),
    path("groups/<int:group_id>/serving/", views.serving_schedule, name="serving_schedule"),
    path("surveys/<int:survey_id>/respond/", views.survey_respond, name="survey_respond"),
    path("groups/<int:group_id>/lessons/", views.group_lessons, name="group_lessons"),
    path("groups/<int:group_id>/set-list/", views.group_set_list, name="group_set_list"),
    path("groups/<int:group_id>/shoutouts/", views.group_shoutouts, name="group_shoutouts"),
]
