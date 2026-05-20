
"""
core/config.py — Centralised settings loaded from environment variables.
All secrets live here; the frontend never sees them.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    # ── LLM (القديم) ──────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-4-20250514"
    ai_max_tokens: int = 1000

    # ── Blockchain RPCs (القديم) ──────────────────────────────────────────────
    solana_rpc_url:   str = "https://api.mainnet-beta.solana.com"
    ethereum_rpc_url: str = "https://eth.llamarpc.com"
    bsc_rpc_url:      str = "https://bsc-dataseed.binance.org"
    arbitrum_rpc_url: str = "https://arb1.arbitrum.io/rpc"
    base_rpc_url:     str = "https://mainnet.base.org"
    avalanche_rpc_url:str = "https://api.avax.network/ext/bc/C/rpc"
    tron_rpc_url:     str = "https://api.trongrid.io"

    # ── App (القديم) ──────────────────────────────────────────────────────────
    app_secret_key:   str = "change-me-in-production"
    cors_origins:     List[str] = ["*"]
    gas_fee_pct:      float = 0.01

    # ── الجديدة (من ملف .env) ─────────────────────────────────────────────────
    binance_api_key: str = ""
    binance_secret_key: str = ""
    database_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_admin_chat_id: str = ""
    eth_collector_wallet: str = ""
    wallet_address: str = ""
    trongrid_api_key: str = ""
    alchemy_api_key: str = ""
    etherscan_api_key: str = ""
    moralis_api_key: str = ""
    
    # الإعدادات الخاصة بالمنفذ والتحقق
    port: int = 8000
    host: str = "0.0.0.0"
    domain: str = ""
    secret_key: str = ""
    debug: bool = False
    
    # القيم التي تسببت في الخطأ سابقاً
    min_score: int
    min_confidence: int

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache
def get_settings() -> Settings:
    return Settings()
