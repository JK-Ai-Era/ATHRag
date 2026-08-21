#!/usr/bin/env python3
"""
Unstructured Office 文档处理器 - 子进程隔离版

在独立进程中解析 docx/xlsx/pptx，防止恶意文档崩溃主服务。
通过 stdin 接收 JSON 参数，stdout 输出 JSON 结果。

用法:
    echo '{"file_path": "/path/to/doc.docx", "mode": "text"}' | python unstructured_processor.py
    echo '{"file_path": "/path/to/doc.docx", "mode": "structured"}' | python unstructured_processor.py
"""

import sys
import json
import os
import traceback

# 确保项目根目录在 sys.path 中
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)


def parse_document(file_path: str, mode: str = "text") -> dict:
    """解析 Office 文档

    Args:
        file_path: 文件路径
        mode: "text" 返回纯文本/markdown，"structured" 返回完整结构

    Returns:
        dict: 解析结果
    """
    from pathlib import Path
    from src.core.unstructured_parser import UnstructuredOfficeParser

    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": f"文件不存在: {file_path}"}

    suffix = path.suffix.lower()
    parser = UnstructuredOfficeParser()

    if suffix == ".docx":
        result = parser.parse_docx(path)
    elif suffix == ".xlsx":
        result = parser.parse_xlsx(path)
    elif suffix == ".pptx":
        result = parser.parse_pptx(path)
    else:
        return {"success": False, "error": f"不支持的格式: {suffix}"}

    if mode == "structured":
        return {
            "success": True,
            "text": result.text,
            "markdown": result.markdown,
            "metadata": result.metadata,
            "tables": [
                {
                    "caption": t.caption,
                    "headers": t.headers,
                    "rows": t.rows,
                    "html": t.html,
                }
                for t in result.tables
            ],
            "sections": [
                {
                    "title": s.title,
                    "level": s.level,
                    "content": s.content,
                    "start_page": s.start_page,
                }
                for s in result.sections
            ],
            "images": result.images,
            "page_count": result.page_count,
        }
    else:
        return {
            "success": True,
            "markdown": result.markdown,
            "text": result.text,
        }


def main():
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            print(json.dumps({"success": False, "error": "无输入参数"}))
            sys.exit(1)

        params = json.loads(raw)
        file_path = params.get("file_path")
        mode = params.get("mode", "text")

        if not file_path:
            print(json.dumps({"success": False, "error": "缺少 file_path 参数"}))
            sys.exit(1)

        result = parse_document(file_path, mode)
        print(json.dumps(result, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
