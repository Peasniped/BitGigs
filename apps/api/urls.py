from django.urls import path
from . import views

app_name = "api"

urlpatterns = [
    # Key-authenticated JSON endpoints (documented in registry.py).
    path("v1/ping/", views.PingView.as_view(), name="v1-ping"),
    path("v1/income/", views.IncomeView.as_view(), name="v1-income"),
    # Key management — normal session-gated pages, POSTed to from Settings → API.
    path("keys/create/", views.ApiKeyCreateView.as_view(), name="key-create"),
    path("keys/<int:pk>/revoke/", views.ApiKeyRevokeView.as_view(), name="key-revoke"),
    path("keys/<int:pk>/delete/", views.ApiKeyDeleteView.as_view(), name="key-delete"),
]
