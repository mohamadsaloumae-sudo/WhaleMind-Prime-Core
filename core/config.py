"""
core/config.py — Centralised settings loaded from environment variables.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM ───────────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    ai_model:          str = "claude-sonnet-4-20250514"
    ai_max_tokens:     int = 1000

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token:    str = ""   # من BotFather: 123456:ABC-DEF...
    telegram_channel_id:   str = ""   # قناة الإشارات: @YourChannel أو -100123456
    telegram_admin_chat_id:str = ""   # Chat ID الخاص بك لاستقبال التنبيهات
    telegram_mini_app_url: str = ""   # https://yourdomain.com/

    # ── Blockchain RPCs ────────────────────────────────────────────────────────
    solana_rpc_url:    str = "https://api.mainnet-beta.solana.com"
    ethereum_rpc_url:  str = "https://eth.llamarpc.com"
    bsc_rpc_url:       str = "https://bsc-dataseed.binance.org"
    arbitrum_rpc_url:  str = "https://arb1.arbitrum.io/rpc"
    base_rpc_url:      str = "https://mainnet.base.org"
    avalanche_rpc_url: str = "https://api.avax.network/ext/bc/C/rpc"
    tron_rpc_url:      str = "https://api.trongrid.io"

    # ── App ───────────────────────────────────────────────────────────────────
    app_secret_key: str        = "change-me-in-production"
    cors_origins:   list[str]  = ["*"]
    gas_fee_pct:    float      = 0.01

    class Config:
        env_file          = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
