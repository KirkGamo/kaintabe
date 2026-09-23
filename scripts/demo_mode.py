"""Switch auto-widen timing between real-world and on-stage values.

Usage (from repo root):
    backend/.venv/Scripts/python scripts/demo_mode.py on       # widen every 1 min
    backend/.venv/Scripts/python scripts/demo_mode.py on 0.5   # widen every 30 s
    backend/.venv/Scripts/python scripts/demo_mode.py off      # back to 10 min
    backend/.venv/Scripts/python scripts/demo_mode.py          # show current settings
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import db  # noqa: E402

REAL_MINUTES = 10
DEMO_MINUTES = 1


def main() -> None:
    args = sys.argv[1:]
    with db.connect() as conn:
        if args:
            minutes = REAL_MINUTES if args[0] == "off" else float(args[1]) if len(args) > 1 else DEMO_MINUTES
            conn.execute("update app_config set value = %s where key = 'widen_after_minutes'", (minutes,))
        for r in conn.execute("select key, value from app_config order by key"):
            print(f"{r['key']:>22} = {r['value']:g}")


if __name__ == "__main__":
    main()
