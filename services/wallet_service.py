"""
services/wallet_service.py — Wallet generation and balance lookup.

Supported chains: sol, eth, bsc, arb, base, avax, tron
"""
from __future__ import annotations

import base58
import hashlib
import logging
import secrets
from typing import Any

import httpx

from core.config import get_settings
from models.schemas import Chain

logger = logging.getLogger(__name__)

# ── RPC URL map ────────────────────────────────────────────────────────────────

def _rpc(chain: str) -> str:
    s = get_settings()
    return {
        "sol":  s.solana_rpc_url,
        "eth":  s.ethereum_rpc_url,
        "bsc":  s.bsc_rpc_url,
        "arb":  s.arbitrum_rpc_url,
        "base": s.base_rpc_url,
        "avax": s.avalanche_rpc_url,
        "tron": s.tron_rpc_url,
    }.get(chain, s.ethereum_rpc_url)


# ── Wallet generation ──────────────────────────────────────────────────────────

def generate_wallet(chain: str) -> dict[str, str]:
    """
    Pure-Python wallet generation (no external signing library dependency).
    In production swap these stubs for solders / eth_account / tronpy etc.
    """
    raw_key = secrets.token_bytes(32)
    hex_key = raw_key.hex()

    if chain == "sol":
        # Solana: derive a 32-byte "public key" via SHA-256 (stub)
        pub_bytes = hashlib.sha256(raw_key).digest()
        address   = base58.b58encode(pub_bytes).decode()
    elif chain == "tron":
        h   = hashlib.sha256(raw_key).hexdigest()
        address = "T" + h[:33]
    else:
        # EVM chains (eth / bsc / arb / base / avax)
        h       = hashlib.sha256(raw_key).hexdigest()
        address = "0x" + h[:40]

    return {"address": address, "private_key": hex_key, "chain": chain}


# ── Balance lookup ──────────────────────────────────────────────────────────────

async def get_balance(chain: str, address: str) -> list[dict[str, Any]]:
    """
    Query native balance from RPC. Returns a list of balance entries so the
    response schema is extensible to multi-token queries later.
    """
    try:
        if chain == "sol":
            return await _sol_balance(address)
        elif chain in ("eth", "bsc", "arb", "base", "avax"):
            return await _evm_balance(chain, address)
        else:
            return [{"token": chain.upper(), "amount": 0.0, "usd": 0.0}]
    except Exception as exc:
        logger.warning("Balance lookup failed (%s %s): %s", chain, address, exc)
        return [{"token": chain.upper(), "amount": 0.0, "usd": 0.0, "error": str(exc)}]


async def _sol_balance(address: str) -> list[dict[str, Any]]:
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method":  "getBalance",
        "params":  [address, {"commitment": "confirmed"}],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(_rpc("sol"), json=payload)
        resp.raise_for_status()
        lamports = resp.json().get("result", {}).get("value", 0)
        sol = lamports / 1_000_000_000
        return [{"token": "SOL", "amount": round(sol, 6), "usd": round(sol * 170, 2)}]


async def _evm_balance(chain: str, address: str) -> list[dict[str, Any]]:
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method":  "eth_getBalance",
        "params":  [address, "latest"],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(_rpc(chain), json=payload)
        resp.raise_for_status()
        wei = int(resp.json().get("result", "0x0"), 16)
        eth = wei / 1e18
        symbol = {"bsc": "BNB", "avax": "AVAX"}.get(chain, "ETH")
        price  = {"bsc": 600, "avax": 38}.get(chain, 3240)
        return [{"token": symbol, "amount": round(eth, 6), "usd": round(eth * price, 2)}]
