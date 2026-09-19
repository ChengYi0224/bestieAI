"""
main.py — bestieAI 唯一啟動入口。

用法：
  uv run python main.py          # 預設：同時啟動 Bot + API Server
  uv run python main.py bot      # 僅啟動 IG Bot
  uv run python main.py api      # 僅啟動 REST API Server
"""
import sys
import logging
import threading
import signal

import typer
import uvicorn

from app.storage.db import init_db
from app.core.error_logger import get_error_logger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
get_error_logger()

cli = typer.Typer(invoke_without_command=True, help="bestieAI 啟動入口")


def _run_bot() -> None:
    """在當前 Thread 啟動 IG Bot Poller（blocking）。"""
    from app.bot.poller import BotPoller
    poller = BotPoller()

    def _shutdown(sig, frame):
        print("\n[Bot] 接收到中斷訊號，正在關閉...")
        poller.running = False
        if poller.bot_client:
            try:
                poller.bot_client.realtime_disconnect()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _shutdown)

    try:
        poller.run()
    except KeyboardInterrupt:
        _shutdown(None, None)


def _run_api(host: str = "0.0.0.0", port: int = 8000) -> None:
    """在當前 Thread 啟動 FastAPI / Uvicorn Server（blocking）。"""
    from app.api.app import create_app
    app = create_app()
    uvicorn.run(app, host=host, port=port)


@cli.callback()
def default(ctx: typer.Context) -> None:
    """未指定子命令時，同時啟動 Bot 與 API Server。"""
    if ctx.invoked_subcommand is not None:
        return
    print("=== bestieAI 啟動（Bot + API）===")
    init_db()
    bot_thread = threading.Thread(target=_run_bot, daemon=True, name="BotPoller")
    bot_thread.start()
    _run_api()


@cli.command()
def bot() -> None:
    """僅啟動 IG Bot Poller。"""
    print("=== bestieAI 啟動（Bot only）===")
    init_db()
    _run_bot()


@cli.command()
def api(
    host: str = typer.Option("0.0.0.0", help="監聽位址"),
    port: int = typer.Option(8000, help="監聽埠號"),
) -> None:
    """僅啟動 REST API Server。"""
    print("=== bestieAI 啟動（API only）===")
    init_db()
    _run_api(host=host, port=port)


if __name__ == "__main__":
    cli()
