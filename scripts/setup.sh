#!/bin/bash

# ATHRag系统初始化脚本

set -e

echo "🚀 ATHRag 初始化脚本"
echo "================================"
echo ""

# 检查 Python 版本
echo "📋 检查 Python 版本..."
python_version=$(python --version 2>&1 | awk '{print $2}')
echo "   Python 版本: $python_version"

# 检查是否在项目目录
if [ ! -f "pyproject.toml" ]; then
    echo "❌ 错误: 请在项目根目录运行此脚本"
    exit 1
fi

# 创建虚拟环境
echo ""
echo "📦 创建虚拟环境..."
if [ ! -d ".venv" ]; then
    python -m venv .venv
    echo "   ✓ 虚拟环境已创建"
else
    echo "   ✓ 虚拟环境已存在"
fi

# 激活虚拟环境
echo ""
echo "🔌 激活虚拟环境..."
source .venv/bin/activate

# 升级 pip
echo ""
echo "⬆️  升级 pip..."
pip install --upgrade pip

# 安装项目依赖
echo ""
echo "📥 安装项目依赖..."
pip install -e ".[dev]"

# 初始化数据库
echo ""
echo "🗄️  初始化数据库..."
python -c "from src.rag_api.models.database import init_db; init_db()"
echo "   ✓ 数据库已初始化"

# 创建必要的目录
echo ""
echo "📁 创建数据目录..."
mkdir -p data/projects data/vector_db db logs
echo "   ✓ 目录已创建"

# 复制环境变量模板
echo ""
echo "⚙️  环境变量配置..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "   ✓ 已创建 .env 文件，请根据需要修改配置"
else
    echo "   ✓ .env 文件已存在"
fi

# 检查 Ollama
echo ""
echo "🔍 检查 Ollama..."
if command -v ollama &> /dev/null; then
    echo "   ✓ Ollama 已安装"
    
    # 检查 bge-m3 模型
    if ollama list | grep -q "bge-m3"; then
        echo "   ✓ bge-m3 模型已存在"
    else
        echo "   ⚠️  bge-m3 模型未找到，建议运行: ollama pull bge-m3"
    fi
else
    echo "   ⚠️  Ollama 未安装，请访问 https://ollama.com 安装"
fi

# 检查 Docker
echo ""
echo "🐳 检查 Docker..."
if command -v docker &> /dev/null; then
    echo "   ✓ Docker 已安装"
    
    # 询问是否启动 Qdrant
    read -p "是否启动 Qdrant 容器? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "   启动 Qdrant..."
        docker run -d \
            --name rag-qdrant \
            -p 6333:6333 \
            -v $(pwd)/data/vector_db:/qdrant/storage \
            --restart unless-stopped \
            qdrant/qdrant
        echo "   ✓ Qdrant 已启动 (http://localhost:6333)"
    fi
else
    echo "   ⚠️  Docker 未安装，Qdrant 需要手动部署"
fi

echo ""
echo "================================"
echo "✅ 初始化完成!"
echo ""
echo "📖 下一步:"
echo "   1. 确保 Ollama 运行中: ollama serve"
echo "   2. 拉取模型: ollama pull bge-m3"
echo "   3. 确保 Qdrant 运行中（Docker 或本地部署）"
echo "   4. 启动 API 服务: rag serve"
echo "   5. 或使用 CLI: rag --help"
echo ""
echo "📚 文档: http://localhost:8000/docs (服务启动后)"
echo ""
