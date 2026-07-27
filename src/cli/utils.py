"""工具函数"""

import subprocess
from pathlib import Path
from typing import Optional, List

from rich.console import Console
from rich.table import Table

console = Console()


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def check_service_port(host: str, port: int) -> bool:
    """检查服务端口是否可用"""
    import socket
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def run_launchctl(command: str, service: str) -> bool:
    """运行 launchctl 命令"""
    service_name = f"com.ATHRag.{service}"
    try:
        result = subprocess.run(
            ["launchctl", command, service_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        console.print(f"[red]命令超时: launchctl {command} {service_name}[/red]")
        return False
    except FileNotFoundError:
        console.print(f"[red]launchctl 命令未找到[/red]")
        return False


def get_service_pid(service: str) -> Optional[int]:
    """获取服务 PID"""
    service_name = f"com.ATHRag.{service}"
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == service_name:
                try:
                    return int(parts[0])
                except ValueError:
                    return None
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def tail_log_file(file_path: Path, lines: int = 50) -> List[str]:
    """读取日志文件最后 N 行"""
    if not file_path.exists():
        return []

    try:
        result = subprocess.run(
            ["tail", "-n", str(lines), str(file_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.splitlines()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def truncate_text(text: str, max_length: int = 100) -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def create_table(title: str, columns: List[tuple]) -> Table:
    """创建表格

    Args:
        title: 表格标题
        columns: [(列名, 样式, 对齐), ...]
    """
    table = Table(title=title, show_header=True, header_style="bold magenta")
    for col_name, style, justify in columns:
        table.add_column(col_name, style=style, justify=justify or "left")
    return table


def confirm_action(message: str, force: bool = False) -> bool:
    """确认操作"""
    if force:
        return True

    from rich.prompt import Confirm
    return Confirm.ask(message)


def get_project_dir_size(project_id: str) -> int:
    """获取项目目录大小"""
    project_dir = Path.home() / "Projects" / "ATHRag" / "data" / "projects" / project_id
    if not project_dir.exists():
        return 0

    total_size = 0
    try:
        for path in project_dir.rglob("*"):
            if path.is_file():
                total_size += path.stat().st_size
    except (OSError, PermissionError):
        pass

    return total_size
