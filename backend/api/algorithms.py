from calendar import month_abbr
from datetime import date
from decimal import Decimal
from math import ceil

from django.db.models import Sum
from django.utils import timezone

from . import models as m
from .services import CENTS, month_bounds, month_summary, previous_month

ANALYSES = {
    "profitability": "Profitability",
    "sales_trends": "Sales trends",
    "expense_analysis": "Expense analysis",
    "product_rankings": "Product rankings",
    "stock_cover": "Stock cover",
}

# Assumed supplier lead time: reorder when cover drops below this many days.
STOCK_LEAD_DAYS = 14
STOCK_TARGET_DAYS = 30
STOCK_STATUS_ORDER = {"Out of stock": 0, "Reorder now": 1, "Watch": 2, "No sales this period": 3, "Healthy": 4}


def _amount(value):
    return str(value.quantize(CENTS))


def _percent(value, total):
    return str((value / total * 100).quantize(Decimal("0.1"))) if total else None


def _change(current, previous):
    return str(((current - previous) / previous * 100).quantize(Decimal("0.1"))) if previous else None


def _profitability(owner, year, month):
    current = month_summary(owner, year, month)
    previous = month_summary(owner, *previous_month(year, month))
    revenue = current["revenue"]
    prior_revenue = previous["revenue"]
    metrics = [
        {"label": "Revenue", "value": _amount(revenue), "format": "currency"},
        {"label": "Gross profit", "value": _amount(current["gross_profit"]), "format": "currency"},
        {"label": "Net profit", "value": _amount(current["net_profit"]), "format": "currency"},
        {"label": "Gross margin", "value": _percent(current["gross_profit"], revenue), "format": "percent"},
        {"label": "Net margin", "value": _percent(current["net_profit"], revenue), "format": "percent"},
        {"label": "Expense ratio", "value": _percent(current["expenses"], revenue), "format": "percent"},
        {"label": "Revenue growth", "value": _change(revenue, prior_revenue), "format": "change"},
    ]
    insights = []
    growth = _change(revenue, prior_revenue)
    if growth is None:
        insights.append("There is no previous-month revenue baseline for comparison.")
    else:
        direction = "increased" if Decimal(growth) > 0 else "decreased" if Decimal(growth) < 0 else "was unchanged"
        insights.append(f"Revenue {direction} by {abs(Decimal(growth))}% compared with {previous['month']}.")
    if revenue:
        insights.append(
            f"Net profit was {_amount(current['net_profit'])}, a "
            f"{_percent(current['net_profit'], revenue)}% margin."
        )
    else:
        insights.append("No revenue was recorded in this period, so profit margins cannot be calculated.")
    return {"period": current["month"], "title": ANALYSES["profitability"], "metrics": metrics, "insights": insights}


def _sales_trends(owner, year, month):
    end = month_bounds(year, month)[1]
    month_starts = []
    y, mo = year, month
    for _ in range(6):
        month_starts.append(date(y, mo, 1))
        y, mo = previous_month(y, mo)
    month_starts.reverse()
    totals = {
        (row["date__year"], row["date__month"]): row["total"] or Decimal(0)
        for row in m.Sale.objects.filter(owner=owner, date__range=(month_starts[0], end))
        .values("date__year", "date__month")
        .annotate(total=Sum("amount"))
    }
    values = [totals.get((start.year, start.month), Decimal(0)) for start in month_starts]
    series = []
    for index, (start, revenue) in enumerate(zip(month_starts, values)):
        window = values[max(0, index - 2):index + 1]
        moving_average = sum(window, Decimal(0)) / len(window)
        series.append({
            "period": f"{start.year}-{start.month:02d}",
            "label": f"{month_abbr[start.month]} {str(start.year)[-2:]}",
            "revenue": _amount(revenue),
            "moving_average": _amount(moving_average),
        })
    growth = _change(values[-1], values[-2])
    if growth is None:
        trend_insight = "There is no previous-month sales baseline for comparison."
    elif Decimal(growth) > 0:
        trend_insight = f"Sales increased by {growth}% compared with the previous month."
    elif Decimal(growth) < 0:
        trend_insight = f"Sales decreased by {abs(Decimal(growth))}% compared with the previous month."
    else:
        trend_insight = "Sales were unchanged compared with the previous month."
    insights = [trend_insight]
    insights.append(f"The latest three-month moving average is {_amount(sum(values[-3:], Decimal(0)) / len(values[-3:]))}.")
    return {
        "period": f"{year}-{month:02d}",
        "title": ANALYSES["sales_trends"],
        "metrics": [
            {"label": "This month", "value": _amount(values[-1]), "format": "currency"},
            {"label": "Previous month", "value": _amount(values[-2]), "format": "currency"},
            {"label": "Month-over-month", "value": growth, "format": "change"},
            {"label": "3-month moving average", "value": _amount(sum(values[-3:], Decimal(0)) / len(values[-3:])), "format": "currency"},
        ],
        "series": series,
        "insights": insights,
    }


def _expense_analysis(owner, year, month):
    start, end = month_bounds(year, month)
    previous_start, previous_end = month_bounds(*previous_month(year, month))

    def grouped(start_date, end_date):
        rows = m.Expense.objects.filter(owner=owner, date__range=(start_date, end_date))
        return {
            row["category"]: row["total"] or Decimal(0)
            for row in rows.values("category").annotate(total=Sum("amount"))
        }

    current = grouped(start, end)
    previous = grouped(previous_start, previous_end)
    total = sum(current.values(), Decimal(0))
    categories = []
    for category in sorted(set(current) | set(previous), key=lambda name: current.get(name, Decimal(0)), reverse=True):
        amount = current.get(category, Decimal(0))
        prior = previous.get(category, Decimal(0))
        categories.append({
            "category": category,
            "amount": _amount(amount),
            "previous_amount": _amount(prior),
            "change_pct": _change(amount, prior),
            "share_pct": _percent(amount, total),
        })
    insights = []
    if not total:
        insights.append("No expenses were recorded in this period.")
    else:
        largest = categories[0]
        insights.append(
            f"{largest['category']} is the largest expense category at "
            f"{largest['share_pct']}% of this month's recorded expenses."
        )
    changes = [row for row in categories if row["change_pct"] is not None]
    if changes:
        largest_change = max(changes, key=lambda row: abs(Decimal(row["change_pct"])))
        change = Decimal(largest_change["change_pct"])
        if change:
            direction = "increased" if change > 0 else "decreased"
            insights.append(
                f"{largest_change['category']} {direction} by {abs(change)}% versus the previous month."
            )
        else:
            insights.append(f"{largest_change['category']} was unchanged versus the previous month.")
    return {
        "period": f"{year}-{month:02d}",
        "title": ANALYSES["expense_analysis"],
        "metrics": [
            {"label": "Total expenses", "value": _amount(total), "format": "currency"},
            {"label": "Categories", "value": str(len(current)), "format": "count"},
        ],
        "categories": categories,
        "insights": insights,
    }


def _product_rankings(owner, year, month):
    start, end = month_bounds(year, month)
    rows = (
        m.Sale.objects.filter(owner=owner, product__isnull=False, date__range=(start, end))
        .values("product__name")
        .annotate(revenue=Sum("amount"), units=Sum("quantity"), cogs=Sum("cogs"))
        .order_by("-revenue", "product__name")
    )
    linked_revenue = sum((row["revenue"] or Decimal(0) for row in rows), Decimal(0))
    products = []
    for rank, row in enumerate(rows[:10], start=1):
        revenue = row["revenue"] or Decimal(0)
        products.append({
            "rank": rank,
            "product": row["product__name"],
            "units": row["units"] or 0,
            "revenue": _amount(revenue),
            "gross_profit": _amount(revenue - (row["cogs"] or Decimal(0))),
            "share_pct": _percent(revenue, linked_revenue),
        })
    insights = (
        [f"{products[0]['product']} leads linked-product sales with {_amount(Decimal(products[0]['revenue']))} in revenue."]
        if products else ["No product-linked sales were recorded in this period."]
    )
    return {
        "period": f"{year}-{month:02d}",
        "title": ANALYSES["product_rankings"],
        "metrics": [
            {"label": "Products sold", "value": str(len(products)), "format": "count"},
            {"label": "Product-linked revenue", "value": _amount(linked_revenue), "format": "currency"},
        ],
        "products": products,
        "insights": insights,
    }


def _stock_cover(owner, year, month):
    start, end = month_bounds(year, month)
    days = max(0, (min(end, timezone.localdate()) - start).days + 1)
    sold = {
        row["product_id"]: row["units"]
        for row in m.Sale.objects.filter(owner=owner, product__isnull=False, date__range=(start, end))
        .values("product_id").annotate(units=Sum("quantity"))
    }
    rows = []
    for product in m.Product.objects.filter(owner=owner).annotate(stock=Sum("batches__quantity_left")):
        stock = product.stock or 0
        units = sold.get(product.id, 0)
        rate = Decimal(units) / days if days and units else None
        cover = Decimal(stock) / rate if rate else None
        if stock == 0:
            status = "Out of stock"
        elif rate is None:
            status = "No sales this period"
        elif cover < STOCK_LEAD_DAYS:
            status = "Reorder now"
        elif cover < STOCK_TARGET_DAYS:
            status = "Watch"
        else:
            status = "Healthy"
        rows.append({
            "product": product.name, "stock": stock, "units_sold": units,
            "daily_rate": str(rate.quantize(Decimal("0.1"))) if rate else None,
            "days_cover": str(cover.quantize(Decimal("0.1"))) if cover is not None else None,
            "status": status,
            "reorder_qty": max(0, ceil(rate * STOCK_TARGET_DAYS) - stock) if rate else 0,
        })
    rows.sort(key=lambda r: (STOCK_STATUS_ORDER[r["status"]], Decimal(r["days_cover"] or "0"), r["product"]))
    urgent = [r for r in rows if r["status"] in ("Out of stock", "Reorder now")]
    insights = []
    if not rows:
        insights.append("Add products and receive stock to see stock cover.")
    elif days == 0:
        insights.append(f"{year}-{month:02d} has not started yet, so there are no sales to measure.")
    else:
        insights.append(
            f"Sales rates use {days} day(s) of {year}-{month:02d}. Reorder when cover is under "
            f"{STOCK_LEAD_DAYS} days, aiming for {STOCK_TARGET_DAYS} days."
        )
    for row in urgent[:3]:
        if row["status"] == "Out of stock":
            insights.append(f"{row['product']} is out of stock.")
        else:
            insights.append(f"{row['product']} has {row['days_cover']} days of cover. Reorder about {row['reorder_qty']} units.")
    if rows and days and not urgent:
        insights.append("No product needs a reorder at the current sales rate.")
    return {
        "period": f"{year}-{month:02d}",
        "title": ANALYSES["stock_cover"],
        "metrics": [
            {"label": "Products tracked", "value": str(len(rows)), "format": "count"},
            {"label": "Need reorder", "value": str(len(urgent)), "format": "count"},
            {"label": "Units sold", "value": str(sum(sold.values())), "format": "count"},
        ],
        "stock": rows,
        "insights": insights,
    }


def analyze(owner, analysis, year, month):
    handlers = {
        "profitability": _profitability,
        "sales_trends": _sales_trends,
        "expense_analysis": _expense_analysis,
        "product_rankings": _product_rankings,
        "stock_cover": _stock_cover,
    }
    if analysis not in handlers:
        raise ValueError("Choose a supported algorithm analysis.")
    return handlers[analysis](owner, year, month)
