"""
main.py — WhaleX Prime Core v3 (HFT Edition)
Uses contextlib.asynccontextmanager lifespan (FastAPI modern standard).
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from core.config import get_settings
from db.database import create_tables, seed_admin, SessionLocal
from routers import ai, signals, trade, wallet, ws
from routers.auth import router as auth_router
from routers.subscription import router as sub_router
from routers.admin import router as admin_router
from routers.hft import router as hft_router
from services.signals_service import signal_broadcaster
from hft.engine.startup import launch_hft_engine, shutdown_hft_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
log      = logging.getLogger(__name__)
settings = get_settings()


# ── Lifespan (replaces deprecated @app.on_event) ─────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────────────────────
    log.info("WhaleX Prime Core v3 starting up…")

    # 1. Database
    create_tables()
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()

    # 2. Background services
    asyncio.create_task(signal_broadcaster(), name="signal_broadcaster")

    # 3. HFT Engine (Radar + Copilot + Demo + WS Ingestor)
    await launch_hft_engine()

    log.info("✅ WhaleX Prime Core v3 ready")

    yield   # ← application runs here

    # ── SHUTDOWN ─────────────────────────────────────────────────────────────
    log.info("WhaleX Prime Core shutting down…")
    await shutdown_hft_engine()
    log.info("Shutdown complete")


# ── Application factory ────────────────────────────────────────────────────────

app = FastAPI(
    title       = "WhaleX Prime Core HFT",
    description = "Adaptive HFT — Radar · Co-Pilot · Demo · Admin",
    version     = "3.0.0",
    lifespan    = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = settings.cors_origins,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(ws.router)
app.include_router(auth_router)
app.include_router(sub_router)
app.include_router(ai.router)
app.include_router(trade.router)
app.include_router(signals.router)
app.include_router(wallet.router)
app.include_router(admin_router)
app.include_router(hft_router)

# ── Static files ───────────────────────────────────────────────────────────────
app.mount("/static",      StaticFiles(directory="static"),                name="static")
app.mount("/admin-panel", StaticFiles(directory="static/admin", html=True), name="admin")


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health():
    from hft.engine.context import GCM
    return {
        "status":        "ok",
        "version":       "3.0.0",
        "radar_score":   GCM.radar.composite_score,
        "radar_regime":  GCM.radar.regime.value,
        "active_trades": len(GCM.active_trades),
        "account_mode":  GCM.current_mode.value,
        "ws_clients":    len(GCM.tg_queue._queue) if hasattr(GCM.tg_queue, '_queue') else 0,
    }
