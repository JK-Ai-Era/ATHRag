"""纯文本 / Markdown 解析器"""

from __future__ import annotations

import logging
from pathlib import Path

from src.contract import ParseResult, error_result
from src.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class TextParser(BaseParser):
    """纯文本解析器"""

    parser_name = "text"
    supported_extensions = [".txt", ".rst", ".log", ".csv", ".tsv"]

    def parse(self, file_path: Path) -> ParseResult:
        file_path = Path(file_path).resolve()

        try:
            content = self._read_text_file(file_path)
        except Exception as e:
            return error_result(str(file_path), f"文本读取失败: {e}", "txt")

        if not content.strip():
            return error_result(str(file_path), "文件内容为空", "txt")

        metadata = {
            "filename": file_path.name,
            "file_size": file_path.stat().st_size,
            "parser_backend": "builtin",
            "encoding": self._detect_encoding(file_path),
            "line_count": content.count("\n") + 1,
            "char_count": len(content),
        }

        return ParseResult(
            source=str(file_path),
            type="document",
            format=file_path.suffix.lstrip("."),
            content=content,
            metadata=metadata,
            parser="text",
        )


class MarkdownParser(BaseParser):
    """Markdown 解析器"""

    parser_name = "markdown"
    supported_extensions = [".md", ".markdown"]

    def parse(self, file_path: Path) -> ParseResult:
        file_path = Path(file_path).resolve()

        try:
            content = self._read_text_file(file_path)
        except Exception as e:
            return error_result(str(file_path), f"Markdown 读取失败: {e}", "md")

        if not content.strip():
            return error_result(str(file_path), "Markdown 文件内容为空", "md")

        # 提取标题作为结构信息
        import re
        headings = re.findall(r"^(#{1,6})\s+(.+)$", content, re.MULTILINE)
        heading_list = [
            {"level": len(h[0]), "text": h[1].strip()} for h in headings
        ]

        metadata = {
            "filename": file_path.name,
            "file_size": file_path.stat().st_size,
            "parser_backend": "builtin",
            "encoding": self._detect_encoding(file_path),
            "line_count": content.count("\n") + 1,
            "char_count": len(content),
            "headings": heading_list,
            "heading_count": len(heading_list),
        }

        return ParseResult(
            source=str(file_path),
            type="document",
            format="md",
            content=content,
            metadata=metadata,
            parser="markdown",
        )
