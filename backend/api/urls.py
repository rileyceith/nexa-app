from django.urls import include, path

from . import views

urlpatterns = [
    path("health/live/", views.health_live),
    path("health/ready/", views.health_ready),
    path("", include("api.auth.urls")),
    path("", include("api.catalog.urls")),
    path("", include("api.sales.urls")),
    path("", include("api.inventory.urls")),
    path("", include("api.reporting.urls")),
    path("", include("api.insights.urls")),
]
