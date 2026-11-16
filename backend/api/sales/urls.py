from django.urls import path

from .. import views as v

urlpatterns = [
    path("sales/", v.sales),
    path("sales/<int:pk>/", v.sale_detail),
    path("expenses/", v.expenses),
]
