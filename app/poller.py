import time
import socket
import logging
from datetime import datetime
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
        # 設定較短的 socket 逾時（2 秒），讓 Windows 底層 blocking socket 能夠及時讓出 GIL 捕捉 SIGINT (Ctrl+C)
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
        try:
            result = self.router.handle_message(text)
        except Exception as e:
            logger.error(f"處理訊息時發生未預期錯誤: {e}")
            if self.bot_ig:
                self.bot_ig.send_message(thread_id, f"抱歉，系統暫時忙碌或發生錯誤：{e}\n請稍候再試。")
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
                from app.db import set_active_contact
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
            from app.db import set_worker_status, set_active_contact
            start_ts = time.time()
            set_worker_status({
                "running": True,
                "target": target,
                "mode": "安全慢速全量抓取",
                "max_amount": max_amt,
                "start_time": start_ts,
                "pages": 0,
                "count": 0,
                "last_update": datetime.utcnow().isoformat()
            })

            self.bot_ig.send_message(
                thread_id,
                f"已開始抓取 {target} 歷史紀錄（{amt_label}）。\n"
                f"採慢速防風控模式，完成會通知。\n"
                f"可輸入 status 查詢進度。"
            )

            def on_full_progress(count: int, pages: int):
                # 靜默記錄進度到 SQLite，不發送 IG 私訊打擾
                set_worker_status({
                    "running": True,
                    "target": target,
                    "mode": "全量抓取",
                    "max_amount": max_amt,
                    "start_time": start_ts,
                    "pages": pages,
                    "count": count,
                    "last_update": datetime.utcnow().isoformat()
                })
                logger.info(f"[Worker] {target} 慢速爬取進度：已抓第 {pages} 頁，累計 {count} 則")

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
                    "elapsed_min": elapsed_min
                })
                reply_text = (
                    f"{target} 歷史紀錄匯入完成（耗時 {elapsed_min} 分鐘）\n"
                    f"下載: {info['downloaded_messages']} 則 / 新增: {info['new_inserted_messages']} 則 / 總量: {info['total_messages_in_db']} 則\n"
                    f"重構 Chunks: {info['chunks_rebuilt']} / 關係摘要卡已更新"
                )
            except Exception as ex:
                logger.error(f"全量抓取失敗: {ex}")
                set_worker_status({
                    "running": False,
                    "target": target,
                    "error": str(ex),
                    "failed_at": datetime.utcnow().isoformat()
                })
                reply_text = f"全量抓取 {target} 失敗: {ex}"
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

        elif result.startswith("SUMMARIZE_HISTORY_REQUEST:"):
            target = result.split(":", 1)[1]
            self.bot_ig.send_message(
                thread_id,
                f"分析 {target} 全量歷史對話中..."
            )
            try:
                info = self.ingestion.build_full_history_summary(target)
                reply_text = (
                    f"【{target} 全景關係復盤卡】（共 {info['total_messages']} 則對話）\n\n"
                    f"{info['summary_card']}"
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
                reply_text = f"同步完成：新增 {sync_info['new_messages_count']} 則訊息，{sync_info['chunks_added']} 個 Chunks。{summary_msg}"
            except Exception as ex:
                logger.error(f"同步失敗: {ex}")
                reply_text = f"同步 {target} 失敗: {ex}"
            self.bot_ig.send_message(thread_id, reply_text)

        elif result.startswith("REBUILD_VECTORS_REQUEST:"):
            target = result.split(":", 1)[1]
            self.bot_ig.send_message(thread_id, f"重建 {target} 向量庫中...")
            try:
                info = self.ingestion.rebuild_vectors(target)
                reply_text = f"向量庫重建完成：總量 {info['total_messages']} 則訊息，共 {info['chunks_rebuilt']} 個 Chunks。"
            except Exception as ex:
                logger.error(f"重建向量庫失敗: {ex}")
                reply_text = f"重建 {target} 向量庫失敗: {ex}"
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
        last_ping_time = time.time()
        while self.running:
            try:
                self.bot_client.realtime_read_once()
            except (socket.timeout, TimeoutError):
                # 正常逾時，檢查是否需要發送 MQTT 心跳 (每 30 秒 ping 一次)
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
