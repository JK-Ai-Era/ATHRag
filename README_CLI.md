# RAG CLI 管理工具 - ath

本地 ATHRag系统的命令行管理工具，提供服务、项目、文档、搜索等管理功能。

## 安装

```bash
cd ~/Projects/ATHRag
pip install -e .
```

安装后即可使用 `ath` 命令。

## 快速开始

```bash
# 查看帮助
ath --help

# 查看版本
ath version

# 查看服务状态
ath service status

# 列出所有项目
ath project list

# 搜索知识库（推荐混合搜索）
ath search hybrid yunxi "数据中台架构"
```

## 命令结构

```
ath
├── service      服务管理
├── project      项目管理
├── doc          文档管理
├── search       搜索
├── watcher      文件监控
├── system       系统信息
└── auth         认证管理
```

---

## 服务管理

```bash
# 查看所有服务状态（包括 Watcher）
ath service status

# 启动所有服务
ath service start

# 停止所有服务
ath service stop

# 重启所有服务
ath service restart

# 查看服务日志
ath service logs api
ath service logs qdrant
ath service logs web

# 查看所有日志（默认每个服务最后 10 行）
ath service logs
```

**服务端口**：

| 服务 | 端口 | 说明 |
|------|------|------|
| API | 8000 | RAG API 服务 |
| Qdrant | 6333 | 向量数据库 |
| Web UI | 3000 | Web 界面 |
| Ollama | 11434 | LLM 服务（非受控） |

---

## 项目管理

```bash
# 列出所有项目
ath project list

# 显示完整 ID
ath project list --full

# 创建项目
ath project create my-project --desc "项目描述"

# 查看项目详情
ath project info <project_id>

# 查看项目统计
ath project stats <project_id>

# 检查项目数据一致性
ath project check <project_id>

# 自动清理孤立文件
ath project check <project_id> --cleanup

# 重新索引项目所有文档
ath project reindex <project_id>

# 强制扫描项目文件
ath project scan <project_id>

# 删除项目
ath project delete <project_id> --force

# 清理孤儿项目（文件夹已删除但数据库记录存在）
ath project clean-orphan

# 只显示，不实际删除
ath project clean-orphan --dry-run
```

**提示**：项目 ID 支持使用项目名称，会自动解析：
```bash
ath project info yunxi        # 使用名称
ath project stats openviking  # 使用名称
```

---

## 文档管理

```bash
# 列出项目文档
ath doc list <project>

# 分页显示
ath doc list yunxi -l 20      # 每页 20 个
ath doc list yunxi -p 2       # 第 2 页

# 搜索文件名
ath doc list yunxi -s "调研"
ath doc list yunxi -s ".xlsx"  # 搜索所有 Excel 文件

# 显示完整 ID
ath doc list yunxi --full

# 上传文档
ath doc upload <project> /path/to/file.pdf

# 上传整个目录
ath doc upload <project> /path/to/directory --recursive

# 导出文档内容
ath doc export <project> <doc_id> --output output.txt
ath doc export <project> <doc_id> --format markdown

# 删除文档
ath doc delete <project> <doc_id> --force
```

---

## 搜索

搜索命令已重构为子命令模式，支持四种搜索方式：

### 语义搜索（向量相似度）

```bash
ath search semantic <project> "搜索内容"
ath search semantic yunxi "采矿计划编制" -k 10
```

### 关键词搜索（BM25）

```bash
ath search keyword <project> "关键词"
ath search keyword yunxi "业务场景" -k 5
```

### 混合搜索（推荐）

向量 + BM25 + RRF 融合，效果最佳：

```bash
ath search hybrid <project> "搜索内容"
ath search hybrid yunxi "数据中台架构" -k 5
ath search hybrid yunxi "系统设计" --threshold 0.7
ath search hybrid openviking "OpenClaw配置" --full  # 显示完整内容
```

### 层次化搜索（RAPTOR）

文档摘要 + chunks，适合长文档：

```bash
ath search hierarchical <project> "搜索内容"
ath search hierarchical yunxi "项目总体设计"
```

**通用参数**：

| 参数 | 说明 |
|------|------|
| `-k, --top-k` | 返回数量（默认 10） |
| `-t, --threshold` | 分数阈值（0-1） |
| `-f, --full` | 显示完整内容（不截断） |

---

## 文件监控

```bash
# 查看监控状态
ath watcher status

# 启动文件监控
ath watcher start

# 停止文件监控
ath watcher stop

# 查看同步统计
ath watcher stats

# 强制扫描项目（不指定则扫描所有）
ath watcher scan
ath watcher scan yunxi

# 重置统计
ath watcher reset-stats
ath watcher reset-stats yunxi

# 刷新项目监控状态（即时生效）
ath watcher refresh yunxi --enable   # 启用监控
ath watcher refresh yunxi --disable  # 禁用监控

# 同步所有 watcher_enabled 项目
ath watcher sync-all
```

---

## 系统信息

```bash
# 健康检查（检查所有服务状态）
ath system health

# 系统统计（项目数、文档数、存储大小）
ath system stats

# 系统信息（配置、端口状态）
ath system info
```

---

## 认证管理

```bash
# 登录
ath auth login
ath auth login -u admin -p password

# 查看认证状态
ath auth status

# 登出
ath auth logout

# 配置环境变量自动登录
ath auth setup
```

**环境变量**（可替代登录）：

```bash
export RAG_API_USERNAME=admin
export RAG_API_PASSWORD=your-password
```

---

## 配置文件

配置文件位于 `~/.config/ath/config.yaml`：

```yaml
api:
  url: http://localhost:8000
  timeout: 30

services:
  qdrant:
    host: localhost
    port: 6333
  ollama:
    host: localhost
    port: 11434
  web:
    host: localhost
    port: 3000

auth:
  enabled: true
  token_file: ~/.config/ath/token

logging:
  level: INFO
```

---

## 常用操作示例

### 搜索文档

```bash
# 快速搜索（推荐）
ath search hybrid yunxi "数据治理方案"

# 精确搜索关键词
ath search keyword yunxi "Excel导出"

# 查看完整内容
ath search hybrid yunxi "系统架构" -k 3 --full
```

### 管理项目

```bash
# 检查项目健康状态
ath project check yunxi

# 重新索引失败文档
ath project reindex yunxi

# 查看存储统计
ath project stats yunxi
ath system stats
```

### 文件监控

```bash
# 启用项目监控
ath watcher refresh yunxi --enable

# 查看同步状态
ath watcher status
ath watcher stats
```

---

## 故障排查

### 无法连接 API

```bash
# 检查服务状态
ath service status

# 查看 API 日志
ath service logs api -n 100

# 重启服务
ath service restart
```

### 认证失败

```bash
# 检查认证状态
ath auth status

# 重新登录
ath auth login

# 或配置环境变量
ath auth setup
```

### 项目数据不一致

```bash
# 检查项目
ath project check yunxi

# 清理孤儿项目
ath project clean-orphan --dry-run  # 先预览
ath project clean-orphan            # 实际清理
```

### 查看详细日志

```bash
# API 日志
tail -f ~/Projects/ATHRag/logs/api_latest.log

# Qdrant 日志
tail -f ~/.qdrant/logs/stderr.log
```

---

## 命令别名

```bash
alias rag='ath'
alias rsearch='ath search hybrid'
alias rlist='ath project list'
alias rstatus='ath service status'
```

---

## 版本信息

```bash
ath version
# ath v0.1.0
# ATHRag CLI Tool
```