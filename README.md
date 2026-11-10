# Nexa

Nexa is a business dashboard for tracking sales, stock, purchases, customers, and expenses. It has a React frontend and a Django JSON API.

## Run locally (Windows PowerShell)

Start the backend. It also serves the frontend, so one command runs everything:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd ..
.\dev.ps1
```

Then open <http://localhost:8000/>. The Django admin is at <http://localhost:8000/admin/>. `dev.ps1` stops any old Nexa server still holding port 8000, applies migrations, and starts the server. Create an admin account once with `python manage.py createsuperuser` from `backend`.

The page and the API share one origin, so there is no CORS setup to keep in step. If you open `frontend/Nexa.html` another way (from a file or another local server), it still finds the API on port 8000 of the same host.

The frontend lives in `frontend/Nexa.html`, `frontend/Nexa.css`, and `frontend/Nexa.jsx`.
`frontend/Nexa.js` is the generated browser-ready script and must remain beside the HTML and CSS,
including on static hosting. After editing the JSX, install Node.js and run `npm ci` once, then
`npm run build:frontend`; commit the updated generated JavaScript with the JSX. Edits to HTML or CSS
do not require a build.

## Mobile app (Android and iOS)

The Capacitor projects in `android/` and `ios/` bundle the same Nexa frontend; they do not
package Django or its database. Configure a stable, reachable HTTPS backend before using the app:

```powershell
npm ci
$env:NEXA_MOBILE_API_URL = "https://your-backend.example/api"
npm run sync:mobile
```

The URL is embedded in the mobile bundle, so do not put credentials in it. If it is unset, the
app can open but sign-in reports that the server address is not configured. Re-run the sync and
rebuild the native app whenever the address or frontend changes. Do not use a temporary quick
tunnel for a distributed app. The backend must allow the WebView origins, for example set
`NEXA_CORS_ORIGINS=https://localhost,capacitor://localhost` alongside any existing allowed origins.
For temporary testing, use the same public address the browser uses, followed by `/api`, as
`NEXA_MOBILE_API_URL`. `.\dev.ps1 -Share` allows the mobile WebView origins. The mobile app
and browser then use the same server and database; changing the quick-tunnel address requires
syncing and rebuilding the app. Do not rely on that temporary address for ongoing use.

Use Node.js 22 or newer and Android Studio with JDK 21 and Android SDK 36 to open `android/` and
build or run Android. To build iOS, run `npm ci` and `npm run sync:mobile` on a Mac with Xcode,
then open `ios/App/App.xcodeproj`. Signing and store distribution require your own developer
accounts. The initial app ID is `com.nexa.app`; choose your own unique ID before publishing and
update the native projects and `capacitor.config.json` consistently.

The frontend and React are bundled, but API features need a network connection; fonts may still
load from Google. This shell does not implement email-link deep linking or secure native token
storage. Password sign-in is the supported mobile flow for now. Protect the device and evaluate
secure storage and release security before distributing the app.

### Share a temporary public link

With [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/) installed (`winget install Cloudflare.cloudflared`), run `.\dev.ps1 -Share`. It starts the server and a Cloudflare quick tunnel, then prints an `https://<random>.trycloudflare.com` address that changes on every run. Press Ctrl+C to stop sharing. A quick tunnel is deleted by Cloudflare if its connection drops for a moment, and then the old address stops resolving (`ERR_NAME_NOT_RESOLVED` on other devices). `-Share` watches for this, opens a new tunnel automatically and prints the new address, so send people the new link. For an address that never changes, use a named tunnel on a domain you own. While sharing, the server runs with debug off and a fresh random secret key, and `/admin/` answers 404 on the public link (it still works at <http://localhost:8000/admin/>). Anyone who has the link can reach the sign-in page and create an account, so only share it with people you trust.

Run backend tests from `backend`:

```powershell
python manage.py test
```

The development settings are not intended for production deployment. See [backend/README.md](backend/README.md) for API details and configuration. For a full guide to the app's features, calculations, and known limitations, see [docs/APP_DOCUMENTATION.md](docs/APP_DOCUMENTATION.md).
