from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import settings

app = FastAPI(title="Trie Code Food Rescue")

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
