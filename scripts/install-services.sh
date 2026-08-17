#!/bin/bash
# ATHRag macOS LaunchD 服务安装
# 用法: bash scripts/install-services.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_DIR="$HOME/Library/LaunchAgents"
QDRANT_BIN="$HOME/.qdrant/qdrant"
VENV_UVICORN="$PROJECT_DIR/.venv/bin/uvicorn"

echo "🚀 ATHRag 服务安装"
echo "================================"

# 检查前置条件
if [ ! -f "$QDRANT_BIN" ]; then
    echo "❌ Qdrant 未安装，运行: bash scripts/start-qdrant.sh"
    exit 1
fi

if [ ! -f "$VENV_UVICORN" ]; then
    echo "❌ 虚拟环境未找到，请先运行: python3 -m venv .venv && .venv/bin/pip install -e ."
    exit 1
fi

mkdir -p "$PLIST_DIR"

# 安装 Qdrant plist
echo "📦 安装 Qdrant 服务..."
cat > "$PLIST_DIR/com.athrag.qdrant.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.athrag.qdrant</string>
    <key>ProgramArguments</key>
    <array>
        <string>$QDRANT_BIN</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$HOME/.qdrant</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>3</integer>
    <key>StandardOutPath</key>
    <string>/tmp/qdrant.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/qdrant.log</string>
</dict>
</plist>
EOF
echo "  ✅ $PLIST_DIR/com.athrag.qdrant.plist"

# 安装 ATHRag Server plist
echo "📦 安装 ATHRag 服务..."
cat > "$PLIST_DIR/com.athrag.server.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.athrag.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_UVICORN</string>
        <string>src.rag_api.main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>16250</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$PROJECT_DIR/.venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>5</integer>
    <key>StandardOutPath</key>
    <string>/tmp/athrag.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/athrag.log</string>
</dict>
</plist>
EOF
echo "  ✅ $PLIST_DIR/com.athrag.server.plist"

# 加载服务
echo ""
echo "🔄 加载服务..."
launchctl load "$PLIST_DIR/com.athrag.qdrant.plist" 2>/dev/null || echo "  Qdrant 已加载"
launchctl load "$PLIST_DIR/com.athrag.server.plist" 2>/dev/null || echo "  ATHRag 已加载"

# 等待启动
echo ""
echo "⏳ 等待服务启动..."
sleep 5

# 验证
echo ""
echo "=== 验证 ==="
if curl -s http://localhost:6333/healthz > /dev/null 2>&1; then
    echo "  ✅ Qdrant 运行中 (http://localhost:6333)"
else
    echo "  ❌ Qdrant 未启动，查看日志: cat /tmp/qdrant.log"
fi

if curl -s http://localhost:16250/docs > /dev/null 2>&1; then
    echo "  ✅ ATHRag 运行中 (http://localhost:16250)"
else
    echo "  ❌ ATHRag 未启动，查看日志: cat /tmp/athrag.log"
fi

echo ""
echo "================================"
echo "✅ 服务已安装为开机自启"
echo ""
echo "管理命令:"
echo "  停止:   launchctl unload ~/Library/LaunchAgents/com.athrag.server.plist"
echo "  启动:   launchctl load ~/Library/LaunchAgents/com.athrag.server.plist"
echo "  日志:   tail -f /tmp/athrag.log"
echo "  Qdrant: tail -f /tmp/qdrant.log"
