from django.urls import path

from .. import views as v

urlpatterns = [
    path("insights/", v.insights),
    path("assistant/chat/", v.assistant_chat),
    path("assistant/analyze/", v.assistant_analyze),
]
