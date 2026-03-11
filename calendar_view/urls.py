from django.urls import path
from . import views

app_name = "calendar_view"

urlpatterns = [
    path("month/", views.MonthCalendarView.as_view(), name="month"),
    path("payroll/", views.PayrollPeriodCalendarView.as_view(), name="payroll-period"),
]
