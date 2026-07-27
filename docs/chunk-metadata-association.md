# 元数据与分块关联方案

## 核心问题

```
文档级别提取的元数据:
- title: 客户主数据标准
- version: 2.0
- phase: 蓝图设计
- logical_id: customer-master-data

        │ 如何传递?
        ▼
        
分块1              分块2              分块3
├── 范围定义       ├── 数据项定义      ├── 接口规范
├── 客户主数据...   ├── 客户编码规则...  ├── API设计...

需要每个分块都知道:
- 属于 customer-master-data v2.0
- 位于蓝图设计阶段
- 在文档中的章节位置
```

## 数据模型设计

### 1. 资料实体表（Artifact）- 新增

```python
# 一个资料可以跨多个文档版本
class Artifact(Base):
    __tablename__ = 'artifacts'
    
    id = Column(String(36), primary_key=True)  # UUID
    logical_id = Column(String(255), index=True)  # 逻辑标识，如 customer-master-data
    name = Column(String(500))  # 显示名称
    type = Column(String(50))   # indicator | data_standard | process | api_spec
    
    # 当前有效版本（缓存，便于查询）
    current_version = Column(String(50))
    current_doc_id = Column(String(36), ForeignKey('documents.id'))
    
    # 项目维度（JSON存储，灵活扩展）
    dimensions = Column(JSON)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    
    # 关系
    versions = relationship("Document", back_populates="artifact")
```

### 2. 文档表（Document）- 增强

```python
class Document(Base):
    __tablename__ = 'documents'
    
    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey('projects.id'))
    file_path = Column(String(1000))
    file_name = Column(String(500))
    
    # 关联到资料实体
    artifact_id = Column(String(36), ForeignKey('artifacts.id'), nullable=True)
    artifact = relationship("Artifact", back_populates="versions")
    
    # 版本信息
    version = Column(String(50))  # 2.0
    effective_date = Column(DateTime)
    status = Column(String(20))   # active | superseded | draft
    
    # 取代关系
    supersedes_doc_id = Column(String(36), ForeignKey('documents.id'))
    
    # 提取的完整元数据
    extracted_metadata = Column(JSON)
    
    # 统计
    chunk_count = Column(Integer, default=0)
    
    # 关系
    chunks = relationship("DocumentChunk", back_populates="document")
```

### 3. 分块表（DocumentChunk）- 增强

```python
class DocumentChunk(Base):
    __tablename__ = 'document_chunks'
    
    # 原有字段
    id = Column(String(36), primary_key=True)
    document_id = Column(String(36), ForeignKey('documents.id'))
    document = relationship("Document", back_populates="chunks")
    
    content = Column(Text)
    embedding = Column(Vector(1024))
    
    # 位置信息
    chunk_index = Column(Integer)  # 第几个分块
    page_number = Column(Integer)
    
    # === 新增：继承的文档级元数据（冗余存储，便于检索过滤）===
    
    # 资料实体信息
    artifact_id = Column(String(36), ForeignKey('artifacts.id'), index=True)
    artifact_logical_id = Column(String(255), index=True)  # customer-master-data
    artifact_name = Column(String(500))
    artifact_type = Column(String(50))
    
    # 版本信息
    doc_version = Column(String(50), index=True)  # 2.0
    doc_status = Column(String(20), index=True)   # active
    
    # 项目维度（从文档继承）
    dim_phase = Column(String(50), index=True)
    dim_domain = Column(String(50), index=True)
    dim_maturity = Column(String(50))
    
    # === 新增：分块特有元数据 ===
    
    # 在文档结构中的位置
    section_title = Column(String(500))   # 所属章节标题
    section_level = Column(Integer)       # 章节层级（1=一级标题）
    section_path = Column(String(1000))   # 完整路径："1.范围定义>1.1客户定义"
    
    # 内容角色
    content_role = Column(String(50))     # definition | example | background | procedure
    
    # 实体引用（可选，用于精确关联）
    entity_refs = Column(JSON)  # ["IND-001", "DATA-002"]
    
    # 完整元数据（JSONB，包含所有信息）
    metadata = Column(JSONB)
    
    # 创建时间（用于时间旅行查询）
    created_at = Column(DateTime, default=datetime.utcnow)
```

## 元数据传递流程

```
┌─────────────────────────────────────────────────────────────┐
│  1. 文档解析 + 元数据提取                                      │
│     - 提取文档级元数据：title, version, phase, logical_id     │
│     - 解析章节结构                                            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  2. 资料实体管理                                              │
│     - 查找或创建 Artifact（通过 logical_id）                  │
│     - 如果 version 更新，更新 Artifact.current_version       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  3. 智能分块（继承元数据）                                     │
│     - 每个 chunk 继承 document 的元数据                        │
│     - 添加 chunk 特有元数据：section_title, content_role       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  4. 存储到数据库                                              │
│     - Document 表：保存文档级信息                              │
│     - DocumentChunk 表：每个 chunk 带完整元数据                 │
└─────────────────────────────────────────────────────────────┘
```

## 分块时的元数据增强

```python
class SmartChunker:
    """智能分块器：在分块时添加位置和内容元数据"""
    
    def chunk_with_metadata(
        self,
        parsed_doc: ParsedDocument,
        doc_metadata: DocumentMetadata,
        artifact: Artifact
    ) -> List[DocumentChunk]:
        """
        分块并附加完整元数据
        """
        chunks = []
        
        # 分块（保持原有逻辑）
        text_chunks = self._split_text(parsed_doc.text)
        
        for idx, chunk_text in enumerate(text_chunks):
            # 确定这个 chunk 在文档结构中的位置
            section_info = self._locate_in_structure(
                chunk_text, 
                parsed_doc.sections
            )
            
            # 确定内容角色
            content_role = self._classify_content_role(
                chunk_text,
                section_info
            )
            
            # 创建带完整元数据的 chunk
            chunk = DocumentChunk(
                # 基础信息
                id=generate_uuid(),
                chunk_index=idx,
                content=chunk_text,
                
                # 继承的文档级元数据（全部冗余存储）
                artifact_id=artifact.id,
                artifact_logical_id=artifact.logical_id,
                artifact_name=artifact.name,
                artifact_type=artifact.type,
                doc_version=doc_metadata.version,
                doc_status=doc_metadata.status,
                dim_phase=doc_metadata.dimensions.get('phase'),
                dim_domain=doc_metadata.dimensions.get('domain'),
                
                # 分块特有元数据
                section_title=section_info.title,
                section_level=section_info.level,
                section_path=section_info.path,
                content_role=content_role,
                
                # 完整元数据打包
                metadata={
                    'artifact': {
                        'id': artifact.id,
                        'logical_id': artifact.logical_id,
                        'name': artifact.name,
                        'type': artifact.type,
                    },
                    'document': {
                        'version': doc_metadata.version,
                        'phase': doc_metadata.dimensions.get('phase'),
                        'date': doc_metadata.effective_date.isoformat(),
                        'source_file': doc_metadata.file_name,
                    },
                    'location': {
                        'section': section_info.title,
                        'section_path': section_info.path,
                        'chunk_index': idx,
                    },
                    'content': {
                        'role': content_role,
                        'char_count': len(chunk_text),
                    }
                }
            )
            
            chunks.append(chunk)
        
        return chunks
    
    def _locate_in_structure(self, chunk_text: str, sections: List[ParsedSection]) -> SectionInfo:
        """
        确定 chunk 属于哪个章节
        """
        # 简单匹配：chunk 内容包含章节标题
        for section in sections:
            if section.title in chunk_text[:200]:  # 看 chunk 开头
                return SectionInfo(
                    title=section.title,
                    level=section.level,
                    path=self._build_section_path(section, sections)
                )
        
        # 找不到则继承上一个 chunk 的章节
        return SectionInfo(title="未分类", level=0, path="")
    
    def _classify_content_role(self, chunk_text: str, section_info: SectionInfo) -> str:
        """
        分类内容角色
        """
        text_lower = chunk_text.lower()
        section_lower = section_info.title.lower()
        
        # 根据章节标题判断
        if any(kw in section_lower for kw in ['定义', '术语', '说明']):
            return 'definition'
        
        if any(kw in section_lower for kw in ['示例', '案例', '举例']):
            return 'example'
        
        if any(kw in section_lower for kw in ['背景', '现状', '引言']):
            return 'background'
        
        if any(kw in section_lower for kw in ['流程', '步骤', '操作']):
            return 'procedure'
        
        if any(kw in section_lower for kw in ['规则', '规范', '要求']):
            return 'rule'
        
        # 根据内容特征判断
        if re.search(r'例如[：:]', text_lower):
            return 'example'
        
        if re.search(r'^[\d一二三四五六七八九十]+[、.．]', chunk_text.strip()):
            return 'list_item'
        
        return 'content'
```

## 检索时的元数据利用

### 1. 默认检索（只返回最新版本）

```python
def search_latest_version(query: str, project_id: str):
    """
    默认检索：每个资料只返回最新 active 版本
    """
    # 1. 向量检索（先不过滤，保证召回率）
    candidates = vector_search(
        query=query,
        filter={"project_id": project_id},
        top_k=100
    )
    
    # 2. 按 artifact_logical_id 分组，只保留每组最高版本
    best_chunks = {}
    for chunk in candidates:
        key = chunk.artifact_logical_id
        
        if key not in best_chunks:
            best_chunks[key] = chunk
        else:
            # 比较版本，保留更新的
            if compare_versions(chunk.doc_version, best_chunks[key].doc_version) > 0:
                best_chunks[key] = chunk
    
    return list(best_chunks.values())
```

### 2. 版本感知检索（显示所有版本）

```python
def search_with_versions(query: str, project_id: str):
    """
    显示同一资料的所有版本，标记冲突
    """
    candidates = vector_search(query=query, top_k=100)
    
    # 按 artifact 分组
    groups = defaultdict(list)
    for chunk in candidates:
        groups[chunk.artifact_logical_id].append(chunk)
    
    results = []
    for logical_id, chunks in groups.items():
        # 按版本排序
        sorted_chunks = sorted(chunks, key=lambda c: c.doc_version, reverse=True)
        
        results.append({
            'artifact': {
                'logical_id': logical_id,
                'name': chunks[0].artifact_name,
            },
            'versions': [
                {
                    'version': c.doc_version,
                    'phase': c.dim_phase,
                    'status': c.doc_status,
                    'content': c.content[:200],
                    'section': c.section_title,
                }
                for c in sorted_chunks
            ],
            'has_conflict': len(sorted_chunks) > 1 and 
                           all(c.doc_status == 'active' for c in sorted_chunks[:2])
        })
    
    return results
```

### 3. 维度过滤检索

```python
def search_with_dimension_filter(
    query: str,
    project_id: str,
    dimensions: Dict[str, Union[str, List[str]]]
):
    """
    按项目维度过滤
    """
    filters = {"project_id": project_id}
    
    for dim, value in dimensions.items():
        column = f"dim_{dim}"
        if isinstance(value, list):
            filters[f"{column}_in"] = value
        else:
            filters[column] = value
    
    # 向量 + 元数据过滤
    return vector_search(query=query, filter=filters, top_k=20)

# 使用示例
search_with_dimension_filter(
    "客户数据标准",
    project_id="yunxi",
    dimensions={
        "phase": ["蓝图设计", "详细设计"],
        "domain": "销售"
    }
)
```

### 4. 时间旅行检索

```python
def search_as_of(query: str, project_id: str, as_of_date: datetime):
    """
    查询某时间点的有效版本
    """
    # 查询在 as_of_date 之前创建，且当时未被取代的 chunk
    filters = {
        "project_id": project_id,
        "created_at_lte": as_of_date,
    }
    
    candidates = vector_search(query=query, filter=filters, top_k=100)
    
    # 过滤掉在 as_of_date 之前已被取代的版本
    valid_chunks = []
    for chunk in candidates:
        # 检查这个 artifact 在 as_of_date 时是否有更新的版本
        newer_exists = check_newer_version_exists(
            artifact_id=chunk.artifact_id,
            version=chunk.doc_version,
            as_of_date=as_of_date
        )
        if not newer_exists:
            valid_chunks.append(chunk)
    
    return valid_chunks
```

## 返回给用户的元数据结构

```python
{
    "query": "客户主数据标准",
    "results": [
        {
            "artifact": {
                "logical_id": "customer-master-data-standard",
                "name": "客户主数据标准",
                "type": "data_standard"
            },
            "version_info": {
                "version": "2.0",
                "phase": "蓝图设计",
                "status": "active",
                "supersedes": "1.0"
            },
            "content": {
                "text": "客户主数据包括客户编码、客户名称、客户分类等字段...",
                "section": "数据项定义",
                "section_path": "3.数据标准>3.1客户主数据",
                "role": "definition"
            },
            "source": {
                "file": "客户主数据标准_v2.0.docx",
                "page": 5,
                "chunk_index": 12
            },
            "score": 0.89,
            "other_versions": [  # 如果有其他版本
                {
                    "version": "1.0",
                    "phase": "现状调研",
                    "status": "superseded",
                    "difference_summary": "v2.0新增客户分级字段，调整编码规则"
                }
            ]
        }
    ]
}
```

## 数据库索引设计

```sql
-- 支持常用查询的索引
CREATE INDEX idx_chunks_artifact_logical_id ON document_chunks(artifact_logical_id);
CREATE INDEX idx_chunks_doc_version ON document_chunks(doc_version);
CREATE INDEX idx_chunks_status ON document_chunks(doc_status);
CREATE INDEX idx_chunks_dim_phase ON document_chunks(dim_phase);
CREATE INDEX idx_chunks_dim_domain ON document_chunks(dim_domain);
CREATE INDEX idx_chunks_created ON document_chunks(created_at);

-- 复合索引：按资料查最新版本
CREATE INDEX idx_chunks_artifact_version 
    ON document_chunks(artifact_logical_id, doc_version DESC);

-- 全文索引（如果需要）
CREATE INDEX idx_chunks_content_gin ON document_chunks USING gin(to_tsvector('chinese', content));
```

## 实施步骤

### 阶段1：数据模型扩展（1天）

1. 创建 `Artifact` 表
2. 扩展 `Document` 表（添加 artifact_id, version 等）
3. 扩展 `DocumentChunk` 表（添加 artifact_*, doc_*, dim_*, section_* 字段）

### 阶段2：文档处理流程改造（2天）

1. 在 `DocumentProcessor` 中集成元数据提取
2. 实现 `SmartChunker` 添加章节和内容角色信息
3. 保存时同时创建/更新 Artifact 和 Document

### 阶段3：检索接口增强（1天）

1. 修改 `search` 接口支持版本去重
2. 添加 `search_with_versions`, `search_as_of` 接口
3. 返回结果包含完整的元数据信息

### 阶段4：存量数据迁移（1天）

1. 脚本为存量文档提取元数据
2. 创建 Artifact 记录
3. 更新 Chunk 的元数据字段
