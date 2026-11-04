# Nexa Development Log

This log records the development increments present in the repository history, followed by subsequent work captured during reviews. The Git history currently available in this repository begins with the initial publication on 2026-11-02.

## 2026-11-02 — Initial application

**Commit:** `9948e9a` — Publish Nexa application

- Published the React-based business dashboard and Django API.
- Added account and token authentication, user-scoped data, and the core products, sales, stock, purchase, expense, dashboard, report, and insight API.
- Added database models, migrations, demo-data seeding, and backend tests.
- Added project setup and API documentation.

## 2026-11-02 — Assistant, algorithms, and account/product settings

**Commit:** `d484864` — Add AI assistant, algorithms, auth rate limiting, and product/settings updates

- Added deterministic financial-analysis algorithms and the AI assistant endpoints.
- Added sign-in rate limiting and expanded authentication behavior.
- Added product-image and revenue-goal settings support, including chart-series data.
- Updated the frontend, backend tests, and application documentation for these features.

## 2026-11-02 — Deployment preparation

**Commit:** `e11930a` — Prepare backend and frontend for Render and Cloudflare Pages

- Prepared Django configuration and dependencies for deployment.
- Updated the frontend API host selection and deployment guidance.
- Refreshed the application documentation for the hosted setup.

## 2026-11-02 — Render deployment resources

**Commit:** `c5abac7` — Add Render Blueprint for the API and database

- Added a Render Blueprint to provision the API service and PostgreSQL database.
- Updated backend deployment instructions.

## 2026-11-03 — Frontend API address audit

- Compared the API addresses called by `frontend/Nexa.html` with the Django URL patterns in `backend/api/urls.py` and the `/api/` include in `backend/nexa/urls.py`.
- Found no frontend call to an unregistered API address; no endpoint or frontend call changes were needed.
- No fix cards were created because the audit found no missing-address problems.

## 2026-11-03 — Email on account signup

- Added a required email field to the signup form and included it in registration requests.
- The registration API now validates and normalizes the email address, checks it as a password attribute, and saves it to the account. Username-based sign-in is unchanged.
- Updated registration tests and the backend/API documentation.
- Validation: `python manage.py test api` passed all 40 tests; `python manage.py check` reported no issues.

## 2026-11-03 — Receive stock form reset and product matching

- Clear the Receive stock form after a successful stock entry so it is ready for another entry; invalid or failed submissions retain entered values.
- If a submitted new-product name matches an existing product (case-insensitively), add a stock batch to that product instead of creating a duplicate or rejecting the entry.
- Updated receive-stock documentation and added backend coverage for matching existing products.
- Validation: `python manage.py test api` passed all 41 tests. Browser test with a mocked receive response confirmed a duplicate name submits the existing `product_id` and the form clears after success.

## 2026-11-03 — Backend hardening: stock, performance, and API errors

- Purchase receiving runs in a transaction with row locking, so a purchase order cannot be received twice by concurrent requests. Duplicate product names return 409 instead of a server error.
- Added a `StockMovement` ledger that records every stock change. Migration `0005` backfills it from existing batches; movements for past sales are approximate.
- Removed per-product queries from stock, insights, and customer lists. Added database indexes (migration `0006`).
- List endpoints accept `limit` and `offset` and return `X-Total-Count`. Responses are gzip-compressed.
- Unexpected server errors return JSON with status 500 and are logged. Money values are returned as two-decimal strings.
- Rate limits use a database cache, so run `python manage.py createcachetable` after migrating.
- Validation: `manage.py test api` passed 55 tests at this point.

## 2026-11-03 — Product photos stored as files

- Product photos are stored as WebP files under `NEXA_MEDIA_ROOT` instead of inline in the database. Each upload is resized with Pillow to 120, 400, and 1000 pixels on the longest edge.
- Product responses return `image_url` (`/api/images/<key>/`) in place of the inline `image` field. `GET /api/images/<key>/?size=` serves the file with an ETag and a one-day cache. The route is public because `<img>` tags cannot send the token; the key is a random 128-bit value.
- Replacing or clearing a photo deletes the old files after the change is saved. If saving fails with a name collision, the new files are deleted and the request returns 409.
- Migration `0007` converts existing inline photos to files, and `0008` removes the old column. Run `migrate` after pulling this change.
- `render.yaml` adds a 1 GB disk at `/var/data` and sets `NEXA_MEDIA_ROOT`. Migrations now run in the start command, because pre-deploy commands cannot see the disk.
- The frontend requests 400-pixel thumbnails through `image_url`.
- Validation: `manage.py test api` passed 60 tests, and `manage.py check` and `makemigrations --check` were clean. Migration `0008` was applied and reversed on a scratch SQLite database. Upload and serving were checked against a local server (200 `image/webp`, 304 on revalidation). Browser display was not checked.

## Keeping this log current

For each future development increment, append a dated section describing the user-visible or technical change, relevant files or components, and validation performed. Include a commit hash when the increment has been committed.
