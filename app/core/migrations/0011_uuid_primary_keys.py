"""Give every row of a UUID-keyed model a UUID instead of its counter, in the row and everywhere it is referenced.

The migrations before this one (``<app>.*_uuid_primary_keys``) changed the type of the key columns. They
turned the counters into text ("1", "2", …) and rebuilt every table that points at them, third-party ones
like django-otp and the admin log included. Here the counters are replaced by UUIDs:

* the key of each row, and each foreign key and many-to-many link that points at it, found through the
  database's own foreign key list, so no table is forgotten;
* what refers to a row without a foreign key: the admin log and the dedupe keys of queued e-mails;
* the sessions, which are deleted: they store the counter of the signed-in user.

The UUIDs are version 7 and given in the order of the old counters, so sorting by key still sorts by age.
All of it is one transaction, and Django checks the foreign keys when the migration ends.
"""

import re
import uuid

from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError

MAP = "lextracker_uuid_map"

# Queued e-mails are sent once per key, and the keys contain the counters of the row they are about
# (see mailer.jobs). Without rewriting them, every report and reminder would be sent again.
DEDUPE_PARTS = [
    (re.compile(r"(weekly-report:)(\d+)(:.*)"), "accounts_user"),
    (re.compile(r"(timer-reminder:)(\d+)(.*)"), "tracking_timeentry"),
    (re.compile(r"(invoice-overdue:)(\d+)(:.*)"), "billing_invoice"),
]
DEDUPE_ADMIN = re.compile(r"(.*:user:)(\d+)")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def rekey(apps, schema_editor):
    connection = schema_editor.connection
    models_by_table = {m._meta.db_table: m for m in apps.get_models() if isinstance(m._meta.pk, models.UUIDField)}

    with connection.cursor() as cursor:
        # Which columns point at which table.
        references: dict[str, list[tuple[str, str]]] = {table: [] for table in models_by_table}
        for table in connection.introspection.table_names(cursor):
            cursor.execute(f"PRAGMA foreign_key_list({_quote(table)})")
            for _, _, target, column, *_ in cursor.fetchall():
                if target in references:
                    references[target].append((table, column))

        cursor.execute(f"CREATE TEMP TABLE {MAP} (old TEXT PRIMARY KEY, new TEXT NOT NULL) WITHOUT ROWID")
        new_ids: dict[str, dict[str, str]] = {}
        for table, model in models_by_table.items():
            key = _quote(model._meta.pk.column)
            # Only counters: a key that is a UUID already (the migration ran before) stays as it is.
            cursor.execute(f"SELECT {key} FROM {_quote(table)} WHERE length({key}) < 32 ORDER BY CAST({key} AS INTEGER)")
            ids = {old: uuid.uuid7().hex for (old,) in cursor.fetchall()}
            new_ids[table] = ids
            if not ids:
                continue
            cursor.execute(f"DELETE FROM {MAP}")
            cursor.executemany(f"INSERT INTO {MAP} VALUES (%s, %s)", list(ids.items()))
            for child, column in references[table]:
                col = _quote(column)
                cursor.execute(
                    f"UPDATE {_quote(child)} SET {col} = (SELECT new FROM {MAP} WHERE old = {_quote(child)}.{col}) "
                    f"WHERE {col} IN (SELECT old FROM {MAP})"
                )
            cursor.execute(f"UPDATE {_quote(table)} SET {key} = (SELECT new FROM {MAP} WHERE old = {_quote(table)}.{key})")
        cursor.execute(f"DROP TABLE {MAP}")

        tables = set(connection.introspection.table_names(cursor))

        # The admin log names its object by the text of its key, which for a UUID is the dashed form.
        if "django_admin_log" in tables and "django_content_type" in tables:
            for table, ids in new_ids.items():
                model = models_by_table[table]
                cursor.execute(
                    "SELECT id FROM django_content_type WHERE app_label = %s AND model = %s",
                    [model._meta.app_label, model._meta.model_name],
                )
                if (content_type := cursor.fetchone()) is None:
                    continue
                cursor.executemany(
                    "UPDATE django_admin_log SET object_id = %s WHERE content_type_id = %s AND object_id = %s",
                    [(str(uuid.UUID(new)), content_type[0], old) for old, new in ids.items()],
                )

        # The dedupe keys of queued e-mails, which use the dashed form of a UUID.
        if "mailer_outgoingmail" in tables:
            cursor.execute("SELECT id, dedupe_key FROM mailer_outgoingmail WHERE dedupe_key != ''")
            updates = []
            for mail_id, dedupe_key in cursor.fetchall():
                key = dedupe_key
                for pattern, table in DEDUPE_PARTS:
                    if match := pattern.fullmatch(key):
                        new = new_ids[table].get(match[2])
                        if new:
                            key = f"{match[1]}{uuid.UUID(new)}{match[3]}"
                        break
                if admin := DEDUPE_ADMIN.fullmatch(key):
                    if new := new_ids["accounts_user"].get(admin[2]):
                        key = f"{admin[1]}{uuid.UUID(new)}"
                if key != dedupe_key:
                    updates.append((key, mail_id))
            cursor.executemany("UPDATE mailer_outgoingmail SET dedupe_key = %s WHERE id = %s", updates)

        # Sessions hold the counter of the signed-in user. Everyone signs in again once.
        if "django_session" in tables:
            cursor.execute("DELETE FROM django_session")

        for table, model in models_by_table.items():
            key = _quote(model._meta.pk.column)
            cursor.execute(f"SELECT COUNT(*) FROM {_quote(table)} WHERE length({key}) != 32")
            if cursor.fetchone()[0]:
                raise RuntimeError(f"{table} still has keys that are not UUIDs.")


def not_reversible(apps, schema_editor):
    raise IrreversibleError(
        "The counters are gone. Restore the copy made before the conversion (…-vor-umstellung.sqlite3)."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_backup_before_uuid_migration"),
        ("accounts", "0010_uuid_primary_keys"),
        ("billing", "0005_uuid_primary_keys"),
        ("customers", "0003_uuid_primary_keys"),
        ("mailer", "0003_uuid_primary_keys"),
        ("projects", "0003_uuid_primary_keys"),
        ("tracking", "0003_uuid_primary_keys"),
    ]

    operations = [
        migrations.RunPython(rekey, not_reversible),
    ]
