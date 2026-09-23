"""Create a demo donation without a phone (for testing the live map and rehearsing).

Usage (from repo root):
    backend/.venv/Scripts/python scripts/sim_post.py                      # random demo listing
    backend/.venv/Scripts/python scripts/sim_post.py --food "Pandesal" --qty "40 pcs" --kg 2 --hours 4 --donor bakery
    backend/.venv/Scripts/python scripts/sim_post.py --clear              # delete all simulated listings
"""
import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import db  # noqa: E402
from app.services import repo  # noqa: E402

DEMO_DONORS = {
    "bakery": "00000000-0000-0000-0000-00000000d001",     # Panaderia sa Mandurriao
    "carinderia": "00000000-0000-0000-0000-00000000d002",  # Molo Carinderia
    "household": "00000000-0000-0000-0000-00000000d003",   # Household in Jaro
}

SAMPLES = [
    ("Pandesal", "40 pieces", 2),
    ("Chicken adobo with rice", "12 packs", 4),
    ("Pancit canton", "3 trays", 4),
    ("Assorted kakanin", "25 pieces", 2),
    ("Lumpiang shanghai", "60 pieces", 2),
    ("Bananas (ripe)", "2 bunches", 3),
]

SIM_MARK = {"simulated": True}  # tag in safety_checklist so --clear only removes sim rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--donor", choices=DEMO_DONORS, default=None)
    p.add_argument("--food")
    p.add_argument("--qty")
    p.add_argument("--kg", type=float)
    p.add_argument("--hours", type=float, default=None)
    p.add_argument("--lat", type=float)
    p.add_argument("--lng", type=float)
    p.add_argument("--clear", action="store_true")
    a = p.parse_args()

    if a.clear:
        with db.connect() as conn:
            conn.execute(
                "delete from claims where donation_id in "
                "(select id from donations where safety_checklist @> '{\"simulated\": true}')"
            )
            n = conn.execute("delete from donations where safety_checklist @> '{\"simulated\": true}'").rowcount
        print(f"deleted {n} simulated listings")
        return

    donor_key = a.donor or random.choice(list(DEMO_DONORS))
    with db.connect() as conn:
        donor = conn.execute("select * from donors where id = %s", (DEMO_DONORS[donor_key],)).fetchone()

    food, qty, kg = random.choice(SAMPLES)
    d = repo.create_donation(
        donor=donor,
        photo_url=None,
        food_type=a.food or food,
        quantity=a.qty or qty,
        est_kg=a.kg if a.kg is not None else kg,
        lat=a.lat if a.lat is not None else donor["lat"],
        lng=a.lng if a.lng is not None else donor["lng"],
        good_for_hours=a.hours if a.hours is not None else random.choice([2, 4, 8]),
        safety_checklist={"hygienic": True, "safe_temperature": True, "contents_known": True, **SIM_MARK},
    )
    print(f"posted {d['food_type']} ({d['quantity']}) from {d['donor_name']}, expires {d['expires_at']:%H:%M}, id={d['id']}")


if __name__ == "__main__":
    main()
