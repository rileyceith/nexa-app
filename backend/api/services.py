import hashlib
import secrets
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from . import models as m

CENTS = Decimal("0.01")
COGS_ESTIMATE_RATIO = Decimal("0.6")  # used when a sale is not linked to a product
SCENARIOS = {"Conservative": Decimal("0.97"), "Expected": Decimal("1.08"), "Optimistic": Decimal("1.2")}


class ServiceError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


# ---------- auth ----------

def send_magic_link(email):
    email = email.strip().lower()
    recent = m.MagicLink.objects.filter(email=email, created_at__gte=timezone.now() - timedelta(hours=1)).count()
    if recent >= 5:
        raise ServiceError("Too many sign-in requests. Try again later.", 429)
    token = secrets.token_urlsafe(32)
    m.MagicLink.objects.create(
        email=email, token_hash=_hash(token),
        expires_at=timezone.now() + timedelta(minutes=settings.MAGIC_LINK_MINUTES),
    )
    send_mail(
        "Your Nexa sign-in link",
        f"Open this link to sign in to Nexa (valid {settings.MAGIC_LINK_MINUTES} minutes):\n\n"
        f"{settings.FRONTEND_URL}?token={token}\n\nIf you did not ask for this, ignore this email.",
        settings.DEFAULT_FROM_EMAIL, [email],
    )


@transaction.atomic
def verify_magic_link(token):
    link = m.MagicLink.objects.select_for_update().filter(token_hash=_hash(token)).first()
    if not link or link.used_at or link.expires_at < timezone.now():
        raise ServiceError("This sign-in link is invalid or has expired.", 400)
    link.used_at = timezone.now()
    link.save(update_fields=["used_at"])
    User = get_user_model()
    user, created = User.objects.get_or_create(username=link.email, defaults={"email": link.email})
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user, issue_token(user)


TERMS_VERSION = "1"


@transaction.atomic
def register(username, password, password2, accepted_terms):
    username = (username or "").strip()
    if not (3 <= len(username) <= 30) or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
        raise ServiceError("Username must be 3 to 30 letters, numbers, dots, dashes or underscores.")
    if password != password2:
        raise ServiceError("The passwords do not match.")
    if accepted_terms is not True:
        raise ServiceError("You must accept the terms and conditions.")
    User = get_user_model()
    if User.objects.filter(username__iexact=username).exists():
        raise ServiceError("That username is taken.", 409)
    try:
        validate_password(password, User(username=username))
    except DjangoValidationError as e:
        raise ServiceError(" ".join(e.messages))
    user = User.objects.create_user(username=username, password=password)
    m.TermsAcceptance.objects.create(user=user, version=TERMS_VERSION)
    return user, issue_token(user)


def login(username, password):
    username = (username or "").strip()
    since = timezone.now() - timedelta(minutes=15)
    if m.LoginAttempt.objects.filter(username__iexact=username, created_at__gte=since).count() >= 5:
        raise ServiceError("Too many failed attempts. Try again in 15 minutes.", 429)
    account = get_user_model().objects.filter(username__iexact=username).first()
    user = authenticate(username=account.username if account else username, password=password or "")
    if not user:
        m.LoginAttempt.objects.create(username=username[:150])
        raise ServiceError("Incorrect username or password.", 401)
    m.LoginAttempt.objects.filter(username__iexact=username).delete()
    return user, issue_token(user)


def issue_token(user):
    key = secrets.token_urlsafe(40)
    m.ApiToken.objects.create(
        user=user, key_hash=_hash(key), expires_at=timezone.now() + timedelta(days=settings.API_TOKEN_DAYS)
    )
    return key


def user_from_token(key):
    tok = m.ApiToken.objects.select_related("user").filter(key_hash=_hash(key), expires_at__gt=timezone.now()).first()
    return tok.user if tok and tok.user.is_active else None


def revoke_token(key):
    m.ApiToken.objects.filter(key_hash=_hash(key)).delete()


# ---------- stock & sales ----------

def stock_of(product):
    return product.batches.aggregate(t=Sum("quantity_left"))["t"] or 0


@transaction.atomic
def record_sale(owner, *, amount, customer_name="Walk-in", status=m.Sale.PAID, product=None, quantity=1, on=None):
    customer_name = (customer_name or "Walk-in").strip() or "Walk-in"
    customer, _ = m.Customer.objects.get_or_create(owner=owner, name=customer_name)
    cogs = (Decimal(amount) * COGS_ESTIMATE_RATIO).quantize(CENTS)
    if product:
        batches = list(product.batches.select_for_update().filter(quantity_left__gt=0).order_by("received_on", "id"))
        if sum(b.quantity_left for b in batches) < quantity:
            raise ServiceError(f"Only {sum(b.quantity_left for b in batches)} of {product.name} in stock.", 409)
        need, cogs = quantity, Decimal(0)
        for b in batches:  # oldest stock is sold first
            take = min(need, b.quantity_left)
            b.quantity_left -= take
            b.save(update_fields=["quantity_left"])
            cogs += take * b.unit_cost
            need -= take
            if not need:
                break
    return m.Sale.objects.create(
        owner=owner, customer=customer, product=product, quantity=quantity, amount=amount,
        cogs=cogs, status=status, date=on or timezone.localdate(),
    )


@transaction.atomic
def receive_stock(owner, *, product, quantity, unit_cost, supplier=None, purchase=None):
    today = timezone.localdate()
    batch = m.StockBatch.objects.create(
        owner=owner, product=product, supplier=supplier, quantity_received=quantity,
        quantity_left=quantity, unit_cost=unit_cost, received_on=today,
    )
    if purchase:
        purchase.status, purchase.delivered_on = m.Purchase.DELIVERED, today
        purchase.save(update_fields=["status", "delivered_on"])
    else:
        m.Purchase.objects.create(
            owner=owner, product=product, supplier=supplier, quantity=quantity, unit_cost=unit_cost,
            status=m.Purchase.DELIVERED, delivered_on=today,
        )
    return batch


# ---------- reporting ----------

def parse_month(value):
    if not value:
        today = timezone.localdate()
        return today.year, today.month
    try:
        y, mo = value.split("-")
        y, mo = int(y), int(mo)
        date(y, mo, 1)
        return y, mo
    except (ValueError, AttributeError):
        raise ServiceError("month must look like 2026-10.")


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def month_summary(owner, year, month):
    start, end = month_bounds(year, month)
    sales = m.Sale.objects.filter(owner=owner, date__range=(start, end))
    totals = sales.aggregate(rev=Sum("amount"), cogs=Sum("cogs"))
    rev, cogs = totals["rev"] or Decimal(0), totals["cogs"] or Decimal(0)
    exp = m.Expense.objects.filter(owner=owner, date__range=(start, end)).aggregate(t=Sum("amount"))["t"] or Decimal(0)
    gross = rev - cogs
    weeks = [Decimal(0)] * 4
    for d, amt in sales.values_list("date", "amount"):
        weeks[min((d.day - 1) // 7, 3)] += amt
    top = (
        sales.exclude(product=None).values("product__name").annotate(units=Sum("quantity")).order_by("-units")[:5]
    )
    return {
        "month": f"{year}-{month:02d}",
        "revenue": rev, "cogs": cogs, "expenses": exp, "gross_profit": gross, "net_profit": gross - exp,
        "weekly_sales": weeks,
        "top_products": [{"name": t["product__name"], "units": t["units"]} for t in top],
    }


def previous_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def forecast(summary):
    last_week = summary["weekly_sales"][3]
    return {
        name: {"next_week": (last_week * f).quantize(CENTS), "next_month": (summary["revenue"] * f).quantize(CENTS)}
        for name, f in SCENARIOS.items()
    }


def insights(owner, slow_days=45):
    out = []
    today = timezone.localdate()
    for p in m.Product.objects.filter(owner=owner).select_related("supplier"):
        left = stock_of(p)
        if p.target_stock and left / p.target_stock < 0.35:
            sold30 = m.Sale.objects.filter(owner=owner, product=p, date__gte=today - timedelta(days=30)).aggregate(
                t=Sum("quantity"))["t"] or 0
            pace = f" At the current pace it runs out in about {round(left / (sold30 / 30))} days." if sold30 else ""
            out.append({"category": "Stock", "priority": "High", "text": f"{p.name} is low ({left} left).{pace} Reorder soon."})
    for b in m.StockBatch.objects.filter(owner=owner, quantity_left__gt=0).select_related("product"):
        if b.age_days > slow_days:
            out.append({"category": "Slow stock", "priority": "Medium",
                        "text": f"{b.product.name} has sat on the shelf for {b.age_days} days. Discount it or bundle it."})
    pending = m.Sale.objects.filter(owner=owner, status=m.Sale.PENDING).aggregate(n=Count("id"), t=Sum("amount"))
    if pending["n"]:
        out.append({"category": "Cash", "priority": "Medium",
                    "text": f"{pending['n']} sale(s) worth {pending['t']} are still waiting on payment."})
    best = max(
        (p for p in m.Product.objects.filter(owner=owner) if p.price),
        key=lambda p: (p.price - p.cost) / p.price, default=None,
    )
    if best:
        out.append({"category": "Pricing", "priority": "Low",
                    "text": f"{best.name} has your widest margin. Consider promoting it."})
    rank = {"High": 0, "Medium": 1, "Low": 2}
    return sorted(out, key=lambda i: rank[i["priority"]])
