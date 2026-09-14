# 💬 bestieAI — Instagram 專屬 AI 社交與情感決策助理

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![uv](<https://img.shields.io/badge/package%20manager-uv-green.svg>)](https://github.com/astral-sh/uv)
[![Tests Passing](<https://img.shields.io/badge/tests-45%20passed-brightgreen.svg>)]()

**bestieAI** 是一個專為個人打造的 Instagram AI 陪聊與回覆策略機器人。

在日常社交與感情互動中，當對方傳來令人困惑的訊息時，傳統做法往往是將零碎截圖或逐字稿手動複製給網頁版 ChatGPT，不僅缺乏長期脈絡，每次開啟新對話還需重新解釋關係背景。**bestieAI 讓你直接在手機 Instagram 私訊中與專屬 AI 助理對話**，系統會透過雙帳號架構自動讀取目標對象的歷史聊天紀錄，結合**分層記憶（Hierarchical Memory）**與**語意檢索（RAG）**，精準洞察對方語氣意圖，並給予兼具情緒同理與不同策略的回覆建議。

---

## 📱 實機畫面展示（Mobile Screenshots）

<p align="center">
  <img src="docs/images/1_help.jpg" width="45%" alt="指令清單與即時狀態查詢" />
    
  <img src="docs/images/2_track_summarize.jpg" width="45%" alt="歷史對話爬取與全景關係復盤卡" />
</p>
<p align="center">
  <em>左圖：在 IG 私訊中直接下達 <code>help</code> 指令查詢即時進度；右圖：全量抓取與自動生成深度全景關係復盤卡。</em>
</p>

---

## 💡 核心使用情境（User Journey）

```
[使用者手機 IG App] (你的主帳號)
       │
       │ 1. 初次追蹤對象：傳送「track alex_123」
       ▼
[bestieAI 背景服務]
       ├─ 主帳號安全抓取與 alex_123 的歷史訊息
       ├─ 訊息清洗、時間切塊（Chunking）、生成 Gemini 向量 Embeddings
       └─ 自動生成初始「人物關係摘要卡」（儲存個性、相處模式與關鍵事件）
       │
       ▼
[Bot 帳號私訊回覆]：「已開始追蹤 alex_123，已匯入歷史對話並建立摘要卡！」

────────────────────────────────────────────────────────────

[日常聊天與策略建議]
       │
       │ 2. 使用者傳送：「他剛剛回覆『隨便啊』，這到底什麼意思？我該怎麼回？」
       ▼
[bestieAI 動態組裝提示詞]
       ├─ 長期記憶：讀取 alex_123 深度關係摘要卡（長期性格與走向）
       ├─ 自身記憶：從獨立 user_self 向量庫檢索使用者自身的近況與習慣
       ├─ 中期 RAG：以「隨便啊」語意搜尋歷史最相關對話片段
       ├─ 短期記憶：撈取 IG 最近 30 則原始對話 ＋ 最近 10 輪與 Bot 討論歷史
       └─ 跨對象調用：若訊息提到其他朋友暱稱（如「小伊」），同步調出該對象記憶
       │
       ▼
[Bot 帳號私訊回覆]：
       ① 先同理接住使用者的焦慮情緒
       ② 客觀剖析對方字面下的真實語氣
       ③ 提供 2~3 種不同風格的回覆選項（直球 / 幽默調侃 / 保持距離）
```

---

## 🛠️ 技術架構與工程亮點

### 1. 五層分層記憶架構（Hierarchical Memory & RAG）

為了克服 LLM 上下文長度限制並大幅降低 Token 成本，系統設計了多層次記憶模型：

- **關係復盤卡（長期記憶）**：以 `gemini-3.5-flash-lite` 深度總結對象的性格、溝通慣性與關係轉折。
- **使用者自身 RAG（個人認知）**：獨立 `user_self` ChromaDB 集合，每次對話後背景執行緒自動萃取使用者近況與習慣，實現真正「了解我」的跨對話長效記憶。
- **暱稱索引與跨對象檢索**：支援 `nickname` 指令設定別名，聊天時提及朋友暱稱自動動態關聯查詢該對象之記憶。
- **ChromaDB 向量庫（中期語意記憶）**：按時間與對話密度切塊，採用 `gemini-embedding-2` 進行語意搜尋。
- **上下文與對話輪次（短期記憶）**：載入最近 20 則 IG 原始訊息與最近 10 輪 Bot 討論歷史，確保語境完全連貫。

### 2. 反爬蟲與風控安全工程（Anti-Bot & Reliability）

由於採用私有 API 模擬 App 登入，防風控為本專案核心關鍵：

- **白名單裝飾器（`@require_whitelist`）**：在最外層嚴格攔截非本人私訊，陌生訊息一律靜默丟棄，杜絕資安漏洞。
- **Session 金鑰自動持久化**：使用 Fernet 對稱加密並自動落地 `data/.session_key`，避免重啟 Session 失效引發頻繁重登風控。
- **單執行緒背景隊列 Worker**：爬取任務嚴格循序執行，任務交接處強制冷卻 60~120 秒，杜絕高併發封號風險。
- **擬真人長尾隨機延遲**：延遲範圍加大至 3.5 ~ 14.0 秒（大標準差），並具備 15% 機率觸發 18~40 秒微停頓；每 4~7 頁隨機深度休眠 35~80 秒。
- **MQTT Realtime 被動監聽**：透過長連接被動接收推播，徹底擺脫主動輪詢帶來的風控負擔。

### 3. 架構設計與高容錯 LLM 陣列

- **宣告式指令註冊（`@command_handler`）**：淘汰龐大的 `if/elif` 判斷，採用 Registry 模式達成高內聚低耦合。
- **多模型自動容錯降級陣列**：遇到 API 尖峰、503 過載或限速時，自動依序切換候選模型（`gemini-3.8-flash` → `gemini-3.7-flash` → `gemini-3.6-flash` → `gemini-3.5-flash-lite`）。
- **外部 Prompt 範本化**：所有 Prompt 全面抽離為 `.txt` 檔案，支援獨立熱更新與版本控管。

---

## 📋 指令一覽表

從**你的主帳號手機 IG 私訊**傳送給 Bot 帳號：

| 指令                                    | 說明                                                                                                   |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `track <IG_ID>`                       | 首次追蹤：爬取近一個月對話、向量化並生成初始人物關係摘要卡                                             |
| `track_full [IG_ID] [上限]`           | 安全慢速抓取歷史訊息：預設最多 5000 則（可在`.env` 調整），含自動去重與重構向量庫                    |
| `select <關鍵字>`                     | 切換目前討論對象（支援模糊搜尋與數字回覆）                                                             |
| `nickname <暱稱> [IG_ID]`             | 為目前對象或指定帳號設定專屬暱稱                                                                       |
| `card [IG_ID/暱稱]`                   | 直接檢視已儲存的人物關係摘要卡（不消耗 API、即時回傳）                                                 |
| `me <內容>`                           | 主動讓 AI 記住關於你的生活近況、習慣或偏好（寫入`user_self` RAG）                                    |
| `summarize_history [IG_ID]`           | **全景關係深度復盤**：以自始至終完整歷史對話（預設 `gemini-3.5-flash-lite`）建立長期全貌摘要卡 |
| `sync [IG_ID]`                        | 增量同步最新訊息；累積達 50 則自動觸發摘要卡更新                                                       |
| `rebuild_vectors [IG_ID]`             | 從本地 SQLite 重建向量庫（**不需重新爬 IG**，修復 Embedding 用）                                 |
| `refresh_summary [IG_ID]`             | 強制以近期對話增量更新摘要卡                                                                           |
| `status`（或 `query`）              | 顯示目前對象追蹤狀態與暱稱；若背景爬蟲正在執行，同步顯示即時頁數與則數                                 |
| `list`                                | 列出所有已追蹤對象及其暱稱                                                                             |
| `untrack <IG_ID>`                     | 標記為停止追蹤（保留歷史資料）                                                                         |
| `help`（或 `h` / `?` / `指令`） | 查詢所有可用指令說明與格式                                                                             |
| `<一般訊息>`                          | 進入 AI 陪聊模式；提及朋友暱稱時自動觸發跨對話記憶檢索                                                 |

> [!WARNING]
> **⚠️ API Token 額度與用量注意**：
> 使用 `summarize_history`（或 `track_full` 完成後的全局摘要卡生成）時，會將本地所有歷史對話（可能高達數千則訊息）全量一次性送入 LLM 進行深度復盤，這會產生**大量的 Input Tokens**。請務必留意你的 Google Gemini API Key 額度與配額上限。系統預設採用 `gemini-3.5-flash-lite` 處理此任務（可在 `config.py` 或 `.env` 中調整）。

---

## 🚀 快速開始

### 1. 安裝環境依賴

本專案使用高效能 Python 套件管理工具 `uv`：

```bash
uv sync
```

### 2. 配置環境變數

```bash
cp .env.example .env
```

開啟 `.env` 填入必要資訊：

- `MAIN_ACCOUNT_USERNAME` / `MAIN_ACCOUNT_PASSWORD`：本人 IG 帳號密碼（讀取歷史對話）
- `BOT_ACCOUNT_USERNAME` / `BOT_ACCOUNT_PASSWORD`：專用 Bot IG 帳號密碼（接收指令與發送建議）
- `GEMINI_API_KEY`：Google Gemini API 金鑰

### 3. 執行單元測試

```bash
uv run pytest -v tests
```

### 4. 啟動服務

```bash
uv run python main.py
```

> 首次啟動若觸發 IG 安全驗證或 2FA，終端機會提示輸入驗證碼。驗證通過後 Session 將加密持久化於 `data/sessions/`，後續重啟無需重新登入。

---

## 測試涵蓋

- **`test_api_contracts.py`**：Instagrapi 與 Gemini SDK 合約模擬測試
- **`test_db.py`**：資料庫遷移、聯絡人 CRUD、訊息去重與摘要門檻判斷
- **`test_self_rag.py`**：使用者自身向量庫寫入/檢索、暱稱關聯、跨對話記憶調用與 `me` 指令
- **`test_poller.py`**：白名單攔截鑑權、背景佇列 Worker 邊界防護與任務交接冷卻
- **`test_rate_limit.py`**：擬真人隨機延遲標準差檢驗與微停頓觸發率
- **`test_router.py`**：宣告式指令路由、模糊搜尋候選確認、`card` 查詢與聊天對話歷史傳遞
- **`test_sessions.py`**：Fernet 金鑰本地持久化與 Session 加解密安全性
- **`test_llm_log.py`**：`ENABLE_LLM_LOG` 開關與結構化日誌記錄
- **`test_ingestion.py`**：歷史訊息清洗、時間分段 Chunking 與全景復盤卡生成
