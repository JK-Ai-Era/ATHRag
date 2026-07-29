"""音频解析器调度器

根据文件扩展名和解析器类型，自动路由到合适的解析器。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .contract import ParseResult, error_result
from .parsers import PARSERS, get_parser, list_parsers, find_parser_for_file


class AudioDispatcher:
    """音频解析器调度器

    根据文件扩展名和指定的解析器类型，自动路由到合适的解析器。

    用法：
        dispatcher = AudioDispatcher()
        result = dispatcher.dispatch(Path("song.mp3"))
        result = dispatcher.dispatch(Path("speech.wav"), parser="speech")
    """

    def __init__(self):
        self.parsers = PARSERS

    def dispatch(self, file_path: Path, parser: Optional[str] = None, **options) -> ParseResult:
        """调度解析器

        Args:
            file_path: 音频文件路径
            parser: 指定解析器名称（可选）
            **options: 传递给解析器的额外参数

        Returns:
            ParseResult 标准化结果
        """
        # 检查文件是否存在
        if not file_path.exists():
            return error_result(str(file_path), "文件不存在")

        # 检查是否是文件
        if not file_path.is_file():
            return error_result(str(file_path), "不是文件")

        # 确定解析器
        if parser:
            # 使用指定的解析器
            if parser not in self.parsers:
                return error_result(
                    str(file_path),
                    f"未知解析器: {parser}，可用: {', '.join(self.parsers.keys())}"
                )
            target_parser = self.parsers[parser]
        else:
            # 自动查找解析器
            target_parser = find_parser_for_file(file_path)
            if not target_parser:
                return error_result(
                    str(file_path),
                    f"没有能处理 {file_path.suffix} 格式的解析器"
                )

        # 调用解析器
        return target_parser.parse(file_path, **options)

    def list_formats(self) -> dict:
        """列出支持的格式"""
        formats = {}
        for name, parser in self.parsers.items():
            formats[name] = {
                "formats": parser.supported_formats,
                "description": parser.__doc__.strip().split("\n")[0] if parser.__doc__ else "",
            }
        return formats

    def list_parsers(self) -> list:
        """列出所有解析器"""
        return list_parsers()
