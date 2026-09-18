# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] - 2026-09-19

### Changed — Gemini 呼叫防卡死、消除雙軌架構與模型重試參數化

- **全面消除雙軌連線架構**：重構 `app/services/llm_service.py` 中的 `LLMClient`，使其底層連線全面委派（Delegate）給專職的 `app/clients/gemini.py`（`GeminiClient`），徹底終結聊天與資料管線連線不一致的雙軌技術債。
- **重試語意修正為「初次嘗試 + N 次重試」**：單一模型嘗試上限調整為 `total_attempts = 1 + retries`，當 `settings.GEMINI_MODEL_MAX_RETRIES=2` 時，確保依序執行「1 次初次呼叫 + 2 次重試」（共嘗試 3 次）後才切換至下一順位候選模型。
- **關閉 Gemini 思考推理 (Thinking)**：呼叫文字生成 API 時預設加入 `thinking_config=ThinkingConfig(thinking_budget=0)`，徹底關閉模型內部思考推理時間，解決 Gemini 3.7 系列深層推理造成的假死與長延遲問題。
- **加入連線超時防護 (Timeout)**：配置 `http_options=HttpOptions(timeout=...)`，預設 30 秒超時中斷，防止底層 Blocking Socket 因網路波動或伺服器排隊無限期掛死。
- **模型輪換重試次數參數化**：`app/core/config.py` 新增 `GEMINI_MODEL_MAX_RETRIES`（預設 2 次）與 `GEMINI_REQUEST_TIMEOUT`（預設 30 秒）。

### Added — 聊天自動同步（Auto-Sync）與 pytest 獨立外部 API 測試

- **聊天觸發即時私訊同步（Auto-Sync）**：於 `ChatHandler` 增加 `sync_callback` 支援。當使用者傳送一般對話訊息時，若目前已設定作用中的聯絡人（Active Contact），自動調用同步流程至 Instagram 抓取該對象之最新私訊並寫入 SQLite 資料庫（`amount=0` 不設上限，由底層 Jitter 與防風控機制調節），確保 `get_full_context` 組裝 Prompt 時能即時納入最新對話。若同步遇異常則安全 Fallback，不阻斷聊天回覆流程。
- **Poller 訊息同步整合**：`BotPoller` 實作 `_sync_contact_messages`，透過 `SourceAdapterFactory` 取得 Instagram Adapter 抓取新訊息並以 `save_messages` 寫入資料庫，並將其綁定至 `CommandRouter` 與 `ChatHandler`。
- **命令列參數支援 (`-E` / `--external`)**：於 `tests/conftest.py` 註冊 `-E` 與 `--external` 旗標；常規執行 `uv run pytest` 時自動跳過（Skip）所有標記 `@pytest.mark.external` 的測試，避免消耗 Token 與依賴外部網路。
- **真實外部 API 連線合約測試**：新增 `tests/contracts/test_external_api.py`，自動檢測環境變數是否配置 Gemini 金鑰或 Instagram 帳密，未提供時自動 Skip，有提供時獨立執行真實端點呼叫與連通性檢測。
- **app/utils/ 模組化與 High-level / Low-level 分離**：建立專屬目錄，依 domain 精簡分檔（`time.py`、`math.py`、`text.py`、`db.py`）並於 `__init__.py` 統一 export。Pipelines、Handlers 與 Services 僅保留 high-level 調度，所有純運算、時間解析（相容 ISO 8601、Z 補償、YYYY-MM-DD）、文字清理、Cosine 向量計算與 DB Mapping 抽離至 utils 底層。
- **模型調用參數化 (Dependency Injection)**：`ChatHandler`、`CommandService` 與 `CommandRouter` 全面支援 `model` 與 `self_extract_model` 傳參；`LLMClient.extract_self_info` 預設直接繼承 instance 首選主模型（`self.candidate_models[0]` 即 `gemini-3.8-flash`），不再 fallback 至 `flash-lite`。
- **訊息 Incremental Sync (Early Stopping)**：`IGClient.get_thread_messages`、`InstagramAdapter.fetch_messages`、`IngestionPipeline.sync_messages` 與 `BotPoller._sync_contact_messages` 全面支援 `stop_item_ids` 錨點。Paging 往回爬取時，一旦偵測到 local 已存的 `item_id` 即刻 break 結束翻頁 (Early Stopping)。同時移除 `amount=0` 時強制抓取 5000 則之設定，常態 Incremental Sync 耗時由數十分鐘降至 1~2 秒。
- **單元測試覆蓋**：於 `tests/unit/test_gemini_keyring.py`、`tests/bot/test_router.py`、`tests/bot/test_poller.py`、`tests/bot/test_self_rag.py`、`tests/sources/test_source_adapters.py`、`tests/storage/test_db.py` 與 `tests/unit/test_utils.py` 補齊 Early Stopping 中斷、local ID 查詢、Auto-Sync 觸發與例外 Fallback、Thinking Budget 與 Timeout 設定、模型傳參驗證、以及各項 utils 邊界測試。

## [0.5.0] - 2026-09-18

### Changed — 記憶組裝、摘要機制與 Prompt 全面升級

**摘要卡生成機制升級（`ref` 與背景更新）**
- `check_and_update_summary`（即 `ref` 指令）改為優先讀取資料庫中「所有 Consolidated 事件記憶」結合「最近 20 則最新私訊（含時間戳與發送者）」，解決摘要只看最近 50 則對話導致深層歷史被洗掉的記憶近視問題。
- `summary.txt` 文本全面改版為結構化事實清單（關係現況、對方具體特徵、關鍵事件、互動策略），字數控制在 200~400 字，徹底淘汰舊版泛化散文。

**陪聊 Prompt 迭代**
- 修正 `companion.txt` 欄位定義，加入 `{display_name}`，更正 `recent_context` 描述為原始私訊流。
- 新增 `companion_v2.txt` 與 `companion_v3.txt`，提供情感成熟、指出隱藏矛盾、語氣冷靜骨感且說完即止的新人格提示詞。

**模型清單精簡**
- 從聊天對話候選模型（`GEMINI_CANDIDATE_MODELS`）中移除 `gemini-3.5-flash-lite`，全面採用 flash 系列主流模型。

### Added

- `app/core/error_logger.py`：全域集中式錯誤日誌模組，以 5MB × 3 份 RotatingFileHandler 記錄至 `logs/error.log`。
- `app/prompts/chat/companion_v2.txt`、`app/prompts/chat/companion_v3.txt`：成熟理性與深度共情版陪聊 Prompt。

### Fixed

- **修復向量檢索（RAG）失效**：`ChromaStore.query()` 補上 `contact_id` 參數與 `where` 條件自動組裝，解決靜默拋出 `TypeError` 導致檢索恆定顯示「向量檢索暫不可用」。
- **修復 Embedding 呼叫方法**：`MemoryManager` 統一採用 `get_embeddings_batch([query])[0]`。
- **自我記憶（Self-Memory）防重複**：`ChatHandler._async_extract` 寫入前增加語意相似度檢驗（cosine distance < 0.15 即略過），解決舊事實反覆重複累積寫入。
- **自我記憶相關性過濾**：`MemoryManager.get_full_context` 加入距離門檻過濾，避免不相關的個人記憶碎片混入 Prompt。
- **日誌追蹤覆蓋**：全面補齊 `memory_service`、`chat`、`poller`、`ingestion_service` 中的例外記錄至 `logs/error.log`。

## [0.4.0] - 2026-09-17

### Changed — Design Pattern 全面重構

**P1 魔法字串消除（`app/bot/poller.py`）**
- `poller.py` 改呼叫 `handle_message_structured()` 取得 `CommandResult`，不再解析 `"TRACK_REQUEST:..."` 字串前綴
- 所有 action dispatch 改用 `result.action_type` 與 `result.data`，`CommandResult.action_type` 欄位正式啟用

**P2 IngestionPipeline DIP 注入（`app/services/ingestion_service.py`）**
- `IngestionPipeline.__init__` 新增 `extractor`, `clusterer`, `consolidator`, `summarizer` 可選注入參數
- 子管線可從外部傳入（測試替換 / 自訂實作），fallback 行為保持不變，現有呼叫完全相容

**P3 handlers.py SRP 拆檔**
- `handlers.py`（617 行）拆分為 `app/commands/handlers/` 子目錄，各類業務邏輯獨立：
  - `commands.py`：所有 Command `@dataclass`（純 DTO 層）
  - `handlers/contact.py`：`ContactHandler`（Track/Select/List/Status/Untrack/Nickname）
  - `handlers/memory.py`：`MemoryHandler`（Card/Me/Sync/RebuildVectors/RefreshSummary/SummarizeHistory）
  - `handlers/chat.py`：`ChatHandler`（AI 聊天 + 非同步記憶萃取）
  - `handlers/help.py`：`HelpHandler`
  - `handlers/follower.py`：`FollowerHandler`（預留）
  - `handlers/__init__.py`：`CommandService` Facade（薄層聚合，向後相容）
- `handlers.py` 改為薄層 re-export，舊有 `from app.commands.handlers import ...` 全部不需修改

**P4 Router Registry Pattern（`app/bot/router.py`、`app/commands/parsers.py`）**
- 新增 `app/commands/parsers.py`：`CommandParser` 抽象介面 + `CommandParserRegistry`
- `router.py` 移除所有 if-else 分支，`parse_text_to_command()` 改為查表
- 新增 `$` 前綴強制進入 AI 聊天模式（`$你好` → `ChatCommand(text="你好")`）
- 新增 Adapter 指令只需建立新的 `CommandParser` 子類並在底部呼叫 `CommandParserRegistry.register()`

**SourceAdapterFactory 改為 Registry Pattern（`app/sources/factory.py`）**
- 移除 if-else 分支，改用 `_registry` dict 查表
- 各 Adapter 在自己模組末尾呼叫 `SourceAdapterFactory.register()` 自我註冊
- 新增 `registered_types()` 方法，新增 `file`、`local` 別名指向 `FileImportAdapter`

### Added

- `app/commands/commands.py`：Command dataclass 定義（純 DTO）
- `app/commands/parsers.py`：CommandParser Registry（各指令解析器）
- `app/commands/handlers/`：按領域拆分的 Handler 子目錄

### Fixed

- `poller.py` 中 `TRACK_FULL_REQUEST` 的 `max_amount` 欄位改由 `result.data["max_amount"]` 取得，不再依賴字串 split 解析

## [0.1.0] - 2026-09-14

### Added
- 初始化專案結構並使用 `uv` 管理相依性。
- 施工文件整理至 `docs/IG-AI陪聊機器人-施工文件.md`。
- `app/config.py`：Pydantic Settings 設定管理。
- `app/db.py`：SQLite 資料庫與 CRUD 函式（`contacts`, `messages`, `bot_state`, `bot_conversations`）。
- `app/vectors.py`：ChromaDB 向量庫封裝與 Gemini `text-embedding-004` 免費 Embedding。
- `app/sessions.py`：雙帳號登入、2FA 與 Fernet 加密 Session 持久化。
- `app/ig.py`：`instagrapi` 操作封裝與延遲保護。
- `app/llm.py`：Google Gemini API（`gemini-2.5-flash`）提示詞與回覆/摘要生成。
- `app/prompts/system.txt`：閨蜜/好友語氣 System Prompt 模板。
- `app/memory.py`：三層記憶整合（近期原始、向量 RAG、長期摘要卡）。
- `app/ingestion.py`：訊息清洗、以天/數量分段、Embedding 與關係摘要卡生成。
- `app/router.py`：指令分派路由與一般對話切換。
- `app/poller.py`：Bot 帳號收件匣輪詢與訊息處理循環。
- `tests/`：涵蓋資料庫、指令路由、訊息清洗分段及 Session 加解密之單元測試。
