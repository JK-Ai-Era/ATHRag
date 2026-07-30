# 架构深度审查与修复

## 背景

基于 2026-07-29 的插件化解析系统重构，对整个项目进行架构级审查，发现 9 项问题（3 严重 + 6 中等）。

## 问题分析与修复

### 严重问题（P0）

#### 1. ParseWorker 竞态条件

**根因**：`_process_batch()` 用 SELECT → UPDATE 两步领取任务，`get_db_session()` 默认 `BEGIN DEFERRED`，读锁在 SELECT 后释放，两个 Worker 能同时 SELECT 到同一批 pending 任务。

**修复**：
- 新增 `get_db_session_immediate()` 使用 `BEGIN IMMEDIATE`，事务开始就持有写锁
- 用 `UPDATE ... WHERE id IN (SELECT ...)` 单条原子 SQL 领取任务
- 消除了 SELECT → UPDATE 之间的时间窗口

#### 2. DocumentService 事务安全

**根因**：`process_document()` 是一个 200+ 行的方法，在同一个 session 里多次 `db.commit()`。创建文档 → 保存分块 → 向量化 → 更新状态 → BM25 → 摘要，全部共用一个 session，中间状态暴露，部分失败时数据库不一致。还有"直接模式"和"队列模式"两条路径，行为不一致。

**修复**：重构为四阶段短事务设计：
- Phase 1 `_save_doc_and_chunks()`：一个事务，原子保存文档记录和所有分块
- Phase 2 `_vectorize_chunks()`：独立操作，逐个向量化，允许部分失败
- Phase 3 `_finalize()`：一个事务，更新文档状态和项目统计
- Phase 4 `_side_effects()`：BM25 + 层次化索引，尽力而为

废弃了 embedding_queue 双轨制（队列模式从未有 worker 消费），统一为直接向量化。

#### 3. EmbeddingService 连接泄漏 + 零向量矛盾

**根因**：
- `embed_batch()` 捕获异常后返回零向量 `[0.0]*dim`，与 `embed_text_sync()` "不返回零向量"的注释行为相反
- `httpx.Client` 全局单例在多线程共享，不是线程安全的
- `close()` 方法存在但从未被调用

**修复**：
- `embed_batch()` 返回 `(results, failed_indices)`，失败位置为 None
- `sync_client` 改为 `threading.local()`，每个线程独立实例
- 新增 `get_embedding_service()` 单例，main.py lifespan 关闭时清理连接

### 中等问题（P1）

#### 4. 统一解析路径
DocumentService 不再直接调用 DocumentProcessor，解析统一走 ParseDispatcher → DocumentService pipeline。所有文件入库（API 上传、Watcher 检测）都经过 parse_queue → ParseWorker → ParseDispatcher → DocumentService。

#### 5. 统一向量化状态
废弃 embedding_queue 双轨制。队列模式从未有 worker 消费，chunks 入队后永远不会被向量化。统一为直接向量化模式，状态反映真实结果。

#### 6. 统一 LLM 客户端
创建 `src/core/llm_client.py`，`LLMClient` 封装 Ollama chat 调用。`QueryTransformer`、`ContextCompressor`、`SummaryGenerator` 三处重复代码统一使用 `LLMClient.chat()` / `LLMClient.chat_sync()`。

#### 7. HierarchicalIndex 清理
`VectorStore.delete_collection()` 现在同时删除 `project_{id}` 和 `project_{id}_summaries` 两个 collection。

#### 8. BM25 内存优化
移除 `self.corpus` 原文存储。BM25 搜索只需要分词后的 token 列表，不需要原文。`search()` 返回 `(chunk_id, score)`，content 由调用方从数据库获取。内存占用降低约 50%。

#### 9. 向量状态统一
移除 `update_chunk_vector_status()` 原生 SQL 调用。向量状态直接通过 `chunk.vector_id` 判断：`None` = 未向量化，有值 = 已向量化。不再维护冗余的 `vector_status` / `vector_error` 字段。

## 影响范围

- 15 个文件变更，649 行新增，896 行删除
- 核心重构：document_service.py（-996 +重写）
- 新增文件：llm_client.py
- 所有 import 验证通过
- BM25 功能测试通过

## 决策记录

1. **废弃 embedding_queue**：设计有但从未实现 worker，属于半成品，直接移除
2. **DocumentService 不再接收 db 参数**：内部自管理事务，每个阶段独立 session
3. **embed_batch 返回 Tuple**：允许调用方区分成功/失败，不再静默返回零向量
