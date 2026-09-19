"""messages.py — 歷史私訊 API 路由模組。"""
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from app.api.dependencies import get_current_user, get_message_service
from app.api.schemas.common import ErrorResponse
from app.api.schemas.message import MessageResponse
from app.services.message_api_service import MessageApiService

router = APIRouter(prefix="/contacts", tags=["Messages"])


@router.get(
    "/{contact_id}/messages",
    response_model=list[MessageResponse],
    responses={404: {"model": ErrorResponse, "description": "聯絡人不存在"}},
    summary="取得聯絡人歷史訊息紀錄（分頁）",
)
async def get_contact_messages(
    contact_id: int,
    response: Response,
    limit: int = Query(default=50, ge=1, le=200, description="單頁筆數"),
    offset: int = Query(default=0, ge=0, description="位移筆數"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    message_service: MessageApiService = Depends(get_message_service),
) -> list[MessageResponse]:
    """分頁查詢指定聯絡人的歷史私訊紀錄，並在 Header 附加總筆數。"""
    result = message_service.get_contact_messages(
        contact_id,
        limit=limit,
        offset=offset,
        user_id=current_user["id"],
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contact {contact_id} not found",
        )

    total, messages = result
    response.headers["X-Total-Count"] = str(total)
    return [MessageResponse.model_validate(dict(m)) for m in messages]
