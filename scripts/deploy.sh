#!/bin/bash
# =============================================
# ATHRag 一键部署脚本
# 用法: bash scripts/deploy.sh
# =============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "🚀 ATHRag 部署"
echo "================================"
echo "项目目录: $PROJECT_DIR"
echo ""

# ── 1. Python 环境 ──────────────────────────
echo "📦 [1/6] Python 环境"
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo "  创建虚拟环境..."
    python3 -m venv "$PROJECT_DIR/.venv"
fi
source "$PROJECT_DIR/.venv/bin/activate"
echo "  ✅ Python $(python3 --version 2>&1 | cut -d' ' -f2)"

# ── 2. 安装依赖 ─────────────────────────────
echo ""
echo "📦 [2/6] 安装 Python 依赖"
cd "$PROJECT_DIR"
pip install -e . --quiet 2>&1 | tail -3
echo "  ✅ 依赖安装完成"

# ── 3. 依赖检查 ─────────────────────────────
echo ""
echo "🔍 [3/6] 依赖验证"
python scripts/check-deps.py
if [ $? -ne 0 ]; then
    echo "❌ 依赖检查失败，请先安装缺失的包"
    exit 1
fi

# ── 4. 配置文件 ─────────────────────────────
echo ""
echo "⚙️  [4/6] 配置文件"
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    # 自动生成 SECRET_KEY
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/^SECRET_KEY=$/SECRET_KEY=$SECRET/" "$PROJECT_DIR/.env"
    else
        sed -i "s/^SECRET_KEY=$/SECRET_KEY=$SECRET/" "$PROJECT_DIR/.env"
    fi
    echo "  ⚠️  已生成 .env，请编辑以下必填项:"
    echo "     ADMIN_PASSWORD  — 管理员密码"
    echo "     WATCHER_ROOT    — 项目监听目录（可选）"
else
    echo "  ✅ .env 已存在"
fi

# ── 5. 数据库 ───────────────────────────────
echo ""
echo "🗄️  [5/6] 数据库初始化"
mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/data/projects" "$PROJECT_DIR/data/vector_db" "$PROJECT_DIR/db"
# 数据库表由应用启动时自动创建（SQLAlchemy create_all）
if [ -f "$PROJECT_DIR/db/metadata.db" ]; then
    echo "  ✅ 数据库已存在"
else
    echo "  ✅ 数据库将在首次启动时自动创建"
fi

# ── 6. 外部服务 ─────────────────────────────
echo ""
echo "🔧 [6/6] 外部服务"

# Ollama
if command -v ollama &> /dev/null; then
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "  ✅ Ollama 运行中"
        # 检查 bge-m3
        if ollama list 2>/dev/null | grep -q "bge-m3"; then
            echo "  ✅ bge-m3 模型已安装"
        else
            echo "  ⏳ 下载 bge-m3 模型..."
            ollama pull bge-m3
        fi
    else
        echo "  ⚠️  Ollama 已安装但未运行，请手动启动: ollama serve"
    fi
else
    echo "  ⚠️  Ollama 未安装，请先安装: brew install ollama"
fi

# Qdrant
QDRANT_BIN="$HOME/.qdrant/qdrant"
if [ ! -f "$QDRANT_BIN" ]; then
    echo "  ⏳ 下载 Qdrant..."
    bash "$SCRIPT_DIR/start-qdrant.sh" &
    sleep 3
    kill %1 2>/dev/null || true
fi
if [ -f "$QDRANT_BIN" ]; then
    echo "  ✅ Qdrant 已安装"
else
    echo "  ⚠️  Qdrant 下载失败，请手动运行: bash scripts/start-qdrant.sh"
fi

# ── 完成 ─────────────────────────────────────
echo ""
echo "================================"
echo "✅ 部署完成！"
echo ""
echo "启动方式:"
echo "  方式一（推荐）: bash scripts/install-services.sh  # launchd 托管，开机自启"
echo "  方式二:          bash scripts/start-all.sh         # 前台运行"
echo ""
echo "访问地址:"
echo "  API:  http://localhost:16250/docs"
echo "  CLI:  ath search hybrid <项目名> <查询>"
