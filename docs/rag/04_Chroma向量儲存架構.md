# 04 - Chroma 向量儲存架構與集合設計

## 1. 雙軌集合設計（Dual Collections）

bestieAI 在 ChromaDB 中維護兩個職責嚴格隔離的集合：

```
ChromaDB (PersistentClient: data/chroma/)
├── chat_events (對象事件記憶集合)
│   ├── metadata: {"contact_id": 1, "start_time": "...", "end_time": "...", "type": "event_memory"}
│   └── document: "[2026-08-15] 兩人討論沖繩自駕自由行..."
│
└── self_memory (使用者自我記憶集合)
    ├── metadata: {"created_at": "...", "type": "self_fact"}
    └── document: "討厭吃香菜，對海鮮稍微過敏..."
```

---

## 2. 核心儲存規格

| 規格項目 | 設定值 | 設計意圖 |
| :--- | :--- | :--- |
| **Embedding 模型** | `gemini-embedding-2` | Google 最新多模態語意模型，跨語言理解能力強 |
| **向量維度** | `768` 維度 | MRL 截斷優化，兼顧極高語意辨識力與降低記憶體負擔 |
| **距離度量** | `cosine` (`hnsw:space: cosine`) | 餘弦空間適合文本長度不一的情感對話語意相似度計算 |
| **批次寫入** | `Batch API` (List[Content]) | 支援一次傳入大量文字列表，單次網路請求完成向量化寫入 |

---

## 3. SQLite 單一事實來源與無痛重建

- **Single Source of Truth**：
  - 向量庫（`data/chroma/`）**隨時可刪除**。
  - 所有原始對話與發送時間 100% 乾淨完整地保存在 SQLite `data/app.db` 的 `messages` 表中。
- **無痛重建指令**：
  - 輸入 `rebuild_vectors`（或短指令 `rv`）。
  - 系統直接從本地 SQLite 重新提取事件、執行時序向量分群、同質無損融合，並建立全新 Chroma 向量。
  - **全程完全不需要碰 IG API**，零帳號風控風險。
