from django.urls import path
from . import views

app_name = "shifts"

urlpatterns = [
    path("new/", views.ShiftCreateView.as_view(), name="shift-create"),
    path("<int:pk>/edit/", views.ShiftUpdateView.as_view(), name="shift-update"),
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
