from django.urls import path

from . import views, views_app as a

urlpatterns = [
    path("", views.landing, name="landing"),
    path("captcha/verify/", views.verify_human, name="verify_human"),
    path("enter/", views.enter_anonymously, name="enter"),
    path("chat/", views.chat, name="chat"),
    path("leave/", views.leave, name="leave"),
    path("api/online/", views.online_count, name="online_count"),
    # signed-in users
    path("auth/google/", a.google_login, name="google_login"),
    path("dashboard/", a.dashboard, name="dashboard"),
    path("friends/", a.friends_page, name="friends"),
    path("messages/", a.messages_page, name="messages"),
    path("profile/", a.profile_page, name="profile"),
    path("profile/save/", a.profile_save, name="profile_save"),
    path("u/<str:other>/", a.user_profile, name="user_profile"),
    path("avatar/<str:uid>/", a.avatar, name="avatar"),
    path("api/users/search/", a.api_search),
    path("api/friends/", a.api_friends),
    path("api/friends/request/", a.api_friend_request),
    path("api/friends/respond/", a.api_friend_respond),
    path("api/friends/remove/", a.api_friend_remove),
    path("api/block/", a.api_block),
    path("api/messages/<str:other>/", a.api_history),
    path("api/messages/<str:other>/delete/", a.api_delete_conversation),
    path("api/report/", a.api_report),
    path("api/notifications/", a.api_notifications),
    path("api/notifications/read/", a.api_notifications_read),
]
