# Nexa backend (Django)

JSON API for the Nexa dashboard. Dependencies are listed in `requirements.txt`: Django, plus gunicorn, psycopg and dj-database-url for deployment.

## Run

```powershell
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py createcachetable
python manage.py seed_demo you@email.com   # optional sample data
python manage.py runserver                 # http://127.0.0.1:8000 (also serves the frontend and /admin/)
python manage.py test
```

From the project root, `.\dev.ps1` does the migrate, cache table and server steps for you and first stops any old server on port 8000.

Migration `0007` moves product photos that were stored in the database into files under `NEXA_MEDIA_ROOT`. Run `migrate` after pulling this change.

Migration `0009` enforces case-insensitive unique usernames and unique nonblank email addresses
(ignoring surrounding spaces and case). Back up the database before migrating. If existing accounts
conflict, migration stops without merging or deleting them; resolve the conflicts and rerun it.
The identity indexes support SQLite and PostgreSQL. Their case handling follows the database's
`LOWER` implementation; SQLite only folds ASCII characters, so legacy non-ASCII email addresses
need special care when checking for duplicates or signing in by email.

Sign in with `POST /api/auth/login/` (`username`, `password`), or create an account with
`POST /api/auth/register/`. Both return an API token. A passwordless alternative also exists:
`POST /api/auth/request-link/` emails a one-time link (printed to the console in development), and
`POST /api/auth/verify/` with the link's `token` returns an API token.
Send it on every other request as `Authorization: Bearer <token>`. All data is scoped to the signed-in user.

Registration creates the user, default settings, terms acceptance and token in one transaction;
inventory starts empty. Usernames for new password accounts use 3–30 ASCII letters, digits, dots,
dashes or underscores. An email address identifies one account: a magic link signs in to that account
or creates an empty one if it does not exist. Repeated registration returns 409 rather than replaying
the original token; after an interrupted response, sign in instead. Passwords are hashed by Django;
profile and financial fields are not encrypted individually. Production deployments must configure
HTTPS, protected email delivery and encryption at rest for the database, backups and media.

## Endpoints (all under `/api/`)

| Method | Path | Purpose |
|---|---|---|
| POST | `auth/register/` `{username, email, password, password2, accepted_terms}` | Create an account (returns 201 and a token) |
| POST | `auth/login/` `{username, password}` | Sign in with a username and password |
| POST | `auth/request-link/` `{email}` | Email a sign-in link |
| POST | `auth/verify/` `{token}` | Exchange link token for an API token |
| POST | `auth/logout/` | Revoke the current token |
| GET | `me/` | Current user: `{id, username, email, is_staff}`. The dashboard shows an **Admin** button (a link to `/admin/`) only when `is_staff` is true |
| GET, POST | `products/` | List (`?q=`) / create `{name, price, cost, category, target_stock, supplier}` |
| GET, PATCH | `products/<id>/` | Read / update (`image` sets or clears the photo, 1 MB max). Responses carry `image_url` instead of the image data |
| GET | `images/<key>/?size=120\|400\|1000` | Public WebP product photo. Use the `image_url` from a product. Default size 400 |
| GET, POST | `suppliers/` | List / create |
| GET | `customers/` | Orders, spend, last purchase, products bought |
| GET, POST | `sales/` | List (`?status=Paid\|Pending&q=`) / record `{customer, amount, status, product_id, quantity}` |
| PATCH | `sales/<id>/` `{status}` | Mark paid / pending |
| GET, POST | `expenses/` | List (`?month=2026-10`, with category totals) / record `{category, amount}` |
| GET | `stock/` | Products with stock level and low-stock flag |
| GET | `batches/` | Batches in stock (`?slow&min_age=45` for slow stock) |
| GET, POST | `purchases/` | List / reorder `{product_id, quantity?, unit_cost?}` |
| POST | `purchases/<id>/receive/` | Receive an order into stock |
| POST | `receive/` | Receive stock `{product_id \| new_product_name+price, quantity, unit_cost, supplier, image?}`; a new-product name matching an existing product adds stock to that product. `image` is an optional data URL (PNG, JPEG, WebP or GIF, 1 MB max) |
| GET | `dashboard/?month=2026-10` | KPIs, change vs previous month, weekly sales, top products, forecast |
| GET | `reports/` | Month-by-month results |
| GET | `insights/` | Generated recommendations |
| POST | `assistant/chat/` `{question, month?}` | Ask about verified, aggregated financial data |
| POST | `assistant/analyze/` `{analysis, month?}` | Deterministic analysis: `profitability`, `sales_trends`, `expense_analysis`, `product_rankings`, `stock_cover`, `reorder_planning`, `aging_inventory`, `break_even`, `customer_concentration`, or `cash_indicators`. See [algorithm details](../docs/APP_DOCUMENTATION.md#algorithm-analyses) for assumptions and limitations. |
| GET, PATCH | `settings/` `{revenue_goal?, goal_period?}` | Revenue goal (`day`, `week`, `month`, or `year`); `null` clears it. Returns the goal and its progress for the current period |
| GET | `settings/series/` | Overview chart buckets for the goal period: `{period, target, current, buckets}` (each bucket has `start`, `end`, `amount`), or `null` without a goal. Counts every sale, with no row limit |

Notes: money values are returned as strings with two decimal places, including zero totals (`"0.00"`). A sale linked to a product takes stock from the oldest
batch first and uses the real batch cost for cost of goods; unlinked sales use a 60% cost estimate.
Paging: `products/`, `sales/`, `expenses/`, `batches/`, and `purchases/` accept `?limit=` and `?offset=`.
Responses carry an `X-Total-Count` header with the full count. Without `limit`, `products/`, `batches/`,
and `purchases/` return every row, and `sales/` and `expenses/` return at most 500. `limit` is capped at 500.
Negative or non-numeric values return 400.
JSON responses are gzip-compressed when the client sends `Accept-Encoding: gzip`.
Unexpected server errors return `{"error": ...}` with status 500 and are logged to the console. They are not HTML pages.

## Configuration (environment variables)

`NEXA_DEBUG` (default `1`), `NEXA_SECRET_KEY` (required when debug is `0`), `NEXA_ALLOWED_HOSTS`,
`NEXA_CORS_ORIGINS` (default allows `null`, i.e. the page opened from `file://`, and localhost dev ports),
`NEXA_CORS_ALLOW_LOCAL_DEV` (default on in debug: any `localhost` or `127.0.0.1` port may call the API),
`NEXA_SERVE_FRONTEND` (default on in debug: serves `frontend/Nexa.html` at `/`),
`NEXA_FRONTEND_URL` (base of the magic link), `NEXA_EMAIL_BACKEND`, `NEXA_FROM_EMAIL`,
`NEXA_DATABASE_URL` (PostgreSQL URL; SQLite `db.sqlite3` is used when unset), `NEXA_MEDIA_ROOT` (folder for product photos; default `media/` in the backend folder).

The assistant requires `NEXA_AI_API_KEY` (a Google Gemini API key). `NEXA_AI_MODEL` defaults to `gemini-3.8-flash`, and `NEXA_AI_BASE_URL` defaults to Google's OpenAI-compatible endpoint.
Keep the key in the server environment and never in frontend code. The assistant sends the user's
question and an owner-scoped monthly aggregate (not customer details or individual transactions)
to the configured AI provider (Google Gemini by default). Names and record identifiers are excluded, and conversation
history is not persisted. Deterministic analyses run without an AI provider and use owner-scoped
Django queries for profitability ratios, six-month sales trends and moving averages, expense
category comparisons, and product revenue rankings.

## Deployment (Render + Cloudflare Pages)

**Backend (Render Blueprint)**

- The repository root has `render.yaml`. In Render, choose **New > Blueprint** and select this repository. It creates the `nexa-api` web service (root directory `backend`) and the `nexa-db` PostgreSQL database, sets the variables below, and connects `NEXA_DATABASE_URL` to the database.
- The database uses the paid `basic-256mb` plan. Render's free PostgreSQL expires after 30 days, and its data is deleted 14 days after that.
- Product photos are stored on a 1 GB disk mounted at `/var/data`. A Render disk allows only one instance, and each deploy restarts the service briefly.
- Build: `pip install -r requirements.txt`. Start: `python manage.py migrate --noinput && python manage.py createcachetable && gunicorn nexa.wsgi --bind 0.0.0.0:$PORT`. Migrations run at start because a pre-deploy command cannot see the persistent disk.
- Variables (the Blueprint sets these; for a manual setup, set them yourself):

  ```
  NEXA_DEBUG=0
  NEXA_SECRET_KEY=<long random string>
  NEXA_ALLOWED_HOSTS=api.Nexa-app.com,nexa-api.onrender.com
  NEXA_CORS_ORIGINS=https://app.Nexa.com
  NEXA_FRONTEND_URL=https://app.Nexa.com/Nexa.html
  NEXA_DATABASE_URL=<Render Postgres internal URL>
  NEXA_MEDIA_ROOT=/var/data/media
  ```

- Add `api.Nexa-app.com` as a custom domain in Render, then add the CNAME record it shows at your DNS provider.
- Sign-in links are printed to the Render logs until `NEXA_EMAIL_BACKEND` and SMTP settings are configured. Password sign-in works without email.

**Frontend (Cloudflare Pages)**

- Connect the GitHub repository. Leave the build command empty and set the build output directory to `frontend`.
- Add `app.Nexa.com` as a custom domain.
- `frontend/Nexa.html` calls `https://api.Nexa-app.com/api` unless it is opened from localhost or `file://`.
