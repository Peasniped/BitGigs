from django.urls import path
from . import views

app_name = "payroll"

urlpatterns = [
    path("periods/", views.PayrollPeriodListView.as_view(), name="period-list"),
    path(
        "periods/generate/",
        views.PayrollPeriodGenerateView.as_view(),
        name="period-generate",
    ),
    path(
        "periods/<int:pk>/",
        views.PayrollPeriodDetailView.as_view(),
        name="period-detail",
    ),
    path(
        "periods/<int:period_pk>/reorder/",
        views.PayslipLineReorderView.as_view(),
        name="payslip-reorder",
    ),
    path(
        "periods/<int:period_pk>/add-line/",
        views.PayslipLineAddView.as_view(),
        name="payslip-add-line",
    ),
    path(
        "periods/<int:period_pk>/edit-line/<int:line_pk>/",
        views.PayslipLineEditView.as_view(),
        name="payslip-edit-line",
    ),
    path(
        "periods/<int:period_pk>/delete-line/<int:line_pk>/",
        views.PayslipLineDeleteView.as_view(),
        name="payslip-delete-line",
    ),
    path(
        "periods/<int:period_pk>/recalculate/",
        views.PayslipRecalculateView.as_view(),
        name="payslip-recalculate",
    ),
    path(
        "periods/<int:period_pk>/tax-pull-day/",
        views.TaxPullDayUpdateView.as_view(),
        name="tax-pull-day-update",
    ),
    path("commuting/", views.CommutingListView.as_view(), name="commuting-list"),
    path(
        "commuting/update/",
        views.CommutingAutoUpdateView.as_view(),
        name="commuting-update",
    ),
    path("vacation/", views.VacationOverviewView.as_view(), name="vacation-overview"),
    path(
        "vacation/update/",
        views.VacationUpdateView.as_view(),
        name="vacation-update",
    ),
]
