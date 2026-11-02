# Nexa

Nexa is a business dashboard for tracking sales, stock, purchases, customers, and expenses. It has a single-file React frontend and a Django JSON API.

## Run locally (Windows PowerShell)

Start the backend:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Then open `frontend/Nexa.html` in a browser. The frontend connects to `http://localhost:8000/api` by default.

Run backend tests from `backend`:

```powershell
python manage.py test
```

The development settings are not intended for production deployment. See [backend/README.md](backend/README.md) for API details and configuration.
