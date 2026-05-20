"""
core/config.py — Centralised settings loaded from environment variables.
All secrets live here; the frontend never sees them.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM ───────────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-4-20250514"
    ai_max_tokens: int = 1000

    # ── Blockchain RPCs ────────────────────────────────────────────────────────
    solana_rpc_url:   str = "https://api.mainnet-beta.solana.com"
    ethereum_rpc_url: str = "https://eth.llamarpc.com"
    bsc_rpc_url:      str = "https://bsc-dataseed.binance.org"
    arbitrum_rpc_url: str = "https://arb1.arbitrum.io/rpc"
    base_rpc_url:     str = "https://mainnet.base.org"
    avalanche_rpc_url:str = "https://api.avax.network/ext/bc/C/rpc"
    tron_rpc_url:     str = "https://api.trongrid.io"

    # ── App ────────────────────────────────────────────────────────────────────
    app_secret_key:   str = "change-me-in-production"
    cors_origins:     list[str] = ["*"]
    gas_fee_pct:      float = 0.01          # 1 % platform gas fee

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
