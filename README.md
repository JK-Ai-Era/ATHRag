# ATHRag

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Qdrant](https://img.shields.io/badge/Qdrant-1.13%2B-red.svg)](https://qdrant.tech/)

**本地知识库 RAG 系统** - 基于 BM25 + 向量检索 + Reranker 的混合搜索方案，支持多项目管理和 RAPTOR 层次化索引。

---

## ✨ 功能特性

### 🔍 多模式搜索

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **Semantic** | 纯向量语义搜索 | 概念查询、语义理解 |
| **Keyword** | BM25 关键词搜索 | 精确匹配、专有名词 |
| **Hybrid** | 向量 + BM25 + RRF 融合 | **推荐默认**，综合效果最好 |
| **Hierarchical** | RAPTOR 层次化检索 | 长文档、需要文档级摘要 |

### 🚀 核心能力

- **混合搜索架构** - 向量检索 + BM25 关键词 + Reciprocal Rank Fusion
- **Reranker 重排序** - BAAI/bge-reranker-v2-m3，分数提升到 0.99+
- **RAPTOR 层次化索引** - 文档摘要生成 + 两阶段检索
- **多项目管理** - 项目间数据严格隔离
- **文件监控同步** - Watcher 自动监控文件夹变化
- **完全本地部署** - 数据不出境，隐私安全

### 📄 支持格式

| 格式 | 解析器 |
|------|--------|
| PDF | MinerU / pypdf |
| Word (.docx/.doc) | Unstructured / python-docx |
| Excel (.xlsx/.xls) | Unstructured / openpyxl |
| PowerPoint | Unstructured / python-pptx |
| Markdown | 原生支持 |
| 图片 (OCR) | pytesseract |
| 代码文件 | 原生支持 |

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户界面层                            │
├──────────────┬──────────────┬──────────────┬───────────────┤
│   CLI (ath)  │   REST API   │   MCP Server   │   Web UI    │
└──────────────┴──────────────┴──────────────┴───────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                        搜索服务层                            │
├─────────────────────────────────────────────────────────────┤
│  SearchService → BM25Index → VectorStore → Reranker         │
│                         ↓                                   │
│              HierarchicalIndex (RAPTOR)                      │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                        核心服务层                            │
├──────────────┬──────────────┬──────────────┬───────────────┤
│ DocumentService │ ProjectService │ WatcherManager │ ConsistencyChecker │
└──────────────┴──────────────┴──────────────┴───────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                        存储层                                │
├──────────────┬──────────────┬──────────────┬───────────────┤
│   SQLite     │   Qdrant     │   Ollama      │   FileSystem  │
│  (元数据)     │  (向量库)    │  (Embedding)   │   (文档文件)   │
└──────────────┴──────────────┴──────────────┴───────────────┘
```

### 模型配置

| 模型 | 用途 | 大小 |
|------|------|------|
| qwen3:8b | 文档摘要生成 (RAPTOR) | 5.2 GB |
| bge-m3 | 向量嵌入 | 1.2 GB |
| bge-reranker-v2-m3 | 重排序 | ~500 MB |

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- macOS / Linux
- 16GB+ 内存
- Ollama (用于嵌入模型)

### 一键安装

```bash
# 克隆项目
git clone https://github.com/JK-Ai-Era/ATHRag.git
cd ATHRag

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Ollama 模型
ollama pull bge-m3:latest
ollama pull qwen3:8b

# 启动服务
./scripts/start-all.sh
```

### 手动启动

```bash
# 1. 启动 Qdrant
docker run -d -p 6333:6333 -v $(pwd)/data/qdrant:/qdrant/storage qdrant/qdrant

# 2. 启动 API
source .venv/bin/activate
uvicorn src.rag_api.main:app --host 0.0.0.0 --port 8000

# 3. 访问 API 文档
open http://localhost:8000/docs
```

---

## 📖 使用指南

### CLI 命令 (ath)

```bash
# 登录认证
ath auth login --username admin --password <密码>

# 项目管理
ath project list                    # 列出项目
ath project stats <项目名>           # 查看统计
ath project check <项目名>           # 一致性检查

# 搜索（4 种模式）
ath search semantic <项目> <查询> -k 5              # 语义搜索
ath search keyword <项目> <查询> -k 5               # 关键词搜索
ath search hybrid <项目> <查询> -k 5                # 混合搜索（推荐）
ath search hierarchical <项目> <查询> -k 5          # 层次化搜索

# 获取完整内容（默认截断 300 字符）
ath search hybrid <项目> <查询> -k 5 --full         # 显示完整内容

# 服务管理
ath service status                   # 查看服务状态
ath watcher status                   # 查看监控状态
```

### 搜索模式对比

| 模式 | 耗时 | 分数 | 适用场景 |
|------|------|------|----------|
| semantic | 2-3s | ~0.85 | 概念查询 |
| keyword | 1-2s | ~0.80 | 精确匹配 |
| hybrid | 4-5s | **~0.99** | 综合查询（推荐） |
| hierarchical | 1-2s | ~0.79 | 长文档摘要 |

### REST API

```bash
# 获取 Token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login/json \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "<密码>"}' | jq -r '.access_token')

# 搜索
curl -X POST "http://localhost:8000/api/v1/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "<项目ID>",
    "query": "查询内容",
    "top_k": 10,
    "search_mode": "hybrid",
    "rerank": true
  }'

# 项目列表
curl -s http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer $TOKEN"
```

---

## ⚙️ 配置说明

### 环境变量 (.env)

```env
# API 配置
API_HOST=0.0.0.0
API_PORT=8000
APP_DEBUG=false

# 认证
AUTH_ENABLED=true
JWT_SECRET=your-secret-key
JWT_EXPIRE_HOURS=24

# Ollama
OLLAMA_HOST=http://localhost:11434
EMBEDDING_MODEL=bge-m3:latest
SUMMARY_MODEL=qwen3:8b

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333

# HuggingFace 镜像（国内）
HF_ENDPOINT=https://hf-mirror.com
```

### Watcher 配置

```bash
# 启用项目监控
curl -X PUT "http://localhost:8000/api/v1/projects/<项目ID>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"watcher_enabled": true}'
```

---

## 📁 项目结构

```
ATHRag/
├── src/
│   ├── rag_api/              # FastAPI 服务
│   │   ├── main.py           # 应用入口
│   │   ├── models/           # 数据模型
│   │   └── routers/          # API 路由
│   ├── core/                 # 核心逻辑
│   │   ├── bm25_index.py     # BM25 索引
│   │   ├── reranker.py       # Reranker
│   │   ├── hierarchical_index.py  # RAPTOR
│   │   ├── vector_store.py   # Qdrant 操作
│   │   └── document_processor.py  # 文档处理
│   ├── services/             # 业务服务
│   │   ├── search_service.py # 搜索服务
│   │   ├── document_service.py    # 文档服务
│   │   └── project_service.py     # 项目服务
│   ├── watcher/              # 文件监控
│   │   ├── manager.py        # 监控管理器
│   │   ├── handler.py        # 事件处理器
│   │   └── sync.py           # 同步逻辑
│   └── cli/                  # CLI 工具
│       ├── main.py           # CLI 入口
│       └── commands/         # 子命令
├── scripts/                  # 运维脚本
├── tests/                    # 测试用例
├── docs/                     # 文档
├── data/                     # 数据目录
└── db/                       # SQLite 数据库
```

---

## 🔧 开发指南

### 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 代码格式化
black src/
isort src/
```

### 添加新文档格式支持

1. 在 `src/core/document_processor.py` 添加解析器
2. 在 `DocumentProcessor.SUPPORTED_FORMATS` 注册格式
3. 添加对应测试用例

---

## 📊 性能优化

### 已实现的优化

- ✅ BM25 索引线程安全 + 批量操作
- ✅ Reranker 懒加载 + 缓存
- ✅ Embedding 批量向量化
- ✅ 数据库连接池
- ✅ 异步 API 端点

### 推荐配置

| 场景 | 内存 | Qdrant 配置 |
|------|------|-------------|
| 小型 (<1万文档) | 8GB | 默认 |
| 中型 (1-10万文档) | 16GB | 增大 cache |
| 大型 (>10万文档) | 32GB+ | 分布式部署 |

---

## ❓ 常见问题

### Q: 新建项目默认关闭监控？

**A:** 是的，新建项目默认 `watcher_enabled=false`。需要手动启用：

```bash
ath project update <项目名> --watcher-enabled true
```

### Q: 搜索结果被截断？

**A:** CLI 默认截断 300 字符，使用 `--full` 获取完整内容：

```bash
ath search hybrid <项目> <查询> --full
```

### Q: 如何重新索引项目？

**A:** 使用 reindex 命令：

```bash
ath project reindex <项目名>
```

### Q: 支持哪些嵌入模型？

**A:** 任何 Ollama 支持的嵌入模型，推荐：
- `bge-m3:latest` (中文，推荐)
- `nomic-embed-text` (英文)

---

## 🗺️ Roadmap

- [ ] 支持更多文档格式 (EPUB, RTF)
- [ ] 多语言支持 (英文、日文)
- [ ] 分布式部署方案
- [ ] Web UI 重构 (React + Tailwind)
- [ ] 更多 Reranker 模型支持
- [ ] 图谱索引 (Graph RAG)

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

---

## 📄 许可证

本项目采用 [MIT](LICENSE) 许可证。

---

## 🙏 致谢

- [Qdrant](https://qdrant.tech/) - 高性能向量数据库
- [Ollama](https://ollama.ai/) - 本地 LLM 运行环境
- [BGE Models](https://huggingface.co/BAAI) - 中文嵌入模型
- [FastAPI](https://fastapi.tiangolo.com/) - 现代 Web 框架

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/JK-Ai-Era">JK-Ai-Era</a>
</p>