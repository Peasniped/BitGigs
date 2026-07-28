from django.urls import path

from . import views

app_name = "scheduler"

urlpatterns = [
    # Session-gated, POSTed to from Settings → Jobs.
    path("jobs/<int:pk>/toggle/", views.ScheduledJobToggleView.as_view(), name="job-toggle"),
    path("tasks/clear/", views.TaskQueueClearView.as_view(), name="tasks-clear"),
    path("tasks/retry/", views.TaskRetryView.as_view(), name="task-retry"),
    # Polled by the tab for live queue/heartbeat updates.
    path("status/", views.SchedulerStatusView.as_view(), name="status"),
]
