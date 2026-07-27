"""认证命令"""

import os

import typer
from rich.console import Console
from rich.prompt import Prompt

from src.cli.api_client import api_client
from src.cli.config import config

app = typer.Typer(name="auth", help="认证管理")
console = Console()


@app.command()
def login(
    username: str = typer.Option(None, "--username", "-u", help="用户名"),
    password: str = typer.Option(None, "--password", "-p", help="密码"),
):
    """登录 RAG 系统"""
    # 优先使用参数，其次环境变量
    username = username or os.environ.get("RAG_API_USERNAME")
    password = password or os.environ.get("RAG_API_PASSWORD")
    
    # 交互式输入
    if not username:
        username = Prompt.ask("用户名", default="admin")
    if not password:
        password = Prompt.ask("密码", password=True)
    
    if api_client.login(username, password):
        console.print(f"[green]✓ 已登录为 {username}[/green]")
        console.print(f"[dim]Token 已保存到: {config.token_file}[/dim]")
    else:
        console.print("[red]✗ 登录失败[/red]")
        raise typer.Exit(1)


@app.command()
def logout():
    """登出（删除本地 Token）"""
    token_file = config.token_file
    if token_file.exists():
        token_file.unlink()
        console.print("[green]✓ 已登出[/green]")
    else:
        console.print("[yellow]未找到本地 Token[/yellow]")


@app.command()
def status():
    """查看认证状态"""
    if api_client.token:
        # 尝试获取用户信息
        result = api_client.get("/api/v1/auth/me")
        if result and result.get("success"):
            data = result.get("data", {})
            console.print(f"[green]✓ 已认证[/green]")
            console.print(f"  用户名: {data.get('username', 'unknown')}")
            console.print(f"  认证启用: {data.get('auth_enabled', True)}")
        else:
            console.print("[yellow]Token 存在但可能已过期[/yellow]")
            console.print("[dim]执行 'ath auth login' 重新登录[/dim]")
    else:
        console.print("[red]✗ 未认证[/red]")
        console.print("[dim]执行 'ath auth login' 登录[/dim]")


@app.command()
def setup():
    """配置环境变量（添加到 shell 配置文件）"""
    import getpass
    
    console.print("[bold cyan]配置 RAG API 自动登录[/bold cyan]\n")
    
    username = Prompt.ask("用户名", default="admin")
    password = getpass.getpass("密码: ")
    
    # 检测 shell 配置文件
    import os
    shell = os.environ.get("SHELL", "")
    
    if "zsh" in shell:
        config_file = os.path.expanduser("~/.zshrc")
    elif "bash" in shell:
        config_file = os.path.expanduser("~/.bashrc")
    else:
        config_file = os.path.expanduser("~/.profile")
    
    # 添加环境变量
    env_vars = f'''
# RAG API 自动登录
export RAG_API_USERNAME="{username}"
export RAG_API_PASSWORD="{password}"
'''
    
    console.print(f"\n[bold]将添加以下配置到 {config_file}:[/bold]")
    console.print(env_vars)
    
    from rich.prompt import Confirm
    if Confirm.ask("确认添加?"):
        with open(config_file, "a") as f:
            f.write(env_vars)
        console.print(f"\n[green]✓ 配置已添加[/green]")
        console.print(f"[dim]执行 'source {config_file}' 使配置生效[/dim]")
    else:
        console.print("[yellow]已取消[/yellow]")