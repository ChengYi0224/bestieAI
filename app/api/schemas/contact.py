"""contact.py — 聯絡人相關 Pydantic Schema 定義。"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ContactResponse(BaseModel):
    """聯絡人資訊回應模型。"""
    id: int
    ig_account_id: str
    display_name: Optional[str] = None
    nickname: Optional[str] = None
    relationship_note: Optional[str] = None
    status: str
    summary_card: Optional[str] = None
    summary_updated_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "extra": "ignore"}


class ContactUpdateRequest(BaseModel):
    """聯絡人更新請求模型。"""
    nickname: Optional[str] = Field(default=None, description="聯絡人暱稱")
    relationship_note: Optional[str] = Field(default=None, description="人物關係備註")


class ContactListResponse(BaseModel):
    """聯絡人清單回應模型。"""
    total: int = Field(description="聯絡人總數")
    items: list[ContactResponse] = Field(description="聯絡人清單項目")
