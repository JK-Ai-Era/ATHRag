# RAG 实用升级方案（Agent 场景优化）

针对 Agent 使用场景的轻量级优化，不求全但求实用。

---

## 一、核心功能清单

| 功能 | 解决的问题 | 实现复杂度 | 工期 |
|------|-----------|-----------|------|
| **代码上下文增强** | 片段缺乏上下文 | 低 | 3天 |
| **文件重要性标记** | 检索结果噪音大 | 低 | 2天 |
| **Agent 查询分析** | 了解使用模式 | 低 | 2天 |
| **跨项目标签关联** | 发现共享代码/工具 | 中 | 4天 |
| **检索结果重排序** | 质量排序 | 低 | 2天 |

**总计：约2周**

---

## 二、功能详细设计

### 2.1 代码上下文增强

**目标**：让 Agent 看到的代码片段知道"谁调用了它"

#### 实现方式

```python
# src/core/code_analyzer.py

class CodeContextEnhancer:
    """为代码片段添加上下文"""
    
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.import_graph = {}  # 文件导入关系缓存
    
    def analyze_project(self) -> None:
        """分析整个项目，构建调用关系"""
        for py_file in self.project_path.rglob("*.py"):
            self._analyze_file(py_file)
    
    def _analyze_file(self, file_path: Path) -> None:
        """分析单个文件"""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            
            # 提取导入关系
            imports = self._extract_imports(content, file_path)
            self.import_graph[file_path] = imports
            
            # 提取函数/类定义及其被调用关系
            definitions = self._extract_definitions(content)
            
            return {
                'imports': imports,
                'definitions': definitions,
                'is_entry_point': self._is_entry_point(file_path, content)
            }
        except Exception:
            return None
    
    def _extract_imports(self, content: str, file_path: Path) -> List[str]:
        """提取文件导入的其他模块"""
        imports = []
        
        # Python import 模式
        patterns = [
            r'^from\s+([\w.]+)\s+import',
            r'^import\s+([\w.]+)',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                imports.append(match.group(1))
        
        return imports
    
    def _extract_definitions(self, content: str) -> Dict[str, Dict]:
        """提取函数和类定义"""
        definitions = {}
        
        # 类定义
        for match in re.finditer(r'^class\s+(\w+)', content, re.MULTILINE):
            name = match.group(1)
            line_no = content[:match.start()].count('\n') + 1
            definitions[name] = {
                'type': 'class',
                'line': line_no,
                'signatures': self._extract_class_methods(content, name)
            }
        
        # 函数定义
        for match in re.finditer(r'^(?:async\s+)?def\s+(\w+)\s*\(', content, re.MULTILINE):
            name = match.group(1)
            line_no = content[:match.start()].count('\n') + 1
            definitions[name] = {
                'type': 'function',
                'line': line_no
            }
        
        return definitions
    
    def _is_entry_point(self, file_path: Path, content: str) -> bool:
        """判断是否是入口文件"""
        # 常见入口文件特征
        entry_patterns = [
            r'if\s+__name__\s*==\s*["\']__main__["\']',
            r'@app\.(route|get|post)',
            r'uvicorn\.run|fastapi|flask\.Flask',
            r'cli\s*=\s*typer\.Typer',
        ]
        
        for pattern in entry_patterns:
            if re.search(pattern, content):
                return True
        
        # 文件名特征
        entry_names = ['main.py', 'app.py', 'server.py', 'cli.py', 'index.py']
        if file_path.name in entry_names:
            return True
        
        return False
    
    def get_context_for_chunk(self, chunk_text: str, file_path: Path) -> Dict:
        """为代码片段生成上下文"""
        context = {
            'file_imports': [],
            'callers': [],  # 谁调用了这个文件
            'callees': [],  # 这个文件调用了谁
            'entry_point': False,
            'related_files': []
        }
        
        file_analysis = self.import_graph.get(file_path)
        if file_analysis:
            context['file_imports'] = file_analysis['imports'][:10]  # 前10个
            context['entry_point'] = file_analysis['is_entry_point']
        
        # 找出谁导入了这个文件
        for other_file, imports in self.import_graph.items():
            if other_file != file_path:
                # 简化匹配：检查是否导入当前文件所在模块
                module_name = file_path.stem
                if any(module_name in imp for imp in imports):
                    context['callers'].append(str(other_file.relative_to(self.project_path)))
        
        context['callers'] = context['callers'][:5]  # 限制数量
        
        return context
```

#### 数据库存储

```sql
-- 新增：文件分析表
CREATE TABLE file_analysis (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    is_entry_point BOOLEAN DEFAULT FALSE,
    file_type TEXT,  -- 'entry', 'util', 'config', 'test'
    import_count INTEGER DEFAULT 0,
    imported_by_count INTEGER DEFAULT 0,
    function_count INTEGER DEFAULT 0,
    class_count INTEGER DEFAULT 0,
    top_imports JSON,  -- ["module1", "module2"]
    called_by JSON,    -- ["file1.py", "file2.py"]
    analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, file_path)
);

-- 新增：片段上下文表（可选，也可以动态生成）
CREATE TABLE chunk_context (
    chunk_id TEXT PRIMARY KEY,
    file_imports JSON,
    callers JSON,
    is_entry_point BOOLEAN,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
);
```

#### 集成到检索结果

```python
# src/services/search_service.py

async def search_with_context(self, project_id: str, query: str) -> SearchResult:
    """带上下文的搜索"""
    # 1. 原有语义检索
    base_results = await self._semantic_search(project_id, query)
    
    # 2. 为每个结果添加上下文
    enhancer = CodeContextEnhancer(self._get_project_path(project_id))
    
    for result in base_results:
        if result.doc_type == 'code':
            context = enhancer.get_context_for_chunk(
                result.content,
                Path(result.file_path)
            )
            result.context = context
            
            # 增强片段内容
            result.enhanced_content = self._format_with_context(
                result.content,
                context,
                result.file_path
            )
    
    return base_results

def _format_with_context(self, content: str, context: Dict, file_path: str) -> str:
    """格式化带上下文的代码片段"""
    sections = [f"【文件: {file_path}】"]
    
    if context.get('entry_point'):
        sections.append("【类型: 入口文件】")
    
    if context.get('callers'):
        sections.append(f"【被调用: {', '.join(context['callers'][:3])}】")
    
    if context.get('file_imports'):
        sections.append(f"【依赖: {', '.join(context['file_imports'][:5])}】")
    
    sections.append("---")
    sections.append(content)
    
    return "\n".join(sections)
```

---

### 2.2 文件重要性标记

**目标**：让 Agent 知道哪些文件是核心，哪些是工具

#### 自动分类规则

```python
# src/core/file_classifier.py

class FileClassifier:
    """自动分类文件重要性"""
    
    FILE_TYPE_RULES = {
        'entry': {
            'patterns': [
                r'main\.py$', r'app\.py$', r'server\.py$', r'cli\.py$',
                r'index\.(js|ts)$', r'index\.html$',
            ],
            'content_patterns': [
                r'if __name__ == ["\']__main__["\']',
                r'@app\.(route|get|post|put|delete)',
                r'uvicorn\.run',
                r'createApp\(',
            ]
        },
        'config': {
            'patterns': [
                r'config', r'settings', r'\.env', r'\.toml$', r'\.yaml$', r'\.json$',
                r'pyproject\.toml$', r'package\.json$', r'tsconfig\.json$',
            ],
            'content_patterns': []
        },
        'test': {
            'patterns': [
                r'test_', r'_test\.py$', r'\.test\.(js|ts)$', r'__tests__',
                r'spec\.(js|ts)$',
            ],
            'content_patterns': [
                r'def test_',
                r'import unittest',
                r'import pytest',
            ]
        },
        'util': {
            'patterns': [
                r'utils?', r'helpers?', r'common', r'shared', r'lib/',
            ],
            'content_patterns': []
        },
        'core': {
            'patterns': [],
            'content_patterns': [],
            'heuristic': 'high_imported_by'  # 被很多文件导入
        }
    }
    
    def classify(self, file_path: Path, content: str, 
                 analysis: Dict) -> str:
        """分类文件类型"""
        file_name = file_path.name.lower()
        
        # 按规则匹配
        for file_type, rules in self.FILE_TYPE_RULES.items():
            # 文件名匹配
            for pattern in rules.get('patterns', []):
                if re.search(pattern, file_name):
                    return file_type
            
            # 内容匹配
            for pattern in rules.get('content_patterns', []):
                if re.search(pattern, content):
                    return file_type
        
        # 启发式规则
        if analysis.get('imported_by_count', 0) > 5:
            return 'core'
        
        if analysis.get('import_count', 0) > 10:
            return 'orchestrator'  # 协调者
        
        return 'normal'
    
    def calculate_importance_score(self, analysis: Dict) -> float:
        """计算文件重要性分数 (0-1)"""
        score = 0.0
        
        # 被导入次数
        imported_by = analysis.get('imported_by_count', 0)
        score += min(imported_by / 10, 0.4)  # 最多贡献0.4
        
        # 是否为入口
        if analysis.get('is_entry_point'):
            score += 0.3
        
        # 定义的数量
        func_count = analysis.get('function_count', 0)
        class_count = analysis.get('class_count', 0)
        score += min((func_count + class_count * 2) / 20, 0.2)
        
        # 文件类型加成
        file_type = analysis.get('file_type', 'normal')
        type_bonus = {
            'entry': 0.1,
            'core': 0.08,
            'config': 0.05,
            'util': 0.02,
            'normal': 0
        }
        score += type_bonus.get(file_type, 0)
        
        return min(score, 1.0)
```

#### 检索时应用

```python
# 检索结果排序时考虑重要性
def rerank_by_importance(self, results: List[SearchResult]) -> List[SearchResult]:
    """根据文件重要性重排序"""
    
    # 获取文件重要性
    for result in results:
        analysis = self.db.query(FileAnalysis).filter(
            FileAnalysis.file_path == result.file_path
        ).first()
        
        if analysis:
            # 基础语义分 * 重要性加成
            importance_boost = 1 + analysis.importance_score * 0.3
            result.final_score = result.semantic_score * importance_boost
            result.file_type = analysis.file_type
        else:
            result.final_score = result.semantic_score
    
    # 按最终分数排序
    return sorted(results, key=lambda x: x.final_score, reverse=True)
```

---

### 2.3 Agent 使用分析

**目标**：了解 Agent 查什么，优化索引

#### 查询日志表

```sql
-- 新增：查询日志表
CREATE TABLE query_logs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    results_count INTEGER,
    clicked_results JSON,  -- 用户/Agent点击了哪些结果 ["chunk_id1", "chunk_id2"]
    response_time_ms INTEGER,
    source TEXT,  -- 'mcp', 'web', 'cli'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- 新增：热门查询统计（每日聚合）
CREATE TABLE query_stats (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    query_pattern TEXT,  -- 归一化后的查询模式
    query_count INTEGER DEFAULT 0,
    avg_results_count FLOAT,
    date DATE NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, query_pattern, date)
);
```

#### 分析服务

```python
# src/services/analytics_service.py

class QueryAnalytics:
    """查询分析服务"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def log_query(self, project_id: str, query_text: str,
                  results: List[SearchResult], source: str = 'mcp') -> None:
        """记录查询"""
        log = QueryLog(
            id=str(uuid4()),
            project_id=project_id,
            query_text=query_text,
            results_count=len(results),
            source=source,
            created_at=datetime.utcnow()
        )
        self.db.add(log)
        self.db.commit()
    
    def get_hot_queries(self, project_id: str, days: int = 7,
                       limit: int = 20) -> List[Dict]:
        """获取热门查询"""
        from_date = datetime.utcnow() - timedelta(days=days)
        
        results = self.db.query(
            QueryLog.query_text,
            func.count(QueryLog.id).label('count')
        ).filter(
            QueryLog.project_id == project_id,
            QueryLog.created_at >= from_date
        ).group_by(
            QueryLog.query_text
        ).order_by(
            desc('count')
        ).limit(limit).all()
        
        return [
            {'query': r.query_text, 'count': r.count}
            for r in results
        ]
    
    def get_unsatisfied_queries(self, project_id: str, 
                                 days: int = 7) -> List[Dict]:
        """识别可能未满足需求的查询（返回结果少或没有点击）"""
        from_date = datetime.utcnow() - timedelta(days=days)
        
        # 返回结果少或没有点击记录的查询
        results = self.db.query(QueryLog).filter(
            QueryLog.project_id == project_id,
            QueryLog.created_at >= from_date,
            (QueryLog.results_count < 3) | 
            (QueryLog.clicked_results == '[]') |
            (QueryLog.clicked_results.is_(None))
        ).all()
        
        return [
            {
                'query': r.query_text,
                'results_count': r.results_count,
                'date': r.created_at
            }
            for r in results
        ]
    
    def get_popular_entities(self, project_id: str,
                            days: int = 7) -> List[Dict]:
        """从查询中提取热门实体（简单版本：高频词）"""
        from_date = datetime.utcnow() - timedelta(days=days)
        
        queries = self.db.query(QueryLog.query_text).filter(
            QueryLog.project_id == project_id,
            QueryLog.created_at >= from_date
        ).all()
        
        # 简单词频统计
        all_text = ' '.join([q.query_text for q in queries])
        words = re.findall(r'\b[A-Z][a-zA-Z]+\b', all_text)  # 大写开头的词（可能是类名）
        
        from collections import Counter
        word_counts = Counter(words)
        
        return [
            {'entity': word, 'mentions': count}
            for word, count in word_counts.most_common(20)
        ]
```

#### 简单可视化

```python
# API 端点
@router.get("/analytics/hot-queries/{project_id}")
async def get_hot_queries(project_id: str, days: int = 7):
    """获取热门查询"""
    analytics = QueryAnalytics(db)
    return {
        "hot_queries": analytics.get_hot_queries(project_id, days),
        "unsatisfied": analytics.get_unsatisfied_queries(project_id, days),
        "popular_entities": analytics.get_popular_entities(project_id, days)
    }
```

---

### 2.4 跨项目简单关联

**目标**：发现"yunxi 和 investor-deck 都用了 AuthService"

#### 实现方式：共享标签

```python
# src/core/cross_project_analyzer.py

class CrossProjectAnalyzer:
    """跨项目分析器"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def generate_shared_tags(self) -> None:
        """为所有项目生成共享标签"""
        # 1. 提取所有项目的文件特征
        all_projects = self.db.query(Project).all()
        
        file_signatures = {}  # signature -> [(project_id, file_path)]
        
        for project in all_projects:
            project_files = self.db.query(FileAnalysis).filter(
                FileAnalysis.project_id == project.id
            ).all()
            
            for file in project_files:
                # 生成文件签名（简化版：文件名 + 关键函数名哈希）
                signature = self._generate_file_signature(file)
                
                if signature not in file_signatures:
                    file_signatures[signature] = []
                file_signatures[signature].append({
                    'project_id': project.id,
                    'file_path': file.file_path,
                    'project_name': project.name
                })
        
        # 2. 找出跨项目共享的文件
        for signature, occurrences in file_signatures.items():
            if len(occurrences) > 1:
                # 这些项目共享了类似的文件
                projects = list(set([o['project_name'] for o in occurrences]))
                
                # 创建共享标签
                tag_name = self._generate_shared_tag_name(occurrences[0]['file_path'])
                
                for occ in occurrences:
                    self._add_file_tag(
                        occ['project_id'],
                        occ['file_path'],
                        tag_name,
                        shared_with=projects
                    )
    
    def _generate_file_signature(self, file_analysis: FileAnalysis) -> str:
        """生成文件签名（用于相似度比较）"""
        # 使用文件名 + 函数名列表的哈希
        components = [file_analysis.file_path.split('/')[-1]]
        
        if file_analysis.top_imports:
            imports = json.loads(file_analysis.top_imports)
            components.extend(imports[:3])
        
        signature = '|'.join(components)
        return hashlib.md5(signature.encode()).hexdigest()[:16]
    
    def find_shared_dependencies(self) -> List[Dict]:
        """找出所有项目共享的依赖"""
        # 获取每个项目的依赖
        project_deps = {}
        
        for project in self.db.query(Project).all():
            files = self.db.query(FileAnalysis).filter(
                FileAnalysis.project_id == project.id
            ).all()
            
            deps = set()
            for f in files:
                if f.top_imports:
                    deps.update(json.loads(f.top_imports))
            
            project_deps[project.name] = deps
        
        # 找交集
        if len(project_deps) < 2:
            return []
        
        all_deps = list(project_deps.values())
        shared = all_deps[0]
        for deps in all_deps[1:]:
            shared = shared.intersection(deps)
        
        return [
            {
                'dependency': dep,
                'used_by': list(project_deps.keys())
            }
            for dep in sorted(shared)
        ]
    
    def query_cross_project(self, entity_name: str) -> List[Dict]:
        """查询实体在哪些项目中使用"""
        results = []
        
        for project in self.db.query(Project).all():
            # 查找包含该实体的文件
            files = self.db.query(FileAnalysis).filter(
                FileAnalysis.project_id == project.id
            ).all()
            
            matching_files = []
            for f in files:
                # 简单匹配：检查文件名或导入中是否包含实体名
                if entity_name.lower() in f.file_path.lower():
                    matching_files.append(f.file_path)
                elif f.top_imports and entity_name in json.loads(f.top_imports):
                    matching_files.append(f.file_path)
            
            if matching_files:
                results.append({
                    'project': project.name,
                    'files': matching_files[:5]  # 限制数量
                })
        
        return results
```

#### 数据库存储

```sql
-- 新增：文件标签表
CREATE TABLE file_tags (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    tag_name TEXT NOT NULL,
    tag_type TEXT,  -- 'shared', 'auto', 'manual'
    shared_with JSON,  -- ["project1", "project2"]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, file_path, tag_name)
);

-- 新增：跨项目关联表
CREATE TABLE cross_project_links (
    id TEXT PRIMARY KEY,
    entity_name TEXT NOT NULL,
    entity_type TEXT,  -- 'file', 'class', 'function', 'dependency'
    projects JSON NOT NULL,  -- ["project1", "project2"]
    occurrences INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(entity_name, entity_type)
);
```

---

## 三、实施计划

### Week 1

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1-2 | 代码分析器 + 文件分类器 | `code_analyzer.py`, `file_classifier.py` |
| Day 3-4 | 数据库迁移 + API 更新 | 新表结构，上下文增强的检索API |
| Day 5 | 查询日志 + 分析服务 | `analytics_service.py` |

### Week 2

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 6-7 | 跨项目分析器 | `cross_project_analyzer.py` |
| Day 8-9 | Web UI 更新 | 分析面板、跨项目查询页面 |
| Day 10 | 集成测试 + 文档 | 测试通过，更新文档 |

---

## 四、API 变更

### 新增端点

```python
# 带上下文的搜索
GET /api/v1/search/enhanced?project_id=xxx&q=xxx

# 返回示例
{
    "results": [
        {
            "content": "def auth_user()...",
            "file_path": "auth.py",
            "context": {
                "is_entry_point": false,
                "file_type": "core",
                "importance_score": 0.85,
                "callers": ["app.py", "routes.py"],
                "dependencies": ["jwt", "bcrypt"]
            },
            "enhanced_preview": "【文件: auth.py】\n【类型: core】\n【被调用: app.py, routes.py】\n---\ndef auth_user()..."
        }
    ]
}

# 分析统计
GET /api/v1/analytics/{project_id}?days=7

# 跨项目查询
GET /api/v1/cross-project/query?entity=AuthService

# 返回示例
{
    "entity": "AuthService",
    "found_in": [
        {"project": "yunxi", "files": ["services/auth.py"]},
        {"project": "investor-deck", "files": ["utils/auth.py"]}
    ],
    "shared_dependencies": ["jwt", "bcrypt"]
}
```

---

## 五、预期效果

### Agent 使用体验

| 场景 | 优化前 | 优化后 |
|------|--------|--------|
| 查代码实现 | 看到孤立代码片段 | 知道谁调用了它、是不是入口 |
| 找核心逻辑 | 在util文件里找半天 | 直接看标记为core/entry的文件 |
| 跨项目复用 | 不知道别的项目有什么 | 自动提示共享的工具类 |

### 运维价值

- 知道 Agent 经常查什么（热门查询）
- 发现 Agent 查不到的东西（未满足查询）
- 了解项目间的依赖关系

---

## 六、验收标准

- [ ] 代码片段显示"被谁调用"
- [ ] 文件自动标记为 entry/core/util/test/config
- [ ] 检索结果按重要性排序
- [ ] 能查看热门查询和未满足查询
- [ ] 能查询"X 在哪些项目里使用"
- [ ] Agent 使用分析面板可用

---

这个方案够实用吗？还是有其他更紧迫的需求？
