"""
commands.py — 所有領域命令（Command）的 Dataclass 定義（純 DTO 層）。

此檔案只定義資料結構，不含任何業務邏輯。
每個 Command 對應一個可被 CommandBus 派發的操作意圖。
"""
from dataclasses import dataclass
from typing import Optional
from app.core.config import settings
from app.commands.base import BaseCommand


# ─── 使用說明 ───────────────────────────────────────────
@dataclass
class HelpCommand(BaseCommand):
    show_all: bool = False

# ─── 聯絡人管理 ──────────────────────────────────────────
@dataclass
class TrackCommand(BaseCommand):
    target: str

@dataclass
class TrackFullCommand(BaseCommand):
    target: str
    max_amount: int = settings.TRACK_FULL_DEFAULT_LIMIT

@dataclass
class SelectCommand(BaseCommand):
    query: str

@dataclass
class SelectChoiceCommand(BaseCommand):
    choice_index: int  # 0-indexed

@dataclass
class NicknameCommand(BaseCommand):
    nickname: str
    target: Optional[str] = None

@dataclass
class UntrackCommand(BaseCommand):
    target: str

@dataclass
class ListContactsCommand(BaseCommand):
    pass

@dataclass
class StatusCommand(BaseCommand):
    pass

# ─── 記憶庫與摘要 ─────────────────────────────────────────
@dataclass
class MeCommand(BaseCommand):
    content: str

@dataclass
class CardCommand(BaseCommand):
    target: Optional[str] = None
    is_full: bool = False

@dataclass
class RefreshSummaryCommand(BaseCommand):
    target: str

@dataclass
class SummarizeHistoryCommand(BaseCommand):
    target: str

@dataclass
class SyncCommand(BaseCommand):
    target: str

@dataclass
class RebuildVectorsCommand(BaseCommand):
    target: str

@dataclass
class ExportCommand(BaseCommand):
    limit: int = 20
    immediate: bool = False
    target: Optional[str] = None

# ─── AI 對話 ─────────────────────────────────────────────
@dataclass
class ChatCommand(BaseCommand):
    text: str

# ─── Follower 監控（預留）────────────────────────────────
@dataclass
class FollowerSnapshotCommand(BaseCommand):
    pass

@dataclass
class CheckUnfollowersCommand(BaseCommand):
    pass
