# MCP 配置指南

ATHRag系统的 MCP (Model Context Protocol) Server，为 Agent 提供标准化的工具接口。

**设计原则**：
- 保留现有 API 不变，通过 MCP 协议暴露功能
- 所有工具返回 JSON 格式，便于 Agent 解析
- Agent 负责推理，RAG 只负责检索

## 可用工具

### 1. rag_search
搜索指定项目的知识库。

**参数**：
- `project` (string): 项目名称或ID
- `query` (string): 搜索查询内容
- `top_k` (integer, optional): 返回结果数量，默认5，最大20

**返回示例**：
```json
{
  "project": "yunxi",
  "project_id": "0cfa29af-b3ea-494d-ab5d-bda854b4d07d",
  "query": "报表统计逻辑",
  "total": 5,
  "time_ms": 85,
  "results": [
    {
      "content": "销售报表统计逻辑：...",
      "score": 0.923,
      "source": "销售报表说明.pdf",
      "document_id": "doc-uuid"
    }
  ]
}
```

### 2. rag_list_projects
列出所有知识库项目。

**参数**：无

**返回示例**：
```json
{
  "projects": [
    {
      "id": "uuid",
      "name": "yunxi",
      "description": "云锡数据治理项目",
      "document_count": 396,
      "chunk_count": 38077
    }
  ]
}
```

### 3. rag_get_project_info
获取指定项目的详细信息。

**参数**：
- `project` (string): 项目名称或ID

### 4. rag_list_documents
列出项目下的所有文档。

**参数**：
- `project` (string): 项目名称或ID

**返回示例**：
```json
{
  "project": "yunxi",
  "project_id": "uuid",
  "documents": [
    {
      "id": "doc-uuid",
      "filename": "报表说明.pdf",
      "doc_type": "application/pdf",
      "file_size": 1024000,
      "file_path": "data/projects/.../报表说明.pdf",
      "chunk_count": 15,
      "status": "completed"
    }
  ]
}
```

### 5. rag_export_document
导出文档的完整解析内容。

**参数**：
- `project` (string): 项目名称或ID
- `document_id` (string): 文档ID

**使用场景**：Agent 需要对单个文档做深度分析时。

### 6. rag_upload_document
上传文档到指定项目。

**参数**：
- `project` (string): 项目名称或ID
- `file_path` (string): 本地文件绝对路径

**使用场景**：Agent 自动索引工作目录中的新文件。

---

## 配置方法

### Claude Code

1. 打开 Claude Code 设置：`claude config`
2. 添加 MCP Server：

```json
{
  "mcpServers": {
    "ATHRag": {
      "command": "bash",
      "args": [
        "-c",
        "cd ~/Projects/ATHRag && source .venv/bin/activate && python -m src.mcp.server"
      ]
    }
  }
}
```

3. 重启 Claude Code

### Cursor / Windsurf

将 `mcp-config.json` 的内容添加到编辑器的 MCP 配置中。

### 直接使用

```python
from mcp import ClientSession

# 连接到 MCP Server
# 然后调用工具...
```

---

## Agent 使用示例

Agent 在分析项目时的工作流程：

```
用户：分析一下云锡项目的报表逻辑

Agent:
1. rag_list_projects() 
   → 确认 "yunxi" 项目存在

2. rag_search(project="yunxi", query="报表统计逻辑")
   → 获取相关文档片段

3. 基于检索内容生成分析
   → "根据销售报表说明.pdf，统计逻辑是..."
```

Agent 上传新文件：

```
Agent:
1. rag_upload_document(
     project="yunxi", 
     file_path="/Users/.../新增报表.pdf"
   )
   → 文档上传并自动索引

2. rag_search(project="yunxi", query="新增报表内容")
   → 立即搜索新上传的文档
```

---

## 故障排查

### MCP Server 无法启动

```bash
# 测试启动
cd ~/Projects/ATHRag
source .venv/bin/activate
python -m src.mcp.server

# 检查依赖
pip list | grep mcp
```

### 服务依赖检查

MCP Server 依赖后端服务，确保以下服务运行：

```bash
# 检查服务状态
~/Projects/ATHRag/scripts/service.sh status

# 应该看到：
# ✓ Qdrant (localhost:6333)
# ✓ RAG API (localhost:8000)
# ✓ Ollama (localhost:11434)
```

### 工具调用失败

如果工具返回错误，检查：
1. 项目ID/名称是否正确
2. 文件路径是否存在且可访问
3. 后端服务是否正常运行

---

## 与 rag-kb 技能的关系

| 方式 | 适用场景 |
|------|---------|
| **rag-kb 技能** | OpenClaw 内部使用，命令行快捷操作 |
| **MCP Server** | 跨平台 Agent 集成，标准化接口 |

两者底层调用相同的 RAG API，功能一致，只是接入方式不同。
