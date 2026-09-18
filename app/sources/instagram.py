"""
instagram.py — Instagram 來源適配器（InstagramAdapter）。

PIPELINE (L2):
  InstagramAdapter.fetch_messages(target=username, amount)
       │
       ▼
  ig_client.get_thread_by_username(username)
       │
       ├─ (查無對話串) ──► raise ValueError
       │
       ▼ (取得 thread_id)
  ig_client.get_thread_messages(thread_id, amount)
       │
       ▼ [DirectMessage 清單]
  逐筆轉換為 NormalizedMessage:
       ├─ external_id   ← str(m.id)
       ├─ sender        ← 'me' if m.user_id == self_id else 'them'
       ├─ content       ← clean_text(m.text)
       ├─ sent_at       ← m.timestamp.isoformat()
       ├─ source_type   ← 'instagram'
       └─ extras        ← {'thread_id': ..., 'user_id': ...}
       │
       ▼
  [NormalizedMessage 清單]
"""
import logging
from typing import Any, List, Optional
from app.sources.base import BaseSourceAdapter, NormalizedMessage

logger = logging.getLogger("bestieAI.sources.instagram")


class InstagramAdapter(BaseSourceAdapter):
    """Instagram 私訊資料來源適配器。"""

    source_type: str = "instagram"

    def __init__(self, ig_client: Any):
        self.ig_client = ig_client

    def get_self_id(self) -> str:
        """取得主帳號的 Instagram PK。"""
        if hasattr(self.ig_client, "client") and hasattr(self.ig_client.client, "user_id"):
            return str(self.ig_client.client.user_id)
        return ""

    @staticmethod
    def _clean_text(raw_text: Optional[str]) -> str:
        from app.utils import clean_message_text
        return clean_message_text(raw_text, default="[圖片/貼圖/非文字訊息]")

    def fetch_messages(
        self,
        target: str,
        amount: int = 0,
        progress_callback: Optional[Any] = None,
        stop_item_ids: Optional[Any] = None,
    ) -> List[NormalizedMessage]:
        thread = self.ig_client.get_thread_by_username(target)
        if not thread:
            raise ValueError(f"找不到與 {target} 的私訊對話串")

        thread_id = str(thread.id)
        raw_messages = self.ig_client.get_thread_messages(
            thread_id=thread_id,
            amount=amount,
            progress_callback=progress_callback,
            stop_item_ids=stop_item_ids,
        )

        me_pk = self.get_self_id()
        normalized_list: List[NormalizedMessage] = []

        for m in raw_messages:
            sender = "me" if str(m.user_id) == me_pk else "them"
            content = self._clean_text(m.text)
            media_type = "text" if m.text and m.text.strip() else "media"

            sent_at = (
                m.timestamp.isoformat()
                if hasattr(m.timestamp, "isoformat")
                else str(m.timestamp)
            )

            msg = NormalizedMessage(
                external_id=str(m.id),
                sender=sender,
                content=content,
                sent_at=sent_at,
                source_type=self.source_type,
                raw_media_type=media_type,
                extras={
                    "thread_id": thread_id,
                    "user_id": str(m.user_id),
                },
            )
            normalized_list.append(msg)

        return normalized_list


# 自我註冊至 SourceAdapterFactory
from app.sources.factory import SourceAdapterFactory  # noqa: E402
SourceAdapterFactory.register("instagram", InstagramAdapter)
