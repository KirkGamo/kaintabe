import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json  # noqa: F401  (re-exported for callers)

from app.config import settings


def connect() -> psycopg.Connection:
    # prepare_threshold=None: the Supabase pooler doesn't support prepared statements
    return psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None)


def check() -> dict:
    """Confirm the DB is reachable and the extensions we rely on are enabled."""
    with connect() as conn:
        rows = conn.execute(
            "select extname, extversion from pg_extension where extname in ('postgis', 'pg_cron')"
        ).fetchall()
    return {r["extname"]: r["extversion"] for r in rows}
