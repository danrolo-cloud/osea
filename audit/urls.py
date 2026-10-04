from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("manage/activity/", views.activity_log, name="activity_log"),
]
