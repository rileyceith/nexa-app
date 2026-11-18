from django.urls import path

from .. import views as v

urlpatterns = [
    path("auth/register/", v.register),
    path("auth/login/", v.login),
    path("auth/request-link/", v.request_link),
    path("auth/verify/", v.verify_link),
    path("auth/password-reset/", v.request_password_reset),
    path("auth/password-reset/confirm/", v.reset_password),
    path("auth/logout/", v.logout),
    path("me/", v.me),
    path("account/profile/", v.account_profile),
    path("account/sessions/", v.account_sessions),
    path("account/security/request/", v.account_security_request),
    path("account/security/confirm/", v.account_security_confirm),
    path("team/", v.team_overview),
    path("team/sharing/", v.team_sharing_settings),
    path("team/invitations/", v.team_invite),
    path("team/invitations/preview/", v.team_invitation_preview),
    path("team/invitations/accept/", v.team_invitation_accept),
    path("team/invitations/<int:pk>/", v.team_invitation_detail),
    path("team/members/<int:pk>/", v.team_member_detail),
]
