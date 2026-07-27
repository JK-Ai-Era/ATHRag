"""系统信息命令"""

import typer
from rich.console import Console
from rich.table import Table

from src.cli.api_client import api_client
from src.cli.utils import format_size
from pathlib import Path

app = typer.Typer(name="system", help="系统信息")
console = Console()


@app.command()
def health():
    """健康检查"""
    result = api_client.get("/health/detailed")
    
    if not result:
        console.print("[red]✗ 健康检查失败 - 无法连接到服务[/red]")
        return
    
    console.print("\n[bold cyan]🏥 RAG 系统健康检查[/bold cyan]\n")
    
    if isinstance(result, dict):
        for service, status in result.items():
            if isinstance(status, dict):
                is_healthy = status.get("status") == "ok" or status.get("healthy", False)
                icon = "🟢" if is_healthy else "🔴"
                console.print(f"  {icon} [magenta]{service}[/magenta]: {status.get('message', status.get('version', 'ok'))}")
            else:
                console.print(f"  🟢 {service}: {status}")
    else:
        console.print(f"  🟢 系统正常")


@app.command()
def stats():
    """显示系统统计"""
    # 获取项目列表
    projects_result = api_client.get("/api/v1/projects")
    
    # 获取存储信息
    data_dir = Path.home() / "Projects/ATHRag/data"
    db_dir = Path.home() / "Projects/ATHRag/db"
    
    # 计算存储大小
    total_data_size = 0
    if data_dir.exists():
        for path in data_dir.rglob("*"):
            if path.is_file():
                try:
                    total_data_size += path.stat().st_size
                except (OSError, PermissionError):
                    pass
    
    total_db_size = 0
    if db_dir.exists():
        for path in db_dir.rglob("*"):
            if path.is_file():
                try:
                    total_db_size += path.stat().st_size
                except (OSError, PermissionError):
                    pass
    
    # 获取文档数
    total_docs = 0
    project_count = 0
    
    if projects_result and projects_result.get("success"):
        projects_data = projects_result.get("data", [])
        if isinstance(projects_data, list):
            project_count = len(projects_data)
            for p in projects_data:
                if isinstance(p, dict):
                    total_docs += p.get("document_count", 0)
    
    console.print("\n[bold cyan]📊 RAG 系统统计[/bold cyan]\n")
    
    table = Table(show_header=False)
    table.add_column("指标", style="cyan")
    table.add_column("值", style="magenta", justify="right")
    
    table.add_row("项目数", str(project_count))
    table.add_row("文档数", str(total_docs))
    table.add_row("数据存储", format_size(total_data_size))
    table.add_row("数据库大小", format_size(total_db_size))
    table.add_row("总存储使用", format_size(total_data_size + total_db_size))
    
    console.print(table)
    
    # Watcher 状态
    watcher_result = api_client.get("/api/v1/watcher/status")
    if watcher_result and watcher_result.get("success"):
        watcher_data = watcher_result.get("data", {})
        if isinstance(watcher_data, dict):
            is_running = watcher_data.get("running", False)
            watching_projects = len(watcher_data.get("projects", []))
            console.print(f"\n[dim]文件监控: {'🟢 运行中' if is_running else '🔴 已停止'} ({watching_projects} 个项目)[/dim]")


@app.command()
def info():
    """显示系统信息"""
    from src.cli.config import config
    
    console.print("\n[bold cyan]ℹ️  RAG 系统信息[/bold cyan]\n")
    console.print(f"  API 地址:     {config.api_url}")
    console.print(f"  API 超时:     {config.api_timeout}s")
    console.print(f"  配置文件:     {config.config_file}")
    console.print(f"  Token 文件:   {config.token_file}")
    
    # 检查各服务端口
    from src.cli.utils import check_service_port
    console.print("\n[bold]服务端口:[/bold]")
    services = [
        ("API", "localhost", 8000),
        ("Qdrant", "localhost", 6333),
        ("Web UI", "localhost", 3000),
        ("Ollama", "localhost", 11434),
    ]
    
    for name, host, port in services:
        is_running = check_service_port(host, port)
        icon = "🟢" if is_running else "🔴"
        console.print(f"  {icon} {name}: {host}:{port}")
