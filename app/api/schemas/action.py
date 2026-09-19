"""action.py — 聯絡人追蹤、事件提煉與 AI 對話之 Pydantic Request / Response 模型。"""
from typing import Optional
from pydantic import BaseModel, Field


class TrackContactRequest(BaseModel):
    """追蹤聯絡人並匯入歷史對話請求模型。"""
    ig_account_id: str = Field(description="目標 Instagram 帳號")
    limit: Optional[int] = Field(default=1000, ge=1, le=5000, description="匯入歷史私訊上限筆數")


class TrackContactResponse(BaseModel):
    """追蹤聯絡人回應模型。"""
    status: str = Field(description="執行狀態（例如 success, queued）")
    message: str = Field(description="狀態描述訊息")
    contact_id: Optional[int] = Field(default=None, description="聯絡人系統 ID")
    inserted_messages: Optional[int] = Field(default=0, description="成功匯入之私訊則數")


class ExtractContactResponse(BaseModel):
    """手動觸發事件萃取與人物摘要更新回應模型。"""
    status: str = Field(description="執行狀態")
    contact_id: int = Field(description="聯絡人系統 ID")
    events_extracted: int = Field(description="本次提煉之事件記憶數量")
    summary_updated: bool = Field(description="關係摘要卡是否已更新")
    summary_card: Optional[str] = Field(default=None, description="更新後之關係摘要卡內容")


class ChatRequest(BaseModel):
    """與 AI 陪聊討論對象之對話請求模型。"""
    message: str = Field(min_length=1, description="使用者對話文字")
    contact_id: Optional[int] = Field(default=None, description="指定討論之聯絡人 ID（若未提供則使用當前活躍聯絡人）")


class ChatResponse(BaseModel):
    """AI 陪聊回應模型。"""
    reply: str = Field(description="AI 回覆內容")
    contact_id: Optional[int] = Field(default=None, description="對應之聯絡人 ID")
