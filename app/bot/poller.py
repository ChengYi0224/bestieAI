"""
poller.py — Bot 編排層：MQTT 即時推播監聽 → 身分解析 → 指令派發 → 動作執行。

PIPELINE (L0 - End-to-End):
  [使用者手機 IG App] ──MQTT 推播──► BotPoller._on_realtime_message()
                                        │ parse_realtime_event()      (bot/realtime.py)
                                        ▼
                               BotPoller._process_message()
                                        │ SenderResolver.resolve()    (bot/identity.py)  發送者 PK → user_id
                                        ▼
                      CommandRouter.handle_message_structured(text, user_id)
                                        │
                                        ▼
                         ActionDispatcher.dispatch()                  (bot/dispatcher.py)
                          ├─ 一般回覆            → bot_ig.send_message()
                          ├─ TRACK_FULL          → TrackWorker 佇列    (bot/task_worker.py)
                          └─ TRACK / SYNC / ...  → 該使用者自己的 IG 連線 (services/ig_pool.py)

  多用戶：每位使用者有獨立的 IG 連線、作用對象 / 待選清單 / 背景進度（bot_user_state）、
  向量庫分區與 IngestionPipeline；擁有者 (OWNER_USER_ID) 使用 .env 主帳號 session。
"""
import logging
import socket
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Optional, Set

from instagrapi import Client
from instagrapi.exceptions import LoginRequired

from app.bot.activity import ActivityTracker
from app.bot.auth import require_whitelist
from app.bot.dispatcher import ActionDispatcher
from app.bot.identity import SenderResolver
from app.bot.realtime import parse_realtime_event
from app.bot.router import CommandRouter
from app.bot.sync_service import MessageSyncService
from app.bot.task_worker import TrackWorker
from app.core.config import settings
from app.core.error_logger import log_error
from app.services.ig_pool import IGClientPool
from app.services.ig_service import IGClient
from app.services.ingestion_service import IngestionPipeline, IngestionPipelinePool
from app.services.session_service import SessionManager
from app.storage.repositories.users import UserRepository
from app.storage.scope import ALL_USERS

logger = logging.getLogger("bestieAI.bot_poller")


class BotPoller:
    MAX_SEEN_MESSAGE_IDS = 5000

    def __init__(
        self,
        session_manager: Optional[SessionManager] = None,
        router: Optional[CommandRouter] = None,
        ingestion: Optional[IngestionPipeline] = None,
        ig_pool: Optional[IGClientPool] = None,
        user_repo: Optional[UserRepository] = None,
    ):
        self.session_manager = session_manager or SessionManager()
        self.user_repo = user_repo or UserRepository()
        self.running: bool = False
        self.bot_client: Optional[Client] = None
        self.bot_ig: Optional[IGClient] = None
        self.allowed_main_pk: Optional[str] = settings.MAIN_ACCOUNT_USER_ID or None

        self.ig_pool = ig_pool or IGClientPool(self.session_manager, self.user_repo)
        self.activity = ActivityTracker()
        self._ingestions = IngestionPipelinePool(override=ingestion)
        self.worker = TrackWorker(self.ig_pool, self._ingestions.for_user, self._notify)
        self.sync_service = MessageSyncService(
            self.ig_pool,
            is_busy=lambda: self.activity.active() or self.worker.busy(),
        )
        self.dispatcher = ActionDispatcher(
            ig_pool=self.ig_pool,
            ingestion_for=self._ingestions.for_user,
            worker=self.worker,
            activity=self.activity,
            send=self._notify,
        )
        self.resolver = SenderResolver(self._owner_pk, self.user_repo)

        self.seen_message_ids: Set[str] = set()
        self._seen_order: Deque[str] = deque()
        self._seen_lock = threading.Lock()

        if router is not None:
            self.router = router
            if getattr(self.router, "sync_callback", None) is None:
                self.router.sync_callback = self._sync_contact_messages
                if hasattr(self.router, "service"):
                    if hasattr(self.router.service, "_chat"):
                        self.router.service._chat.sync_callback = self._sync_contact_messages
                    if hasattr(self.router.service, "_export"):
                        self.router.service._export.sync_callback = self._sync_contact_messages
        else:
            self.router = CommandRouter(sync_callback=self._sync_contact_messages)

    # ==================== 小工具 ====================

    def _notify(self, thread_id: str, text: str) -> None:
        """以 Bot 帳號回覆私訊；失敗只記錄，不中斷流程。"""
        if not self.bot_ig or not thread_id:
            return
        try:
            self.bot_ig.send_message(thread_id, text)
        except Exception as e:
            logger.error(f"發送回覆訊息失敗: {e}")
            log_error(e, context="BotPoller._notify", logger_name="bestieAI.bot_poller")

    def _mark_seen(self, item_id: str) -> bool:
        """記錄已處理的 item_id；已見過回傳 False。保留最近 MAX_SEEN_MESSAGE_IDS 筆以免無限成長。"""
        with self._seen_lock:
            if item_id in self.seen_message_ids:
                return False
            self.seen_message_ids.add(item_id)
            self._seen_order.append(item_id)
            while len(self._seen_order) > self.MAX_SEEN_MESSAGE_IDS:
                self.seen_message_ids.discard(self._seen_order.popleft())
            return True

    def _sync_contact_messages(self, target_username: str, amount: int = 0, *, user_id: int) -> int:
        """Router / Handler 的同步回呼：以該使用者自己的 IG 連線同步私訊（失敗回傳 SYNC_FAILED）。"""
        return self.sync_service.sync(target_username, amount, user_id=user_id)

    # ==================== 身分 ====================

    def _owner_pk(self) -> Optional[str]:
        if not self.allowed_main_pk:
            self._resolve_main_pk()
        return self.allowed_main_pk

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

    # ==================== MQTT Realtime ====================

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
                except Exception as e:
                    logger.debug(f"重連前關閉舊 MQTT 連線失敗（可忽略）: {e}")
                self._setup_realtime()
        except Exception as e:
            logger.error(f"MQTT 重新連線失敗: {e}")

    def _on_realtime_message(self, event: Dict[str, Any]) -> None:
        try:
            incoming = parse_realtime_event(event)
            if incoming is None:
                return
            self._process_message(incoming.thread_id, incoming.sender_pk, incoming.item_id, incoming.text)
        except Exception as e:
            logger.error(f"即時推播處理異常: {e}")
            log_error(e, context="BotPoller._on_realtime_message", logger_name="bestieAI.bot_poller")

    # ==================== 訊息接收與分發 ====================

    @require_whitelist
    def _process_message(self, thread_id: str, sender_pk: str, item_id: str, text: str) -> None:
        if not text or not thread_id:
            return

        if item_id and not self._mark_seen(item_id):
            return

        user_id = self.resolver.resolve(sender_pk)
        logger.info(f"[Realtime Push] 收到發訊者 (pk={sender_pk}, user_id={user_id}) 訊息: {text}")
        try:
            result = self.router.handle_message_structured(text, sender_pk=sender_pk, user_id=user_id)
        except Exception as e:
            logger.error(f"處理訊息時發生未預期錯誤: {e}")
            log_error(e, context="BotPoller._process_message", logger_name="bestieAI.bot_poller")
            self._notify(thread_id, f"系統暫時忙碌或發生錯誤：{e}")
            return

        if not self.bot_ig:
            return
        self.dispatcher.dispatch(result, user_id, thread_id)

    # ==================== 定期維護 ====================

    def _check_periodic_summaries(self) -> None:
        try:
            from app.storage.repositories import ContactRepository
            rows = ContactRepository().get_tracked_contacts(user_id=ALL_USERS)  # 保底排程涵蓋所有使用者
            for r in rows:
                pipeline = self._ingestions.for_user(r["user_id"])
                if pipeline.check_and_update_summary(r["id"]):
                    logger.info(f"自動保底更新了 {r['ig_account_id']} 的人物關係摘要卡。")
        except Exception as e:
            logger.error(f"定期檢查摘要更新失敗: {e}")
            log_error(e, context="BotPoller._check_periodic_summaries", logger_name="bestieAI.bot_poller")

    # ==================== 主迴圈 ====================

    def run(self) -> None:
        logger.info("正在啟動 Bot 服務...")
        try:
            self.bot_client = self.session_manager.login("bot")
            self.bot_ig = IGClient(self.bot_client)
            self._resolve_main_pk()
            self.worker.start()
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
                except Exception as e:
                    logger.debug(f"關閉 MQTT 連線失敗（可忽略）: {e}")
                break
            except LoginRequired:
                logger.error("Session 過期失效，請重新啟動以手動驗證！")
                break
            except Exception as e:
                logger.error(f"MQTT 傳輸異常: {e}，等待 5 秒後重連...")
                time.sleep(5)
                self._reconnect_realtime()

        self.worker.stop()

    def _fallback_poll_loop(self) -> None:
        logger.info("啟動備用安全輪詢模式...")
        while self.running:
            try:
                threads = self.bot_ig.get_inbox_threads(amount=10)
                for thread in threads:
                    thread_id = str(thread.id)
                    msgs = self.bot_ig.get_thread_messages(thread_id=thread_id, amount=10)
                    for m in msgs:
                        if m.text and str(m.user_id).strip():
                            self._process_message(thread_id, str(m.user_id), str(m.id), m.text)
            except LoginRequired:
                logger.error("Session 過期失效！")
                break
            except Exception as e:
                logger.error(f"輪詢中發生異常: {e}")

            time.sleep(max(settings.POLL_INTERVAL_SECONDS, 30))
