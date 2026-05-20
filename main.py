from services.ai_agent import get_ai_solution
from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from core.config import get_settings
from db.database import create_tables, seed_admin, SessionLocal
from routers import ai, signals, trade, wallet, ws
from routers.auth import router as auth_router
from routers.subscription import router as sub_router
from routers.admin import router as admin_router
from routers.hft import router as hft_router
from routers.telegram import router as tg_router
from services.signals_service import signal_broadcaster
from services.telegram_service import TG
from hft.engine.startup import launch_hft_engine, shutdown_hft_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s - %(message)s")
log = logging.getLogger(__name__)
settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("WhaleX Prime Core v3 starting up")
    try:
        create_tables()
        db = SessionLocal()
        try:
            seed_admin(db)
        finally:
            db.close()
        asyncio.create_task(signal_broadcaster(), name="signal_broadcaster")
        await launch_hft_engine()
        await TG.setup()
        asyncio.create_task(TG.run_queue_consumer(), name="tg_queue_consumer")
        log.info("WhaleX Prime Core v3 ready - Telegram bridge active")
        yield
    except Exception as e:
        error_msg = str(e)
        log.critical(f"خطأ كارثي عند التشغيل: {error_msg}")
        solution = get_ai_solution(error_msg)
        log.error(f"تحليل كلاود للخطأ: {solution}")
    finally:
        log.info("Shutting down")
        TG.stop()
        await shutdown_hft_engine()
        log.info("Shutdown complete")

app = FastAPI(title="WhaleX Prime Core HFT", version="3.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(ws.router)
app.include_router(auth_router)
app.include_router(sub_router)
app.include_router(ai.router)
app.include_router(trade.router)
app.include_router(signals.router)
app.include_router(wallet.router)
app.include_router(admin_router)
app.include_router(hft_router)
app.include_router(tg_router)

@app.get("/", include_in_schema=False)
async def root(): return RedirectResponse(url="/static/index.html", status_code=302)
@app.get("/app", include_in_schema=False)
async def app_route(): return RedirectResponse(url="/static/index.html", status_code=302)
@app.get("/hft", include_in_schema=False)
async def hft_route(): return RedirectResponse(url="/static/hft.html", status_code=302)
@app.get("/admin", include_in_schema=False)
async def admin_route(): return RedirectResponse(url="/admin-panel/", status_code=302)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/admin-panel", StaticFiles(directory="static/admin", html=True), name="admin_panel")

@app.get("/health")
async def health():
    from hft.engine.context import GCM
    return {"status": "ok", "version": "3.0.0", "radar_score": GCM.radar.composite_score, "active_trades": len(GCM.active_trades), "telegram": bool(settings.telegram_bot_token)}
