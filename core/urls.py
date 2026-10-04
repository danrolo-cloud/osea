from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("manage/", views.admin_dashboard, name="admin_dashboard"),
    path("coach/", views.coach_dashboard, name="coach_dashboard"),
    path("manage/style-guide/", views.style_guide, name="style_guide"),
    path("healthz", views.healthz, name="healthz"),
]
