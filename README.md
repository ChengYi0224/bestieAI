# IG AI 陪聊機器人 (bestieAI)

個人專屬的 Instagram AI 陪聊機器人服務。透過主帳號讀取目標對象歷史對話脈絡（RAG / 分層記憶），在手機 IG 私訊中由 Bot 帳號提供即時情感接住與回覆建議。

## 技術特點

| 項目 | 技術選型 |
|---|---|
| 套件管理 | `uv` |
| IG 存取 | `instagrapi`（非官方私有 API，含 Session 加密持久化） |
| 訊息監聽 | MQTT Realtime 長連接（被動接收推播，降低風控風險） |
| 向量資料庫 | ChromaDB（本地檔案模式） |
| Embedding | Gemini `text-embedding-004`（免費） |
| LLM | Gemini `gemini-3.8-flash` |
| 關聯式儲存 | SQLite |
| Session 加密 | `cryptography.fernet` 對稱加密 |

> **⚠️ 風險聲明**：本服務透過帳密直接模擬 IG App 登入，違反 Meta ToS，兩帳號均有被風控或封鎖風險。請妥善保管憑證，並以個人實驗性工具的心態使用。

---

## 快速開始

### 1. 安裝依賴

```bash
uv sync
```

### 2. 環境變數設定

```bash
cp .env.example .env
```

開啟 `.env` 填入以下欄位：

| 變數 | 說明 |
|---|---|
| `MAIN_ACCOUNT_USERNAME` | 使用者本人 IG 帳號（大帳，讀取對話紀錄用） |
| `MAIN_ACCOUNT_PASSWORD` | 大帳密碼 |
| `BOT_ACCOUNT_USERNAME` | AI 陪聊機器人 IG 帳號（接收指令與回覆）|
| `BOT_ACCOUNT_PASSWORD` | Bot 帳號密碼 |
| `SESSION_ENCRYPTION_KEY` | Fernet 金鑰，以下指令一鍵產生：`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GEMINI_API_KEY` | Google Gemini API Key（Embedding + LLM 回覆共用） |

### 3. 執行單元測試

```bash
uv run pytest -v tests
```

### 4. 啟動機器人

```bash
uv run python main.py
```

首次啟動若觸發 IG 安全驗證或 2FA，終端機會提示手動輸入驗證碼。驗證通過後 Session 將加密存於 `data/sessions/`，之後重啟不需重新登入。

---

## 指令一覽

從**你的主帳號手機 IG App** 私訊給 Bot 帳號：

| 指令 | 說明 |
|---|---|
| `track <IG_ID>` | 首次追蹤：爬取近一個月對話、向量化、生成初始人物關係摘要卡 |
| `select <IG_ID>` | 切換目前討論對象（純本地操作，不動 IG API） |
| `sync [IG_ID]` | 增量同步最新訊息並寫入向量庫；累積達 50 則自動更新摘要卡 |
| `refresh_summary [IG_ID]` | 強制以最新對話重新生成人物關係摘要卡 |
| `status` | 顯示目前對象的追蹤狀態、上次同步時間與未摘要訊息數 |
| `list` | 列出所有已追蹤對象 |
| `untrack <IG_ID>` | 標記為停止追蹤（保留資料，不刪除） |
| `help`（或 `h` / `?` / `指令`） | 查詢所有可用指令說明與格式 |
| `<一般訊息>` | 進入 AI 陪聊模式，接住情緒後提供 2~3 種回覆建議版本 |

> **`[IG_ID]` 為選填**：若省略，預設使用目前 `select` 的作用中對象。

---

## 分層記憶架構

```
長期記憶  →  人物關係摘要卡（contacts.summary_card）
              Gemini 生成，記錄個性、相處模式、重大事件、關係狀態
              更新時機：
                1. track 初次匯入時生成
                2. 累積 50 則新訊息自動增量更新
                3. 距上次更新超過 14 天保底觸發
                4. refresh_summary 手動觸發

中期記憶  →  ChromaDB 向量庫（按天/50則分段的 chunks）
              Gemini text-embedding-004 向量化
              回覆時語意搜尋最相關 5 筆

近期記憶  →  SQLite messages 表最近 20~30 則原始訊息
              完整對話原文，確保當下語境準確
```

---

## 服務運作流程

```
[使用者手機 IG App] (主帳號)
       │
       │  私訊指令或訊息給 Bot 帳號
       ▼
[Bot 帳號] ── MQTT Realtime 長連接（被動接收推播，不主動輪詢）
       │
       ├─ track <IG_ID>
       │      ├─ 登入大帳（首次或 Session 失效時，支援 2FA）
       │      ├─ 爬取與目標近一個月對話（每頁加隨機延遲）
       │      ├─ 訊息清洗＋按天/數量切 chunks
       │      ├─ Gemini text-embedding-004 向量化 → 寫入 ChromaDB
       │      └─ Gemini gemini-3.8-flash 生成初始人物關係摘要卡 → 寫入 SQLite
       │
       ├─ sync [IG_ID]
       │      ├─ 只抓自上次同步後的新訊息（增量，不重跑）
       │      ├─ 向量化並寫入 ChromaDB
       │      └─ 若新訊息累積 ≥ 50 則：呼叫 Gemini 增量更新摘要卡
       │
       ├─ select / status / list / untrack
       │      └─ 純本地 SQLite 操作
       │
       ├─ refresh_summary [IG_ID]
       │      └─ 強制用最新訊息重新生成摘要卡（保留舊摘要做增量更新）
       │
       └─ <一般訊息>
              ├─ 讀取摘要卡（長期記憶）
              ├─ 讀取最近 20~30 則原始訊息（近期記憶）
              ├─ Gemini Embedding 語意搜尋 ChromaDB，取 Top 5 相關片段（中期 RAG）
              ├─ 組裝三層記憶 → System Prompt
              ├─ Gemini 3.8 Flash 生成回覆：先同理情緒，再給 2~3 種語氣建議版本
              └─ Bot 傳回回覆至你的 IG 私訊

[保底排程] ── 每小時 Ping 維持 MQTT 連線時順帶檢查
       └─ 若任一追蹤對象距上次摘要更新 ≥ 14 天且有新訊息 → 自動觸發增量更新
```
