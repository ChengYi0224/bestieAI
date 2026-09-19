"""
help.py — 說明指令 Handler。
"""
from app.commands.base import CommandResult
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
                "【IG AI 陪聊機器人 指令清單 - 全量模式】\n\n"
                "--- 需搭配 select（針對目前選定對象操作）---\n"
                "• 直接傳送訊息：與 AI 討論當前對象的相處與回覆策略\n"
                "• card (c) [full]：檢視日常輕量人物摘要卡（加 full 查長文）\n"
                "• exp [數量] [-I]：輸出最新私訊對話（預設先 sync，加 -I 僅讀取本地）\n"
                "• sync (sy)：立即增量同步最新私訊\n"
                "• refresh_summary (rs/ref)：強制重新分析並更新人物摘要卡\n"
                "• summarize_history (sh/sum)：生成 7 大章節全景深度復盤長文\n"
                f"• track_full (tf) [上限]：慢速防風控全量抓取歷史紀錄（預設上限 {settings.TRACK_FULL_DEFAULT_LIMIT} 則）\n"
                "• rebuild_vectors (rv/rb)：從本地 SQLite 重新建置事件向量庫\n"
                "• nickname (n/nick) <暱稱>：為目前選定對象設定專屬暱稱\n"
                "💡 提示：上述指令亦可在末尾加上 [IG_ID] 直接指定對象，如 card alex。\n\n"
                "--- 獨立指令（全域管理，不需搭配 select）---\n"
                "• select (s) <關鍵字>：切換目前討論的作用中對象\n"
                "• track (t) <IG_ID>：首次追蹤新對象並匯入近期對話\n"
                "• list (ls/l)：列出所有已追蹤對象名單\n"
                "• status (st/q)：檢視目前選定對象與背景爬蟲進度\n"
                "• me (m) <內容>：記錄關於你的個人生活近況、習慣或喜好\n"
                "• untrack (ut) <IG_ID>：停止追蹤特定對象\n"
                "• help (h/?)：返回精簡核心指令說明"
            )
        return CommandResult(success=True, message=msg, data={"show_all": cmd.show_all})
