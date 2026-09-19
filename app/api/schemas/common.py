"""common.py — 通用 API Pydantic Schema 定義。"""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """通用分頁查詢參數。"""
    limit: int = Field(default=50, ge=1, le=200, description="單頁筆數")
    offset: int = Field(default=0, ge=0, description="位移筆數")


class ErrorResponse(BaseModel):
    """標準錯誤回應結構。"""
    detail: str = Field(description="錯誤訊息說明")
    code: Optional[str] = Field(default=None, description="錯誤碼")


class StatusResponse(BaseModel):
    """系統健康狀態與 Bot 狀態回應結構。"""
    status: str = Field(default="ok", description="系統狀態 (ok/degraded/error)")
    timestamp: datetime = Field(description="當前伺服器時間 (UTC)")
    worker_status: Optional[dict[str, Any]] = Field(default=None, description="背景 Worker 運作狀態")
    active_contact_id: Optional[int] = Field(default=None, description="目前活躍聯絡人 ID")
