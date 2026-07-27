from django.urls import path

from . import views

app_name = "scheduler"

urlpatterns = [
    # Session-gated, POSTed to from Settings → Jobs.
    path("jobs/<int:pk>/toggle/", views.ScheduledJobToggleView.as_view(), name="job-toggle"),
]
