from django.urls import path
from . import views

app_name = "calendar_view"

urlpatterns = [
    path("month/", views.MonthCalendarView.as_view(), name="month"),
    path("payroll/", views.PayrollPeriodCalendarView.as_view(), name="payroll-period"),
    path("planning/", views.PlanningCalendarView.as_view(), name="planning"),
    path("planning/shifts/", views.PlannedShiftAPIView.as_view(), name="planned-shift-api"),
    path("planning/shifts/<int:pk>/", views.PlannedShiftUpdateAPIView.as_view(), name="planned-shift-update-api"),
    path("planning/shifts/bulk-delete/", views.BulkDeleteShiftsView.as_view(), name="bulk-delete-shifts"),
    path("planning/sessions/<int:pk>/", views.WorkSessionUpdateAPIView.as_view(), name="session-update-api"),
    path("planning/default-shift/<int:pk>/", views.DefaultShiftAPIView.as_view(), name="default-shift-api"),
    path("planning/check-overlaps/", views.CheckOverlapsAPIView.as_view(), name="check-overlaps"),
    path("planning/approve/<int:workplace_id>/", views.ApproveShiftsView.as_view(), name="approve-shifts"),
    path("planning/approve-bulk/", views.BulkApproveShiftsView.as_view(), name="bulk-approve-shifts"),
]
