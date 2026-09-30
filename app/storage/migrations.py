"""
migrations.py — 多租戶（multi-tenant）相關的 Schema 定義與遷移。

背景：
- contacts.ig_account_id 原為全域 UNIQUE，導致兩個使用者無法追蹤同一個 IG 帳號
  → 改為 UNIQUE (user_id, ig_account_id)
- messages.ig_item_id 原為全域 UNIQUE，同一串私訊（例如主人與朋友互相追蹤）的訊息會互相吃掉
  → 改為 UNIQUE (contact_id, ig_item_id)
- bot_state 原為單列全域單例，所有使用者共用「目前作用對象 / 待選清單 / 背景進度」
  → 改為 bot_user_state，每位使用者一列

SQLite 無法直接修改欄位約束，因此以「建立新表 → 複製 → 刪除舊表 → 更名」方式重建（保留 id，外鍵不變）。
"""
import logging
import sqlite3
from typing import List

logger = logging.getLogger("bestieAI.storage.migrations")

# name 由呼叫端帶入（正式表名或暫存表名）
CONTACTS_DDL = """
CREATE TABLE IF NOT EXISTS {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER DEFAULT 1 REFERENCES users(id) ON DELETE CASCADE,
    ig_account_id TEXT NOT NULL,
    display_name TEXT,
    nickname TEXT,
    relationship_note TEXT,
    status TEXT DEFAULT 'tracked',
    summary_card TEXT,
    summary_updated_at DATETIME,
    full_history_summary TEXT,
    full_history_updated_at DATETIME,
    new_messages_since_summary INTEGER DEFAULT 0,
    last_synced_at DATETIME,
    UNIQUE (user_id, ig_account_id)
);
"""

MESSAGES_DDL = """
CREATE TABLE IF NOT EXISTS {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    ig_item_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    sent_at DATETIME NOT NULL,
    ingested_to_vector_store BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (contact_id, ig_item_id)
);
"""

BOT_USER_STATE_DDL = """
CREATE TABLE IF NOT EXISTS bot_user_state (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    active_contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    pending_selection TEXT,
    worker_status TEXT,
    updated_at DATETIME
);
"""


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table});")]


def _has_unique_index_on(conn: sqlite3.Connection, table: str, cols: List[str]) -> bool:
    """資料表是否存在欄位集合恰好等於 cols 的 UNIQUE 約束 / 索引。"""
    for idx in conn.execute(f"PRAGMA index_list({table});").fetchall():
        if not idx["unique"]:
            continue
        idx_cols = [r[2] for r in conn.execute(f"PRAGMA index_info({idx['name']});")]
        if idx_cols == cols:
            return True
    return False


def _rebuild(conn: sqlite3.Connection, table: str, ddl: str) -> None:
    """以新 DDL 重建資料表並保留資料（12 步驟標準流程；需在交易外執行 PRAGMA）。"""
    new_name = f"{table}__new"
    old_cols = _columns(conn, table)
    conn.executescript(ddl.format(name=new_name))  # executescript 會先 commit 既有交易
    new_cols = _columns(conn, new_name)
    shared = ", ".join(c for c in old_cols if c in new_cols)
    conn.executescript(f"""
        PRAGMA foreign_keys = OFF;
        BEGIN;
        INSERT INTO {new_name} ({shared}) SELECT {shared} FROM {table};
        DROP TABLE {table};
        ALTER TABLE {new_name} RENAME TO {table};
        COMMIT;
        PRAGMA foreign_keys = ON;
    """)
    violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
    if violations:
        raise RuntimeError(f"重建 {table} 後發現 {len(violations)} 筆外鍵違規，請檢查資料庫")
    logger.info(f"已重建資料表 {table}（多租戶唯一性約束）")


def apply_multi_tenant_migrations(conn: sqlite3.Connection) -> None:
    """冪等：可重複執行。必須在 users / contacts / messages / bot_state 皆已建立、預設管理者已存在後呼叫。"""
    if _has_unique_index_on(conn, "contacts", ["ig_account_id"]):
        _rebuild(conn, "contacts", CONTACTS_DDL)
    if _has_unique_index_on(conn, "messages", ["ig_item_id"]):
        _rebuild(conn, "messages", MESSAGES_DDL)

    conn.executescript(BOT_USER_STATE_DDL)
    # 既有的全域單例狀態歸屬於管理者 (user_id = 1)
    conn.execute("""
        INSERT OR IGNORE INTO bot_user_state (user_id, active_contact_id, pending_selection, worker_status, updated_at)
        SELECT 1, active_contact_id, pending_selection, worker_status, updated_at FROM bot_state WHERE id = 1
    """)
    conn.commit()

    if "user_id" not in _columns(conn, "bot_conversations"):
        conn.execute("ALTER TABLE bot_conversations ADD COLUMN user_id INTEGER DEFAULT 1;")
        # 既有對話依其聯絡人歸屬；無聯絡人的一般對話歸屬管理者
        conn.execute("""
            UPDATE bot_conversations
            SET user_id = COALESCE((SELECT c.user_id FROM contacts c WHERE c.id = bot_conversations.contact_id), 1)
        """)
        conn.commit()
