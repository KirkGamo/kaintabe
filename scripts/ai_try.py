"""Run AI photo intake on real food photos and print what it extracts (costs a few cents per photo).

Usage (from repo root):
    backend/.venv/Scripts/python scripts/ai_try.py photo1.jpg photo2.jpg ...
    backend/.venv/Scripts/python scripts/ai_try.py --recent 5     # last 5 donation photos in Supabase
"""
import asyncio
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.services import ai_intake  # noqa: E402


def load_photos(args: list[str]) -> list[tuple[str, bytes, str | None]]:
    if args[:1] == ["--recent"]:
        n = int(args[1]) if len(args) > 1 else 5
        with db.connect() as conn:
            rows = conn.execute(
                "select photo_url, food_type from donations where photo_url is not null order by created_at desc limit %s",
                (n,),
            ).fetchall()
        return [(r["photo_url"].rsplit("/", 1)[1], httpx.get(r["photo_url"]).content, None) for r in rows]
    return [(Path(a).name, Path(a).read_bytes(), None) for a in args]


async def main() -> None:
    if not settings.anthropic_api_key:
        sys.exit("ANTHROPIC_API_KEY is not set in backend/.env")
    photos = load_photos(sys.argv[1:] or ["--recent", "5"])
    print(f"model: {settings.ai_model}\n")
    for name, data, caption in photos:
        t0 = time.perf_counter()
        listing = await ai_intake.parse_food_photo(data, caption)
        took = time.perf_counter() - t0
        print(f"--- {name}  ({len(data) // 1024} KB, {took:.1f}s)")
        if listing is None:
            print("    FAILED (see log above) -> bot would ask manually")
        else:
            for k, v in listing.model_dump().items():
                print(f"    {k:>20}: {v}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
