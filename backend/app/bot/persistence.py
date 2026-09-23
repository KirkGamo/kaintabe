"""Persist conversation state and user_data in Postgres so a restart doesn't lose half-finished posts.

Only user_data and conversation states are stored (chat/bot/callback data are unused by this bot).
Values must be JSON-safe: handlers keep Telegram file ids (not photo bytes) in user_data; UUIDs and
datetimes are stored as strings and come back as strings.
"""
import asyncio
import json
from typing import Any

from telegram.ext import BasePersistence, PersistenceInput

from app import db


def _dumps(value: Any) -> str:
    return json.dumps(value, default=str)


class DbPersistence(BasePersistence):
    def __init__(self, bot_id: str, update_interval: float = 5):
        super().__init__(
            store_data=PersistenceInput(bot_data=False, chat_data=False, user_data=True, callback_data=False),
            update_interval=update_interval,
        )
        self.bot_id = bot_id  # token prefix: keeps the dev and prod bots apart in the shared DB

    # --- sync DB helpers (run in a thread) -------------------------------------------

    def _load(self, kind: str) -> list[dict]:
        with db.connect() as conn:
            return conn.execute(
                "select key, data from bot_state where bot_id = %s and kind = %s", (self.bot_id, kind)
            ).fetchall()

    def _save(self, kind: str, key: str, data: Any) -> None:
        with db.connect() as conn:
            conn.execute(
                """
                insert into bot_state (bot_id, kind, key, data, updated_at) values (%s, %s, %s, %s::jsonb, now())
                on conflict (bot_id, kind, key) do update set data = excluded.data, updated_at = now()
                """,
                (self.bot_id, kind, key, _dumps(data)),
            )

    def _delete(self, kind: str, key: str) -> None:
        with db.connect() as conn:
            conn.execute("delete from bot_state where bot_id = %s and kind = %s and key = %s", (self.bot_id, kind, key))

    # --- user_data ---------------------------------------------------------------------

    async def get_user_data(self) -> dict[int, dict]:
        rows = await asyncio.to_thread(self._load, "user")
        return {int(r["key"]): r["data"] for r in rows}

    async def update_user_data(self, user_id: int, data: dict) -> None:
        if data:
            await asyncio.to_thread(self._save, "user", str(user_id), data)
        else:  # nothing in progress: don't keep an empty row around
            await asyncio.to_thread(self._delete, "user", str(user_id))

    async def refresh_user_data(self, user_id: int, user_data: dict) -> None:
        pass  # this process is the only writer; nothing to refresh

    async def drop_user_data(self, user_id: int) -> None:
        await asyncio.to_thread(self._delete, "user", str(user_id))

    # --- conversations -----------------------------------------------------------------

    async def get_conversations(self, name: str) -> dict[tuple, object]:
        rows = await asyncio.to_thread(self._load, f"conv:{name}")
        return {tuple(json.loads(r["key"])): r["data"] for r in rows}

    async def update_conversation(self, name: str, key: tuple, new_state: object | None) -> None:
        kind, k = f"conv:{name}", json.dumps(list(key))
        if new_state is None:
            await asyncio.to_thread(self._delete, kind, k)
        else:
            await asyncio.to_thread(self._save, kind, k, new_state)

    # --- unused stores (required by the interface) ---------------------------------------

    async def get_chat_data(self) -> dict:
        return {}

    async def update_chat_data(self, chat_id: int, data: dict) -> None:
        pass

    async def refresh_chat_data(self, chat_id: int, chat_data: dict) -> None:
        pass

    async def drop_chat_data(self, chat_id: int) -> None:
        pass

    async def get_bot_data(self) -> dict:
        return {}

    async def update_bot_data(self, data: dict) -> None:
        pass

    async def refresh_bot_data(self, bot_data: dict) -> None:
        pass

    async def get_callback_data(self):
        return None

    async def update_callback_data(self, data) -> None:
        pass

    async def flush(self) -> None:
        pass  # every update is written immediately
