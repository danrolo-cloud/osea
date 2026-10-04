from django.urls import path

from . import manage_views, views

app_name = "matches"

urlpatterns = [
    # Teacher coaches
    path("coach/matches/", views.my_matches, name="my_matches"),
    path("coach/matches/<int:pk>/", views.coach_match, name="coach_match"),
    path("coach/matches/<int:pk>/propose/", views.propose, name="propose"),
    path("coach/matches/<int:pk>/proposals/<int:proposal_pk>/accept/", views.accept, name="accept"),
    path("coach/matches/<int:pk>/proposals/<int:proposal_pk>/decline/", views.decline, name="decline"),
    path("coach/matches/<int:pk>/proposals/<int:proposal_pk>/withdraw/", views.withdraw, name="withdraw"),
    # OSEA administrators
    path("manage/competitions/<int:competition_pk>/stages/new/", manage_views.stage_form, name="stage_create"),
    path("manage/competitions/<int:competition_pk>/stages/<int:pk>/edit/", manage_views.stage_form, name="stage_edit"),
    path("manage/stages/<int:pk>/", manage_views.stage_detail, name="stage"),
    path("manage/stages/<int:pk>/generate/", manage_views.stage_generate, name="stage_generate"),
    path("manage/stages/<int:pk>/clear/", manage_views.stage_clear, name="stage_clear"),
    path("manage/stages/<int:pk>/delete/", manage_views.stage_delete, name="stage_delete"),
    path("manage/stages/<int:stage_pk>/matches/new/", manage_views.match_form, name="match_create"),
    path("manage/stages/<int:stage_pk>/matches/<int:pk>/", manage_views.match_form, name="match_edit"),
    path("manage/matches/<int:pk>/cancel/", manage_views.match_cancel, name="match_cancel"),
    path("manage/matches/<int:pk>/restore/", manage_views.match_restore, name="match_restore"),
]
