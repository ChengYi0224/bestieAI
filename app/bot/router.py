"""
router.py — 文字指令適配器（CommandRouter）。

PIPELINE (L0 → L1):
  CommandRouter.handle_message_structured(raw_text)
       │
       ▼
  parse_text_to_command(raw_text)
       │  委託 CommandParserRegistry（查表，不含 if-else）
       │  ├─ "$" 開頭 → ChatCommand（強制 AI 聊天）
       │  ├─ 純數字 + pending → SelectChoiceCommand
       │  ├─ 查表找到 Parser → BaseCommand
       │  └─ fallback → ChatCommand
       │
       ▼
  CommandBus.dispatch(cmd) → CommandResult
       │
       ▼
  CommandResult(success, message, data, action_type)

職責：
- 解析來自 Instagram 私訊（或 CLI）的自然語言/文字指令。
- 委託 CommandParserRegistry 查表解析，自身不含任何 if-else 分支。
- 將 CommandResult 格式化為給 IG 私訊傳送的訊息字串（向後相容）。
"""
from typing import Optional, Any

from app.commands.base import BaseCommand, CommandResult
from app.commands.bus import CommandBus
from app.commands.commands import HelpCommand, ChatCommand
from app.commands.handlers import CommandService, create_default_command_bus
from app.commands.parsers import CommandParserRegistry
from app.storage.db import get_pending_selection
from app.services.memory_service import MemoryManager
from app.services.llm_service import LLMClient


class CommandRouter:
    """文字指令適配器：解析文字為 Command 物件並調用 CommandBus。"""

    @classmethod
    def get_help_text(cls, show_all: bool = False) -> str:
        service = CommandService()
        return service.handle_help(HelpCommand(show_all=show_all)).message

    @property
    def HELP_TEXT(self) -> str:
        return self.get_help_text(show_all=False)

    def __init__(
        self,
        memory_manager: Optional[MemoryManager] = None,
        llm_client: Optional[LLMClient] = None,
        db_path: Optional[Any] = None,
        command_bus: Optional[CommandBus] = None,
    ):
        # 根組合點：只在 Router 層建立依賴，往下傳入 CommandService
        mm = memory_manager or MemoryManager()
        lc = llm_client or LLMClient()
        self.db_path = db_path

        self.service = CommandService(
            memory_manager=mm,
            llm_client=lc,
            db_path=self.db_path,
        )
        self.bus = command_bus or create_default_command_bus(self.service)

    def parse_text_to_command(self, raw_text: str) -> BaseCommand:
        """
        將使用者傳入的字串解析為對應領域的 Command 物件。
        委託 CommandParserRegistry 查表，自身不含 if-else。
        純數字 + 有 pending_selection 時，優先解析為 SelectChoiceCommand。
        """
        text = raw_text.strip()

        # 純數字優先確認 pending selection
        if text.isdigit():
            pending_ids = get_pending_selection(db_path=self.db_path)
            if pending_ids:
                from app.commands.commands import SelectChoiceCommand
                return SelectChoiceCommand(choice_index=int(text) - 1)

        return CommandParserRegistry.parse(text, db_path=self.db_path)

    def handle_message_structured(self, raw_text: str) -> CommandResult:
        """主入口：回傳具備結構化資料與文字的 CommandResult。"""
        text = raw_text.strip()
        if not text:
            return CommandResult(success=False, message="收到空白訊息。")

        cmd = self.parse_text_to_command(raw_text)
        return self.bus.dispatch(cmd)

    def handle_message(self, raw_text: str) -> str:
        """向後相容主入口：接收文字指令並返回供 IG 私訊傳送的字串。"""
        res = self.handle_message_structured(raw_text)
        return res.message
