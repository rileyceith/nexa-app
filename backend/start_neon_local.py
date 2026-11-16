import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values


backend_dir = Path(__file__).resolve().parent
url = dotenv_values(backend_dir.parent / ".env.local").get("DATABASE_URL")
if not url or urlsplit(url).scheme not in ("postgres", "postgresql") or not urlsplit(url).hostname:
    raise SystemExit("Set DATABASE_URL in the ignored .env.local file before starting Nexa with Neon.")

os.environ["NEXA_DATABASE_URL"] = url
os.environ["NEXA_MEDIA_STORAGE"] = "local"
os.environ["NEXA_MEDIA_ROOT"] = str(backend_dir / "media")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nexa.settings")

from django.core.management import execute_from_command_line

execute_from_command_line(["manage.py", "runserver", "127.0.0.1:8000", "--noreload"])
