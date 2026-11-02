# Nexa Application Documentation

Nexa is a business dashboard for tracking sales, stock, purchases, customers, and expenses. It has two parts:

- **Frontend**: a single HTML file with a React interface, opened directly in a browser.
- **Backend**: a Django JSON API with SQLite storage. All data is scoped to the signed-in user.

It also includes a financial intelligence layer with two engines. The **Algorithm engine** runs deterministic calculations and works without any AI service. The **AI engine** answers questions in natural language, using aggregated figures from the same data.

> **Status note:** This document describes the current behavior of the code. Section [Known limitations](#known-limitations) lists the places where the browser UI and the API differ. Read that section before relying on a feature.

## Contents

1. [Quick start](#quick-start)
2. [Accounts and sign-in](#accounts-and-sign-in)
3. [Using the app](#using-the-app)
4. [Calculation rules](#calculation-rules)
5. [Financial intelligence](#financial-intelligence)
6. [Project structure](#project-structure)
7. [API reference](#api-reference)
8. [Data model](#data-model)
9. [Configuration](#configuration)
10. [Testing](#testing)
11. [Known limitations](#known-limitations)

---

## Quick start

Requirements: Python 3 and PowerShell on Windows. Run these commands from the project root.

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo you@email.com   # optional: sample data for this account
python manage.py runserver 127.0.0.1:8000
```

Leave the server running. Then open `frontend/Nexa.html` in a browser. The page connects to `http://localhost:8000/api` by default. You can change this by setting `window.NEXA_API` before the app script loads.

The development settings are not for production. Debug mode is on by default. See [Configuration](#configuration).

---

## Accounts and sign-in

### Creating an account in the browser

The sign-up form asks for a username, password, password confirmation, and acceptance of the terms.

- **Username**: 3 to 30 characters, using letters, digits, `.`, `_`, and `-`. An email address is not allowed.
- **Password**: must pass the password validators configured in [settings.py](../backend/nexa/settings.py).
- **Terms**: must be accepted. The acceptance is recorded.

### Sign-in rules

- Use the username and password. A session token is stored in the browser under the key `nexa_token`. The app checks it with `GET /api/me/` when the page loads, and signs you in again if the token is still valid.
- Each token is valid for 30 days. Signing out revokes the token on the server.
- After **5 failed sign-in attempts within 15 minutes**, the account is locked for further attempts. The API returns `429`.

### Passwordless sign-in (API only)

The API also supports a one-time sign-in link:

1. `POST /api/auth/request-link/` with `{"email": "..."}`. The response is the same whether or not the address is known. In development, the link is printed to the server console.
2. `POST /api/auth/verify/` with `{"token": "<token from the link>"}`. This returns an API token.

A link expires after 15 minutes. Each email address can request at most 5 links per hour. An account created through this flow gets an unusable password, so it can sign in again only through a new link. The browser UI does not yet handle this flow. See [Known limitations](#known-limitations).

### Demo accounts

`python manage.py seed_demo <email>` creates an account whose username is the email address, with an unusable password. The browser sign-in form therefore **cannot** sign in to this account. To use the seeded data in the browser:

1. Request a link: `POST /api/auth/request-link/` with `{"email": "you@email.com"}`.
2. Copy the `token` value from the link printed in the server console.
3. Exchange it: `POST /api/auth/verify/` with `{"token": "<that token>"}`. Copy the `token` field from the response.
4. In the browser's developer console on `Nexa.html`, run `localStorage.setItem('nexa_token', '<token from step 3>')`, then reload the page.

---

## Using the app

The sidebar has these pages:

| Page | What it is for | Backed by the API today? |
|---|---|---|
| Overview | Dashboard figures for the month: KPIs, weekly sales, top products, and forecast | **Yes**: the KPIs, weekly sales, top products, and forecast load from `dashboard/?month=`. Expenses, sales, and reports come from `expenses/`, `sales/`, and `reports/`. These load when the page opens and again after each sale or expense. The Revenue ring and caption use the saved revenue goal from `settings/`. When a revenue goal is set, the sales chart loads its buckets from `settings/series/` and changes shape with the goal period, with a dashed target marker. A day goal shows each day of the current month, with the goal as the target. A week goal shows the last 8 Monday-to-Sunday weeks, with the goal as the target. A month goal shows the last 6 calendar months, with the goal as the target. A year goal shows the 12 months of the current year, with the goal divided by 12 as the monthly target. Future periods show the target marker with no bar. Bars can rise above the target marker. With no goal, the chart shows the last four weeks and a next-week forecast bar. The low-stock warning uses the loaded stock. |
| Settings | Light or dark theme (local only), and a revenue goal for a day, week, month, or year. Progress counts every sale in the period, paid and pending, and shows the amount left and the period dates. The goal also sets the target and the period shown on the Overview sales chart (see Overview). | **Yes** for the revenue goal: it loads from `settings/` and `settings/series/` when the page opens, saves with `PATCH /api/settings/`, and then reloads both. The theme is local only. |
| Sales | Record a sale: customer, amount, Paid or Pending status, and an optional product with quantity. A product sale takes that quantity from stock straight away, oldest batch first. Out-of-stock products cannot be chosen. | **Yes**: records are saved with `POST /api/sales/`. The list is not reloaded from the API. |
| Products | Products, prices, costs, and target stock | Partly. The list loads from `products/` when the page opens. Suppliers are not loaded from `suppliers/`, and the page has no create or edit form. |
| Stock | Stock level per product, reorders, and low-stock warnings | **Yes**: products, batches, and purchases load from `products/`, `batches/`, and `purchases/` when the page opens. Reorder saves a purchase with `POST /api/purchases/`. |
| Receive stock | Record a delivery into stock with its cost, supplier, and an optional product photo. Mark open orders as received. | **Yes**: deliveries are saved with `POST /api/receive/`. Open orders and recent deliveries load when the page opens, and Mark received calls `POST /api/purchases/<id>/receive/`. |
| Slow stock | Stock batches that have been on hand for a long time | Partly. Batches load from `batches/` when the page opens, and the age filter runs in the browser. The API also provides `batches/?slow`, which the browser does not call. |
| Expenses | Record an expense: category and amount | **Yes**: records are saved with `POST /api/expenses/`, and the list and category totals load from `expenses/?month=` when the page opens. |
| Customers | Customer order counts and spend | Partly. Customers are built in the browser from the loaded sales list. The browser does not call `customers/`. |
| Reports | Results month by month | **Yes**: rows load from `reports/`, one per month from the first sale to the current month. |
| Insights | Algorithm analyses, the AI assistant chat, and recommendations | **Yes** for the analysis and chat. The recommendation list is not loaded from `insights/`. |

Sales, expenses, the Overview figures, and reports reload from the API when the page opens, so saved records appear after a reload. Products, stock, and receiving also reload from the API. Suppliers are not loaded from their API route. See [Known limitations](#known-limitations).

### Insights page

The Insights page has a selector with two modes:

- **Algorithms**: choose one of the analyses listed in [Algorithm analyses](#algorithm-analyses) and select **Run analysis**. The result is calculated on the server without AI.
- **AI assistant**: type a question. The reply is generated by the AI engine (see [AI engine](#ai-engine)). This needs `NEXA_OPENAI_API_KEY` on the server.

---

## Calculation rules

These rules apply to the API. They define how the figures are calculated.

### Sales and cost of goods

- **Revenue** is the sum of sale amounts dated within the month. It includes both Paid and Pending sales, so Pending sales count toward revenue, gross profit, and net profit.
- **Cost of goods (COGS)** is stored on each sale when it is recorded:
  - A sale linked to a product takes stock from the **oldest batch first** (FIFO). The cost is the real batch cost.
  - An unlinked sale uses an estimate: **60% of the sale amount** (`COGS_ESTIMATE_RATIO`).
- The browser's sale form sends the product and quantity when one is chosen, so those sales use the real batch cost. Sales without a product use the 60% estimate.

### Monthly results

| Figure | Formula |
|---|---|
| Gross profit | Revenue − COGS |
| Net profit | Gross profit − Expenses |

Monthly summaries also include **weekly sales** and **top products**:

- **Weekly sales** are four buckets: days 1–7, 8–14, 15–21, and 22 to the end of the month. The last bucket is longer in months with more than 28 days.
- **Top products** are ranked by units sold, using linked sales only, with a maximum of five.

### Forecast

The forecast uses three scenarios, each with a multiplier:

| Scenario | Multiplier |
|---|---|
| Conservative | 0.97 |
| Expected | 1.08 |
| Optimistic | 1.20 |

- **Next week** = last weekly bucket (days 22 to month end) × multiplier.
- **Next month** = the month's revenue × multiplier.

For the current month, the figures are based on sales so far, so the forecast is partial.

### Stock and warnings

- A product is **low on stock** when stock on hand ÷ target stock is below **0.35**. The default target stock is 60.
- A batch is **slow** when it still has stock and has been on hand for more than **45 days** (`slow_days`).
- **Pending payments** are sales with status Pending. The insight shows how many there are and their total.
- The **best margin** product has the highest value of (price − cost) ÷ price.

### Recommendations (`insights/`)

Recommendations are returned in this priority order: High, Medium, Low.

| Category | Priority | Condition |
|---|---|---|
| Stock | High | Product is below the 0.35 stock ratio. The text includes a runway estimate when recent sales exist. |
| Slow stock | Medium | A batch has been on hand for more than 45 days. |
| Cash | Medium | There are pending sales. |
| Pricing | Low | Product with the widest margin. |

---

## Financial intelligence

Nexa has two engines that work on the same records. The user chooses which one to use.

### Algorithm engine

The Algorithm engine is deterministic. It uses the database and fixed formulas, and it needs no AI service. Its results can be checked by hand. The module is [algorithms.py](../backend/api/algorithms.py).

Request: `POST /api/assistant/analyze/` with `{"analysis": "<name>", "month": "YYYY-MM"}`. If `month` is omitted, the current month is used.

#### Algorithm analyses

| Name | What it returns |
|---|---|
| `profitability` | Revenue, gross profit (revenue − COGS), net profit (gross profit − expenses), gross margin %, net margin %, expense ratio %, and revenue growth % against the previous month. |
| `sales_trends` | Revenue for the six calendar months ending in the selected month, with a 3-month moving average. The first months use shorter windows. |
| `expense_analysis` | Expense totals by category, compared with the previous month. Each category includes its change % and its share of total expenses. |
| `product_rankings` | Top 10 products by revenue, then by name, using linked sales only (Paid and Pending). Gross profit = revenue − batch COGS. |
| `stock_cover` | For each product: stock on hand, units sold in the month, daily sales rate, days of cover, status, and the quantity to order. Status is "Out of stock" at zero stock, "No sales this period" without sales, "Reorder now" under 14 days of cover, "Watch" under 30 days, and "Healthy" otherwise. Reorder quantity = 30 days of sales − stock on hand. |

Formulas for `profitability`:

- Gross margin % = gross profit ÷ revenue × 100
- Net margin % = net profit ÷ revenue × 100
- Expense ratio % = expenses ÷ revenue × 100
- Revenue growth % = (this month − previous month) ÷ previous month × 100

Any percentage whose denominator is zero is returned as `null`.

**Example:** with revenue of $12,000, expenses of $8,000, and previous revenue of $10,000, the results are net profit $4,000, net margin 33.3%, expense ratio 66.7%, and revenue growth 20%.

### AI engine

The AI engine answers questions in natural language. It uses the same figures as the Algorithm engine, but it explains them and does not calculate them.

Request: `POST /api/assistant/chat/` with `{"question": "...", "month": "YYYY-MM"}`.

- The question can be up to 1000 characters. The request body is limited to 4096 bytes.
- The server sends the question and an **aggregated monthly summary** to the OpenAI Responses API. The summary includes totals, change against the previous month, paid and pending sales totals, weekly sales, expense categories, and product categories with their top results.
- The summary **does not** include customer names, product names, record identifiers, or individual transactions. Product results are grouped by category.
- Conversation history is not stored on the server.
- The model is set by `NEXA_OPENAI_MODEL` (default `gpt-4o-mini`). The request times out after 15 seconds, and the answer is limited to 400 output tokens.
- Each user can send at most **10 chat requests per minute**.
- The API key is read only from the server environment (`NEXA_OPENAI_API_KEY`). It is never sent to the browser.

If the key is not set, the endpoint returns `503`. If the provider fails or returns an unexpected response, it returns `502`.

**Recommended use:** keep the figures in the Algorithm engine and use the AI engine for explanations and suggestions, such as "Why did my margin improve, and what should I do to keep it?"

---

## Project structure

```
Nexa-app/
├── README.md                     Project overview and run steps
├── docs/
│   └── APP_DOCUMENTATION.md      This document
├── frontend/
│   └── Nexa.html                 Single-file React UI (React 18 and in-browser Babel from a CDN)
└── backend/
    ├── manage.py
    ├── requirements.txt          Django only
    ├── README.md                 API and configuration reference
    ├── nexa/
    │   └── settings.py           Settings, environment variables, and defaults
    └── api/
        ├── models.py             Data model
        ├── views.py              Endpoint handlers and the api() decorator
        ├── urls.py               Routes under /api/
        ├── services.py           Auth, sales, stock, FIFO, summaries, forecast, insights
        ├── algorithms.py         Algorithm engine
        ├── assistant.py          AI engine (OpenAI call)
        ├── middleware.py         CORS handling
        ├── tests.py              Automated tests
        └── management/commands/
            └── seed_demo.py      Sample data command
```

`backend/venv/` is the local Python environment and is not part of the application. Do not commit it.

The browser loads React and Babel from a CDN, so the page needs internet access to load them.

---

## API reference

All paths are under `/api/`. Requests and responses use JSON.

### Conventions

- **Authentication**: send `Authorization: Bearer <token>` on every request except the auth routes marked "public" below.
- **Money**: values are returned as strings with two decimal places.
- **Errors**: `{"error": "message"}` with an HTTP status code.

| Status | Meaning |
|---|---|
| 200 | Success |
| 201 | Created (register) |
| 400 | Invalid input. For example, a body that is not a JSON object, or a `month` that is not `YYYY-MM`. |
| 401 | Missing or invalid token ("Authentication required.") |
| 405 | Method not allowed for this route |
| 413 | Request body too large |
| 429 | Too many attempts (sign-in lockout, link requests, or chat rate limit) |
| 502 | The AI provider failed |
| 503 | The AI key is not configured |

### Endpoints

| # | Method | Path | Auth | Body or query | Purpose |
|---|---|---|---|---|---|
| 1 | POST | `auth/register/` | Public | `{username, password, password2, accepted_terms}` | Create an account. Returns 201 with `{token, user: {id, username}}`. |
| 2 | POST | `auth/login/` | Public | `{username, password}` | Sign in. Returns 200 with the same shape as register. |
| 3 | POST | `auth/request-link/` | Public | `{email}` | Send a sign-in link. Same response for any valid address. |
| 4 | POST | `auth/verify/` | Public | `{token}` | Exchange a link token for an API token. Returns `{token, user: {id, email}}`. |
| 5 | POST | `auth/logout/` | Yes | none | Revoke the current token. |
| 6 | GET | `me/` | Yes | none | Current user: `{id, username, email}`. |
| 7 | GET, POST | `products/` | Yes | GET: `?q=`. POST: `{name, price, cost, category, target_stock, supplier}` | List or create products. |
| 8 | GET, PATCH | `products/<id>/` | Yes | PATCH: fields to change, including `image` | Read or update a product. `image` is a data URL (`data:image/png;base64,...`), or `""` to remove the photo. Accepts PNG, JPEG, WebP, or GIF up to 1 MB. |
| 9 | GET, POST | `suppliers/` | Yes | POST: supplier fields | List or create suppliers. |
| 10 | GET | `customers/` | Yes | none | Customers with order count, spend, last purchase, and products bought. |
| 11 | GET, POST | `sales/` | Yes | GET: `?status=Paid\|Pending&q=`. POST: `{customer, amount, status, product_id, quantity}` | List or record sales. `product_id` and `quantity` are optional. |
| 12 | PATCH | `sales/<id>/` | Yes | `{status}` | Mark a sale as Paid or Pending. |
| 13 | GET, POST | `expenses/` | Yes | GET: `?month=YYYY-MM` (includes category totals). POST: `{category, amount}` | List or record expenses. |
| 14 | GET | `stock/` | Yes | none | Products with stock level and low-stock flag. |
| 15 | GET | `batches/` | Yes | `?slow&min_age=45` | Stock batches. `slow` filters to slow stock. |
| 16 | GET, POST | `purchases/` | Yes | POST: `{product_id, quantity?, unit_cost?}` | List purchase orders, or reorder a product. |
| 17 | POST | `purchases/<id>/receive/` | Yes | none | Receive an order into stock. |
| 18 | POST | `receive/` | Yes | `{product_id}` or `{new_product_name, price}`, plus `{quantity, unit_cost, supplier}` and optional `image` (data URL, same limits as above) | Receive stock for an existing or new product. An image replaces the product's photo. Returns the batch and the `product`. |
| 19 | GET | `dashboard/` | Yes | `?month=YYYY-MM` | KPIs, change against the previous month, weekly sales, top products, and forecast. |
| 20 | GET | `reports/` | Yes | none | Results month by month. |
| 21 | GET | `insights/` | Yes | none | Recommendations (see [Recommendations](#recommendations-insights)). |
| 22 | POST | `assistant/chat/` | Yes | `{question, month?}` | Ask the AI engine. |
| 23 | POST | `assistant/analyze/` | Yes | `{analysis, month?}` | Run an Algorithm analysis: `profitability`, `sales_trends`, `expense_analysis`, `product_rankings`, or `stock_cover`. |
| 24 | GET, PATCH | `settings/` | Yes | PATCH: `{revenue_goal?, goal_period?}` | Read or update the revenue goal. `goal_period` is `day`, `week`, `month`, or `year` (default `month`). A `revenue_goal` of `null` or `""` clears the goal. GET and PATCH return `{revenue_goal, goal_period, progress}`. `progress` is `null` when no goal is set; otherwise it holds `period`, `start`, `end`, `revenue`, `goal`, `percent`, and `remaining` for the current period. Weeks run Monday to Sunday, and years run January 1 to December 31. |
| 25 | GET | `settings/series/` | Yes | none | Chart buckets for the saved revenue goal period, used by the Overview sales chart. Returns `null` when no goal is set. Otherwise returns `{period, target, current, buckets}`. `target` is the goal (a twelfth of it for `year`), `current` is the index of the current bucket, and each bucket has `start`, `end`, and `amount`. Buckets count every sale in the period, paid and pending, with no row limit: each day of the current month, the last 8 Monday-to-Sunday weeks, the last 6 months, or the 12 months of the current year. |

Sales and purchases use the stock rules in [Sales and cost of goods](#sales-and-cost-of-goods).

### Example request

Sign in:

```json
POST /api/auth/login/
{
  "username": "you",
  "password": "your-password"
}
```

Record a sale with a product (the sale uses real batch cost):

```json
POST /api/sales/
Authorization: Bearer <token>
{
  "customer": "Jane",
  "amount": "120.00",
  "status": "Paid",
  "product_id": 3,
  "quantity": 2
}
```

Run an algorithm analysis:

```json
POST /api/assistant/analyze/
Authorization: Bearer <token>
{
  "analysis": "profitability",
  "month": "2026-10"
}
```

---

## Data model

All records belong to one user (the owner). Queries never return another user's data.

| Model | Purpose | Key fields and rules |
|---|---|---|
| `ApiToken` | Session tokens | Stored as a SHA-256 hash. Expires after 30 days. |
| `MagicLink` | One-time sign-in links | Expires after 15 minutes. Used once. |
| `LoginAttempt` | Failed sign-in tracking | Used for the lockout rule. |
| `TermsAcceptance` | Record of accepted terms | Created at registration. |
| `Supplier` | Stock suppliers | Name. |
| `Product` | Products | Name (unique per owner), price, cost, category, `target_stock` (default 60), optional supplier, optional `image` (data URL, empty when unset). |
| `StockBatch` | Stock received | Product, supplier, quantity received, quantity left, unit cost, received date. Consumed oldest first (FIFO). |
| `Customer` | Customers | Name. Used to group sales. |
| `Sale` | Sales | Customer, amount, status (Paid or Pending), COGS stored at the time of sale, optional product and quantity. |
| `Expense` | Expenses | Category, amount, date. |
| `Purchase` | Purchase orders | Product, quantity, unit cost, status (Ordered or Delivered). |
| `UserSettings` | Owner preferences | One row per owner. Optional `revenue_goal` (null when unset) and `goal_period` (`day`, `week`, `month`, or `year`; default `month`). Created on first read. |

---

## Configuration

Set these environment variables before starting the server. The defaults are for local development.

| Variable | Default | Purpose |
|---|---|---|
| `NEXA_DEBUG` | `1` | Debug mode. Set to `0` for production. |
| `NEXA_SECRET_KEY` | (none) | Required when `NEXA_DEBUG` is `0`. |
| `NEXA_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Hosts the server accepts. |
| `NEXA_CORS_ORIGINS` | `null` (for `file://`), `localhost:5500`, `127.0.0.1:5500`, `localhost:8080` | Origins allowed to call the API. |
| `NEXA_FRONTEND_URL` | `http://localhost:5500/Nexa.html` | Base of the links in sign-in emails. |
| `NEXA_EMAIL_BACKEND` | console | Where emails go. In development, links print to the console. |
| `NEXA_FROM_EMAIL` | (see settings) | Sender address for emails. |
| `NEXA_OPENAI_API_KEY` | (none) | Enables the AI engine. Keep it on the server only. |
| `NEXA_OPENAI_MODEL` | `gpt-4o-mini` | Model used by the AI engine. |

Fixed settings in [settings.py](../backend/nexa/settings.py):

- Time zone: `Africa/Harare`. Month and day boundaries use this zone.
- Sign-in link lifetime: 15 minutes.
- API token lifetime: 30 days.

---

## Testing

Run the backend tests from the `backend` folder:

```powershell
python manage.py test
```

There are 40 tests. They cover authentication, the sign-in lockout, the assistant and algorithm endpoints, the revenue goal settings, and related business rules. The tests use a separate test database, so your development data is not changed.

Run `python manage.py check` and `python manage.py makemigrations --check` before committing model changes.

---

## Known limitations

These are known differences between the code and the browser experience. Each has a clear workaround or fix.

1. **Some pages use in-memory data.** Suppliers are kept in the browser only, and customers are built from the loaded sales list. Their API routes exist, but the browser does not call them yet. Products, stock, slow stock, purchases, and receiving load from the API when the page opens, and their changes are saved.
2. **Seeded and passwordless accounts cannot sign in through the browser form.** Use the [demo account steps](#demo-accounts) for now.
3. **Magic-link URLs do not work in the browser.** The link points to `NEXA_FRONTEND_URL`, and the page does not read the `token` parameter. Use the API steps instead.
4. **Browser sales without a product use an estimated cost.** The 60% COGS estimate applies only when no product is chosen. Choosing a product uses the real batch cost.
5. **The forecast is simple.** "Next week" uses the last bucket, which covers days 22 to the end of the month. For the current month, figures are partial.
6. **The AI engine has not been tested end to end with a real key.** The Algorithm engine has been tested through the API and the browser.
7. **Rate limits use Django's cache.** Unless `CACHES` is configured in settings, Django uses per-process memory. Counts are not shared across server processes.
9. **The mobile layout is not fully verified.** The desktop layout has been checked.
10. **The settings are for development.** Debug mode is on by default, and the server is not configured for production hosting.
