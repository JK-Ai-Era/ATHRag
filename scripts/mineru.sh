#!/bin/bash

# MinerU PDF 处理脚本
# 使用 Python 3.11 环境

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV311="$PROJECT_DIR/.venv-311"

# 检查 Python 3.11 环境
if [ ! -d "$VENV311" ]; then
    echo "Error: Python 3.11 虚拟环境不存在"
    exit 1
fi

# 使用 Python 3.11 运行处理器
source "$VENV311/bin/activate"
python "$SCRIPT_DIR/mineru_processor.py" "$@"
