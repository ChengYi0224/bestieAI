"""
poller.py — MQTT 即時推播監聽與背景任務 Worker。

功能：
- 白名單授權防護 (@require_whitelist)
- MQTT 雙向長連接監聽，被動即時喚醒
- 背景單一執行緒隊列 Worker，任務間 60~120s 安全冷卻
"""
import time
import socket
import logging
import queue
import threading
from datetime import datetime
from typing import Set, Optional, Dict, Any, List
from instagrapi import Client
from instagrapi.exceptions import LoginRequired

from app.core.config import settings
from app.core.security import require_whitelist
from app.services.session_service import SessionManager
from app.services.ig_service import IGClient
from app.bot.router import CommandRouter
from app.services.ingestion_service import IngestionPipeline
from app.storage.db import set_worker_status, get_worker_status, set_active_contact

logger = logging.getLogger("bestieAI.bot_poller")


class BotPoller:
    def __init__(
        self,
        session_manager: Optional[SessionManager] = None,
        router: Optional[CommandRouter] = None,
        ingestion: Optional[IngestionPipeline] = None
    ):
        self.session_manager = session_manager or SessionManager()
        self.router = router or CommandRouter()
        self.ingestion = ingestion or IngestionPipeline()
        self.seen_message_ids: Set[str] = set()
        self.running: bool = False
        self.bot_client: Optional[Client] = None
        self.bot_ig: Optional[IGClient] = None
        self.main_ig: Optional[IGClient] = None
        self.allowed_main_pk: Optional[str] = settings.MAIN_ACCOUNT_USER_ID or None

        self._task_queue: queue.Queue = queue.Queue()
        self._current_task: Optional[Dict[str, Any]] = None
        self._worker_thread: Optional[threading.Thread] = None

    def _resolve_main_pk(self) -> None:
        """動態取得主帳號的 Instagram PK (User ID)。"""
        if settings.MAIN_ACCOUNT_USER_ID:
            self.allowed_main_pk = str(settings.MAIN_ACCOUNT_USER_ID)
            return
        if self.bot_client and settings.MAIN_ACCOUNT_USERNAME:
            try:
                pk = self.bot_client.user_id_from_username(settings.MAIN_ACCOUNT_USERNAME)
                if pk:
                    self.allowed_main_pk = str(pk)
                    logger.info(f"已動態解析主帳號 {settings.MAIN_ACCOUNT_USERNAME} 之 PK: {self.allowed_main_pk}")
            except Exception as e:
                logger.warning(f"動態查詢主帳號 PK 失敗 ({e})，請於 .env 設定 MAIN_ACCOUNT_USER_ID。")

    def _setup_realtime(self) -> None:
        if not self.bot_client:
            return
        logger.info("建立 MQTT Realtime 長連接...")
        rt = self.bot_client.realtime_connect()
        if hasattr(rt, "transport") and rt.transport:
            rt.transport.timeout = 2.0
            if hasattr(rt.transport, "sock") and rt.transport.sock:
                rt.transport.sock.settimeout(2.0)

        self.bot_client.realtime_on("message", self._on_realtime_message)
        rt.direct_subscribe()
        logger.info("MQTT Realtime 訂閱成功，進入被動推播監聽模式。")

    def _reconnect_realtime(self) -> None:
        try:
            if self.bot_client:
                try:
                    self.bot_client.realtime_disconnect()
                except Exception:
                    pass
                self._setup_realtime()
        except Exception as e:
            logger.error(f"MQTT 重新連線失敗: {e}")

    def _on_realtime_message(self, event: Dict[str, Any]) -> None:
        msg_wrapper = event.get("message", {}) if isinstance(event, dict) else {}
        thread_id = str(msg_wrapper.get("thread_id") or event.get("thread_id") or "")
        item_id = str(msg_wrapper.get("item_id") or event.get("item_id") or "")
        user_id = str(msg_wrapper.get("user_id") or event.get("user_id") or "")
        text = msg_wrapper.get("text") or event.get("text") or ""

        if not text and isinstance(msg_wrapper.get("value"), dict):
            val = msg_wrapper["value"]
            text = val.get("text", "")
            item_id = item_id or str(val.get("item_id", ""))
            user_id = user_id or str(val.get("user_id", ""))

        self._process_message(thread_id, user_id, item_id, text)

    # ==================== 背景任務隊列 Worker ====================

    def _start_queue_worker(self) -> None:
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._task_worker_loop, daemon=True)
            self._worker_thread.start()
            logger.info("背景任務 Worker 執行緒已啟動。")

    def _task_worker_loop(self) -> None:
        import random
        while self.running:
            try:
                task = self._task_queue.get(timeout=2.0)
            except queue.Empty:
                continue

            self._current_task = task
            target = task["target"]
            max_amt = task["max_amount"]
            thread_id = task["thread_id"]
            start_ts = time.time()

            logger.info(f"[Worker] 開始處理排程任務：{target}（上限 {max_amt} 則）")
            set_worker_status({
                "running": True,
                "target": target,
                "mode": "安全慢速全量抓取",
                "max_amount": max_amt,
                "start_time": start_ts,
                "pages": 0,
                "count": 0,
                "queue": self._get_queued_targets(),
                "last_update": datetime.utcnow().isoformat()
            })

            def on_full_progress(count: int, pages: int):
                set_worker_status({
                    "running": True,
                    "target": target,
                    "mode": "全量抓取",
                    "max_amount": max_amt,
                    "start_time": start_ts,
                    "pages": pages,
                    "count": count,
                    "queue": self._get_queued_targets(),
                    "last_update": datetime.utcnow().isoformat()
                })
                logger.info(f"[Worker] {target} 慢速爬取進度：第 {pages} 頁，累計 {count} 則")

            try:
                if self.main_ig is None:
                    main_client = self.session_manager.login("main")
                    self.main_ig = IGClient(main_client)
                info = self.ingestion.run_full_ingestion(
                    self.main_ig,
                    target,
                    max_amount=max_amt,
                    progress_callback=on_full_progress
                )
                set_active_contact(target)
                elapsed_min = int((time.time() - start_ts) // 60)
                set_worker_status({
                    "running": False,
                    "target": target,
                    "completed_at": datetime.utcnow().isoformat(),
                    "total_downloaded": info['downloaded_messages'],
                    "elapsed_min": elapsed_min,
                    "queue": self._get_queued_targets()
                })
                reply_text = (
                    f"{target} 歷史紀錄匯入完成（耗時 {elapsed_min} 分鐘）\n"
                    f"下載: {info['downloaded_messages']} 則 / 新增: {info['new_inserted_messages']} 則 / 總量: {info['total_messages_in_db']} 則\n"
                    f"重構事件記憶: {info['chunks_rebuilt']} 條 / 關係摘要卡已更新"
                )
            except Exception as ex:
                logger.error(f"[Worker] 全量抓取 {target} 失敗: {ex}")
                set_worker_status({
                    "running": False,
                    "target": target,
                    "error": str(ex),
                    "failed_at": datetime.utcnow().isoformat(),
                    "queue": self._get_queued_targets()
                })
                reply_text = f"全量抓取 {target} 失敗: {ex}"

            if self.bot_ig and thread_id:
                try:
                    self.bot_ig.send_message(thread_id, reply_text)
                except Exception as send_err:
                    logger.warning(f"發送完成通知失敗: {send_err}")

            self._current_task = None
            self._task_queue.task_done()

            if not self._task_queue.empty():
                cooldown = random.uniform(60.0, 120.0)
                logger.info(f"[Worker] 任務 {target} 完成，安全冷卻 {cooldown:.1f} 秒後執行下一任務...")
                time.sleep(cooldown)

    def _get_queued_targets(self) -> List[str]:
        with self._task_queue.mutex:
            return [t["target"] for t in list(self._task_queue.queue)]

    # ==================== 訊息接收與分發 ====================

    @require_whitelist
    def _process_message(self, thread_id: str, user_id: str, item_id: str, text: str) -> None:
        if not text or not thread_id:
            return

        if item_id and item_id in self.seen_message_ids:
            return
        if item_id:
            self.seen_message_ids.add(item_id)

        logger.info(f"[Realtime Push] 收到授權主帳號 ({user_id}) 訊息: {text}")
        try:
            result = self.router.handle_message(text)
        except Exception as e:
            logger.error(f"處理訊息時發生未預期錯誤: {e}")
            if self.bot_ig:
                self.bot_ig.send_message(thread_id, f"系統暫時忙碌或發生錯誤：{e}")
            return

        if not self.bot_ig:
            return

        if result.startswith("TRACK_REQUEST:"):
            target = result.split(":", 1)[1]
            self.bot_ig.send_message(thread_id, f"開始抓取與 {target} 的歷史訊息...")
            try:
                if self.main_ig is None:
                    main_client = self.session_manager.login("main")
                    self.main_ig = IGClient(main_client)
                info = self.ingestion.run_ingestion(self.main_ig, target)
                set_active_contact(target)
                reply_text = f"已追蹤 {target}，匯入 {info['inserted_messages']} 則訊息，關係摘要卡已建立。"
            except Exception as ex:
                logger.error(f"Ingestion 失敗: {ex}")
                reply_text = f"追蹤 {target} 失敗: {ex}"
            self.bot_ig.send_message(thread_id, reply_text)

        elif result.startswith("TRACK_FULL_REQUEST:"):
            _, target, max_amt_str = result.split(":", 2)
            max_amt = int(max_amt_str)
            amt_label = f"上限 {max_amt} 則" if max_amt > 0 else "無限制"

            self._start_queue_worker()

            if self._current_task and self._current_task.get("target") == target:
                w_status = get_worker_status()
                pages = w_status.get("pages", 0) if w_status else 0
                count = w_status.get("count", 0) if w_status else 0
                self.bot_ig.send_message(
                    thread_id,
                    f"已有相同任務進行中：{target} 全量抓取中（目前第 {pages} 頁 / {count} 則），請稍候完成。"
                )
                return

            queued = self._get_queued_targets()
            if target in queued:
                pos = queued.index(target) + 1
                self.bot_ig.send_message(
                    thread_id,
                    f"{target} 已在排程名單中（排隊順位: {pos}），前項任務完成後將自動執行。"
                )
                return

            if self._current_task is not None:
                self._task_queue.put({"target": target, "max_amount": max_amt, "thread_id": thread_id})
                queued = self._get_queued_targets()
                pos = len(queued)
                self.bot_ig.send_message(
                    thread_id,
                    f"目前正在抓取 {self._current_task.get('target')}，已將 {target} 加入排程（順位: {pos}）。\n"
                    f"將於前一任務完成且安全冷卻後自動啟動。"
                )
                return

            self._task_queue.put({"target": target, "max_amount": max_amt, "thread_id": thread_id})
            self.bot_ig.send_message(
                thread_id,
                f"已開始抓取 {target} 歷史紀錄（{amt_label}）。\n"
                f"採慢速防風控模式，完成會通知。\n"
                f"可輸入 status 查詢進度。"
            )

        elif result.startswith("REFRESH_SUMMARY_REQUEST:"):
            target = result.split(":", 1)[1]
            self.bot_ig.send_message(thread_id, f"正在重新分析並更新 {target} 的人物關係摘要卡...")
            try:
                from app.storage.db import get_contact_by_username
                contact = get_contact_by_username(target)
                if not contact:
                    reply_text = f"找不到對象 {target}，請確認是否已 track。"
                else:
                    new_summary = self.ingestion.check_and_update_summary(contact["id"], force=True)
                    if new_summary:
                        reply_text = f"【{target} 摘要卡更新完成】\n{new_summary}"
                    else:
                        reply_text = f"{target} 尚無對話紀錄可生成摘要卡。"
            except Exception as ex:
                logger.error(f"更新摘要卡失敗: {ex}")
                reply_text = f"更新 {target} 摘要卡失敗: {ex}"
            self.bot_ig.send_message(thread_id, reply_text)

        elif result.startswith("SUMMARIZE_HISTORY_REQUEST:"):
            target = result.split(":", 1)[1]
            self.bot_ig.send_message(
                thread_id,
                f"分析 {target} 全量歷史對話中..."
            )
            try:
                info = self.ingestion.build_full_history_summary(target)
                reply_text = (
                    f"【{target} 全景關係復盤完成】（共 {info['total_messages']} 則對話）\n\n"
                    f"💡 7 大章節長文已保存，日常對話卡片已同步更新！\n"
                    f"可輸入「card full」查看完整長篇復盤內容。"
                )
            except Exception as ex:
                logger.error(f"全景歷史摘要失敗: {ex}")
                reply_text = f"全景歷史摘要失敗: {ex}"
            self.bot_ig.send_message(thread_id, reply_text)

        elif result.startswith("SYNC_REQUEST:"):
            target = result.split(":", 1)[1]
            self.bot_ig.send_message(thread_id, f"同步 {target} 最新訊息中...")
            try:
                if self.main_ig is None:
                    main_client = self.session_manager.login("main")
                    self.main_ig = IGClient(main_client)
                sync_info = self.ingestion.sync_messages(self.main_ig, target)
                summary_msg = "（摘要卡已更新）" if sync_info["summary_updated"] else ""
                reply_text = f"同步完成：新增 {sync_info['new_messages_count']} 則訊息，提煉 {sync_info['chunks_added']} 條事件記憶。{summary_msg}"
            except Exception as ex:
                logger.error(f"同步失敗: {ex}")
                reply_text = f"同步 {target} 失敗: {ex}"
            self.bot_ig.send_message(thread_id, reply_text)

        elif result.startswith("REBUILD_VECTORS_REQUEST:"):
            target = result.split(":", 1)[1]
            self.bot_ig.send_message(thread_id, f"重建 {target} 向量庫中...")
            try:
                info = self.ingestion.rebuild_vectors(target)
                reply_text = f"向量庫重建完成：總量 {info['total_messages']} 則訊息，提煉 {info['chunks_rebuilt']} 條事件記憶。"
            except Exception as ex:
                logger.error(f"重建向量庫失敗: {ex}")
                reply_text = f"重建 {target} 向量庫失敗: {ex}"
            self.bot_ig.send_message(thread_id, reply_text)

        else:
            self.bot_ig.send_message(thread_id, result)

    def _check_periodic_summaries(self) -> None:
        try:
            from app.storage.db import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, ig_account_id FROM contacts WHERE status = 'tracked'")
            rows = cursor.fetchall()
            conn.close()
            for r in rows:
                updated = self.ingestion.check_and_update_summary(r["id"])
                if updated:
                    logger.info(f"自動保底更新了 {r['ig_account_id']} 的人物關係摘要卡。")
        except Exception as e:
            logger.error(f"定期檢查摘要更新失敗: {e}")

    def run(self) -> None:
        logger.info("正在啟動 Bot 服務...")
        try:
            self.bot_client = self.session_manager.login("bot")
            self.bot_ig = IGClient(self.bot_client)
            self._resolve_main_pk()
            self._start_queue_worker()
        except Exception as e:
            logger.error(f"Bot 登入失敗: {e}")
            return

        self.running = True
        last_check_time = time.time()

        try:
            self._setup_realtime()
        except Exception as e:
            logger.warning(f"MQTT 初始化失敗 ({e})，降級為安全間隔輪詢模式。")
            self._fallback_poll_loop()
            return

        logger.info("Bot MQTT 服務運作中，等待手機 IG 私訊... (按 Ctrl+C 結束)")
        last_ping_time = time.time()
        while self.running:
            try:
                self.bot_client.realtime_read_once()
            except (socket.timeout, TimeoutError):
                now = time.time()
                if now - last_ping_time >= 30:
                    try:
                        self.bot_client.realtime_ping()
                        last_ping_time = now
                    except Exception as pe:
                        logger.warning(f"MQTT Ping 斷線 ({pe})，重新建立連線...")
                        self._reconnect_realtime()
                        last_ping_time = time.time()

                if now - last_check_time > 3600:
                    self._check_periodic_summaries()
                    last_check_time = now
            except KeyboardInterrupt:
                logger.info("接收到終止訊號 (Ctrl+C)，正在關閉 MQTT 連線...")
                try:
                    self.bot_client.realtime_disconnect()
                except Exception:
                    pass
                break
            except LoginRequired:
                logger.error("Session 過期失效，請重新啟動以手動驗證！")
                break
            except Exception as e:
                logger.error(f"MQTT 傳輸異常: {e}，等待 5 秒後重連...")
                time.sleep(5)
                self._reconnect_realtime()

    def _fallback_poll_loop(self) -> None:
        logger.info("啟動備用安全輪詢模式...")
        while self.running:
            try:
                threads = self.bot_ig.get_inbox_threads(amount=10)
                for thread in threads:
                    thread_id = str(thread.id)
                    msgs = self.bot_ig.get_thread_messages(thread_id=thread_id, amount=10)
                    for m in msgs:
                        self._process_message(thread_id, str(m.user_id), str(m.id), m.text or "")
            except LoginRequired:
                logger.error("Session 過期失效！")
                break
            except Exception as e:
                logger.error(f"輪詢中發生異常: {e}")

            time.sleep(max(settings.POLL_INTERVAL_SECONDS, 30))
