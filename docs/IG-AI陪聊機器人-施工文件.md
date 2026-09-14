# IG AI 陪聊機器人 — 施工文件

版本：v0.2 草案
最後更新：2026-09-14

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
│  session_manager.py ── 兩個帳號的登入、2FA、session 持久化      │
│  poller.py          ── 定期輪詢 bot 帳號收件匣，取得新訊息        │
│  command_router.py  ── 解析指令（track/select/status/...）    │
│  ingestion.py        ── RAG ingestion pipeline               │
│  memory.py           ── 分層記憶讀取（近期/RAG/摘要卡）          │
│  llm.py              ── 組 Prompt、呼叫 Claude API             │
│  db.py               ── SQLite 讀寫                          │
│  vector_store.py     ── 向量資料庫封裝（Chroma）                │
│  ig_client.py        ── 封裝 instagrapi 的讀取/發送操作          │
│  config.py           ── 讀取 .env 設定                        │
│                                                             │
└──────────┬───────────────────────────────┬─────────────────┘
           ▼                               ▼
  ┌─────────────────┐             ┌─────────────────────┐
  │  SQLite 資料庫    │             │  Chroma 向量資料庫    │
  └─────────────────┘             └─────────────────────┘
           │
           ▼
  ┌─────────────────────┐
  │      Claude API       │
  └─────────────────────┘
```

### 4.2 模組職責說明

| 模組                   | 職責                                                              | 主要依賴                    |
| ---------------------- | ----------------------------------------------------------------- | --------------------------- |
| `session_manager.py` | 管理主帳號與 bot 帳號的登入、2FA 驗證碼輸入、session 序列化與還原 | instagrapi                  |
| `poller.py`          | 定期（你手動啟動的常駐程式）檢查 bot 帳號有沒有新訊息             | instagrapi                  |
| `command_router.py`  | 判斷訊息是否為指令，分派到對應的處理函式                          | —                          |
| `ingestion.py`       | 抓取歷史訊息、清洗、分段、embedding、寫入向量庫、生成摘要卡       | instagrapi, embedding model |
| `memory.py`          | 依`active_contact_id` 組合近期上下文 + RAG 搜尋結果 + 摘要卡    | —                          |
| `llm.py`             | 組裝最終 prompt、呼叫 Claude API                                  | anthropic SDK               |
| `db.py`              | `contacts` / `messages` / `bot_state` 表的存取              | sqlite3                     |
| `vector_store.py`    | chunk 的 embedding 寫入、語意搜尋                                 | chromadb                    |
| `ig_client.py`       | 封裝 instagrapi 的訊息讀取、發送                                  | instagrapi                  |

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

## 8. 分層記憶架構與摘要排程

採用「近期原始層 → 中期 RAG 層 → 長期摘要層」三層記憶，越久遠的資料壓縮程度越高，兼顧回答品質與 API 成本。

| 層級                  | 內容                                                       | 更新時機                                                                |
| --------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------- |
| **近期原始層**  | 最近 20–30 則原始訊息，逐字保留，存於`messages` 表      | 每次同步/track 有新訊息時即時更新                                       |
| **中期 RAG 層** | 依天/依段落切的 chunk + embedding，存於 Chroma，可語意搜尋 | `track` 初次 ingestion 建立；之後每次同步只對「新增部分」做 ingestion |
| **長期摘要卡**  | 高度壓縮的人物摘要：個性、相處模式、重大事件、目前關係狀態 | 見 8.1                                                                  |

### 8.1 摘要卡更新時機

1. **初次 track**：用整月訊息一次性生成初始摘要卡。
2. **累積增量觸發**：該對象「新增訊息數」累積達到門檻（建議 50 則）時，自動觸發增量更新——把「舊摘要卡 + 這批新訊息」一起丟給 LLM，請它**更新**摘要卡而非重寫，保留連續性並控制成本。
3. **時間觸發（保底機制）**：若「距離上次摘要更新超過 14 天」，即使新訊息量不多也強制更新一次，避免摘要卡過時。
4. **手動觸發**：保留 `refresh_summary` 指令，隨時可手動要求重新生成。

### 8.2 長期歷史資料管理

- 超過 3 個月的舊 chunk，建議定期（例如每月跑一次維護 job）合併壓縮成「月摘要 chunk」，取代原本較細碎的 chunk，減少向量搜尋時的雜訊。
- 原始訊息在 SQLite 中**永久完整保留、不刪除**，向量庫的壓縮只影響 RAG 搜尋層，不影響原始資料的可追溯性。
- 向量庫的搜尋範圍務必用 `contact_id` 過濾，確保不同對象的記憶不會互相污染。

---

## 9. 資料庫設計（SQLite）

### 9.1 `contacts`

| 欄位                       | 型別       | 說明                                         |
| -------------------------- | ---------- | -------------------------------------------- |
| id                         | INTEGER PK |                                              |
| ig_account_id              | TEXT       | 對方的 IG 帳號 ID/username                   |
| display_name               | TEXT       | 使用者對這個對象的稱呼                       |
| relationship_note          | TEXT       | 使用者自訂備註                               |
| status                     | TEXT       | `tracked` / `untracked`                  |
| summary_card               | TEXT       | 關係摘要卡內容                               |
| summary_updated_at         | DATETIME   | 摘要卡最後更新時間                           |
| new_messages_since_summary | INTEGER    | 自上次摘要後累積的新訊息數，用於觸發增量更新 |
| last_synced_at             | DATETIME   | 上次同步聊天紀錄的時間                       |

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

## 11. 專案資料夾結構

```
ig-ai-companion/
├── app/
│   ├── session_manager.py
│   ├── poller.py
│   ├── command_router.py
│   ├── ingestion.py
│   ├── memory.py
│   ├── llm.py
│   ├── db.py
│   ├── vector_store.py
│   ├── ig_client.py
│   ├── config.py
│   └── prompts/
│       └── system_prompt.txt
├── data/
│   ├── app.db                 # SQLite（.gitignore）
│   ├── chroma/                # 向量資料庫檔案（.gitignore）
│   └── sessions/
│       ├── main_account.json  # 加密 session（.gitignore）
│       └── bot_account.json   # 加密 session（.gitignore）
├── tests/
│   └── test_ingestion.py
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── CHANGELOG.md
└── docs/
    └── IG-AI陪聊機器人-施工文件.md   # 本文件
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

## 14. 版本迭代規劃

| 版本   | 內容                                                                         |
| ------ | ---------------------------------------------------------------------------- |
| v0.1.0 | `session_manager` 完成雙帳號登入 + 2FA + session 持久化                    |
| v0.2.0 | `poller` + `command_router` 完成，能收到訊息並辨識指令                   |
| v0.3.0 | `track` 指令完成，含完整 RAG ingestion pipeline、初始摘要卡生成            |
| v0.4.0 | `select` + `memory.py` 完成，一般聊天模式可組合三層記憶並呼叫 Claude API |
| v0.5.0 | 增量同步 + 摘要卡自動更新觸發機制（累積門檻 + 時間保底）                     |
| v0.6.0 | `bot_conversations` 記憶，AI 記得討論到哪                                  |
| v0.7.0 | 長期歷史壓縮（月摘要 chunk）維護 job                                         |
| v1.0.0 | 穩定使用一段時間、聊天體驗順暢後標記為第一個穩定版                           |

**Git 慣例**：

- Commit message 用 `feat: `、`fix: `、`docs: ` 前綴
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
- [X] embedding model 要用哪一個？（已確認使用 Google Gemini `text-embedding-004` 免費 API）
- [ ] 摘要卡的增量觸發門檻（50 則）是否合理，要不要依對象聊天頻率動態調整？
- [ ] 是否需要多對象同時 tracked，或先鎖定 1 個對象把整套流程跑順再擴充？
