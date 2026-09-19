# bestieAI — 架構設計規範

> 本文件是後端與 API 開發的架構參考，所有 AI Agent 與開發者必須遵守。

---

## 技術棧

| 類別 | 技術 |
|------|------|
| 語言 | Python 3.11 |
| 套件管理 | uv |
| 關聯式資料庫 | SQLite（pp/storage/db.py） |
| 向量資料庫 | ChromaDB（pp/storage/chroma_store.py） |
| 設定管理 | Pydantic Settings（pp/core/config.py） |
| REST API | FastAPI + uvicorn（pp/api/） |
| LLM | Google Gemini（pp/clients/gemini.py） |
| Instagram | instagrapi（pp/clients/instagram.py） |

---

## 目錄結構

`
app/
├── api/               # FastAPI REST API 層（Router / Schema / Dependency）
├── bot/               # Instagram Bot（Poller、Router、Auth）
├── clients/           # 外部 API 封裝（Gemini、Instagram）
├── commands/          # Bot 指令解析與分發（Command Bus 模式）
├── core/              # 全域設定、安全、Rate Limit
├── pipelines/         # 長流程 Pipeline
├── prompts/           # Prompt 模板
├── services/          # 業務邏輯層
├── sources/           # 資料來源抽象
├── storage/
│   ├── db.py              # Schema 定義、init_db、相容橋接函式
│   ├── repositories/      # Repository Pattern（SQL 唯一存在處）
│   │   ├── base.py        BaseRepository + @with_connection decorator
│   │   ├── contacts.py    ContactRepository
│   │   ├── messages.py    MessageRepository
│   │   ├── bot_state.py   BotStateRepository
│   │   └── events.py      EventRepository
│   ├── chroma_store.py    # ChromaDB 向量存取
│   └── vectors.py
└── utils/
`

---

## 層次職責分離（強制）

`
┌─────────────────────────────────────────────────┐
│  Presentation / Router   app/api/routers/        │
│  · 接收 HTTP Request，呼叫 Service               │
│  · 回傳 Pydantic Schema Response                 │
│  · 禁止：業務邏輯、直接呼叫 Repository           │
├─────────────────────────────────────────────────┤
│  Schema                  app/api/schemas/        │
│  · Pydantic Request / Response 模型              │
│  · 禁止：業務邏輯                               │
├─────────────────────────────────────────────────┤
│  Service                 app/services/           │
│  · 業務邏輯、跨 Repository 組合                  │
│  · 禁止：直接寫任何 SQL 語法                     │
├─────────────────────────────────────────────────┤
│  Repository              app/storage/repositories/│
│  · SQL 查詢、資料庫存取                          │
│  · 繼承 BaseRepository，使用 @with_connection    │
│  · 禁止：業務邏輯判斷                            │
└─────────────────────────────────────────────────┘
`

---

## 鐵則

### 1. SQL 只能在 Repository

`python
# ❌ 違規：Service 直接寫 SQL
class ContactApiService:
    def get_contact(self, contact_id: int):
        conn = get_connection()
        return conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))

# ✅ 正確：Service 呼叫 Repository
class ContactApiService:
    def __init__(self, repo: ContactRepository):
        self.repo = repo

    def get_contact(self, contact_id: int):
        return self.repo.get_by_id(contact_id)
`

### 2. Router 不可直接碰 Repository

`python
# ❌ 違規：Router 直接呼叫 Repository
@router.get("/contacts/{id}")
async def get_contact(id: int):
    return ContactRepository().get_by_id(id)

# ✅ 正確：Router 透過 Service（用 Depends 注入）
@router.get("/contacts/{id}", response_model=ContactResponse)
async def get_contact(id: int, service: ContactApiService = Depends(get_contact_service)):
    return service.get_contact(id)
`

### 3. 新增 Repository 方法必須繼承 BaseRepository

`python
# ✅ 正確寫法
from app.storage.repositories.base import BaseRepository, with_connection

class ContactRepository(BaseRepository):
    @with_connection(readonly=True)
    def get_by_id(self, conn, contact_id: int):
        return conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
`

### 4. 現有 Service 不直接改動

新增 API 所需的業務邏輯，在 pp/services/ 新增 *_api_service.py（如 contact_api_service.py），不修改現有 ingestion_service.py、llm_service.py 等 Bot 專用 Service。

### 5. get_connection() 禁止在 Repository 外呼叫

除 pp/storage/db.py 與 pp/storage/repositories/base.py 外，任何地方不得直接 import get_connection 並呼叫。

---

## API 層結構（app/api/）

`
app/api/
├── app.py              # FastAPI 應用程式實例、CORS、掛載 router
├── dependencies.py     # Depends() 工廠：注入 Service 與 Repository
├── schemas/            # Pydantic Request / Response 模型
│   ├── auth.py
│   ├── contact.py
│   ├── message.py
│   └── common.py
└── routers/            # 每個資源一個檔案
    ├── auth.py         # POST /auth/token
    ├── contacts.py     # GET /contacts, GET/PATCH /contacts/{id}
    ├── messages.py     # GET /contacts/{id}/messages
    └── status.py       # GET /status
`

---

## 認證機制

- JWT Bearer Token
- 端點：POST /auth/token
- 環境變數：API_SECRET、API_TOKEN_EXPIRE_HOURS

---

## 環境變數（.env 新增欄位）

`dotenv
API_SECRET=your-secure-secret-key
API_TOKEN_EXPIRE_HOURS=24
CORS_ORIGINS=http://localhost,http://10.0.2.2
`

---

## 相關文件

- [GEMINI.md](../GEMINI.md) — AI Agent 快速檢查點
- [施工文件（舊版 Bot）](IG-AI陪聊機器人-施工文件.md)
- [Source Adapter 架構](source-adapter-architecture.md)
