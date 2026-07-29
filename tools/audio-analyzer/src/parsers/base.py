"""音频解析器基类"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..contract import ParseResult


class AudioParser(ABC):
    """音频解析器基类"""

    name: str = "base"
    supported_formats: list[str] = []

    @abstractmethod
    def parse(self, file_path: Path, **options) -> ParseResult:
        """解析音频文件，返回标准化结果"""
        ...

    def can_parse(self, file_path: Path) -> bool:
        """检查是否能解析该文件"""
        return file_path.suffix.lower().lstrip(".") in self.supported_formats

    def _get_format(self, file_path: Path) -> str:
        """获取文件格式"""
        return file_path.suffix.lower().lstrip(".")
