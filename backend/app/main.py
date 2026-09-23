import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.bot.handlers import build_application
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log bot-token URLs
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot = None
    if settings.telegram_bot_token and settings.bot_mode == "polling":
        bot = build_application(settings.telegram_bot_token)
        await bot.initialize()
        await bot.start()
        await bot.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram bot @%s polling", bot.bot.username)
    app.state.bot = bot
    yield
    if bot:
        await bot.updater.stop()
        await bot.stop()
        await bot.shutdown()


app = FastAPI(title="KainTabe", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    try:
        extensions = db.check()
        return {"status": "ok", "db": "ok", "extensions": extensions}
    except Exception as e:
        return {"status": "ok", "db": "error", "detail": type(e).__name__}
