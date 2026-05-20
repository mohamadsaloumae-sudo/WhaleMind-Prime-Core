"""
main.py — WhaleX Prime Core v3 (HFT Edition)
"""
import asyncio, logging
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

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s")
settings = get_settings()

app = FastAPI(title="WhaleX Prime Core HFT", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(ws.router)
app.include_router(auth_router)
app.include_router(sub_router)
app.include_router(ai.router)
app.include_router(trade.router)
app.include_router(signals.router)
app.include_router(wallet.router)
app.include_router(admin_router)
app.include_router(hft_router)

app.mount("/static",      StaticFiles(directory="static"),           name="static")
app.mount("/admin-panel", StaticFiles(directory="static/admin", html=True), name="admin")

@app.on_event("startup")
async def startup():
    create_tables()
    db = SessionLocal()
    try:   seed_admin(db)
    finally: db.close()
    asyncio.create_task(signal_broadcaster())
    await launch_hft_engine()

@app.on_event("shutdown")
async def shutdown():
    await shutdown_hft_engine()

@app.get("/health")
async def health():
    from hft.engine.context import GCM
    return {"status":"ok","version":"3.0.0",
            "radar_score": GCM.radar.composite_score,
            "active_trades": len(GCM.active_trades)}
