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

Sign in with `POST /api/auth/login/` (`username`, `password`), or create an account with
`POST /api/auth/register/`. Both return an API token. A passwordless alternative also exists:
`POST /api/auth/request-link/` emails a one-time link (printed to the console in development), and
`POST /api/auth/verify/` with the link's `token` returns an API token.
Send it on every other request as `Authorization: Bearer <token>`. All data is scoped to the signed-in user.

## Endpoints (all under `/api/`)

| Method | Path | Purpose |
|---|---|---|
| POST | `auth/register/` `{username, password, password2, accepted_terms}` | Create an account (returns 201 and a token) |
| POST | `auth/login/` `{username, password}` | Sign in with a username and password |
| POST | `auth/request-link/` `{email}` | Email a sign-in link |
| POST | `auth/verify/` `{token}` | Exchange link token for an API token |
| POST | `auth/logout/` | Revoke the current token |
| GET | `me/` | Current user |
| GET, POST | `products/` | List (`?q=`) / create `{name, price, cost, category, target_stock, supplier}` |
| GET, PATCH | `products/<id>/` | Read / update (`image` sets or clears the photo, 1 MB max) |
| GET, POST | `suppliers/` | List / create |
| GET | `customers/` | Orders, spend, last purchase, products bought |
| GET, POST | `sales/` | List (`?status=Paid\|Pending&q=`) / record `{customer, amount, status, product_id, quantity}` |
| PATCH | `sales/<id>/` `{status}` | Mark paid / pending |
| GET, POST | `expenses/` | List (`?month=2026-10`, with category totals) / record `{category, amount}` |
| GET | `stock/` | Products with stock level and low-stock flag |
| GET | `batches/` | Batches in stock (`?slow&min_age=45` for slow stock) |
| GET, POST | `purchases/` | List / reorder `{product_id, quantity?, unit_cost?}` |
| POST | `purchases/<id>/receive/` | Receive an order into stock |
| POST | `receive/` | Receive stock `{product_id \| new_product_name+price, quantity, unit_cost, supplier, image?}`; `image` is an optional data URL (PNG, JPEG, WebP or GIF, 1 MB max) |
| GET | `dashboard/?month=2026-10` | KPIs, change vs previous month, weekly sales, top products, forecast |
| GET | `reports/` | Month-by-month results |
| GET | `insights/` | Generated recommendations |
| POST | `assistant/chat/` `{question, month?}` | Ask about verified, aggregated financial data |
| POST | `assistant/analyze/` `{analysis, month?}` | Deterministic profitability, sales trend, expense, product, or stock cover analysis |
| GET, PATCH | `settings/` `{revenue_goal?, goal_period?}` | Revenue goal (`day`, `week`, `month`, or `year`); `null` clears it. Returns the goal and its progress for the current period |
| GET | `settings/series/` | Overview chart buckets for the goal period: `{period, target, current, buckets}` (each bucket has `start`, `end`, `amount`), or `null` without a goal. Counts every sale, with no row limit |

Notes: money values are returned as strings. A sale linked to a product takes stock from the oldest
batch first and uses the real batch cost for cost of goods; unlinked sales use a 60% cost estimate.

## Configuration (environment variables)

`NEXA_DEBUG` (default `1`), `NEXA_SECRET_KEY` (required when debug is `0`), `NEXA_ALLOWED_HOSTS`,
`NEXA_CORS_ORIGINS` (default allows `null`, i.e. the page opened from `file://`, and localhost dev ports),
`NEXA_FRONTEND_URL` (base of the magic link), `NEXA_EMAIL_BACKEND`, `NEXA_FROM_EMAIL`.

The assistant requires `NEXA_OPENAI_API_KEY`; `NEXA_OPENAI_MODEL` defaults to `gpt-4o-mini`.
Keep the key in the server environment and never in frontend code. The assistant sends the user's
question and an owner-scoped monthly aggregate (not customer details or individual transactions)
to the configured OpenAI API. Names and record identifiers are excluded, and conversation
history is not persisted. Deterministic analyses run without an AI provider and use owner-scoped
Django queries for profitability ratios, six-month sales trends and moving averages, expense
category comparisons, and product revenue rankings.
