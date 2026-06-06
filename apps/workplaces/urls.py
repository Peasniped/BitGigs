from django.urls import path
from . import views

app_name = "workplaces"

urlpatterns = [
    path("", views.WorkplaceListView.as_view(), name="workplace-list"),
    path("new/", views.WorkplaceCreateView.as_view(), name="workplace-create"),
    path("<slug:slug>/", views.WorkplaceDetailView.as_view(), name="workplace-detail"),
    path("<slug:slug>/edit/", views.WorkplaceUpdateView.as_view(), name="workplace-update"),
    path("<slug:slug>/delete/", views.WorkplaceDeleteView.as_view(), name="workplace-delete"),
    path("<slug:slug>/customize/", views.WorkplaceCustomizeView.as_view(), name="workplace-customize"),

    # Contract management
    path("<slug:slug>/contracts/add/", views.ContractCreateView.as_view(), name="contract-create"),
    path("<slug:slug>/contracts/<int:cpk>/edit/", views.ContractUpdateView.as_view(), name="contract-update"),
    path("<slug:slug>/contracts/<int:cpk>/delete/", views.ContractDeleteView.as_view(), name="contract-delete"),

    # ContractTermSet management
    path("<slug:slug>/contracts/<int:cpk>/terms/add/", views.ContractTermSetCreateView.as_view(), name="termset-create"),
    path("<slug:slug>/contracts/<int:cpk>/terms/<int:tpk>/edit/", views.ContractTermSetUpdateView.as_view(), name="termset-update"),
    path("<slug:slug>/contracts/<int:cpk>/terms/<int:tpk>/delete/", views.ContractTermSetDeleteView.as_view(), name="termset-delete"),
]
