"""
bus.py — Command Bus 核心派發中介。

PIPELINE (L2):
  CommandBus.dispatch(command: BaseCommand)
       │
       ▼
  查表 handler = self._handlers.get(type(command))
       │
       ├─ (查無 Handler) ──► return CommandResult(success=False, "未找到指令處理器")
       │
       ▼ (查得 Handler)
  執行 handler(command)
       │
       ├─ (執行成功) ──────► return CommandResult(success=True, data=..., message=...)
       │
       └─ (拋出 Exception) ─► return CommandResult(success=False, "指令執行失敗: ...")
"""
import logging
from typing import Dict, Type, Union, Callable
from app.commands.base import BaseCommand, CommandResult, CommandHandler

logger = logging.getLogger("bestieAI.commands.bus")

HandlerType = Union[CommandHandler, Callable[[BaseCommand], CommandResult]]


class CommandBus:
    """Command Bus 指令派發中心。"""

    def __init__(self):
        self._handlers: Dict[Type[BaseCommand], HandlerType] = {}

    def register(self, command_cls: Type[BaseCommand], handler: HandlerType) -> None:
        """註冊命令類型及其對應 Handler。"""
        self._handlers[command_cls] = handler
        logger.debug(f"已註冊命令處理器：{command_cls.__name__} -> {handler}")

    def dispatch(self, command: BaseCommand) -> CommandResult:
        """派發命令至註冊的 Handler 執行並返回 CommandResult。"""
        cmd_cls = type(command)
        handler = self._handlers.get(cmd_cls)

        if not handler:
            err_msg = f"未找到指令「{cmd_cls.__name__}」的註冊處理器。"
            logger.error(err_msg)
            return CommandResult(success=False, message=err_msg)

        try:
            if isinstance(handler, CommandHandler):
                return handler.handle(command)
            return handler(command)
        except Exception as e:
            logger.exception(f"執行指令 {cmd_cls.__name__} 發生異常: {e}")
            return CommandResult(success=False, message=f"指令執行失敗: {e}")
