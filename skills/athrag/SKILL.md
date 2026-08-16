---
name: athrag
description: |
  ATHRag 知识库系统操作工具。
  触发条件（满足任一）：
  - 搜索/查询知识库中的文档
  - 创建/列出/删除知识库项目
  - 上传/删除/重新索引文档
  - 管理文件监控（watcher 启停、同步控制）
  - 查看知识库系统状态
  不触发：查代码实现、函数定义、变量查找（用 grep）
---

# ATHRag 知识库系统

本地 RAG 知识库，支持多项目文档的语义搜索、混合搜索、文件监控和自动索引。

## 前置条件

- API 地址：`http://localhost:16250`
- 认证：当前未启用，直接调用即可

## RAG vs grep 选择

- **RAG**：概念查询、设计思路、需求文档、业务场景、项目概况
- **grep/rg**：函数定义、变量查找、代码实现、配置项、精确匹配

## 获取项目列表

```bash
curl -s http://localhost:16250/api/v1/projects | python3 -m json.tool
```

返回 `id`（即 project_id）、`name`、`document_count`、`chunk_count`、`watcher_enabled`

## 搜索知识库

### 简单搜索（推荐）

```bash
curl -s "http://localhost:16250/api/v1/search/simple?project_id=<PROJECT_ID>&q=<查询>&top_k=10" | python3 -m json.tool
```

### 高级搜索

```bash
curl -s -X POST http://localhost:16250/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "<PROJECT_ID>",
    "query": "查询内容",
    "top_k": 20,
    "search_mode": "hybrid",
    "rerank": true,
    "query_transform": "none",
    "context_compress": false
  }' | python3 -m json.tool
```

| 参数 | 默认 | 说明 |
|------|------|------|
| search_mode | hybrid | `hybrid`/`vector`/`bm25` |
| rerank | true | bge-reranker-v2-m3 重排序，提高质量但增加延迟 |
| query_transform | none | `none`/`hyde`/`multi_query`/`sub_query`/`combined`，需 LLM |
| context_compress | false | 上下文压缩，提取相关内容减少噪音 |
| top_k | 20 | 返回数量（1-100） |
| score_threshold | None | 分数阈值（0-1） |

**分数参考**：≥0.80 高度相关，0.60-0.80 中等，<0.60 低相关

## 项目管理

```bash
# 创建项目
curl -s -X POST http://localhost:16250/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "项目名", "description": "描述"}' | python3 -m json.tool

# 项目详情
curl -s http://localhost:16250/api/v1/projects/<PROJECT_ID> | python3 -m json.tool

# 更新项目
curl -s -X PUT http://localhost:16250/api/v1/projects/<PROJECT_ID> \
  -H "Content-Type: application/json" \
  -d '{"name": "新名", "description": "新描述"}' | python3 -m json.tool

# 删除项目（不可恢复，清除所有关联数据）
curl -s -X DELETE http://localhost:16250/api/v1/projects/<PROJECT_ID> | python3 -m json.tool
```

## 文档管理

```bash
# 列出文档
curl -s "http://localhost:16250/api/v1/<PROJECT_ID>/documents?page=1&page_size=50" | python3 -m json.tool

# 上传文档
curl -s -X POST http://localhost:16250/api/v1/<PROJECT_ID>/documents \
  -F "file=@/path/to/doc.pdf" | python3 -m json.tool

# 批量上传
curl -s -X POST http://localhost:16250/api/v1/<PROJECT_ID>/documents/batch \
  -F "files=@/a.pdf" -F "files=@/b.md" | python3 -m json.tool

# 删除文档
curl -s -X DELETE http://localhost:16250/api/v1/<PROJECT_ID>/documents/<DOC_ID> | python3 -m json.tool

# 重新索引
curl -s -X POST http://localhost:16250/api/v1/<PROJECT_ID>/documents/<DOC_ID>/reindex | python3 -m json.tool

# 支持的格式
curl -s http://localhost:16250/api/v1/parsers/formats | python3 -m json.tool
```

## Watcher 管理

```bash
# 状态
curl -s http://localhost:16250/api/v1/watcher/status | python3 -m json.tool

# 启停
curl -s -X POST http://localhost:16250/api/v1/watcher/start | python3 -m json.tool
curl -s -X POST http://localhost:16250/api/v1/watcher/stop | python3 -m json.tool

# 开启/关闭项目的自动同步
curl -s -X POST http://localhost:16250/api/v1/watcher/refresh \
  -H "Content-Type: application/json" \
  -d '{"project_name": "项目名", "watcher_enabled": true}' | python3 -m json.tool

# 强制扫描（不传 project_name 扫描所有）
curl -s -X POST http://localhost:16250/api/v1/watcher/scan \
  -H "Content-Type: application/json" \
  -d '{"project_name": "项目名"}' | python3 -m json.tool
```

## 搜索结果处理

搜索返回的 `content` 是匹配的文本片段，`filename` 是来源文件名。引用时注明来源。如需完整上下文，可用 `read` 工具读取源文件。
