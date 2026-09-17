# Source Adapter Architecture

版本：v2.0  
建立日期：2026-09-17  
更新日期：2026-09-17  
適用範圍：`bestieAI` Source Adapter 模組 + Command Bus / Router Registry Pattern 設計規範

---

## 1. 為什麼需要 Source Adapter

目前的 `IngestionPipeline` 的「進料」邏輯直接耦合在 `instagrapi.IGClient`：

```
# ingestion_service.py — 現況（問題）
thread = ig_client.get_thread_by_username(target_username)    # IG 專屬
raw_messages = ig_client.get_thread_messages(thread_id, ...)  # IG 專屬
me_pk = str(ig_client.client.user_id)                         # IG 專屬
```

這代表「提煉 → 分群 → 融合 → 摘要」這套完整的 Pipeline，只能吃 Instagram 的訊息。

**目標**：讓同一套 Pipeline 能接受任意來源的訊息，包括但不限於：

| 來源 | 代號 | 狀態 |
|---|---|---|
| Instagram（instagrapi） | `instagram` | ✅ 現有 |
| 本地 JSON / CSV 聊天紀錄匯入 | `file_import` | 🔜 待實作 |
| LINE | `line` | 🔲 預留介面 |
| Telegram | `telegram` | 🔲 預留介面 |
| iOS App 手動輸入 | `manual` | 🔲 預留介面 |

---

## 2. 架構總覽

```
╔══════════════════════════════════════════════════════════════════════════╗
║                        bestieAI 資料流總覽                               ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  [指令層]                  [解析層]              [派發層]                ║
║                                                                          ║
║  IG 私訊文字 ─→ CommandRouter ─→ CommandParserRegistry ─→ BaseCommand   ║
║                     │              （Registry 查表，無 if-else）          ║
║                     └──────────────────────────► CommandBus.dispatch()  ║
║                                                         │                ║
║                                               CommandService Facade      ║
║                                       ┌───────────────┼────────────┐    ║
║                                  ContactHandler  MemoryHandler  ChatHandler ║
║                                                         │                ║
║                                                  CommandResult           ║
║                                                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  [資料來源層]              [適配層]             [核心 Pipeline 層]        ║
║                                                                          ║
║  Instagram    ──→  InstagramAdapter  ──┐                                ║
║  LINE         ──→  LineAdapter       ├──→ NormalizedMessage[]           ║
║  JSON / CSV   ──→  FileImportAdapter ─┘    (統一訊息模型)                ║
║  Telegram     ──→  TelegramAdapter（未來）       │                       ║
║                          ↑                      ▼                        ║
║               SourceAdapterFactory     IngestionPipeline                 ║
║               Registry.create()    ┌───────┼───────┐                   ║
║               （Registry 查表）    Extractor Clusterer Consolidator      ║
║                                    (事件提煉) (向量分群) (無損融合)       ║
║                                    └───────┼───────┘                   ║
║                                       Summarizer                         ║
║                                     (摘要卡生成)                         ║
║                                            │                             ║
║  [儲存層]                                  ▼                             ║
║  SQLite ←──────── save_messages() / save_events()                        ║
║  ChromaDB ←─────── vector_store.add_chunks()                             ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## 3. 模組目錄結構

```
app/
├── bot/
│   ├── poller.py                    # L0：端到端訊息輪詢與派發
│   └── router.py                    # L1：文字 → CommandParser Registry → CommandBus
│
├── commands/
│   ├── base.py                      # BaseCommand, CommandResult, CommandHandler
│   ├── bus.py                       # CommandBus（Registry 查表派發）
│   ├── commands.py                  # 所有 Command @dataclass（純 DTO 層）
│   ├── parsers.py                   # CommandParser Registry（各指令解析器，無 if-else）
│   ├── handlers.py                  # 薄層 re-export（向後相容）
│   └── handlers/
│       ├── __init__.py              # CommandService Facade + create_default_command_bus
│       ├── contact.py               # ContactHandler（Track/Select/List/Status/Untrack/Nickname）
│       ├── memory.py                # MemoryHandler（Card/Me/Sync/RebuildVectors/Summary）
│       ├── chat.py                  # ChatHandler（AI 聊天 + 非同步記憶萃取）
│       ├── help.py                  # HelpHandler
│       └── follower.py              # FollowerHandler（Follower 監控，預留）
│
└── sources/
    ├── __init__.py                  # 匯出 BaseSourceAdapter, NormalizedMessage, SourceAdapterFactory
    ├── base.py                      # 抽象介面 + 統一資料模型（L2）
    ├── factory.py                   # Registry Pattern 工廠（L2）
    ├── instagram.py                 # InstagramAdapter（L2）+ 自我註冊
    └── file_import.py               # FileImportAdapter（L2）+ 自我註冊
```

---

## 4. NormalizedMessage — 統一資料模型

### 4.1 欄位定義

```python
@dataclass
class NormalizedMessage:
    # ── 核心欄位（Pipeline 直接使用，不輕易更動）──
    external_id: str        # 來源平台訊息唯一 ID
                            #   Instagram: item.id (str)
                            #   LINE:      message_id
                            #   CSV:       row index (str)
    sender: str             # "me" | "them"  (必填，只能二擇一)
    content: str            # 純文字內容（非文字訊息填 "[圖片/貼圖/非文字訊息]"）
    sent_at: str            # ISO 8601 時間字串 (e.g. "2026-09-17T01:00:00+08:00")
    source_type: str        # "instagram" | "line" | "file_import" | "telegram"

    # ── 可選通用欄位（已知跨平台通用，從 extras 升格）──
    raw_media_type: str = "text"   # "text" | "image" | "sticker" | "audio" | "video"

    # ── 擴充逃生門（平台專屬資訊，不影響 Pipeline 邏輯）──
    extras: Dict[str, Any] = field(default_factory=dict)
```

### 4.2 各平台 extras 參考範例

```python
# Instagram
extras = {
    "thread_id": "340282366841710300949128000000000000",
    "is_seen": True,
    "reactions": ["❤️"],
    "reply_to_item_id": None,
}

# LINE
extras = {
    "group_id": "Cxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "reply_to": "msg_998",
    "emoji": ["(笑)"],
}

# file_import（CSV / JSON）
extras = {
    "source_file": "line_export_2024.csv",
    "row_index": 142,
    "original_format": "LINE_TEXT_EXPORT",
}
```

### 4.3 欄位升格路徑

```
【升格規則】
extras["reply_to"] 僅 LINE 使用
         │
         ▼ 若 Telegram、Instagram 等也支援並需在 Pipeline 中使用
Optional[str] reply_to = None 升格為正式欄位
         │
         ▼ 舊 Adapter 不用動（有預設值 None）
只更新 Pipeline 中消費此欄位的邏輯
```

### 4.4 `__post_init__` 驗證規則

```
NormalizedMessage 建立時自動驗證：
  external_id 不可為空字串
  sender 必須為 "me" 或 "them"
  sent_at 必須為有效 ISO 8601 格式
  → 驗證失敗拋出 ValueError（在 Adapter 端提早爆錯，不污染 Pipeline）
```

---

## 5. BaseSourceAdapter — 抽象基底介面

### 5.1 介面定義

```python
class BaseSourceAdapter(ABC):
    source_type: str                    # 類別屬性，由子類宣告

    @abstractmethod
    def fetch_messages(
        self,
        target: str,                    # 對象帳號 / 對話 ID / 檔案路徑
        amount: int = 0,                # 0 = 無上限
        progress_callback = None,
    ) -> List[NormalizedMessage]:
        """拉取訊息並轉換為 NormalizedMessage 列表。"""

    @abstractmethod
    def get_self_id(self) -> str:
        """返回「我」的識別 ID，用於判斷 sender = 'me' | 'them'。"""
```

### 5.2 各 Adapter 對應關係

```
BaseSourceAdapter (ABC)
        │
        ├── InstagramAdapter
        │       source_type = "instagram"
        │       fetch_messages(target=username, amount=...)
        │           → ig_client.get_thread_by_username(username)
        │           → ig_client.get_thread_messages(thread_id, amount)
        │           → [NormalizedMessage(..., source_type="instagram")]
        │       get_self_id()
        │           → str(ig_client.client.user_id)
        │
        ├── FileImportAdapter
        │       source_type = "file_import"
        │       fetch_messages(target=file_path, amount=...)
        │           → 解析 JSON / CSV
        │           → [NormalizedMessage(..., source_type="file_import")]
        │       get_self_id()
        │           → config 中設定的 self_identifier (預設 "me")
        │
        └── (未來) LineAdapter / TelegramAdapter / ...
                依相同介面實作，Pipeline 完全不感知差異
```

---

## 6. SourceAdapterFactory — Registry Pattern 工廠

### 6.1 設計原則

採用 **Registry Pattern**（而非 if-else Factory），符合 Open-Closed Principle：
- `factory.py` 本身不需修改即可擴充新 Adapter
- 每個 Adapter 在自己模組末尾呼叫 `SourceAdapterFactory.register()` 自我註冊

### 6.2 流程圖

```
SourceAdapterFactory.create(source_type, **kwargs)
              │
              ▼
     查表 _registry.get(source_type)
              │
              ├─ (未找到) ──► raise ValueError，列出已註冊清單
              │
              ▼ (找到 adapter_cls)
     adapter_cls(**kwargs) 實例化
              │
              ▼
     [BaseSourceAdapter 實例]
```

### 6.3 自我註冊機制

各 Adapter 在模組末尾自行呼叫：

```python
# instagram.py 末尾
from app.sources.factory import SourceAdapterFactory
SourceAdapterFactory.register("instagram", InstagramAdapter)

# file_import.py 末尾
SourceAdapterFactory.register("file_import", FileImportAdapter)
SourceAdapterFactory.register("file", FileImportAdapter)    # 別名
SourceAdapterFactory.register("local", FileImportAdapter)   # 別名
```

### 6.4 呼叫範例

```python
# Instagram 流程（在 poller.py 中）
adapter = SourceAdapterFactory.create(
    "instagram",
    ig_client=self.main_ig,
)
info = ingestion.run_full_ingestion(adapter, target_username)

# 本地 LINE 聊天紀錄匯入
adapter = SourceAdapterFactory.create(
    "file_import",
    path="/path/to/line_chat_export.json",
    format="line_json",
    self_id="張呈義",
)
info = ingestion.run_full_ingestion(adapter, "朋友A")
```

---

## 7. IngestionPipeline 改動界面

`run_full_ingestion` 與 `sync_messages` 的簽名更新如下：

```
【改動前】
run_full_ingestion(ig_client: IGClient, target_username: str, ...)

【改動後】
run_full_ingestion(adapter: BaseSourceAdapter, target: str, ...)

【改動範圍】
  ingestion_service.py 內部：
    ig_client.get_thread_by_username(...)  →  adapter.fetch_messages(target, ...)
    ig_client.client.user_id              →  adapter.get_self_id()
    NormalizedMessage 轉換邏輯移出 Pipeline，由各 Adapter 自行負責
```

---

## 8. FileImportAdapter — 支援格式規範

### 8.1 JSON 格式（通用）

```json
{
  "self_id": "張呈義",
  "messages": [
    {
      "id": "1",
      "sender_name": "張呈義",
      "content": "你好",
      "timestamp_ms": 1726502400000
    },
    {
      "id": "2",
      "sender_name": "朋友A",
      "content": "嗨！",
      "timestamp_ms": 1726502460000
    }
  ]
}
```

### 8.2 CSV 格式（通用）

```csv
id,sender,content,sent_at
1,me,你好,2026-09-17T01:00:00
2,them,嗨！,2026-09-17T01:01:00
```

### 8.3 LINE 聊天記錄匯出格式（`.txt` 自動解析）

```
[LINE] 2024/01/15  與「朋友A」的聊天記錄

2024/01/15 星期一
10:00  張呈義  你好
10:01  朋友A  嗨！
```

---

## 9. 如何新增一個新的 Source Adapter

以 **Telegram** 為例，完整步驟如下：

### Step 1 — 建立 Adapter 檔案

```
app/sources/telegram.py
```

```python
"""
telegram.py — Telegram Source Adapter

PIPELINE (L2):
  TelegramAdapter.fetch_messages(chat_id, amount)
       │
       ├── telegram_client.get_history(chat_id, limit=amount)
       │        │
       │        └── [TelegramMessage(id, sender_id, text, date)]
       │
       └── 轉換 → [NormalizedMessage(
                      external_id=str(msg.id),
                      sender="me" | "them",
                      content=msg.text or "[非文字訊息]",
                      sent_at=msg.date.isoformat(),
                      source_type="telegram",
                      extras={"chat_id": chat_id}
                  )]
"""
from app.sources.base import BaseSourceAdapter, NormalizedMessage

class TelegramAdapter(BaseSourceAdapter):
    source_type = "telegram"

    def __init__(self, telegram_client, self_user_id: str):
        self._client = telegram_client
        self._self_id = self_user_id

    def get_self_id(self) -> str:
        return self._self_id

    def fetch_messages(self, target, amount=0, progress_callback=None):
        raw = self._client.get_history(target, limit=amount or None)
        result = []
        for msg in raw:
            sender = "me" if str(msg.sender_id) == self._self_id else "them"
            result.append(NormalizedMessage(
                external_id=str(msg.id),
                sender=sender,
                content=msg.text or "[非文字訊息]",
                sent_at=msg.date.isoformat(),
                source_type="telegram",
                extras={"chat_id": target},
            ))
        return result
```

### Step 2 — 在 Adapter 末尾自我註冊

在 `telegram.py` **末尾**加入自我註冊，`factory.py` 不需要改動：

```python
# telegram.py 末尾
from app.sources.factory import SourceAdapterFactory  # noqa: E402
SourceAdapterFactory.register("telegram", TelegramAdapter)
```

### Step 3 — 新增測試

```
tests/sources/test_telegram_adapter.py
```

驗證 `TelegramAdapter.fetch_messages()` 輸出符合 `NormalizedMessage` 規範即可。

**Pipeline、IngestionService、CommandBus 均不需要任何修改。**

---

## 10. ASCII Flowchart 分層規範

本專案所有 Python 檔案頂部 docstring **必須**包含對應層級的 ASCII Flowchart。

### 層級定義

```
Layer  │ 對象                                  │ 描述層次
───────┼───────────────────────────────────────┼──────────────────────────────
L0     │ app/bot/poller.py                     │ 使用者輸入 → AI 回覆的完整路徑
───────┼───────────────────────────────────────┼──────────────────────────────
L1     │ app/bot/router.py                     │ 文字解析 → CommandBus 派發路徑
       │ app/services/ingestion_service.py     │ 跨模組協作（Service 協調各子管線）
       │ app/commands/handlers/__init__.py     │ CommandService Facade 聚合路徑
───────┼───────────────────────────────────────┼──────────────────────────────
L2     │ app/commands/parsers.py               │ CommandParserRegistry 查表流程
       │ app/commands/bus.py                   │ Command 查表 → Handler 執行 → 結果回傳
       │ app/commands/handlers/contact.py      │ 聯絡人管理各操作步驟
       │ app/commands/handlers/memory.py       │ 記憶庫與摘要各操作步驟
       │ app/commands/handlers/chat.py         │ AI 聊天 + 非同步記憶萃取步驟
       │ app/sources/factory.py                │ Registry 查表 → Adapter 實例化
       │ app/sources/instagram.py              │ IG 訊息 → NormalizedMessage 步驟
       │ app/sources/file_import.py            │ 檔案解析 → 格式偵測 → 轉換步驟
───────┼───────────────────────────────────────┼──────────────────────────────
L3     │ app/pipelines/extraction.py           │ 切塊演算法 → Batch 提煉 → SQLite 增量寫入
       │ app/pipelines/clustering.py           │ 向量取得 → Complete Linkage → 分群輸出
       │ app/pipelines/consolidation.py        │ 群批次 → LLM 融合 → 去重輸出
       │ app/pipelines/summarization.py        │ 近期對話組裝 → Prompt → 摘要卡輸出
```

### Flowchart 格式規範

```python
"""
檔名 — 簡短一行功能說明

PIPELINE (Lx):
  [輸入] ─動作→ 處理節點A
                    │
              ┌─────┴─────┐
           分支A         分支B
              │             │
           輸出A          輸出B
                    │
                 [輸出]
"""
```

- 使用 `─`, `│`, `┌`, `┐`, `└`, `┘`, `┤`, `├`, `┼`, `▼`, `→` 等 box-drawing 字元
- 縮排對齊（輸入在最頂，輸出在最底，條件分支明確標示）
- Flowchart **只描述此檔案的職責範圍**，不向上展開父層的細節
- 高階 (L0/L1) 檔案 Flowchart **不超過 25 行**，低階 (L2/L3) **不超過 35 行**

---

## 11. 相關文件

| 文件 | 描述 |
|---|---|
| [施工文件](./IG-AI陪聊機器人-施工文件.md) | 整體系統設計說明 |
| [RAG 01 — 事件提煉](./rag/01_微觀事件提煉與節流.md) | EventExtractor 管線細節 |
| [RAG 02 — 向量分群](./rag/02_時序語意向量分群.md) | EventClusterer 演算法 |
| [RAG 03 — 無損融合](./rag/03_同質無損融合去重.md) | EventConsolidator 設計 |
| [RAG 04 — 向量儲存](./rag/04_Chroma向量儲存架構.md) | ChromaDB 存取結構 |
| [RAG 05 — 記憶組裝](./rag/05_共享檢索與Prompt組裝.md) | MemoryManager 與 RAG 組裝 |
