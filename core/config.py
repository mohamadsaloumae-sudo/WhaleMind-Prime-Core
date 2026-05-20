"""
core/config.py — Centralised settings loaded from System Environment Variables.
"""
import os
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    # ── LLM ──────────────────────────────────────────────────────────
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    ai_model: str = "claude-sonnet-4-20250514"
    ai_max_tokens: int = 1000

    # ── Blockchain RPCs ──────────────────────────────────────────────
    solana_rpc_url:   str = "https://api.mainnet-beta.solana.com"
    ethereum_rpc_url: str = "https://eth.llamarpc.com"
    bsc_rpc_url:      str = "https://bsc-dataseed.binance.org"
    arbitrum_rpc_url: str = "https://arb1.arbitrum.io/rpc"
    base_rpc_url:     str = "https://mainnet.base.org"
    avalanche_rpc_url:str = "https://api.avax.network/ext/bc/C/rpc"
    tron_rpc_url:     str = "https://api.trongrid.io"

    # ── App ──────────────────────────────────────────────────────────
    app_secret_key:   str = os.getenv("SECRET_KEY", "change-me-in-production")
    cors_origins:     List[str] = ["*"]
    gas_fee_pct:      float = 1.0

    # ── Security & Integration ───────────────────────────────────────
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_secret_key: str = os.getenv("BINANCE_SECRET_KEY", "")
    database_url: str = os.getenv("DATABASE_URL", "")
    
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_admin_chat_id: str = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
    
    eth_collector_wallet: str = os.getenv("ETH_COLLECTOR_WALLET", "")
    wallet_address: str = os.getenv("WALLET_ADDRESS", "")
    trongrid_api_key: str = os.getenv("TRONGRID_API_KEY", "")
    alchemy_api_key: str = os.getenv("ALCHEMY_API_KEY", "")
    etherscan_api_key: str = os.getenv("ETHERSCAN_API_KEY", "")
    moralis_api_key: str = os.getenv("MORALIS_API_KEY", "")
    
    # ── System Settings ──────────────────────────────────────────────
    port: int = 8000
    host: str = "0.0.0.0"
    domain: str = os.getenv("DOMAIN", "")
    debug: bool = False
    
    # القيم التي كانت تسبب الخطأ (تم وضع قيم افتراضية)
    min_score: int = 4
    min_confidence: int = 58

    class Config:
        # لا نحدد ملف .env هنا لنعتمد كلياً على بيئة النظام
        case_sensitive = True

def get_settings() -> Settings:
    return Settings()
