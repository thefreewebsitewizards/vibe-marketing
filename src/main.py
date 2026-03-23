import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from src.routers import health, reel, plans, script, dashboard, knowledge
from src.services.telegram_bot import start_bot, stop_bot

# Persist logs to file with rotation (in addition to stdout)
_plans_dir = Path(os.getenv("PLANS_DIR", "plans"))
_log_file = _plans_dir / "_server.log"
logger.add(
    str(_log_file),
    rotation="10 MB",
    retention="7 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}",
    level="INFO",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ReelBot starting up")
    start_bot()
    yield
    await stop_bot()
    logger.info("ReelBot shutting down")


app = FastAPI(
    title="ReelBot",
    description="Instagram Reel → Business Strategy Pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

allowed_origins = os.getenv("CORS_ORIGINS", "https://reelbot.leadneedleai.com").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(reel.router)
app.include_router(plans.router)
app.include_router(script.router)
app.include_router(dashboard.router)
app.include_router(knowledge.router)


# Mount static files (CSS, JS, images)
static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
