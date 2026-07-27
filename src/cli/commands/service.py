"""服务管理命令"""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from src.cli.utils import check_service_port, run_launchctl, get_service_pid, tail_log_file
from src.cli.api_client import api_client

app = typer.Typer(name="service", help="服务管理")
console = Console()


SERVICES = [
    {"name": "API", "host": "localhost", "port": 8000, "launchctl": "api"},
    {"name": "Qdrant", "host": "localhost", "port": 6333, "launchctl": "qdrant"},
    {"name": "Web UI", "host": "localhost", "port": 3000, "launchctl": "web"},
    {"name": "Ollama", "host": "localhost", "port": 11434, "launchctl": None},
]


@app.command()
def status():
    """查看所有服务状态"""
    table = Table(title="📊 RAG 服务状态")
    table.add_column("服务", style="cyan", justify="center")
    table.add_column("状态", style="green", justify="center")
    table.add_column("地址", style="magenta")
    table.add_column("PID", justify="right")

    for svc in SERVICES:
        is_running = check_service_port(svc["host"], svc["port"])
        status_icon = "🟢 运行中" if is_running else "🔴 已停止"
        
        pid = None
        if svc["launchctl"] and is_running:
            pid = get_service_pid(svc["launchctl"])
        
        address = f"{svc['host']}:{svc['port']}"
        pid_str = str(pid) if pid else "-"
        
        table.add_row(svc["name"], status_icon, address, pid_str)

    # 添加 Watcher 状态
    watcher_status = _get_watcher_status()
    watcher_icon = "🟢 运行中" if watcher_status["running"] else "🔴 已停止"
    watcher_detail = f"{watcher_status['projects']} 个项目" if watcher_status["running"] else "-"
    table.add_row("Watcher", watcher_icon, watcher_detail, "-")

    console.print(table)


def _get_watcher_status() -> dict:
    """获取 Watcher 状态"""
    try:
        result = api_client.get("/api/v1/watcher/status")
        if result and result.get("success"):
            data = result.get("data", {})
            if isinstance(data, dict):
                # 兼容 is_running 和 running 两种字段名
                running = data.get("is_running", data.get("running", False))
                projects = data.get("watched_projects", data.get("projects", []))
                return {
                    "running": running,
                    "projects": len(projects) if isinstance(projects, list) else 0
                }
    except Exception:
        pass
    return {"running": False, "projects": 0}


@app.command()
def start():
    """启动所有服务"""
    console.print("[bold green]🚀 启动 RAG 服务...[/bold green]\n")
    
    for svc in SERVICES:
        if svc["launchctl"] is None:
            console.print(f"[dim]跳过 {svc['name']} (非受控服务)[/dim]")
            continue
            
        if check_service_port(svc["host"], svc["port"]):
            console.print(f"[dim]✓ {svc['name']} 已在运行[/dim]")
            continue
        
        console.print(f"启动 {svc['name']}...", end=" ")
        if run_launchctl("start", svc["launchctl"]):
            console.print("[green]✓[/green]")
        else:
            console.print("[red]✗[/red]")

    console.print("\n[bold]访问地址:[/bold]")
    console.print("  API 文档: http://localhost:8000/docs")
    console.print("  Web UI:   http://localhost:3000")


@app.command()
def stop():
    """停止所有服务"""
    console.print("[bold yellow]🛑 停止 RAG 服务...[/bold yellow]\n")
    
    for svc in SERVICES:
        if svc["launchctl"] is None:
            continue
            
        if not check_service_port(svc["host"], svc["port"]):
            console.print(f"[dim]跳过 {svc['name']} (未运行)[/dim]")
            continue
        
        console.print(f"停止 {svc['name']}...", end=" ")
        if run_launchctl("stop", svc["launchctl"]):
            console.print("[green]✓[/green]")
        else:
            console.print("[red]✗[/red]")


@app.command()
def restart():
    """重启所有服务"""
    console.print("[bold yellow]🔄 重启 RAG 服务...[/bold yellow]\n")
    stop()
    console.print()
    start()


@app.command()
def logs(
    service: Optional[str] = typer.Argument(None, help="服务名称 (api/qdrant/web)"),
    lines: int = typer.Option(50, "--lines", "-n", help="显示行数"),
):
    """查看服务日志"""
    from pathlib import Path
    
    log_map = {
        "api": Path.home() / "Projects/ATHRag/logs/api_latest.log",
        "qdrant": Path.home() / ".qdrant/logs/stderr.log",
        "web": Path.home() / "Projects/ATHRag/logs/web_stderr.log",
    }
    
    if service:
        if service.lower() not in log_map:
            console.print(f"[red]未知服务: {service}[/red]")
            console.print(f"可用服务: {', '.join(log_map.keys())}")
            raise typer.Exit(1)
        
        log_file = log_map[service.lower()]
        lines_output = tail_log_file(log_file, lines)
        
        if lines_output:
            console.print(f"[bold]📜 {service.upper()} 日志 ({log_file}):[/bold]\n")
            for line in lines_output:
                console.print(line)
        else:
            console.print(f"[yellow]日志文件为空或不存在: {log_file}[/yellow]")
    else:
        # 显示所有日志
        for name, log_file in log_map.items():
            lines_output = tail_log_file(log_file, lines)
            console.print(f"\n[bold]📜 {name.upper()} 日志:[/bold]")
            if lines_output:
                for line in lines_output[-10:]:  # 每个服务只显示最后10行
                    console.print(line)
            else:
                console.print("[dim]无日志[/dim]")
