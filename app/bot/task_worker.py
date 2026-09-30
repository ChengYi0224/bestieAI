"""
task_worker.py — 全量歷史抓取（track_full）的背景排程 Worker。

所有使用者共用同一個佇列與單一 worker 執行緒（一次只跑一個任務，任務之間安全冷卻），
但任務帶有 user_id：使用該使用者自己的 IG 連線與 IngestionPipeline，進度寫入該使用者自己的狀態。
"""
import logging
import queue
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from app.bot import worker_status
from app.core.error_logger import log_error
from app.services.ig_pool import IGClientPool
from app.services.ingestion_service import IngestionPipeline
from app.sources.factory import SourceAdapterFactory
from app.storage.db import set_active_contact

logger = logging.getLogger("bestieAI.bot.task_worker")


@dataclass
class Task:
    user_id: int
    target: str
    max_amount: int
    thread_id: str


@dataclass
class EnqueueResult:
    kind: str  # "started" | "running_same" | "queued_same" | "queued"
    position: int = 0
    other_user_busy: bool = False


class TrackWorker:
    COOLDOWN_RANGE = (60.0, 120.0)

    def __init__(
        self,
        ig_pool: IGClientPool,
        ingestion_for: Callable[[int], IngestionPipeline],
        notify: Callable[[str, str], None],
    ):
        self._pool = ig_pool
        self._ingestion_for = ingestion_for
        self._notify = notify
        self._queue: "queue.Queue[Task]" = queue.Queue()
        self._current: Optional[Task] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ---------- 狀態查詢 ----------
    def busy(self) -> bool:
        return self._current is not None or not self._queue.empty()

    @property
    def current(self) -> Optional[Task]:
        return self._current

    def queued_targets(self, user_id: Optional[int] = None) -> List[str]:
        """佇列中的目標；指定 user_id 時只回傳該使用者自己的（不洩漏他人的對象）。"""
        with self._queue.mutex:
            return [t.target for t in list(self._queue.queue) if user_id is None or t.user_id == user_id]

    # ---------- 排程 ----------
    def enqueue(self, task: Task) -> EnqueueResult:
        self.start()
        cur = self._current
        if cur and cur.user_id == task.user_id and cur.target == task.target:
            return EnqueueResult("running_same")
        mine = self.queued_targets(task.user_id)
        if task.target in mine:
            return EnqueueResult("queued_same", position=self._position_of(task))
        was_busy = cur is not None
        self._queue.put(task)
        if was_busy:
            return EnqueueResult(
                "queued",
                position=len(self.queued_targets()),
                other_user_busy=cur.user_id != task.user_id,
            )
        return EnqueueResult("started")

    def _position_of(self, task: Task) -> int:
        with self._queue.mutex:
            for idx, t in enumerate(list(self._queue.queue), 1):
                if t.user_id == task.user_id and t.target == task.target:
                    return idx
        return 0

    # ---------- 生命週期 ----------
    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            logger.info("背景任務 Worker 執行緒已啟動。")

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                task = self._queue.get(timeout=2.0)
            except queue.Empty:
                continue
            self._current = task
            try:
                self._run(task)
            finally:
                self._current = None
                self._queue.task_done()
            if not self._queue.empty():
                cooldown = random.uniform(*self.COOLDOWN_RANGE)
                logger.info(f"[Worker] 任務 {task.target} 完成，安全冷卻 {cooldown:.1f} 秒後執行下一任務...")
                time.sleep(cooldown)

    # ---------- 單一任務 ----------
    def _run(self, task: Task) -> None:
        uid, target, max_amt = task.user_id, task.target, task.max_amount
        start_ts = time.time()
        logger.info(f"[Worker] 開始處理排程任務：user={uid} {target}（上限 {max_amt} 則）")

        def status(**fields) -> None:
            worker_status.report(uid, target=target, queue=self.queued_targets(uid), **fields)

        status(running=True, mode="安全慢速全量抓取", max_amount=max_amt, start_time=start_ts, pages=0, count=0)

        def on_progress(*args, **kwargs) -> None:
            if len(args) == 2 and isinstance(args[0], int) and isinstance(args[1], int):
                count, pages = args
                status(running=True, mode="全量抓取", max_amount=max_amt, start_time=start_ts, pages=pages, count=count,
                       detail=f"爬取歷史私訊中: 第 {pages} 頁 (累計 {count} 則)")
                logger.info(f"[Worker] user={uid} {target} 慢速爬取進度：第 {pages} 頁，累計 {count} 則")
            elif args and isinstance(args[0], str):
                status(running=True, mode="全量抓取", max_amount=max_amt, start_time=start_ts, detail=args[0])
                logger.info(f"[Worker] user={uid} {target} 全量抓取進度：{args[0]}")

        try:
            ig = self._pool.get(uid)
            adapter = SourceAdapterFactory.create("instagram", ig_client=ig)
            info = self._ingestion_for(uid).run_full_ingestion(adapter, target, max_amount=max_amt, progress_callback=on_progress)
            set_active_contact(target, uid)
            elapsed_min = int((time.time() - start_ts) // 60)
            worker_status.report(uid, running=False, target=target, completed_at=worker_status.now_iso(),
                                 total_downloaded=info["downloaded_messages"], elapsed_min=elapsed_min,
                                 queue=self.queued_targets(uid))
            reply = (
                f"{target} 歷史紀錄匯入完成（耗時 {elapsed_min} 分鐘）\n"
                f"下載: {info['downloaded_messages']} 則 / 新增: {info['new_inserted_messages']} 則 / 總量: {info['total_messages_in_db']} 則\n"
                f"重構事件記憶: {info['chunks_rebuilt']} 條 / 關係摘要卡已更新"
            )
        except Exception as ex:
            logger.error(f"[Worker] 全量抓取 user={uid} {target} 失敗: {ex}")
            log_error(ex, context=f"TrackWorker._run — user={uid} 全量抓取 {target}", logger_name="bestieAI.bot.task_worker")
            worker_status.report(uid, running=False, target=target, error=str(ex),
                                 failed_at=worker_status.now_iso(), queue=self.queued_targets(uid))
            reply = f"全量抓取 {target} 失敗: {ex}"

        if task.thread_id:
            self._notify(task.thread_id, reply)
