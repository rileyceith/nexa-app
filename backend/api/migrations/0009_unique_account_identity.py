from django.conf import settings
from django.db import migrations
from django.db.models import Count
from django.db.models.functions import Lower, Trim


def create_identity_indexes(apps, schema_editor):
    if schema_editor.connection.vendor not in ("sqlite", "postgresql"):
        raise RuntimeError("Account identity indexes require SQLite or PostgreSQL.")
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    users = User.objects.using(schema_editor.connection.alias)
    emails = users.annotate(identity=Lower(Trim("email"))).exclude(identity="").values("identity")
    usernames = users.annotate(identity=Lower("username")).values("identity")
    if emails.annotate(total=Count("pk")).filter(total__gt=1).exists():
        raise RuntimeError(
            "Cannot enforce unique account emails: duplicate email addresses exist. "
            "Resolve the duplicates without deleting account data, then run migrations again."
        )
    if usernames.annotate(total=Count("pk")).filter(total__gt=1).exists():
        raise RuntimeError(
            "Cannot enforce unique account usernames: case-insensitive duplicates exist. "
            "Resolve the duplicates without deleting account data, then run migrations again."
        )
    table = schema_editor.quote_name(User._meta.db_table)
    schema_editor.execute(
        f'CREATE UNIQUE INDEX nexa_user_email_identity_uniq ON {table} (LOWER(TRIM(email))) '
        "WHERE TRIM(email) <> ''"
    )
    schema_editor.execute(
        f'CREATE UNIQUE INDEX nexa_user_username_identity_uniq ON {table} (LOWER(username))'
    )


def drop_identity_indexes(apps, schema_editor):
    schema_editor.execute("DROP INDEX nexa_user_email_identity_uniq")
    schema_editor.execute("DROP INDEX nexa_user_username_identity_uniq")


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0008_remove_product_image"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(create_identity_indexes, drop_identity_indexes)]
