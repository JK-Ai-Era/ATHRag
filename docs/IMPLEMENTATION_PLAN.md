# RAG 实用升级 - 实现方案

## 一、数据库变更

### 1.1 新增表结构

```sql
-- 文件分析表（代码上下文+重要性）
CREATE TABLE file_analysis (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_type TEXT DEFAULT 'normal',  -- entry, core, util, config, test, normal
    is_entry_point BOOLEAN DEFAULT FALSE,
    importance_score REAL DEFAULT 0.0,
    import_count INTEGER DEFAULT 0,
    imported_by_count INTEGER DEFAULT 0,
    function_count INTEGER DEFAULT 0,
    class_count INTEGER DEFAULT 0,
    top_imports JSON DEFAULT '[]',
    called_by JSON DEFAULT '[]',  -- 谁调用了这个文件
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, file_path)
);

-- 查询日志表
CREATE TABLE query_logs (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    query_text TEXT NOT NULL,
    results_count INTEGER,
    source TEXT DEFAULT 'api',  -- mcp, web, cli
    created_at TIMESTAM DEFAULT CURRENT_TIMESTAMP
);

-- 跨项目标签表
CREATE TABLE file_tags (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    tag_name TEXT NOT NULL,
    shared_with JSON DEFAULT '[]',  -- ["project1", "project2"]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, file_path, tag_name)
);

-- 索引
CREATE INDEX idx_file_analysis_project ON file_analysis(project_id);
CREATE INDEX idx_file_analysis_type ON file_analysis(file_type);
CREATE INDEX idx_query_logs_project ON query_logs(project_id);
CREATE INDEX idx_query_logs_created ON query_logs(created_at);
```

## 二、核心模块实现

### 2.1 代码分析器

```python
# src/core/code_analyzer.py
import re
import json
from pathlib import Path
from typing import Dict, List, Set, Optional
from dataclasses import dataclass

@dataclass
class FileAnalysisResult:
    file_path: str
    file_type: str
    is_entry_point: bool
    importance_score: float
    import_count: int
    imported_by_count: int
    function_count: int
    class_count: int
    top_imports: List[str]
    called_by: List[str]

class CodeAnalyzer:
    """分析项目代码结构"""
    
    ENTRY_PATTERNS = [
        r'if\s+__name__\s*==\s*["\']__main__["\']',
        r'@app\.(route|get|post|put|delete)',
        r'uvicorn\.run',
        r'fastapi\s*import\s*FastAPI',
        r'flask\.Flask',
    ]
    
    ENTRY_FILENAMES = {'main.py', 'app.py', 'server.py', 'cli.py', 'manage.py', 'wsgi.py'}
    
    TEST_PATTERNS = [r'test_', r'_test\.py$', r'__tests__', r'\.test\.', r'\.spec\.']
    CONFIG_PATTERNS = [r'config', r'settings', r'\.env', r'pyproject\.toml', r'package\.json']
    UTIL_PATTERNS = [r'util', r'helper', r'common', r'shared', r'/lib/', r'/libs/']
    
    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.import_graph: Dict[str, List[str]] = {}
        self.file_info: Dict[str, Dict] = {}
    
    def analyze_project(self) -> List[FileAnalysisResult]:
        """分析整个项目"""
        # 第一步：收集所有文件信息
        for file_path in self._get_code_files():
            self.file_info[str(file_path)] = self._analyze_single_file(file_path)
        
        # 第二步：构建导入关系图
        self._build_import_graph()
        
        # 第三步：计算被导入次数
        self._calculate_imported_by()
        
        # 第四步：生成结果
        results = []
        for file_path, info in self.file_info.items():
            result = self._create_result(file_path, info)
            results.append(result)
        
        return results
    
    def _get_code_files(self) -> List[Path]:
        """获取所有代码文件"""
        code_files = []
        for ext in ['*.py', '*.js', '*.ts', '*.java', '*.go']:
            code_files.extend(self.project_path.rglob(ext))
        return code_files
    
    def _analyze_single_file(self, file_path: Path) -> Dict:
        """分析单个文件"""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            return {}
        
        # 提取导入
        imports = self._extract_imports(content)
        
        # 提取定义
        functions = re.findall(r'^(?:async\s+)?def\s+(\w+)\s*\(', content, re.MULTILINE)
        classes = re.findall(r'^class\s+(\w+)', content, re.MULTILINE)
        
        # 检查是否为入口
        is_entry = self._check_entry_point(file_path, content)
        
        return {
            'imports': imports,
            'import_count': len(imports),
            'functions': functions,
            'function_count': len(functions),
            'classes': classes,
            'class_count': len(classes),
            'is_entry_point': is_entry,
            'content': content[:5000],  # 缓存前5000字符用于进一步分析
        }
    
    def _extract_imports(self, content: str) -> List[str]:
        """提取导入语句"""
        imports = []
        
        # Python imports
        for match in re.finditer(r'^from\s+([\w.]+)', content, re.MULTILINE):
            imports.append(match.group(1))
        for match in re.finditer(r'^import\s+([\w.]+)', content, re.MULTILINE):
            imports.append(match.group(1))
        
        return imports[:20]  # 限制数量
    
    def _check_entry_point(self, file_path: Path, content: str) -> bool:
        """检查是否为入口文件"""
        # 文件名检查
        if file_path.name in self.ENTRY_FILENAMES:
            return True
        
        # 内容检查
        for pattern in self.ENTRY_PATTERNS:
            if re.search(pattern, content):
                return True
        
        return False
    
    def _build_import_graph(self):
        """构建导入关系图"""
        for file_path, info in self.file_info.items():
            self.import_graph[file_path] = info.get('imports', [])
    
    def _calculate_imported_by(self):
        """计算每个文件被谁导入"""
        for file_path in self.file_info:
            called_by = []
            file_module = self._path_to_module(file_path)
            
            for other_path, imports in self.import_graph.items():
                if other_path == file_path:
                    continue
                
                # 检查是否导入当前文件
                for imp in imports:
                    if file_module and file_module in imp:
                        called_by.append(other_path)
                        break
            
            self.file_info[file_path]['called_by'] = called_by
            self.file_info[file_path]['imported_by_count'] = len(called_by)
    
    def _path_to_module(self, file_path: str) -> Optional[str]:
        """将文件路径转为模块名"""
        path = Path(file_path)
        if path.suffix == '.py':
            return path.stem
        return None
    
    def _create_result(self, file_path: str, info: Dict) -> FileAnalysisResult:
        """创建分析结果"""
        # 分类文件类型
        file_type = self._classify_file(file_path, info)
        
        # 计算重要性分数
        score = self._calculate_importance(info, file_type)
        
        return FileAnalysisResult(
            file_path=file_path,
            file_type=file_type,
            is_entry_point=info.get('is_entry_point', False),
            importance_score=score,
            import_count=info.get('import_count', 0),
            imported_by_count=info.get('imported_by_count', 0),
            function_count=info.get('function_count', 0),
            class_count=info.get('class_count', 0),
            top_imports=info.get('imports', [])[:10],
            called_by=info.get('called_by', [])[:5],
        )
    
    def _classify_file(self, file_path: str, info: Dict) -> str:
        """分类文件类型"""
        path_lower = file_path.lower()
        
        # 测试文件
        for pattern in self.TEST_PATTERNS:
            if re.search(pattern, path_lower):
                return 'test'
        
        # 配置文件
        for pattern in self.CONFIG_PATTERNS:
            if pattern in path_lower:
                return 'config'
        
        # 工具文件
        for pattern in self.UTIL_PATTERNS:
            if pattern in path_lower:
                return 'util'
        
        # 入口文件
        if info.get('is_entry_point'):
            return 'entry'
        
        # 核心文件（被很多文件导入）
        if info.get('imported_by_count', 0) >= 5:
            return 'core'
        
        return 'normal'
    
    def _calculate_importance(self, info: Dict, file_type: str) -> float:
        """计算重要性分数 (0-1)"""
        score = 0.0
        
        # 被导入次数（最多贡献0.4）
        imported_by = info.get('imported_by_count', 0)
        score += min(imported_by / 10, 0.4)
        
        # 入口文件（贡献0.3）
        if info.get('is_entry_point'):
            score += 0.3
        
        # 代码量（最多贡献0.2）
        func_count = info.get('function_count', 0)
        class_count = info.get('class_count', 0)
        score += min((func_count + class_count * 2) / 20, 0.2)
        
        # 类型加成
        type_bonus = {
            'entry': 0.1,
            'core': 0.08,
            'config': 0.03,
            'util': 0.02,
            'test': 0,
            'normal': 0,
        }
        score += type_bonus.get(file_type, 0)
        
        return min(round(score, 2), 1.0)
```

### 2.2 分析任务调度

```python
# src/services/analysis_service.py
from sqlalchemy.orm import Session
from src.core.code_analyzer import CodeAnalyzer
from src.rag_api.models.database import FileAnalysis
import json

class AnalysisService:
    """文件分析服务"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def analyze_project(self, project_id: str, project_path: Path) -> None:
        """分析整个项目并保存结果"""
        analyzer = CodeAnalyzer(project_path)
        results = analyzer.analyze_project()
        
        # 清空旧数据
        self.db.query(FileAnalysis).filter(
            FileAnalysis.project_id == project_id
        ).delete()
        
        # 保存新数据
        for result in results:
            analysis = FileAnalysis(
                id=str(uuid4()),
                project_id=project_id,
                file_path=result.file_path,
                file_type=result.file_type,
                is_entry_point=result.is_entry_point,
                importance_score=result.importance_score,
                import_count=result.import_count,
                imported_by_count=result.imported_by_count,
                function_count=result.function_count,
                class_count=result.class_count,
                top_imports=json.dumps(result.top_imports),
                called_by=json.dumps(result.called_by),
            )
            self.db.add(analysis)
        
        self.db.commit()
    
    def get_file_context(self, project_id: str, file_path: str) -> Optional[Dict]:
        """获取文件上下文"""
        analysis = self.db.query(FileAnalysis).filter(
            FileAnalysis.project_id == project_id,
            FileAnalysis.file_path == file_path
        ).first()
        
        if not analysis:
            return None
        
        return {
            'file_type': analysis.file_type,
            'is_entry_point': analysis.is_entry_point,
            'importance_score': analysis.importance_score,
            'import_count': analysis.import_count,
            'imported_by_count': analysis.imported_by_count,
            'top_imports': json.loads(analysis.top_imports),
            'called_by': json.loads(analysis.called_by),
        }
```

### 2.3 查询日志服务

```python
# src/services/query_logger.py
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from sqlalchemy import func

class QueryLogger:
    """查询日志服务"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def log(self, query_text: str, project_id: str = None,
            results_count: int = 0, source: str = 'api') -> None:
        """记录查询"""
        log = QueryLog(
            id=str(uuid4()),
            project_id=project_id,
            query_text=query_text,
            results_count=results_count,
            source=source,
            created_at=datetime.utcnow(),
        )
        self.db.add(log)
        self.db.commit()
    
    def get_hot_queries(self, project_id: str = None, days: int = 7, limit: int = 20):
        """获取热门查询"""
        since = datetime.utcnow() - timedelta(days=days)
        
        query = self.db.query(
            QueryLog.query_text,
            func.count(QueryLog.id).label('count')
        ).filter(
            QueryLog.created_at >= since
        )
        
        if project_id:
            query = query.filter(QueryLog.project_id == project_id)
        
        return query.group_by(
            QueryLog.query_text
        ).order_by(
            func.count(QueryLog.id).desc()
        ).limit(limit).all()
    
    def get_unsatisfied_queries(self, project_id: str = None, days: int = 7):
        """获取未满足查询（结果少）"""
        since = datetime.utcnow() - timedelta(days=days)
        
        return self.db.query(QueryLog).filter(
            QueryLog.created_at >= since,
            QueryLog.results_count < 3
        ).order_by(
            QueryLog.created_at.desc()
        ).limit(50).all()
```

### 2.4 跨项目关联

```python
# src/services/cross_project_service.py
import hashlib
import json
from sqlalchemy.orm import Session

class CrossProjectService:
    """跨项目关联服务"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def find_shared_files(self):
        """找出跨项目共享的文件"""
        # 获取所有文件分析
        all_files = self.db.query(FileAnalysis).all()
        
        # 按签名分组
        signatures = {}
        for file in all_files:
            sig = self._file_signature(file)
            if sig not in signatures:
                signatures[sig] = []
            signatures[sig].append(file)
        
        # 找出共享的
        shared = []
        for sig, files in signatures.items():
            if len(files) > 1:
                projects = list(set([f.project_id for f in files]))
                if len(projects) > 1:
                    shared.append({
                        'file_pattern': files[0].file_path.split('/')[-1],
                        'count': len(files),
                        'projects': projects,
                    })
        
        return shared
    
    def _file_signature(self, file: FileAnalysis) -> str:
        """生成文件签名"""
        # 简单签名：文件名 + 函数数量 + 类数量
        parts = [
            file.file_path.split('/')[-1],
            str(file.function_count),
            str(file.class_count),
        ]
        return hashlib.md5('|'.join(parts).encode()).hexdigest()[:12]
    
    def query_entity_across_projects(self, entity_name: str):
        """查询实体在哪些项目中使用"""
        results = []
        
        # 简单匹配：检查文件路径和导入
        all_files = self.db.query(FileAnalysis).all()
        
        project_files = {}
        for file in all_files:
            matched = False
            
            # 检查文件名
            if entity_name.lower() in file.file_path.lower():
                matched = True
            
            # 检查导入
            imports = json.loads(file.top_imports)
            for imp in imports:
                if entity_name.lower() in imp.lower():
                    matched = True
                    break
            
            if matched:
                if file.project_id not in project_files:
                    project_files[file.project_id] = []
                project_files[file.project_id].append(file.file_path)
        
        # 转为项目名
        for project_id, files in project_files.items():
            project = self.db.query(Project).get(project_id)
            if project:
                results.append({
                    'project': project.name,
                    'files': files[:5],
                })
        
        return results
```

## 三、API 端点

```python
# src/rag_api/routers/enhanced_search.py

@router.get("/search/enhanced")
async def enhanced_search(
    project_id: str,
    q: str,
    include_context: bool = True,
    db: Session = Depends(get_db)
):
    """增强搜索（带上下文）"""
    # 原有搜索
    results = await search_service.search(project_id, q)
    
    # 添加上下文
    if include_context:
        analysis_service = AnalysisService(db)
        for result in results:
            context = analysis_service.get_file_context(
                project_id, result['file_path']
            )
            if context:
                result['context'] = context
                result['enhanced_preview'] = format_with_context(
                    result['content'], context, result['file_path']
                )
    
    # 按重要性排序
    results.sort(
        key=lambda x: x.get('context', {}).get('importance_score', 0),
        reverse=True
    )
    
    return {"results": results}

# src/rag_api/routers/analytics.py

@router.get("/analytics/{project_id}")
async def get_analytics(project_id: str, days: int = 7, db: Session = Depends(get_db)):
    """获取分析数据"""
    logger = QueryLogger(db)
    
    hot = logger.get_hot_queries(project_id, days)
    unsatisfied = logger.get_unsatisfied_queries(project_id, days)
    
    return {
        "hot_queries": [{"query": q, "count": c} for q, c in hot],
        "unsatisfied_count": len(unsatisfied),
        "unsatisfied_examples": [q.query_text for q in unsatisfied[:10]],
    }

# src/rag_api/routers/cross_project.py

@router.get("/cross-project/entity/{entity_name}")
async def query_entity(entity_name: str, db: Session = Depends(get_db)):
    """跨项目查询实体"""
    service = CrossProjectService(db)
    results = service.query_entity_across_projects(entity_name)
    return {"entity": entity_name, "found_in": results}

@router.get("/cross-project/shared")
async def get_shared_files(db: Session = Depends(get_db)):
    """获取跨项目共享的文件"""
    service = CrossProjectService(db)
    return {"shared": service.find_shared_files()}
```

## 四、集成点

### 4.1 文件同步时触发分析

```python
# 在 watcher/handler.py 中
async def on_file_created(self, file_path: Path):
    # 原有逻辑...
    
    # 新增：触发分析
    if file_path.suffix in ['.py', '.js', '.ts']:
        asyncio.create_task(
            self._analyze_file_later(file_path)
        )

async def _analyze_file_later(self, file_path: Path):
    """延迟分析（避免阻塞）"""
    await asyncio.sleep(5)  # 等待文件稳定
    service = AnalysisService(self.db)
    service.analyze_project(self.project_id, self.project_path)
```

### 4.2 搜索时记录日志

```python
# 在 search_service.py 中
async def search(self, project_id: str, query: str):
    results = await self._do_search(project_id, query)
    
    # 记录查询
    logger = QueryLogger(self.db)
    logger.log(query, project_id, len(results))
    
    return results
```

## 五、实施步骤（Agent 并行模式）

**说明**：以下按 AI Agent 团队并行执行规划，非人类开发时间。Coder/Tester 可并行工作，无需按天顺序执行。

### Phase 1: 基础层（并行）
**可同时执行**：

**Coder A - 数据库层**
- [ ] 执行 migration 创建新表
- [ ] 测试数据库连接和查询

**Coder B - 代码分析器**
- [ ] 实现 `CodeAnalyzer` 类
- [ ] 支持 Python/JS/TS 分析
- [ ] 测试分析准确性

**Coder C - 分析服务**
- [ ] 实现 `AnalysisService`
- [ ] 保存分析结果到 DB
- [ ] 提供查询接口

**交付物**：数据库就绪 + 代码分析功能可用

### Phase 2: 服务层（并行）

**Coder D - API 集成**
- [ ] 增强搜索 API（带上下文）
- [ ] 集成到现有搜索流程
- [ ] 按重要性重排序

**Coder E - 查询日志**
- [ ] 实现 `QueryLogger`
- [ ] 记录所有查询
- [ ] 统计 API

**Coder F - 跨项目服务**
- [ ] 文件签名算法
- [ ] 跨项目查询
- [ ] 共享文件发现

**交付物**：所有 API 可用

### Phase 3: 集成与测试（并行）

**Coder G - Watcher 集成**
- [ ] 文件变更时触发重新分析
- [ ] 异步分析任务

**Tester - 测试验证**
- [ ] 单元测试
- [ ] 集成测试
- [ ] 性能测试

**Coder H - Web UI**
- [ ] 搜索结果显示上下文
- [ ] 分析面板页面
- [ ] 跨项目关联页面

**交付物**：完整功能可用

### Phase 4: 验收

**MC 验收**：
- [ ] 验证所有功能符合预期
- [ ] 检查代码质量
- [ ] 确认测试通过

---

**时间估算**：
- Phase 1: 30-40 分钟（并行）
- Phase 2: 30-40 分钟（并行）
- Phase 3: 40-60 分钟（并行）
- Phase 4: 10-15 分钟

**总计：约 2 小时（AI Agent 团队）**

## 六、验收检查清单

- [ ] 代码片段显示文件类型和被调用信息
- [ ] 文件自动标记 entry/core/util/config/test
- [ ] 检索结果按重要性排序
- [ ] 能查看热门查询和未满足查询
- [ ] 能查询"X 在哪些项目里使用"
- [ ] 文件变更后自动重新分析

---

**就按这个做，有问题随时调整。**
