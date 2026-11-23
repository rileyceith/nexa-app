from django.urls import path

from .. import views as v

urlpatterns = [
    path("dashboard/", v.dashboard),
    path("reports/", v.reports),
    path("settings/", v.app_settings),
    path("settings/series/", v.goal_series),
    path("settings/verify-email/", v.verify_settings_email),
    path("account/confirm/", v.request_account_confirmation),
    path("account/export/", v.account_export),
    path("account/delete/", v.account_delete),
    path("account/reset-data/", v.reset_business_data),
]
