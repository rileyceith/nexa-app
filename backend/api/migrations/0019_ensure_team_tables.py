# Generated migration to fix missing tables from 0017 if they weren't created

from django.db import migrations


def create_tables_if_missing(apps, schema_editor):
    """Create team tables if they don't exist"""
    db_name = schema_editor.connection.settings_dict['ENGINE'].split('.')[-1]
    is_postgres = 'postgresql' in db_name
    
    with schema_editor.connection.cursor() as cursor:
        # Try to access TeamInvitation table
        try:
            cursor.execute("SELECT 1 FROM api_teaminvitation LIMIT 1")
        except Exception:
            # Table doesn't exist, create it
            if is_postgres:
                cursor.execute("""
                    CREATE TABLE api_teaminvitation (
                        id bigserial NOT NULL PRIMARY KEY,
                        email varchar(254) NOT NULL,
                        token_hash varchar(64) NOT NULL UNIQUE,
                        permissions jsonb NOT NULL,
                        can_manage_members boolean NOT NULL,
                        expires_at timestamp with time zone NOT NULL,
                        accepted_at timestamp with time zone NULL,
                        created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        owner_id integer NOT NULL,
                        FOREIGN KEY (owner_id) REFERENCES auth_user(id) ON DELETE CASCADE
                    );
                """)
                cursor.execute("""
                    CREATE INDEX team_invite_owner_email_idx 
                    ON api_teaminvitation(owner_id, email, expires_at);
                """)
            else:  # SQLite
                cursor.execute("""
                    CREATE TABLE api_teaminvitation (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        email varchar(254) NOT NULL,
                        token_hash varchar(64) NOT NULL UNIQUE,
                        permissions TEXT NOT NULL,
                        can_manage_members INTEGER NOT NULL,
                        expires_at datetime NOT NULL,
                        accepted_at datetime NULL,
                        created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        owner_id integer NOT NULL,
                        FOREIGN KEY (owner_id) REFERENCES auth_user(id)
                    );
                """)
                cursor.execute("""
                    CREATE INDEX team_invite_owner_email_idx 
                    ON api_teaminvitation(owner_id, email, expires_at);
                """)

        # Try to access TeamMembership table
        try:
            cursor.execute("SELECT 1 FROM api_teammembership LIMIT 1")
        except Exception:
            # Table doesn't exist, create it
            if is_postgres:
                cursor.execute("""
                    CREATE TABLE api_teammembership (
                        id bigserial NOT NULL PRIMARY KEY,
                        permissions jsonb NOT NULL,
                        can_manage_members boolean NOT NULL,
                        created_at timestamp with time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        member_id integer NOT NULL,
                        owner_id integer NOT NULL,
                        UNIQUE(owner_id, member_id),
                        FOREIGN KEY (member_id) REFERENCES auth_user(id) ON DELETE CASCADE,
                        FOREIGN KEY (owner_id) REFERENCES auth_user(id) ON DELETE CASCADE,
                        CHECK (owner_id != member_id)
                    );
                """)
            else:  # SQLite
                cursor.execute("""
                    CREATE TABLE api_teammembership (
                        id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                        permissions TEXT NOT NULL,
                        can_manage_members INTEGER NOT NULL,
                        created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        member_id integer NOT NULL,
                        owner_id integer NOT NULL,
                        UNIQUE(owner_id, member_id),
                        FOREIGN KEY (member_id) REFERENCES auth_user(id),
                        FOREIGN KEY (owner_id) REFERENCES auth_user(id),
                        CHECK (owner_id != member_id)
                    );
                """)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0018_ensure_team_sharing_column'),
    ]

    operations = [
        migrations.RunPython(create_tables_if_missing, migrations.RunPython.noop),
    ]

