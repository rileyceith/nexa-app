# Generated migration to fix missing column issue - safely re-applies column if missing

from django.db import migrations


def add_column_if_missing(apps, schema_editor):
    """Add team_sharing_enabled column if it doesn't exist"""
    # This works for both PostgreSQL and SQLite
    db_name = schema_editor.connection.settings_dict['ENGINE'].split('.')[-1]
    
    with schema_editor.connection.cursor() as cursor:
        try:
            # Try to access the column to see if it exists
            cursor.execute("SELECT team_sharing_enabled FROM api_usersettings LIMIT 1")
            # If we get here, the column exists
        except Exception:
            # Column doesn't exist, add it
            if 'postgresql' in db_name:
                cursor.execute("""
                    ALTER TABLE api_usersettings 
                    ADD COLUMN team_sharing_enabled boolean NOT NULL DEFAULT false;
                """)
            else:  # SQLite
                cursor.execute("""
                    ALTER TABLE api_usersettings 
                    ADD COLUMN team_sharing_enabled boolean NOT NULL DEFAULT 0;
                """)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0017_usersettings_team_sharing_enabled_teaminvitation_and_more'),
    ]

    operations = [
        migrations.RunPython(add_column_if_missing, migrations.RunPython.noop),
    ]



