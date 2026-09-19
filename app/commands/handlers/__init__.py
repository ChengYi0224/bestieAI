"""
handlers/__init__.py — 組合所有領域 Handler，對外提供 CommandService Facade。

CommandService 是向後相容的薄層 Facade：
  - 聚合 ContactHandler / MemoryHandler / ChatHandler / HelpHandler / FollowerHandler
  - 將所有 handle_* 方法代理至對應的子 Handler
  - 現有呼叫 from app.commands.handlers import CommandService 完全不受影響
"""
from typing import Any, Optional, Callable

from app.services.memory_service import MemoryManager
from app.services.llm_service import LLMClient
from app.commands.handlers.help import HelpHandler
from app.commands.handlers.contact import ContactHandler
from app.commands.handlers.memory import MemoryHandler
from app.commands.handlers.chat import ChatHandler
from app.commands.handlers.follower import FollowerHandler
from app.commands.handlers.export import ExportHandler
from app.commands.handlers.auth import AuthHandler
from app.commands.commands import (
    HelpCommand, TrackCommand, TrackFullCommand, SelectCommand,
    SelectChoiceCommand, NicknameCommand, MeCommand, StatusCommand,
    ListContactsCommand, CardCommand, RefreshSummaryCommand,
    SummarizeHistoryCommand, SyncCommand, UntrackCommand,
    RebuildVectorsCommand, ChatCommand, FollowerSnapshotCommand,
    CheckUnfollowersCommand, ExportCommand,
    LoginCommand, TwoFactorCommand,
)

# 重新匯出 Command 類別（讓現有 import 不需改動）
__all__ = [
    "CommandService",
    "create_default_command_bus",
    "ExportHandler",
    "AuthHandler",
    "HelpCommand", "TrackCommand", "TrackFullCommand", "SelectCommand",
    "SelectChoiceCommand", "NicknameCommand", "MeCommand", "StatusCommand",
    "ListContactsCommand", "CardCommand", "RefreshSummaryCommand",
    "SummarizeHistoryCommand", "SyncCommand", "UntrackCommand",
    "RebuildVectorsCommand", "ChatCommand", "FollowerSnapshotCommand",
    "CheckUnfollowersCommand", "ExportCommand",
    "LoginCommand", "TwoFactorCommand",
]


from app.storage.repositories import (
    BotStateRepository,
    ContactRepository,
    MessageRepository,
    UserRepository,
)


class CommandService:
    """
    向後相容 Facade：聚合所有領域 Handler。
    新增功能請直接使用對應的子 Handler，CommandService 只做代理。
    """

    def __init__(
        self,
        memory_manager: Optional[MemoryManager] = None,
        llm_client: Optional[LLMClient] = None,
        db_path: Optional[Any] = None,
        sync_callback: Optional[Callable[[str], Any]] = None,
        model: Optional[str] = None,
        self_extract_model: Optional[str] = None,
        contact_repo: Optional[ContactRepository] = None,
        message_repo: Optional[MessageRepository] = None,
        bot_state_repo: Optional[BotStateRepository] = None,
        user_repo: Optional[UserRepository] = None,
    ):
        # 根組合點：在此建立或接收 Repositories，以 DI 注入子 Handler
        mm = memory_manager or MemoryManager()
        lc = llm_client or LLMClient()
        cr = contact_repo or ContactRepository(db_path)
        mr = message_repo or MessageRepository(db_path)
        bsr = bot_state_repo or BotStateRepository(db_path)
        ur = user_repo or UserRepository(db_path)

        self._help = HelpHandler()
        self._contact = ContactHandler(contact_repo=cr, bot_state_repo=bsr)
        self._memory = MemoryHandler(memory_manager=mm, contact_repo=cr)
        self._chat = ChatHandler(
            memory_manager=mm,
            llm_client=lc,
            contact_repo=cr,
            bot_state_repo=bsr,
            sync_callback=sync_callback,
            model=model,
            self_extract_model=self_extract_model,
        )
        self._follower = FollowerHandler()
        self._export = ExportHandler(
            contact_repo=cr,
            message_repo=mr,
            sync_callback=sync_callback,
        )
        self._auth = AuthHandler(user_repo=ur)

        # 向後相容屬性
        self.memory_manager = mm
        self.llm_client = lc
        self.db_path = db_path
        self.contact_repo = cr
        self.message_repo = mr
        self.bot_state_repo = bsr


    # ── Help ──────────────────────────────────────────────────────────────────
    def handle_help(self, cmd: HelpCommand):
        return self._help.handle(cmd)

    # ── Contact ───────────────────────────────────────────────────────────────
    def handle_track(self, cmd: TrackCommand):
        return self._contact.handle_track(cmd)

    def handle_track_full(self, cmd: TrackFullCommand):
        return self._contact.handle_track_full(cmd)

    def handle_select(self, cmd: SelectCommand):
        return self._contact.handle_select(cmd)

    def handle_select_choice(self, cmd: SelectChoiceCommand):
        return self._contact.handle_select_choice(cmd)

    def handle_nickname(self, cmd: NicknameCommand):
        return self._contact.handle_nickname(cmd)

    def handle_untrack(self, cmd: UntrackCommand):
        return self._contact.handle_untrack(cmd)

    def handle_list(self, cmd: ListContactsCommand):
        return self._contact.handle_list(cmd)

    def handle_status(self, cmd: StatusCommand):
        return self._contact.handle_status(cmd)

    # ── Memory ────────────────────────────────────────────────────────────────
    def handle_me(self, cmd: MeCommand):
        return self._memory.handle_me(cmd)

    def handle_card(self, cmd: CardCommand):
        return self._memory.handle_card(cmd)

    def handle_refresh_summary(self, cmd: RefreshSummaryCommand):
        return self._memory.handle_refresh_summary(cmd)

    def handle_summarize_history(self, cmd: SummarizeHistoryCommand):
        return self._memory.handle_summarize_history(cmd)

    def handle_sync(self, cmd: SyncCommand):
        return self._memory.handle_sync(cmd)

    def handle_rebuild_vectors(self, cmd: RebuildVectorsCommand):
        return self._memory.handle_rebuild_vectors(cmd)

    # ── Chat ──────────────────────────────────────────────────────────────────
    def handle_chat(self, cmd: ChatCommand):
        return self._chat.handle_chat(cmd)

    # ── Export ────────────────────────────────────────────────────────────────
    def handle_export(self, cmd: ExportCommand):
        return self._export.handle_export(cmd)

    # ── Auth ──────────────────────────────────────────────────────────────────
    def handle_login(self, cmd: LoginCommand):
        return self._auth.handle_login(cmd)

    def handle_two_factor(self, cmd: TwoFactorCommand):
        return self._auth.handle_two_factor(cmd)

    # ── Follower ──────────────────────────────────────────────────────────────
    def handle_follower_snapshot(self, cmd: FollowerSnapshotCommand):
        return self._follower.handle_follower_snapshot(cmd)

    def handle_check_unfollowers(self, cmd: CheckUnfollowersCommand):
        return self._follower.handle_check_unfollowers(cmd)


def create_default_command_bus(service: "CommandService"):
    """便利函式：建立 CommandBus 並註冊所有標準命令。"""
    from app.commands.bus import CommandBus
    bus = CommandBus()
    bus.register(HelpCommand, service.handle_help)
    bus.register(TrackCommand, service.handle_track)
    bus.register(TrackFullCommand, service.handle_track_full)
    bus.register(SelectCommand, service.handle_select)
    bus.register(SelectChoiceCommand, service.handle_select_choice)
    bus.register(NicknameCommand, service.handle_nickname)
    bus.register(MeCommand, service.handle_me)
    bus.register(StatusCommand, service.handle_status)
    bus.register(ListContactsCommand, service.handle_list)
    bus.register(CardCommand, service.handle_card)
    bus.register(RefreshSummaryCommand, service.handle_refresh_summary)
    bus.register(SummarizeHistoryCommand, service.handle_summarize_history)
    bus.register(SyncCommand, service.handle_sync)
    bus.register(UntrackCommand, service.handle_untrack)
    bus.register(RebuildVectorsCommand, service.handle_rebuild_vectors)
    bus.register(ChatCommand, service.handle_chat)
    bus.register(ExportCommand, service.handle_export)
    bus.register(LoginCommand, service.handle_login)
    bus.register(TwoFactorCommand, service.handle_two_factor)
    bus.register(FollowerSnapshotCommand, service.handle_follower_snapshot)
    bus.register(CheckUnfollowersCommand, service.handle_check_unfollowers)
    return bus
