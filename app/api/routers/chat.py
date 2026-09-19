"""chat.py — AI 陪聊 API 路由模組。"""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_chat_service, get_current_user
from app.api.schemas.action import ChatRequest, ChatResponse
from app.api.schemas.common import ErrorResponse
from app.services.chat_api_service import ChatApiService

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "",
    response_model=ChatResponse,
    responses={
        400: {"model": ErrorResponse, "description": "對話請求參數無效"},
        404: {"model": ErrorResponse, "description": "找不到對象聯絡人"},
    },
    summary="與 AI 陪聊進行對話（支援聯絡人記憶上下文）",
)
async def chat_with_ai(
    payload: ChatRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    chat_service: ChatApiService = Depends(get_chat_service),
) -> ChatResponse:
    """接收使用者文字訊息，結合該使用者的聯絡人 RAG 記憶體提煉上下文，回傳 AI 閨蜜風格回覆。"""
    try:
        reply, resolved_cid = chat_service.chat(
            user_id=current_user["id"],
            message=payload.message,
            contact_id=payload.contact_id,
        )
        return ChatResponse(reply=reply, contact_id=resolved_cid)
    except ValueError as e:
        err_msg = str(e)
        status_code = status.HTTP_404_NOT_FOUND if "找不到" in err_msg else status.HTTP_400_BAD_REQUEST
        raise HTTPException(
            status_code=status_code,
            detail=err_msg,
        )
