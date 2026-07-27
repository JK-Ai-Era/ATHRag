# 项目资料版本管理方案（通用框架）

## 核心概念抽象

### 1. 资料（Artifact）
泛指项目中产生的任何可检索内容：
- 业务流程、数据标准、接口规范、架构设计
- 需求文档、会议纪要、决策记录
- 任何需要被引用、可能随时间变化的实体

### 2. 版本维度（Dimensions）
不硬编码阶段名称，使用灵活的维度体系：

```yaml
# 维度定义（项目级别配置）
dimensions:
  - name: phase
    display: 项目阶段
    values:                    # 每个项目自定义
      - research
      - blueprint  
      - detailed
      - implementation
      - maintenance           # 运维阶段也能加
    
  - name: maturity
    display: 成熟度
    values:
      - draft                 # 草稿
      - review                # 评审中
      - approved              # 已批准
      - archived              # 已归档
      
  - name: source_type
    display: 资料来源
    values:
      - meeting_notes         # 会议纪要
      - design_doc            # 设计文档
      - requirement           # 需求文档
      - decision_record       # 决策记录
```

### 3. 关系（Relationship）
资料之间的逻辑关系：

```yaml
relationships:
  - type: supersedes         # 取代/替代
    direction: forward       # A supersedes B
    
  - type: refines            # 细化/展开
    direction: forward       # A 是 B 的详细设计
    
  - type: contradicts        # 矛盾/冲突
    direction: bidirectional
    
  - type: depends_on         # 依赖
    direction: forward
```

## 数据模型

### 资料实体（Artifact）

```python
class Artifact:
    # 唯一标识
    artifact_id: str           # 全局唯一，如 "ART-2026-001"
    
    # 内容标识（多文档可指向同一资料）
    logical_id: str            # 逻辑ID，如 "customer-data-standard"
    
    # 维度值（灵活，不限定具体维度）
    dimensions: Dict[str, str]  # { "phase": "blueprint", "maturity": "approved" }
    
    # 版本信息
    version: str               # 语义化版本 "2.1.0"
    effective_date: datetime   # 生效时间
    expiration_date: datetime  # 失效时间（可选）
    
    # 关系
    relations: List[Relation]  # 与其他资料的关系
    
    # 状态
    status: str                # active | deprecated | superseded | draft
    
    # 来源文档（1:N，一个资料可由多个文档片段组成）
    sources: List[SourceRef]
```

### 文档片段（Chunk）增强

```python
class DocumentChunk:
    # 原有字段
    id: str
    content: str
    embedding: Vector
    
    # 新增：关联到资料实体
    artifact_id: str           # 属于哪个资料
    artifact_version: str      # 资料版本
    
    # 新增：片段级别元数据
    chunk_role: str            # definition | example | background | rationale
    confidence: float          # LLM提取的置信度
```

## 检索策略（通用）

### 1. 默认策略：最新有效

```python
def search_default(query: str, context: SearchContext):
    """
    默认只返回当前有效的资料版本
    """
    filters = {
        "status": "active",
        "effective_date": {"lte": context.as_of or now()},
        "expiration_date": {"gt": context.as_of or now(), "or_null": True}
    }
    
    # 按逻辑ID分组，每个逻辑ID只取最高版本
    results = search_and_deduplicate_by_logical_id(
        query=query,
        filters=filters,
        sort_by=["version_desc", "effective_date_desc"]
    )
    
    return results
```

### 2. 历史追溯：指定时间点

```python
def search_historical(query: str, as_of: datetime):
    """
    时间机器：查看某时间点的有效资料
    """
    filters = {
        "effective_date": {"lte": as_of},
        "OR": [
            {"expiration_date": {"gt": as_of}},
            {"expiration_date": None}
        ]
    }
    return search(query, filters=filters)
```

### 3. 冲突发现：显示所有版本

```python
def search_with_conflicts(query: str):
    """
    返回同一逻辑ID的所有活跃版本，标记冲突
    """
    results = search(query)
    
    # 按 logical_id 分组
    groups = group_by_logical_id(results)
    
    for logical_id, versions in groups.items():
        if len(versions) > 1:
            # 检查是否有取代关系
            if not has_supersede_chain(versions):
                mark_conflict(logical_id, versions)
    
    return groups
```

### 4. 维度过滤

```python
def search_by_dimensions(query: str, dimensions: Dict[str, Union[str, List[str]]]):
    """
    灵活维度过滤
    """
    filters = {}
    for dim, value in dimensions.items():
        if isinstance(value, list):
            filters[f"dimensions.{dim}"] = {"in": value}
        else:
            filters[f"dimensions.{dim}"] = value
    
    return search(query, filters=filters)

# 使用示例
search_by_dimensions(
    "数据标准",
    dimensions={
        "phase": ["blueprint", "detailed"],      # 蓝图或详细设计阶段
        "maturity": "approved",                   # 已批准的
        "source_type": "design_doc"               # 设计文档
    }
)
```

## 项目配置（灵活定义）

每个项目可以定义自己的维度和工作流：

```yaml
# projects/yunxi/config.yaml
project:
  name: 云锡数据治理项目
  
  dimensions:
    phase:
      values:
        - current_state          # 现状调研
        - target_design          # 目标设计  
        - implementation         # 实施交付
        - operation              # 运维优化
      default: current_state
      
    approval_status:
      values:
        - draft
        - stakeholder_review
        - steering_committee_approved
        - baselined
      
    domain:                     # 业务域
      values:
        - finance
        - production
        - sales
        - supply_chain
        - master_data

  # 自动规则
  rules:
    - when:
        artifact_type: "data_standard"
        phase: "target_design"
      then:
        supersedes: "phase:current_state AND artifact_type:data_standard"
        
    - when:
        approval_status: "baselined"
      then:
        lock_editing: true
        notification: "stakeholders"
```

## 使用场景示例

### 场景1：查找当前有效的数据标准

```python
results = rag.search("客户主数据标准")
# 自动返回最新 approved + active 的版本
# 如果调研版和蓝图版都有，返回蓝图版（假设已取代调研版）
```

### 场景2：查看某个决策的演变

```python
results = rag.search(
    "财务指标口径",
    show_evolution=True           # 显示完整演变链
)
# 返回：
# - v1.0 (调研) 定义为 X
# - v2.0 (蓝图) 修改为 Y，取代 v1.0
# - v2.1 (详细设计) 细化为 Z，基于 v2.0
```

### 场景3：跨项目复用

```python
# 另一个项目有自己的阶段定义
results = rag.search(
    "指标定义",
    project_id="other_project",
    dimensions={
        "phase": "conceptual_design",    # 完全不同的阶段名称
        "maturity": "validated"
    }
)
```

## 实现路线图

### 阶段1：元数据增强（核心）
1. 扩展 Chunk 表，增加 artifact 相关字段
2. 支持文档上传时指定维度值
3. 文件名/目录约定提取维度信息

### 阶段2：检索增强
1. 默认过滤 active 状态
2. 按 logical_id 去重，取最新版本
3. 显示版本来源和取代关系

### 阶段3：项目配置
1. 项目级维度配置
2. 可视化界面管理资料关系
3. 变更通知和审批流

### 阶段4：智能提取
1. LLM自动识别文档中的资料实体
2. 自动发现潜在的取代关系
3. 冲突检测和提醒

## 关键设计原则

1. **不预设具体值**：阶段、类型、状态都可在项目级别配置
2. **向后兼容**：没有维度信息的旧文档也能正常工作
3. **渐进增强**：可以从简单的文件名约定开始，逐步完善
4. **显式优于隐式**：取代关系需要显式声明，不自动推断
5. **检索透明**：用户知道看到的是哪个版本，为什么是这个版本
