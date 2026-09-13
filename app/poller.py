import time
import logging
from typing import Set, Optional
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

    def run(self) -> None:
        logger.info("正在啟動 Bot 輪詢服務...")
        try:
            bot_client_raw = self.session_manager.login("bot")
            bot_ig = IGClient(bot_client_raw)
        except Exception as e:
            logger.error(f"Bot 登入失敗: {e}")
            return

        main_ig = None

        logger.info("Bot 輪詢中，按 Ctrl+C 結束...")
        while True:
            try:
                threads = bot_ig.get_inbox_threads(amount=10)
                for thread in threads:
                    thread_id = str(thread.id)
                    msgs = bot_ig.get_thread_messages(thread_id=thread_id, amount=10)
                    for m in msgs:
                        msg_id = str(m.id)
                        if msg_id in self.seen_message_ids:
                            continue

                        self.seen_message_ids.add(msg_id)

                        if str(m.user_id) == str(bot_client_raw.user_id):
                            continue

                        user_text = m.text or ""
                        logger.info(f"收到來自 {m.user_id} 的訊息: {user_text}")

                        result = self.router.handle_message(user_text)

                        if result.startswith("TRACK_REQUEST:"):
                            target = result.split(":", 1)[1]
                            bot_ig.send_message(thread_id, f"開始抓取與 {target} 的歷史訊息，請稍候...")
                            try:
                                if main_ig is None:
                                    main_client = self.session_manager.login("main")
                                    main_ig = IGClient(main_client)
                                info = self.ingestion.run_ingestion(main_ig, target)
                                reply_text = f"已完成追蹤 {target}！匯入 {info['inserted_messages']} 則訊息，摘要卡已建立。"
                            except Exception as ex:
                                logger.error(f"Ingestion 失敗: {ex}")
                                reply_text = f"追蹤 {target} 失敗: {ex}"
                            bot_ig.send_message(thread_id, reply_text)

                        elif result.startswith("REFRESH_SUMMARY_REQUEST:"):
                            bot_ig.send_message(thread_id, "手動重新生成摘要卡功能尚未整合至背景排程。")

                        else:
                            bot_ig.send_message(thread_id, result)

            except LoginRequired:
                logger.error("Session 過期失效，請手動重啟程式進行重新驗證登入！")
                break
            except Exception as e:
                logger.error(f"輪詢中發生異常: {e}")

            time.sleep(settings.POLL_INTERVAL_SECONDS)
