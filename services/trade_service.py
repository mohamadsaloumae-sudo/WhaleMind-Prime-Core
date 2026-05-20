"""
services/trade_service.py — Trade execution logic.

Routes orders through the user-selected DEX.
In production, wire each DEX branch to its actual SDK / smart-contract call.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from core.config import get_settings
from models.schemas import TradeRequest, TradeResponse, SupportedDex

logger = logging.getLogger(__name__)

# DEX → chain affinity (for validation)
DEX_CHAIN_MAP: dict[str, list[str]] = {
    "jupiter":     ["sol"],
    "raydium":     ["sol"],
    "uniswap":     ["eth", "arb", "base"],
    "camelot":     ["arb"],
    "pancakeswap": ["bsc", "arb"],
    "traderjoe":   ["avax", "arb"],
}


async def execute_trade(req: TradeRequest) -> TradeResponse:
    settings  = get_settings()
    gas_fee   = round(req.amount * settings.gas_fee_pct, 4)
    net_amount= round(req.amount - gas_fee, 4)

    # Validate DEX ↔ chain compatibility
    if req.dex:
        allowed_chains = DEX_CHAIN_MAP.get(req.dex.value, [])
        if allowed_chains and req.chain not in allowed_chains:
            return TradeResponse(
                status     = "rejected",
                message    = f"{req.dex.value} does not operate on {req.chain}. Use: {allowed_chains}",
                gas_fee    = 0.0,
                net_amount = 0.0,
            )

    dex_label = req.dex.value.capitalize() if req.dex else "Auto-router"
    logger.info(
        "Executing %s %s %s via %s on %s | amount=%.2f leverage=%dx",
        req.direction, req.trade_type, req.symbol,
        dex_label, req.chain, req.amount, req.leverage,
    )

    # ── Route to DEX ──────────────────────────────────────────────────────────
    tx_hash = _simulate_execution(req, dex_label)

    return TradeResponse(
        status     = "executed",
        tx_hash    = tx_hash,
        message    = (
            f"{req.direction} {req.symbol} executed via {dex_label} "
            f"on {req.chain.upper()} | leverage {req.leverage}× | "
            f"gas fee ${gas_fee}"
        ),
        gas_fee    = gas_fee,
        net_amount = net_amount,
    )


def _simulate_execution(req: TradeRequest, dex: str) -> str:
    """
    Stub — replace with actual on-chain transaction submission.
    Returns a fake tx hash for UI demo purposes.
    """
    fake_hash = uuid.uuid4().hex
    logger.debug("[STUB] %s order routed to %s — tx: %s", req.symbol, dex, fake_hash)
    return fake_hash
