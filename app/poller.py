import time
import socket
import logging
from typing import Set, Optional, Dict, Any
from instagrapi import Client
from instagrapi.exceptions import LoginRequired
from app.config import settings
from app.sessions import SessionManager
from app.ig import IGClient
from app.router import CommandRouter
from app.ingestion import IngestionPipeline

logger = logging.getLogger("bestieAI.poller")


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

    def _setup_realtime(self) -> None:
        if not self.bot_client:
            return
        logger.info("建立 MQTT Realtime 長連接...")
        rt = self.bot_client.realtime_connect()
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

    def _process_message(self, thread_id: str, user_id: str, item_id: str, text: str) -> None:
        if not text or not thread_id:
            return

        if item_id and item_id in self.seen_message_ids:
            return
        if item_id:
            self.seen_message_ids.add(item_id)

        bot_pk = str(getattr(self.bot_client, "user_id", ""))
        if user_id and user_id == bot_pk:
            return

        logger.info(f"[Realtime Push] 收到來自 {user_id} 的訊息: {text}")
        result = self.router.handle_message(text)

        if not self.bot_ig:
            return

        if result.startswith("TRACK_REQUEST:"):
            target = result.split(":", 1)[1]
            self.bot_ig.send_message(thread_id, f"開始抓取與 {target} 的歷史訊息，請稍候...")
            try:
                if self.main_ig is None:
                    main_client = self.session_manager.login("main")
                    self.main_ig = IGClient(main_client)
                info = self.ingestion.run_ingestion(self.main_ig, target)
                reply_text = f"已完成追蹤 {target}！匯入 {info['inserted_messages']} 則訊息，摘要卡已建立。"
            except Exception as ex:
                logger.error(f"Ingestion 失敗: {ex}")
                reply_text = f"追蹤 {target} 失敗: {ex}"
            self.bot_ig.send_message(thread_id, reply_text)

        elif result.startswith("REFRESH_SUMMARY_REQUEST:"):
            target = result.split(":", 1)[1]
            self.bot_ig.send_message(thread_id, f"正在重新分析並更新 {target} 的人物關係摘要卡...")
            try:
                from app.db import get_contact_by_username
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

        elif result.startswith("SYNC_REQUEST:"):
            target = result.split(":", 1)[1]
            self.bot_ig.send_message(thread_id, f"開始增量同步與 {target} 的最新聊天紀錄...")
            try:
                if self.main_ig is None:
                    main_client = self.session_manager.login("main")
                    self.main_ig = IGClient(main_client)
                sync_info = self.ingestion.sync_messages(self.main_ig, target)
                summary_msg = "（已達門檻，人物關係摘要卡已增量更新）" if sync_info["summary_updated"] else "（尚未達到摘要卡更新門檻）"
                reply_text = f"同步完成！新增 {sync_info['new_messages_count']} 則訊息，建立 {sync_info['chunks_added']} 個向量片段。{summary_msg}"
            except Exception as ex:
                logger.error(f"同步失敗: {ex}")
                reply_text = f"同步 {target} 失敗: {ex}"
            self.bot_ig.send_message(thread_id, reply_text)

        else:
            self.bot_ig.send_message(thread_id, result)

    def _check_periodic_summaries(self) -> None:
        try:
            from app.db import get_connection
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
        while self.running:
            try:
                self.bot_client.realtime_read_once()
            except (socket.timeout, TimeoutError):
                try:
                    self.bot_client.realtime_ping()
                    if time.time() - last_check_time > 3600:
                        self._check_periodic_summaries()
                        last_check_time = time.time()
                except Exception as pe:
                    logger.warning(f"MQTT Ping 逾時或斷線: {pe}，重新建立連線...")
                    self._reconnect_realtime()
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
