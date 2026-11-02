from django.conf import settings
from django.db import models
from django.utils import timezone

Owner = settings.AUTH_USER_MODEL


class MagicLink(models.Model):
    email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class TermsAcceptance(models.Model):
    user = models.OneToOneField(Owner, on_delete=models.CASCADE, related_name="terms")
    accepted_at = models.DateTimeField(auto_now_add=True)
    version = models.CharField(max_length=20, default="1")


class LoginAttempt(models.Model):
    username = models.CharField(max_length=150, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ApiToken(models.Model):
    user = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="api_tokens")
    key_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)


class Supplier(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="suppliers")
    name = models.CharField(max_length=120)
    supplies = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_supplier_per_owner")]

    def __str__(self):
        return self.name


class Product(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="products")
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=80, default="General")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    target_stock = models.PositiveIntegerField(default=60)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_product_per_owner")]

    def __str__(self):
        return self.name


class StockBatch(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="batches")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="batches")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL)
    quantity_received = models.PositiveIntegerField()
    quantity_left = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    received_on = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["received_on", "id"]

    @property
    def age_days(self):
        return (timezone.localdate() - self.received_on).days


class Customer(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=120)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_customer_per_owner")]

    def __str__(self):
        return self.name


class Sale(models.Model):
    PAID = "Paid"
    PENDING = "Pending"
    STATUSES = [(PAID, PAID), (PENDING, PENDING)]

    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="sales")
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name="sales")
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="sales")
    quantity = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    cogs = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUSES, default=PAID)
    date = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["-date", "-id"]


class Expense(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="expenses")
    category = models.CharField(max_length=80, default="General")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["-date", "-id"]


class Purchase(models.Model):
    ORDERED = "Ordered"
    DELIVERED = "Delivered"
    STATUSES = [(ORDERED, ORDERED), (DELIVERED, DELIVERED)]

    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="purchases")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="purchases")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL)
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=STATUSES, default=ORDERED)
    ordered_on = models.DateField(default=timezone.localdate)
    delivered_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-ordered_on", "-id"]

    @property
    def total(self):
        return self.quantity * self.unit_cost
