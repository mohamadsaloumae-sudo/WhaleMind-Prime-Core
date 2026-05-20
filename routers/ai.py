"""
routers/ai.py — /api/ai/* — PRO only, API key stays server-side.
"""
from fastapi import APIRouter, HTTPException, Depends

from core.auth import require_pro
from db.database import User
from models.schemas import ChatRequest, ChatResponse, MemeAnalysisRequest, MemeAnalysisResponse
from services import ai_service

router = APIRouter(prefix="/api/ai", tags=["AI"])


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(body: ChatRequest, user: User = Depends(require_pro)) -> ChatResponse:
    """PRO ONLY — Anthropic API key never exposed to client."""
    if not body.messages:
        raise HTTPException(422, "messages list is empty")
    try:
        reply = await ai_service.chat(body.messages)
        return ChatResponse(reply=reply)
    except Exception as exc:
        raise HTTPException(502, f"LLM error: {exc}") from exc


@router.post("/analyze-meme", response_model=MemeAnalysisResponse)
async def analyze_meme_endpoint(body: MemeAnalysisRequest, user: User = Depends(require_pro)):
    """PRO ONLY — Meme coin rug-pull analysis via AI."""
    try:
        return await ai_service.analyze_meme(body.address, body.chain.value)
    except Exception as exc:
        raise HTTPException(502, f"Analysis error: {exc}") from exc
