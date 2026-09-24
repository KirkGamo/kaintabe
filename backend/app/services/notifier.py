"""Background loop that pushes Telegram notifications which don't come from a user action:
new-food alerts for partner orgs, and flash offers for individuals when a listing escalates."""
import asyncio
import logging

from app.services import flash, org_alerts

log = logging.getLogger(__name__)

INTERVAL_S = 15  # same cadence as the pg_cron tick that widens/escalates listings


async def run_forever(bot) -> None:
    while True:
        for job in (org_alerts.send_pending, flash.send_pending):
            try:
                await job(bot)
            except Exception:  # noqa: BLE001 - e.g. DB unreachable; try again next tick
                log.exception("notifier job %s failed", job.__module__)
        await asyncio.sleep(INTERVAL_S)
