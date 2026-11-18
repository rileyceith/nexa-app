from decimal import Decimal
from hashlib import sha256
import unicodedata

from django.conf import settings
from django.db import models
from django.utils import timezone

Owner = settings.AUTH_USER_MODEL

TEAM_PERMISSION_SCOPES = (
    "dashboard", "sales", "inventory", "customers", "expenses", "reports", "insights", "settings",
)


def default_team_permissions():
    return {scope: {"view": False, "edit": False} for scope in TEAM_PERMISSION_SCOPES}


def business_name_fingerprint(name):
    normalized = " ".join(unicodedata.normalize("NFKC", name).split()).casefold()
    return sha256(normalized.encode("utf-8")).hexdigest() if normalized else None


class MagicLink(models.Model):
    email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PasswordResetToken(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="password_reset_tokens")
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
    user_agent = models.CharField(max_length=180, blank=True, default="", db_default="")


class AccountSecurityChallenge(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE)
    session = models.ForeignKey(ApiToken, on_delete=models.CASCADE)
    action = models.CharField(max_length=20)
    target = models.CharField(max_length=254, blank=True)
    email_snapshot = models.EmailField()
    stage = models.CharField(max_length=8, default="current")
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)


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
    image_key = models.CharField(max_length=32, blank=True, default="")
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
        indexes = [models.Index(fields=["owner", "product", "quantity_left"], name="batch_owner_product_idx")]

    @property
    def age_days(self):
        return (timezone.localdate() - self.received_on).days


class StockMovement(models.Model):
    """Append-only audit trail of stock in and out. StockBatch remains the FIFO source of truth."""
    RECEIVE = "receive"
    SALE = "sale"
    KIND_CHOICES = [(RECEIVE, "Receive"), (SALE, "Sale")]

    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="stock_movements")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="movements")
    batch = models.ForeignKey(StockBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="movements")
    sale = models.ForeignKey("Sale", null=True, blank=True, on_delete=models.SET_NULL, related_name="movements")
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    quantity = models.IntegerField()  # positive for stock in, negative for stock out
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    on = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=160, blank=True, default="")

    class Meta:
        ordering = ["on", "id"]
        indexes = [models.Index(fields=["owner", "product", "on"], name="movement_owner_product_idx")]


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
        indexes = [models.Index(fields=["owner", "date"], name="sale_owner_date_idx")]


class Expense(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="expenses")
    category = models.CharField(max_length=80, default="General")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["owner", "date"], name="expense_owner_date_idx")]


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
        indexes = [models.Index(fields=["owner", "status"], name="purchase_owner_status_idx")]

    @property
    def total(self):
        return self.quantity * self.unit_cost


class UserSettings(models.Model):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    PERIODS = [(DAY, "Day"), (WEEK, "Week"), (MONTH, "Month"), (YEAR, "Year")]
    CURRENCY_CHOICES = [
        ("USD", "USD"),
        ("ZWL", "ZWL"),
        ("ZAR", "ZAR"),
        ("EUR", "EUR"),
        ("GBP", "GBP"),
    ]

    owner = models.OneToOneField(Owner, on_delete=models.CASCADE, related_name="preferences")
    revenue_goal = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    goal_period = models.CharField(max_length=10, choices=PERIODS, default=MONTH)
    theme = models.CharField(max_length=5, choices=[("light", "Light"), ("dark", "Dark")], default="light")
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="USD")
    time_zone = models.CharField(max_length=64, default="Africa/Harare")
    business_name = models.CharField(max_length=120, blank=True)
    business_name_fingerprint = models.CharField(max_length=64, unique=True, null=True, editable=False)
    business_logo_key = models.CharField(max_length=32, blank=True, default="")
    business_logo_fingerprint = models.CharField(max_length=64, unique=True, null=True, editable=False)
    business_logo_zoom = models.PositiveSmallIntegerField(default=100)
    business_logo_x = models.SmallIntegerField(default=0)
    business_logo_y = models.SmallIntegerField(default=0)
    business_email = models.EmailField(blank=True)
    business_phone = models.CharField(max_length=32, blank=True)
    low_stock_threshold = models.DecimalField(max_digits=4, decimal_places=3, default=Decimal("0.350"))
    slow_stock_days = models.PositiveSmallIntegerField(default=45)
    reorder_lead_days = models.PositiveSmallIntegerField(default=14)
    safety_stock_days = models.PositiveSmallIntegerField(default=7)
    reorder_target_days = models.PositiveSmallIntegerField(default=30)
    email_verified = models.BooleanField(default=False)
    team_sharing_enabled = models.BooleanField(default=False)
    notify_low_stock = models.BooleanField(default=False)
    notify_slow_stock = models.BooleanField(default=False)
    notify_goal_reached = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is None or "business_name" in update_fields:
            self.business_name_fingerprint = business_name_fingerprint(self.business_name)
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"business_name_fingerprint"}
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(low_stock_threshold__gte=Decimal("0.01"))
                & models.Q(low_stock_threshold__lte=Decimal("1.000")),
                name="settings_low_stock_threshold_range",
            ),
            models.CheckConstraint(condition=models.Q(slow_stock_days__gte=1), name="settings_slow_stock_days_positive"),
            models.CheckConstraint(
                condition=models.Q(business_logo_zoom__gte=100, business_logo_zoom__lte=300),
                name="settings_logo_zoom_range",
            ),
            models.CheckConstraint(
                condition=models.Q(business_logo_x__gte=-100, business_logo_x__lte=100),
                name="settings_logo_x_range",
            ),
            models.CheckConstraint(
                condition=models.Q(business_logo_y__gte=-100, business_logo_y__lte=100),
                name="settings_logo_y_range",
            ),
        ]


class NotificationState(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="notification_states")
    key = models.CharField(max_length=100)
    active = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "key"], name="uniq_notification_state_per_owner"),
        ]


class NotificationDelivery(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="notification_deliveries")
    email = models.EmailField()
    currency = models.CharField(max_length=3)
    time_zone = models.CharField(max_length=64)
    messages = models.JSONField()
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.CharField(max_length=32, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)


class AccountActionToken(models.Model):
    EXPORT = "export"
    DELETE = "delete"
    ACTIONS = [(EXPORT, "Export"), (DELETE, "Delete")]

    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="account_action_tokens")
    action = models.CharField(max_length=8, choices=ACTIONS)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class TeamMembership(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="team_members")
    member = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="business_memberships")
    permissions = models.JSONField(default=default_team_permissions)
    can_manage_members = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "member"], name="uniq_team_membership"),
            models.CheckConstraint(condition=~models.Q(owner=models.F("member")), name="team_member_not_owner"),
        ]


class TeamInvitation(models.Model):
    owner = models.ForeignKey(Owner, on_delete=models.CASCADE, related_name="team_invitations")
    email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    permissions = models.JSONField(default=default_team_permissions)
    can_manage_members = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["owner", "email", "expires_at"], name="team_invite_owner_email_idx")]
