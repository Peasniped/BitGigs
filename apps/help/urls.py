from django.urls import path

from . import views

app_name = "help"

urlpatterns = [
    path("", views.HelpManualView.as_view(), name="manual"),
    path("search-index.json", views.HelpSearchIndexView.as_view(), name="search-index"),
    path("context/", views.HelpContextView.as_view(), name="context"),
    path("fragment/<slug:slug>/", views.HelpArticleFragmentView.as_view(), name="fragment"),
    # Editor (staff only)
    path("manage/", views.HelpArticleManageView.as_view(), name="manage"),
    path("manage/new/", views.HelpArticleEditView.as_view(), name="create"),
    path("manage/preview/", views.HelpPreviewView.as_view(), name="preview"),
    path("manage/<slug:slug>/edit/", views.HelpArticleEditView.as_view(), name="edit"),
    path("manage/<slug:slug>/delete/", views.HelpArticleDeleteView.as_view(), name="delete"),
    path("manage/<slug:slug>/revisions/", views.HelpArticleRevisionsView.as_view(), name="revisions"),
    path(
        "manage/<slug:slug>/revisions/<int:pk>/revert/",
        views.HelpArticleRevertView.as_view(),
        name="revert",
    ),
    # Full-page article — kept last so it can't shadow the routes above.
    path("<slug:slug>/", views.HelpManualView.as_view(), name="manual-article"),
]
