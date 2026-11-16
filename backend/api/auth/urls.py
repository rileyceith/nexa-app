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
]
