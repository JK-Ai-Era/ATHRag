# RAG 系统记忆架构升级方案

基于 memory-systems 技能的最佳实践，为我们的 RAG 系统引入结构化记忆层。

---

## 一、现状分析

### 当前架构

```
┌─────────────────────────────────────────────────────────┐
│                    当前 RAG 架构                          │
├─────────────────────────────────────────────────────────┤
│  Working Memory (Context Window)                         │
│    └── 单次查询上下文                                     │
│                                                          │
│  Short-term Memory                                       │
│    └── ❌ 缺失                                            │
│                                                          │
│  Long-term Memory                                        │
│    └── Qdrant 向量存储 (文档片段)                          │
│                                                          │
│  Entity Memory                                           │
│    └── ❌ 缺失                                            │
│                                                          │
│  Temporal Memory                                         │
│    └── Watcher 文件监控 (原始事件)                         │
└─────────────────────────────────────────────────────────┘
```

### 核心问题

1. **只有文档级检索** - 无法回答"这个API在哪些项目里用过？"
2. **无实体关联** - 代码实体、人物、项目之间的关系无法追踪
3. **时序信息未结构化** - Watcher 记录了变更，但无法做时序查询
4. **检索模式单一** - 只有语义相似度，缺乏图谱遍历能力

---

## 二、目标架构设计

### 升级后架构

```
┌─────────────────────────────────────────────────────────┐
│                  升级后 RAG 架构                          │
├─────────────────────────────────────────────────────────┤
│  Layer 5: Temporal Knowledge Graph                       │
│    └── 时序事实图谱 (变更历史、时间旅行查询)                │
│                                                          │
│  Layer 4: Entity Graph                                   │
│    └── 实体关系图谱 (代码实体、人物、项目、API)              │
│                                                          │
│  Layer 3: Vector Store (Enhanced)                        │
│    └── 增强向量存储 (+ 实体标签、时间戳、关系ID)             │
│                                                          │
│  Layer 2: Document Store                                 │
│    └── 文档元数据 (+ 实体列表、变更历史)                    │
│                                                          │
│  Layer 1: Working Memory                                 │
│    └── 查询上下文 (+ 相关实体缓存)                         │
└─────────────────────────────────────────────────────────┘
```

---

## 三、分阶段实施计划

### Phase 1: 实体提取与索引 (2周)

**目标**: 从文档中提取关键实体，建立实体注册表

#### 3.1.1 实体类型定义

```python
# src/core/entity_types.py

class EntityType(Enum):
    # 代码实体
    CLASS = "class"           # 类定义
    FUNCTION = "function"     # 函数/方法
    API_ENDPOINT = "api"      # API 端点
    MODULE = "module"         # 模块/包
    
    # 人物实体
    PERSON = "person"         # 人名
    ORG = "organization"      # 组织
    
    # 项目实体
    PROJECT = "project"       # 项目名称
    TECHNOLOGY = "tech"       # 技术栈
    
    # 文档实体
    DOCUMENT = "document"     # 文档引用
```

#### 3.1.2 实体提取器

```python
# src/core/entity_extractor.py

class EntityExtractor:
    """从代码和文档中提取实体"""
    
    def extract_from_code(self, content: str, language: str) -> List[Entity]:
        """提取代码实体"""
        entities = []
        
        # 类定义提取
        if language in ['python', 'java', 'javascript', 'typescript']:
            class_pattern = r'(?:class|interface)\s+(\w+)'
            for match in re.finditer(class_pattern, content):
                entities.append(Entity(
                    name=match.group(1),
                    type=EntityType.CLASS,
                    line_number=content[:match.start()].count('\n') + 1
                ))
        
        # 函数/方法提取
        func_pattern = r'(?:def|function|async def)\s+(\w+)\s*\('
        for match in re.finditer(func_pattern, content):
            entities.append(Entity(
                name=match.group(1),
                type=EntityType.FUNCTION,
                line_number=content[:match.start()].count('\n') + 1
            ))
        
        # API 端点提取 (FastAPI/Flask/Django 模式)
        api_patterns = [
            r'@(?:app|router)\.(get|post|put|delete)\s*\(["\']([^"\']+)',  # FastAPI/Flask
            r'@route\s*\(["\']([^"\']+)',  # Flask
            r'path\s*\(\s*["\']([^"\']+)',  # Django
        ]
        
        return entities
    
    def extract_from_document(self, content: str) -> List[Entity]:
        """从文档中提取实体"""
        entities = []
        
        # 人名识别 (使用正则 + 常见中文/英文人名模式)
        # 技术栈识别 (关键词匹配)
        # 项目名识别 (基于上下文)
        
        return entities
```

#### 3.1.3 数据库扩展

```sql
-- 新增实体表
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    description TEXT,
    metadata JSON,  -- 额外信息，如代码位置、参数等
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, name, type)
);

-- 新增实体关系表
CREATE TABLE entity_relationships (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,  -- defines, calls, references, uses
    metadata JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES entities(id) ON DELETE CASCADE,
    UNIQUE(source_id, target_id, relation_type)
);

-- 新增片段-实体关联表
CREATE TABLE chunk_entities (
    chunk_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    occurrences INTEGER DEFAULT 1,  -- 出现次数
    PRIMARY KEY (chunk_id, entity_id),
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

-- 新增时序事件表 (基于 Watcher 事件)
CREATE TABLE temporal_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    entity_id TEXT,  -- 可选，关联的实体
    event_type TEXT NOT NULL,  -- created, modified, deleted, renamed
    event_data JSON,  -- 事件详情
    valid_from TIMESTAMP NOT NULL,
    valid_until TIMESTAMP,  -- NULL 表示当前有效
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE SET NULL
);
```

#### 3.1.4 集成点

在 `sync.py` 的 `_process_document` 方法中增加实体提取：

```python
async def _process_document(self, doc: DocumentModel, file_path: Path) -> None:
    # ... 原有处理逻辑 ...
    
    # 新增：实体提取
    if doc.doc_type == 'code':
        extractor = EntityExtractor()
        entities = extractor.extract_from_code(text, language=doc.language)
        
        # 保存实体并建立与片段的关联
        await self._save_entities(doc, chunks, chunk_records, entities)
```

---

### Phase 2: 图谱存储与检索 (2周)

**目标**: 引入图数据库，支持实体关系查询

#### 3.2.1 技术选型

| 方案 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| **NetworkX + SQLite** | 零依赖，易部署 | 性能有限 | ✅ Phase 2 选用 |
| **Neo4j** | 功能完整，性能好 | 需额外部署 | Phase 3 考虑 |
| **KuzuDB** | 嵌入式图DB，轻量 | 较新，生态小 | 备选 |

#### 3.2.2 NetworkX 实现

```python
# src/core/entity_graph.py

import networkx as nx
from pathlib import Path
import pickle

class EntityGraph:
    """项目级实体关系图谱"""
    
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.graph = nx.DiGraph()
        self._cache_path = Path(f"./data/graphs/{project_id}.pkl")
        self._load()
    
    def add_entity(self, entity: Entity) -> None:
        """添加实体节点"""
        self.graph.add_node(
            entity.id,
            name=entity.name,
            type=entity.type.value,
            description=entity.description,
            metadata=entity.metadata
        )
    
    def add_relationship(self, source_id: str, target_id: str, 
                        relation_type: str, metadata: dict = None) -> None:
        """添加关系边"""
        self.graph.add_edge(
            source_id, target_id,
            relation=relation_type,
            metadata=metadata or {}
        )
    
    def get_related_entities(self, entity_id: str, 
                            relation_type: str = None,
                            depth: int = 1) -> List[Entity]:
        """获取相关实体"""
        if relation_type:
            # 特定关系类型
            edges = [(u, v, d) for u, v, d in self.graph.edges(data=True) 
                    if d.get('relation') == relation_type]
            subgraph = nx.DiGraph()
            subgraph.add_edges_from(edges)
        else:
            subgraph = self.graph
        
        # BFS 遍历
        related = []
        for node in nx.bfs_tree(subgraph, entity_id, depth_limit=depth):
            if node != entity_id:
                data = self.graph.nodes[node]
                related.append(Entity(id=node, **data))
        
        return related
    
    def find_paths(self, source_id: str, target_id: str,
                   max_length: int = 3) -> List[List[str]]:
        """查找两个实体间的路径"""
        try:
            paths = list(nx.all_simple_paths(
                self.graph, source_id, target_id, 
                cutoff=max_length
            ))
            return paths
        except nx.NetworkXNoPath:
            return []
    
    def save(self) -> None:
        """持久化图谱"""
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._cache_path, 'wb') as f:
            pickle.dump(self.graph, f)
    
    def _load(self) -> None:
        """加载图谱"""
        if self._cache_path.exists():
            with open(self._cache_path, 'rb') as f:
                self.graph = pickle.load(f)
```

#### 3.2.3 增强检索服务

```python
# src/services/search_service.py

class EnhancedSearchService:
    """增强版检索服务"""
    
    def __init__(self):
        self.vector_store = VectorStore()
        self.entity_graph = None  # 按需加载
    
    async def hybrid_search(self, project_id: str, query: str, 
                          search_type: SearchType = SearchType.SEMANTIC) -> SearchResult:
        """
        混合检索：语义 + 实体 + 关键词
        """
        results = []
        
        # 1. 语义检索 (原有功能)
        semantic_results = await self._semantic_search(project_id, query)
        results.extend(semantic_results)
        
        # 2. 实体检索 (新增)
        if search_type in [SearchType.ENTITY, SearchType.HYBRID]:
            entity_results = await self._entity_search(project_id, query)
            results.extend(entity_results)
        
        # 3. 关键词检索 (BM25)
        if search_type in [SearchType.KEYWORD, SearchType.HYBRID]:
            keyword_results = await self._keyword_search(project_id, query)
            results.extend(keyword_results)
        
        # 4. 重排序 (Rerank)
        return self._rerank_results(results, query)
    
    async def _entity_search(self, project_id: str, query: str) -> List[SearchResult]:
        """基于实体的检索"""
        # 从查询中提取实体
        entities = self._extract_entities_from_query(query)
        
        if not entities:
            return []
        
        # 加载项目图谱
        graph = EntityGraph(project_id)
        
        results = []
        for entity_name in entities:
            # 查找实体
            entity = self._find_entity(project_id, entity_name)
            if not entity:
                continue
            
            # 获取相关实体
            related = graph.get_related_entities(entity.id, depth=2)
            
            # 获取包含这些实体的片段
            for rel_entity in related:
                chunks = self._get_chunks_by_entity(rel_entity.id)
                for chunk in chunks:
                    results.append(SearchResult(
                        content=chunk.content,
                        source=chunk.document.filename,
                        score=0.8,  # 实体匹配基础分
                        match_type="entity",
                        matched_entity=rel_entity.name
                    ))
        
        return results
    
    async def multi_hop_search(self, project_id: str, 
                              start_entity: str, 
                              end_entity: str) -> List[SearchResult]:
        """
        多跳推理检索
        例如："investor-deck 项目里用到哪些内部工具？"
        """
        graph = EntityGraph(project_id)
        
        # 查找实体
        start = self._find_entity(project_id, start_entity)
        end = self._find_entity(project_id, end_entity)
        
        if not start or not end:
            return []
        
        # 查找路径
        paths = graph.find_paths(start.id, end.id, max_length=3)
        
        results = []
        for path in paths:
            # 获取路径上所有实体的相关信息
            path_entities = [graph.graph.nodes[node] for node in path]
            path_description = " -> ".join([e['name'] for e in path_entities])
            
            # 获取关联片段
            for node_id in path:
                chunks = self._get_chunks_by_entity(node_id)
                for chunk in chunks:
                    results.append(SearchResult(
                        content=chunk.content,
                        source=chunk.document.filename,
                        score=0.9,
                        match_type="multi_hop",
                        path=path_description
                    ))
        
        return results
```

---

### Phase 3: 时序记忆层 (1周)

**目标**: 将 Watcher 事件升级为时序事实图谱

#### 3.3.1 时序事件处理器

```python
# src/watcher/temporal_handler.py

from datetime import datetime
from typing import Optional

class TemporalEventHandler:
    """处理文件变更的时序事件"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def record_event(self, project_id: str, event_type: str,
                    file_path: str, entity_id: str = None,
                    diff_content: str = None) -> TemporalEvent:
        """记录时序事件"""
        
        # 查找该文件/实体的当前有效事件，标记为过期
        if entity_id:
            current_events = self.db.query(TemporalEvent).filter(
                TemporalEvent.entity_id == entity_id,
                TemporalEvent.valid_until.is_(None)
            ).all()
            
            for event in current_events:
                event.valid_until = datetime.utcnow()
        
        # 创建新事件
        event = TemporalEvent(
            id=str(uuid4()),
            project_id=project_id,
            entity_id=entity_id,
            event_type=event_type,  # created, modified, deleted
            event_data={
                'file_path': file_path,
                'diff': diff_content,
                'timestamp': datetime.utcnow().isoformat()
            },
            valid_from=datetime.utcnow(),
            valid_until=None  # 当前有效
        )
        
        self.db.add(event)
        self.db.commit()
        
        return event
    
    def query_at_time(self, project_id: str, entity_id: str,
                     query_time: datetime) -> Optional[TemporalEvent]:
        """时间旅行查询：查询某个时间点的状态"""
        event = self.db.query(TemporalEvent).filter(
            TemporalEvent.project_id == project_id,
            TemporalEvent.entity_id == entity_id,
            TemporalEvent.valid_from <= query_time,
            (TemporalEvent.valid_until > query_time) | 
            (TemporalEvent.valid_until.is_(None))
        ).order_by(TemporalEvent.valid_from.desc()).first()
        
        return event
    
    def get_change_history(self, project_id: str, entity_id: str,
                          limit: int = 10) -> List[TemporalEvent]:
        """获取实体的变更历史"""
        events = self.db.query(TemporalEvent).filter(
            TemporalEvent.project_id == project_id,
            TemporalEvent.entity_id == entity_id
        ).order_by(TemporalEvent.valid_from.desc()).limit(limit).all()
        
        return events
```

#### 3.3.2 集成到 Watcher

```python
# src/watcher/handler.py

class FileChangeHandler:
    """增强的文件变更处理器"""
    
    def __init__(self, project_id: str, db: Session):
        self.project_id = project_id
        self.db = db
        self.file_sync = FileSync(db, project_id)
        self.temporal_handler = TemporalEventHandler(db)
        self.debouncer = EventDebouncer()
    
    async def on_modified(self, file_path: Path) -> None:
        """文件修改处理"""
        relative_path = self._get_relative_path(file_path)
        
        # 获取文件差异 (如果是文本文件)
        diff = self._get_file_diff(file_path)
        
        # 同步到 RAG
        result = await self.file_sync.sync_file(file_path, relative_path)
        
        # 记录时序事件
        if result.get('doc_id'):
            doc = self.db.query(DocumentModel).get(result['doc_id'])
            
            # 查找关联的实体
            entities = self._get_document_entities(doc.id)
            
            for entity in entities:
                self.temporal_handler.record_event(
                    project_id=self.project_id,
                    event_type='modified',
                    file_path=str(file_path),
                    entity_id=entity.id,
                    diff_content=diff
                )
```

---

### Phase 4: API 与 UI 升级 (1周)

**目标**: 提供新的检索接口和可视化

#### 3.4.1 新增 API 端点

```python
# src/rag_api/routers/memory.py

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])

class EntitySearchRequest(BaseModel):
    project_id: str
    entity_name: str
    relation_type: Optional[str] = None
    depth: int = 1

class MultiHopSearchRequest(BaseModel):
    project_id: str
    start_entity: str
    end_entity: str
    max_hops: int = 3

class TemporalQueryRequest(BaseModel):
    project_id: str
    entity_name: str
    query_time: datetime

@router.post("/entities/search")
async def search_by_entity(request: EntitySearchRequest):
    """实体检索：查找与指定实体相关的所有内容"""
    service = EnhancedSearchService()
    results = await service.entity_search(
        request.project_id,
        request.entity_name,
        request.relation_type,
        request.depth
    )
    return {"results": results}

@router.post("/entities/multi-hop")
async def multi_hop_search(request: MultiHopSearchRequest):
    """多跳推理检索：查找两个实体间的关联"""
    service = EnhancedSearchService()
    results = await service.multi_hop_search(
        request.project_id,
        request.start_entity,
        request.end_entity,
        request.max_hops
    )
    return {"results": results, "paths": results.get("paths")}

@router.post("/temporal/query")
async def temporal_query(request: TemporalQueryRequest):
    """时序查询：查询某个时间点的状态"""
    handler = TemporalEventHandler()
    event = handler.query_at_time(
        request.project_id,
        request.entity_name,
        request.query_time
    )
    return {"event": event}

@router.get("/entities/{project_id}/graph")
async def get_entity_graph(project_id: str, entity_name: str):
    """获取实体关系图谱（用于可视化）"""
    graph = EntityGraph(project_id)
    
    # 查找中心实体
    center = None
    for node, data in graph.graph.nodes(data=True):
        if data.get('name') == entity_name:
            center = node
            break
    
    if not center:
        return {"error": "Entity not found"}
    
    # 获取2度关系内的子图
    subgraph = nx.ego_graph(graph.graph, center, radius=2)
    
    # 转换为前端友好的格式
    nodes = [{"id": n, **d} for n, d in subgraph.nodes(data=True)]
    edges = [{"source": u, "target": v, **d} for u, v, d in subgraph.edges(data=True)]
    
    return {"nodes": nodes, "edges": edges}
```

#### 3.4.2 Web UI 新增页面

```
web/my-app/app/
├── memory/               # 新增：记忆管理模块
│   ├── entities/         # 实体浏览器
│   │   └── page.tsx
│   ├── graph/            # 关系图谱可视化
│   │   └── page.tsx
│   └── timeline/         # 时序时间线
│       └── page.tsx
└── search/
    └── page.tsx          # 搜索页增强（实体筛选、多跳搜索）
```

---

## 四、数据迁移策略

### 4.1 现有数据处理

```python
# scripts/migrate_to_memory_system.py

async def migrate_existing_documents():
    """为现有文档提取实体"""
    db = get_db_session()
    
    # 获取所有现有文档
    documents = db.query(DocumentModel).all()
    
    extractor = EntityExtractor()
    
    for doc in documents:
        # 读取文档内容
        file_path = Path(doc.file_path)
        if not file_path.exists():
            continue
        
        content = file_path.read_text(encoding='utf-8', errors='ignore')
        
        # 提取实体
        if doc.doc_type == 'code':
            entities = extractor.extract_from_code(content, doc.language)
        else:
            entities = extractor.extract_from_document(content)
        
        # 保存实体
        for entity in entities:
            # 检查是否已存在
            existing = db.query(Entity).filter(
                Entity.project_id == doc.project_id,
                Entity.name == entity.name,
                Entity.type == entity.type
            ).first()
            
            if not existing:
                new_entity = Entity(
                    id=str(uuid4()),
                    project_id=doc.project_id,
                    name=entity.name,
                    type=entity.type,
                    description=entity.description,
                    metadata=entity.metadata
                )
                db.add(new_entity)
                db.commit()
                existing = new_entity
            
            # 建立与片段的关联
            for chunk in doc.chunks:
                if entity.name in chunk.content:
                    assoc = ChunkEntity(
                        chunk_id=chunk.id,
                        entity_id=existing.id
                    )
                    db.add(assoc)
        
        db.commit()
        
        # 为项目构建图谱
        graph = EntityGraph(doc.project_id)
        # ... 构建关系 ...
        graph.save()
```

---

## 五、性能与存储预估

### 5.1 存储开销

| 数据类型 | 预估大小 | 说明 |
|---------|---------|------|
| 实体表 | ~10MB/万实体 | SQLite |
| 关系表 | ~20MB/万关系 | SQLite |
| 图谱缓存 | ~50MB/项目 | NetworkX pickle |
| 时序事件 | ~5MB/万事件 | SQLite |
| **总计** | **~100MB** | 5个项目，每项目500文件 |

### 5.2 性能指标

| 操作 | 目标延迟 | 当前对比 |
|------|---------|---------|
| 实体提取 (单文件) | < 100ms | 新增 |
| 实体检索 | < 200ms | 新增 |
| 多跳推理 (2跳) | < 500ms | 新增 |
| 时序查询 | < 100ms | 新增 |
| 语义检索 | < 300ms | 保持 |

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 实体提取准确性低 | 高 | 使用LLM辅助提取，人工审核关键实体 |
| 图谱构建慢 | 中 | 异步构建，后台任务 |
| 存储膨胀 | 中 | 定期合并、压缩，清理历史版本 |
| 查询复杂度爆炸 | 中 | 限制搜索深度，超时机制 |

---

## 七、验收标准

- [ ] 代码文件能自动提取类、函数、API端点
- [ ] 能通过实体名搜索到相关文档片段
- [ ] 支持"查找使用这个API的所有地方"类查询
- [ ] 支持"3月1号的时候这个模块是怎么实现的"类时序查询
- [ ] Web UI 能展示实体关系图谱
- [ ] 原有语义检索性能不下降

---

**预计总工期**: 6 周
**核心收益**: 从"文档检索"升级为"知识推理"
