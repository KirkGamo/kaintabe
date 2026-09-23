"""Switch the auto-widen and sale-price timers between real-world and on-stage values.

Usage (from repo root):
    backend/.venv/Scripts/python scripts/demo_mode.py on       # both timers 1 min
    backend/.venv/Scripts/python scripts/demo_mode.py on 0.5   # both timers 30 s
    backend/.venv/Scripts/python scripts/demo_mode.py off      # widen 10 min, sale window 60 min
    backend/.venv/Scripts/python scripts/demo_mode.py          # show current settings
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import db  # noqa: E402

REAL = {"widen_after_minutes": 10, "sale_window_minutes": 60}
DEMO_MINUTES = 1


def main() -> None:
    args = sys.argv[1:]
    with db.connect() as conn:
        if args:
            if args[0] == "off":
                values = REAL
            else:
                minutes = float(args[1]) if len(args) > 1 else DEMO_MINUTES
                values = {key: minutes for key in REAL}
            for key, value in values.items():
                conn.execute("update app_config set value = %s where key = %s", (value, key))
        for r in conn.execute("select key, value from app_config order by key"):
            print(f"{r['key']:>22} = {r['value']:g}")


if __name__ == "__main__":
    main()
