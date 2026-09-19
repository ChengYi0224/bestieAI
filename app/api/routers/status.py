"""status.py — 系統與 Bot 狀態 API 路由模組。"""
from fastapi import APIRouter, Depends
from app.api.dependencies import get_status_service
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
) -> StatusResponse:
    """檢查系統健康度並取得 Bot Worker 目前狀態。"""
    data = status_service.get_system_status()
    return StatusResponse(**data)
