# IG AI 陪聊機器人 (bestieAI)

個人專屬的 Instagram AI 陪聊機器人服務。透過主帳號讀取目標對象歷史對話脈絡（RAG / 分層記憶），在手機 IG 私訊中由 Bot 帳號提供即時情感接住與回覆建議。

## 系統架構特點

- **套件管理**：使用 `uv` 進行虛擬環境與相依性管理。
- **資料庫**：SQLite 儲存對話、聯絡人與討論紀錄；ChromaDB 本地儲存向量 chunks。
- **免費 Embedding**：整合 Google Gemini `text-embedding-004` API。
- **LLM 陪聊**：Google Gemini API（預設 `gemini-3.8-flash`，好友/閨蜜犀利溫暖語氣）。
- **Session 加密**：`cryptography.fernet` 對稱加密保護 IG Session 憑證。

## 快速開始

### 1. 建立環境與安裝依賴

```bash
uv sync
```

### 2. 環境變數設定

複製 `.env.example` 為 `.env` 並填入憑證：

```bash
cp .env.example .env
```

必填欄位：
- `MAIN_ACCOUNT_USERNAME` & `MAIN_ACCOUNT_PASSWORD`：使用者本人 IG 帳密（讀取訊息用）
- `BOT_ACCOUNT_USERNAME` & `BOT_ACCOUNT_PASSWORD`：陪聊機器人 IG 帳密（接收指令與陪聊）
- `SESSION_ENCRYPTION_KEY`：Fernet 金鑰（可由 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 產生）
- `GEMINI_API_KEY`：Google Gemini API Key（支援 Embedding 與對話生成）

### 3. 執行測試

```bash
uv run pytest -v tests
```

### 4. 啟動機器人

```bash
uv run python main.py
```

首次登入若觸發 2FA / 安全驗證，終端機將提示手動輸入驗證碼。驗證通過後會加密快取 Session 至 `data/sessions/`。

## 指令一覽

| 指令 | 說明 |
|---|---|
| `track <IG_ID>` | 開始追蹤該對象，抓取近一個月歷史訊息建立向量與摘要卡 |
| `select <IG_ID>` | 切換目前作用中的討論對象 |
| `status` | 檢視目前對象的追蹤狀態與同步資訊 |
| `list` | 列出所有已追蹤對象 |
| `untrack <IG_ID>` | 標記為停止追蹤 |
| `<一般訊息>` | 進入 AI 陪聊模式，給予 2~3 種回覆建議版本 |
