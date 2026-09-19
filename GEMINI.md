# bestieAI — AI Agent Checklist

閱讀本文件後，你必須在整個對話中嚴格遵守以下所有規則。

## 專案定位

bestieAI 是 Sonara 產品的 Python 後端，使用 SQLite + ChromaDB，目前包含 Instagram Bot 與 REST API 兩個入口。

## 架構層次與職責

`
Routers (app/api/routers/)              → 處理 HTTP，禁止業務邏輯
Services (app/services/)               → 業務邏輯，禁止直接寫 SQL
Repositories (app/storage/repositories/) → 唯一允許 SQL 的地方
Schemas (app/api/schemas/)             → Pydantic 模型，禁止業務邏輯
`

## 鐵則（違反即不合格）

1. **SQL 僅允許在 pp/storage/repositories/ 內**，Service 層嚴禁出現任何 SQL 語法或 conn.execute()
2. **Router 不可直接呼叫 Repository**，必須透過 Service
3. **新增 API 功能時**，若需要業務邏輯，在 pp/services/ 新增專用 Service，不直接改動現有 Service
4. **新增 Repository 方法**時，繼承 BaseRepository，使用 @with_connection decorator
5. **禁止在任何層新增 get_connection() 的直接呼叫**，一律透過 Repository

## 現有模式（必須對照遵守）

詳見 [docs/architecture.md](docs/architecture.md)。
