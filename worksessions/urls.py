from django.urls import path
from . import views

app_name = "worksessions"

urlpatterns = [
    path("new/", views.SessionCreateView.as_view(), name="session-create"),
    path("<int:pk>/edit/", views.SessionUpdateView.as_view(), name="session-update"),
    path("<int:pk>/delete/", views.SessionDeleteView.as_view(), name="session-delete"),
    path(
        "daily/<int:year>/<int:month>/<int:day>/",
        views.DailyOverviewView.as_view(),
        name="daily-overview",
    ),
    path(
        "monthly/<int:year>/<int:month>/",
        views.MonthlyOverviewView.as_view(),
        name="monthly-overview",
    ),
]
