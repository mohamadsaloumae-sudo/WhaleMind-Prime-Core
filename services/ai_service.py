"""
services/ai_service.py — All LLM calls happen here, never in the frontend.
The Anthropic API key never leaves the server.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from core.config import get_settings
from models.schemas import ChatMessage, MemeAnalysisResponse, RiskLevel

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are WhaleX AI, an advanced crypto trading assistant.
You have access to:
1. Live trading signals (Futures / Spot / Meme Coins)
2. Meme coin scanning & Rug Pull detection
3. Risk assessment and trend prediction

Portfolio snapshot: SOL $2108, ETH $1560, BNB $780, USDC $380
Active signals: SOL/USDT LONG (82% confidence), ETH/USDT SHORT (91% confidence)

Rules:
- Keep replies concise and actionable (3–5 lines)
- Use numbers; always append "⚠️ Not financial advice"
- Reply in the same language the question was asked in
"""

MEME_PROMPT_TEMPLATE = """Analyze this meme coin: address={address} on chain={chain}.
Return ONLY a valid JSON object (no markdown, no backticks) with these exact keys:
{{
  "name": "...",
  "symbol": "...",
  "price": "$...",
  "mcap": "$...",
  "vol24h": "$...",
  "change24h": "+X.X%",
  "holders": "...",
  "liquidity_locked": true/false,
  "mint_disabled": true/false,
  "owner_renounced": true/false,
  "score": 0-100,
  "risk": "low|medium|high",
  "verdict": "short verdict emoji + text",
  "details": "2-3 sentence analysis"
}}"""


async def chat(messages: list[ChatMessage]) -> str:
    """Send conversation to Claude, return assistant reply."""
    settings = get_settings()
    payload = {
        "model":      settings.ai_model,
        "max_tokens": settings.ai_max_tokens,
        "system":     SYSTEM_PROMPT,
        "messages":   [{"role": m.role, "content": m.content} for m in messages],
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return "".join(b.get("text", "") for b in data.get("content", []))
    except httpx.HTTPStatusError as exc:
        logger.error("Claude API HTTP error: %s — %s", exc.response.status_code, exc.response.text)
        raise
    except Exception as exc:
        logger.exception("Claude API unexpected error: %s", exc)
        raise


async def analyze_meme(address: str, chain: str) -> MemeAnalysisResponse:
    """Ask Claude to analyse a meme-coin contract address; parse the JSON reply."""
    settings = get_settings()
    prompt   = MEME_PROMPT_TEMPLATE.format(address=address, chain=chain)
    payload  = {
        "model":      settings.ai_model,
        "max_tokens": 600,
        "messages":   [{"role": "user", "content": prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            raw  = "".join(b.get("text", "") for b in data.get("content", []))

        # Strip any accidental markdown fences
        raw = re.sub(r"```[a-z]*", "", raw).strip().rstrip("`")
        coin: dict[str, Any] = json.loads(raw)

        return MemeAnalysisResponse(
            name             = coin.get("name",  "UNKNOWN"),
            symbol           = coin.get("symbol","???"),
            price            = coin.get("price", "N/A"),
            mcap             = coin.get("mcap",  "N/A"),
            vol24h           = coin.get("vol24h","N/A"),
            change24h        = coin.get("change24h","N/A"),
            holders          = coin.get("holders","N/A"),
            liquidity_locked = bool(coin.get("liquidity_locked", False)),
            mint_disabled    = bool(coin.get("mint_disabled",    False)),
            owner_renounced  = bool(coin.get("owner_renounced",  False)),
            score            = int(coin.get("score", 50)),
            risk             = RiskLevel(coin.get("risk","medium")),
            verdict          = coin.get("verdict","N/A"),
            details          = coin.get("details","No details returned."),
        )
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Meme analysis JSON parse failed: %s", exc)
        # Return a safe fallback so the UI still renders
        return MemeAnalysisResponse(
            name="UNKNOWN", symbol="???", price="N/A", mcap="N/A",
            vol24h="N/A", change24h="N/A", holders="N/A",
            liquidity_locked=False, mint_disabled=False, owner_renounced=False,
            score=0, risk=RiskLevel.high,
            verdict="⚠️ Analysis unavailable",
            details="Could not parse contract data. Proceed with extreme caution.",
        )
