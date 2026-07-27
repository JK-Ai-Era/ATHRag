#!/bin/bash

# ATHRag系统启动脚本
# 一键启动所有必要服务

set -e

echo "🚀 ATHRag 启动脚本"
echo "================================"
echo ""

PROJECT_DIR="$HOME/Projects/ATHRag"
cd "$PROJECT_DIR"

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    echo "❌ 虚拟环境不存在，请先运行 ./scripts/setup.sh"
    exit 1
fi

source .venv/bin/activate

# 启动 Qdrant
echo "📦 启动 Qdrant..."
QDRANT_PID=""
if ! curl -s http://localhost:6333/healthz > /dev/null 2>&1; then
    echo "   启动 Qdrant 服务..."
    ./scripts/start-qdrant.sh > /tmp/qdrant.log 2>&1 &
    QDRANT_PID=$!
    
    # 等待启动
    for i in {1..10}; do
        if curl -s http://localhost:6333/healthz > /dev/null 2>&1; then
            echo "   ✓ Qdrant 已启动 (PID: $QDRANT_PID)"
            break
        fi
        sleep 1
    done
else
    echo "   ✓ Qdrant 已在运行"
fi

# 检查 Ollama
echo "🧠 检查 Ollama..."
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "   ⚠️  Ollama 未运行，请手动启动: ollama serve"
else
    echo "   ✓ Ollama 运行中"
    
    # 检查 bge-m3
    if ollama list | grep -q "bge-m3"; then
        echo "   ✓ bge-m3 模型已加载"
    else
        echo "   ⚠️  bge-m3 模型未加载，正在拉取..."
        ollama pull bge-m3
    fi
fi

echo ""
echo "🌐 启动 API 服务..."
echo "   地址: http://localhost:8000"
echo "   文档: http://localhost:8000/docs"
echo ""
echo "按 Ctrl+C 停止服务"
echo ""

# 捕获退出信号
cleanup() {
    echo ""
    echo "🛑 正在停止服务..."
    if [ -n "$QDRANT_PID" ]; then
        kill $QDRANT_PID 2> /dev/null || true
        echo "   ✓ Qdrant 已停止"
    fi
    exit 0
}
trap cleanup INT TERM

# 启动 API
exec uvicorn src.rag_api.main:app --host 0.0.0.0 --port 8000 --reload
