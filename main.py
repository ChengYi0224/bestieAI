import sys
import logging
from app.db import init_db
from app.poller import BotPoller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

def main():
    print("=== IG AI 陪聊機器人 (bestieAI) 啟動中 ===")
    init_db()
    poller = BotPoller()
    try:
        poller.run()
    except KeyboardInterrupt:
        print("\n服務已由使用者手動終止。")
        sys.exit(0)

if __name__ == "__main__":
    main()
