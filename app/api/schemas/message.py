"""message.py — 訊息與事件相關 Pydantic Schema 定義。"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    """歷史私訊回應模型。"""
    id: int
    contact_id: int
    ig_item_id: str
    sender: str
    content: str
    sent_at: datetime
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "extra": "ignore"}


class MessageListResponse(BaseModel):
    """歷史私訊清單回應模型（分頁）。"""
    total: int = Field(description="總訊息數")
    limit: int = Field(description="每頁筆數")
    offset: int = Field(description="位移筆數")
    items: list[MessageResponse] = Field(description="訊息紀錄清單")


class EventResponse(BaseModel):
    """記憶事件回應模型。"""
    id: int
    contact_id: int
    event_id: Optional[str] = None
    content: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    message_count: int = 1
    status: str = "raw"
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "extra": "ignore"}


class EventListResponse(BaseModel):
    """記憶事件清單回應模型。"""
    total: int = Field(description="總事件數")
    items: list[EventResponse] = Field(description="記憶事件清單")
