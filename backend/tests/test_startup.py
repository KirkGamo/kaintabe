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
        asyncio.run(main.start_bot(bot, "polling"))
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


def test_webhook_mode_registers_webhook():
    bot = fake_bot(fail_times=0)
    bot.bot.set_webhook = AsyncMock()
    with patch.object(main.settings, "public_url", "https://api.example.com"), \
         patch.object(main.settings, "webhook_secret", "s3cret"):
        asyncio.run(main.start_bot(bot, "webhook"))
    kwargs = bot.bot.set_webhook.await_args.kwargs
    assert kwargs["url"] == "https://api.example.com/telegram/webhook"
    assert kwargs["secret_token"] == "s3cret"
    bot.updater.start_polling.assert_not_awaited()


UPDATE = {"update_id": 1, "message": {"message_id": 1, "date": 0, "chat": {"id": 5, "type": "private"}, "text": "/start"}}


def test_webhook_endpoint_checks_secret_and_queues_update():
    bot = MagicMock()
    bot.running = True
    bot.update_queue.put = AsyncMock()
    client = TestClient(main.app)
    main.app.state.bot = bot
    try:
        with patch.object(main.settings, "webhook_secret", "s3cret"):
            assert client.post("/telegram/webhook", json=UPDATE).status_code == 403
            assert client.post("/telegram/webhook", json=UPDATE,
                               headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code == 403
            res = client.post("/telegram/webhook", json=UPDATE, headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
            assert res.status_code == 200
            queued = bot.update_queue.put.await_args.args[0]
            assert queued.update_id == 1 and queued.message.text == "/start"

            bot.running = False  # still connecting to Telegram
            res = client.post("/telegram/webhook", json=UPDATE, headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
            assert res.status_code == 503
    finally:
        main.app.state.bot = None


def test_webhook_rejected_when_no_secret_configured():
    client = TestClient(main.app)
    with patch.object(main.settings, "webhook_secret", ""):
        res = client.post("/telegram/webhook", json=UPDATE, headers={"X-Telegram-Bot-Api-Secret-Token": ""})
    assert res.status_code == 403


def test_cors_origins_parsing():
    with patch.object(main.settings, "frontend_origin", "http://localhost:5173, https://kaintabe.vercel.app/"):
        assert main.settings.cors_origins == ["http://localhost:5173", "https://kaintabe.vercel.app"]


def test_public_url_gets_https_scheme(monkeypatch):
    import importlib

    from app import config

    monkeypatch.setenv("PUBLIC_URL", "my-app.up.railway.app/")
    try:
        assert importlib.reload(config).settings.public_url == "https://my-app.up.railway.app"
        monkeypatch.setenv("PUBLIC_URL", "https://already.example.com")
        assert importlib.reload(config).settings.public_url == "https://already.example.com"
    finally:
        monkeypatch.delenv("PUBLIC_URL")
        importlib.reload(config)
