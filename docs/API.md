# ATHRag API 文档

## 基础信息

- **基础 URL**: `http://localhost:8000`
- **API 文档**: `http://localhost:8000/docs`
- **OpenAPI 规范**: `http://localhost:8000/openapi.json`

## 认证

当前版本无认证，直接访问即可。

## API 端点

### 健康检查

```
GET /health
```

**响应：**
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

### 项目管理

#### 创建项目

```
POST /api/v1/projects
```

**请求体：**
```json
{
  "name": "项目名称",
  "description": "项目描述"
}
```

**响应：**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "name": "项目名称",
    "description": "项目描述",
    "document_count": 0,
    "chunk_count": 0,
    "created_at": "2026-02-26T10:00:00",
    "updated_at": "2026-02-26T10:00:00"
  }
}
```

#### 列出项目

```
GET /api/v1/projects
```

**查询参数：**
- `skip` (int): 跳过数量，默认 0
- `limit` (int): 返回数量，默认 100

#### 获取项目详情

```
GET /api/v1/projects/{project_id}
```

#### 更新项目

```
PUT /api/v1/projects/{project_id}
```

**请求体：**
```json
{
  "name": "新名称",
  "description": "新描述"
}
```

#### 删除项目

```
DELETE /api/v1/projects/{project_id}
```

### 文档管理

#### 上传文档

```
POST /api/v1/projects/{project_id}/documents
```

**Content-Type:** `multipart/form-data`

**表单字段：**
- `file` (file): 文档文件
- `metadata` (string, optional): JSON 格式的元数据

#### 批量上传

```
POST /api/v1/projects/{project_id}/documents/batch
```

**表单字段：**
- `files` (files): 多个文档文件

#### 列出文档

```
GET /api/v1/projects/{project_id}/documents
```

#### 删除文档

```
DELETE /api/v1/projects/{project_id}/documents/{document_id}
```

#### 重新索引

```
POST /api/v1/projects/{project_id}/documents/{document_id}/reindex
```

### 搜索

#### 高级搜索

```
POST /api/v1/search
```

**请求体：**
```json
{
  "project_id": "uuid",
  "query": "搜索内容",
  "top_k": 10,
  "search_mode": "hybrid",
  "score_threshold": 0.7,
  "filters": {
    "doc_type": ["pdf", "md"]
  },
  "rerank": true
}
```

**参数说明：**
- `project_id` (string, required): 项目ID
- `query` (string, required): 查询内容
- `top_k` (integer, optional): 返回数量，默认 10
- `search_mode` (string, optional): 搜索模式
  - `semantic`: 仅语义搜索
  - `keyword`: 仅关键词搜索
  - `hybrid`: 混合搜索（默认）
- `score_threshold` (float, optional): 分数阈值
- `filters` (object, optional): 过滤条件
- `rerank` (boolean, optional): 是否重排序

**响应：**
```json
{
  "success": true,
  "data": {
    "query": "搜索内容",
    "project_id": "uuid",
    "results": [
      {
        "content": "文档内容片段",
        "score": 0.89,
        "search_type": "semantic",
        "metadata": {
          "filename": "doc.md"
        },
        "document_id": "uuid",
        "chunk_id": "uuid"
      }
    ],
    "total": 10,
    "query_time_ms": 45
  }
}
```

#### 简单搜索

```
GET /api/v1/search/simple?project_id={id}&q={query}&top_k=10
```

## 错误处理

所有错误响应格式：

```json
{
  "success": false,
  "message": "错误描述",
  "data": null
}
```

**HTTP 状态码：**
- `200`: 成功
- `400`: 请求参数错误
- `404`: 资源不存在
- `500`: 服务器内部错误

## 使用示例

### Python

```python
import requests

# 创建项目
response = requests.post(
    "http://localhost:8000/api/v1/projects",
    json={"name": "我的项目", "description": "测试"}
)
project_id = response.json()["data"]["id"]

# 搜索
response = requests.post(
    "http://localhost:8000/api/v1/search",
    json={
        "project_id": project_id,
        "query": "系统架构",
        "top_k": 5
    }
)
results = response.json()["data"]["results"]
```

### cURL

```bash
# 创建项目
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "测试项目"}'

# 搜索
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "uuid",
    "query": "系统组件",
    "top_k": 5
  }'
```
