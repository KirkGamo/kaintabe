"""The API must come up even when Telegram is unreachable; the bot connects later."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from telegram.error import TimedOut

from app import main


def fake_bot(fail_times):
    bot = MagicMock()
    bot.initialize = AsyncMock(side_effect=[TimedOut()] * fail_times + [None])
    bot.start = AsyncMock()
    bot.stop = AsyncMock()
    bot.shutdown = AsyncMock()
    bot.updater.start_polling = AsyncMock()
    bot.updater.stop = AsyncMock()
    bot.running = False
    return bot


def test_bot_retries_until_telegram_is_reachable():
    bot = fake_bot(fail_times=2)
    with patch.object(main.asyncio, "sleep", new_callable=AsyncMock) as sleep:
        asyncio.run(main.start_polling_bot(bot))
    assert bot.initialize.await_count == 3
    assert [c.args[0] for c in sleep.await_args_list] == [2, 4]  # backoff
    bot.updater.start_polling.assert_awaited_once()


def test_api_serves_while_telegram_is_down():
    bot = fake_bot(fail_times=10_000)  # never reachable during this test
    with patch.object(main, "build_application", return_value=bot), \
         patch.object(main.settings, "bot_mode", "polling"), \
         patch.object(main.settings, "telegram_bot_token", "123:TEST"), \
         patch.object(main.asyncio, "sleep", new=AsyncMock(side_effect=lambda s: asyncio.sleep(0.01))):
        with TestClient(main.app) as client:  # runs the lifespan
            assert client.get("/health").status_code == 200
    bot.shutdown.assert_awaited_once()  # clean shutdown even though it never connected
