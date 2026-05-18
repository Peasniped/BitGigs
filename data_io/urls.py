from django.urls import path
from . import views

app_name = "data_io"

urlpatterns = [
    path("", views.DataIOPageView.as_view(), name="main"),
    path("export/", views.ExportView.as_view(), name="export"),
    path("import/", views.ImportUploadView.as_view(), name="import-upload"),
    path("import/confirm/", views.ImportConfirmView.as_view(), name="import-confirm"),
]
