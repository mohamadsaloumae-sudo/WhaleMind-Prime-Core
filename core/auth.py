"""
core/auth.py — JWT authentication + subscription tier enforcement.

Every protected endpoint calls `require_pro()` which:
1. Validates the JWT
2. Loads the user from DB
3. Raises HTTP 403 if tier is not 'pro'
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from core.config import get_settings
from db.database import User, get_db

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 72


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()

def verify_password(plain: str, hashed: str) -> bool:
    return hash_password(plain) == hashed


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_token(user_uid: str, is_admin: bool = False) -> str:
    settings = get_settings()
    payload = {
        "sub":      user_uid,
        "admin":    is_admin,
        "exp":      datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS),
        "iat":      datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


# ── FastAPI dependency helpers ────────────────────────────────────────────────

def _extract_token(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    return authorization.removeprefix("Bearer ").strip()


def get_current_user(
    token: str = Depends(_extract_token),
    db:    Session = Depends(get_db),
) -> User:
    payload = decode_token(token)
    uid     = payload.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="Bad token payload")
    user = db.query(User).filter(User.uid == uid, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    return user


def require_pro(user: User = Depends(get_current_user)) -> User:
    """
    Hard paywall gate — enforced in backend.
    Free users get 403; the actual data is never returned.
    """
    if user.subscription_tier != "pro":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code":    "SUBSCRIPTION_REQUIRED",
                "message": "This feature requires a PRO subscription.",
                "upgrade": "/api/subscription/plans",
            },
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── Guest token for demo/development ─────────────────────────────────────────

def create_guest_token() -> dict:
    """
    Returns a temporary FREE-tier token so the frontend can boot without
    a login flow. In production, replace with real auth.
    """
    fake_uid = "guest-" + str(uuid.uuid4())
    token    = create_token(fake_uid, is_admin=False)
    return {"access_token": token, "tier": "free", "uid": fake_uid}
