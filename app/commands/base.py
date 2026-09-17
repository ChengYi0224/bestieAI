"""
base.py — Command Bus 基礎類別與介面定義。
"""
from dataclasses import dataclass, field
from typing import Any, Optional, Dict


@dataclass
class CommandResult:
    """
    命令執行結果：
    - success: 是否執行成功
    - message: 人類可讀訊息（供 IG 私訊或文字介面顯示）
    - data: 結構化資料（供 REST API / iOS App 端讀取）
    - action_type: 後續非同步動作識別碼（例如 TRACK_REQUEST, SYNC_REQUEST）
    - metadata: 額外延伸資訊
    """
    success: bool = True
    message: str = ""
    data: Optional[Any] = None
    action_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "action_type": self.action_type,
            "metadata": self.metadata,
        }


@dataclass
class BaseCommand:
    """領域命令的基礎抽象類別。"""
    pass


class CommandHandler:
    """命令處理器基礎介面。"""
    def handle(self, command: BaseCommand) -> CommandResult:
        raise NotImplementedError
