# Render Database Reset - Step-by-Step Guide

## Overview
Your Render database (nexa-db) needs to be reset so it starts fresh with all migrations properly applied. This will fix the login issue.

---

## Step 1: Access Render Dashboard

1. Go to https://dashboard.render.com/
2. Log in with your account
3. Select your **Nexa** project
4. You should see services listed (nexa-api, nexa-db, etc.)

---

## Step 2: Delete the Database

**IMPORTANT:** This deletes all data in nexa-db. Only proceed if you're okay with losing test data.

1. Click on the **"nexa-db"** database service
2. Scroll down to the bottom of the page
3. Click the **"Delete"** button (red button)
4. Confirm the deletion when prompted
5. Wait for the database to be deleted (takes ~30 seconds)

---

## Step 3: Redeploy the API Service

After the database is deleted, Render will auto-recreate it. Now trigger a rebuild:

1. Click on the **"nexa-api"** web service
2. Click the **"Redeploy"** button (or similar - look for a deploy/rebuild button)
3. Choose **"Redeploy latest commit"**
4. The service will rebuild with the latest code

**What happens during redeploy:**
- ✅ Installs Python dependencies (from requirements.txt)
- ✅ Runs `python manage.py migrate --noinput`
  - This applies migrations 0017, 0018, 0019 to the fresh database
  - Creates all tables, columns, indexes
- ✅ Starts gunicorn web server
- ✅ Service should be ready in ~3-5 minutes

---

## Step 4: Monitor the Deployment

1. While the service is rebuilding, click on the **"Logs"** tab
2. Watch the logs scroll by - you should see:
   ```
   Building...
   Collecting Django...
   Installing dependencies...
   Applying migration 0001...
   Applying migration 0017...
   Applying migration 0018...  ← NEW (recovery migration)
   Applying migration 0019...  ← NEW (recovery migration)
   Running startCommand...
   gunicorn nexa.wsgi running...
   ```

3. If you see any errors in red, take note of them

---

## Step 5: Verify the Backend is Working

Once the logs say "gunicorn nexa.wsgi running...":

1. Open a new browser tab
2. Go to: `https://nexa-api.onrender.com/api/health/live/`
3. You should see a JSON response:
   ```json
   {"status": "healthy"}
   ```
4. ✅ If you see this, the backend is working!

---

## Step 6: Test the Login Flow

1. Go to: `https://nexa-app-3f0z.onrender.com/`
2. You should see the Nexa welcome page
3. Click **"I have an account"**
4. The login dialog should appear
5. Enter your credentials
6. ✅ You should now proceed past the login (instead of staying on welcome page)

---

## If Something Goes Wrong

### Backend still returns 404
- Check the Logs tab in Render
- Look for error messages during migration phase
- Common issues:
  - Database connection failed
  - Migration syntax error
  - Missing environment variables

### Database deletion didn't work
- Try clicking "Delete" again
- If that doesn't work, manually delete via Render's data browser
- Contact Render support if still stuck

### Redeploy button not visible
- Scroll to the top of the service page
- Look for a "Manual Deploy" or "Redeploy" button
- Or push a new commit to master: `git push origin master`
  - This auto-triggers a redeploy

### Database keeps getting 404 after redeploy
- Database might not be created yet
- Wait 5+ minutes and try again
- Or redeploy the nexa-api service again

---

## Success Indicators ✅

After these steps, you should see:

| Component | Status | Check |
|-----------|--------|-------|
| nexa-db database | Running | Shows in Render as "Available" |
| nexa-api service | Running | Shows in Render as "Live" |
| Health endpoint | 200 OK | `curl https://nexa-api.onrender.com/api/health/live/` returns JSON |
| Frontend page | 200 OK | `https://nexa-app-3f0z.onrender.com/` loads HTML |
| Login dialog | Appears | Click "I have an account" and form shows |
| Login submission | Works | Credentials are accepted and you proceed |

---

## Alternative: If You Want to Keep Data

If you have important test data and don't want to delete it:

1. DON'T delete the database
2. Instead, SSH into Render and manually run:
   ```bash
   python manage.py migrate --noinput
   ```
3. This should apply any missing migrations to your existing database
4. Then restart the nexa-api service

(But the delete approach is simpler and guaranteed to work)

---

## Questions?

If you get stuck:
1. Take a screenshot of the error
2. Check the Render logs for exact error messages
3. Let me know what you see and I can help debug

---

**Timeline:** Steps 1-6 should take about 10 minutes total
- Delete: 1 minute
- Redeploy: 3-5 minutes
- Testing: 2-3 minutes
