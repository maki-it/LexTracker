from django.db import migrations


def backup(apps, schema_editor):
    """Copy the database before the primary keys are converted, so the conversion can be undone.

    Skipped for a database without users, i.e. a fresh installation, where there is nothing to lose.
    """
    from core import backup as backups

    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS (SELECT 1 FROM accounts_user)")
        has_data = cursor.fetchone()[0]
    if has_data:
        backups.backup_before_upgrade()


class Migration(migrations.Migration):
    # All apps are migrated up to here, so every table exists. The migrations that change the primary keys
    # depend on this one and run after the copy is made.
    dependencies = [
        ("core", "0009_overdue_notice_and_invite_by_mail"),
        ("accounts", "0009_portal_contact"),
        ("billing", "0004_invoice_open_amount"),
        ("customers", "0002_category_customer_lexware_deleted_and_more"),
        ("mailer", "0002_alter_outgoingmail_kind"),
        ("projects", "0002_tasktemplate"),
        ("tracking", "0002_timeentry_invoice"),
    ]

    operations = [
        migrations.RunPython(backup, migrations.RunPython.noop),
    ]
