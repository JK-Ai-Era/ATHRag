# 元数据提取策略设计

## 核心原则

**渐进式提取**：先尝试自动化，不行再降级，最后兜底手动标注

```
文档输入
    │
    ▼
┌─────────────────┐
│ 第1层：文件名/路径解析 │ ← 零成本，覆盖80%场景
│ (FilenameParser) │
└─────────────────┘
    │ 未识别字段
    ▼
┌─────────────────┐
│ 第2层：文档内置元数据  │ ← Office/PDF属性、Markdown Frontmatter
│ (DocumentMetaExtractor) │
└─────────────────┘
    │ 未识别字段
    ▼
┌─────────────────┐
│ 第3层：LLM智能提取    │ ← 读内容识别资料类型、版本、关系
│ (LLMMetadataExtractor) │
└─────────────────┘
    │ 仍未识别
    ▼
┌─────────────────┐
│ 第4层：默认值/手动补充 │ ← 系统默认值或用户后续标注
│ (Default/Manual) │
└─────────────────┘
```

## 第1层：文件名/路径解析（最高优先级）

### 目录结构约定

```
云锡项目/
├── @phase=现状调研/                    # 目录级维度标注
│   ├── @type=数据标准/
│   │   └── 客户主数据标准_v1.0.md
│   └── @type=指标体系/
│       └── 财务指标清单_v1.0_20260115.xlsx
├── @phase=蓝图设计/
│   ├── @type=数据标准/
│   │   └── 客户主数据标准_v2.0_[supersedes:v1.0].md
│   └── @type=业务架构/
│       └── 销售域业务流程_v1.0.pdf
└── @phase=详细设计/
    └── @type=接口规范/
        └── 客户主数据接口_v1.0_[refines:客户主数据标准_v2.0].md
```

### 文件名解析规则

```python
class FilenameParser:
    """从文件名提取元数据"""
    
    PATTERNS = {
        # 版本号：_v1.0 _v2.1.3 _version_3
        'version': r'[_\-]v(ersion)?(?P<version>\d+\.\d+(?:\.\d+)?)',
        
        # 日期：_20260115 _2026-01-15 _Jan15_2026
        'date': r'[_\-]?(?P<date>\d{4}[-.]?\d{2}[-.]?\d{2})',
        
        # 取代关系：[supersedes:xxx] [replaces:xxx]
        'supersedes': r'\[supersedes[:=](?P<ref>[^\]]+)\]',
        'refines': r'\[refines[:=](?P<ref>[^\]]+)\]',
        'depends_on': r'\[depends[:=](?P<ref>[^\]]+)\]',
        
        # 状态标记：_FINAL _DRAFT _APPROVED
        'status': r'[_\-](?P<status>FINAL|DRAFT|APPROVED|BASELINE|ARCHIVED)',
        
        # 逻辑ID：@customer-data-standard
        'logical_id': r'@(?P<logical_id>[a-zA-Z0-9_-]+)',
    }
    
    @classmethod
    def parse(cls, filepath: str) -> Metadata:
        """
        解析文件路径和名称
        """
        path = Path(filepath)
        metadata = {}
        
        # 1. 从目录名提取维度
        for parent in path.parents:
            parent_name = parent.name
            # 匹配 @key=value 格式
            if match := re.match(r'@(?P<key>\w+)=(?P<value>.+)', parent_name):
                metadata[f"dim_{match['key']}"] = match['value']
        
        # 2. 从文件名提取
        filename = path.stem  # 不含扩展名
        
        for field, pattern in cls.PATTERNS.items():
            if match := re.search(pattern, filename, re.IGNORECASE):
                metadata[field] = match.group(field)
        
        # 3. 生成logical_id（如果没有指定）
        if 'logical_id' not in metadata:
            # 清理版本号、日期等，保留核心名称
            clean_name = cls._clean_filename(filename)
            metadata['logical_id'] = slugify(clean_name)
        
        return Metadata(**metadata)
    
    @staticmethod
    def _clean_filename(filename: str) -> str:
        """清理文件名，保留核心标识"""
        # 移除版本、日期、状态标记
        clean = re.sub(r'[_\-]v\d+(\.\d+)*', '', filename)
        clean = re.sub(r'[_\-]?\d{4}[-.]?\d{2}[-.]?\d{2}', '', clean)
        clean = re.sub(r'\[.*?\]', '', clean)
        return clean.strip('_-')
```

### 提取示例

| 文件路径 | 提取的元数据 |
|---------|-------------|
| `@phase=蓝图设计/客户主数据标准_v2.0_[supersedes:v1.0].md` | `dim_phase=蓝图设计`, `version=2.0`, `supersedes=v1.0`, `logical_id=客户主数据标准` |
| `@phase=详细设计/@type=接口规范/客户同步接口_v1.0_[depends:客户主数据标准].yaml` | `dim_phase=详细设计`, `dim_type=接口规范`, `version=1.0`, `depends_on=客户主数据标准` |
| `财务指标清单_20260215_FINAL.xlsx` | `date=20260215`, `status=FINAL`, `logical_id=财务指标清单` |

## 第2层：文档内置元数据

### Markdown Frontmatter

```markdown
---
logical_id: customer-master-standard
name: 客户主数据标准
version: 2.0.0
dimensions:
  phase: 蓝图设计
  domain: 销售
  maturity: approved
effective_date: 2026-02-15
supersedes: 
  - customer-master-standard@v1.0
relations:
  - type: refines
    target: sales-domain-blueprint
    description: 细化销售域蓝图中的客户数据要求
status: active
---

# 客户主数据标准

## 1. 范围
...
```

### Office文档属性

```python
class OfficeMetadataExtractor:
    """提取Word/Excel/PPT内置属性"""
    
    @staticmethod
    def extract(doc_path: str) -> Metadata:
        doc = Document(doc_path)
        props = doc.core_properties
        
        metadata = {
            'title': props.title,
            'author': props.author,
            'created': props.created,
            'modified': props.modified,
            'version': props.version,
        }
        
        # 自定义属性（高级用户可用）
        try:
            custom_props = doc.custom_doc_props
            for prop in custom_props:
                if prop.name.startswith('rag.'):
                    key = prop.name[4:]  # 去掉 rag. 前缀
                    metadata[key] = prop.value
        except:
            pass
        
        return metadata
```

**Word中设置自定义属性**：
- 文件 → 信息 → 属性 → 高级属性 → 自定义
- 添加属性如：`rag.logical_id`, `rag.phase`, `rag.version`

### PDF文档属性

```python
class PDFMetadataExtractor:
    """提取PDF元数据"""
    
    @staticmethod
    def extract(pdf_path: str) -> Metadata:
        reader = PdfReader(pdf_path)
        info = reader.metadata
        
        return Metadata(
            title=info.title,
            author=info.author,
            creator=info.creator,
            subject=info.subject,
            # PDF常把版本放在 subject 或自定义字段
            version=info.subject if 'v' in str(info.subject) else None,
        )
```

## 第3层：LLM智能提取

当前两层未能提取关键字段（如 `logical_id`, `supersedes`, `dimensions`）时，使用LLM读取文档内容推断。

```python
class LLMMetadataExtractor:
    """使用LLM从文档内容提取元数据"""
    
    PROMPT = """分析以下文档内容，提取项目资料管理所需的元数据。

文档内容：
{content}

请提取以下信息（JSON格式，无法确定则留空）：
{{
    "logical_id": "资料的逻辑标识符（如 customer-data-standard）",
    "name": "资料的显示名称",
    "version": "版本号（如 2.0）",
    "dimensions": {{
        "phase": "项目阶段（如：现状调研、蓝图设计、详细设计）",
        "type": "资料类型（如：数据标准、业务流程、接口规范）",
        "domain": "业务域（如：销售、财务、生产）"
    }},
    "relations": [
        {{
            "type": "supersedes|refines|depends_on|contradicts",
            "target": "目标资料名称或ID",
            "confidence": 0.9
        }}
    ],
    "status": "draft|active|deprecated",
    "confidence": 0.85
}}

注意：
1. 如果文档提到"取代"、"替代"、"v2替代v1"等，提取为 supersedes 关系
2. 如果文档提到"基于...设计"、"细化..."，提取为 refines 关系
3. 只返回JSON，不要其他解释"""
    
    @classmethod
    def extract(cls, content: str, existing_metadata: Metadata) -> Metadata:
        """
        仅提取未识别的字段
        """
        # 如果关键字段都已识别，跳过LLM
        if all(existing_metadata.get(k) for k in ['logical_id', 'version']):
            return existing_metadata
        
        # 截取文档前3000字符（节省token）
        sample = content[:3000]
        
        prompt = cls.PROMPT.format(content=sample)
        response = llm.generate(prompt)
        
        try:
            extracted = json.loads(response)
            
            # 只补充缺失字段，不覆盖已识别的
            for key, value in extracted.items():
                if not existing_metadata.get(key) and value:
                    existing_metadata[key] = value
                    existing_metadata['_extracted_by'] = 'llm'
                    
        except json.JSONDecodeError:
            logger.warning("LLM metadata extraction failed to parse JSON")
        
        return existing_metadata
```

### LLM提取示例

**输入文档片段**：
```
客户主数据标准（第二版）

本文档取代《客户主数据标准v1.0》（2026年1月发布），
基于蓝图设计阶段的要求进行细化。

主要变更：
- 新增客户分级字段
- 调整客户编码规则
...
```

**LLM提取结果**：
```json
{
    "logical_id": "customer-master-standard",
    "name": "客户主数据标准",
    "version": "2.0",
    "dimensions": {
        "phase": "蓝图设计",
        "type": "数据标准"
    },
    "relations": [
        {
            "type": "supersedes",
            "target": "customer-master-standard@v1.0",
            "confidence": 0.95
        }
    ],
    "status": "active",
    "confidence": 0.88
}
```

## 第4层：默认值与手动标注

### 系统默认值

```python
DEFAULTS = {
    'version': '1.0',
    'status': 'active',
    'effective_date': lambda: datetime.now(),
    'dimensions.phase': '未分类',
    'dimensions.type': '未分类',
}
```

### 手动标注接口

```python
# API：后续手动补充元数据
POST /api/documents/{doc_id}/metadata
{
    "logical_id": "customer-master-standard",
    "version": "2.0",
    "dimensions": {
        "phase": "蓝图设计",
        "domain": "销售"
    },
    "supersedes": ["customer-master-standard@v1.0"]
}

# 触发重新索引
POST /api/documents/{doc_id}/reindex
```

## 完整提取流程整合

```python
class MetadataExtractor:
    """元数据提取 orchestrator"""
    
    EXTRACTORS = [
        FilenameParser,           # 第1层
        DocumentMetaExtractor,    # 第2层  
        LLMMetadataExtractor,     # 第3层
    ]
    
    @classmethod
    def extract(cls, file_path: str, content: str = None) -> Metadata:
        metadata = {}
        
        # 逐层提取，后层补充前层未识别的字段
        for extractor in cls.EXTRACTORS:
            try:
                new_data = extractor.extract(file_path, content, metadata)
                for key, value in new_data.items():
                    if not metadata.get(key) and value:
                        metadata[key] = value
                        metadata[f'_source_{key}'] = extractor.__name__
            except Exception as e:
                logger.warning(f"Extractor {extractor.__name__} failed: {e}")
                continue
        
        # 应用默认值
        for key, default in DEFAULTS.items():
            if not metadata.get(key):
                metadata[key] = default() if callable(default) else default
                metadata[f'_source_{key}'] = 'default'
        
        return Metadata(**metadata)
```

## 元数据存储

```python
# 在DocumentChunk中存储
class DocumentChunk(Base):
    # 原有字段
    id = Column(String, primary_key=True)
    content = Column(Text)
    embedding = Column(Vector(1024))
    
    # 新增：元数据（JSONB存储）
    metadata = Column(JSONB, default={})
    
    # 常用字段也单独建列（便于过滤）
    logical_id = Column(String, index=True)
    version = Column(String)
    status = Column(String, index=True)
    effective_date = Column(DateTime)
    
    # 维度（动态，如 dim_phase, dim_type）
    dim_phase = Column(String, index=True)
    dim_type = Column(String, index=True)
    
    # 来源追踪
    _meta_sources = Column(JSONB)  # 记录每个字段的提取来源
```

## 实施建议

### 阶段1：文件名/路径（立即开始）
- 约定目录命名格式 `@key=value`
- 约定文件名标记版本和关系
- 实现 `FilenameParser`

### 阶段2：Frontmatter支持（1天）
- 支持Markdown文档头部YAML
- 零成本，用户可选使用

### 阶段3：LLM提取（2-3天）
- 针对未识别关键字段的文档
- 可配置开启/关闭（节省成本）

### 阶段4：可视化标注（长期）
- Web界面手动修正元数据
- 批量标注工具
