"""
base.py — 資料來源統一介面與標準化訊息模型。

PIPELINE (L2):
  [外部各平台原始訊息]
           │
           ▼
  Adapter.fetch_messages()
           │
           ▼
  NormalizedMessage 實例化
           │
     ┌─────┴─────┐
  驗證通過    驗證失敗 (external_id 為空 或 sender 非 me/them)
     │           │
     ▼           ▼
  [標準訊息]   raise ValueError
     │
     ▼
  IngestionPipeline
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NormalizedMessage:
    """
    標準化訊息資料結構：
    - external_id: 來源平台唯一訊息 ID
    - sender: 'me' | 'them'
    - content: 純文字內容
    - sent_at: ISO 8601 時間字串
    - source_type: 來源類別代碼 (e.g. 'instagram', 'file_import', 'line')
    - raw_media_type: 原始媒體型態 ('text', 'image', 'sticker', 等)
    - extras: 平台特有或延伸資訊（Open-Closed 逃生門）
    """
    external_id: str
    sender: str
    content: str
    sent_at: str
    source_type: str
    raw_media_type: str = "text"
    extras: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.external_id or not str(self.external_id).strip():
            raise ValueError("NormalizedMessage.external_id 不得為空。")

        if self.sender not in ("me", "them"):
            raise ValueError(f"NormalizedMessage.sender 必須為 'me' 或 'them'，得到: {self.sender!r}")

        if not self.sent_at or not str(self.sent_at).strip():
            raise ValueError("NormalizedMessage.sent_at 不得為空。")

        # 檢驗時間字串可被基本解析
        from app.utils import parse_time_str
        if not parse_time_str(self.sent_at):
            raise ValueError(f"NormalizedMessage.sent_at 非有效時間格式: {self.sent_at!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "external_id": self.external_id,
            "sender": self.sender,
            "content": self.content,
            "sent_at": self.sent_at,
            "source_type": self.source_type,
            "raw_media_type": self.raw_media_type,
            "extras": self.extras,
        }


class BaseSourceAdapter(ABC):
    """資料來源適配器抽象基底類別。"""

    source_type: str = "base"

    @abstractmethod
    def fetch_messages(
        self,
        target: str,
        amount: int = 0,
        progress_callback: Optional[Any] = None,
        stop_item_ids: Optional[Any] = None,
    ) -> List[NormalizedMessage]:
        """從指定來源抓取訊息並轉換為 NormalizedMessage 列表。"""
        pass

    @abstractmethod
    def get_self_id(self) -> str:
        """取得自身使用者識別代碼（用於判斷 me / them）。"""
        pass
