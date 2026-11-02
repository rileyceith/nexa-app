# Nexa backend (Django)

JSON API for the Nexa dashboard. Dependencies: Django only.

## Run

```powershell
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo you@email.com   # optional sample data
python manage.py runserver                 # http://127.0.0.1:8000
python manage.py test
```

Sign-in is passwordless. `POST /api/auth/request-link/` emails a one-time link (printed to the
console in development); `POST /api/auth/verify/` with the link's `token` returns an API token.
Send it on every other request as `Authorization: Bearer <token>`. All data is scoped to the signed-in user.

## Endpoints (all under `/api/`)

| Method | Path | Purpose |
|---|---|---|
| POST | `auth/request-link/` `{email}` | Email a sign-in link |
| POST | `auth/verify/` `{token}` | Exchange link token for an API token |
| POST | `auth/logout/` | Revoke the current token |
| GET | `me/` | Current user |
| GET, POST | `products/` | List (`?q=`) / create `{name, price, cost, category, target_stock, supplier}` |
| GET, PATCH | `products/<id>/` | Read / update |
| GET, POST | `suppliers/` | List / create |
| GET | `customers/` | Orders, spend, last purchase, products bought |
| GET, POST | `sales/` | List (`?status=Paid\|Pending&q=`) / record `{customer, amount, status, product_id, quantity}` |
| PATCH | `sales/<id>/` `{status}` | Mark paid / pending |
| GET, POST | `expenses/` | List (`?month=2026-10`, with category totals) / record `{category, amount}` |
| GET | `stock/` | Products with stock level and low-stock flag |
| GET | `batches/` | Batches in stock (`?slow&min_age=45` for slow stock) |
| GET, POST | `purchases/` | List / reorder `{product_id, quantity?, unit_cost?}` |
| POST | `purchases/<id>/receive/` | Receive an order into stock |
| POST | `receive/` | Receive stock `{product_id \| new_product_name+price, quantity, unit_cost, supplier}` |
| GET | `dashboard/?month=2026-10` | KPIs, change vs previous month, weekly sales, top products, forecast |
| GET | `reports/` | Month-by-month results |
| GET | `insights/` | Generated recommendations |

Notes: money values are returned as strings. A sale linked to a product takes stock from the oldest
batch first and uses the real batch cost for cost of goods; unlinked sales use a 60% cost estimate.

## Configuration (environment variables)

`NEXA_DEBUG` (default `1`), `NEXA_SECRET_KEY` (required when debug is `0`), `NEXA_ALLOWED_HOSTS`,
`NEXA_CORS_ORIGINS` (default allows `null`, i.e. the page opened from `file://`, and localhost dev ports),
`NEXA_FRONTEND_URL` (base of the magic link), `NEXA_EMAIL_BACKEND`, `NEXA_FROM_EMAIL`.
