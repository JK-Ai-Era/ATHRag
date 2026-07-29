"""解析器注册表"""

from __future__ import annotations

from typing import Dict, List, Type

from src.parsers.base import BaseParser

# 解析器注册表：parser_name → parser class
_REGISTRY: Dict[str, Type[BaseParser]] = {}


def register_parser(parser_class: Type[BaseParser]) -> Type[BaseParser]:
    """注册解析器（可作为装饰器使用）"""
    _REGISTRY[parser_class.parser_name] = parser_class
    return parser_class


def get_parser(name: str) -> BaseParser:
    """按名称获取解析器实例"""
    if name not in _REGISTRY:
        raise KeyError(f"未注册的解析器: {name}。可用: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]()


def get_all_parsers() -> List[BaseParser]:
    """获取所有已注册解析器的实例"""
    return [cls() for cls in _REGISTRY.values()]


def list_parser_names() -> List[str]:
    """列出所有已注册的解析器名称"""
    return list(_REGISTRY.keys())


# 导入各解析器模块以触发注册
from src.parsers.pdf import PDFParser          # noqa: F401, E402
from src.parsers.office import OfficeParser    # noqa: F401, E402
from src.parsers.image import ImageParser      # noqa: F401, E402
from src.parsers.text import TextParser, MarkdownParser  # noqa: F401, E402
from src.parsers.code import CodeParser        # noqa: F401, E402

# 注册内置解析器
register_parser(PDFParser)
register_parser(OfficeParser)
register_parser(ImageParser)
register_parser(TextParser)
register_parser(MarkdownParser)
register_parser(CodeParser)
