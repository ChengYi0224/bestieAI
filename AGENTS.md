# bestieAI — AI Agent 規則

本文件是 bestieAI 給所有 AI 工具（Claude Code、Codex、Antigravity/Gemini）共用的唯一規則來源。
`CLAUDE.md` 與 `GEMINI.md` 只是指向本檔，請勿在那兩份重複寫規則。

## 專案定位

bestieAI 是 Sonara 產品的 Python 後端，使用 SQLite + ChromaDB，包含 Instagram Bot 與 REST API 兩個入口。
上層的 `Sonara/` 不是 git repo；Flutter 前端 `../sonara/` 是獨立 repo，本 repo 的變更不要涉及它。

## 常用指令

```bash
uv run python main.py            # Bot + API 同時啟動
uv run python main.py api        # 僅 REST API
uv run python main.py bot        # 僅 IG Bot
uv run pytest tests -q           # 全量測試（-E 才會跑真實外部 API 測試）
```

- Commit 會觸發 `scripts/pre_commit_check.py`：compileall → `uvx ruff check app --select F` → 全量 pytest，三項都過才能 commit，**不可用 `--no-verify` 跳過**。
- Windows 上 `uvx ruff` 偶爾因 uv 快取被防毒鎖住而失敗（os error 32）。遇到時改設全新快取目錄再 commit：
  `UV_CACHE_DIR="C:/Users/<you>/AppData/Local/Temp/uvcache-fresh" git commit ...`

## 架構層次與職責

```
Routers (app/api/routers/)                → 處理 HTTP，禁止業務邏輯
Services (app/services/)                  → 業務邏輯，禁止直接寫 SQL
Repositories (app/storage/repositories/)  → 唯一允許 SQL 的地方
Schemas (app/api/schemas/)                → Pydantic 模型，禁止業務邏輯
```

詳見 [docs/architecture.md](docs/architecture.md)。

## 鐵則（違反即不合格）

1. **SQL 僅允許在 `app/storage/repositories/` 內**，Service 層嚴禁出現任何 SQL 語法或 `conn.execute()`。（`app/storage/db.py` 的 schema 初始化與遷移為既有例外，不要再擴充。）
2. **Router 不可直接呼叫 Repository**，必須透過 Service。
3. **新增 API 功能時**，若需要業務邏輯，在 `app/services/` 新增專用 Service，不直接改動現有 Service。
4. **新增 Repository 方法**時，繼承 `BaseRepository`，使用 `@with_connection` decorator。
5. **禁止在任何層新增 `get_connection()` 的直接呼叫**，一律透過 Repository。
6. **租戶隔離**：`ContactRepository` 的查詢方法 `user_id` 是 keyword-only 必填。
   - API / Service 一律傳登入使用者的 `user_id`。
   - IG Bot 指令用 `settings.BOT_USER_ID`。
   - 只有背景排程 / 內部管線可傳 `ALL_USERS`（`app.storage.scope`），且要寫註解說明原因。
   - 禁止為了讓呼叫通過而傳 `None` 或加預設值。
7. **禁止 `except Exception: pass`**：至少要 `logger.warning/debug`。進度回報用 `app.utils.progress.notify_progress`。
8. **共用的 IG 連線只能透過 `BotPoller._get_main_ig()` 取得**，不要自行 `session_manager.login("main")`。

## 安全與設定

- `APP_ENV=dev`（預設）：允許預設金鑰，LLM 明文日誌（`logs/llm.log`，含私訊內容）預設開啟。
- `APP_ENV=prod`：啟動時 `settings.validate_security()` 會拒絕預設 / 過短的 `API_SECRET`、缺少 `GOOGLE_CLIENT_ID_*`，LLM 日誌預設關閉。
- `API_SECRET` 只用來簽 JWT，**不可當密碼**；管理者密碼登入用獨立的 `ADMIN_PASSWORD`。
- Google 登入必須驗證 `email_verified`，且不得依信箱自動綁定既有原生帳號。
- 不要把 `.env`、`data/`、`logs/` 的內容貼進 commit、日誌或對話。

## 使用 GitNexus（程式碼影響分析）

- 本 repo 已用 `npx gitnexus analyze --skip-agents-md` 建立索引（存於 `.gitnexus/`，不提交）。
- 呼叫任何 GitNexus 工具時**一律明確帶 `repo: "bestieAI"`**。同一個 GitNexus 還登錄了其他專案（工作用的 repo），不可查詢或修改它們。
- 改動被廣泛呼叫的符號（例如 Repository 方法）之前，先用 `impact`（`direction: upstream`）看呼叫端；commit 前可用 `detect_changes`。
- 索引不會自動更新；大幅改動後重跑上述 analyze 指令。索引過期時，結果只能當參考，仍以 grep 與測試為準。

## Git 慣例

- Commit 訊息使用繁體中文，格式 `type(scope): 摘要`（feat / fix / perf / refactor / chore / test / docs）。
- **Commit 與 PR 不要加 `Co-Authored-By` 或 "Generated with Claude Code" 等 AI 署名行。**
- 每個 commit 聚焦單一主題；新增或修改行為時同步補測試。
