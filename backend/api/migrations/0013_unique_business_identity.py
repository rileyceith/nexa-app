import hashlib
import re
import unicodedata
from pathlib import Path

from django.conf import settings
from django.db import migrations, models


def populate_fingerprints(apps, schema_editor):
    preferences = apps.get_model("api", "UserSettings")
    rows = []
    names = set()
    logos = set()
    for prefs in preferences.objects.using(schema_editor.connection.alias).all().iterator():
        name = " ".join(unicodedata.normalize("NFKC", prefs.business_name).split()).casefold()
        name_hash = hashlib.sha256(name.encode("utf-8")).hexdigest() if name else None
        if name_hash and name_hash in names:
            raise RuntimeError("Duplicate company names exist. Resolve them before applying this migration.")
        if name_hash:
            names.add(name_hash)
        logo_hash = None
        if prefs.business_logo_key:
            if not re.fullmatch(r"[0-9a-f]{32}", prefs.business_logo_key):
                raise RuntimeError("An existing company logo has an invalid key. Resolve it before applying this migration.")
            path = Path(settings.MEDIA_ROOT) / "products" / prefs.business_logo_key / "1000.webp"
            try:
                logo_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as error:
                raise RuntimeError("An existing company logo cannot be read. Resolve it before applying this migration.") from error
            if logo_hash in logos:
                raise RuntimeError("Duplicate company logos exist. Resolve them before applying this migration.")
            logos.add(logo_hash)
        rows.append((prefs.pk, name_hash, logo_hash))
    for pk, name_hash, logo_hash in rows:
        preferences.objects.using(schema_editor.connection.alias).filter(pk=pk).update(
            business_name_fingerprint=name_hash, business_logo_fingerprint=logo_hash,
        )


class Migration(migrations.Migration):
    dependencies = [("api", "0012_usersettings_business_logo_key")]

    operations = [
        migrations.AddField(
            model_name="usersettings",
            name="business_name_fingerprint",
            field=models.CharField(editable=False, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="usersettings",
            name="business_logo_fingerprint",
            field=models.CharField(editable=False, max_length=64, null=True),
        ),
        migrations.RunPython(populate_fingerprints, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="usersettings",
            name="business_name_fingerprint",
            field=models.CharField(editable=False, max_length=64, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="usersettings",
            name="business_logo_fingerprint",
            field=models.CharField(editable=False, max_length=64, null=True, unique=True),
        ),
    ]
