"""
repositories — 資料存取庫模式 (Repository Pattern) 模組。

依存取對象分類：
- contacts: 聯絡人與人物設定 (ContactRepository)
- messages: 歷史私訊紀錄 (MessageRepository)
- bot_state: 系統狀態與對話歷史 (BotStateRepository)
- events: 事件記憶快取 (EventRepository)
- base: 基礎類別與連線裝飾器 (BaseRepository, with_connection)
"""
from app.storage.repositories.base import BaseRepository, with_connection
from app.storage.repositories.contacts import ContactRepository
from app.storage.repositories.messages import MessageRepository
from app.storage.repositories.bot_state import BotStateRepository
from app.storage.repositories.events import EventRepository
from app.storage.repositories.users import UserRepository

__all__ = [
    "BaseRepository",
    "with_connection",
    "ContactRepository",
    "MessageRepository",
    "BotStateRepository",
    "EventRepository",
    "UserRepository",
]
