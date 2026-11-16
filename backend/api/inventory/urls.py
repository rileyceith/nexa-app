from django.urls import path

from .. import views as v

urlpatterns = [
    path("stock/", v.stock),
    path("batches/", v.batches),
    path("purchases/", v.purchases),
    path("purchases/<int:pk>/receive/", v.purchase_receive),
    path("receive/", v.receive),
]
