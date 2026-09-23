"""Apply pending SQL migrations (and optionally the seed) to the Supabase DB.

Usage (from repo root, using the backend venv):
    backend/.venv/Scripts/python scripts/apply_sql.py          # pending migrations
    backend/.venv/Scripts/python scripts/apply_sql.py --seed   # + supabase/seed.sql
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import db  # noqa: E402

MIGRATIONS = ROOT / "supabase" / "migrations"
SEED = ROOT / "supabase" / "seed.sql"


def main() -> None:
    with db.connect() as conn:
        conn.execute(
            "create table if not exists schema_migrations ("
            " name text primary key, applied_at timestamptz not null default now())"
        )
        conn.execute("alter table schema_migrations enable row level security")
        applied = {r["name"] for r in conn.execute("select name from schema_migrations")}
        conn.commit()

        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in applied:
                continue
            print(f"applying {path.name} ...")
            # One transaction per migration: all or nothing
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("insert into schema_migrations (name) values (%s)", (path.name,))
            print(f"  ok")

        if "--seed" in sys.argv:
            print("seeding ...")
            with conn.transaction():
                conn.execute(SEED.read_text(encoding="utf-8"))
            print("  ok")

    print("done")


if __name__ == "__main__":
    main()
