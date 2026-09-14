# RAG 與向量資料庫架構設計總覽

本目錄以數字前綴依序拆解 bestieAI 的 RAG 與向量記憶系統：從原始私訊提取、時序向量分群、同質無損融合，一路到 Chroma 儲存與共享向量檢索組裝。

---

## 系統全景流程圖

```mermaid
flowchart TD
    A["01. 原始對話"] -->|40 則分批 + 4.2s 節流| B["01. 微觀事件提取 (extract_events)"]
    B --> C["02. 批次 Embedding (768 維)"]
    C --> D{"02. 時序向量分群 (36h 內 & Sim >= 0.80)"}
    
    D -->|孤立事件 / Sim < 0.80| G["04. ChromaDB (chat_events)"]
    D -->|高相似候選群 (Cluster >= 2)| E["03. Lite LLM 無損融合 (consolidate_events)"]
    
    E -->|同主題融合補全 / 異主題獨立| G
    
    H["使用者即時發言"] --> I["05. 單次 Query Embedding"]
    I -->|共享向量並行檢索| G
    I -->|共享向量並行檢索| J["04. ChromaDB (self_memory)"]
    
    G & J --> K["05. Prompt 組裝 (日常輕量卡 + 事件 Top-K + 近期對話)"]
    K --> L["Gemini Flash 即時回覆"]
```

---

## 文件章節索引

| 編號與文件 | 核心主旨 | 解決的關鍵問題 |
| :--- | :--- | :--- |
| [01_微觀事件提煉與節流.md](01_微觀事件提煉與節流.md) | 微觀事件提煉與 15 RPM 速率節流 | 揚棄原始碎句雜訊、避開 Gemini 429 限速 |
| [02_時序語意向量分群.md](02_時序語意向量分群.md) | 時序感知語意向量分群 | 篩出高相似候選群，節省 80%+ LLM 呼叫 |
| [03_同質無損融合去重.md](03_同質無損融合去重.md) | 同質無損融合與異質保留 | 消除跨批次重複事件，杜絕 Top-K 霸佔 |
| [04_Chroma向量儲存架構.md](04_Chroma向量儲存架構.md) | 雙軌集合儲存架構與維護 | `chat_events` 與 `self_memory` 隔離與重建 |
| [05_共享檢索與Prompt組裝.md](05_共享檢索與Prompt組裝.md) | 共享 Query 向量檢索與 Prompt 組裝 | 消除重複 Embedding 延遲，維持 < 3s 回覆 |
