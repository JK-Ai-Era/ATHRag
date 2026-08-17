#!/usr/bin/env python3
"""ATHRag 部署前依赖检查

在部署到新机器时运行此脚本，验证所有依赖都已正确安装。
用法: python scripts/check-deps.py
"""

import sys
import importlib

# 所有必需的第三方依赖（与 pyproject.toml 同步）
REQUIRED = [
    # Web Framework
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    
    # Auth
    ("jose", "python-jose[cryptography]"),
    ("bcrypt", "bcrypt"),
    
    # Vector DB
    ("qdrant_client", "qdrant-client"),
    
    # Database
    ("sqlalchemy", "sqlalchemy"),
    
    # Document Processing
    ("docx", "python-docx"),
    ("pypdf", "pypdf"),
    ("bs4", "beautifulsoup4"),
    ("lxml", "lxml"),
    ("openpyxl", "openpyxl"),
    ("PIL", "Pillow"),
    
    # Embedding / LLM
    ("ollama", "ollama"),
    
    # Search & NLP
    ("rank_bm25", "rank-bm25"),
    ("jieba", "jieba"),
    ("sklearn", "scikit-learn"),
    ("sentence_transformers", "sentence-transformers"),
    
    # CLI
    ("typer", "typer"),
    ("rich", "rich"),
    
    # Utilities
    ("pydantic", "pydantic"),
    ("pydantic_settings", "pydantic-settings"),
    ("dotenv", "python-dotenv"),
    ("aiofiles", "aiofiles"),
    ("tenacity", "tenacity"),
    ("httpx", "httpx"),
    ("watchdog", "watchdog"),
    ("yaml", "PyYAML"),
    ("requests", "requests"),
    ("loguru", "loguru"),
]

# 可选依赖（失败不阻断，只警告）
OPTIONAL = [
    ("torch", "torch (Reranker 需要，首次加载会自动下载模型)"),
    ("unstructured", "unstructured[all-docs] (部分文档格式支持)"),
    ("mcp", "mcp (MCP 协议支持)"),
]


def check_dependencies():
    """检查所有依赖"""
    missing_required = []
    missing_optional = []
    
    print("🔍 ATHRag 依赖检查\n")
    
    # 检查必需依赖
    for module, package in REQUIRED:
        try:
            importlib.import_module(module)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package}")
            missing_required.append(package)
    
    # 检查可选依赖
    print("\n可选依赖:")
    for module, desc in OPTIONAL:
        try:
            importlib.import_module(module)
            print(f"  ✅ {desc}")
        except ImportError:
            print(f"  ⚠️  {desc} (可选)")
            missing_optional.append(desc)
    
    # 结果
    print(f"\n{'='*50}")
    if missing_required:
        print(f"\n❌ 缺少 {len(missing_required)} 个必需依赖:")
        for pkg in missing_required:
            print(f"   pip install {pkg}")
        print(f"\n一键安装:")
        print(f"   pip install {' '.join(missing_required)}")
        return False
    
    if missing_optional:
        print(f"\n⚠️  缺少 {len(missing_optional)} 个可选依赖（不影响核心功能）")
    
    print("\n✅ 所有必需依赖已安装，可以部署！")
    return True


if __name__ == "__main__":
    ok = check_dependencies()
    sys.exit(0 if ok else 1)
