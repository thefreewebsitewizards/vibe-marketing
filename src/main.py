from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.routers import health, reel, plans, script, dashboard
from src.services.telegram_bot import start_bot, stop_bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_bot()
    yield
    await stop_bot()


app = FastAPI(
    title="ReelBot",
    description="Instagram Reel → Business Strategy Pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(reel.router)
app.include_router(plans.router)
app.include_router(script.router)
app.include_router(dashboard.router)


# Mount static files (CSS, JS, images)
static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
