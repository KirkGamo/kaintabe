import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from telegram import MenuButtonWebApp, Update, WebAppInfo

from app import db, tg_auth
from app.bot.handlers import build_application
from app.bot.persistence import DbPersistence
from app.config import settings
from app.routes import router
from app.services import notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log bot-token URLs
log = logging.getLogger(__name__)

WEBHOOK_PATH = "/telegram/webhook"

BOT_COMMANDS = [
    ("start", "Start or see your options"),
    ("mylistings", "See or take down food you posted"),
    ("profile", "Update your donor details"),
    ("stop", "Stop free-food offers"),
    ("cancel", "Cancel what you're doing"),
]


async def start_bot(bot, mode: str) -> None:
    """Connect to Telegram, retrying with backoff; a flaky network must not block the API."""
    delay = 2
    while True:
        try:
            await bot.initialize()
            break
        except Exception as e:  # noqa: BLE001 - any failure here is a connectivity problem
            log.warning("Telegram unreachable (%s); retrying in %ss", type(e).__name__, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
    tg_auth._bot_username = bot.bot.username  # the API links Mini App users to orgs of this bot
    try:  # the "/" menu and the 🗺️ Map button in the chat; cosmetic, so never block startup on them
        await bot.bot.set_my_commands(BOT_COMMANDS)
        if settings.map_url:
            await bot.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="🗺️ Map", web_app=WebAppInfo(url=settings.map_url))
            )
    except Exception as e:  # noqa: BLE001
        log.warning("could not set bot commands/menu: %s", type(e).__name__)
    await bot.start()
    if mode == "webhook":
        await bot.bot.set_webhook(
            url=f"{settings.public_url}{WEBHOOK_PATH}",
            secret_token=settings.webhook_secret,
            allowed_updates=Update.ALL_TYPES,
        )
        log.info("Telegram bot @%s receiving via webhook", bot.bot.username)
    else:
        # Note: this removes any webhook, so don't poll locally while a deployed bot uses the same token
        await bot.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram bot @%s polling", bot.bot.username)


async def run_bot(bot, mode: str) -> None:
    """Connect the bot, then keep sending alerts and flash offers until shutdown cancels this task."""
    await start_bot(bot, mode)
    await notifier.run_forever(bot.bot)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot = starter = None
    mode = settings.bot_mode
    if mode == "webhook" and not (settings.public_url and settings.webhook_secret):
        log.error("BOT_MODE=webhook needs PUBLIC_URL and WEBHOOK_SECRET; bot disabled")
        mode = "off"
    if settings.telegram_bot_token and mode in ("polling", "webhook"):
        bot = build_application(
            settings.telegram_bot_token,
            # keyed by bot id (token prefix) so the dev and prod bots never share saved state
            persistence=DbPersistence(bot_id=settings.telegram_bot_token.split(":", 1)[0]),
        )
        starter = asyncio.create_task(run_bot(bot, mode))
    app.state.bot = bot
    yield
    if starter and not starter.done():
        starter.cancel()
    if bot and bot.running:
        if bot.updater.running:
            await bot.updater.stop()
        await bot.stop()
    if bot:
        await bot.shutdown()


app = FastAPI(title="KainTabe", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.post(WEBHOOK_PATH, include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if not settings.webhook_secret or not secrets.compare_digest(
        x_telegram_bot_api_secret_token or "", settings.webhook_secret
    ):
        raise HTTPException(403)
    bot = request.app.state.bot
    if not bot or not bot.running:
        raise HTTPException(503, "Bot starting")  # Telegram retries later
    await bot.update_queue.put(Update.de_json(await request.json(), bot.bot))
    return {"ok": True}


@app.get("/health")
def health():
    try:
        extensions = db.check()
        return {"status": "ok", "db": "ok", "extensions": extensions}
    except Exception as e:
        return {"status": "ok", "db": "error", "detail": type(e).__name__}
