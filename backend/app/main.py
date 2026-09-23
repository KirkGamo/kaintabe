import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.bot.handlers import build_application
from app.config import settings
from app.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log bot-token URLs
log = logging.getLogger(__name__)


async def start_polling_bot(bot) -> None:
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
    await bot.start()
    await bot.updater.start_polling(drop_pending_updates=True)
    log.info("Telegram bot @%s polling", bot.bot.username)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot = starter = None
    if settings.telegram_bot_token and settings.bot_mode == "polling":
        bot = build_application(settings.telegram_bot_token)
        starter = asyncio.create_task(start_polling_bot(bot))
    app.state.bot = bot
    yield
    if starter and not starter.done():
        starter.cancel()
    if bot and bot.running:
        await bot.updater.stop()
        await bot.stop()
    if bot:
        await bot.shutdown()


app = FastAPI(title="KainTabe", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health():
    try:
        extensions = db.check()
        return {"status": "ok", "db": "ok", "extensions": extensions}
    except Exception as e:
        return {"status": "ok", "db": "error", "detail": type(e).__name__}
