# Render Database Troubleshooting Guide

## Current Issue

The backend API (nexa-api service) is returning 404 on all endpoints, indicating the Django app either:
1. Isn't starting, OR
2. Is crashing on startup due to database schema issues

## Root Cause

Migration 0017 (team-sharing features) needs to run on the Render nexa-db database, but it may not have applied successfully.

## Solution Options

### Option 1: Reset and Rebuild Database (Recommended)

If the database is new/empty and migrations aren't applying automatically:

1. **In Render Dashboard:**
   - Navigate to your Nexa project
   - Click on the "nexa-db" database service
   - Click "Delete" (this removes the database)
   - Re-deploy the nexa-api web service

2. **What happens:**
   - Render automatically recreates nexa-db
   - nexa-api service rebuilds
   - On startup, `python manage.py migrate --noinput` runs
   - All migrations (including 0018, 0019 recovery migrations) apply cleanly
   - Service should start successfully

**Risk:** This deletes all data. Only safe if no production data yet (you're still testing login).

### Option 2: Use PostgreSQL Shell (Advanced)

If you need to preserve data:

1. **In Render Dashboard:**
   - Click on "nexa-db" database
   - Click "Shell" tab
   - Connect via CLI or use the web shell
   - Manually check and apply schema

2. **Check if column exists:**
   ```sql
   SELECT EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_name = 'api_usersettings'
       AND column_name = 'team_sharing_enabled'
   );
   ```

3. **If column missing, manually add it:**
   ```sql
   ALTER TABLE api_usersettings 
   ADD COLUMN team_sharing_enabled boolean NOT NULL DEFAULT false;
   ```

4. **Then restart nexa-api service** in Render dashboard

### Option 3: Manual Migration Check

1. **In Render Dashboard:**
   - Click nexa-api web service
   - Click "Shell" tab
   - Run:
   ```bash
   python manage.py showmigrations api
   ```

2. This shows which migrations have applied
3. If 0017, 0018, 0019 show as `[X]` they're applied
4. If they show as `[ ]` they haven't applied yet
5. Try manually running:
   ```bash
   python manage.py migrate --noinput
   ```

## Recent Commits

The recovery migrations are now in the codebase:

```
713a048 Doc: Add login issue root cause analysis and fix status
0a790e9 Fix: Add recovery migrations to ensure database schema is complete
  - 0018_ensure_team_sharing_column.py (safely re-applies team_sharing_enabled)
  - 0019_ensure_team_tables.py (safely re-applies team tables)
```

These migrations:
- ✅ Are idempotent (safe to run multiple times)
- ✅ Work with PostgreSQL and SQLite
- ✅ Check if schema elements exist before creating them
- ✅ Will auto-apply on next service startup

## Expected Timeline

After fix is applied:
1. **Backend rebuilds** → ~2 minutes
2. **Migrations run** → ~30 seconds
3. **Django starts** → Should be responsive
4. **Login flow works** → Users can proceed past welcome page

## Verification

Once backend is up:

```bash
# Check health
curl https://nexa-api.onrender.com/api/health/live/

# Check if returns 200 OK with:
# {"status": "healthy"}
```

## If Still Broken After Reset

This might indicate a deeper Django configuration issue:

1. Check nexa-api service logs in Render dashboard
2. Look for Python errors during migration phase
3. Verify NEXA_DATABASE_URL is set correctly in env vars
4. Ensure all requirements in requirements.txt are compatible

## Next Steps

**Recommended:** Try Option 1 (Reset database) first since you're in early testing phase.
If that doesn't work, provide the error logs from Render dashboard and we can debug further.
