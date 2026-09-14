import sys
import signal
import logging
from app.storage.db import init_db
from app.bot.poller import BotPoller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

def main():
    print("=== IG AI 陪聊機器人 (bestieAI) 啟動中 ===")
    init_db()
    poller = BotPoller()

    def signal_handler(sig, frame):
        print("\n接收到中斷訊號，正在關閉服務...")
        poller.running = False
        if poller.bot_client:
            try:
                poller.bot_client.realtime_disconnect()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGBREAK"):  # Windows Ctrl+Break 支援
        signal.signal(signal.SIGBREAK, signal_handler)

    try:
        poller.run()
    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == "__main__":
    main()
