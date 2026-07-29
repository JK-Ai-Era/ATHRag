# 2026-07-29 — 插件化解析系统与模型配置统一

## 背景

ATHRag 原有的文档解析是内嵌在 DocumentProcessor 中的，扩展新格式需要改核心代码。本次改造目标：
1. 解析器独立为 CLI 工具，通过标准化 JSON 契约与主程序通信
2. 文件处理从同步直连改为异步队列
3. 模型配置统一管理，支持 provider 切换

## P1: doc-analyzer CLI

**位置**：`tools/doc-analyzer/`

6 个解析器：pdf（MinerU/pypdf）、office（Unstructured/native）、image（Tesseract OCR）、text、markdown、code（注释提取）。

标准化 JSON 输出契约（ParseResult），解析器调度器按扩展名自动路由。30 个测试全过。

## P2: audio-analyzer CLI

**位置**：`tools/audio-analyzer/`

4 个解析器：
- **metadata**（mutagen）— 提取 ID3 标签、时长、采样率
- **features**（librosa）— BPM、调性、响度、频谱质心、过零率
- **speech**（Whisper）— 语音转文字，支持本地/API 切换
- **classify**（PANNs CNN14）— 527 类 AudioSet 音频事件识别

修复了 features.py 的 numpy import bug 和 speech.py 的文件检查顺序问题。41 个测试全过。

## P3: 解析层改造

**架构变化**：
```
旧：Watchdog → Handler → FileSync → DocumentProcessor（同步阻塞）
新：Watchdog → Handler → parse_queue → Worker → CLI 解析器 → DocumentService（异步队列）
```

新增模块：
- `config/parsers.yaml` — 解析器注册表（5 个解析器，44 种格式）
- `ParseQueue` 数据库模型 — 持久化解析队列（SHA256 去重、3 次重试、优先级排序）
- `core/parse_dispatcher.py` — 读 yaml 配置，路由文件到 CLI，从 venv/bin 激活
- `core/parse_worker.py` — 轮询队列，调 CLI，喂 DocumentService
- `watcher/handler.py` 改造 — create/modify 写队列，delete/move 走 FileSync

三层队列：事件队列（Debouncer）→ 解析队列（parse_queue）→ 向量化队列（embedding_queue）。

22 个新测试全过。

## P4: 接口扩展

新增 API 端点：
- `GET /api/v1/queue/status` — 队列状态统计
- `GET /api/v1/queue/tasks` — 任务列表（支持状态/项目筛选）
- `POST /api/v1/queue/enqueue` — 手动入队
- `POST /api/v1/queue/retry` — 重试失败任务
- `DELETE /api/v1/queue/tasks/{id}` — 删除任务
- `DELETE /api/v1/queue/clear` — 清理已完成任务
- `GET /api/v1/parsers` — 解析器列表
- `GET /api/v1/parsers/formats` — 支持格式
- `GET /api/v1/parsers/check/{ext}` — 格式检查

## 模型配置统一（provider 模式）

**核心设计**：一个 `config/models.yaml` 管所有模型选型，切换 provider = 切换实现，上游代码零改动。

```yaml
audio:
  speech:
    provider: whisper-local   # 改成 openai-api 就切到云端
    model: base
  classify:
    provider: panns           # 改成 none 就禁用
    device: auto              # 自动检测 MPS/CUDA/CPU
document:
  pdf:
    provider: mineru          # 改成 pypdf 就用轻量方案
  office:
    provider: unstructured    # 改成 native 就用原生解析器
  image:
    provider: tesseract
    languages: chi_sim+eng    # OCR 语言可配置
```

每个 CLI 工具有独立的 `model_config.py`，不依赖主程序。硬件设备自动检测（MPS/CUDA/CPU）。

## 缺陷审查与修复

审查发现 10 个缺陷，修复 8 个：

| # | 缺陷 | 严重度 | 修复 |
|---|------|--------|------|
| 1 | SQLAlchemy 对象脱离 Session | 🔴 | session 内提取值到局部变量 |
| 2 | 同名文件覆盖 | 🔴 | 同名不同文件用哈希前缀区分 |
| 3 | CLI venv 未激活 | 🔴 | parsers.yaml 加 venv 字段 |
| 4 | 文件未写完就入队 | 🟡 | 两次 stat 检查文件稳定性 |
| 5 | file_type 映射不一致 | 🟡 | parsers.yaml 显式声明 file_type |
| 6 | _config_cache 缓存 bug | 🟡 | 重写缓存逻辑 |
| 7 | 空哈希不唯一 | 🟡 | 空哈希用路径+时间戳生成 |
| 9 | classify 标签未缓存 | 🟢 | 实例级缓存 |

保留的设计决策：dispatch 异常处理（ValueError 传播）、model_config 重复（CLI 工具独立性）。

## 测试汇总

| 模块 | 测试数 | 状态 |
|------|--------|------|
| doc-analyzer | 30 | ✅ |
| audio-analyzer | 41 | ✅ |
| parse_queue (P3/P4) | 22 | ✅ |
| **合计** | **93** | **全过** |

## 文件变更

新增文件：
- `config/parsers.yaml` — 解析器注册表
- `config/models.yaml` — 统一模型配置
- `src/core/model_config.py` — 模型配置加载器
- `src/core/parse_dispatcher.py` — 解析器调度器
- `src/core/parse_worker.py` — 解析队列 Worker
- `src/rag_api/routers/queue.py` — 队列管理 API
- `src/rag_api/routers/parsers.py` — 解析器信息 API
- `tests/test_parse_queue.py` — P3/P4 测试
- `tools/doc-analyzer/` — 文档解析 CLI 工具
- `tools/audio-analyzer/` — 音频解析 CLI 工具

修改文件：
- `src/rag_api/main.py` — 注册 queue/parsers 路由
- `src/rag_api/models/database.py` — 新增 ParseQueue 模型
- `src/watcher/handler.py` — 改造为队列化处理

## 待办

- P5: music-director Skill（话剧配乐推荐）
- PANNs 模型下载（312MB，首次运行自动下载）
- CLI 工具 venv 初始化脚本（setup-tools.sh）
