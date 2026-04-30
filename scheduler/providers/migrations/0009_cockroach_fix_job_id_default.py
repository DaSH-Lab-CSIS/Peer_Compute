from django.db import migrations


def set_job_id_default_for_cockroach(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return

    with connection.cursor() as cursor:
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0]
        if "CockroachDB" not in version:
            return

        # MOLT-created integer primary keys can miss auto-generated defaults.
        # For INT4 columns, unique_rowid() overflows, so use a sequence.
        # For INT8 columns, unique_rowid() is safe.
        cursor.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'providers_job'
              AND column_name = 'id'
            """
        )
        row = cursor.fetchone()
        if not row:
            return

        id_type = row[0]
        if id_type == "integer":
            cursor.execute("CREATE SEQUENCE IF NOT EXISTS public.providers_job_id_seq MINVALUE 1 MAXVALUE 2147483647")
            cursor.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM public.providers_job")
            next_id = cursor.fetchone()[0]
            cursor.execute("SELECT setval('public.providers_job_id_seq', %s, false)", [next_id])
            cursor.execute(
                """
                ALTER TABLE public.providers_job
                ALTER COLUMN id SET DEFAULT nextval('public.providers_job_id_seq')
                """
            )
        else:
            cursor.execute(
                """
                ALTER TABLE public.providers_job
                ALTER COLUMN id SET DEFAULT unique_rowid()
                """
            )


class Migration(migrations.Migration):

    dependencies = [
        ("providers", "0008_remove_job_last_recovery_attempt_and_more"),
    ]

    operations = [
        migrations.RunPython(
            set_job_id_default_for_cockroach,
            migrations.RunPython.noop,
        ),
    ]

