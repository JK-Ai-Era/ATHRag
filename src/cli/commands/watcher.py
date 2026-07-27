"""文件监控命令"""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from src.cli.api_client import api_client

app = typer.Typer(name="watcher", help="文件监控")
console = Console()


@app.command()
def status():
    """查看监控状态"""
    result = api_client.get("/api/v1/watcher/status")
    
    if not result or not result.get("success"):
        console.print("[red]获取监控状态失败[/red]")
        return
    
    data = result.get("data", {})
    
    if isinstance(data, dict):
        # 兼容 is_running 和 running 两种字段名
        is_running = data.get("is_running", data.get("running", False))
        projects = data.get("watched_projects", data.get("projects", []))
        
        console.print(f"\n[bold cyan]文件监控状态[/bold cyan]")
        console.print(f"  监控状态: {'🟢 运行中' if is_running else '🔴 已停止'}")
        console.print(f"  监控项目: {len(projects) if isinstance(projects, list) else 0} 个\n")
        
        if projects and isinstance(projects, list):
            table = Table(title="监控项目列表")
            table.add_column("项目名称", style="magenta")
            
            for p in projects:
                if isinstance(p, dict):
                    table.add_row(p.get("name", "-"))
                else:
                    table.add_row(str(p))
            
            console.print(table)
        else:
            console.print("[dim]暂无监控项目[/dim]")
    else:
        console.print(f"[yellow]数据格式异常: {data}[/yellow]")


@app.command()
def start():
    """启动文件监控"""
    result = api_client.post("/api/v1/watcher/start")
    
    if result and result.get("success"):
        console.print("[green]✓ 文件监控已启动[/green]")
    else:
        console.print(f"[red]✗ 启动失败: {result.get('message', '未知错误') if result else '无响应'}[/red]")


@app.command()
def stop():
    """停止文件监控"""
    result = api_client.post("/api/v1/watcher/stop")
    
    if result and result.get("success"):
        console.print("[green]✓ 文件监控已停止[/green]")
    else:
        console.print(f"[red]✗ 停止失败: {result.get('message', '未知错误') if result else '无响应'}[/red]")


@app.command()
def stats():
    """查看同步统计"""
    result = api_client.get("/api/v1/watcher/stats")
    
    if not result or not result.get("success"):
        console.print("[red]获取统计信息失败[/red]")
        return
    
    data = result.get("data", {})
    
    if isinstance(data, dict):
        console.print(f"\n[bold cyan]文件同步统计[/bold cyan]\n")
        
        for project_name, stats in data.items():
            if isinstance(stats, dict):
                created = stats.get("created", 0)
                updated = stats.get("updated", 0)
                deleted = stats.get("deleted", 0)
                total = created + updated + deleted
                
                console.print(f"  [magenta]{project_name}[/magenta]")
                console.print(f"    创建: {created} | 更新: {updated} | 删除: {deleted}")
                console.print(f"    总计: {total}\n")
            else:
                console.print(f"  [magenta]{project_name}[/magenta]: {stats}\n")
    else:
        console.print(f"[yellow]{data}[/yellow]")


@app.command()
def scan(
    project_name: Optional[str] = typer.Argument(None, help="项目名称 (不指定则扫描所有)"),
):
    """强制扫描项目"""
    url = "/api/v1/watcher/scan"
    if project_name:
        url += f"?project_name={project_name}"
    
    result = api_client.post(url)
    
    if result and result.get("success"):
        msg = f"已触发扫描: {project_name}" if project_name else "已触发全量扫描"
        console.print(f"[green]✓ {msg}[/green]")
    else:
        console.print(f"[red]✗ 扫描失败[/red]")


@app.command()
def reset_stats(
    project_name: Optional[str] = typer.Argument(None, help="项目名称 (不指定则重置所有)"),
):
    """重置统计信息"""
    url = "/api/v1/watcher/reset-stats"
    if project_name:
        url += f"?project_name={project_name}"
    
    result = api_client.post(url)
    
    if result and result.get("success"):
        msg = f"已重置统计: {project_name}" if project_name else "已重置所有统计"
        console.print(f"[green]✓ {msg}[/green]")
    else:
        console.print(f"[red]✗ 重置失败[/red]")


@app.command()
def refresh(
    project_name: str = typer.Argument(..., help="项目名称"),
    enable: bool = typer.Option(True, "--enable/--disable", help="启用或禁用监控"),
):
    """
    刷新项目监控状态（即时生效，无需重启 watcher）
    
    用法：
      ath watcher refresh yunxi --enable    # 启用监控
      ath watcher refresh yunxi --disable   # 禁用监控
    """
    result = api_client.post(
        "/api/v1/watcher/refresh",
        json_data={"project_name": project_name, "watcher_enabled": enable}
    )
    
    if result and result.get("success"):
        action = "启用" if enable else "禁用"
        console.print(f"[green]✓ {action}监控: {project_name}[/green]")
        console.print(f"[dim]{result.get('message', '')}[/dim]")
    else:
        console.print(f"[red]✗ 刷新失败: {result.get('message', '未知错误') if result else '无响应'}[/red]")


@app.command("sync-all")
def sync_all():
    """
    同步所有 watcher_enabled 项目
    
    扫描数据库中所有 watcher_enabled=1 的项目，确保 watcher 监控状态一致。
    适用于手动修改数据库后批量同步。
    """
    result = api_client.post("/api/v1/watcher/sync-all")
    
    if result and result.get("success"):
        data = result.get("data", {})
        synced_count = data.get("synced_count", 0)
        console.print(f"[green]✓ 已同步 {synced_count} 个项目的监控状态[/green]")
        console.print(f"[dim]{result.get('message', '')}[/dim]")
    else:
        console.print(f"[red]✗ 同步失败: {result.get('message', '未知错误') if result else '无响应'}[/red]")
