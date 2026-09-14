# IG AI 陪聊機器人 — 施工文件

版本：v0.3 架構重構與 RAG 效率革命
最後更新：2026-09-15

---

## 1. 專案目標

打造一個個人使用的 IG 聊天機器人帳號，使用者可以直接在手機 Instagram App 裡，用私訊的方式跟這個 AI 討論「某個特定對象傳來的訊息該怎麼回」。AI 需要具備：

- 對特定對象的歷史對話脈絡（RAG / 分層記憶）
- 近期訊息的即時 context
- 像朋友一樣的對話語氣，而非制式分析工具
- 可透過指令切換「目前在討論的對象」

**非目標（Out of Scope）**：

- 不自動回覆對方（前男友/曖昧對象）的訊息，發送永遠由使用者手動操作
- 不做大規模、多帳號、多使用者的服務
- 不需要高可用性（HA）、不需要橫向擴展

---

## 2. 重要技術決策：不走 Meta 官方 API

本專案**不使用 Instagram Graph API / Messenger Platform**，改用帳號密碼直接登入的方式（透過 `instagrapi` 這類模擬 IG 私有 App API 的函式庫）操作兩個帳號：

| 帳號     | 角色                   | 登入方式                                        |
| -------- | ---------------------- | ----------------------------------------------- |
| 主帳號   | 使用者本人平常用的帳號 | 帳密登入，用來讀取跟目標對象的聊天紀錄          |
| Bot 帳號 | AI 陪聊機器人          | 帳密登入，用來接收使用者指令/聊天、回傳 AI 回覆 |

**這個決定的風險提醒（務必知悉）**：

- 這不是官方支援的整合方式，違反 IG 使用條款，兩個帳號都有被要求異常驗證、限制功能、甚至停權的風險。
- 沒有 SLA、沒有官方保證，IG 前端/私有 API 隨時可能變動導致函式庫失效。
- 因應方式：登入後**持久化 session**（見第 4 節），避免頻繁重新登入；所有操作間加隨機延遲；不要做高頻率輪詢；把這個服務定位成「你自己手動觸發為主」的個人工具，而不是 24 小時無人值守的常駐機器人。

---

## 3. 使用情境（User Flow）

### 3.1 指令情境

```
使用者手機 IG App（用主帳號）
      │
      │ 傳訊息給「AI 閨蜜」bot 帳號： track alex_1234
      ▼
Bot 帳號的訊息輪詢服務偵測到新訊息
      │
      ▼
指令解析器判斷為 track 指令
      │
      ▼
【觸發 Ingestion Pipeline】（詳見第 6 節）
  - 用主帳號 session 抓取與 alex_1234 近一個月的聊天紀錄
  - 清洗、分段、embedding，寫入向量資料庫
  - 生成初始關係摘要卡
      │
      ▼
Bot 帳號回覆：「已開始追蹤 alex_1234，匯入 87 則訊息，摘要卡已建立」
```

### 3.2 一般聊天情境

```
使用者：select alex_1234
Bot：目前作用對象已切換為 alex_1234

使用者：他剛剛傳「隨便啊」給我，這什麼意思，我要怎麼回
      │
      ▼
讀取 bot_state.active_contact_id → alex_1234
      │
      ├─ 撈 contacts.summary_card（關係摘要卡）
      ├─ 撈 messages 最近 20-30 則（近期原始上下文）
      └─ 用這句「隨便啊」做語意搜尋，撈向量資料庫中最相關的歷史 chunk
      │
      ▼
組合成 Prompt → 呼叫 Gemini API
      │
      ▼
Bot 回覆：先接住情緒／分析語氣／給 2-3 種回覆版本
```

---

## 4. 系統架構

### 4.1 高層架構圖

```
┌───────────────────────────────────────────────────────────┐
│                 使用者手機 IG App（主帳號）                    │
└──────────────────────────────┬──────────────────────────────┘
                                │ 傳訊息 / 指令
                                ▼
┌───────────────────────────────────────────────────────────┐
│              Bot 帳號（instagrapi session）                  │
│              由本地/小型主機服務輪詢新訊息                       │
└──────────────────────────────┬──────────────────────────────┘
                                ▼
┌───────────────────────────────────────────────────────────┐
│                     本地 / 小型主機 App（Python）             │
│                                                             │
│  app/clients/       ── 外部通訊 (Instagram Client, GeminiKeyRing)   │
│  app/bot/           ── 入口交互 (指令 Router, Poller, 白名單 Auth)   │
│  app/pipelines/     ── 業務管線 (事件提煉, 向量分群, 批次融合, 摘要)  │
│  app/services/      ── 業務調度 (MemoryManager, LLMService)        │
│  app/storage/       ── 本地存儲 (SQLite Repositories, ChromaStore)  │
│  app/core/          ── 系統基礎 (Config, Fernet Security)          │
│                                                             │
└──────────┬───────────────────────────────┬─────────────────┘
           ▼                               ▼
  ┌─────────────────┐             ┌─────────────────────┐
  │  SQLite 資料庫    │             │  Chroma 向量資料庫    │
  └─────────────────┘             └─────────────────────┘
           │
           ▼
  ┌─────────────────────┐
  │  Gemini API KeyRing │
  └─────────────────────┘
```

### 4.2 模組職責說明

| 模組目錄 | 主要檔案 | 職責說明 | 主要依賴 |
| :--- | :--- | :--- | :--- |
| **`app/clients/`** | `gemini.py`, `instagram.py` | 專責外部服務通訊：多組 API Key 輪換與 429 冷卻跳過、IG 私訊與抓取操作 | `google-genai`, `instagrapi` |
| **`app/pipelines/`** | `extraction.py`, `clustering.py`, `consolidation.py`, `summarization.py` | 專責業務管線：對話滑動窗口切塊與事件提煉、時序 Complete Linkage 分群、多 Cluster 批次融合、人物卡與全景復盤 | 專屬 Prompt 範本, `GeminiClient` |
| **`app/storage/`** | `db.py`, `repositories.py`, `chroma_store.py` | 本地存儲與持久化：SQLite 連線與單一事實來源、純本地 Chroma 雙軌集合操作 | `sqlite3`, `chromadb` |
| **`app/services/`** | `memory_service.py`, `llm_service.py`, `ingestion_service.py` | 領域服務層：分層記憶多路檢索與共享向量組裝、高階流程協調器 | 各 pipelines, repositories |
| **`app/bot/`** | `router.py`, `poller.py`, `auth.py` | 機器人交互層：宣告式指令分派與別名路由、長連接/輪詢監聽、白名單過濾 | `instagrapi` |
| **`app/core/`** | `config.py`, `security.py` | 核心基礎設施：Pydantic 環境變數管理、Fernet Session 對稱加解密 | `pydantic-settings`, `cryptography` |

---

## 5. 帳號登入與 Session 持久化

### 5.1 登入流程（含 2FA / 驗證碼）

```
啟動 session_manager.login(account_type)
      │
      ▼
是否已有存好的 session 檔？
      │
   ┌──┴──┐
   有       沒有
   │         │
   ▼         ▼
載入 session   用帳密登入
   │         │
   │         ▼
   │    IG 要求驗證碼（簡訊/Email/2FA App）？
   │         │
   │      ┌──┴──┐
   │      是      否
   │      │       │
   │      ▼       │
   │  程式暫停，   │
   │  透過 CLI     │
   │  prompt 讓    │
   │  使用者輸入   │
   │  驗證碼       │
   │      │       │
   │      ▼       ▼
   │   驗證成功 → 登入完成
   │      │
   ▼      ▼
存/更新 session 檔（加密後存於本地）
      │
      ▼
回傳可用的 client 物件
```

**設計重點**：

- 使用 `instagrapi` 的 `client.dump_settings()` / `client.load_settings()` 機制，把登入後的 session（含 cookies、device 資訊）序列化成 JSON 存到本地檔案，之後啟動程式優先載入既有 session，避免每次都重新走帳密登入（帳密登入頻率越高，風險越高）。
- 兩個帳號（主帳號、bot 帳號）**分開存 session 檔**，並各自綁定固定的虛擬 device 資訊（instagrapi 支援指定 `device_settings`），讓每次登入的裝置指紋一致，降低被判定異常的機率。
- 2FA 驗證碼輸入：因為是本地個人使用的 CLI 工具，登入階段直接用 `input()` 讓你在終端機貼上收到的驗證碼即可，不需要額外做網頁介面。
- Session 檔存放路徑：`data/sessions/main_account.json`、`data/sessions/bot_account.json`，兩者都要進 `.gitignore`。
- 建議對 session 檔案內容做**本地加密**（例如用 `cryptography` 套件的 Fernet，金鑰存在 `.env` 裡的 `SESSION_ENCRYPTION_KEY`），避免明文 session 檔外流就等於帳號被盜。
- Session 失效處理：如果偵測到 API 呼叫回傳「需要重新登入」的錯誤，程式應該捕捉這個例外，刪除失效的 session 檔，重新走一次登入流程（含可能的 2FA），而不是直接崩潰。

### 5.2 `session_manager.py` 介面設計（草案）

```python
class SessionManager:
    def login(self, account_type: str) -> Client:
        """account_type: 'main' or 'bot'
        優先載入本地 session，失敗才走帳密+2FA 登入流程
        """

    def _load_session(self, account_type: str) -> Client | None: ...

    def _interactive_login(self, account_type: str) -> Client:
        """呼叫 instagrapi 登入，若觸發 2FA challenge，
        透過 input() 提示使用者輸入驗證碼並重試
        """

    def _save_session(self, account_type: str, client: Client) -> None:
        """dump_settings() 後加密寫入本地檔案"""
```

---

## 6. 指令系統設計

`command_router.py` 在每則新訊息進來時，先判斷是否符合指令格式（例如以特定關鍵字開頭），是的話分派到對應處理器，否則進入一般聊天模式。

| 指令                        | 功能                                                           |
| --------------------------- | -------------------------------------------------------------- |
| `track [IG ID]`           | 開始追蹤這個帳號跟主帳號的對話，觸發 RAG ingestion（近一個月） |
| `select [IG ID]`          | 切換「目前作用中」的對象，之後聊天預設載入這個人的 context     |
| `status`                  | 顯示目前 selected 對象、上次同步時間、摘要卡最後更新時間       |
| `refresh_summary [IG ID]` | 手動觸發重新生成該對象的摘要卡                                 |
| `list`                    | 列出目前所有 tracked 的對象與其狀態                            |
| `untrack [IG ID]`（選用） | 停止追蹤，但不刪除既有資料                                     |

### 6.1 `bot_state` 狀態表

因為只有你一個人使用，狀態管理不需要 session/多使用者機制，一張表存「目前作用中對象」即可：

```sql
CREATE TABLE bot_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- 永遠只有一筆
    active_contact_id INTEGER,
    updated_at DATETIME
);
```

---

## 7. RAG Ingestion Pipeline

### 7.1 `track` 觸發的完整流程

```
track [IG ID]
      │
      ▼
用主帳號 session 找到與該 IG ID 的 thread
      │
      ▼
分頁抓取近一個月的訊息（每頁抓取間加隨機延遲，避免短時間大量請求）
      │
      ▼
寫入 contacts 表（若不存在則新建，狀態設為 tracked）
      │
      ▼
寫入 messages 表
  （去重 key：IG 原始訊息 item_id，避免重複 ingestion 造成向量庫髒資料）
      │
      ▼
【Ingestion 子流程】
  1. 清洗：
     - 過濾系統訊息（例如「已讀」「開始聊天」等非對話內容）
     - 貼圖/圖片/語音訊息轉為 placeholder 文字描述（例如「[貼圖]」「[圖片]」）
  2. 分段（chunking）：
     - 以「天」為單位切 chunk；若單日訊息量過大（例如 >50 則），
       再依訊息數量切成多個 chunk（例如每 20 則一個 chunk）
     - chunk 內容保留說話者標記（「我：」/「對方：」），避免語意斷裂
  3. Embedding：
     - 呼叫 embedding model 產生向量
  4. 寫入向量資料庫（Chroma）：
     - metadata: contact_id、chunk 起訖時間、原始文字全文
  5. 生成初始摘要卡：
     - 把整月訊息（或分批，視 token 上限）丟給 Claude API，
       萃取人物個性、互動模式、重要事件
     - 寫入 contacts.summary_card，記錄 summary_updated_at
      │
      ▼
回覆使用者：「已開始追蹤 [IG ID]，匯入 N 則訊息，摘要卡已建立」
```

### 7.2 後續增量同步

`track` 只處理初次匯入。之後若要讓已追蹤的對象持續更新，建議：

- 提供一個可手動觸發的 `sync` 指令（或排程），只抓取「比目前 DB 最新一筆訊息時間更新」的訊息
- 新訊息一樣走過清洗 → chunking → embedding → 寫入向量庫的流程，**不需要重跑舊資料**
- 每次同步後檢查是否達到摘要卡更新門檻（見第 8 節）

---

## 8. 分層記憶架構與事件 RAG（v0.3 革命）

採用「近期原始層 → 事件條目 RAG 層 → 雙軌摘要層」三層記憶，徹底解決破碎字句雜訊與 Token 暴增問題：

| 層級                      | 內容                                                                 | 儲存與格式                                                        |
| ------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------- |
| **近期原始層**            | 最近 20–30 則原始訊息，逐字保留                                      | SQLite `messages` 表                                              |
| **事件記憶 RAG 層**       | **[v0.3]** 由 LLM 從對話批次提煉的客觀事實條目（含日期）             | ChromaDB `chat_events` 集合（768 維度，支援共享 Query Embedding） |
| **日常輕量卡**            | **[v0.3]** 限制 300–500 字之核心人物與相處狀態（注入日常聊天 Prompt） | SQLite `contacts.summary_card`                                    |
| **全景深度長文**          | **[v0.3]** 7 大章節、數千字全景關係復盤長文（`card full` 查看，不注入聊天） | SQLite `contacts.full_history_summary`                            |

### 8.1 事件記憶 RAG（Event-based Memory RAG）
- **揚棄原始碎句**：傳統 RAG 將破碎口語（如「？？？」、「哈哈哈哈」）直接切塊 Embedding，資訊密度極低且檢索充滿雜訊。
- **批次事件萃取**：每 30~50 則對話由 LLM（優先調用 Lite 模型池）透過 `extract_events.txt` 提煉為 2~4 則高密度時間事實（例如：`[2026-08-18] 兩人相約夜市吃德克士，分享音樂與室友生活`）。
- **共享單次 Query Embedding**：在 `MemoryService` 檢索時，單次對話僅發送 1 次 Embedding API 請求，計算出 768 維向量後同時並行檢索 Contact Event、Self、以及暱稱跨對象庫，徹底消除重複延遲。

### 8.2 雙軌摘要架構與更新機制
1. **日常輕量卡（`summary_card`）**：嚴格壓制在 300~500 字，專供即時聊天的 System Prompt，確保回覆速度在 2~3 秒內。
2. **全景復盤長文（`full_history_summary`）**：儲存 7 大面向深層分析，供使用者以 `card full` 隨時手動檢閱。
3. **分流指令**：
   - `card`：調閱日常輕量卡。
   - `card full`：調閱全景長文。
   - `summarize_history`：同時生成全景長文與 400 字日常輕量卡。

---

## 9. 資料庫設計（SQLite）

### 9.1 `contacts`

| 欄位                       | 型別       | 說明                                              |
| -------------------------- | ---------- | ------------------------------------------------- |
| id                         | INTEGER PK | 主鍵                                              |
| ig_account_id              | TEXT       | 對方的 IG 帳號 ID/username                        |
| display_name               | TEXT       | 使用者對這個對象的稱呼                            |
| relationship_note          | TEXT       | 使用者自訂備註                                    |
| status                     | TEXT       | `tracked` / `untracked`                           |
| summary_card               | TEXT       | 日常輕量關係摘要卡（300-500 字）                  |
| summary_updated_at         | DATETIME   | 摘要卡最後更新時間                                |
| full_history_summary       | TEXT       | **[v0.3]** 全景深度歷史復盤長文（7 大章節）       |
| full_history_updated_at    | DATETIME   | **[v0.3]** 全景長文最後更新時間                   |
| new_messages_since_summary | INTEGER    | 自上次摘要後累積的新訊息數，用於觸發增量更新      |
| last_synced_at             | DATETIME   | 上次同步聊天紀錄的時間                            |

### 9.2 `messages`

| 欄位                     | 型別        | 說明                                     |
| ------------------------ | ----------- | ---------------------------------------- |
| id                       | INTEGER PK  |                                          |
| contact_id               | INTEGER FK  |                                          |
| ig_item_id               | TEXT UNIQUE | IG 原始訊息 ID，用於去重                 |
| sender                   | TEXT        | `me` 或 `them`                       |
| content                  | TEXT        | 訊息文字內容（非文字訊息存 placeholder） |
| sent_at                  | DATETIME    | 訊息原始時間                             |
| ingested_to_vector_store | BOOLEAN     | 是否已完成向量化寫入                     |
| created_at               | DATETIME    | 匯入本地 DB 的時間                       |

### 9.3 `bot_state`

見第 6.1 節。

### 9.4 `bot_conversations`（選用）

| 欄位       | 型別       | 說明                     |
| ---------- | ---------- | ------------------------ |
| id         | INTEGER PK |                          |
| contact_id | INTEGER FK | 這次討論關於哪個對象     |
| role       | TEXT       | `user` / `assistant` |
| content    | TEXT       | 對話內容                 |
| created_at | DATETIME   |                          |

> 讓 AI 記得「上次我們討論到哪、你打算怎麼回」，而不只是記得對方傳了什麼。

---

## 10. Prompt 設計骨架

```
[System Prompt]
你是使用者的好朋友，個性溫暖、直接、有點犀利，了解使用者跟「{display_name}」
之間的所有互動歷史。

這是你對這個人的認識（關係摘要卡）：
{summary_card}

以下是跟這個人相關、可能有幫助的過去對話片段（依語意相關性排序）：
{RAG 搜尋結果 chunks}

原則：
1. 使用者情緒上來的時候，先接住情緒，不用急著分析或講道理。
2. 使用者問「這句話什麼意思」「我該怎麼回」時，才切換成實際分析模式。
3. 給建議時，提供 2–3 種不同語氣的版本，並簡短說明取捨，而非替使用者決定。
4. 不要重複空泛安慰，要具體針對訊息內容討論。

[近期上下文]
{最近 20-30 則對方與使用者的訊息，按時間排序}

[使用者現在說]
{使用者這次傳給 bot 的內容}
```

---

## 11. 專案資料夾結構（v0.3 分層模組化架構）

```
bestieAI/
├── app/
│   ├── core/                  # 核心基礎設施
│   │   ├── config.py          # Pydantic Settings 配置、模型清單與常數
│   │   ├── rate_limit.py      # IG/Gemini 限速、防風控延遲、指數退避裝飾器
│   │   └── security.py        # 白名單鑑權裝飾器、Session 加密金鑰管理
│   ├── storage/               # 儲存層（封裝底層持久化）
│   │   ├── db.py              # SQLite 連線管理與結構遷移
│   │   ├── repositories.py    # ContactRepository, MessageRepository, BotStateRepository
│   │   └── vectors.py         # ChromaDB 向量檢索（Batch API + 768 維度 + 共享 Query 向量）
│   ├── services/              # 業務領域服務層
│   │   ├── ig_service.py      # 高階 IG 操作與雙帳號 Session 生命週期封裝
│   │   ├── llm_service.py     # Gemini 多模型容錯陣列、日誌、結構化提煉
│   │   ├── memory_service.py  # 分層記憶組裝（共享單次 Query Embedding 檢索）
│   │   ├── ingestion_service.py # 歷史對話清洗、事件萃取（Event Extraction）與批次向量化
│   │   └── session_service.py # Session 密鑰管理與持久化操作
│   ├── bot/                   # 機器人交互層
│   │   ├── router.py          # 宣告式指令路由（@command_handler）、分組 Help、card full
│   │   └── poller.py          # MQTT 即時推播監聽與背景隊列 Worker
│   └── prompts/               # 提示詞範本目錄（依職責分類）
│       ├── chat/
│       │   └── companion.txt  # 即時閨蜜陪聊核心 Prompt
│       ├── events/
│       │   ├── extract.txt    # 微觀事實事件提煉範本
│       │   ├── extract_self.txt # 使用者自身事實萃取範本
│       │   └── consolidate_batch.txt # 多群組批次無損融合
│       └── summary/
│           ├── concise.txt    # 日常輕量關係摘要卡範本（300-500字）
│           ├── full.txt       # 全景歷史深度復盤長文範本（7 大章節）
│           └── summary.txt    # 舊版全篇人物摘要卡（相容備援）
├── data/                      # 本地持久化資料（.gitignore）
│   ├── app.db                 # SQLite 資料庫（原始對話、聯絡人、摘要）
│   ├── chroma/                # ChromaDB 向量資料庫（事件記憶與自我記憶）
│   └── sessions/              # 加密 session（main_account.json, bot_account.json）
├── tests/                     # 單元與整合測試套件（57 項測試全數通過）
├── docs/                      # 架構與施工文件
├── main.py                    # 系統進入點
├── pyproject.toml             # uv 依賴設定檔
└── .env                       # 本地環境變數（.gitignore）
```

---

## 12. Secrets 與環境變數

`.env.example`：

```
MAIN_ACCOUNT_USERNAME=
MAIN_ACCOUNT_PASSWORD=
BOT_ACCOUNT_USERNAME=
BOT_ACCOUNT_PASSWORD=
SESSION_ENCRYPTION_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
DB_PATH=./data/app.db
CHROMA_PATH=./data/chroma
```

`.gitignore` 需包含：

```
.env
data/*.db
data/chroma/
data/sessions/
__pycache__/
.venv/
```

> 密碼直接放在 `.env` 已是相對風險較高的做法，務必確保 `.env` 不進版控、本機磁碟有加密（例如 macOS FileVault），且不要在共用電腦上跑這個服務。

---

## 13. 部署與維運（不使用 Docker）

單一 Python 程式 + SQLite + Chroma（本地檔案模式）+ 呼叫 Claude API，用 `venv` 管理套件即可達到「好維護」的目的。

| 需求                                 | 方案                                                                                                  |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| 開機自動啟動、掛掉自動重啟           | macOS 用`launchd`；Linux 用 `systemd` service 檔                                                  |
| 開發階段方便看 log、重啟             | `pm2` 管理 Python 常駐程式                                                                          |
| session 過期需要人工介入（輸入 2FA） | 常駐程式偵測到需要重新登入時，記錄 log 並發通知（例如寫入本地檔案或印出提示），不要讓程式卡死等待輸入 |
| 套件版本鎖定                         | `requirements.txt` + `pip freeze`，或改用 `poetry`/`uv`                                       |

若未來想部署到雲端小主機長期運行，屆時再包一層 `Dockerfile`，屬於低成本的後續擴充。

---

## 14. 版本迭代歷程與規劃

| 版本   | 狀態   | 核心內容                                                                                                 |
| ------ | ------ | -------------------------------------------------------------------------------------------------------- |
| v0.1.0 | 已完成 | `session_service` 完成雙帳號登入 + 2FA + session 加密持久化                                             |
| v0.2.0 | 已完成 | `poller` (MQTT) + `router` 完成即時推播、狀態機切換、宣告式指令分發                                      |
| v0.3.0 | **當前** | **Clean Architecture 重構**（分層目錄化）、**RAG 效率革命**（事件記憶條目化 + 768 維度 + 共享 Query 向量）、**雙軌記憶分離**（300 字日常卡 vs 7 大章節長文）、**Lite 模型分流**（獨立 500 RPD 配額池） |
| v0.4.0 | 規劃中 | **跨對話自我全景畫像（Cross-Chat Self Profiling）**：跨對話深度分析使用者個性、溝通習慣、情緒模式與 MBTI |
| v0.5.0 | 規劃中 | 增量對話自動批次提煉（門檻 30~50 則打包）與自我畫像週期性更新機制                                         |
| v1.0.0 | 未來   | 穩定運行、各項指標滿足後發布正式版                                                                       |

**Git 慣例**：

- Commit message 用 `feat: `、`fix: `、`docs: `、`refactor: ` 前綴
- 每個版本完成後打 `git tag vX.Y.Z`
- `CHANGELOG.md` 依 [Keep a Changelog](https://keepachangelog.com/) 格式記錄每版異動

---

## 15. 風險與限制說明

| 風險                     | 說明                                                                | 因應方式                                                                                                        |
| ------------------------ | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| 非官方 API 的帳號風險    | 帳密直接登入 + 模擬私有 API，違反 IG ToS，兩帳號都有被限制/停權風險 | 持久化 session 減少重新登入次數、操作加隨機延遲、避免高頻輪詢、心理上接受這是個人實驗性工具而非長期穩定服務     |
| IG 私有 API 隨時可能變動 | `instagrapi` 等函式庫依賴逆向工程，IG 改版可能導致失效            | 訂閱該函式庫的 GitHub release，定期檢查是否有更新；程式設計上把 IG 存取邏輯集中在`ig_client.py`，方便未來替換 |
| 2FA 流程中斷常駐服務     | session 過期需要人工輸入驗證碼，若程式無人值守會卡住                | `poller` 偵測到登入失效時記錄清楚的 log/通知，不要讓整個服務掛掉，等你手動介入重新登入                        |
| 密碼與 session 外流風險  | `.env` 明文密碼、session 檔內容等同登入憑證                       | `.env`/session 檔不進版控、session 內容加密、本機磁碟全碟加密                                                 |
| 資料隱私                 | 儲存的是私人對話紀錄 + 向量化的語意內容                             | 全部本地儲存，未來若要上雲端主機需額外評估加密與存取控制                                                        |

---

## 16. 待確認事項（Open Questions）

- [ ] `poller` 的輪詢頻率設多少合適？（頻率越低越安全，但回覆延遲越高，需要抓一個平衡點）
- [X] embedding model 要用哪一個？（已確認使用 Google Gemini `gemini-embedding-2` 模型，固定 768 維度）
- [ ] 摘要卡的增量觸發門檻（30~50 則）是否合理，要不要依對象聊天頻率動態調整？
- [ ] 是否需要多對象同時 tracked，或先鎖定 1 個對象把整套流程跑順再擴充？

---

## 17. 核心技術抉擇與取捨（ADR）

僅記錄「具替代方案、沒有絕對對錯，但為滿足特定目標所做的工程取捨」：

### 1. 事件條目提煉 vs. 原始對話切塊
- **替代方案**：傳統 RAG 保留所有原句並以滑動視窗切塊。
- **我們的取捨**：犧牲原始碎句語氣，強制由 LLM 提煉為「帶時間戳的客觀事實條目」。
- **原因**：真實私訊充斥無語意廢話（「？？？」、「哈哈哈哈」），切塊檢索充滿雜訊且佔滿 Context；事件化雖有提煉損耗，但資訊密度提升數倍、檢索命中精準，並降低 80% 以上 Token 成本。

### 2. 雙軌摘要分離 vs. 單一動態摘要
- **替代方案**：全系統只維護一份隨時間更新的摘要。
- **我們的取捨**：硬拆為「日常輕量卡（300–500 字）」與「全景復盤長文（7 大章節）」，欄位與指令徹底分流。
- **原因**：即時聊天需要極致低延遲與低 Token；使用者復盤關係時需要數千字全貌分析。兩者需求互斥，因此透過架構分流（`card` vs `card full`），日常 Prompt 絕不載入長文。

### 3. 多模型配額分流 vs. 單一模型通吃
- **替代方案**：全系統統一使用單一主力模型。
- **我們的取捨**：即時對話走 Flash 主系列；背景提煉與摘要走 Lite 系列（3.5 / 3.1-flash-lite）。
- **原因**：Gemini 免費額度以 Model Family 各自獨立計算（各 500 RPD）。提煉工作屬結構化任務，交由 Lite 模型吃獨立 500 RPD 池，零成本享有雙倍配額，互不搶佔即時聊天額度。

### 4. 延遲批次打包 vs. 逐則即時提煉
- **替代方案**：每收到新訊息即時呼叫 LLM 提煉事實。
- **我們的取捨**：容忍記憶更新滯後，累積 30~50 則訊息或手動指令才批次打包提煉。
- **原因**：IG 私訊發送高頻且零碎，逐則提煉會瞬間打滿 RPD 並大幅增加延遲與風控風險；犧牲微小即時性換取額度安全與穩定。

### 5. 跨對話客觀萃取 vs. 日常問答主觀積累自我認知
- **替代方案**：在陪聊過程中主動詢問使用者來認識其性格。
- **我們的取捨**：直接從本地 SQLite 跨所有人歷史對話撈取 `sender == 'me'` 分析個人特質與 MBTI。
- **原因**：使用者自述通常帶有主觀偏差；而在面對不同社交對象時的真實言行與情緒反應，才能拼湊出客觀立體的自我畫像，且完全無需發出額外網路請求。

