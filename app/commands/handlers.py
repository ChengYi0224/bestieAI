"""
handlers.py — 向後相容轉發層。

此檔案已重構：業務邏輯已移至 app/commands/handlers/ 子目錄。
此檔案僅作為 re-export 橋接，確保舊有 import 不需修改。

新增功能請直接使用對應的子模組：
  - app/commands/handlers/contact.py   聯絡人管理
  - app/commands/handlers/memory.py    記憶庫與摘要
  - app/commands/handlers/chat.py      AI 聊天
  - app/commands/handlers/help.py      說明指令
  - app/commands/handlers/follower.py  Follower 監控（預留）
"""
# 所有 Command dataclass（從 commands.py 轉發）
from app.commands.commands import (
    HelpCommand,
    TrackCommand,
    TrackFullCommand,
    SelectCommand,
    SelectChoiceCommand,
    NicknameCommand,
    MeCommand,
    StatusCommand,
    ListContactsCommand,
    CardCommand,
    RefreshSummaryCommand,
    SummarizeHistoryCommand,
    SyncCommand,
    UntrackCommand,
    RebuildVectorsCommand,
    ChatCommand,
    FollowerSnapshotCommand,
    CheckUnfollowersCommand,
)

# CommandService Facade 與工廠函式（從 handlers/ 子目錄轉發）
from app.commands.handlers import CommandService, create_default_command_bus

__all__ = [
    "CommandService",
    "create_default_command_bus",
    "HelpCommand",
    "TrackCommand",
    "TrackFullCommand",
    "SelectCommand",
    "SelectChoiceCommand",
    "NicknameCommand",
    "MeCommand",
    "StatusCommand",
    "ListContactsCommand",
    "CardCommand",
    "RefreshSummaryCommand",
    "SummarizeHistoryCommand",
    "SyncCommand",
    "UntrackCommand",
    "RebuildVectorsCommand",
    "ChatCommand",
    "FollowerSnapshotCommand",
    "CheckUnfollowersCommand",
]
