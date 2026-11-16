import hashlib
import logging
import re
import secrets
import smtplib
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from anymail.exceptions import AnymailError
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce, Lower, Trim, TruncMonth
from django.utils import timezone

from . import models as m

logger = logging.getLogger(__name__)

CENTS = Decimal("0.01")
COGS_ESTIMATE_RATIO = Decimal("0.6")  # used when a sale is not linked to a product
SCENARIOS = {"Conservative": Decimal("0.97"), "Expected": Decimal("1.08"), "Optimistic": Decimal("1.2")}


def money_out(value):
    return str((value or Decimal(0)).quantize(CENTS))


class ServiceError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


# ---------- auth ----------

def _send_email(*args, **kwargs):
    try:
        return send_mail(*args, **kwargs)
    except AnymailError as error:
        status = error.status_code
        raise OSError(f"Email provider request failed (HTTP status: {status}).") from None


def send_magic_link(email):
    if not email_delivery_configured():
        raise ServiceError("Secure email delivery is not configured.", 503)
    email = email.strip().lower()
    recent = m.MagicLink.objects.filter(email=email, created_at__gte=timezone.now() - timedelta(hours=1)).count()
    if recent >= 5:
        raise ServiceError("Too many sign-in requests. Try again later.", 429)
    token = secrets.token_urlsafe(32)
    m.MagicLink.objects.create(
        email=email, token_hash=_hash(token),
        expires_at=timezone.now() + timedelta(minutes=settings.MAGIC_LINK_MINUTES),
    )
    try:
        sent = _send_email(
            "Your Nexa sign-in link",
            f"Open this link to sign in to Nexa (valid {settings.MAGIC_LINK_MINUTES} minutes):\n\n"
            f"{settings.FRONTEND_URL}#token={token}\n\nIf you did not ask for this, ignore this email.",
            settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False,
        )
        if sent != 1:
            raise OSError("Email backend did not confirm delivery.")
    except (OSError, smtplib.SMTPException, ValueError) as error:
        m.MagicLink.objects.filter(token_hash=_hash(token)).delete()
        logger.exception("Could not send sign-in link")
        raise ServiceError("The email could not be sent. Try again later.", 503) from error


def _rate_limit_hit(key, limit, timeout):
    if cache.add(key, 1, timeout=timeout):
        return False
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return False
    return count > limit


def request_password_reset(email, remote_addr=""):
    email = email.strip().lower()
    email_key = "password-reset:email:" + _hash(email)
    ip_key = "password-reset:ip:" + _hash(remote_addr or "unknown")
    if _rate_limit_hit(email_key, 3, 60 * 60) or _rate_limit_hit(ip_key, 20, 60 * 60):
        return

    user = users_with_email(email).filter(is_active=True).first()
    if user is None:
        return
    if not email_delivery_configured():
        logger.error("Secure email delivery is not configured for password reset.")
        return

    now = timezone.now()
    m.PasswordResetToken.objects.filter(owner=user).filter(
        Q(used_at__isnull=False) | Q(expires_at__lte=now),
    ).delete()
    token = secrets.token_urlsafe(32)
    reset_token = m.PasswordResetToken.objects.create(
        owner=user,
        token_hash=_hash(token),
        expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_MINUTES),
    )
    try:
        sent = _send_email(
            "Reset your Nexa password",
            f"Open this link to reset your Nexa password (valid {settings.PASSWORD_RESET_MINUTES} minutes):\n\n"
            f"{settings.FRONTEND_URL}#password_reset={token}\n\n"
            "If you did not ask for this, ignore this email.",
            settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False,
        )
        if sent != 1:
            raise OSError("Email backend did not confirm delivery.")
    except (OSError, smtplib.SMTPException, ValueError) as error:
        reset_token.delete()
        logger.exception("Could not send password reset email")


@transaction.atomic
def reset_password(token, password, password2):
    if password != password2:
        raise ServiceError("The passwords do not match.")

    candidate = m.PasswordResetToken.objects.filter(token_hash=_hash(token)).first()
    if candidate is None:
        raise ServiceError("This password reset link is invalid or has expired.")
    user = get_user_model().objects.select_for_update().filter(pk=candidate.owner_id).first()
    if user is None or not user.is_active:
        raise ServiceError("This password reset link is invalid or has expired.")
    reset_token = m.PasswordResetToken.objects.select_for_update().filter(
        pk=candidate.pk, owner=user, used_at__isnull=True, expires_at__gt=timezone.now(),
    ).first()
    if reset_token is None:
        raise ServiceError("This password reset link is invalid or has expired.")

    try:
        validate_password(password, user)
    except DjangoValidationError as error:
        raise ServiceError(" ".join(error.messages))

    user.set_password(password)
    user.save(update_fields=["password"])
    now = timezone.now()
    m.PasswordResetToken.objects.filter(owner=user, used_at__isnull=True).update(used_at=now)
    m.ApiToken.objects.filter(user=user).delete()


def users_with_email(email):
    return get_user_model().objects.annotate(normalized_email=Lower(Trim("email"))).filter(
        normalized_email=email
    )


def initialize_business_data(user):
    m.UserSettings.objects.get_or_create(owner=user)


@transaction.atomic
def verify_magic_link(token, user_agent=""):
    link = m.MagicLink.objects.select_for_update().filter(token_hash=_hash(token)).first()
    if not link or link.used_at or link.expires_at < timezone.now():
        raise ServiceError("This sign-in link is invalid or has expired.", 400)
    email = link.email.strip().lower()
    User = get_user_model()
    user = users_with_email(email).first()
    if user is None:
        username = email
        if len(username) > 150 or User.objects.filter(username__iexact=username).exists():
            username = "email_" + secrets.token_hex(16)
        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username, email=email)
        except IntegrityError:
            user = users_with_email(email).first()
            if user is None:
                raise
    if not user.is_active:
        raise ServiceError("This account is inactive.", 403)
    initialize_business_data(user)
    if user.email.strip().lower() == email:
        prefs = m.UserSettings.objects.get(owner=user)
        if not prefs.email_verified:
            prefs.email_verified = True
            prefs.save(update_fields=["email_verified"])
    link.used_at = timezone.now()
    link.save(update_fields=["used_at"])
    return user, issue_token(user, user_agent)


TERMS_VERSION = "1"


def register(username, email, password, password2, accepted_terms, user_agent=""):
    username = (username or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", username):
        raise ServiceError("Username must be 3 to 30 ASCII letters, numbers, dots, dashes or underscores.")
    email = (email or "").strip().lower()
    try:
        validate_email(email)
    except DjangoValidationError:
        raise ServiceError("Enter a valid email address.")
    if password != password2:
        raise ServiceError("The passwords do not match.")
    if accepted_terms is not True:
        raise ServiceError("You must accept the terms and conditions.")
    User = get_user_model()
    if User.objects.filter(username__iexact=username).exists() or users_with_email(email).exists():
        raise ServiceError("That username or email is already in use. Please sign in.", 409)
    try:
        validate_password(password, User(username=username, email=email))
    except DjangoValidationError as e:
        raise ServiceError(" ".join(e.messages))
    try:
        with transaction.atomic():
            user = User.objects.create_user(username=username, email=email, password=password)
            initialize_business_data(user)
            m.TermsAcceptance.objects.create(user=user, version=TERMS_VERSION)
            return user, issue_token(user, user_agent)
    except IntegrityError:
        if User.objects.filter(username__iexact=username).exists() or users_with_email(email).exists():
            raise ServiceError("That username or email is already in use. Please sign in.", 409)
        raise


def login(username, password, user_agent=""):
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
    return user, issue_token(user, user_agent)


def issue_token(user, user_agent=""):
    key = secrets.token_urlsafe(40)
    m.ApiToken.objects.create(
        user=user, key_hash=_hash(key), expires_at=timezone.now() + timedelta(days=settings.API_TOKEN_DAYS),
        user_agent=user_agent[:180],
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


def with_stock(products):
    """Annotate products with in_stock in one query, so listings do not query per product."""
    return products.annotate(in_stock=Coalesce(Sum("batches__quantity_left"), Value(0)))


def ledger_balance(product):
    return product.movements.aggregate(t=Sum("quantity"))["t"] or 0


def log_movement(owner, *, product, kind, quantity, batch=None, sale=None, unit_cost=None, on=None, note=""):
    return m.StockMovement.objects.create(
        owner=owner, product=product, kind=kind, quantity=quantity, batch=batch, sale=sale,
        unit_cost=unit_cost, on=on or timezone.localdate(), note=note,
    )


@transaction.atomic
def record_sale(owner, *, amount, customer_name="Walk-in", status=m.Sale.PAID, product=None, quantity=1, on=None):
    customer_name = (customer_name or "Walk-in").strip() or "Walk-in"
    customer, _ = m.Customer.objects.get_or_create(owner=owner, name=customer_name)
    cogs = (Decimal(amount) * COGS_ESTIMATE_RATIO).quantize(CENTS)
    takes = []
    if product:
        batches = list(product.batches.select_for_update().filter(quantity_left__gt=0).order_by("received_on", "id"))
        if sum(b.quantity_left for b in batches) < quantity:
            raise ServiceError(f"Only {sum(b.quantity_left for b in batches)} of {product.name} in stock.", 409)
        need, cogs = quantity, Decimal(0)
        for b in batches:  # oldest stock is sold first
            take = min(need, b.quantity_left)
            b.quantity_left -= take
            b.save(update_fields=["quantity_left"])
            takes.append((b, take))
            cogs += take * b.unit_cost
            need -= take
            if not need:
                break
    sale = m.Sale.objects.create(
        owner=owner, customer=customer, product=product, quantity=quantity, amount=amount,
        cogs=cogs, status=status, date=on or timezone.localdate(),
    )
    for b, take in takes:
        log_movement(owner, product=product, kind=m.StockMovement.SALE, quantity=-take, batch=b, sale=sale,
                     unit_cost=b.unit_cost, on=sale.date)
    return sale


@transaction.atomic
def receive_stock(owner, *, product, quantity, unit_cost, supplier=None, purchase=None):
    today = timezone.localdate()
    batch = m.StockBatch.objects.create(
        owner=owner, product=product, supplier=supplier, quantity_received=quantity,
        quantity_left=quantity, unit_cost=unit_cost, received_on=today,
    )
    log_movement(owner, product=product, kind=m.StockMovement.RECEIVE, quantity=quantity, batch=batch,
                 unit_cost=unit_cost, on=today)
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
    totals = sales.filter(status=m.Sale.PAID).aggregate(rev=Sum("amount"), cogs=Sum("cogs"))
    rev, cogs = totals["rev"] or Decimal(0), totals["cogs"] or Decimal(0)
    exp = m.Expense.objects.filter(owner=owner, date__range=(start, end)).aggregate(t=Sum("amount"))["t"] or Decimal(0)
    gross = rev - cogs
    weeks = [Decimal(0)] * 4
    for d, amt in sales.order_by().values_list("date").annotate(total=Sum("amount")):
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


def monthly_reports(owner, today):
    first = m.Sale.objects.filter(owner=owner).order_by("date").values_list("date", flat=True).first()
    start = date(first.year, first.month, 1) if first else date(today.year, today.month, 1)
    end = month_bounds(today.year, today.month)[1]
    if start > end:
        return []
    sales = {
        row["month"]: row
        for row in m.Sale.objects.filter(owner=owner, status=m.Sale.PAID, date__range=(start, end))
        .order_by().annotate(month=TruncMonth("date")).values("month")
        .annotate(revenue=Sum("amount"), cogs=Sum("cogs"))
    }
    expenses = {
        row["month"]: row["total"]
        for row in m.Expense.objects.filter(owner=owner, date__range=(start, end))
        .order_by().annotate(month=TruncMonth("date")).values("month").annotate(total=Sum("amount"))
    }
    rows = []
    year, month = start.year, start.month
    while (year, month) <= (today.year, today.month):
        key = date(year, month, 1)
        total = sales.get(key)
        revenue = total["revenue"] if total else Decimal(0)
        cogs = total["cogs"] if total else Decimal(0)
        expense = expenses.get(key, Decimal(0))
        gross = revenue - cogs
        rows.append({
            "month": f"{year}-{month:02d}", "revenue": revenue, "expenses": expense,
            "gross_profit": gross, "net_profit": gross - expense,
        })
        year, month = shift_month(year, month, 1)
    return rows


def previous_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def goal_bounds(period, today):
    if period == m.UserSettings.DAY:
        return today, today
    if period == m.UserSettings.WEEK:
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if period == m.UserSettings.MONTH:
        return month_bounds(today.year, today.month)
    return date(today.year, 1, 1), date(today.year, 12, 31)


def goal_progress(owner, goal, period):
    start, end = goal_bounds(period, timezone.localdate())
    revenue = (
        m.Sale.objects.filter(owner=owner, status=m.Sale.PAID, date__range=(start, end))
        .aggregate(t=Sum("amount"))["t"] or Decimal(0)
    )
    return {
        "period": period,
        "start": start,
        "end": end,
        "revenue": revenue,
        "goal": goal,
        "percent": round(float(revenue) / float(goal) * 100, 1),
        "remaining": max(goal - revenue, Decimal(0)),
    }


def shift_month(year, month, delta):
    index = year * 12 + month - 1 + delta
    return index // 12, index % 12 + 1


def goal_series(owner, goal, period, today):
    """Paid revenue per bucket for the Overview goal chart: the days, weeks, or months of the goal period."""
    if period == m.UserSettings.DAY:
        first = date(today.year, today.month, 1)
        days = [first + timedelta(days=i) for i in range(monthrange(today.year, today.month)[1])]
        spans = [(d, d) for d in days]
        current, target = today.day - 1, goal
    elif period == m.UserSettings.WEEK:
        monday = today - timedelta(days=today.weekday())
        starts = [monday + timedelta(weeks=i) for i in range(-7, 1)]
        spans = [(start, start + timedelta(days=6)) for start in starts]
        current, target = 7, goal
    elif period == m.UserSettings.MONTH:
        spans = [month_bounds(*shift_month(today.year, today.month, i)) for i in range(-5, 1)]
        current, target = 5, goal
    else:
        spans = [month_bounds(today.year, month) for month in range(1, 13)]
        current, target = today.month - 1, goal / 12
    daily = [
        (row["date"], row["total"])
        for row in m.Sale.objects.filter(owner=owner, status=m.Sale.PAID, date__range=(spans[0][0], spans[-1][1]))
        .order_by().values("date").annotate(total=Sum("amount"))
    ]
    return {
        "period": period,
        "target": str(target.quantize(CENTS)),
        "current": current,
        "buckets": [
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "amount": str(sum((total for day, total in daily if start <= day <= end), Decimal(0)).quantize(CENTS)),
            }
            for start, end in spans
        ],
    }


def assistant_context(owner, year, month):
    """Build a compact, owner-scoped summary; never include individual transactions."""
    prefs, _ = m.UserSettings.objects.get_or_create(owner=owner)
    start, end = month_bounds(year, month)
    current = month_summary(owner, year, month)
    previous = month_summary(owner, *previous_month(year, month))
    sales = m.Sale.objects.filter(owner=owner, date__range=(start, end))
    paid = sales.filter(status=m.Sale.PAID).aggregate(total=Sum("amount"))["total"] or Decimal(0)
    pending = sales.filter(status=m.Sale.PENDING).aggregate(count=Count("id"), total=Sum("amount"))

    def amount(value):
        return str(value.quantize(CENTS))

    def change(key):
        old = previous[key]
        return str(((current[key] - old) / old * 100).quantize(Decimal("0.1"))) if old > 0 else None

    categories = (
        m.Expense.objects.filter(owner=owner, date__range=(start, end))
        .values("category").annotate(total=Sum("amount")).order_by("-total")[:5]
    )
    products = (
        sales.exclude(product=None).values("product__category")
        .annotate(units=Sum("quantity"), revenue=Sum("amount", filter=Q(status=m.Sale.PAID))).order_by("-units")[:5]
    )
    return {
        "period": current["month"],
        "currency": prefs.currency,
        "summary": {
            key: amount(current[key])
            for key in ("revenue", "cogs", "expenses", "gross_profit", "net_profit")
        },
        "previous_period": previous["month"],
        "previous_summary": {
            key: amount(previous[key])
            for key in ("revenue", "cogs", "expenses", "gross_profit", "net_profit")
        },
        "change_vs_previous_pct": {
            key: change(key) for key in ("revenue", "gross_profit", "expenses", "net_profit")
        },
        "paid_sales_total": amount(paid),
        "pending_payments": {
            "count": pending["count"],
            "total": amount(pending["total"] or Decimal(0)),
        },
        "weekly_sales": [amount(value) for value in current["weekly_sales"]],
        "top_product_categories": [
            {"rank": rank, "category": row["product__category"], "units": row["units"],
             "revenue": amount(row["revenue"])}
            for rank, row in enumerate(products, start=1)
        ],
        "expense_categories": [
            {"category": row["category"], "amount": amount(row["total"])}
            for row in categories
        ],
    }


def forecast(summary):
    last_week = summary["weekly_sales"][3]
    return {
        name: {"next_week": (last_week * f).quantize(CENTS), "next_month": (summary["revenue"] * f).quantize(CENTS)}
        for name, f in SCENARIOS.items()
    }


def insights(owner, slow_days=None):
    out = []
    today = timezone.localdate()
    prefs, _ = m.UserSettings.objects.get_or_create(owner=owner)
    slow_days = prefs.slow_stock_days if slow_days is None else slow_days
    products = list(with_stock(m.Product.objects.filter(owner=owner).select_related("supplier")))
    low = [p for p in products if p.target_stock and p.in_stock / p.target_stock < prefs.low_stock_threshold]
    sold30 = {
        row["product"]: row["t"]
        for row in m.Sale.objects.filter(owner=owner, product__in=low, date__gte=today - timedelta(days=30))
        .order_by().values("product").annotate(t=Sum("quantity"))
    }
    for p in low:
        left = p.in_stock
        units = sold30.get(p.id, 0)
        pace = f" At the current pace it runs out in about {round(left / (units / 30))} days." if units else ""
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
        (p for p in products if p.price),
        key=lambda p: (p.price - p.cost) / p.price, default=None,
    )
    if best:
        out.append({"category": "Pricing", "priority": "Low",
                    "text": f"{best.name} has your widest margin. Consider promoting it."})
    rank = {"High": 0, "Medium": 1, "Low": 2}
    return sorted(out, key=lambda i: rank[i["priority"]])


def _notification_candidates(owner):
    prefs, _ = m.UserSettings.objects.get_or_create(owner=owner)
    if not prefs.email_verified or not owner.email:
        return []

    candidates = []
    if prefs.notify_low_stock:
        products = with_stock(m.Product.objects.filter(owner=owner))
        for product in products:
            if product.target_stock and product.in_stock / product.target_stock < prefs.low_stock_threshold:
                candidates.append((
                    f"low:{product.pk}",
                    f"{product.name} is low on stock ({product.in_stock} left of {product.target_stock}).",
                ))
    if prefs.notify_slow_stock:
        for batch in m.StockBatch.objects.filter(owner=owner, quantity_left__gt=0).select_related("product"):
            if batch.age_days > prefs.slow_stock_days:
                candidates.append((
                    f"slow:{batch.pk}",
                    f"{batch.product.name} has a stock batch aged {batch.age_days} days.",
                ))
    if prefs.notify_goal_reached and prefs.revenue_goal is not None:
        progress = goal_progress(owner, prefs.revenue_goal, prefs.goal_period)
        if progress["revenue"] >= prefs.revenue_goal:
            candidates.append((
                f"goal:{progress['period']}:{progress['start'].isoformat()}",
                f"You reached your {progress['period']} revenue goal of {prefs.revenue_goal} {prefs.currency}.",
            ))
    return candidates


def sync_email_notifications(owner):
    prefs, _ = m.UserSettings.objects.get_or_create(owner=owner)
    active = dict(_notification_candidates(owner))
    send = {}
    with transaction.atomic():
        states = {
            row.key: row
            for row in m.NotificationState.objects.select_for_update().filter(owner=owner)
        }
        for key, state in states.items():
            should_be_active = key in active
            if state.active != should_be_active:
                state.active = should_be_active
                state.save(update_fields=["active", "updated_at"])
        for key, message in active.items():
            state = states.get(key)
            if state is None:
                state, created = m.NotificationState.objects.get_or_create(
                    owner=owner, key=key, defaults={"active": True},
                )
                if created:
                    send[key] = message
            elif not state.active:
                state.active = True
                state.save(update_fields=["active", "updated_at"])
                send[key] = message
        if send and settings.NEXA_ASYNC_ALERTS:
            m.NotificationDelivery.objects.create(
                owner=owner, email=owner.email, currency=prefs.currency, time_zone=prefs.time_zone, messages=send,
            )
    if send and not settings.NEXA_ASYNC_ALERTS:
        timezone_name = prefs.time_zone
        currency = prefs.currency
        email = owner.email
        owner_id = owner.pk
        transaction.on_commit(
            lambda: _send_email_notifications(owner_id, email, currency, timezone_name, send)
        )


def _send_email_notifications(owner_id, email, currency, timezone_name, messages):
    try:
        deliver_email_notifications(email, currency, timezone_name, messages)
    except (OSError, smtplib.SMTPException, ValueError):
        logger.exception("Could not send business alerts to account %s", owner_id)
        m.NotificationState.objects.filter(owner_id=owner_id, key__in=messages).update(active=False)


def deliver_email_notifications(email, currency, timezone_name, messages):
    if not email_delivery_configured():
        raise OSError("Secure email delivery is not configured.")
    sent = _send_email(
        "Nexa business alerts",
        f"Your Nexa alerts ({currency}, {timezone_name}):\n\n"
        + "\n".join(f"- {item}" for item in messages.values()),
        settings.DEFAULT_FROM_EMAIL,
        [email],
        fail_silently=False,
    )
    if sent != 1:
        raise OSError("Email backend did not confirm delivery.")


def process_alert_delivery():
    now = timezone.now()
    token = secrets.token_hex(16)
    with transaction.atomic():
        pending = m.NotificationDelivery.objects.filter(available_at__lte=now).filter(
            Q(locked_until__isnull=True) | Q(locked_until__lte=now)
        ).order_by("id")
        if connection.features.has_select_for_update_skip_locked:
            pending = pending.select_for_update(skip_locked=True)
        else:
            pending = pending.select_for_update()
        delivery = pending.first()
        if delivery is None:
            return False
        delivery.lease_token = token
        delivery.locked_until = now + timedelta(minutes=5)
        delivery.attempts += 1
        delivery.save(update_fields=["lease_token", "locked_until", "attempts"])
    try:
        deliver_email_notifications(delivery.email, delivery.currency, delivery.time_zone, delivery.messages)
    except (OSError, smtplib.SMTPException, ValueError):
        logger.exception("Could not deliver queued alert for account %s; retrying", delivery.owner_id)
        delay = min(3600, 5 * (2 ** min(delivery.attempts - 1, 10)))
        m.NotificationDelivery.objects.filter(pk=delivery.pk, lease_token=token).update(
            lease_token="", locked_until=None, available_at=timezone.now() + timedelta(seconds=delay),
        )
    else:
        m.NotificationDelivery.objects.filter(pk=delivery.pk, lease_token=token).delete()
    return True


def request_account_action(owner, action):
    if not isinstance(action, str) or action not in dict(m.AccountActionToken.ACTIONS):
        raise ServiceError("Choose export or delete.")
    if not email_delivery_configured():
        raise ServiceError("Secure email delivery is not configured.", 503)
    prefs, _ = m.UserSettings.objects.get_or_create(owner=owner)
    if not prefs.email_verified or not owner.email:
        raise ServiceError("Verify your account email before requesting this action.", 403)
    cache_key = f"nexa:account_action:{owner.pk}:{action}"
    if not cache.add(cache_key, 1, timeout=60):
        raise ServiceError("A confirmation email was sent recently. Check your inbox before retrying.", 429)

    m.AccountActionToken.objects.filter(owner=owner).filter(
        Q(used_at__isnull=False) | Q(expires_at__lte=timezone.now())
    ).delete()
    token = secrets.token_urlsafe(32)
    action_token = m.AccountActionToken.objects.create(
        owner=owner,
        action=action,
        token_hash=_hash(token),
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    link = f"{settings.FRONTEND_URL}#account_action={action}&token={token}"
    try:
        sent = _send_email(
            "Confirm your Nexa account action",
            f"Open this link to confirm your Nexa {action} request. The link expires in 10 minutes:\n\n"
            f"{link}\n\nIf you did not request this, ignore this email.",
            settings.DEFAULT_FROM_EMAIL,
            [owner.email],
            fail_silently=False,
        )
        if sent != 1:
            raise OSError("Email backend did not confirm delivery.")
    except (OSError, smtplib.SMTPException, ValueError) as error:
        action_token.delete()
        cache.delete(cache_key)
        logger.exception("Could not send account action confirmation to account %s", owner.pk)
        raise ServiceError("The confirmation email could not be sent. Try again later.", 503) from error


def consume_account_action(action, token):
    if not isinstance(action, str) or action not in dict(m.AccountActionToken.ACTIONS):
        raise ServiceError("Choose a valid account action.")
    action_token = m.AccountActionToken.objects.select_for_update().filter(
        action=action,
        token_hash=_hash(token),
        used_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).first()
    if action_token is None:
        raise ServiceError("This confirmation link is invalid or has expired.", 403)
    action_token.used_at = timezone.now()
    action_token.save(update_fields=["used_at"])
    return action_token


def email_delivery_configured():
    if settings.DEBUG and settings.EMAIL_BACKEND in (
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.locmem.EmailBackend",
    ):
        return True
    if settings.EMAIL_BACKEND == "anymail.backends.resend.EmailBackend":
        return bool(
            settings.RESEND_API_KEY
            and settings.DEFAULT_FROM_EMAIL
            and settings.DEFAULT_FROM_EMAIL != "Nexa <no-reply@nexa.local>"
        )
    return (
        settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
        and bool(settings.EMAIL_HOST and settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD)
        and (settings.EMAIL_USE_TLS or settings.EMAIL_USE_SSL)
    )
