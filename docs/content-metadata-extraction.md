# 基于文档内容的元数据提取方案

## 核心思路

不依赖文件名，而是在文档解析后，利用解析出的**结构化信息**提取元数据：

```
文档文件
    │
    ▼
┌─────────────────┐
│  Unstructured   │  ← 解析出标题、页眉、表格、章节结构
│    / MinerU     │
└─────────────────┘
    │
    ▼ ParsedDocument (text, sections, tables, headers/footers)
┌─────────────────┐
│ ContentMetadata │  ← 从解析结果提取元数据
│   Extractor     │
└─────────────────┘
    │
    ▼ DocumentChunk (带元数据)
```

## 提取来源

### 1. 封面/首页信息（最可靠）

```python
class CoverPageExtractor:
    """从文档首页提取元数据"""
    
    def extract(self, parsed_doc: ParsedDocument) -> Metadata:
        """
        首页通常包含：
        - 文档标题（大字居中）
        - 版本号（V1.0、第二版、修订记录）
        - 日期（2026年2月）
        - 部门/作者
        - 阶段标识（蓝图设计、详细设计）
        """
        first_page = self._get_first_page_text(parsed_doc)
        
        metadata = {}
        
        # 模式匹配（从首页文本）
        patterns = {
            'version': [
                r'版本[：:]?\s*(V?\d+\.\d+)',
                r'(第[一二三四五12345]+版)',
                r'V(\d+\.\d+(?:\.\d+)?)',
                r'(\d+\.\d+)\s*版',
            ],
            'date': [
                r'(20\d{2})\s*年\s*(\d{1,2})\s*月',
                r'(20\d{2})[-./](\d{1,2})[-./](\d{1,2})',
                r'(\d{4})年(?:\d{1,2}月)?',
            ],
            'phase': [
                r'(现状调研|需求调研|业务调研)',
                r'(蓝图设计|概要设计|总体设计)',
                r'(详细设计|深化设计)',
                r'(实施|上线|交付)',
                r'(运维|运营)',
            ],
            'doc_type': [
                r'(数据标准|指标体系|指标清单)',
                r'(业务流程|业务架构)',
                r'(接口规范|API设计)',
                r'(架构设计|技术方案)',
                r'(需求文档|需求规格)',
            ],
            'supersedes': [
                r'(?:取代|替代|更新|升级|替代).{0,10}([Vv]?(?:ersion)?\s*\d+\.\d+)',
                r'(?:原|旧).{0,5}版本[：:]?\s*([Vv]?\d+\.\d+)',
            ]
        }
        
        for field, regex_list in patterns.items():
            for pattern in regex_list:
                if match := re.search(pattern, first_page):
                    metadata[field] = match.group(1)
                    break
        
        return metadata
```

### 2. 文档属性（Word/PDF内置）

```python
class DocumentPropertiesExtractor:
    """提取文档内置属性"""
    
    def extract_from_docx(self, file_path: Path) -> Metadata:
        from docx import Document
        
        doc = Document(file_path)
        props = doc.core_properties
        
        return {
            'title': props.title,
            'author': props.author,
            'subject': props.subject,  # 常用于存储版本/阶段信息
            'comments': props.comments,
            'created': props.created,
            'modified': props.modified,
            'version': props.version,
        }
```

### 3. 标题层级分析

```python
class HeadingStructureExtractor:
    """分析标题结构提取信息"""
    
    def extract(self, parsed_doc: ParsedDocument) -> Metadata:
        """
        从标题结构推断：
        - 文档主标题（第一个 Title 或 level-1 Heading）
        - 是否包含"修订记录"、"变更历史"等章节
        - 文档类型（从标题关键词）
        """
        sections = parsed_doc.sections
        
        metadata = {}
        
        # 主标题
        if sections:
            metadata['title'] = sections[0].title
            
            # 从主标题提取逻辑ID
            metadata['logical_id'] = self._slugify(sections[0].title)
        
        # 检查是否有修订历史章节
        for section in sections:
            title_lower = section.title.lower()
            if any(kw in title_lower for kw in ['修订', '变更', '历史', '版本记录', '更新记录']):
                metadata['has_revision_history'] = True
                # 从修订记录提取版本信息
                metadata.update(self._extract_from_revision_section(section))
                break
        
        return metadata
    
    def _extract_from_revision_section(self, section: ParsedSection) -> Dict:
        """从"修订记录"章节提取版本信息"""
        content = '\n'.join(section.content)
        
        # 找最新版本（通常是表格第一行或最上面的记录）
        # 匹配模式：版本 | 日期 | 修订内容 | 作者
        versions = re.findall(
            r'(V?\d+\.\d+).{0,30}?(20\d{2}[-/年]\d{1,2})',
            content
        )
        
        if versions:
            return {
                'version': versions[0][0],
                'last_modified': versions[0][1]
            }
        return {}
```

### 4. 页眉页脚分析

```python
class HeaderFooterExtractor:
    """从页眉页脚提取信息"""
    
    def extract(self, parsed_doc: ParsedDocument) -> Metadata:
        """
        页眉页脚常包含：
        - 文档名称
        - 版本号
        - 阶段/保密级别
        - 日期
        """
        metadata = {}
        
        # Unstructured 可以提取 Header/Footer 元素
        for element in parsed_doc.elements:
            if element.category in ['Header', 'Footer']:
                text = element.text
                
                # 匹配版本号
                if match := re.search(r'V(\d+\.\d+)', text):
                    metadata['version'] = match.group(1)
                
                # 匹配阶段标识
                if match := re.search(r'(蓝图|详细|实施|运维)', text):
                    metadata['phase'] = match.group(1)
        
        return metadata
```

### 5. 表格内容分析（重要！）

项目文档常在开头有**文档信息表**：

```python
class DocumentInfoTableExtractor:
    """提取文档开头的信息表格"""
    
    KEYWORDS = {
        'version': ['版本', '版本号', 'Version'],
        'author': ['编制', '作者', 'Author', '编制人'],
        'reviewer': ['审核', 'Reviewer', '审核人'],
        'approver': ['批准', 'Approver', '批准人'],
        'date': ['日期', '编制日期', 'Date'],
        'phase': ['阶段', '项目阶段', 'Phase'],
        'doc_type': ['文档类型', '类别', 'Type'],
        'project': ['项目名称', '项目', 'Project'],
    }
    
    def extract(self, parsed_doc: ParsedDocument) -> Metadata:
        """
        查找文档开头的信息表（通常是前3个表格）
        """
        metadata = {}
        
        for table in parsed_doc.tables[:3]:  # 只看前3个表格
            # 检查是否是文档信息表
            if self._is_document_info_table(table):
                metadata.update(self._parse_info_table(table))
                break
        
        return metadata
    
    def _is_document_info_table(self, table: ParsedTable) -> bool:
        """判断是否为文档信息表"""
        # 信息表特征：包含"版本"、"编制"等关键词
        table_text = str(table.headers) + str(table.rows)
        keywords = ['版本', '编制', '审核', '日期', '文档名称']
        return any(kw in table_text for kw in keywords)
    
    def _parse_info_table(self, table: ParsedTable) -> Dict:
        """解析信息表格"""
        metadata = {}
        
        for row in table.rows:
            if len(row) >= 2:
                key_cell = row[0]
                value_cell = row[1]
                
                # 匹配关键词
                for field, keywords in self.KEYWORDS.items():
                    if any(kw in key_cell for kw in keywords):
                        metadata[field] = value_cell.strip()
                        break
        
        return metadata
```

### 6. LLM 智能提取（兜底+增强）

```python
class LLMContentExtractor:
    """使用LLM从解析后的结构化内容提取元数据"""
    
    PROMPT_TEMPLATE = """分析以下文档的结构化内容，提取项目资料管理元数据。

文档标题：{title}
前3个章节标题：{headings}
文档开头内容：
{content_sample}

请提取（JSON格式）：
{{
    "logical_id": "资料逻辑标识（如 customer-master-data-standard）",
    "name": "资料显示名称",
    "version": "版本号",
    "phase": "项目阶段（现状调研/蓝图设计/详细设计/实施交付/运维）",
    "doc_type": "文档类型（数据标准/业务流程/接口规范/架构设计/需求文档）",
    "relations": [
        {{
            "type": "supersedes",
            "target": "被取代的资料名称或版本",
            "evidence": "证据文本片段"
        }}
    ],
    "confidence": 0.85
}}

注意：
1. 从"修订记录"、"版本历史"章节提取版本信息
2. 从"本文档取代XXX"、"基于XXX细化"等表述提取关系
3. 从章节结构推断文档类型（如包含"数据项定义"可能是数据标准）
4. 如果无法确定，字段留空"""
    
    def extract(self, parsed_doc: ParsedDocument) -> Metadata:
        # 准备输入
        headings = [s.title for s in parsed_doc.sections[:5]]
        content_sample = parsed_doc.text[:2000]  # 前2000字符
        
        prompt = self.PROMPT_TEMPLATE.format(
            title=headings[0] if headings else "",
            headings=headings[1:4],
            content_sample=content_sample
        )
        
        response = llm.generate(prompt, temperature=0.1)
        
        try:
            return json.loads(response)
        except:
            return {}
```

## 整合提取器

```python
class ContentMetadataExtractor:
    """基于文档内容的元数据提取 orchestrator"""
    
    EXTRACTORS = [
        CoverPageExtractor,           # 首页模式匹配
        DocumentPropertiesExtractor,  # 文档内置属性
        HeadingStructureExtractor,    # 标题结构分析
        HeaderFooterExtractor,        # 页眉页脚
        DocumentInfoTableExtractor,   # 信息表格
        LLMContentExtractor,          # LLM智能提取（兜底）
    ]
    
    def extract(self, file_path: Path, parsed_doc: ParsedDocument) -> Metadata:
        """执行完整的元数据提取"""
        metadata = {}
        sources = {}
        
        for extractor_class in self.EXTRACTORS:
            try:
                extractor = extractor_class()
                
                if isinstance(extractor, DocumentPropertiesExtractor):
                    new_data = extractor.extract_from_docx(file_path)
                else:
                    new_data = extractor.extract(parsed_doc)
                
                # 只补充缺失字段，记录来源
                for key, value in new_data.items():
                    if value and not metadata.get(key):
                        metadata[key] = value
                        sources[key] = extractor_class.__name__
                        
            except Exception as e:
                logger.warning(f"Extractor {extractor_class.__name__} failed: {e}")
                continue
        
        metadata['_extraction_sources'] = sources
        return Metadata(**metadata)
```

## 在文档处理流程中集成

```python
# src/core/document_processor.py

class DocumentProcessor:
    def process(self, file_path: Union[str, Path]) -> ProcessedDocument:
        """完整处理文档：解析 → 提取元数据 → 分块"""
        file_path = Path(file_path)
        doc_type = self._detect_type(file_path)
        
        # 1. 解析文档（Unstructured/MinerU）
        parsed = self.parse(file_path, doc_type)
        
        # 2. 提取元数据（新增！）
        from src.core.metadata_extractor import ContentMetadataExtractor
        metadata_extractor = ContentMetadataExtractor()
        doc_metadata = metadata_extractor.extract(file_path, parsed)
        
        # 3. 分块（传入元数据）
        chunks = self.chunk(parsed, doc_metadata)
        
        return ProcessedDocument(
            chunks=chunks,
            metadata=doc_metadata,
            parsed_structure=parsed
        )
```

## 实际提取示例

### 示例1：有规范封面的文档

**文档首页**：
```
                        云锡集团
                  客户主数据标准规范
                          
                      版本：V2.0
                   编制日期：2026年2月
                   
                    蓝图设计阶段
```

**提取结果**：
```json
{
    "title": "客户主数据标准规范",
    "logical_id": "customer-master-data-standard",
    "version": "2.0",
    "phase": "蓝图设计",
    "date": "2026年2月",
    "_extraction_sources": {
        "title": "HeadingStructureExtractor",
        "version": "CoverPageExtractor",
        "phase": "CoverPageExtractor"
    }
}
```

### 示例2：有修订记录表的文档

**文档结构**：
```
1. 修订记录

| 版本 | 修订日期 | 修订内容 | 作者 |
|------|----------|----------|------|
| V2.0 | 2026-02 | 新增客户分级 | 张三 |
| V1.0 | 2026-01 | 初始版本 | 李四 |

2. 引言
本文档取代《客户主数据标准V1.0》... 
```

**提取结果**：
```json
{
    "title": "客户主数据标准",
    "version": "2.0",
    "last_modified": "2026-02",
    "relations": [
        {
            "type": "supersedes",
            "target": "客户主数据标准V1.0",
            "evidence": "本文档取代《客户主数据标准V1.0》"
        }
    ],
    "_extraction_sources": {
        "version": "DocumentInfoTableExtractor",
        "relations": "LLMContentExtractor"
    }
}
```

### 示例3：无规范格式的文档

**文件名**：`指标清单(1).pdf`（无法提取任何信息）

**文档内容**：
```
一、财务指标体系

1.1 应收账款周转率
定义：营业收入/平均应收账款
...

本文档基于蓝图设计阶段的业务调研结果编制
```

**提取结果**（LLM兜底）：
```json
{
    "title": "财务指标体系",
    "logical_id": "financial-indicator-system",
    "phase": "蓝图设计",
    "doc_type": "指标体系",
    "confidence": 0.75,
    "_extraction_sources": {
        "title": "HeadingStructureExtractor",
        "phase": "LLMContentExtractor",
        "doc_type": "LLMContentExtractor"
    }
}
```

## 实施优先级

### 阶段1：文档内置属性 + 封面模式（2天）
- Word/PDF 属性提取
- 首页正则模式匹配版本、日期、阶段
- 覆盖 60% 有规范格式的文档

### 阶段2：信息表格提取（2天）
- 识别文档开头的"修订记录"、"文档信息"表格
- 从表格提取结构化元数据
- 覆盖到 80%

### 阶段3：LLM兜底（1天）
- 上述方法未提取到关键字段时，调用LLM
- 可配置开启/关闭
- 覆盖到 95%

### 阶段4：反馈闭环（长期）
- 用户手动修正的元数据回传
- 用于改进提取模式
