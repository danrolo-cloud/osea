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
    path("coach/matches/<int:pk>/result/", views.submit_result, name="submit_result"),
    path("coach/matches/<int:pk>/results/<int:submission_pk>/confirm/", views.confirm_result, name="confirm_result"),
    path("coach/matches/<int:pk>/results/<int:submission_pk>/dispute/", views.dispute_result, name="dispute_result"),
    # OSEA administrators
    path("manage/results/", manage_views.results_queue, name="results_queue"),
    path("manage/matches/<int:pk>/result/", manage_views.admin_result, name="admin_result"),
    path("manage/stages/<int:pk>/swiss-next-round/", manage_views.swiss_next_round, name="swiss_next_round"),
    path("manage/stages/<int:pk>/tiebreak/", manage_views.tiebreak, name="tiebreak"),
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
