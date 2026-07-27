"""ATHRag CLI - ath

本地 ATHRag系统的命令行管理工具
"""

import typer
from rich.console import Console

from src.cli.commands import service, project, document, search, watcher, system, auth

app = typer.Typer(
    name="ath",
    help="ATHRag CLI 管理工具",
    rich_markup_mode="rich",
)

console = Console()

# 添加子命令
app.add_typer(service.app, name="service", help="服务管理")
app.add_typer(project.app, name="project", help="项目管理")
app.add_typer(document.app, name="doc", help="文档管理")
app.add_typer(search.app, name="search", help="搜索")
app.add_typer(watcher.app, name="watcher", help="文件监控")
app.add_typer(system.app, name="system", help="系统信息")
app.add_typer(auth.app, name="auth", help="认证管理")


@app.callback()
def callback():
    """ATHRag CLI 工具

    管理本地 RAG 系统的服务、项目、文档和搜索功能。
    """
    pass


@app.command()
def version():
    """显示版本信息"""
    console.print("[bold cyan]ath[/bold cyan] v0.1.0")
    console.print("ATHRag CLI Tool")


def main():
    app()


if __name__ == "__main__":
    main()
