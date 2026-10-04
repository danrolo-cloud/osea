from django.urls import path

from . import manage_views, views

app_name = "competitions"

urlpatterns = [
    # Public
    path("competitions/", views.competition_list, name="list"),
    path("competitions/<int:pk>/", views.competition_detail, name="detail"),
    # Teacher coaches
    path("competitions/<int:pk>/register/", views.register, name="register"),
    path("coach/registrations/<int:pk>/", views.registration_detail, name="registration"),
    path("coach/registrations/<int:pk>/add-player/", views.add_player, name="add_player"),
    path("coach/registrations/<int:pk>/remove-player/<int:entry_pk>/", views.remove_player, name="remove_player"),
    path("coach/registrations/<int:pk>/rename/", views.rename, name="rename"),
    path("coach/registrations/<int:pk>/submit/", views.submit, name="submit"),
    path("coach/registrations/<int:pk>/reopen/", views.unsubmit, name="unsubmit"),
    path("coach/registrations/<int:pk>/withdraw/", views.withdraw, name="withdraw"),
    path("coach/registrations/<int:pk>/roster-change/", views.request_change, name="request_change"),
    path("coach/schools/<int:school_pk>/students/", views.student_list, name="student_list"),
    path("coach/schools/<int:school_pk>/students/new/", views.student_form, name="student_create"),
    path("coach/schools/<int:school_pk>/students/<int:pk>/", views.student_form, name="student_edit"),
    # OSEA administrators
    path("manage/games/", manage_views.game_list, name="game_list"),
    path("manage/games/new/", manage_views.game_form, name="game_create"),
    path("manage/games/<int:pk>/", manage_views.game_form, name="game_edit"),
    path("manage/competitions/", manage_views.competition_list, name="manage_list"),
    path("manage/competitions/new/", manage_views.competition_form, name="competition_create"),
    path("manage/competitions/<int:pk>/", manage_views.competition_detail, name="manage_competition"),
    path("manage/competitions/<int:pk>/settings/", manage_views.competition_form, name="competition_edit"),
    path("manage/competitions/<int:pk>/divisions/assign/", manage_views.assign_divisions, name="assign_divisions"),
    path("manage/competitions/<int:competition_pk>/divisions/new/", manage_views.division_form, name="division_create"),
    path(
        "manage/competitions/<int:competition_pk>/divisions/<int:pk>/", manage_views.division_form, name="division_edit"
    ),
    path(
        "manage/competitions/<int:competition_pk>/divisions/<int:pk>/delete/",
        manage_views.division_delete,
        name="division_delete",
    ),
    path("manage/competitions/<int:pk>/export/teams.csv", manage_views.export_registrations, name="export_teams"),
    path("manage/competitions/<int:pk>/export/rosters.csv", manage_views.export_rosters, name="export_rosters"),
    path(
        "manage/competitions/<int:competition_pk>/announcements/new/",
        manage_views.announcement_form,
        name="announcement_create",
    ),
    path(
        "manage/competitions/<int:competition_pk>/announcements/<int:pk>/",
        manage_views.announcement_form,
        name="announcement_edit",
    ),
    path(
        "manage/competitions/<int:competition_pk>/announcements/<int:pk>/delete/",
        manage_views.announcement_delete,
        name="announcement_delete",
    ),
    path("manage/registrations/<int:pk>/", manage_views.registration_review, name="manage_registration"),
    path("manage/registrations/<int:pk>/add-player/", manage_views.admin_add_player, name="admin_add_player"),
    path(
        "manage/registrations/<int:pk>/remove-player/<int:entry_pk>/",
        manage_views.admin_remove_player,
        name="admin_remove_player",
    ),
    path("manage/registrations/<int:pk>/rename/", manage_views.admin_rename, name="admin_rename"),
    path("manage/roster-changes/<int:pk>/", manage_views.roster_change_decide, name="roster_change_decide"),
]
