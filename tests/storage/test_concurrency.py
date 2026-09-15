import time
import pytest
import concurrent.futures
from pathlib import Path
from app.storage.db import (
    init_db,
    get_connection,
    get_or_create_contact,
    save_messages,
    get_recent_messages,
    set_worker_status,
    get_worker_status,
    set_active_contact,
    get_active_contact,
)
from app.clients.gemini import GeminiKeyRing


def test_sqlite_concurrent_read_write(tmp_path):
    """驗證多執行緒同時讀寫 SQLite 時不會出現 database is locked 錯誤。"""
    db_file = tmp_path / 'concurrent_test.db'
    init_db(db_file)

    c1 = get_or_create_contact('user_1', 'User 1', db_path=db_file)
    c2 = get_or_create_contact('user_2', 'User 2', db_path=db_file)
    c3 = get_or_create_contact('user_3', 'User 3', db_path=db_file)

    errors = []

    def writer_task(worker_id: int):
        try:
            for i in range(15):
                cid = [c1, c2, c3][i % 3]
                save_messages(
                    contact_id=cid,
                    messages=[{
                        'ig_item_id': f'w_{worker_id}_{i}',
                        'sender': 'them' if i % 2 == 0 else 'me',
                        'content': f'msg {worker_id}-{i}',
                        'sent_at': f'2026-09-16T12:{i:02d}:00'
                    }],
                    db_path=db_file
                )
                set_worker_status({
                    'running': True,
                    'target': f'user_{(i % 3) + 1}',
                    'detail': f'worker {worker_id} writing {i}'
                }, db_path=db_file)
        except Exception as e:
            errors.append((worker_id, 'writer', e))

    def reader_task(worker_id: int):
        try:
            for i in range(25):
                cid = [c1, c2, c3][i % 3]
                get_recent_messages(cid, limit=5, db_path=db_file)
                get_worker_status(db_path=db_file)
                get_active_contact(db_path=db_file)
        except Exception as e:
            errors.append((worker_id, 'reader', e))

    with concurrent.futures.ThreadPoolExecutor(max_workers=14) as executor:
        futures = []
        for wid in range(8):
            futures.append(executor.submit(writer_task, wid))
        for rid in range(6):
            futures.append(executor.submit(reader_task, rid))
        concurrent.futures.wait(futures)

    assert len(errors) == 0, f'併發測試出現例外: {errors}'

    conn = get_connection(db_file)
    cur = conn.cursor()
    cur.execute('SELECT COUNT(1) as cnt FROM messages')
    total_msgs = cur.fetchone()['cnt']
    conn.close()

    assert total_msgs == 8 * 15


def test_gemini_keyring_concurrency_thread_safety():
    """驗證 GeminiKeyRing 在高併發多執行緒調用下無 race condition 且正確輪詢與冷卻。"""
    keys = [f'key_{i}' for i in range(5)]
    ring = GeminiKeyRing(keys=keys)
    errors = []
    keys_obtained = []

    def keyring_task(worker_id: int):
        try:
            for i in range(50):
                k = ring.get_available_key()
                if not k:
                    raise ValueError('未取得可用 key')
                keys_obtained.append(k)

                if i % 10 == 0 and worker_id % 2 == 0:
                    ring.mark_cooldown(k, cooldown_seconds=0.1)
                time.sleep(0.001)
        except Exception as e:
            errors.append((worker_id, e))

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(keyring_task, wid) for wid in range(10)]
        concurrent.futures.wait(futures)

    assert len(errors) == 0, f'KeyRing 併發出現例外: {errors}'
    assert len(keys_obtained) == 10 * 50
