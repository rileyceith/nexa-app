import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


BACKEND_DIR = Path(__file__).resolve().parent


def main():
    database_url = os.environ.get("NEXA_DATABASE_URL", "")
    try:
        database = urlsplit(database_url)
        sslmode = parse_qs(database.query, keep_blank_values=True).get("sslmode", [])
        valid_database = (
            database.scheme in ("postgres", "postgresql")
            and database.hostname
            and sslmode in (["require"], ["verify-ca"], ["verify-full"])
        )
    except ValueError:
        valid_database = False
    if not valid_database:
        print("Production requires a PostgreSQL NEXA_DATABASE_URL with TLS enabled.", file=sys.stderr)
        return 1

    port = os.environ.get("PORT", "")
    if not port.isascii() or not port.isdecimal() or len(port) > 5 or not 1 <= int(port) <= 65535:
        print("PORT must be a valid TCP port.", file=sys.stderr)
        return 1

    result = subprocess.run(
        [sys.executable, str(BACKEND_DIR / "manage.py"), "migrate", "--check"],
        cwd=BACKEND_DIR,
        check=False,
    )
    if result.returncode:
        print("Database migration check failed. Apply and verify migrations before deploying.", file=sys.stderr)
        return result.returncode

    args = [
        "gunicorn", "--chdir", str(BACKEND_DIR), "nexa.wsgi:application",
        "--bind", f"0.0.0.0:{port}",
    ]
    os.execvp(args[0], args)


if __name__ == "__main__":
    sys.exit(main())
