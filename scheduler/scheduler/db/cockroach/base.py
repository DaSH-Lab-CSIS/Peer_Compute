from django.db.backends.postgresql.base import DatabaseWrapper as PostgreSQLDatabaseWrapper


class DatabaseWrapper(PostgreSQLDatabaseWrapper):
    """
    CockroachDB reports PostgreSQL compatibility as 13.x on the wire.
    Django 4.2+ enforces PostgreSQL 14+ for the postgres backend, which blocks
    Cockroach connections despite wire-level compatibility.
    """

    def check_database_version_supported(self) -> None:
        # Intentionally bypass Django's PostgreSQL version gate for CockroachDB.
        return

