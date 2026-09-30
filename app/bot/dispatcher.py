"""
dispatcher.py — 將 CommandResult.action_type 對應到實際的非同步動作。

  TRACK_REQUEST / TRACK_FULL_REQUEST / REFRESH_SUMMARY_REQUEST / SUMMARIZE_HISTORY_REQUEST /
  SYNC_REQUEST / REBUILD_VECTORS_REQUEST / LOGIN_COMPLETED（重設該使用者 IG 連線）/ 無 action（直接回覆訊息）

每個動作都帶著發送者的 user_id：使用該使用者的 IG 連線、IngestionPipeline，
並把進度寫入該使用者自己的 worker_status。
"""
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from app.bot import worker_status
from app.bot.activity import ActivityTracker
from app.bot.task_worker import Task, TrackWorker
from app.commands.base import CommandResult
from app.core.config import settings
from app.core.error_logger import log_error
from app.services.ig_pool import IGClientPool, IGSessionUnavailable
from app.services.ingestion_service import IngestionPipeline
from app.sources.factory import SourceAdapterFactory
from app.storage.db import get_contact_by_username, set_active_contact

logger = logging.getLogger("bestieAI.bot.dispatcher")

Send = Callable[[str, str], None]  # (thread_id, text)


class ActionDispatcher:
    def __init__(
        self,
        *,
        ig_pool: IGClientPool,
        ingestion_for: Callable[[int], IngestionPipeline],
        worker: TrackWorker,
        activity: ActivityTracker,
        send: Send,
    ):
        self._pool = ig_pool
        self._ingestion_for = ingestion_for
        self._worker = worker
        self._activity = activity
        self._send = send
        self._handlers: Dict[str, Callable[[Dict[str, Any], int, str], None]] = {
            "TRACK_REQUEST": self._track,
            "TRACK_FULL_REQUEST": self._track_full,
            "REFRESH_SUMMARY_REQUEST": self._refresh_summary,
            "SUMMARIZE_HISTORY_REQUEST": self._summarize_history,
            "SYNC_REQUEST": self._sync,
            "REBUILD_VECTORS_REQUEST": self._rebuild_vectors,
        }

    def dispatch(self, result: CommandResult, user_id: Optional[int], thread_id: str) -> None:
        if result.action_type == "LOGIN_COMPLETED":
            bound = (result.data or {}).get("user_id")
            if bound is not None:
                self._pool.invalidate(int(bound))  # 新 session 已寫入，丟棄舊連線
            self._send(thread_id, result.message)
            return

        handler = self._handlers.get(result.action_type or "")
        if handler is None:
            self._send(thread_id, result.message)
            return
        if user_id is None:
            self._send(thread_id, "尚未綁定身分，請先私訊：login <IG帳號> <密碼>")
            return
        handler(result.data or {}, user_id, thread_id)

    # ---------- 即時動作 ----------
    def _track(self, data: Dict[str, Any], uid: int, thread_id: str) -> None:
        target = data.get("target", "")
        amount = data.get("amount", settings.TRACK_DEFAULT_LIMIT)
        self._send(thread_id, f"開始抓取與 {target} 的歷史訊息（上限 {amount} 則）...")
        try:
            adapter = SourceAdapterFactory.create("instagram", ig_client=self._pool.get(uid))
            with self._activity.track():
                info = self._ingestion_for(uid).run_ingestion(adapter, target, amount=amount)
            set_active_contact(target, uid)
            reply = f"已追蹤 {target}，匯入 {info['inserted_messages']} 則訊息，關係摘要卡已建立。"
        except IGSessionUnavailable as ex:
            reply = str(ex)
        except Exception as ex:
            logger.error(f"Ingestion 失敗 (user={uid}): {ex}")
            log_error(ex, context=f"ActionDispatcher.TRACK_REQUEST — user={uid} {target}", logger_name="bestieAI.bot.dispatcher")
            reply = f"追蹤 {target} 失敗: {ex}"
        self._send(thread_id, reply)

    def _track_full(self, data: Dict[str, Any], uid: int, thread_id: str) -> None:
        target = data.get("target", "")
        max_amt = data.get("max_amount", 0)
        amt_label = f"上限 {max_amt} 則" if max_amt > 0 else "無限制"

        res = self._worker.enqueue(Task(user_id=uid, target=target, max_amount=max_amt, thread_id=thread_id))
        if res.kind == "running_same":
            from app.storage.db import get_worker_status
            w_status = get_worker_status(uid) or {}
            self._send(thread_id, f"已有相同任務進行中：{target} 全量抓取中（目前第 {w_status.get('pages', 0)} 頁 / {w_status.get('count', 0)} 則），請稍候完成。")
        elif res.kind == "queued_same":
            self._send(thread_id, f"{target} 已在排程名單中（排隊順位: {res.position}），前項任務完成後將自動執行。")
        elif res.kind == "queued":
            ahead = "其他任務" if res.other_user_busy else f"{self._worker.current.target if self._worker.current else '前一任務'}"
            self._send(thread_id, f"目前正在處理 {ahead}，已將 {target} 加入排程（順位: {res.position}）。\n將於前一任務完成且安全冷卻後自動啟動。")
        else:
            self._send(thread_id, f"已開始抓取 {target} 歷史紀錄（{amt_label}）。\n採慢速防風控模式，完成會通知。\n可輸入 status 查詢進度。")

    def _refresh_summary(self, data: Dict[str, Any], uid: int, thread_id: str) -> None:
        target = data.get("target", "")
        self._send(thread_id, f"正在重新分析並更新 {target} 的人物關係摘要卡...")
        try:
            contact = get_contact_by_username(target, user_id=uid)
            if not contact:
                reply = f"找不到對象 {target}，請確認是否已 track。"
            else:
                new_summary = self._ingestion_for(uid).check_and_update_summary(contact["id"], force=True)
                reply = f"【{target} 摘要卡更新完成】\n{new_summary}" if new_summary else f"{target} 尚無對話紀錄可生成摘要卡。"
        except Exception as ex:
            logger.error(f"更新摘要卡失敗 (user={uid}): {ex}")
            log_error(ex, context=f"ActionDispatcher.REFRESH_SUMMARY — user={uid} {target}", logger_name="bestieAI.bot.dispatcher")
            reply = f"更新 {target} 摘要卡失敗: {ex}"
        self._send(thread_id, reply)

    def _sync(self, data: Dict[str, Any], uid: int, thread_id: str) -> None:
        target = data.get("target", "")
        self._send(thread_id, f"同步 {target} 最新訊息中...")
        worker_status.report(uid, running=True, target=target, mode="增量同步", start_time=time.time(),
                             detail=f"正在同步 {target} 最新私訊...")
        try:
            adapter = SourceAdapterFactory.create("instagram", ig_client=self._pool.get(uid))
            with self._activity.track():
                info = self._ingestion_for(uid).sync_messages(adapter, target)
            summary_msg = "（摘要卡已更新）" if info["summary_updated"] else ""
            reply = f"同步完成：新增 {info['new_messages_count']} 則訊息，提煉 {info['chunks_added']} 條事件記憶。{summary_msg}"
            worker_status.report(uid, running=False, target=target, completed_at=worker_status.now_iso(),
                                 detail=f"同步完成: 新增 {info['new_messages_count']} 則訊息")
        except Exception as ex:
            logger.error(f"同步失敗 (user={uid}): {ex}")
            log_error(ex, context=f"ActionDispatcher.SYNC_REQUEST — user={uid} {target}", logger_name="bestieAI.bot.dispatcher")
            reply = str(ex) if isinstance(ex, IGSessionUnavailable) else f"同步 {target} 失敗: {ex}"
            worker_status.report(uid, running=False, target=target, error=str(ex), failed_at=worker_status.now_iso())
        self._send(thread_id, reply)

    # ---------- 背景長任務（各自一條執行緒）----------
    def _summarize_history(self, data: Dict[str, Any], uid: int, thread_id: str) -> None:
        target = data.get("target", "")
        self._send(thread_id, f"已在背景啟動 {target} 全景深度復盤分析。\n正在統整全量歷史對話並生成 7 大維度長文，完成時會發送通知。")

        def job(on_progress: Callable[[str], None]) -> str:
            info = self._ingestion_for(uid).build_full_history_summary(target, progress_callback=on_progress)
            worker_status.report(uid, running=False, target=target, completed_at=worker_status.now_iso(),
                                 detail=f"全景復盤完成 (共 {info['total_messages']} 則對話)")
            elapsed = int((time.time() - start_ts) // 60)
            return (
                f"【{target} 全景關係復盤完成】（共 {info['total_messages']} 則對話，耗時約 {elapsed} 分鐘）\n\n"
                f"💡 7 大章節長文已保存，日常對話卡片已同步更新！\n可輸入「card full」查看完整長篇復盤內容。"
            )

        start_ts = time.time()
        self._spawn(uid, target, thread_id, "全景復盤分析", "正統整全量歷史對話並提煉深度長文中...", job, "全景歷史摘要失敗")

    def _rebuild_vectors(self, data: Dict[str, Any], uid: int, thread_id: str) -> None:
        target = data.get("target", "")
        self._send(thread_id, f"已在背景啟動 {target} 向量庫重建。\n系統將採用批次斷點續傳提煉記憶，完成時會發送通知。\n期間可正常傳送訊息或使用 status 查詢進度。")

        def job(on_progress: Callable[[str], None]) -> str:
            info = self._ingestion_for(uid).rebuild_vectors(target, progress_callback=on_progress)
            worker_status.report(uid, running=False, target=target, completed_at=worker_status.now_iso(),
                                 detail=f"重建完成 (共 {info['chunks_rebuilt']} 條記憶)")
            elapsed = int((time.time() - start_ts) // 60)
            return (
                f"【{target} 向量庫重建完成】（耗時約 {elapsed} 分鐘）\n"
                f"總訊息: {info['total_messages']} 則\n提煉事件記憶: {info['chunks_rebuilt']} 條已寫入向量庫"
            )

        start_ts = time.time()
        self._spawn(uid, target, thread_id, "重建向量庫", "準備讀取本地歷史對話紀錄...", job, f"重建 {target} 向量庫失敗")

    def _spawn(
        self,
        uid: int,
        target: str,
        thread_id: str,
        mode: str,
        first_detail: str,
        job: Callable[[Callable[[str], None]], str],
        fail_prefix: str,
    ) -> None:
        def runner() -> None:
            start_ts = time.time()
            worker_status.report(uid, running=True, target=target, mode=mode, start_time=start_ts, detail=first_detail)

            def on_progress(detail_msg: str) -> None:
                worker_status.report(uid, running=True, target=target, mode=mode, start_time=start_ts, detail=detail_msg)
                logger.info(f"[{mode}] user={uid} {target}: {detail_msg}")

            try:
                reply = job(on_progress)
            except Exception as ex:
                logger.error(f"{fail_prefix} (user={uid}): {ex}")
                log_error(ex, context=f"ActionDispatcher.{mode} — user={uid} {target}", logger_name="bestieAI.bot.dispatcher")
                worker_status.report(uid, running=False, target=target, error=str(ex), failed_at=worker_status.now_iso())
                reply = f"{fail_prefix}: {ex}"
            if thread_id:
                self._send(thread_id, reply)

        threading.Thread(target=runner, daemon=True).start()
