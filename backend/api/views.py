import csv
import base64
import io
import json
import logging
from decimal import Decimal, InvalidOperation
from functools import wraps
from hashlib import sha256
from zoneinfo import available_timezones

from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Count, Max, QuerySet, Sum
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from redis.exceptions import RedisError

from .insights import algorithms
from .insights import assistant as ai
from . import images
from . import models as m
from . import services as svc

logger = logging.getLogger(__name__)


# ---------- helpers ----------

def ok(data, status=200):
    return JsonResponse(data, status=status, encoder=DjangoJSONEncoder, safe=False)


def fail(message, status=400):
    return JsonResponse({"error": message}, status=status)


@require_GET
def health_live(request):
    response = ok({"status": "ok"})
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def health_ready(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        cache.get("nexa:health-check")
    except (DatabaseError, OSError, RedisError):
        logger.exception("Readiness check failed")
        response = fail("Service is not ready.", 503)
    else:
        response = ok({"status": "ready"})
    response["Cache-Control"] = "no-store"
    return response


MAX_PAGE_SIZE = 500


def page(request, items, default_limit=None):
    """Slice a queryset or list by ?limit= and ?offset=. Returns (rows, total before slicing)."""
    try:
        offset = int(request.GET.get("offset", 0))
        raw_limit = request.GET.get("limit", default_limit)
        limit = None if raw_limit is None else int(raw_limit)
    except ValueError:
        raise svc.ServiceError("limit and offset must be whole numbers.")
    if offset < 0 or (limit is not None and limit < 0):
        raise svc.ServiceError("limit and offset must be zero or more.")
    total = items.count() if isinstance(items, QuerySet) else len(items)
    if limit is None:
        return items[offset:], total
    return items[offset:offset + min(limit, MAX_PAGE_SIZE)], total


def with_total(response, total):
    response["X-Total-Count"] = str(total)
    return response


def api(*methods, auth=True, max_body=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return fail("Method not allowed.", 405)
            request.owner = None
            request.prefs = None
            if auth:
                header = request.headers.get("Authorization", "")
                user = svc.user_from_token(header[7:]) if header.startswith("Bearer ") else None
                if not user:
                    return fail("Authentication required.", 401)
                request.owner = user
            request.data = {}
            if request.method in ("POST", "PATCH") and request.body:
                if max_body is not None and len(request.body) > max_body:
                    return fail("Request is too large.", 413)
                try:
                    request.data = json.loads(request.body)
                    if not isinstance(request.data, dict):
                        raise ValueError
                except ValueError:
                    return fail("Body must be a JSON object.")
            try:
                if request.owner:
                    prefs, _ = m.UserSettings.objects.get_or_create(owner=request.owner)
                    request.prefs = prefs
                    with timezone.override(prefs.time_zone):
                        return fn(request, *args, **kwargs)
                return fn(request, *args, **kwargs)
            except svc.ServiceError as e:
                return fail(e.message, e.status)
            except Http404:
                return fail("Not found.", 404)
            except Exception:
                logger.exception("Unhandled error in %s %s", request.method, request.path)
                return fail("Something went wrong. Please try again.", 500)
        return wrapper
    return deco


def money(data, key, required=True):
    raw = data.get(key)
    if raw in (None, ""):
        if required:
            raise svc.ServiceError(f"{key} is required.")
        return None
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        raise svc.ServiceError(f"{key} must be a number.")
    if not value.is_finite() or value <= 0 or value >= Decimal("1e10"):
        raise svc.ServiceError(f"{key} must be above zero.")
    return value.quantize(svc.CENTS)


def whole(data, key, default=None):
    raw = data.get(key, default)
    if isinstance(raw, bool) or raw in (None, ""):
        raise svc.ServiceError(f"{key} is required.")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise svc.ServiceError(f"{key} must be a whole number.")
    if value <= 0 or value > 10_000_000:
        raise svc.ServiceError(f"{key} must be above zero.")
    return value


def text(data, key, default="", maxlen=120):
    value = str(data.get(key) or default).strip()
    if len(value) > maxlen:
        raise svc.ServiceError(f"{key} is too long.")
    return value


def mine(model, owner, pk):
    return get_object_or_404(model, pk=pk, owner=owner)


def supplier_named(owner, name):
    name = (name or "").strip()
    return m.Supplier.objects.get_or_create(owner=owner, name=name)[0] if name else None


IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
MAX_IMAGE_BYTES = 1024 * 1024


def image_data(data, key="image"):
    """Validate and render a base64 image data URL, before anything is written.

    Returns None when the key is absent, "" to clear the photo, or {size: WebP bytes} to store.
    """
    if key not in data:
        return None
    raw = str(data.get(key) or "")
    if not raw:
        return ""
    header, sep, payload = raw.partition(",")
    if not sep or not header.startswith("data:") or ";base64" not in header or header[5:].split(";")[0] not in IMAGE_TYPES:
        raise svc.ServiceError("image must be a PNG, JPEG, WebP or GIF file.")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except ValueError:
        raise svc.ServiceError("image could not be read.")
    if len(decoded) > MAX_IMAGE_BYTES:
        raise svc.ServiceError("image must be 1 MB or smaller.")
    try:
        return images.render(decoded)
    except ValueError as e:
        raise svc.ServiceError(str(e))


# ---------- serializers ----------

def s_product(p, low_stock_threshold=Decimal("0.350")):
    # List views annotate in_stock via svc.with_stock; a single product falls back to one query.
    left = p.in_stock if hasattr(p, "in_stock") else svc.stock_of(p)
    return {
        "id": p.id, "name": p.name, "category": p.category, "price": p.price, "cost": p.cost,
        "margin_pct": round((p.price - p.cost) / p.price * 100, 1) if p.price else 0,
        "target_stock": p.target_stock, "in_stock": left,
        "low_stock": bool(p.target_stock) and left / p.target_stock < low_stock_threshold,
        "supplier": p.supplier.name if p.supplier else None,
        "image_url": reverse("product_image", args=[p.image_key]) if p.image_key else "",
    }


def s_sale(s):
    return {
        "id": s.id, "customer": s.customer.name if s.customer else "Walk-in",
        "product": s.product.name if s.product else None, "quantity": s.quantity,
        "amount": s.amount, "status": s.status, "date": s.date, "cogs": s.cogs,
    }


def s_purchase(p):
    return {
        "id": p.id, "product": p.product.name, "supplier": p.supplier.name if p.supplier else None,
        "quantity": p.quantity, "unit_cost": p.unit_cost, "total": p.total, "status": p.status,
        "ordered_on": p.ordered_on, "delivered_on": p.delivered_on,
    }


def s_batch(b):
    return {
        "id": b.id, "product": b.product.name, "supplier": b.supplier.name if b.supplier else None,
        "quantity_received": b.quantity_received, "quantity_left": b.quantity_left,
        "unit_cost": b.unit_cost, "received_on": b.received_on, "age_days": b.age_days,
        "tied_up": b.quantity_left * b.unit_cost,
    }


# ---------- auth ----------

@api("POST", auth=False)
def request_link(request):
    email = text(request.data, "email", maxlen=254).lower()
    try:
        validate_email(email)
    except ValidationError:
        return fail("Enter a valid email address.")
    svc.send_magic_link(email)
    return ok({"detail": "If that address is valid, a sign-in link is on its way."})


@api("POST", auth=False, max_body=2048)
def request_password_reset(request):
    email = text(request.data, "email", maxlen=254).lower()
    try:
        validate_email(email)
    except ValidationError:
        return fail("Enter a valid email address.")
    svc.request_password_reset(email, request.META.get("REMOTE_ADDR", ""))
    response = ok({"detail": "If an account exists for that email, password reset instructions will be sent."})
    response["Cache-Control"] = "no-store, private"
    return response


@api("POST", auth=False, max_body=4096)
def reset_password(request):
    data = request.data
    token = text(data, "token", maxlen=200)
    password = data.get("password") if isinstance(data.get("password"), str) else ""
    password2 = data.get("password2") if isinstance(data.get("password2"), str) else None
    svc.reset_password(token, password, password2)
    response = ok({"detail": "Your password has been reset. Sign in with your new password."})
    response["Cache-Control"] = "no-store, private"
    return response


@api("POST", auth=False)
def verify_link(request):
    user, key = svc.verify_magic_link(text(request.data, "token", maxlen=200))
    response = ok({"token": key, "user": {"id": user.id, "email": user.email}})
    response["Cache-Control"] = "no-store, private"
    return response


def _session(user, key, status=200):
    response = ok({"token": key, "user": {"id": user.id, "username": user.username}}, status)
    response["Cache-Control"] = "no-store, private"
    return response


@api("POST", auth=False)
def register(request):
    d = request.data
    user, key = svc.register(
        text(d, "username", maxlen=30), text(d, "email", maxlen=254),
        d.get("password") if isinstance(d.get("password"), str) else "",
        d.get("password2") if isinstance(d.get("password2"), str) else None, d.get("accepted_terms"),
    )
    return _session(user, key, 201)


@api("POST", auth=False)
def login(request):
    d = request.data
    user, key = svc.login(text(d, "username", maxlen=150), d.get("password") if isinstance(d.get("password"), str) else "")
    return _session(user, key)


@api("POST")
def logout(request):
    svc.revoke_token(request.headers["Authorization"][7:])
    return ok({"detail": "Signed out."})


@api("GET")
def me(request):
    return ok({"id": request.owner.id, "username": request.owner.username, "email": request.owner.email, "is_staff": request.owner.is_staff})


# ---------- catalogue ----------

@api("GET", "POST")
def products(request):
    o = request.owner
    if request.method == "GET":
        qs = m.Product.objects.filter(owner=o).select_related("supplier")
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        rows, total = page(request, svc.with_stock(qs).order_by("name", "id"))
        return with_total(ok([s_product(p, request.prefs.low_stock_threshold) for p in rows]), total)
    name = text(request.data, "name")
    if not name:
        return fail("name is required.")
    if m.Product.objects.filter(owner=o, name__iexact=name).exists():
        return fail("That product already exists.", 409)
    try:
        with transaction.atomic():
            p = m.Product.objects.create(
                owner=o, name=name, category=text(request.data, "category", "General", 80),
                price=money(request.data, "price"), cost=money(request.data, "cost"),
                target_stock=whole(request.data, "target_stock", 60),
                supplier=supplier_named(o, request.data.get("supplier")),
            )
    except IntegrityError:
        return fail("That product already exists.", 409)
    return ok(s_product(p, request.prefs.low_stock_threshold), 201)


@api("GET", "PATCH")
def product_detail(request, pk):
    p = mine(m.Product, request.owner, pk)
    if request.method == "PATCH":
        d = request.data
        if "name" in d:
            p.name = text(d, "name") or p.name
        if "category" in d:
            p.category = text(d, "category", "General", 80)
        if "price" in d:
            p.price = money(d, "price")
        if "cost" in d:
            p.cost = money(d, "cost")
        if "target_stock" in d:
            p.target_stock = whole(d, "target_stock")
        if "supplier" in d:
            p.supplier = supplier_named(request.owner, d["supplier"])
        variants = image_data(d)
        old_key = p.image_key
        if variants is not None:
            p.image_key = images.save(variants) if variants else ""
        try:
            with transaction.atomic():
                p.save()
        except IntegrityError:
            if variants:
                images.delete(p.image_key)
            return fail("That product already exists.", 409)
        if variants is not None and old_key:
            images.delete(old_key)
    return ok(s_product(p, request.prefs.low_stock_threshold))


@api("GET", "POST")
def suppliers(request):
    o = request.owner
    if request.method == "GET":
        return ok([{"id": s.id, "name": s.name, "supplies": s.supplies} for s in m.Supplier.objects.filter(owner=o)])
    name = text(request.data, "name")
    if not name:
        return fail("name is required.")
    s, created = m.Supplier.objects.get_or_create(owner=o, name=name, defaults={"supplies": text(request.data, "supplies", maxlen=200)})
    return ok({"id": s.id, "name": s.name, "supplies": s.supplies}, 201 if created else 200)


@api("GET")
def customers(request):
    o = request.owner
    rows = (
        m.Customer.objects.filter(owner=o)
        .annotate(orders=Count("sales"), spent=Sum("sales__amount"), last=Max("sales__date"))
        .order_by("-spent")
    )
    # Sale.Meta.ordering would be added to SELECT DISTINCT, so clear it and group the names in Python.
    bought = {}
    pairs = (
        m.Sale.objects.filter(owner=o, customer__isnull=False).exclude(product=None)
        .order_by("customer_id", "product__name").values_list("customer_id", "product__name").distinct()
    )
    for customer_id, product_name in pairs:
        bought.setdefault(customer_id, []).append(product_name)
    out = []
    for c in rows:
        out.append({
            "id": c.id, "name": c.name, "orders": c.orders, "spent": svc.money_out(c.spent),
            "last_purchase": c.last, "products": bought.get(c.id, []),
        })
    return ok(out)


# ---------- sales & expenses ----------

@api("GET", "POST")
def sales(request):
    o = request.owner
    if request.method == "GET":
        qs = m.Sale.objects.filter(owner=o).select_related("customer", "product")
        status = request.GET.get("status")
        if status in (m.Sale.PAID, m.Sale.PENDING):
            qs = qs.filter(status=status)
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(customer__name__icontains=q)
        rows, total = page(request, qs, default_limit=500)
        return with_total(ok([s_sale(s) for s in rows]), total)
    d = request.data
    status = d.get("status", m.Sale.PAID)
    if status not in (m.Sale.PAID, m.Sale.PENDING):
        return fail("status must be Paid or Pending.")
    product = None
    if d.get("product_id"):
        product = mine(m.Product, o, d["product_id"])
    sale = svc.record_sale(
        o, amount=money(d, "amount"), customer_name=text(d, "customer", "Walk-in"),
        status=status, product=product, quantity=whole(d, "quantity", 1),
    )
    svc.sync_email_notifications(o)
    return ok(s_sale(sale), 201)


@api("PATCH")
def sale_detail(request, pk):
    sale = mine(m.Sale, request.owner, pk)
    status = request.data.get("status")
    if status not in (m.Sale.PAID, m.Sale.PENDING):
        return fail("status must be Paid or Pending.")
    sale.status = status
    sale.save(update_fields=["status"])
    svc.sync_email_notifications(request.owner)
    return ok(s_sale(sale))


@api("GET", "POST")
def expenses(request):
    o = request.owner
    if request.method == "GET":
        qs = m.Expense.objects.filter(owner=o)
        month = request.GET.get("month")
        if month:
            start, end = svc.month_bounds(*svc.parse_month(month))
            qs = qs.filter(date__range=(start, end))
        by_cat = qs.values("category").annotate(total=Sum("amount")).order_by("-total")
        rows, total = page(request, qs, default_limit=500)
        return with_total(ok({
            "items": [{"id": e.id, "category": e.category, "amount": e.amount, "date": e.date} for e in rows],
            "by_category": list(by_cat), "total": svc.money_out(qs.aggregate(t=Sum("amount"))["t"]),
        }), total)
    e = m.Expense.objects.create(
        owner=o, category=text(request.data, "category", "General", 80), amount=money(request.data, "amount")
    )
    return ok({"id": e.id, "category": e.category, "amount": e.amount, "date": e.date}, 201)


# ---------- stock ----------

@api("GET")
def stock(request):
    products = svc.with_stock(m.Product.objects.filter(owner=request.owner).select_related("supplier"))
    return ok([s_product(p, request.prefs.low_stock_threshold) for p in products])


@api("GET")
def batches(request):
    qs = m.StockBatch.objects.filter(owner=request.owner, quantity_left__gt=0).select_related("product", "supplier")
    if request.GET.get("slow") is None:
        rows, total = page(request, qs)
        return with_total(ok([s_batch(b) for b in rows]), total)
    try:
        limit = int(request.GET.get("min_age", request.prefs.slow_stock_days))
    except ValueError:
        return fail("min_age must be a whole number.")
    # The slow-moving filter depends on age_days, so it runs before paging.
    rows = [s_batch(b) for b in qs]
    rows = sorted((b for b in rows if b["age_days"] > limit), key=lambda b: -b["age_days"])
    rows, total = page(request, rows)
    return with_total(ok(rows), total)


@api("GET", "POST")
def purchases(request):
    o = request.owner
    if request.method == "GET":
        rows, total = page(request, m.Purchase.objects.filter(owner=o).select_related("product", "supplier"))
        return with_total(ok([s_purchase(p) for p in rows]), total)
    product = mine(m.Product, o, request.data.get("product_id"))
    qty = whole(request.data, "quantity", max(product.target_stock - svc.stock_of(product), 1))
    p = m.Purchase.objects.create(
        owner=o, product=product, supplier=product.supplier, quantity=qty,
        unit_cost=money(request.data, "unit_cost", required=False) or product.cost,
    )
    return ok(s_purchase(p), 201)


@api("POST")
def purchase_receive(request, pk):
    with transaction.atomic():
        p = get_object_or_404(m.Purchase.objects.select_for_update(), pk=pk, owner=request.owner)
        if p.status == m.Purchase.DELIVERED:
            return fail("This order was already received.", 409)
        svc.receive_stock(request.owner, product=p.product, quantity=p.quantity, unit_cost=p.unit_cost, supplier=p.supplier, purchase=p)
    p.refresh_from_db()
    svc.sync_email_notifications(request.owner)
    return ok(s_purchase(p))


@api("POST")
def receive(request):
    o, d = request.owner, request.data
    qty, cost = whole(d, "quantity"), money(d, "unit_cost")
    variants = image_data(d)
    supplier = supplier_named(o, d.get("supplier"))
    if d.get("product_id"):
        product = mine(m.Product, o, d["product_id"])
        existing = True
    else:
        name = text(d, "new_product_name")
        if not name:
            return fail("Choose a product or give the new product a name.")
        product = m.Product.objects.filter(owner=o, name__iexact=name).first()
        existing = product is not None
        price = None if existing else money(d, "price")
    replace = existing and variants is not None
    new_key = images.save(variants) if variants else ""
    try:
        with transaction.atomic():
            if not existing:
                product = m.Product.objects.create(
                    owner=o, name=name, category="General", price=price, cost=cost, supplier=supplier,
                    image_key=new_key,
                )
            batch = svc.receive_stock(o, product=product, quantity=qty, unit_cost=cost, supplier=supplier)
            if replace:
                old_key, product.image_key = product.image_key, new_key
                product.save(update_fields=["image_key"])
    except IntegrityError:
        images.delete(new_key)
        return fail("That product already exists.", 409)
    except Exception:
        images.delete(new_key)
        raise
    if replace:
        images.delete(old_key)
    svc.sync_email_notifications(o)
    return ok({**s_batch(batch), "product": s_product(product, request.prefs.low_stock_threshold)}, 201)


@api("GET", auth=False)
def product_image(request, key):
    """Public so <img> tags can load it without a Bearer header. The key is a random 128-bit value."""
    try:
        wanted = int(request.GET.get("size", images.DEFAULT_SIZE))
    except ValueError:
        return fail("size must be a whole number.")
    size = next((s for s in images.SIZES if s >= wanted), images.SIZES[-1])
    image = images.open_variant(key, size)
    if image is None:
        raise Http404
    etag = f'"{key}-{size}"'
    if etag in [tag.strip() for tag in request.headers.get("If-None-Match", "").split(",")]:
        image.close()
        response = HttpResponseNotModified()
    else:
        response = FileResponse(image, content_type="image/webp")
    response["ETag"] = etag
    response["Cache-Control"] = "public, max-age=86400"
    return response


# ---------- reporting ----------

@api("GET")
def dashboard(request):
    year, month = svc.parse_month(request.GET.get("month"))
    cur = svc.month_summary(request.owner, year, month)
    prev = svc.month_summary(request.owner, *svc.previous_month(year, month))

    def change(key):
        return round((cur[key] / prev[key] - 1) * 100, 1) if prev[key] else None

    o = request.owner
    pending = m.Sale.objects.filter(owner=o, status=m.Sale.PENDING).aggregate(n=Count("id"), t=Sum("amount"))
    prefs, _ = m.UserSettings.objects.get_or_create(owner=o)
    cur["change_vs_previous_pct"] = {k: change(k) for k in ("revenue", "gross_profit", "expenses", "net_profit")}
    cur["forecast"] = svc.forecast(cur)
    cur["pending_payments"] = {"count": pending["n"], "total": svc.money_out(pending["t"])}
    cur["low_stock"] = [
        p["name"]
        for p in (
            s_product(product, prefs.low_stock_threshold)
            for product in svc.with_stock(m.Product.objects.filter(owner=o).select_related("supplier"))
        )
        if p["low_stock"]
    ]
    cur["slow_batches"] = sum(
        1 for b in m.StockBatch.objects.filter(owner=o, quantity_left__gt=0) if b.age_days > prefs.slow_stock_days
    )
    svc.sync_email_notifications(o)
    return ok(cur)


@api("GET")
def reports(request):
    return ok(svc.monthly_reports(request.owner, timezone.localdate()))


@api("GET")
def insights(request):
    svc.sync_email_notifications(request.owner)
    return ok(svc.insights(request.owner))


@api("GET", "PATCH", max_body=1500000)
def app_settings(request):
    prefs, _ = m.UserSettings.objects.get_or_create(owner=request.owner)
    if request.method == "PATCH":
        d = request.data
        known = {
            "goal_period", "revenue_goal", "theme", "currency", "confirm_currency_change",
            "time_zone", "business_name", "business_logo", "business_email", "business_phone",
            "business_logo_zoom", "business_logo_x", "business_logo_y",
            "low_stock_threshold", "slow_stock_days", "reorder_lead_days", "safety_stock_days",
            "reorder_target_days",
            "notify_low_stock", "notify_slow_stock", "notify_goal_reached",
        }
        unknown = set(d) - known
        if unknown:
            return fail(f"Unsupported setting: {sorted(unknown)[0]}.")
        if "goal_period" in d:
            period = str(d["goal_period"] or "")
            if period not in dict(m.UserSettings.PERIODS):
                return fail("goal_period must be day, week, month, or year.")
            prefs.goal_period = period
        if "revenue_goal" in d:
            prefs.revenue_goal = money(d, "revenue_goal", required=False)
        if "theme" in d:
            if not isinstance(d["theme"], str) or d["theme"] not in dict(m.UserSettings._meta.get_field("theme").choices):
                return fail("theme must be light or dark.")
            prefs.theme = d["theme"]
        if "currency" in d:
            currency = d["currency"]
            if not isinstance(currency, str) or currency not in dict(m.UserSettings.CURRENCY_CHOICES):
                return fail("Choose a supported currency.")
            if currency != prefs.currency and d.get("confirm_currency_change") is not True:
                return fail("Confirm that changing currency does not convert recorded amounts.")
            prefs.currency = currency
        if "time_zone" in d:
            time_zone = d["time_zone"]
            if not isinstance(time_zone, str) or time_zone not in available_timezones():
                return fail("Choose a valid IANA time zone.")
            prefs.time_zone = time_zone
        for field, max_length in (("business_name", 120), ("business_phone", 32)):
            if field in d:
                value = d[field]
                if not isinstance(value, str) or len(value.strip()) > max_length:
                    return fail(f"{field} must be {max_length} characters or fewer.")
                setattr(prefs, field, value.strip())
        for field, minimum, maximum in (
            ("business_logo_zoom", 100, 300), ("business_logo_x", -100, 100),
            ("business_logo_y", -100, 100),
        ):
            if field in d:
                value = d[field]
                if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                    return fail(f"{field} must be a whole number between {minimum} and {maximum}.")
                setattr(prefs, field, value)
        if "business_email" in d:
            value = d["business_email"]
            if not isinstance(value, str) or len(value.strip()) > 254:
                return fail("business_email must be a valid email address.")
            value = value.strip()
            if value:
                try:
                    validate_email(value)
                except ValidationError:
                    return fail("business_email must be a valid email address.")
            prefs.business_email = value
        if "low_stock_threshold" in d:
            try:
                threshold = Decimal(str(d["low_stock_threshold"]))
                if not threshold.is_finite() or not Decimal("0.01") <= threshold <= Decimal("1.000"):
                    raise InvalidOperation
                prefs.low_stock_threshold = threshold.quantize(Decimal("0.001"))
            except (InvalidOperation, TypeError, ValueError):
                return fail("low_stock_threshold must be between 0.01 and 1.")
        for field, maximum in (
            ("slow_stock_days", 3650), ("reorder_lead_days", 365), ("safety_stock_days", 365),
            ("reorder_target_days", 365),
        ):
            if field in d:
                value = d[field]
                if isinstance(value, bool):
                    return fail(f"{field} must be a whole number between 1 and {maximum}.")
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    return fail(f"{field} must be a whole number between 1 and {maximum}.")
                if value < 1 or value > maximum or str(value) != str(d[field]):
                    return fail(f"{field} must be a whole number between 1 and {maximum}.")
                setattr(prefs, field, value)
        for field in ("notify_low_stock", "notify_slow_stock", "notify_goal_reached"):
            if field in d:
                if not isinstance(d[field], bool):
                    return fail(f"{field} must be true or false.")
                if d[field] and (not prefs.email_verified or not svc.email_delivery_configured()):
                    return fail("Verify your account email and configure secure email delivery before enabling alerts.", 400)
                setattr(prefs, field, d[field])
        variants = image_data(d, "business_logo")
        new_key = images.save(variants) if variants else ""
        fields = set(d) - {"confirm_currency_change", "business_logo"}
        try:
            with transaction.atomic():
                if variants is not None:
                    old_key = m.UserSettings.objects.select_for_update().get(pk=prefs.pk).business_logo_key
                    prefs.business_logo_key = new_key
                    prefs.business_logo_fingerprint = sha256(variants[1000]).hexdigest() if variants else None
                    fields.update({"business_logo_key", "business_logo_fingerprint"})
                    if old_key:
                        transaction.on_commit(lambda: images.delete(old_key))
                if fields:
                    prefs.save(update_fields=fields)
        except IntegrityError:
            if new_key:
                images.delete(new_key)
            others = m.UserSettings.objects.exclude(pk=prefs.pk)
            if "business_name" in fields and prefs.business_name_fingerprint and others.filter(
                business_name_fingerprint=prefs.business_name_fingerprint
            ).exists():
                return fail("That company name is already in use by another account.", 409)
            if variants and others.filter(business_logo_fingerprint=prefs.business_logo_fingerprint).exists():
                return fail("That company logo is already in use by another account.", 409)
            raise
        except Exception:
            if new_key:
                images.delete(new_key)
            raise
        svc.sync_email_notifications(request.owner)
    with timezone.override(prefs.time_zone):
        goal = prefs.revenue_goal
        progress = svc.goal_progress(request.owner, goal, prefs.goal_period) if goal is not None else None
    response = ok({
        "revenue_goal": goal,
        "goal_period": prefs.goal_period,
        "progress": progress,
        "theme": prefs.theme,
        "currency": prefs.currency,
        "time_zone": prefs.time_zone,
        "business_name": prefs.business_name,
        "business_logo_url": reverse("product_image", args=[prefs.business_logo_key]) if prefs.business_logo_key else "",
        "business_logo_zoom": prefs.business_logo_zoom,
        "business_logo_x": prefs.business_logo_x,
        "business_logo_y": prefs.business_logo_y,
        "business_email": prefs.business_email,
        "business_phone": prefs.business_phone,
        "low_stock_threshold": prefs.low_stock_threshold,
        "slow_stock_days": prefs.slow_stock_days,
        "reorder_lead_days": prefs.reorder_lead_days,
        "safety_stock_days": prefs.safety_stock_days,
        "reorder_target_days": prefs.reorder_target_days,
        "email_verified": prefs.email_verified,
        "email_delivery_configured": svc.email_delivery_configured(),
        "notify_low_stock": prefs.notify_low_stock,
        "notify_slow_stock": prefs.notify_slow_stock,
        "notify_goal_reached": prefs.notify_goal_reached,
    })
    response["Cache-Control"] = "no-store, private"
    return response


@api("POST", max_body=1024)
def verify_settings_email(request):
    if not request.owner.email:
        return fail("Add an account email before requesting verification.", 400)
    if not svc.email_delivery_configured():
        return fail("Secure email delivery is not configured.", 503)
    svc.send_magic_link(request.owner.email)
    return ok({"message": "A sign-in and email verification link was sent."})


@api("POST", max_body=1024)
def request_account_confirmation(request):
    action = request.data.get("action")
    svc.request_account_action(request.owner, action)
    return ok({"message": f"Confirmation email sent for {action}."})


def _consume_account_action(request, action):
    if request.data.get("confirmation") != action.upper():
        raise svc.ServiceError(f"Type {action.upper()} to confirm this action.")
    token = request.data.get("token")
    if not isinstance(token, str) or len(token) > 200:
        raise svc.ServiceError("A valid email confirmation token is required.")
    return svc.consume_account_action(action, token)


@api("POST", auth=False, max_body=4096)
def account_export(request):
    with transaction.atomic():
        action_token = _consume_account_action(request, m.AccountActionToken.EXPORT)
        owner_id = action_token.owner_id
        tables = [
            ("supplier", m.Supplier, ("id", "name", "supplies")),
            ("product", m.Product, ("id", "name", "category", "price", "cost", "target_stock", "supplier_id")),
            ("stock_batch", m.StockBatch, ("id", "product_id", "supplier_id", "quantity_received", "quantity_left", "unit_cost", "received_on")),
            ("stock_movement", m.StockMovement, ("id", "product_id", "batch_id", "sale_id", "kind", "quantity", "unit_cost", "on", "note")),
            ("customer", m.Customer, ("id", "name")),
            ("sale", m.Sale, ("id", "customer_id", "product_id", "quantity", "amount", "cogs", "status", "date")),
            ("expense", m.Expense, ("id", "category", "amount", "date")),
            ("purchase", m.Purchase, ("id", "product_id", "supplier_id", "quantity", "unit_cost", "status", "ordered_on", "delivered_on")),
            ("settings", m.UserSettings, (
                "revenue_goal", "goal_period", "theme", "currency", "time_zone", "business_name",
                "business_email", "business_phone", "business_logo_zoom", "business_logo_x", "business_logo_y",
                "low_stock_threshold", "slow_stock_days",
                "reorder_lead_days", "safety_stock_days", "reorder_target_days",
                "notify_low_stock", "notify_slow_stock",
                "notify_goal_reached",
            )),
        ]
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["record_type", "record_id", "data"])
        owner = action_token.owner
        writer.writerow([
            "account", owner.pk,
            json.dumps({
                "username": owner.username,
                "email": owner.email,
                "terms_acceptance": m.TermsAcceptance.objects.filter(user=owner).values(
                    "accepted_at", "version",
                ).first(),
            }, cls=DjangoJSONEncoder, ensure_ascii=True, sort_keys=True),
        ])
        for record_type, model, fields in tables:
            records = model.objects.filter(owner_id=owner_id).values(*fields)
            for row in records.iterator():
                record_id = row.pop("id", "")
                writer.writerow([
                    record_type,
                    record_id,
                    json.dumps(row, cls=DjangoJSONEncoder, ensure_ascii=True, sort_keys=True),
                ])
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="nexa-account-export.csv"'
    response["Cache-Control"] = "no-store, private"
    response["Pragma"] = "no-cache"
    return response


@api("POST", auth=False, max_body=4096)
def account_delete(request):
    with transaction.atomic():
        action_token = _consume_account_action(request, m.AccountActionToken.DELETE)
        owner = action_token.owner
        photo_keys = list(
            m.Product.objects.filter(owner=owner).exclude(image_key="").values_list("image_key", flat=True)
        )
        logo_key = m.UserSettings.objects.filter(owner=owner).values_list("business_logo_key", flat=True).first()
        if logo_key:
            photo_keys.append(logo_key)
        m.MagicLink.objects.filter(email__iexact=owner.email).delete()
        m.LoginAttempt.objects.filter(username__iexact=owner.username).delete()
        owner.delete()

        def cleanup_photos():
            for key in photo_keys:
                images.delete(key)

        transaction.on_commit(cleanup_photos)
    response = ok({"message": "Your Nexa account and associated data were deleted."})
    response["Cache-Control"] = "no-store, private"
    return response


@api("GET")
def goal_series(request):
    prefs = m.UserSettings.objects.filter(owner=request.owner).first()
    if prefs is None or prefs.revenue_goal is None:
        return ok(None)
    return ok(svc.goal_series(request.owner, prefs.revenue_goal, prefs.goal_period, timezone.localdate()))


@api("POST", max_body=4096)
def assistant_chat(request):
    key = f"nexa:assistant:{request.owner.pk}"
    if not cache.add(key, 1, timeout=60):
        try:
            requests = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=60)
            requests = 1
        if requests > 10:
            return fail("Too many assistant requests. Try again in a minute.", 429)
    question = request.data.get("question")
    if not isinstance(question, str) or not question.strip():
        return fail("Enter a question for the assistant.")
    question = question.strip()
    if len(question) > 1000:
        return fail("Questions must be 1000 characters or fewer.")
    year, month = svc.parse_month(request.data.get("month"))
    context = svc.assistant_context(request.owner, year, month)
    return ok({
        "answer": ai.generate_answer(question, context),
        "period": context["period"],
    })


@api("POST", max_body=4096)
def assistant_analyze(request):
    analysis = request.data.get("analysis")
    if not isinstance(analysis, str) or analysis not in algorithms.ANALYSES:
        return fail("Choose a supported algorithm analysis.")
    try:
        year, month = svc.parse_month(request.data.get("month"))
    except svc.ServiceError as error:
        return fail(error.message, error.status)
    return ok(algorithms.analyze(request.owner, analysis, year, month))
