from django.urls import path

from . import manage_views, views

app_name = "schools"

urlpatterns = [
    # Teacher coaches
    path("coach/request-school/", views.request_school, name="request_school"),
    path("coach/schools/<int:pk>/", views.my_school, name="my_school"),
    # OSEA administrators
    path("manage/coach-requests/", manage_views.access_requests, name="access_requests"),
    path("manage/coach-requests/<int:pk>/", manage_views.access_request_detail, name="access_request"),
    path("manage/coach-access/<int:pk>/remove/", manage_views.access_revoke, name="access_revoke"),
    path("manage/coaches/", manage_views.coach_list, name="coach_list"),
    path("manage/coaches/<int:pk>/", manage_views.coach_detail, name="coach_detail"),
    path("manage/coaches/<int:pk>/active/", manage_views.coach_set_active, name="coach_set_active"),
    path("manage/schools/", manage_views.school_list, name="school_list"),
    path("manage/schools/new/", manage_views.school_create, name="school_create"),
    path("manage/schools/<int:pk>/", manage_views.school_detail, name="school_detail"),
    path("manage/schools/<int:pk>/edit/", manage_views.school_edit, name="school_edit"),
    path("manage/schools/<int:pk>/membership/<int:year_pk>/", manage_views.membership_edit, name="membership_edit"),
    path("manage/boards/", manage_views.board_list, name="board_list"),
    path("manage/boards/new/", manage_views.board_form, name="board_create"),
    path("manage/boards/<int:pk>/", manage_views.board_form, name="board_edit"),
    path("manage/school-years/", manage_views.year_list, name="year_list"),
    path("manage/school-years/new/", manage_views.year_form, name="year_create"),
    path("manage/school-years/<int:pk>/", manage_views.year_form, name="year_edit"),
    path("manage/exports/", manage_views.exports, name="exports"),
    path("manage/exports/<slug:kind>.csv", manage_views.export_csv, name="export_csv"),
]
