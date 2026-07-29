"""解析器基类"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

from src.contract import ParseResult

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """解析器基类

    所有格式解析器必须继承此类并实现：
    - supported_extensions: 支持的文件扩展名列表
    - parser_name: 解析器名称
    - parse(): 解析逻辑
    """

    # 子类必须定义
    parser_name: str = "base"
    supported_extensions: List[str] = []

    @abstractmethod
    def parse(self, file_path: Path) -> ParseResult:
        """解析文件，返回标准化结果

        Args:
            file_path: 文件绝对路径

        Returns:
            ParseResult: 符合契约的解析结果
        """
        ...

    def can_handle(self, file_path: Path) -> bool:
        """判断是否能处理该文件"""
        return file_path.suffix.lower() in self.supported_extensions

    def _detect_encoding(self, file_path: Path) -> str:
        """检测文件编码"""
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1"]
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    f.read(4096)  # 读一部分测试
                return encoding
            except (UnicodeDecodeError, UnicodeError):
                continue
        return "latin-1"  # 兜底

    def _read_text_file(self, file_path: Path) -> str:
        """读取文本文件（自动检测编码）"""
        encoding = self._detect_encoding(file_path)
        with open(file_path, "r", encoding=encoding) as f:
            return f.read()
