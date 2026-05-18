from django.urls import path
from . import views

app_name = "workplaces"

urlpatterns = [
    path("", views.WorkplaceListView.as_view(), name="workplace-list"),
    path("new/", views.WorkplaceCreateView.as_view(), name="workplace-create"),
    path("<slug:slug>/", views.WorkplaceDetailView.as_view(), name="workplace-detail"),
    path("<slug:slug>/edit/", views.WorkplaceUpdateView.as_view(), name="workplace-update"),
    path("<slug:slug>/customize/", views.WorkplaceCustomizeView.as_view(), name="workplace-customize"),
    path("<slug:slug>/change-rate/", views.PayRateCreateView.as_view(), name="payrate-create"),
    path("<slug:slug>/rate-history/", views.PayRateHistoryView.as_view(), name="payrate-history"),
    path(
        "<slug:slug>/delete/",
        views.WorkplaceDeleteView.as_view(),
        name="workplace-delete",
    ),
]
