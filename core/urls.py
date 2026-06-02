from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("setup/", views.SetupWizardView.as_view(), name="setup"),
    path("tax-profiles/", views.TaxProfileListView.as_view(), name="taxprofile-list"),
    path(
        "tax-profiles/new/",
        views.TaxProfileCreateView.as_view(),
        name="taxprofile-create",
    ),
    path(
        "tax-profiles/<int:pk>/edit/",
        views.TaxProfileUpdateView.as_view(),
        name="taxprofile-update",
    ),
    path(
        "tax-profiles/<int:pk>/delete/",
        views.TaxProfileDeleteView.as_view(),
        name="taxprofile-delete",
    ),
    path("settings/", views.UserSettingsView.as_view(), name="settings"),
    path("dashboard/stats/", views.DashboardStatsAPIView.as_view(), name="dashboard-stats"),
    path("logo/", views.LogoView.as_view(), name="logo"),
]
