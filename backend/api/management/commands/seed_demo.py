from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from api import models as m
from api import services as svc

SUPPLIERS = [("Supplier A", "Power banks, cases, protectors"), ("Supplier B", "Audio"), ("Supplier C", "Cables")]
# name, category, price, cost, target, supplier
PRODUCTS = [
    ("Earbuds", "Audio", 24, 14, 80, "Supplier B"),
    ("Phone case", "Accessories", 9, 4, 100, "Supplier A"),
    ("Power bank", "Power", 28, 17, 60, "Supplier A"),
    ("USB-C cable", "Cables", 6, 2.5, 80, "Supplier C"),
    ("Screen protector", "Accessories", 7, 2, 80, "Supplier A"),
]
# product, received, left, age in days
BATCHES = [("Earbuds", 60, 22, 18), ("Phone case", 80, 30, 74), ("Phone case", 50, 34, 12),
           ("Power bank", 40, 14, 25), ("USB-C cable", 60, 38, 96), ("Screen protector", 70, 51, 61)]
# customer, product, qty, amount, status, days ago
SALES = [("Tendai", "Earbuds", 3, 84, "Paid", 0), ("Walk-in", "Phone case", 3, 32, "Paid", 0),
         ("Chipo", "Power bank", 5, 146, "Pending", 1), ("Farai", "Earbuds", 2, 61, "Paid", 2),
         ("Walk-in", "USB-C cable", 3, 19, "Paid", 2), ("Tendai", "Earbuds", 4, 92, "Paid", 4),
         ("Rudo", "Power bank", 2, 58, "Pending", 5), ("Walk-in", "Screen protector", 4, 27, "Paid", 6)]
EXPENSES = [("Salaries", 1900), ("Rent", 1800), ("Transport", 900), ("Marketing", 600)]


class Command(BaseCommand):
    help = "Load sample business data for an account (created if missing)."

    def add_arguments(self, parser):
        parser.add_argument("email")

    @transaction.atomic
    def handle(self, *args, email, **opts):
        user, created = get_user_model().objects.get_or_create(username=email.lower(), defaults={"email": email.lower()})
        if created:
            user.set_unusable_password()
            user.save()
        if m.Product.objects.filter(owner=user).exists():
            self.stdout.write("Account already has data; nothing to do.")
            return
        today = timezone.localdate()
        sup = {n: m.Supplier.objects.create(owner=user, name=n, supplies=s) for n, s in SUPPLIERS}
        prod = {}
        for n, cat, price, cost, target, s in PRODUCTS:
            prod[n] = m.Product.objects.create(owner=user, name=n, category=cat, price=Decimal(str(price)),
                                               cost=Decimal(str(cost)), target_stock=target, supplier=sup[s])
        for n, got, left, age in BATCHES:
            p = prod[n]
            day = today - timedelta(days=age)
            batch = m.StockBatch.objects.create(owner=user, product=p, supplier=p.supplier, quantity_received=got,
                                                quantity_left=left, unit_cost=p.cost, received_on=day)
            svc.log_movement(user, product=p, kind=m.StockMovement.RECEIVE, quantity=got, batch=batch, unit_cost=p.cost, on=day)
            if got > left:
                svc.log_movement(user, product=p, kind=m.StockMovement.SALE, quantity=left - got, batch=batch,
                                 unit_cost=p.cost, on=day, note="Seed history")
        for who, n, qty, amt, status, ago in SALES:
            svc.record_sale(user, amount=Decimal(amt), customer_name=who, status=status,
                            product=prod[n], quantity=qty, on=today - timedelta(days=ago))
        for cat, amt in EXPENSES:
            m.Expense.objects.create(owner=user, category=cat, amount=Decimal(amt))
        self.stdout.write(self.style.SUCCESS(f"Sample data loaded for {user.email}."))
