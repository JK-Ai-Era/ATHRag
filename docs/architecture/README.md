# ATHRag 架构文档

> ATHRag — 本地知识库 RAG 系统
> 最后更新：2026-07-29

## 目录

- [系统概述](#系统概述)
- [核心架构](#核心架构)
- [插件化解析系统](#插件化解析系统)
- [任务队列与并发控制](#任务队列与并发控制)
- [检索系统](#检索系统)
- [Agent/Skill 集成](#agentskill-集成)

---

## 系统概述

ATHRag 解决的核心问题：**非结构化数据 → 可检索的知识**。

### 设计原则

1. **知识基础设施定位** — ATHRag 是基础设施层，负责"存"和"搜"，不做业务分析
2. **插件化扩展** — 新格式支持 = 新增一个解析器 CLI 工具 + 注册配置，ATHRag 核心代码不改动
3. **关注点分离** — 解析器独立开发部署，RAG 引擎只接收标准化的解析结果
4. **队列化处理** — 文件变更通过队列异步处理，解析并发受控，不打爆本地模型

### 系统边界

```
┌─────────────────────────────────────────────────────────────┐
│                    ATHRag 知识基础设施                        │
│                                                             │
│  输入：文件夹（自动监控）或手动上传                            │
│  处理：文件检测 → 解析 → 分块 → 向量化 → 索引                 │
│  输出：可检索的知识库 + 语义搜索结果                           │
│                                                             │
│  接口：CLI / REST API / MCP                                 │
└─────────────────────────────────────────────────────────────┘
                               │
                    检索 API / CLI / MCP
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Agent / Skill 层（外部）                    │
│                                                             │
│  消费 ATHRag 的检索能力，结合 LLM 做业务分析                   │
│  例：剧本配乐推荐、法律文档分析、会议纪要生成                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 核心架构

### 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│                      接口层                                    │
│  CLI (ath)  │  REST API (FastAPI)  │  MCP Server              │
└──────────────┴─────────────────────┴──────────────────────────┘
                               │
┌──────────────────────────────────────────────────────────────┐
│                      服务层                                    │
│  DocumentService  │  SearchService  │  ProjectService         │
└──────────────┬────┴────────┬────────┴────────┬────────────────┘
               │             │                 │
┌──────────────┴─────────────┴─────────────────┴───────────────┐
│                      核心层                                    │
│  TextChunker  │  EmbeddingService  │  VectorStore             │
│  BM25Index    │  Reranker          │  QueryTransformer        │
│  ParseDispatcher  │  ParseQueue    │  ParseWorker             │
└──────────────┬─────────────────────┬─────────────────────────┘
               │                     │
┌──────────────┴──────┐  ┌───────────┴─────────────────────────┐
│    存储层            │  │    外部解析器（独立 CLI 工具）         │
│  SQLite (元数据)     │  │  doc-analyze  │  audio-analyze       │
│  Qdrant  (向量)      │  │  image-analyze │ video-analyze       │
│  BM25    (关键词)    │  │  （按需扩展...）                      │
└─────────────────────┘  └─────────────────────────────────────┘
```

### 数据流

```
文件变更/上传
      │
      ▼
  Watchdog 检测 ──→ 写入 parse_queue（事件持久化）
                          │
                          ▼
                    Parse Worker（并发受控）
                          │
                    ┌─────┴─────┐
                    ▼           ▼
              doc-analyze   audio-analyze   ...（按扩展名路由）
                    │           │
                    └─────┬─────┘
                          │ 标准化 JSON
                          ▼
                    DocumentService
                          │
                    ┌─────┼──────────┐
                    ▼     ▼          ▼
                TextChunker  BM25Index  EmbeddingService
                    │                       │
                    ▼                       ▼
              SQLite (chunks)        Qdrant (vectors)
                    │
                    ▼
              检索接口（CLI / API / MCP）
```

---

## 插件化解析系统

### 设计目标

新增文件格式支持时，只需要：
1. 开发一个独立的 CLI 工具，遵守标准化输出契约
2. 在 `parsers.yaml` 注册扩展名和 CLI 名称
3. ATHRag 核心代码零改动

### 解析器注册表

配置文件：`config/parsers.yaml`

```yaml
parsers:
  document:
    cli: doc-analyze
    venv: ".venv"           # CLI 工具的虚拟环境
    file_type: document      # parse_queue 的 file_type 字段
    extensions: [".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"]
    description: "Office/PDF 文档解析"
    timeout: 120
    enabled: true

  audio:
    cli: audio-analyze
    venv: ".venv"
    file_type: audio
    extensions: [".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff"]
    description: "音频文件分析（librosa + Whisper + PANNs）"
    timeout: 300
    enabled: true

  image:
    cli: doc-analyze
    venv: ".venv"
    file_type: image
    extensions: [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"]
    description: "图片 OCR"
    timeout: 60
    enabled: true

  text:
    cli: doc-analyze
    venv: ".venv"
    file_type: document
    extensions: [".md", ".txt", ".rst"]
    description: "纯文本/Markdown"
    timeout: 10
    enabled: true

  code:
    cli: doc-analyze
    venv: ".venv"
    file_type: document
    extensions: [".py", ".js", ".ts", ".go", ".java", ".cpp", ".c", ...]
    description: "代码注释提取"
    timeout: 30
    enabled: true
```

### 标准化输出契约

所有解析器 CLI 必须输出符合以下 JSON Schema 的结果：

```json
{
  "source": "/absolute/path/to/file.pdf",
  "type": "document",
  "format": "pdf",
  "content": "提取出的完整文本内容...",
  "metadata": {
    "title": "文档标题",
    "language": "zh",
    "format_specific": {
      "pages": 12,
      "author": "作者"
    }
  },
  "chunks": [
    {
      "text": "第一段文本内容...",
      "position": "page:1",
      "metadata": {}
    }
  ],
  "semantic": {
    "summary": "文档摘要...",
    "keywords": ["关键词1", "关键词2"],
    "categories": ["分类1"]
  }
}
```

**字段说明：**

| 字段 | 必填 | 说明 |
|------|------|------|
| `source` | ✅ | 源文件绝对路径 |
| `type` | ✅ | 文件类型：document / audio / image / video |
| `format` | ✅ | 具体格式：pdf / docx / mp3 / wav... |
| `content` | ✅ | 提取的完整文本（用于全文检索） |
| `metadata` | ✅ | 元数据字典 |
| `metadata.title` | ❌ | 文件标题 |
| `metadata.language` | ❌ | 语言代码 |
| `metadata.format_specific` | ❌ | 格式特有的元数据 |
| `chunks` | ❌ | 预分块结果（有则用，无则 RAG 自动分块） |
| `semantic` | ❌ | 语义增强（有则优先用于向量化） |
| `semantic.summary` | ❌ | LLM 生成的摘要 |
| `semantic.keywords` | ❌ | 关键词列表 |
| `semantic.categories` | ❌ | 分类标签 |

### 解析器调度器 (ParseDispatcher)

```python
class ParseDispatcher:
    """解析器调度器 — 根据文件扩展名自动路由到对应 CLI"""

    def dispatch(self, file_path: Path) -> dict:
        # 1. 从 parsers.yaml 查找扩展名对应的解析器
        # 2. 检查解析器 CLI 是否可用（which xxx）
        # 3. 调用 CLI，传入文件路径，获取 JSON 输出
        # 4. 校验输出格式（必填字段）
        # 5. 返回标准化结果
```

### 模型配置与 Provider 模式

配置文件：`config/models.yaml`

一个文件管所有模型选型。切换 provider = 切换实现，上游代码零改动。

```yaml
embedding:
  provider: ollama          # ollama | openai | huggingface
  model: bge-m3
  dimension: 1024

audio:
  speech:
    provider: whisper-local # whisper-local | openai-api | funasr
    model: base
  classify:
    provider: panns         # panns | none
    model: cnn14
    device: auto            # auto | cpu | mps | cuda

document:
  pdf:
    provider: mineru        # mineru | pypdf
  office:
    provider: unstructured  # unstructured | native
  image:
    provider: tesseract
    languages: chi_sim+eng

hardware:
  device: auto              # auto | cpu | mps | cuda
```

每个解析器通过 `get_model_config(category, subcategory)` 读取配置，根据 provider 字段分发到不同实现。

每个 CLI 工具有独立的 `model_config.py`，不依赖主程序。

### CLI 工具契约测试

每个解析器必须通过契约测试：

```python
def test_output_contract(result):
    """验证解析器输出是否符合契约"""
    assert "source" in result
    assert "type" in result
    assert "format" in result
    assert "content" in result
    assert "metadata" in result
    assert isinstance(result["content"], str)
    assert len(result["content"]) > 0
```

---

## 任务队列与并发控制

### 为什么需要队列

1. **本地模型并发能力弱** — MinerU 处理一个 PDF 可能要 30 秒，PANNs 分析音频也需要数秒
2. **文件批量变更** — git pull、文件夹复制等场景会同时产生大量文件事件
3. **资源保护** — 防止并发过高导致 OOM 或 CPU 打满

### 三层队列架构

```
┌─────────────────────────────────────────────────┐
│  第 1 层：事件队列（Watchdog → parse_queue）       │
│  职责：文件变更事件持久化、去重                      │
│  存储：SQLite parse_queue 表                      │
│  特点：写入快，不阻塞 Watchdog                     │
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────┐
│  第 2 层：解析队列（Parse Worker 消费）             │
│  职责：从队列取任务 → 调解析 CLI → 写结果            │
│  并发：可配置，默认 1-2（按解析器类型分别配置）        │
│  重试：失败自动重试，最多 3 次                       │
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────┐
│  第 3 层：向量化队列（embedding_queue，已有）        │
│  职责：chunks 向量化                               │
│  并发：1（Ollama 单请求）                           │
│  说明：已有机制，不改动                              │
└─────────────────────────────────────────────────┘
```

### parse_queue 表设计

```sql
CREATE TABLE parse_queue (
    id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    file_hash TEXT,                    -- SHA256，用于去重
    file_type TEXT NOT NULL,           -- document / audio / image / video
    project_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',     -- pending / running / done / failed / skipped
    priority INTEGER DEFAULT 0,        -- 越小越优先：手动上传=10, 自动检测=0
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    error_msg TEXT,
    worker_id TEXT,
    result_json TEXT,                  -- 解析结果 JSON（done 时写入）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,

    UNIQUE(file_hash, project_id)      -- 同文件同项目不重复入队
);

CREATE INDEX idx_pq_status ON parse_queue(status, priority, created_at);
CREATE INDEX idx_pq_hash ON parse_queue(file_hash);
```

### 并发控制配置

```yaml
# config.yaml
parse_worker:
  enabled: true
  poll_interval: 2          # 无任务时轮询间隔（秒）
  batch_size: 5             # 每次最多领取任务数
  timeout_per_task: 300     # 单任务超时（秒）

  # 全局并发数
  concurrency: 2

  # 按解析器类型分别配置并发（覆盖全局）
  concurrency_by_type:
    document: 1             # MinerU 吃内存，限制并发 1
    audio: 2                # PANNs 较轻，可以 2
    image: 2                # OCR 较轻，可以 2
```

### Worker 领取任务的原子性

多个 Worker 实例运行时，通过 SQL 的 `UPDATE ... RETURNING` 保证任务不被重复领取：

```sql
UPDATE parse_queue
SET status = 'running', worker_id = :worker_id, started_at = CURRENT_TIMESTAMP
WHERE id IN (
    SELECT id FROM parse_queue
    WHERE status = 'pending'
    ORDER BY priority ASC, created_at ASC
    LIMIT :batch_size
)
RETURNING *
```

---

## 检索系统

### 混合检索

- **语义搜索**：向量检索（Qdrant + bge-m3 嵌入）
- **关键词搜索**：BM25（jieba 中文分词）
- **融合策略**：RRF（Reciprocal Rank Fusion）
- **重排序**：bge-reranker-v2-m3

### 检索接口

```bash
# CLI
ath search hybrid <project> "紧张的弦乐" -k 5

# REST API
POST /api/search
{
  "project_id": "xxx",
  "query": "紧张的弦乐",
  "search_mode": "hybrid",
  "top_k": 5,
  "rerank": true
}

# MCP Tool
search(project="xxx", query="紧张的弦乐", mode="hybrid")
```

---

## Agent/Skill 集成

### 集成模式

ATHRag 作为知识基础设施，通过三种接口供 Agent/Skill 调用：

1. **CLI** — OpenClaw exec 工具直接调用 `ath` 命令
2. **REST API** — HTTP 调用，适合复杂交互
3. **MCP** — Model Context Protocol，Agent 原生调用

### 典型集成流程

```
Agent（OpenClaw）
    │
    ├── 1. 用户说"把这个文件夹的素材入库"
    │      → exec: ath project sync /path/to/folder
    │      → ATHRag 自动监控、解析、索引
    │
    ├── 2. 用户说"分析这个剧本需要什么配乐"
    │      → Agent 读取剧本文件
    │      → Agent 用 LLM 分析配乐需求
    │      → 每个需求点：
    │          → exec: ath search hybrid <project> "紧张弦乐" -k 5
    │          → 获取候选素材
    │      → Agent 综合推荐给用户
    │
    └── 3. 用户说"没有合适的，生成一段"
           → Agent 调用 MiniMax API 生成
           → 可选：生成结果存入 ATHRag 素材库
```

### 边界原则

| ATHRag 做 | Agent/Skill 做 |
|-----------|---------------|
| 文件监控和变更检测 | 业务逻辑（剧本分析、配乐推荐） |
| 格式解析（PDF、音频、图片...） | LLM 推理和决策 |
| 语义增强（摘要、关键词、标签） | 用户交互和展示 |
| 文本分块和向量化 | 外部 API 调用（音乐生成） |
| 索引存储和检索 | 多步骤编排 |
| 并发控制和队列管理 | 结果呈现和确认 |
