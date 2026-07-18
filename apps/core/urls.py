from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("onboarding/", views.OnboardingRootView.as_view(), name="onboarding"),
    path("onboarding/account/", views.OnboardingAccountView.as_view(), name="onboarding-account"),
    path("onboarding/account/method/", views.OnboardingAccountMethodView.as_view(), name="onboarding-account-method"),
    path("onboarding/account/email/", views.OnboardingAccountEmailView.as_view(), name="onboarding-account-email"),
    path("onboarding/account/confirm/", views.OnboardingAccountConfirmView.as_view(), name="onboarding-account-confirm"),
    path("onboarding/tax/", views.OnboardingTaxView.as_view(), name="onboarding-tax"),
    path("onboarding/workplace/", views.OnboardingWorkplaceView.as_view(), name="onboarding-workplace"),
    path("onboarding/terms/", views.OnboardingTermsView.as_view(), name="onboarding-terms"),
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
    path("settings/sign-in/", views.PasswordSignInView.as_view(), name="password-signin"),
    path("settings/sign-in/link/", views.SSOLinkConfirmView.as_view(), name="sso-link-confirm"),
    # Set this as the application's Launch URL at the identity provider.
    path("sso/launch/", views.SSOLaunchView.as_view(), name="sso-launch"),
    path("sso/idp-logout/", views.SSOEndIdPSessionView.as_view(), name="sso-idp-logout"),
    path("dashboard/stats/", views.DashboardStatsAPIView.as_view(), name="dashboard-stats"),
]
