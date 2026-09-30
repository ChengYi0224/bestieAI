"""
base.py — Command Bus 基礎類別與介面定義。
"""
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional, Dict


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
    """
    領域命令的基礎抽象類別。

    user_id: 發出指令的使用者（租戶）。由 Router 依發送者身分填入；requires_user 為 True 的指令
    在 user_id 為 None 時會被 CommandBus 拒絕執行。
    """
    user_id: Optional[int] = field(default=None, kw_only=True)
    requires_user: ClassVar[bool] = True


class CommandHandler:
    """命令處理器基礎介面。"""
    def handle(self, command: BaseCommand) -> CommandResult:
        raise NotImplementedError


# sync_callback 的回傳值：>= 0 為新增則數，SYNC_FAILED 表示同步失敗（已 fallback 使用本地紀錄）
SYNC_FAILED = -1


def need_user(cmd: "BaseCommand") -> int:
    """取得指令發送者的 user_id；缺少時拋出（正常流程已由 CommandBus 在派發前擋下）。"""
    if cmd.user_id is None:
        raise ValueError(f"{type(cmd).__name__} 缺少 user_id，無法判定租戶")
    return cmd.user_id
