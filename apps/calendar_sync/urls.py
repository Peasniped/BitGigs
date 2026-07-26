from django.urls import path

from . import views

app_name = "calendar_sync"

urlpatterns = [
    path("busy/", views.BusyView.as_view(), name="busy"),
    path("invites/send/", views.SendInvitesView.as_view(), name="send-invites"),
    # Settings → Calendar tab endpoints
    path("subscriptions/save/", views.CalendarSubscriptionSaveView.as_view(),
         name="subscription-save"),
    path("subscriptions/delete/", views.CalendarSubscriptionDeleteView.as_view(),
         name="subscription-delete"),
    path("subscriptions/test/", views.CalendarSubscriptionTestView.as_view(),
         name="subscription-test"),
    path("subscriptions/check/", views.CalendarSubscriptionCheckView.as_view(),
         name="subscription-check"),
    path("invites/settings/", views.CalendarInviteSettingsSaveView.as_view(),
         name="invite-settings"),
    path("invites/test/", views.InviteTestView.as_view(), name="invite-test"),
    path("invites/sync/", views.InviteSyncView.as_view(), name="invite-sync"),
    path("invites/shift/<int:pk>/", views.ShiftInviteView.as_view(), name="invite-shift"),
]
