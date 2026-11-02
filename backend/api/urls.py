from django.urls import path

from . import views as v

urlpatterns = [
    path("auth/register/", v.register),
    path("auth/login/", v.login),
    path("auth/request-link/", v.request_link),
    path("auth/verify/", v.verify_link),
    path("auth/logout/", v.logout),
    path("me/", v.me),
    path("products/", v.products),
    path("products/<int:pk>/", v.product_detail),
    path("suppliers/", v.suppliers),
    path("customers/", v.customers),
    path("sales/", v.sales),
    path("sales/<int:pk>/", v.sale_detail),
    path("expenses/", v.expenses),
    path("stock/", v.stock),
    path("batches/", v.batches),
    path("purchases/", v.purchases),
    path("purchases/<int:pk>/receive/", v.purchase_receive),
    path("receive/", v.receive),
    path("dashboard/", v.dashboard),
    path("reports/", v.reports),
    path("insights/", v.insights),
]
