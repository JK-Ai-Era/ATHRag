#!/bin/bash
# ATHRag服务管理脚本

COMMAND=$1

 case "$COMMAND" in
    start)
        echo "🚀 启动 ATHRag服务..."
        launchctl start com.ATHRag.qdrant
        launchctl start com.ATHRag.api
        launchctl start com.ATHRag.web
        echo "✓ 服务已启动"
        echo ""
        echo "访问地址:"
        echo "  Web UI:   http://localhost:3000"
        echo "  API 文档: http://localhost:8000/docs"
        ;;
    stop)
        echo "🛑 停止 ATHRag服务..."
        launchctl stop com.ATHRag.qdrant
        launchctl stop com.ATHRag.api
        launchctl stop com.ATHRag.web
        echo "✓ 服务已停止"
        ;;
    restart)
        echo "🔄 重启 ATHRag服务..."
        launchctl stop com.ATHRag.qdrant 2>/dev/null
        launchctl stop com.ATHRag.api 2>/dev/null
        launchctl stop com.ATHRag.web 2>/dev/null
        sleep 2
        launchctl start com.ATHRag.qdrant
        launchctl start com.ATHRag.api
        launchctl start com.ATHRag.web
        echo "✓ 服务已重启"
        echo ""
        echo "访问地址:"
        echo "  Web UI:   http://localhost:3000"
        echo "  API 文档: http://localhost:8000/docs"
        ;;
    status)
        echo "📊 服务状态:"
        echo ""
        echo "LaunchAgent 状态:"
        launchctl list | grep ATHRag | while read pid status name; do
            if [ "$status" = "0" ]; then
                echo "  ✓ $name - 运行中 (PID: $pid)"
            else
                echo "  ✗ $name - 未运行 (状态: $status)"
            fi
        done
        echo ""
        echo "端口检查:"
        curl -s http://localhost:6333/healthz >/dev/null 2>&1 && echo "  ✓ Qdrant   (localhost:6333)" || echo "  ✗ Qdrant   (localhost:6333)"
        curl -s http://localhost:8000/health >/dev/null 2>&1 && echo "  ✓ RAG API  (localhost:8000)" || echo "  ✗ RAG API  (localhost:8000)"
        curl -s http://localhost:11434/api/tags >/dev/null 2>&1 && echo "  ✓ Ollama   (localhost:11434)" || echo "  ✗ Ollama   (localhost:11434)"
        curl -s http://localhost:3000 >/dev/null 2>&1 && echo "  ✓ Web UI   (localhost:3000)" || echo "  ✗ Web UI   (localhost:3000)"
        ;;
    logs)
        echo "📜 日志路径:"
        echo "  Qdrant:   ~/.qdrant/logs/"
        echo "  API:      ~/Projects/ATHRag/logs/api_*.log"
        echo "  Web:      ~/Projects/ATHRag/logs/web_*.log"
        ;;
    *)
        echo "ATHRag服务管理"
        echo ""
        echo "用法: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "命令:"
        echo "  start    启动所有服务"
        echo "  stop     停止所有服务"
        echo "  restart  重启所有服务"
        echo "  status   查看状态"
        echo "  logs     查看日志路径"
        echo ""
        echo "访问地址:"
        echo "  Web UI:   http://localhost:3000"
        echo "  API 文档: http://localhost:8000/docs"
        ;;
esac
