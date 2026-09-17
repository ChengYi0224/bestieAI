# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
