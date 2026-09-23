import logging
import time

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json  # noqa: F401  (re-exported for callers)

from app.config import settings

log = logging.getLogger(__name__)

RETRY_DELAYS_S = (0.5, 1.5, 3.0)  # rides out brief DNS/network blips on flaky wifi


def connect() -> psycopg.Connection:
    """Open a connection, retrying transient failures (e.g. DNS hiccups) before giving up."""
    for attempt, delay in enumerate((*RETRY_DELAYS_S, None), start=1):
        try:
            # prepare_threshold=None: the Supabase pooler doesn't support prepared statements
            return psycopg.connect(settings.database_url, row_factory=dict_row, prepare_threshold=None, connect_timeout=10)
        except psycopg.OperationalError as e:
            if delay is None:
                raise
            log.warning("DB connect failed (attempt %s): %s; retrying in %ss", attempt, str(e).splitlines()[0], delay)
            time.sleep(delay)


def check() -> dict:
    """Confirm the DB is reachable and the extensions we rely on are enabled."""
    with connect() as conn:
        rows = conn.execute(
            "select extname, extversion from pg_extension where extname in ('postgis', 'pg_cron')"
        ).fetchall()
    return {r["extname"]: r["extversion"] for r in rows}
