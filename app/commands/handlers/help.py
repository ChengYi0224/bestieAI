"""
help.py — 說明指令 Handler。
"""
from app.commands.base import BaseCommand, CommandResult
from app.commands.commands import HelpCommand
from app.core.config import settings


class HelpHandler:
    """處理 HelpCommand，回傳指令說明文字。"""

    def handle(self, cmd: HelpCommand) -> CommandResult:
        if not cmd.show_all:
            msg = (
                "【IG AI 陪聊機器人 指令清單】\n"
                "• track (t) <IG_ID>：首次追蹤對象並匯入近況\n"
                "• select (s) <關鍵字>：切換目前討論對象\n"
                "• card (c) [IG_ID]：檢視日常摘要卡（加 full 查長文）\n"
                "• me (m) <內容>：讓 AI 記住你的喜好與生活近況\n"
                "• status (st/q)：檢視目前對象與背景進度\n"
                "• 直接傳送訊息：與 AI 討論相處回覆策略\n\n"
                "💡 輸入「help all」(或 h all) 可查看全量進階指令（同步、全量抓取、重建等）。"
            )
        else:
            msg = (
                "【IG AI 陪聊機器人 指令清單 - 全量模式】\n"
                "--- 常用對話與設定 ---\n"
                "• track (t) <IG_ID>：首次追蹤對象並匯入近期對話\n"
                "• select (s) <關鍵字>：切換目前作用中的討論對象\n"
                "• nickname (n/nick) <暱稱> [IG_ID]：為對象設定專屬暱稱\n"
                "• card (c) [IG_ID]：檢視日常輕量人物關係摘要卡\n"
                "• card full (c full) [IG_ID]：檢視 7 大章節全景深度復盤長文\n"
                "• me (m) <內容>：記錄關於你的生活近況或偏好\n"
                "• list (ls/l)：列出所有已追蹤對象名單\n"
                "• status (st/q)：檢視目前選定對象與背景爬蟲進度\n\n"
                "--- 深度復盤與維護 ---\n"
                "• summarize_history (sh/sum) [IG_ID]：以所有完整歷史對話進行深度全景復盤\n"
                "• sync (sy) [IG_ID]：增量同步最新訊息\n"
                f"• track_full (tf) [IG_ID] [上限]：慢速防風控全量抓取（預設上限 {settings.TRACK_FULL_DEFAULT_LIMIT} 則）\n"
                "• rebuild_vectors (rv/rb) [IG_ID]：從本地 SQLite 重建事件向量庫\n"
                "• refresh_summary (rs/ref) [IG_ID]：強制更新日常人物摘要卡\n"
                "• untrack (ut) <IG_ID>：停止追蹤該對象\n"
                "• help (h/?)：返回精簡核心指令"
            )
        return CommandResult(success=True, message=msg, data={"show_all": cmd.show_all})
