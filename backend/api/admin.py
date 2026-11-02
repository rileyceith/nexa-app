from django.contrib import admin

from . import models

for m in (
    models.Supplier, models.Product, models.StockBatch, models.Customer,
    models.Sale, models.Expense, models.Purchase,
):
    admin.site.register(m)
