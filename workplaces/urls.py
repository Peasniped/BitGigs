from django.urls import path
from . import views

app_name = "workplaces"

urlpatterns = [
    path("", views.WorkplaceListView.as_view(), name="workplace-list"),
    path("new/", views.WorkplaceCreateView.as_view(), name="workplace-create"),
    path("<int:pk>/", views.WorkplaceDetailView.as_view(), name="workplace-detail"),
    path("<int:pk>/edit/", views.WorkplaceUpdateView.as_view(), name="workplace-update"),
    path("<int:pk>/customize/", views.WorkplaceCustomizeView.as_view(), name="workplace-customize"),
    path(
        "<int:pk>/delete/",
        views.WorkplaceDeleteView.as_view(),
        name="workplace-delete",
    ),
]
