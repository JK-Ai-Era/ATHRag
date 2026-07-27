# ATHRag系统 - Web UI 方案

## 1. 系统概述

### 1.1 系统定位
本地部署的知识库检索系统，支持多项目管理，完全离线运行，提供 Web UI 和 API 双重访问能力。

### 1.2 核心功能
- 完全本地部署 - 数据不出境，隐私安全
- 多项目管理 - 项目间数据严格隔离
- 多格式支持 - PDF、Word、Excel、PPT、Markdown、代码文件
- 混合检索 - 语义搜索 + 关键词搜索
- Web UI - 现代化网页界面
- API 集成 - Claude Code MCP Server 支持
- 文件监控 - 自动同步 ~/Projects 目录变化

---

## 2. 现有系统分析

### 2.1 后端架构 (保留)

```
┌─────────────────────────────────────────────────────────┐
│                    RAG API (FastAPI)                     │
├─────────────────────────────────────────────────────────┤
│  Auth    │  Projects  │  Documents  │  Search  │ Watcher │
├─────────────────────────────────────────────────────────┤
│  SQLite (元数据)  │  Qdrant (向量库)  │  Ollama (Embedding) │
└─────────────────────────────────────────────────────────┘
```

### 2.2 API 端点清单

| 模块 | 端点 | 说明 |
|------|------|------|
| **认证** | POST /api/v1/auth/login | 登录获取 Token |
| **项目** | GET /api/v1/projects | 项目列表 |
| **项目** | POST /api/v1/projects | 创建项目 |
| **项目** | PUT /api/v1/projects/{id} | 更新项目 |
| **项目** | DELETE /api/v1/projects/{id} | 删除项目 |
| **文档** | GET /api/v1/projects/{id}/documents | 文档列表 |
| **文档** | POST /api/v1/projects/{id}/documents | 上传文档 |
| **文档** | DELETE /api/v1/projects/{id}/documents/{doc_id} | 删除文档 |
| **搜索** | POST /api/v1/search | 高级搜索 |
| **搜索** | GET /api/v1/search/simple | 简单搜索 |
| **监控** | POST /api/v1/watcher/start | 启动监控 |
| **监控** | POST /api/v1/watcher/stop | 停止监控 |
| **监控** | GET /api/v1/watcher/status | 监控状态 |

### 2.3 响应格式标准

统一响应格式：
```json
{
  "success": true,
  "message": "操作成功",
  "data": { ... }
}
```

---

## 3. 新 Web UI 设计方案

### 3.1 技术选型

| 层面 | 选型 | 理由 |
|------|------|------|
| 框架 | React 18 + TypeScript | 生态成熟，类型安全 |
| 构建 | Vite | 快速冷启动，HMR |
| UI 库 | Ant Design 5.x | 企业级组件，中文友好 |
| 状态管理 | Zustand | 轻量，无样板代码 |
| 路由 | React Router v6 | 官方标准 |
| HTTP 客户端 | Axios | 成熟稳定 |

### 3.2 项目结构

```
web/
├── public/
├── src/
│   ├── api/              # API 层
│   ├── components/       # 公共组件
│   ├── hooks/            # 自定义 Hooks
│   ├── pages/            # 页面组件
│   ├── stores/           # 状态管理
│   ├── types/            # TypeScript 类型
│   ├── utils/            # 工具函数
│   ├── App.tsx
│   └── main.tsx
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

---

## 4. 页面详细设计

### 4.1 登录页 (/login)
- 用户名/密码登录
- 记住登录状态
- 居中卡片布局

### 4.2 项目列表页 (/)
- 项目卡片网格展示
- 搜索过滤
- 新建/删除项目
- 自动同步开关

### 4.3 项目详情页 (/projects/:id)
**Tab 1: 智能搜索**
- 搜索模式选择（语义/关键词/混合）
- 搜索结果列表
- 结果高亮

**Tab 2: 文档管理**
- 文档列表
- 拖拽上传
- 删除/导出文档

**Tab 3: 项目设置**
- 项目名称/描述修改
- 自动同步开关
- 删除项目

### 4.4 监控管理页 (/watcher)
- 监控状态显示
- 启动/停止监控
- 同步统计

---

## 5. API 客户端设计

### 5.1 核心配置

```typescript
// 统一在 axios 拦截器中处理响应
// 自动提取 response.data.data
// 401 自动跳转登录页
```

### 5.2 关键改进
- API 响应统一处理
- 完善的错误处理
- 加载状态管理

---

## 6. 开发计划 (5-6天)

| 阶段 | 内容 | 时间 |
|------|------|------|
| 1 | 基础框架搭建 | 1天 |
| 2 | 认证模块 | 0.5天 |
| 3 | 项目列表 | 1天 |
| 4 | 项目详情 | 2天 |
| 5 | 监控管理 | 0.5天 |
| 6 | 优化完善 | 1天 |

---

**方案版本**: v1.0
**制定日期**: 2026-03-01
