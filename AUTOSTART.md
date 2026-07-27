# ATHRag - 自动启动配置

系统重启后，以下服务将**自动启动**：

## 服务清单

| 服务 | 端口 | 启动方式 | 状态 |
|------|------|---------|------|
| Ollama | 11434 | Ollama.app 自带 LaunchAgent | ✅ |
| Qdrant | 6333 | ~/Library/LaunchAgents/com.ATHRag.qdrant.plist | ✅ |
| RAG API | 8000 | ~/Library/LaunchAgents/com.ATHRag.api.plist | ✅ |
| Web UI | 3000 | ~/Library/LaunchAgents/com.ATHRag.web.plist | ✅ |

## 访问地址

- **Web UI**: http://localhost:3000
- **API 文档**: http://localhost:8000/docs
- **Qdrant**: http://localhost:6333

## 管理命令

```bash
cd ~/Projects/ATHRag

# 查看所有服务状态
./scripts/service.sh status

# 启动所有服务
./scripts/service.sh start

# 停止所有服务
./scripts/service.sh stop

# 重启所有服务
./scripts/service.sh restart

# 查看日志路径
./scripts/service.sh logs
```

## 手动管理 LaunchAgent

```bash
# 加载配置
launchctl load ~/Library/LaunchAgents/com.ATHRag.qdrant.plist
launchctl load ~/Library/LaunchAgents/com.ATHRag.api.plist
launchctl load ~/Library/LaunchAgents/com.ATHRag.web.plist

# 卸载配置
launchctl unload ~/Library/LaunchAgents/com.ATHRag.qdrant.plist
launchctl unload ~/Library/LaunchAgents/com.ATHRag.api.plist
launchctl unload ~/Library/LaunchAgents/com.ATHRag.web.plist

# 启动/停止单个服务
launchctl start com.ATHRag.web
launchctl stop com.ATHRag.web
```

## 日志位置

- **Qdrant**: `~/.qdrant/logs/`
- **RAG API**: `~/Projects/ATHRag/logs/api_*.log`
- **Web UI**: `~/Projects/ATHRag/logs/web_*.log`

## 故障排查

如果服务未能自动启动：

1. 检查 LaunchAgent 是否加载：
   ```bash
   launchctl list | grep ATHRag
   ```

2. 查看错误日志：
   ```bash
   # Qdrant
   tail ~/.qdrant/logs/stderr.log
   
   # API
   tail ~/Projects/ATHRag/logs/api_stderr.log
   
   # Web UI
   tail ~/Projects/ATHRag/logs/web_stderr.log
   ```

3. 手动重启：
   ```bash
   ./scripts/service.sh restart
   ```

## 配置说明

### Web UI LaunchAgent

- 使用生产模式运行 (`npm run start`)
- 端口: 3000
- 依赖后端服务 (API + Qdrant)

### Qdrant LaunchAgent

- 使用 shell 脚本启动以正确设置工作目录
- 文件描述符限制设置为 65536（避免 "Too many open files" 错误）
- 自动重启（KeepAlive）

### RAG API LaunchAgent

- 使用虚拟环境 Python 解释器
- 设置 PYTHONPATH 确保模块导入正常
- 自动重启（KeepAlive）

---

配置完成时间: 2026-02-26
