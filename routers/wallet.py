"""
routers/wallet.py — /api/wallet/* endpoints.
"""
from fastapi import APIRouter, HTTPException

from models.schemas import (
    Chain,
    WalletGenerateRequest, WalletGenerateResponse,
    WalletAddressResponse, WalletBalanceResponse,
)
from services import wallet_service

router = APIRouter(prefix="/api/wallet", tags=["Wallet"])

# In-memory store of generated addresses per chain (dev only; use a DB in prod)
_CHAIN_ADDRESSES: dict[str, str] = {
    "sol":  "7xKp3mN9qR8z...4wBv",
    "eth":  "0x1a2B3c4D5e6F...dEfF",
    "bsc":  "0xBNB3m7kL9...9zX1",
    "arb":  "0xARB1mNpQ...2wRt",
    "base": "0xBASExYz2...5kPo",
    "avax": "X-avax1pQrS...9mNv",
    "tron": "TUsdt3mpQrS...7wXy",
}


@router.post("/generate", response_model=WalletGenerateResponse)
async def generate_wallet(body: WalletGenerateRequest) -> WalletGenerateResponse:
    try:
        result = wallet_service.generate_wallet(body.chain.value)
        _CHAIN_ADDRESSES[body.chain.value] = result["address"]
        return WalletGenerateResponse(
            chain       = result["chain"],
            address     = result["address"],
            private_key = result["private_key"],   # omit / encrypt in production
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{chain}/address", response_model=WalletAddressResponse)
async def get_address(chain: Chain) -> WalletAddressResponse:
    address = _CHAIN_ADDRESSES.get(chain.value, "Not generated")
    return WalletAddressResponse(chain=chain.value, address=address)


@router.get("/{chain}/{address}/balance", response_model=WalletBalanceResponse)
async def get_balance(chain: Chain, address: str) -> WalletBalanceResponse:
    balances = await wallet_service.get_balance(chain.value, address)
    return WalletBalanceResponse(chain=chain.value, address=address, balances=balances)
