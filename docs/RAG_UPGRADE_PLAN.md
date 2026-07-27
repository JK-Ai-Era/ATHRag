# RAG 系统升级方案

## 现有架构（v1）

### 技术栈

| 层级 | 组件 | 技术 |
|------|------|------|
| 接口层 | CLI / REST API / MCP Server | ath / FastAPI / MCP |
| 搜索服务层 | SearchService | 向量 + BM25 + RRF 融合 |
| 核心服务层 | 文档/项目/Watcher/一致性检查 | SQLAlchemy / Watchdog |
| 存储层 | 元数据 / 向量 / 文件 | SQLite / Qdrant / FS |
| 模型层 | 嵌入 / 摘要 / 重排序 | bge-m3 / qwen3.5:9b / bge-reranker-v2-m3 |

### 搜索管线

```
Query → Embedding(bge-m3) → [向量检索 + BM25检索] → RRF融合 → Reranker → 结果
                                    ↓
                            RAPTOR层次化检索（摘要→chunks）
```

### 分块策略

- 启发式语义分块：Markdown 标题 > 段落 > 列表 > 句子 > 行
- 长度保护：target 1000 / max 4000 / min 300
- 重叠保护：chunk_overlap 100

### 当前强项

- ✅ 混合搜索（向量 + BM25 + RRF）
- ✅ Reranker 重排序（bge-reranker-v2-m3）
- ✅ RAPTOR 层次化索引
- ✅ 语义分块
- ✅ 完全本地部署

### 当前短板

- ❌ Query 处理缺失 — 原始 query 直接检索
- ❌ 无上下文压缩 — 返回完整 chunk，相关信息被稀释
- ❌ 无多轮推理 — 复杂问题无法分解和迭代
- ❌ 纯文本 — 不支持表格结构化理解、图片理解
- ❌ 无反馈机制 — 搜索结果无法学习优化
- ❌ Embedding 固定 — 无领域微调能力

---

## 升级路线

### 第一阶段：低成本高收益（1-2周）

#### 1. Query Transformation（查询变换）

**问题**：用户 query 模糊、简短，直接检索效果差。

**方案**：在检索前增加 query 预处理管线：

```
原始 Query → [HyDE | Multi-Query | Sub-Query Decomposition] → 检索
```

- **HyDE（Hypothetical Document Embeddings）**：让 LLM 生成假设性答案，用答案的 embedding 检索
- **Multi-Query Expansion**：一个 query 扩展为 3-5 个不同角度，分别检索后合并
- **Sub-Query Decomposition**：复杂问题拆解为子问题，分别检索后综合

**改动范围**：SearchService.search() 前加一层

**文件改动**：
- `src/core/query_transformer.py` — 新增
- `src/services/search_service.py` — 集成
- `src/rag_api/config.py` — 新增配置项

#### 2. Contextual Compression（上下文压缩）

**问题**：返回 chunk 包含大量无关信息，LLM 上下文窗口被浪费。

**方案**：检索后增加压缩/提取步骤：

```
检索结果 → LLM 提取相关句子 → 精炼上下文 → 返回
```

**文件改动**：
- `src/core/context_compressor.py` — 新增
- `src/services/search_service.py` — 集成
- `src/rag_api/config.py` — 新增配置项

#### 3. Multi-stage Reranking（多阶段重排序）

**方案**：单次 rerank 升级为多阶段：

```
粗排（向量+BM25, top-20）→ 精排（bge-reranker, top-10）→ 精选（LLM rerank, top-5）
```

**文件改动**：
- `src/core/reranker.py` — 扩展多阶段
- `src/services/search_service.py` — 集成

---

### 第二阶段：中等投入显著提升（2-4周）

#### 4. Agentic RAG（智能体式 RAG）

**核心**：Agent 自主决定是否检索、检索什么、检索几次。

```
Query → Agent 判断 → [直接回答 | 单次检索 | 多轮检索 | 工具调用]
                         ↓
                    [检索 → 评估 → 不满意 → 改写query → 再检索]
```

#### 5. Table & Structured Data Understanding

- 表格数据单独建立结构化索引
- 支持 text-to-SQL 或 pandas 查询
- 表格摘要生成

#### 6. Self-RAG / Corrective RAG

```
检索结果 → LLM 评估相关性 → [足够 → 生成] [不足 → 改写query重新检索]
                                    ↓
                            生成后 → LLM 自检 → [合理 → 输出] [有幻觉 → 再检索修正]
```

---

### 第三阶段：长期演进（1-2月）

#### 7. Graph RAG（知识图谱增强）

文档之上构建实体关系图谱，支持多跳推理。

#### 8. Multimodal RAG

- 图片理解：引入视觉模型理解文档中的图表
- PDF 流程图、架构图单独提取和索引

#### 9. Fine-tuned Embedding

- 收集 query-document 标注对
- 对 bge-m3 做 LoRA 微调

---

## 优先级矩阵

| 优先级 | 功能 | 效果提升 | 实现难度 | 阶段 |
|--------|------|----------|----------|------|
| P0 | Query Transformation (HyDE) | ⭐⭐⭐⭐ | ⭐⭐ | 第一阶段 |
| P0 | Contextual Compression | ⭐⭐⭐ | ⭐⭐ | 第一阶段 |
| P1 | Multi-stage Reranking | ⭐⭐⭐ | ⭐⭐ | 第一阶段 |
| P1 | Agentic RAG | ⭐⭐⭐⭐ | ⭐⭐⭐ | 第二阶段 |
| P2 | Self-RAG / Corrective RAG | ⭐⭐⭐ | ⭐⭐⭐ | 第二阶段 |
| P2 | Table Understanding | ⭐⭐ | ⭐⭐⭐ | 第二阶段 |
| P3 | Graph RAG | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 第三阶段 |
| P3 | Multimodal RAG | ⭐⭐⭐ | ⭐⭐⭐⭐ | 第三阶段 |

---

## 实施记录

### 2026-05-28：模型配置化

- 将 `qwen3:8b` 硬编码改为 `OLLAMA_SUMMARY_MODEL` 配置项
- 当前值：`qwen3.5:9b`
- 改动文件：`config.py`, `hierarchical_index.py`, `.env`, `.env.example`

---

_文档版本：v1 | 创建：2026-05-28_
