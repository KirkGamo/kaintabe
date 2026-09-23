"""Seed a week of SAMPLE past pickups so the impact dashboard has history for the demo.

Every row is tagged {"simulated": true, "seed_history": true} and is removed by
    backend/.venv/Scripts/python scripts/sim_post.py --clear
Say on stage that the history is sample data; only the live pickup is real.

Usage (from repo root):
    backend/.venv/Scripts/python scripts/seed_demo_history.py            # 6 past days
    backend/.venv/Scripts/python scripts/seed_demo_history.py --replace  # wipe old seed first
"""
import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import db  # noqa: E402

MANILA = timezone(timedelta(hours=8))
MARK = {"hygienic": True, "safe_temperature": True, "contents_known": True, "simulated": True, "seed_history": True}

DONORS = ["00000000-0000-0000-0000-00000000d001", "00000000-0000-0000-0000-00000000d002",
          "00000000-0000-0000-0000-00000000d003"]
PANTRIES = ["00000000-0000-0000-0000-00000000a001", "00000000-0000-0000-0000-00000000a002",
            "00000000-0000-0000-0000-00000000a003"]
# (food, quantity, kg, typical sale price if sold)
FOODS = [
    ("Pandesal", "40 pieces", 2.0, 60), ("Ensaymada", "12 pieces", 1.2, 90), ("Spanish bread", "20 pieces", 1.5, 70),
    ("Chicken adobo with rice", "10 packs", 4.0, 250), ("Pancit canton", "3 trays", 4.5, 300),
    ("Lumpiang shanghai", "60 pieces", 2.0, 180), ("Assorted kakanin", "25 pieces", 2.5, 150),
    ("Bananas (ripe)", "2 bunches", 3.0, 80), ("La Paz batchoy broth", "2 pots", 6.0, 0),
    ("Pork sinigang", "1 pot", 5.0, 0), ("Puto and kutsinta", "30 pieces", 1.8, 100),
]
PICKUPS_PER_DAY = [3, 4, 4, 5, 6, 7]  # growing week, oldest first


def seeded_count(conn) -> int:
    return conn.execute("select count(*) n from donations where safety_checklist @> '{\"seed_history\": true}'").fetchone()["n"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--replace", action="store_true", help="delete previously seeded history first")
    a = p.parse_args()
    rng = random.Random(2026)  # same history every run

    with db.connect() as conn:
        if seeded_count(conn):
            if not a.replace:
                sys.exit("Seed history already exists. Use --replace to regenerate it.")
            conn.execute("delete from claims where donation_id in "
                         "(select id from donations where safety_checklist @> '{\"seed_history\": true}')")
            conn.execute("delete from donations where safety_checklist @> '{\"seed_history\": true}'")

        donors = {str(r["id"]): r for r in conn.execute("select * from donors where id = any(%s)", (DONORS,))}
        today = datetime.now(MANILA).replace(hour=0, minute=0, second=0, microsecond=0)
        total_kg = 0.0
        for days_ago, count in zip(range(len(PICKUPS_PER_DAY), 0, -1), PICKUPS_PER_DAY):
            for _ in range(count):
                donor = donors[rng.choice(DONORS)]
                food, qty, kg, price = rng.choice(FOODS)
                sale = price > 0 and rng.random() < 0.25
                posted = today - timedelta(days=days_ago) + timedelta(hours=rng.uniform(7, 20))
                claimed = posted + timedelta(minutes=rng.uniform(2, 18))
                confirmed = claimed + timedelta(minutes=rng.uniform(20, 75))
                reserved = round(price * rng.uniform(0.45, 0.8)) if sale else None
                d = conn.execute(
                    """
                    insert into donations (donor_id, donor_name, food_type, quantity, est_kg, lat, lng,
                                           safety_checklist, listing_type, original_price, current_price,
                                           expires_at, search_radius_m, radius_widened_at, status, created_at)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 2000, %s, %s, %s)
                    returning id
                    """,
                    (donor["id"], donor["name"], food, qty, kg, donor["lat"], donor["lng"], db.Json(MARK),
                     "sale" if sale else "donation", price if sale else None, reserved,
                     posted + timedelta(hours=4), posted, "sold" if sale else "completed", posted),
                ).fetchone()
                conn.execute(
                    "insert into claims (donation_id, recipient_id, claimed_at, confirmed_at, reserved_price) "
                    "values (%s, %s, %s, %s, %s)",
                    (d["id"], rng.choice(PANTRIES), claimed, confirmed, reserved),
                )
                total_kg += kg
        print(f"seeded {sum(PICKUPS_PER_DAY)} sample pickups over {len(PICKUPS_PER_DAY)} past days ({total_kg:g} kg)")
        print("remove with: backend/.venv/Scripts/python scripts/sim_post.py --clear")


if __name__ == "__main__":
    main()
