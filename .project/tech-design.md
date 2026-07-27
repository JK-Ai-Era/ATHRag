# RAG Web UI 重构 - 技术设计方案

**项目名称**: ATHRag Web UI  
**负责人**: Coder  
**版本**: v1.0  
**日期**: 2026-03-01

---

## 一、技术方案概述

### 1.1 设计目标
- **简洁**: 代码结构清晰，易于维护
- **现代**: 使用最新的前端技术栈
- **稳定**: 类型安全，错误处理完善
- **体验**: 流畅的交互，良好的反馈

### 1.2 技术选型

| 层级 | 技术/框架 | 版本 | 选型理由 |
|-----|----------|------|---------|
| 框架 | **Next.js 15** | 15.x | App Router、RSC、更好的性能 |
| 语言 | **TypeScript** | 5.x | 类型安全，开发体验好 |
| 样式 | **Tailwind CSS** | 4.x | 原子化CSS，开发效率高 |
| 组件库 | **shadcn/ui** | latest | 基于Radix，可定制性强 |
| 状态管理 | **Zustand** | 5.x | 简洁轻量，TypeScript友好 |
| 数据获取 | **TanStack Query** | 5.x | 缓存、重试、实时更新 |
| 图标 | **Lucide React** | latest | 统一风格，树摇优化 |
| HTTP | **Axios** | 1.x | 拦截器、错误处理 |

**不选 Vue 的理由**: 
- 现有 Vue 代码已混乱，重构成本不亚于重写
- Next.js App Router 的 RSC/SSR 更适合内容型应用
- React 生态更成熟，组件库更丰富

---

## 二、架构设计

### 2.1 目录结构

```
web/next-app/
├── app/                          # Next.js App Router
│   ├── (auth)/                   # 认证路由组
│   │   └── login/
│   │       └── page.tsx
│   ├── (main)/                   # 主界面路由组
│   │   ├── layout.tsx            # 侧边栏布局
│   │   ├── projects/
│   │   │   └── page.tsx          # 项目列表
│   │   └── projects/[id]/
│   │       ├── layout.tsx        # 项目内导航
│   │       ├── page.tsx          # 项目概览
│   │       ├── search/
│   │       │   └── page.tsx      # 搜索
│   │       ├── documents/
│   │       │   └── page.tsx      # 文档列表
│   │       └── upload/
│   │           └── page.tsx      # 上传
│   ├── api/                      # API Routes (可选)
│   ├── layout.tsx                # 根布局
│   └── page.tsx                  # 首页(重定向)
├── components/                   # React组件
│   ├── ui/                       # shadcn/ui 组件
│   ├── layout/                   # 布局组件
│   │   ├── sidebar.tsx
│   │   ├── header.tsx
│   │   └── project-nav.tsx
│   ├── projects/                 # 项目相关
│   │   ├── project-card.tsx
│   │   ├── project-form.tsx
│   │   └── project-list.tsx
│   ├── documents/                # 文档相关
│   │   ├── document-list.tsx
│   │   ├── document-card.tsx
│   │   └── upload-dropzone.tsx
│   ├── search/                   # 搜索相关
│   │   ├── search-box.tsx
│   │   ├── search-results.tsx
│   │   └── result-card.tsx
│   └── watcher/                  # Watcher相关
│       └── watcher-control.tsx
├── hooks/                        # 自定义Hooks
│   ├── use-auth.ts
│   ├── use-projects.ts
│   ├── use-documents.ts
│   ├── use-search.ts
│   └── use-watcher.ts
├── lib/                          # 工具库
│   ├── api.ts                    # API客户端
│   ├── utils.ts                  # 工具函数
│   └── constants.ts              # 常量
├── stores/                       # Zustand状态
│   ├── auth-store.ts
│   ├── project-store.ts
│   └── ui-store.ts
├── types/                        # TypeScript类型
│   └── index.ts
└── public/                       # 静态资源
```

### 2.2 模块划分

| 模块 | 职责 | 核心文件 |
|-----|------|---------|
| **Auth** | 登录/登出/Token管理 | `hooks/use-auth.ts`, `stores/auth-store.ts` |
| **Project** | 项目CRUD | `hooks/use-projects.ts`, `components/projects/*` |
| **Document** | 文档管理/上传 | `hooks/use-documents.ts`, `components/documents/*` |
| **Search** | 搜索功能 | `hooks/use-search.ts`, `components/search/*` |
| **Watcher** | 文件监控 | `hooks/use-watcher.ts`, `components/watcher/*` |

---

## 三、接口设计

### 3.1 API 客户端 (`lib/api.ts`)

**多环境支持**：Web UI 需要同时支持本地局域网访问和外网访问，API 地址根据访问域名自动适配。

| 访问方式 | Web UI 地址 | API 地址 |
|---------|------------|---------|
| 本地局域网 | `http://192.168.3.191:3090` | `http://192.168.3.191:8000` |
| 外网 | `https://rag.kwok.vip` | `https://rag-api.kwok.vip` |
| 本机开发 | `http://localhost:3090` | `http://localhost:8000` |

```typescript
// lib/api.ts - 统一封装的API客户端
import axios from 'axios';

// 根据当前访问域名自动判断API地址
const getApiBaseUrl = (): string => {
  const hostname = window.location.hostname;
  
  // 外网访问 (通过 frp 转发)
  if (hostname === 'rag.kwok.vip') {
    return 'https://rag-api.kwok.vip';
  }
  
  // 本地局域网访问 (192.168.x.x)
  if (hostname.startsWith('192.168.')) {
    // 使用 https 协议访问局域网API
    return `http://${hostname}:8000`;
  }
  
  // 本机开发环境
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return 'http://localhost:8000';
  }
  
  // 默认兜底
  return 'http://localhost:8000';
};

const apiClient = axios.create({
  baseURL: getApiBaseUrl(),
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器 - 添加Token
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('rag_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截器 - 统一处理错误
apiClient.interceptors.response.use(
  (response) => response.data?.data ?? response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('rag_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default apiClient;
```

### 3.2 后端 CORS 配置

后端需要配置允许的来源域名：

```python
# src/rag_api/main.py - CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # 外网域名
        "https://rag.kwok.vip",
        # 局域网IP (192.168.x.x)
        "http://192.168.3.191:3090",
        "https://192.168.3.191:3090",
        # 本机开发
        "http://localhost:3000",
        "http://localhost:3090",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3090",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)
```

### 3.3 核心接口封装

```typescript
// lib/api.ts - 接口方法
export const authApi = {
  login: (username: string, password: string) => 
    apiClient.post('/api/v1/auth/login/json', { username, password }),
  me: () => apiClient.get('/api/v1/auth/me'),
};

export const projectApi = {
  list: () => apiClient.get('/api/v1/projects'),
  get: (id: string) => apiClient.get(`/api/v1/projects/${id}`),
  create: (data: CreateProjectDTO) => apiClient.post('/api/v1/projects', data),
  update: (id: string, data: UpdateProjectDTO) => apiClient.put(`/api/v1/projects/${id}`, data),
  delete: (id: string) => apiClient.delete(`/api/v1/projects/${id}`),
};

export const documentApi = {
  list: (projectId: string) => apiClient.get(`/api/v1/projects/${projectId}/documents`),
  upload: (projectId: string, file: File, onProgress?: (progress: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    return apiClient.post(`/api/v1/projects/${projectId}/documents`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (progressEvent) => {
        const progress = progressEvent.total
          ? Math.round((progressEvent.loaded * 100) / progressEvent.total)
          : 0;
        onProgress?.(progress);
      },
    });
  },
  delete: (projectId: string, documentId: string) => 
    apiClient.delete(`/api/v1/projects/${projectId}/documents/${documentId}`),
  export: (projectId: string, documentId: string, format: 'txt' | 'json' = 'txt') =>
    apiClient.get(`/api/v1/projects/${projectId}/documents/${documentId}/export?format=${format}`),
};

export const searchApi = {
  search: (params: SearchParams) => apiClient.post('/api/v1/search', params),
};

export const watcherApi = {
  status: () => apiClient.get('/api/v1/watcher/status'),
  start: () => apiClient.post('/api/v1/watcher/start'),
  stop: () => apiClient.post('/api/v1/watcher/stop'),
  stats: () => apiClient.get('/api/v1/watcher/stats'),
};
```

---

## 四、状态管理设计

### 4.1 Zustand 全局状态

```typescript
// stores/auth-store.ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  token: string | null;
  username: string | null;
  isAuthenticated: boolean;
  setToken: (token: string) => void;
  setUsername: (username: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      username: null,
      isAuthenticated: false,
      setToken: (token) => set({ token, isAuthenticated: true }),
      setUsername: (username) => set({ username }),
      logout: () => set({ token: null, username: null, isAuthenticated: false }),
    }),
    { name: 'auth-storage' }
  )
);

// stores/project-store.ts
interface ProjectState {
  currentProject: Project | null;
  setCurrentProject: (project: Project | null) => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  currentProject: null,
  setCurrentProject: (project) => set({ currentProject: project }),
}));
```

### 4.2 TanStack Query 服务端状态

```typescript
// hooks/use-projects.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { projectApi } from '@/lib/api';

export const useProjects = () => {
  return useQuery({
    queryKey: ['projects'],
    queryFn: () => projectApi.list(),
  });
};

export const useCreateProject = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: projectApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
  });
};
```

---

## 五、关键功能实现

### 5.1 文件上传组件

```typescript
// components/documents/upload-dropzone.tsx
'use client';

import { useCallback, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { useUploadDocument } from '@/hooks/use-documents';

interface UploadFile {
  id: string;
  file: File;
  name: string;
  size: number;
  progress: number;
  status: 'pending' | 'uploading' | 'completed' | 'error';
  error?: string;
}

export function UploadDropzone({ projectId }: { projectId: string }) {
  const [files, setFiles] = useState<UploadFile[]>([]);
  const uploadMutation = useUploadDocument(projectId);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles: UploadFile[] = acceptedFiles.map((file) => ({
      id: crypto.randomUUID(),
      file,
      name: file.name,
      size: file.size,
      progress: 0,
      status: 'pending',
    }));
    setFiles((prev) => [...prev, ...newFiles]);
    
    // 自动开始上传
    newFiles.forEach((fileItem) => {
      uploadMutation.mutate(
        {
          file: fileItem.file,
          onProgress: (progress) => {
            setFiles((prev) =>
              prev.map((f) =>
                f.id === fileItem.id ? { ...f, progress, status: 'uploading' } : f
              )
            );
          },
        },
        {
          onSuccess: () => {
            setFiles((prev) =>
              prev.map((f) =>
                f.id === fileItem.id ? { ...f, progress: 100, status: 'completed' } : f
              )
            );
          },
          onError: () => {
            setFiles((prev) =>
              prev.map((f) =>
                f.id === fileItem.id ? { ...f, status: 'error' } : f
              )
            );
          },
        }
      );
    });
  }, [projectId, uploadMutation]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'text/markdown': ['.md', '.markdown'],
      'text/plain': ['.txt'],
    },
    maxSize: 50 * 1024 * 1024, // 50MB
  });

  return (
    <div {...getRootProps()} className="border-2 border-dashed rounded-lg p-8">
      <input {...getInputProps()} />
      <p>拖拽文件到此处，或点击选择</p>
    </div>
  );
}
```

---

## 六、部署配置

### 6.1 环境变量

```bash
# .env.local - 开发环境
NEXT_PUBLIC_API_URL=http://localhost:8000

# .env.production - 生产环境 (由前端代码自动判断，无需配置)
# API 地址通过 window.location.hostname 自动判断
```

### 6.2 构建部署

```bash
# 安装依赖
npm install

# 开发
npm run dev

# 构建
npm run build

# 生产运行
npm start
```

### 6.3 Nginx 配置

```nginx
# 外网访问 (rag.kwok.vip)
server {
    listen 443 ssl;
    server_name rag.kwok.vip;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:3090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

# 局域网访问 (192.168.3.191:3090)
# 直接监听端口，无需额外配置
```

---

## 七、开发计划

### Phase 1: 基础搭建 (Day 1)
- [ ] 初始化 Next.js 15 项目
- [ ] 配置 Tailwind CSS + shadcn/ui
- [ ] 搭建项目目录结构
- [ ] 配置 API 客户端（含多环境支持）

### Phase 2: 认证模块 (Day 1)
- [ ] 登录页面
- [ ] Auth Store
- [ ] 路由守卫

### Phase 3: 项目模块 (Day 2)
- [ ] 项目列表页面
- [ ] 创建/编辑项目
- [ ] 项目卡片组件

### Phase 4: 搜索模块 (Day 2)
- [ ] 搜索页面
- [ ] 搜索结果组件
- [ ] 高亮显示

### Phase 5: 文档模块 (Day 3)
- [ ] 文档列表
- [ ] 文件上传（拖拽）
- [ ] 删除文档

### Phase 6: Watcher模块 (Day 3)
- [ ] Watcher控制面板
- [ ] 状态显示

### Phase 7: 测试与优化 (Day 4)
- [ ] 功能测试
- [ ] 性能优化
- [ ] Bug修复

---

## 八、变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|-----|------|---------|-------|
| v1.0 | 2026-03-01 | 初始版本 | Coder |
| v1.1 | 2026-03-01 | 增加多环境API配置和CORS说明 | Coder |
