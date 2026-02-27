from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routers import health, reel
from src.services.telegram_bot import start_bot, stop_bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_bot()
    yield
    await stop_bot()


app = FastAPI(
    title="Vibe Marketing",
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
