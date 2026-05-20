"""
hft/engine/startup.py
Wires and launches all HFT coroutines as asyncio tasks.
Called from main.py on startup.
"""
from __future__ import annotations
import asyncio, logging
from hft.engine.context import GCM
from hft.engine.orchestrator import SignalOrchestrator
from hft.execution.ingestor import BinanceFuturesIngestor
from hft.macro.advisor import MacroAdvisor
from hft.position.copilot import PositionManager
from hft.radar.anti_spoof import AntiSpoofRadar
from hft.simulator.demo_engine import DemoSimulator

log = logging.getLogger("hft.startup")
SYMBOL = "BTCUSDT"

# Module singletons (imported by routers)
radar   = AntiSpoofRadar(SYMBOL)
macro   = MacroAdvisor()
pm      = PositionManager()
demo    = DemoSimulator()
orch    = SignalOrchestrator(pm, demo)
ingestor= BinanceFuturesIngestor(SYMBOL, radar_feed_cb=radar.feed_trade)

async def launch_hft_engine() -> None:
    log.info("═══ Launching HFT Engine ═══")
    asyncio.create_task(ingestor.run(),  name="ingestor")
    asyncio.create_task(radar.run(),     name="radar")
    asyncio.create_task(macro.run(),     name="macro")
    asyncio.create_task(demo.run(),      name="demo_sim")
    asyncio.create_task(orch.run(),      name="orchestrator")
    log.info("All HFT tasks spawned ✓")

async def shutdown_hft_engine() -> None:
    GCM.running = False
    ingestor.stop(); radar.stop(); macro.stop()
    demo.stop();     orch.stop()
    log.info("HFT engine stopped")
