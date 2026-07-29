# 2026-07-29 ATHRag 架构重构 — 插件化解析系统

## 背景

大哥提出话剧配乐系统需求，引发对 ATHRag 架构的深入讨论。核心问题：
1. 现有 DocumentProcessor 把所有解析逻辑（PDF、Office、图片、代码）塞在一个 433 行的文件里
2. 依赖越来越重（MinerU 需要单独的 Python 3.11 venv，Unstructured 是大包）
3. Watcher 直接调 DocumentService，耦合紧密，无队列、无并发控制
4. 未来加新格式（音频、视频、CAD）每次都要改 ATHRag 核心代码

## 架构决策

### 1. 职责边界
- **ATHRag = 知识基础设施**：文件监控 → 解析 → 分块 → 向量化 → 索引 → 检索
- **Agent/Skill = 应用层**：消费 ATHRag 检索能力，结合 LLM 做业务分析（如剧本配乐推荐）
- 剧本解析不属于 ATHRag，属于 Skill 层

### 2. 插件化解析系统
- 所有格式解析器做成独立 CLI 工具，遵守标准化 JSON 输出契约
- ATHRag 通过 parsers.yaml 配置注册解析器，根据文件扩展名自动路由
- 新增格式 = 新 CLI 工具 + 注册配置，ATHRag 核心代码零改动

### 3. 三层队列架构
- 第 1 层：Watchdog → parse_queue（事件持久化，不阻塞）
- 第 2 层：Parse Worker → 调解析 CLI → 写结果（并发受控）
- 第 3 层：embedding_queue → 向量化（已有，不改动）

### 4. 语义增强
- 格式解析（必须）：提取文本内容
- 语义增强（可选但有价值）：LLM 生成摘要/关键词/标签
- 语义增强放在解析器内部做，结果通过 `semantic` 字段传给 RAG

## 今日完成

### 架构文档
- `docs/architecture/README.md` — 完整的架构设计文档

### doc-analyzer CLI 工具（P1 阶段）
位置：`tools/doc-analyzer/`

已完成模块：
- `src/contract.py` — 标准化输出契约（ParseResult、SemanticInfo、ChunkInfo、validate_output）
- `src/parsers/base.py` — 解析器基类
- `src/parsers/pdf.py` — PDF 解析器（MinerU 优先 / pypdf 回退）
- `src/parsers/office.py` — Office 解析器（Unstructured 优先 / 原生回退）
- `src/parsers/image.py` — 图片 OCR 解析器（pytesseract）
- `src/parsers/text.py` — 纯文本 / Markdown 解析器
- `src/parsers/code.py` — 代码注释提取器（Python AST / 正则兜底）
- `src/parsers/unstructured_parser.py` — Unstructured Office 解析器（从 ATHRag 迁移）
- `src/parsers/__init__.py` — 解析器注册表
- `src/dispatcher.py` — 解析器调度器（根据扩展名自动路由）
- `src/cli.py` — CLI 入口（单文件解析、批量解析、列出格式、状态检查）
- `config/parsers.yaml` — 解析器注册配置
- `tests/test_contract.py` — 契约测试（16 个）
- `tests/test_dispatcher.py` — 调度器测试（14 个）

测试结果：**30 个测试全部通过**

### 关键设计
1. **标准化输出契约**：所有解析器必须输出 `{source, type, format, content, metadata}` + 可选 `{chunks, semantic}`
2. **解析器注册制**：parsers.yaml 配置扩展名映射，dispatcher 自动路由
3. **双后端策略**：每个解析器优先高质量后端（MinerU/Unstructured），失败自动回退轻量后端

## 待办

- [ ] P2: audio-analyzer CLI 工具
- [ ] P3: ATHRag 解析层改造（Watcher → Parse Queue → Worker）
- [ ] P4: ATHRag 接口扩展（index_parsed_result + 音频元数据）
- [ ] P5: music-director Skill
- [ ] P6: MiniMax 生成集成
