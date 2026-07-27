"""文件系统监控和自动同步模块

自动同步 ~/Projects/ 目录下的项目到 ATHRag。
"""

from src.watcher.gitignore import GitIgnoreParser, gitignore_cache
from src.watcher.handler import FileChangeHandler, ProjectDirectoryHandler, FileEvent, EventDebouncer
from src.watcher.manager import WatcherManager, get_watcher_manager
from src.watcher.sync import FileSync, ProjectMapping, SyncStats

__all__ = [
    # gitignore
    "GitIgnoreParser",
    "gitignore_cache",
    # handler
    "FileChangeHandler",
    "ProjectDirectoryHandler",
    "FileEvent",
    "EventDebouncer",
    # manager
    "WatcherManager",
    "get_watcher_manager",
    # sync
    "FileSync",
    "ProjectMapping",
    "SyncStats",
]
