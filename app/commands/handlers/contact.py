"""
contact.py — 聯絡人管理相關 Command Handler。

PIPELINE (L2):
  ContactHandler.handle_*()
       │
       ├── handle_track        → CommandResult(action_type="TRACK_REQUEST")
       ├── handle_track_full   → CommandResult(action_type="TRACK_FULL_REQUEST")
       ├── handle_select       → 模糊搜尋聯絡人 → 切換 active contact
       ├── handle_select_choice→ 確認待選候選人
       ├── handle_nickname     → 設定暱稱 → SQLite
       ├── handle_untrack      → 標記 status='untracked'
       ├── handle_list         → 列出所有追蹤對象
       └── handle_status       → 查詢 worker 狀態 + active contact
"""
import time
from typing import Any, Optional

from app.commands.base import CommandResult
from app.commands.commands import (
    TrackCommand, TrackFullCommand, SelectCommand, SelectChoiceCommand,
    NicknameCommand, UntrackCommand, ListContactsCommand, StatusCommand,
)
from app.storage.repositories import ContactRepository, BotStateRepository


class ContactHandler:
    """聯絡人管理 Handler。依賴 ContactRepository 與 BotStateRepository。"""

    def __init__(
        self,
        contact_repo: Optional[ContactRepository] = None,
        bot_state_repo: Optional[BotStateRepository] = None,
        db_path: Optional[Any] = None,
    ):
        self.contact_repo = contact_repo or ContactRepository(db_path)
        self.bot_state_repo = bot_state_repo or BotStateRepository(db_path)


    def handle_track(self, cmd: TrackCommand) -> CommandResult:
        if not cmd.target:
            return CommandResult(
                success=False,
                message="格式錯誤！請提供要追蹤的帳號：track <IG_ID> [數量]\n（輸入 help 可查看常用指令）"
            )
        return CommandResult(
            success=True,
            message=f"開始追蹤 {cmd.target}（抓取 {cmd.amount} 則訊息）...",
            action_type="TRACK_REQUEST",
            data={"target": cmd.target, "amount": cmd.amount}
        )


    def handle_track_full(self, cmd: TrackFullCommand) -> CommandResult:
        if not cmd.target:
            return CommandResult(
                success=False,
                message="請指定要全量抓取的帳號：track_full <IG_ID> [最大訊息數]，或先使用 select 切換對象。"
            )
        return CommandResult(
            success=True,
            message=f"開始全量抓取 {cmd.target}（上限 {cmd.max_amount} 則）...",
            action_type="TRACK_FULL_REQUEST",
            data={"target": cmd.target, "max_amount": cmd.max_amount}
        )

    def handle_select(self, cmd: SelectCommand) -> CommandResult:
        query_key = cmd.query.strip()
        if not query_key:
            return CommandResult(
                success=False,
                message="格式錯誤！請提供要切換的帳號或名稱關鍵字：select <關鍵字>"
            )

        matches = self.contact_repo.search_fuzzy(query_key)
        if not matches:
            return CommandResult(
                success=False,
                message=f"找不到符合「{query_key}」的已追蹤對象。\n請先執行 track <IG_ID> 追蹤該帳號，或輸入 list 查看現有名單。",
                data={"query": query_key, "matches": []}
            )

        exact = next((m for m in matches if m["ig_account_id"].lower() == query_key.lower()), None)
        target_match = exact or (matches[0] if len(matches) == 1 else None)
        if target_match:
            self.contact_repo.set_active_by_id(target_match["id"])
            name_str = f"（{target_match['display_name'] or '未設定名稱'}）"
            return CommandResult(
                success=True,
                message=f"目前作用對象已切換為：{target_match['ig_account_id']}{name_str}",
                data={"status": "selected", "contact": dict(target_match)}
            )

        candidate_ids = [m["id"] for m in matches]
        self.bot_state_repo.set_pending_selection(candidate_ids)

        lines = [f"找到 {len(matches)} 個符合「{query_key}」的對象，請回傳數字選擇："]
        for idx, m in enumerate(matches, 1):
            name_str = f"（{m['display_name']}）" if m["display_name"] else ""
            lines.append(f"{idx}. {m['ig_account_id']}{name_str}")
        lines.append("（直接回傳數字如 1 即可完成切換）")
        return CommandResult(
            success=True,
            message="\n".join(lines),
            data={"status": "pending_selection", "candidates": [dict(m) for m in matches]}
        )

    def handle_select_choice(self, cmd: SelectChoiceCommand) -> CommandResult:
        pending_ids = self.bot_state_repo.get_pending_selection()
        if not pending_ids:
            return CommandResult(success=False, message="目前沒有待確認的候選對象。")

        if 0 <= cmd.choice_index < len(pending_ids):
            selected_id = pending_ids[cmd.choice_index]
            self.contact_repo.set_active_by_id(selected_id)
            target = self.contact_repo.get_by_id(selected_id)
            name_str = f"（{target['display_name']}）" if target and target["display_name"] else ""
            return CommandResult(
                success=True,
                message=f"已確認！目前作用對象切換為：{target['ig_account_id']}{name_str}",
                data={"status": "selected", "contact": dict(target) if target else None}
            )
        return CommandResult(
            success=False,
            message=f"數字超出範圍，請輸入 1 到 {len(pending_ids)} 之間的數字選擇對象。"
        )

    def handle_nickname(self, cmd: NicknameCommand) -> CommandResult:
        if not cmd.nickname:
            return CommandResult(success=False, message="格式錯誤！請提供暱稱：nickname <暱稱> [IG_ID]")

        if cmd.target:
            target = self.contact_repo.get_by_username(cmd.target)
        else:
            target = self.contact_repo.get_active()

        if not target:
            return CommandResult(
                success=False,
                message="尚未指定對象，請在指令後附帶帳號或先使用 select 切換對象。"
            )

        self.contact_repo.set_nickname(target["id"], cmd.nickname)
        return CommandResult(
            success=True,
            message=f"已為 {target['ig_account_id']} 設定暱稱為「{cmd.nickname}」。",
            data={"target": target["ig_account_id"], "nickname": cmd.nickname}
        )

    def handle_untrack(self, cmd: UntrackCommand) -> CommandResult:
        if not cmd.target:
            return CommandResult(success=False, message="格式錯誤！請指定對象：untrack <IG_ID>")
        self.contact_repo.untrack(cmd.target)
        return CommandResult(
            success=True,
            message=f"已將 {cmd.target} 標記為停止追蹤。",
            data={"target": cmd.target, "status": "untracked"}
        )

    def handle_list(self, cmd: ListContactsCommand) -> CommandResult:
        rows = self.contact_repo.list_all()


        if not rows:
            return CommandResult(
                success=True,
                message="目前尚未追蹤任何對象，請使用 track <IG_ID> 開始追蹤。",
                data={"contacts": []}
            )

        lines = ["【已追蹤對象清單】"]
        contacts_data = []
        for r in rows:
            nick_str = f" [暱稱: {r['nickname']}]" if ("nickname" in r.keys() and r["nickname"]) else ""
            lines.append(f"- {r['ig_account_id']} ({r['display_name']}){nick_str} [{r['status']}]")
            contacts_data.append(dict(r))

        return CommandResult(success=True, message="\n".join(lines), data={"contacts": contacts_data})

    def handle_status(self, cmd: StatusCommand) -> CommandResult:
        w_status = self.bot_state_repo.get_worker_status()
        worker_section = ""
        if w_status and w_status.get("running"):
            mode = w_status.get("mode", "背景任務")
            target = w_status.get("target", "未指定")
            detail = w_status.get("detail", "")
            elapsed_min = int((time.time() - w_status.get("start_time", time.time())) // 60)
            queue_str = f"\n排隊中: {', '.join(w_status.get('queue', []))}" if w_status.get('queue') else ""

            if detail:
                progress_str = f"進度: {detail}"
            elif w_status.get("pages") is not None:
                progress_str = f"進度: 第 {w_status.get('pages', 0)} 頁 ({w_status.get('count', 0)} 則)"
            else:
                progress_str = "進度: 處理中"

            title = "【背景抓取中】" if ("抓取" in mode and w_status.get("pages") is not None and not (detail and "重建" in detail)) else f"【{mode}執行中】"
            worker_section = (
                f"{title}\n"
                f"對象: {target}\n"
                f"{progress_str}\n"
                f"耗時: 約 {elapsed_min} 分鐘"
                f"{queue_str}\n\n"
            )
        elif w_status and not w_status.get("running"):
            worker_section = "【背景任務】無執行中任務\n\n"

        contact = self.contact_repo.get_active()
        if not contact:
            hint = f"{worker_section}尚未選定作用對象，請使用 select <關鍵字> 切換。" if worker_section else "尚未選定作用對象，請使用 select <IG_ID> 切換。"
            return CommandResult(
                success=True,
                message=hint,
                data={"worker_status": w_status, "active_contact": None}
            )

        nick_str = f" [暱稱: {contact['nickname']}]" if ("nickname" in contact.keys() and contact["nickname"]) else ""
        msg = (
            f"{worker_section}"
            f"【目前對象】\n"
            f"帳號: {contact['ig_account_id']} ({contact['display_name'] or '未設定'}){nick_str}\n"
            f"狀態: {contact['status']}\n"
            f"上次同步: {contact['last_synced_at'] or '無'}\n"
            f"摘要更新: {contact['summary_updated_at'] or '無'}\n"
            f"累積未摘要: {contact['new_messages_since_summary']} 則"
        )
        return CommandResult(
            success=True,
            message=msg,
            data={"worker_status": w_status, "active_contact": dict(contact)}
        )
