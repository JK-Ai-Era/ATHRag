# Unstructured 解析器进程隔离

## 日期
2026-08-21

## 背景
研究 Apache Tika 4.x 后决定不引入（Java 栈冲突、我们已有更好的 PDF/Office 方案），但借鉴了其**进程隔离解析**的理念。Tika 4.x 用 forked process 解析，恶意文档崩溃不影响主服务。我们的 Unstructured 解析器之前是直接在主进程内 import 调用，存在同样风险。

## 改动

### 新增
- `scripts/unstructured_processor.py`：独立子进程解析脚本，通过 stdin 接收 JSON 参数，stdout 输出 JSON 结果
  - 支持 `text` 模式（返回 markdown/text）和 `structured` 模式（返回完整结构含 tables/sections/images）
  - 内部 import `src.core.unstructured_parser.UnstructuredOfficeParser`，复用已有解析逻辑

### 修改
- `src/core/document_processor.py`：
  - `_extract_with_unstructured()` → 改为调用 `_run_unstructured_subprocess()`
  - `extract_structured()` → 改为调用 `_run_unstructured_subprocess(mode="structured")`
  - 新增 `_run_unstructured_subprocess()`：subprocess 调用，stdin/stdout JSON 协议，120s 超时
  - 添加 `import sys`

### 未改动
- `src/core/unstructured_parser.py`：保持原样，仍然可被直接 import 使用
- 原生解析器（python-docx/openpyxl/python-pptx）：保留作为回退

## 架构对比

```
之前：
  主进程 → import UnstructuredOfficeParser → 解析（在主进程内）

之后：
  主进程 → subprocess(unstructured_processor.py) → 子进程内 import → 解析
           ↑ stdin: JSON {file_path, mode}
           ↓ stdout: JSON {success, markdown, ...}
```

## 防护效果
- **崩溃隔离**：恶意文档导致 segfault/异常只杀子进程，主服务不受影响
- **内存隔离**：Unstructured 的内存泄漏不会传播到主进程
- **超时保护**：120s 超时自动终止，防止解析卡死
- **原生回退**：子进程失败时仍可回退到 python-docx/openpyxl/python-pptx

## 测试
- docx text 模式：✅ 2800 字符
- docx structured 模式：✅ text=2800, markdown=2800, tables=0, sections=1
- xlsx text 模式：✅ 19786 字符
- 原生回退：✅ 2793 字符
