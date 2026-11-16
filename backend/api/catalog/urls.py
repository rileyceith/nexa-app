from django.urls import path

from .. import views as v

urlpatterns = [
    path("products/", v.products),
    path("products/<int:pk>/", v.product_detail),
    path("images/<str:key>/", v.product_image, name="product_image"),
    path("suppliers/", v.suppliers),
    path("customers/", v.customers),
]
