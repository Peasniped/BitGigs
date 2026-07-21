from django.urls import path

from . import views

app_name = "calendar_sync"

urlpatterns = [
    path("busy/", views.BusyView.as_view(), name="busy"),
]
