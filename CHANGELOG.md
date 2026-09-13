# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-14

### Added
- 初始化專案結構並使用 `uv` 管理相依性。
- 施工文件整理至 `docs/IG-AI陪聊機器人-施工文件.md`。
- `app/config.py`：Pydantic Settings 設定管理。
- `app/db.py`：SQLite 資料庫與 CRUD 函式（`contacts`, `messages`, `bot_state`, `bot_conversations`）。
- `app/vectors.py`：ChromaDB 向量庫封裝與 Gemini `text-embedding-004` 免費 Embedding。
- `app/sessions.py`：雙帳號登入、2FA 與 Fernet 加密 Session 持久化。
- `app/ig.py`：`instagrapi` 操作封裝與延遲保護。
- `app/llm.py`：Claude API 與提示詞組裝。
- `app/prompts/system.txt`：閨蜜/好友語氣 System Prompt 模板。
- `app/memory.py`：三層記憶整合（近期原始、向量 RAG、長期摘要卡）。
- `app/ingestion.py`：訊息清洗、以天/數量分段、Embedding 與關係摘要卡生成。
- `app/router.py`：指令分派路由與一般對話切換。
- `app/poller.py`：Bot 帳號收件匣輪詢與訊息處理循環。
- `tests/`：涵蓋資料庫、指令路由、訊息清洗分段及 Session 加解密之單元測試。
