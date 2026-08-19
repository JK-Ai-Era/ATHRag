#!/bin/bash

# Qdrant 本地二进制启动脚本
# 用于 Docker 不可用时

QDRANT_VERSION="1.12.0"
QDRANT_DIR="$HOME/.qdrant"
QDRANT_BIN="$QDRANT_DIR/qdrant"

# 创建目录
mkdir -p "$QDRANT_DIR"
mkdir -p "$QDRANT_DIR/storage"

# 检查是否已下载
if [ ! -f "$QDRANT_BIN" ]; then
    echo "📥 下载 Qdrant..."
    
    # 检测架构
    ARCH=$(uname -m)
    if [ "$ARCH" = "arm64" ]; then
        DOWNLOAD_URL="https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/qdrant-${ARCH}-apple-darwin.tar.gz"
    else
        DOWNLOAD_URL="https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/qdrant-x86_64-apple-darwin.tar.gz"
    fi
    
    curl -L "$DOWNLOAD_URL" -o /tmp/qdrant.tar.gz
    tar -xzf /tmp/qdrant.tar.gz -C "$QDRANT_DIR"
    chmod +x "$QDRANT_BIN"
    rm /tmp/qdrant.tar.gz
    
    echo "✓ Qdrant 下载完成"
fi

# 检查端口是否已被占用（避免与 launchd 服务冲突）
if lsof -i :6333 -sTCP:LISTEN > /dev/null 2>&1; then
    echo "⚠️  端口 6333 已被占用，Qdrant 已在运行："
    lsof -i :6333 -sTCP:LISTEN | head -3
    echo ""
    echo "如需重启，请先运行: launchctl stop com.athrag.qdrant"
    exit 1
fi

# 启动 Qdrant
echo "🚀 启动 Qdrant..."
echo "   地址: http://localhost:6333"
echo ""

cd "$QDRANT_DIR"
exec "$QDRANT_BIN"
