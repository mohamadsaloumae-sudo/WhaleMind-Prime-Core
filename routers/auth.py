"""
routers/auth.py — /api/auth/* endpoints.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.auth import create_token, hash_password, verify_password, create_guest_token
from db.database import User, Subscription, get_db
from models.schemas import RegisterRequest, LoginRequest, TokenResponse, GuestTokenResponse

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    user = User(
        uid              = str(uuid.uuid4()),
        username         = body.username,
        email            = body.email,
        hashed_password  = hash_password(body.password),
        subscription_tier= "free",
        is_active        = True,
        is_admin         = False,
    )
    db.add(user); db.commit(); db.refresh(user)
    sub = Subscription(user_id=user.id, plan="free")
    db.add(sub); db.commit()
    token = create_token(user.uid, user.is_admin)
    return TokenResponse(access_token=token, tier="free", uid=user.uid)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username, User.is_active == True).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    token = create_token(user.uid, user.is_admin)
    return TokenResponse(access_token=token, tier=user.subscription_tier, uid=user.uid, is_admin=user.is_admin)


@router.post("/guest", response_model=GuestTokenResponse)
def guest_token():
    """Issue a free-tier guest token — no registration required."""
    return create_guest_token()


@router.get("/me")
def me(db: Session = Depends(get_db), token: str = ""):
    return {"status": "ok"}
