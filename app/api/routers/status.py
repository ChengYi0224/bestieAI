"""status.py — 系統與 Bot 狀態 API 路由模組。"""
from typing import Any, Dict
from fastapi import APIRouter, Depends
from app.api.dependencies import get_current_user, get_status_service
from app.api.schemas.common import StatusResponse
from app.services.status_api_service import StatusApiService

router = APIRouter(tags=["Status"])


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="取得系統與 Bot 運作狀態",
)
async def get_status(
    status_service: StatusApiService = Depends(get_status_service),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> StatusResponse:
    """檢查系統健康度並取得登入使用者自己的 Bot Worker 狀態。"""
    data = status_service.get_system_status(user_id=current_user["id"])
    return StatusResponse(**data)
