"""
parsers.py — 指令解析器 Registry。

PIPELINE (L2):
  CommandParserRegistry.parse(raw_text, db_path)
       │
       ├─ 文字以 "$" 開頭 ──────────────────────► ChatCommand(text=去掉"$"後的文字)
       │
       ├─ 純數字 + 有 pending_selection ────────► SelectChoiceCommand(choice_index=N)
       │
       ├─ 查 _registry.get(首個單詞)
       │     ├─ 找到 Parser ─────────────────────► parser.parse(parts) → BaseCommand
       │     └─ 找不到 ──────────────────────────► ChatCommand(text=原始文字)（fallback）
       │
       └─ [BaseCommand 實例]

新增指令只需實作 CommandParser 並在底部呼叫：
  CommandParserRegistry.register(("aliases",), YourParser())
  parsers.py 本身不需修改。
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple

from app.commands.base import BaseCommand
from app.commands.commands import (
    HelpCommand, TrackCommand, TrackFullCommand, SelectCommand,
    SelectChoiceCommand, NicknameCommand, MeCommand, StatusCommand,
    ListContactsCommand, CardCommand, RefreshSummaryCommand,
    SummarizeHistoryCommand, SyncCommand, UntrackCommand,
    RebuildVectorsCommand, ChatCommand, FollowerSnapshotCommand,
    CheckUnfollowersCommand,
)
from app.core.config import settings


# ─── 抽象介面 ────────────────────────────────────────────────────────────────

class CommandParser(ABC):
    """指令解析器抽象介面。"""

    @property
    @abstractmethod
    def aliases(self) -> Tuple[str, ...]:
        """此 Parser 負責的指令關鍵字清單。"""
        ...

    @abstractmethod
    def parse(self, parts: List[str], db_path: Optional[Any] = None) -> BaseCommand:
        """將 parts（已 split 的字串）解析為 BaseCommand。"""
        ...


# ─── Registry ────────────────────────────────────────────────────────────────

class CommandParserRegistry:
    """CommandParser 查表 Registry。"""

    _registry: Dict[str, CommandParser] = {}

    @classmethod
    def register(cls, parser: CommandParser) -> None:
        for alias in parser.aliases:
            cls._registry[alias.lower()] = parser

    @classmethod
    def parse(cls, raw_text: str, db_path: Optional[Any] = None) -> BaseCommand:
        text = raw_text.strip()
        if not text:
            return ChatCommand(text="")

        # 1. "$" 開頭 → 強制進入 AI 聊天模式
        if text.startswith("$"):
            return ChatCommand(text=text[1:].strip())

        parts = text.split()
        cmd_key = parts[0].lower()

        # 2. 純數字 → SelectChoiceCommand（由外部傳入 pending check）
        if text.isdigit():
            return SelectChoiceCommand(choice_index=int(text) - 1)

        # 3. 查表
        parser = cls._registry.get(cmd_key)
        if parser:
            return parser.parse(parts, db_path=db_path)

        # 4. fallback：當作 AI 聊天
        return ChatCommand(text=text)


# ─── 各 Parser 實作 ──────────────────────────────────────────────────────────

class _HelpParser(CommandParser):
    @property
    def aliases(self): return ("help", "h", "?", "指令")

    def parse(self, parts, db_path=None):
        show_all = len(parts) >= 2 and parts[1].lower() in ("all", "full", "全部", "詳細")
        return HelpCommand(show_all=show_all)


class _TrackParser(CommandParser):
    @property
    def aliases(self): return ("track", "t")

    def parse(self, parts, db_path=None):
        return TrackCommand(target=parts[1] if len(parts) >= 2 else "")


class _TrackFullParser(CommandParser):
    @property
    def aliases(self): return ("track_full", "tf")

    def parse(self, parts, db_path=None):
        target = None
        max_amount = settings.TRACK_FULL_DEFAULT_LIMIT
        if len(parts) >= 2:
            if parts[1].isdigit():
                max_amount = int(parts[1])
            else:
                target = parts[1]
                if len(parts) >= 3 and parts[2].isdigit():
                    max_amount = int(parts[2])
        if not target:
            from app.storage.db import get_active_contact
            active = get_active_contact(db_path=db_path)
            target = active["ig_account_id"] if active else ""
        return TrackFullCommand(target=target or "", max_amount=max_amount)


class _SelectParser(CommandParser):
    @property
    def aliases(self): return ("select", "s")

    def parse(self, parts, db_path=None):
        return SelectCommand(query=parts[1] if len(parts) >= 2 else "")


class _NicknameParser(CommandParser):
    @property
    def aliases(self): return ("nickname", "nick", "n", "暱稱")

    def parse(self, parts, db_path=None):
        nick = parts[1] if len(parts) >= 2 else ""
        target_acc = parts[2] if len(parts) >= 3 else None
        return NicknameCommand(nickname=nick, target=target_acc)


class _MeParser(CommandParser):
    @property
    def aliases(self): return ("me", "m", "我")

    def parse(self, parts, db_path=None):
        return MeCommand(content=" ".join(parts[1:]) if len(parts) >= 2 else "")


class _StatusParser(CommandParser):
    @property
    def aliases(self): return ("status", "query", "st", "q", "進度", "狀態")

    def parse(self, parts, db_path=None):
        return StatusCommand()


class _ListParser(CommandParser):
    @property
    def aliases(self): return ("list", "ls", "l")

    def parse(self, parts, db_path=None):
        return ListContactsCommand()


class _CardParser(CommandParser):
    @property
    def aliases(self): return ("card", "summary", "c", "摘要", "摘要卡")

    def parse(self, parts, db_path=None):
        is_full = False
        clean_parts = parts[1:]
        if clean_parts and clean_parts[0].lower() in ("full", "-f", "--full", "全景", "長文"):
            is_full = True
            clean_parts = clean_parts[1:]
        target = clean_parts[0] if clean_parts else None
        return CardCommand(target=target, is_full=is_full)


class _RefreshSummaryParser(CommandParser):
    @property
    def aliases(self): return ("refresh_summary", "rs", "ref")

    def parse(self, parts, db_path=None):
        target = _resolve_active(parts, db_path=db_path)
        return RefreshSummaryCommand(target=target or "")


class _SummarizeHistoryParser(CommandParser):
    @property
    def aliases(self): return ("summarize_history", "sh", "sum")

    def parse(self, parts, db_path=None):
        target = _resolve_active(parts, db_path=db_path)
        return SummarizeHistoryCommand(target=target or "")


class _SyncParser(CommandParser):
    @property
    def aliases(self): return ("sync", "sy")

    def parse(self, parts, db_path=None):
        target = _resolve_active(parts, db_path=db_path)
        return SyncCommand(target=target or "")


class _UntrackParser(CommandParser):
    @property
    def aliases(self): return ("untrack", "ut")

    def parse(self, parts, db_path=None):
        return UntrackCommand(target=parts[1] if len(parts) >= 2 else "")


class _RebuildVectorsParser(CommandParser):
    @property
    def aliases(self): return ("rebuild_vectors", "rv", "rb")

    def parse(self, parts, db_path=None):
        target = _resolve_active(parts, db_path=db_path)
        return RebuildVectorsCommand(target=target or "")


# ─── 工具函式 ─────────────────────────────────────────────────────────────────

def _resolve_active(parts: List[str], index: int = 1, db_path: Optional[Any] = None) -> Optional[str]:
    """若 parts[index] 存在且非數字則直接回傳；否則查 active contact。"""
    if len(parts) > index and not parts[index].isdigit():
        return parts[index]
    from app.storage.db import get_active_contact
    active = get_active_contact(db_path=db_path)
    return active["ig_account_id"] if active else None


# ─── 自動註冊所有 Parser ──────────────────────────────────────────────────────

for _parser in [
    _HelpParser(), _TrackParser(), _TrackFullParser(), _SelectParser(),
    _NicknameParser(), _MeParser(), _StatusParser(), _ListParser(),
    _CardParser(), _RefreshSummaryParser(), _SummarizeHistoryParser(),
    _SyncParser(), _UntrackParser(), _RebuildVectorsParser(),
]:
    CommandParserRegistry.register(_parser)
