"""BitGigs URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("core.urls")),
    path("workplaces/", include("workplaces.urls")),
    path("shifts/", include("shifts.urls")),
    path("payroll/", include("payroll.urls")),
    path("calendar/", include("calendar_view.urls")),
    path("data/", include("data_io.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
