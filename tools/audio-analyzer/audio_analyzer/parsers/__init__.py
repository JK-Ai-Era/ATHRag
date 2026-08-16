"""音频解析器注册表"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .base import AudioParser
from .metadata import MetadataParser
from .features import FeaturesParser
from .speech import SpeechParser
from .classify import ClassifyParser


# ============================================================================
# 解析器注册表
# ============================================================================

PARSERS: Dict[str, AudioParser] = {
    "metadata": MetadataParser(),
    "features": FeaturesParser(),
    "speech": SpeechParser(),
    "classify": ClassifyParser(),
}


def get_parser(name: str) -> Optional[AudioParser]:
    """获取解析器"""
    return PARSERS.get(name)


def list_parsers() -> List[dict]:
    """列出所有解析器"""
    return [
        {
            "name": p.name,
            "formats": p.supported_formats,
        }
        for p in PARSERS.values()
    ]


def find_parser_for_file(file_path: Path) -> Optional[AudioParser]:
    """根据文件扩展名查找合适的解析器"""
    suffix = file_path.suffix.lower().lstrip(".")
    for parser in PARSERS.values():
        if suffix in parser.supported_formats:
            return parser
    return None
