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
Send it on every authenticated request as `Authorization: Bearer <token>`. By default, business data is scoped
to the signed-in user's workspace. For another business they belong to, send `X-Nexa-Workspace: <owner-user-id>`;
the API checks active membership and the requested view/edit permission on every business endpoint. Account
profile, security codes and signed-in sessions always remain scoped to the signed-in person.

Registration creates the user, default settings, terms acceptance and token in one transaction. The optional
`team_sharing_enabled` boolean enables sharing for the new owner's workspace; sharing can also be enabled later
in Team settings. Inventory starts empty.
Usernames for new password accounts use 3–30 ASCII letters, digits, dots,
dashes or underscores. An email address identifies one account: a magic link signs in to that account
or creates an empty one if it does not exist. Repeated registration returns 409 rather than replaying
the original token; after an interrupted response, sign in instead. Passwords are hashed by Django;
profile and financial fields are not encrypted individually. Production deployments must configure
HTTPS, protected email delivery and encryption at rest for the database, backups and media.

Password reset requests return the same response for known and unknown valid email addresses.
Reset tokens are stored as hashes, expire after 30 minutes by default, and can only be used once.
The new password uses Django's configured validators, and resetting it revokes all existing API tokens.
Requests are limited to three per email address and 20 per IP address per hour.

## Endpoints (all under `/api/`)

| Method | Path | Purpose |
|---|---|---|
| POST | `auth/register/` `{username, email, password, password2, accepted_terms, team_sharing_enabled?}` | Create an account (returns 201 and a token) |
| POST | `auth/login/` `{username, password}` | Sign in with a username and password |
| POST | `auth/request-link/` `{email}` | Email a sign-in link |
| POST | `auth/verify/` `{token}` | Exchange link token for an API token |
| POST | `auth/password-reset/` `{email}` | Request a password reset link (non-enumerating response) |
| POST | `auth/password-reset/confirm/` `{token, password, password2}` | Set a new password and revoke existing API tokens |
| POST | `auth/logout/` | Revoke the current token |
| GET | `me/` | Current account, available workspaces, selected workspace ID and email verification status. The dashboard shows an **Admin** button (a link to `/admin/`) only when `is_staff` is true |
| PATCH | `account/profile/` `{username}` | Change the account username |
| GET | `account/sessions/` | List this account's active sessions, including the current session |
| POST | `account/security/request/` `{action, target}` | Send a security code to the verified current account email for `email`, `password`, or `device`; target is the new email or session ID |
| POST | `account/security/confirm/` `{action, code, password, password2}` | Confirm a security code; email changes require a second code sent to the new address |
| GET | `team/` | Owner/team-manager view of members and pending invitations |
| PATCH | `team/sharing/` `{team_sharing_enabled}` | Owner enables sharing or revokes all members and pending invitations |
| POST | `team/invitations/` `{email, permissions, can_manage_members}` | Send a seven-day, single-use invitation to a separate account |
| POST | `team/invitations/preview/` `{token}` | Validate an invitation link without accepting it |
| POST | `team/invitations/accept/` `{token}` | Accept while signed in with the invited email; personal business data is not merged |
| PATCH, DELETE | `team/members/<id>/` | Update a member's scope permissions or remove the membership |
| DELETE | `team/invitations/<id>/` | Cancel a pending invitation |
| GET, POST | `products/` | List (`?q=`) / create `{name, price, cost, category, target_stock, supplier}` |
| GET, PATCH | `products/<id>/` | Read / update (`image` sets or clears the photo, 1 MB max). Responses carry `image_url` instead of the image data |
| GET | `images/<key>/?size=120\|400\|1000` | Public WebP product photo. Use the `image_url` from a product. Default size 400 |
| GET, POST | `suppliers/` | List / create |
| GET | `customers/` | Orders, spend, last purchase, products bought |
| GET, POST | `sales/` | List (`?status=Paid\|Pending&q=`) / record `{customer, amount, status, product_id, quantity}` |
| PATCH | `sales/<id>/` `{status}` | Mark paid / pending |
| GET, POST | `expenses/` | List (`?month=2026-10`, with category totals) / record `{category, amount}` |
| GET | `stock/` | Products with stock level and low-stock flag |
| GET | `batches/` | Batches in stock (`?slow&min_age=<days>` for slow stock; defaults to the owner's configured threshold) |
| GET, POST | `purchases/` | List / reorder `{product_id, quantity?, unit_cost?}` |
| POST | `purchases/<id>/receive/` | Receive an order into stock |
| POST | `receive/` | Receive stock `{product_id \| new_product_name+price, quantity, unit_cost, supplier, image?}`; a new-product name matching an existing product adds stock to that product. `image` is an optional data URL (PNG, JPEG, WebP or GIF, 1 MB max) |
| GET | `dashboard/?month=2026-10` | KPIs, change vs previous month, weekly sales, top products, forecast |
| GET | `reports/` | Month-by-month results |
| GET | `insights/` | Generated recommendations |
| POST | `assistant/chat/` `{question, month?}` | Ask about verified, aggregated financial data |
| POST | `assistant/analyze/` `{analysis, month?}` | Deterministic analysis: `profitability`, `sales_trends`, `expense_analysis`, `product_rankings`, `stock_cover`, `reorder_planning`, `aging_inventory`, `break_even`, `customer_concentration`, or `cash_indicators`. See [algorithm details](../docs/APP_DOCUMENTATION.md#algorithm-analyses) for assumptions and limitations. |
| GET, PATCH | `settings/` | Owner preferences: goal, theme, display currency, time zone, business profile, stock/reorder thresholds, and email alert preferences. Currency changes require `confirm_currency_change: true` and never convert recorded amounts. |
| GET | `settings/series/` | Overview chart buckets for the goal period: `{period, target, current, buckets}` (each bucket has `start`, `end`, `amount`), or `null` without a goal. Counts every sale, with no row limit |
| POST | `settings/verify-email/` | Send a verification/sign-in link to the current account email |
| POST | `account/confirm/` `{action: "export" \| "delete"}` | Send a short-lived, one-use email confirmation link |
| POST | `account/export/` `{token, confirmation: "EXPORT"}` | Download an owner-scoped CSV; no authenticated API token is needed because the email token is the re-authentication |
| POST | `account/delete/` `{token, confirmation: "DELETE"}` | Permanently delete the account and its associated data after email re-authentication |

Settings belong to the selected business workspace. Set `business_name` and optionally `business_logo` (a PNG, JPEG, WebP or GIF data URL of up to 1 MB) through `PATCH /api/settings/`; set `business_logo` to `""` to remove it. The response includes `business_logo_url`. As with product photos, logo images are served through a public, unguessable image URL; do not upload sensitive images. The logo is stored in the configured media storage and deleted when replaced, removed, or the account is deleted. CSV exports do not include image files. Currency changes only change the display label and do not convert stored amounts. Inventory thresholds affect stock warnings and reorder/aging analyses. Email alerts are opt-in, require a verified account email and secure SMTP configuration, and are deduplicated until the triggering condition is resolved. Aged-stock alerts are checked on app requests; this deployment has no scheduler.

Team sharing uses migration `0017`. Apply migrations before deploying code that includes these endpoints. Invitations are sent only when the owner's account email is verified and secure email delivery is configured. Permissions are separate `view` and `edit` grants for each business area; edit requires view. Non-owner team managers can only delegate permissions they personally have and cannot grant team-management rights. Disabling sharing deletes memberships and pending invitations; it never merges or deletes member-owned data. Signed-in sessions and device lists remain private to each individual account, not visible through team membership.

Account security codes require a verified current email and configured delivery. Codes expire in
10 minutes, permit at most five incorrect attempts, and are bound to the requesting session and
action. Requests are limited to five per account per hour. Email changes also verify the new
address and sign out other sessions; password changes sign out all sessions. Previously issued
reset, sign-in and account-action links are invalidated. Session browser details are collected
at sign-in; sessions created before this feature show as unknown. Do not rely on browser labels
as verified device identities.

Logo framing is saved with the business settings: `business_logo_zoom` is an integer from 100 to 300 percent, and `business_logo_x` and `business_logo_y` are integer offsets from -100 to 100 percent of the frame. Positive offsets move the image right and down. These adjustments apply to both desktop and mobile without altering the stored image.

Nonempty company names and logos must be unique across accounts. Name matching ignores case, Unicode compatibility differences, and repeated whitespace; logo matching compares the rendered image, not visually similar or edited images. A conflict returns HTTP 409 with an error message. This does not verify company ownership. Before applying migration `0013`, ensure existing company names and rendered logos are unique and stored logo files are accessible; the migration stops without deleting data if they are not.

## Scalability foundations

- Set `NEXA_REDIS_URL` to a shared `redis://` or `rediss://` service to move the cache and rate-limit counters out of the database. Leave it unset for the existing database cache. Protect Redis with network access controls and TLS where appropriate; a Redis outage is not silently replaced by a process-local cache.
- Set `NEXA_MEDIA_STORAGE=r2`, `NEXA_R2_ENDPOINT` (the HTTPS account endpoint), `NEXA_R2_BUCKET`, `NEXA_R2_ACCESS_KEY_ID` and `NEXA_R2_SECRET_ACCESS_KEY` to use a private Cloudflare R2 bucket. Keep credentials in protected environment variables. Leave storage unset for local `NEXA_MEDIA_ROOT`. Existing local images must be copied with their `products/<key>/<size>.webp` paths intact and verified before switching; migration `0013` still needs its existing local logo files when applied to an older database. The image API remains public through unguessable URLs. Remote storage failures are reported; image cleanup needs operational monitoring.
- After applying migrations, set `NEXA_ASYNC_ALERTS=1` and run `python manage.py run_alert_worker` as a separate continuously supervised process. Each instance must use the same PostgreSQL database and email configuration. The queue is stored in the database, not Redis. Failed sends retry with backoff; a crash after provider acceptance can cause a duplicate. Queue creation and notification state update are atomic, but alert detection still occurs on application requests after the triggering business transaction. Monitor worker health, queue age, and errors; without a worker, alerts remain queued. Login, password-reset, and account confirmation emails still run in requests. Use PostgreSQL for multiple workers; SQLite does not provide equivalent row locking.
- `/api/health/live/` is a liveness probe; `/api/health/ready/` checks the database and configured cache and returns 503 when they cannot be reached. Limit public probe traffic at the edge.

These are application foundations, not a finished multi-instance deployment. The existing Render blueprint still uses a single-instance disk and runs migrations on startup. Do not scale it horizontally until shared storage, Redis, worker deployment, one-time migrations, backups, and monitoring are configured and tested. No capacity target is established without representative load tests.

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
`NEXA_FRONTEND_URL` (base of the magic link), `NEXA_EMAIL_BACKEND` (console in debug; SMTP in production),
`NEXA_EMAIL_HOST`, `NEXA_EMAIL_PORT` (587 by default; 465 with SSL), `NEXA_EMAIL_USER`,
`NEXA_EMAIL_PASSWORD`, `NEXA_EMAIL_USE_TLS` (on by default in production),
`NEXA_EMAIL_USE_SSL` (off by default; do not enable together with TLS), `NEXA_FROM_EMAIL`,
`NEXA_RESEND_API_KEY` (private Resend sending-only API key when using the Resend backend),
`NEXA_PASSWORD_RESET_MINUTES` (30 by default; allowed range 5–120),
`NEXA_DATABASE_URL` (PostgreSQL URL; SQLite `db.sqlite3` is used when unset), `NEXA_MEDIA_ROOT` (folder for product photos; default `media/` in the backend folder).

Neon CLI writes its PostgreSQL connection string as `DATABASE_URL` in `.env.local`; Django does
not load that file automatically. Configure the same value as `NEXA_DATABASE_URL` in the hosting
provider's secret environment settings. Do not commit the file or print the connection string.
Connecting a new database does not transfer existing SQLite accounts or data; back up and migrate
them separately before switching. Neon Auth does not replace Nexa's existing authentication.

For the manually configured Render + Neon service, use `python backend/start_production.py` as
the start command with the repository root as the root directory. It requires a PostgreSQL
`NEXA_DATABASE_URL` with `sslmode=require`, `verify-ca`, or `verify-full`, and refuses to start
if Django reports pending migrations or cannot check the database. `require` encrypts the
connection but does not provide the same server identity verification as `verify-full`; configure
the trusted root certificate and use `verify-full` where supported. Keep credentials private.

Before deploying schema changes, back up the database, test the migrations on an isolated
production-like Neon branch, and apply them to production with Django using a direct (non-pooled)
connection. Only deploy compatible code after they succeed. The startup check detects pending
migrations, not every possible schema drift, and does not apply or repair migrations automatically.
Keep migrations compatible with the running version during deployment. A failed check prevents
the new instance from starting; monitor deployment logs and restore service before retrying.

For HTTPS email delivery on Render, set `NEXA_EMAIL_BACKEND=anymail.backends.resend.EmailBackend`,
`NEXA_RESEND_API_KEY` to a Resend sending-only API key, and `NEXA_FROM_EMAIL` to a sender
permitted by Resend. These settings apply to sign-in links, password resets, account confirmations,
and alerts. Resend's `onboarding@resend.dev` test sender can only send to the account owner's
email. To send to other users, verify a domain you control in Resend and use an address on that
domain. Keep the key in hosting secrets. Provider acceptance does not guarantee inbox delivery;
check the provider's delivery logs. Disable click tracking for authentication links.

For local testing with a migrated Neon database and images kept on this computer, run
`python start_neon_local.py` from `backend`. It uses `DATABASE_URL` from the root `.env.local`
and serves the local `backend/media` folder, without changing your SQLite database. Changes made
to either database are not synchronized to the other. Stop the ordinary local server first.
This development server is not a public deployment; local images still need to be copied to
shared storage before deploying.

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
- Configure authenticated TLS SMTP or the Resend HTTPS backend with Render secrets before enabling email features. Production defaults to SMTP, never console logging; password reset requests remain generic even when delivery fails. Password sign-in works without email.

**Frontend (Cloudflare Pages)**

- Connect the GitHub repository. Leave the build command empty and set the build output directory to `frontend`.
- Add `app.Nexa.com` as a custom domain.
- `frontend/Nexa.html` calls `https://api.Nexa-app.com/api` unless it is opened from localhost or `file://`.
