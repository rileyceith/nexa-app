import json
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db.models import Count, Max, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import models as m
from . import services as svc


# ---------- helpers ----------

def ok(data, status=200):
    return JsonResponse(data, status=status, encoder=DjangoJSONEncoder, safe=False)


def fail(message, status=400):
    return JsonResponse({"error": message}, status=status)


def api(*methods, auth=True):
    def deco(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return fail("Method not allowed.", 405)
            request.owner = None
            if auth:
                header = request.headers.get("Authorization", "")
                user = svc.user_from_token(header[7:]) if header.startswith("Bearer ") else None
                if not user:
                    return fail("Authentication required.", 401)
                request.owner = user
            request.data = {}
            if request.method in ("POST", "PATCH") and request.body:
                try:
                    request.data = json.loads(request.body)
                    if not isinstance(request.data, dict):
                        raise ValueError
                except ValueError:
                    return fail("Body must be a JSON object.")
            try:
                return fn(request, *args, **kwargs)
            except svc.ServiceError as e:
                return fail(e.message, e.status)
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


# ---------- serializers ----------

def s_product(p):
    left = svc.stock_of(p)
    return {
        "id": p.id, "name": p.name, "category": p.category, "price": p.price, "cost": p.cost,
        "margin_pct": round((p.price - p.cost) / p.price * 100, 1) if p.price else 0,
        "target_stock": p.target_stock, "in_stock": left,
        "low_stock": bool(p.target_stock) and left / p.target_stock < 0.35,
        "supplier": p.supplier.name if p.supplier else None,
    }


def s_sale(s):
    return {
        "id": s.id, "customer": s.customer.name if s.customer else "Walk-in",
        "product": s.product.name if s.product else None, "quantity": s.quantity,
        "amount": s.amount, "status": s.status, "date": s.date,
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


@api("POST", auth=False)
def verify_link(request):
    user, key = svc.verify_magic_link(text(request.data, "token", maxlen=200))
    return ok({"token": key, "user": {"id": user.id, "email": user.email}})


def _session(user, key, status=200):
    return ok({"token": key, "user": {"id": user.id, "username": user.username}}, status)


@api("POST", auth=False)
def register(request):
    d = request.data
    user, key = svc.register(
        text(d, "username", maxlen=30), d.get("password") if isinstance(d.get("password"), str) else "",
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
    return ok({"id": request.owner.id, "username": request.owner.username, "email": request.owner.email})


# ---------- catalogue ----------

@api("GET", "POST")
def products(request):
    o = request.owner
    if request.method == "GET":
        qs = m.Product.objects.filter(owner=o).select_related("supplier")
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        return ok([s_product(p) for p in qs])
    name = text(request.data, "name")
    if not name:
        return fail("name is required.")
    if m.Product.objects.filter(owner=o, name__iexact=name).exists():
        return fail("That product already exists.", 409)
    p = m.Product.objects.create(
        owner=o, name=name, category=text(request.data, "category", "General", 80),
        price=money(request.data, "price"), cost=money(request.data, "cost"),
        target_stock=whole(request.data, "target_stock", 60),
        supplier=supplier_named(o, request.data.get("supplier")),
    )
    return ok(s_product(p), 201)


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
        p.save()
    return ok(s_product(p))


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
    rows = (
        m.Customer.objects.filter(owner=request.owner)
        .annotate(orders=Count("sales"), spent=Sum("sales__amount"), last=Max("sales__date"))
        .order_by("-spent")
    )
    out = []
    for c in rows:
        items = (
            m.Sale.objects.filter(customer=c).exclude(product=None).values_list("product__name", flat=True).distinct()
        )
        out.append({"id": c.id, "name": c.name, "orders": c.orders, "spent": c.spent or 0, "last_purchase": c.last, "products": list(items)})
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
        return ok([s_sale(s) for s in qs[:500]])
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
    return ok(s_sale(sale), 201)


@api("PATCH")
def sale_detail(request, pk):
    sale = mine(m.Sale, request.owner, pk)
    status = request.data.get("status")
    if status not in (m.Sale.PAID, m.Sale.PENDING):
        return fail("status must be Paid or Pending.")
    sale.status = status
    sale.save(update_fields=["status"])
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
        return ok({
            "items": [{"id": e.id, "category": e.category, "amount": e.amount, "date": e.date} for e in qs[:500]],
            "by_category": list(by_cat), "total": qs.aggregate(t=Sum("amount"))["t"] or 0,
        })
    e = m.Expense.objects.create(
        owner=o, category=text(request.data, "category", "General", 80), amount=money(request.data, "amount")
    )
    return ok({"id": e.id, "category": e.category, "amount": e.amount, "date": e.date}, 201)


# ---------- stock ----------

@api("GET")
def stock(request):
    return ok([s_product(p) for p in m.Product.objects.filter(owner=request.owner).select_related("supplier")])


@api("GET")
def batches(request):
    qs = m.StockBatch.objects.filter(owner=request.owner, quantity_left__gt=0).select_related("product", "supplier")
    rows = [s_batch(b) for b in qs]
    if request.GET.get("slow") is not None:
        try:
            limit = int(request.GET.get("min_age", 45))
        except ValueError:
            return fail("min_age must be a whole number.")
        rows = sorted((b for b in rows if b["age_days"] > limit), key=lambda b: -b["age_days"])
    return ok(rows)


@api("GET", "POST")
def purchases(request):
    o = request.owner
    if request.method == "GET":
        return ok([s_purchase(p) for p in m.Purchase.objects.filter(owner=o).select_related("product", "supplier")])
    product = mine(m.Product, o, request.data.get("product_id"))
    qty = whole(request.data, "quantity", max(product.target_stock - svc.stock_of(product), 1))
    p = m.Purchase.objects.create(
        owner=o, product=product, supplier=product.supplier, quantity=qty,
        unit_cost=money(request.data, "unit_cost", required=False) or product.cost,
    )
    return ok(s_purchase(p), 201)


@api("POST")
def purchase_receive(request, pk):
    p = mine(m.Purchase, request.owner, pk)
    if p.status == m.Purchase.DELIVERED:
        return fail("This order was already received.", 409)
    svc.receive_stock(request.owner, product=p.product, quantity=p.quantity, unit_cost=p.unit_cost, supplier=p.supplier, purchase=p)
    p.refresh_from_db()
    return ok(s_purchase(p))


@api("POST")
def receive(request):
    o, d = request.owner, request.data
    qty, cost = whole(d, "quantity"), money(d, "unit_cost")
    supplier = supplier_named(o, d.get("supplier"))
    if d.get("product_id"):
        product = mine(m.Product, o, d["product_id"])
    else:
        name = text(d, "new_product_name")
        if not name:
            return fail("Choose a product or give the new product a name.")
        if m.Product.objects.filter(owner=o, name__iexact=name).exists():
            return fail("That product already exists. Choose it from the list.", 409)
        product = m.Product.objects.create(
            owner=o, name=name, category="General", price=money(d, "price"), cost=cost, supplier=supplier
        )
    batch = svc.receive_stock(o, product=product, quantity=qty, unit_cost=cost, supplier=supplier)
    return ok(s_batch(batch), 201)


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
    cur["change_vs_previous_pct"] = {k: change(k) for k in ("revenue", "gross_profit", "expenses", "net_profit")}
    cur["forecast"] = svc.forecast(cur)
    cur["pending_payments"] = {"count": pending["n"], "total": pending["t"] or 0}
    cur["low_stock"] = [p["name"] for p in map(s_product, m.Product.objects.filter(owner=o)) if p["low_stock"]]
    cur["slow_batches"] = sum(
        1 for b in m.StockBatch.objects.filter(owner=o, quantity_left__gt=0) if b.age_days > 45
    )
    return ok(cur)


@api("GET")
def reports(request):
    first = m.Sale.objects.filter(owner=request.owner).order_by("date").values_list("date", flat=True).first()
    today = timezone.localdate()
    y, mo = (first.year, first.month) if first else (today.year, today.month)
    rows = []
    while (y, mo) <= (today.year, today.month):
        s = svc.month_summary(request.owner, y, mo)
        rows.append({k: s[k] for k in ("month", "revenue", "expenses", "gross_profit", "net_profit")})
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return ok(rows)


@api("GET")
def insights(request):
    return ok(svc.insights(request.owner))
