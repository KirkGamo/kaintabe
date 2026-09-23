"""db.connect retries transient failures (no real network involved)."""
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from app import db


def test_retries_then_succeeds():
    conn = MagicMock()
    with patch.object(db.psycopg, "connect", side_effect=[psycopg.OperationalError("dns"), psycopg.OperationalError("dns"), conn]) as c, \
         patch.object(db.time, "sleep") as sleep:
        assert db.connect() is conn
    assert c.call_count == 3
    assert [s.args[0] for s in sleep.call_args_list] == [0.5, 1.5]


def test_gives_up_after_all_retries():
    with patch.object(db.psycopg, "connect", side_effect=psycopg.OperationalError("down")) as c, \
         patch.object(db.time, "sleep"):
        with pytest.raises(psycopg.OperationalError):
            db.connect()
    assert c.call_count == len(db.RETRY_DELAYS_S) + 1


def test_real_connection_works():
    with db.connect() as conn:
        assert conn.execute("select 1 as one").fetchone()["one"] == 1
