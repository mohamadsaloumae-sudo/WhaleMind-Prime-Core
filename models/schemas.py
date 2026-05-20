"""
models/schemas.py — All Pydantic request/response models.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field

class Direction(str, Enum):
    LONG = "LONG"; SHORT = "SHORT"

class TradeType(str, Enum):
    futures = "futures"; spot = "spot"; swap = "swap"

class Chain(str, Enum):
    sol = "sol"; eth = "eth"; bsc = "bsc"; arb = "arb"
    base = "base"; avax = "avax"; tron = "tron"

class SupportedDex(str, Enum):
    jupiter = "jupiter"; uniswap = "uniswap"; pancakeswap = "pancakeswap"
    camelot = "camelot"; raydium = "raydium"; traderjoe = "traderjoe"

class RiskLevel(str, Enum):
    low = "low"; medium = "medium"; high = "high"

class SubscriptionPlan(str, Enum):
    free = "free"; pro = "pro"; enterprise = "enterprise"

# Auth
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=40)
    password: str = Field(..., min_length=6)
    email: Optional[str] = None

class LoginRequest(BaseModel):
    username: str; password: str

class TokenResponse(BaseModel):
    access_token: str; tier: str; uid: str; is_admin: bool = False

class GuestTokenResponse(BaseModel):
    access_token: str; tier: str = "free"; uid: str

# Subscription
class PlanInfo(BaseModel):
    plan: str; price: float; currency: str; features: list[str]

class UpgradeRequest(BaseModel):
    plan: SubscriptionPlan = SubscriptionPlan.pro
    chain: Chain = Chain.sol
    wallet_address: str
    tx_hash: Optional[str] = None

class UpgradeResponse(BaseModel):
    status: str; plan: str; message: str; expires_at: Optional[str] = None

class SubscriptionStatus(BaseModel):
    tier: str; plan: str; expires_at: Optional[str]; is_active: bool

# Trade
class TradeRequest(BaseModel):
    symbol: str = Field(..., example="SOL_USDT")
    direction: Direction; amount: float = Field(..., gt=0)
    leverage: int = Field(1, ge=1, le=125)
    sl: Optional[float] = None; tp: Optional[float] = None
    chain: str = Field("sol"); trade_type: TradeType = TradeType.futures
    collateral: str = Field("USDT"); dex: Optional[SupportedDex] = None

class TradeResponse(BaseModel):
    status: str; tx_hash: Optional[str] = None
    message: str; gas_fee: float; net_amount: float

# AI
class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$"); content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]

class ChatResponse(BaseModel):
    reply: str

class MemeAnalysisRequest(BaseModel):
    address: str; chain: Chain = Chain.sol

class MemeAnalysisResponse(BaseModel):
    name: str; symbol: str; price: str; mcap: str; vol24h: str
    change24h: str; holders: str; liquidity_locked: bool
    mint_disabled: bool; owner_renounced: bool
    score: int; risk: RiskLevel; verdict: str; details: str

# Wallet
class WalletGenerateRequest(BaseModel):
    chain: Chain

class WalletGenerateResponse(BaseModel):
    chain: str; address: str; private_key: Optional[str] = None

class WalletAddressResponse(BaseModel):
    chain: str; address: str

class WalletBalanceResponse(BaseModel):
    chain: str; address: str; balances: list[dict[str, Any]]

# Signals
class Signal(BaseModel):
    id: str; symbol: str; direction: Direction; grade: str
    confidence: int; entry: float; sl: float; tp1: float; tp2: float; tp3: float
    strategies: str; chain: str; trade_type: str; timestamp: str

class SignalsResponse(BaseModel):
    signals: list[Signal]; count: int

# Stats
class StatsResponse(BaseModel):
    total_balance: float; open_trades: int; total_signals: int
    symbols_watched: int; roi_pct: float; win_rate_pct: float; total_trades: int

# Admin
class AdminUserView(BaseModel):
    id: int; uid: str; username: Optional[str]; email: Optional[str]
    subscription_tier: str; is_active: bool; is_admin: bool
    created_at: datetime; total_trades: int; total_volume: float

class AdminStatsView(BaseModel):
    total_users: int; pro_users: int; free_users: int
    total_trades: int; total_volume: float; total_revenue: float
    active_signals: int; ws_connections: int

class AdminSetTierRequest(BaseModel):
    user_uid: str; tier: SubscriptionPlan

class AdminBanRequest(BaseModel):
    user_uid: str; reason: str = ""
