"""BitGigs URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Django's auth URLs come first on purpose: they claim /accounts/login/ and
    # /accounts/logout/, so the native password login stays the primary flow and
    # allauth only supplies what Django doesn't define — the OIDC routes under
    # /accounts/oidc/…  (allauth's own signup page is closed by NoSignupAccountAdapter.)
    # Our LoginView first — it knows whether password sign-in is even available.
    path("accounts/login/", core_views.BitGigsLoginView.as_view(), name="login"),
    # Same reasoning for the reset flow: ours knows whether mail is configured
    # at all, rate-limits the public form, and sends From the operator's address.
    path("accounts/password_reset/",
         core_views.BitGigsPasswordResetView.as_view(), name="password_reset"),
    path("accounts/password_reset/done/",
         core_views.BitGigsPasswordResetDoneView.as_view(), name="password_reset_done"),
    path("accounts/reset/<uidb64>/<token>/",
         core_views.BitGigsPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("accounts/reset/done/",
         core_views.BitGigsPasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/", include("allauth.urls")),
    path("", include("core.urls")),
    path("workplaces/", include("workplaces.urls")),
    path("shifts/", include("shifts.urls")),
    path("payroll/", include("payroll.urls")),
    path("calendar/", include("calendar_view.urls")),
    path("data/", include("data_io.urls")),
    path("analytics/", include("analytics.urls")),
    path("help/", include("help.urls")),
    path("api/", include("api.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
