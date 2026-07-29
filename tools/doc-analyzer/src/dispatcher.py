"""解析器调度器 — 根据文件类型自动路由到对应解析器

核心职责：
1. 从 parsers.yaml 加载解析器注册配置
2. 根据文件扩展名查找对应的解析器
3. 检查解析器可用性
4. 调用解析器并校验输出
5. 返回标准化 ParseResult
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

from src.contract import ParseResult, error_result, validate_output
from src.parsers import get_all_parsers, list_parser_names
from src.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# 配置文件默认路径
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "parsers.yaml"


class ParserConfig:
    """单个解析器的配置"""

    def __init__(
        self,
        name: str,
        cli: str,
        extensions: List[str],
        description: str = "",
        timeout: int = 300,
        enabled: bool = True,
    ):
        self.name = name
        self.cli = cli
        self.extensions = [ext.lower() for ext in extensions]
        self.description = description
        self.timeout = timeout
        self.enabled = enabled
        self.available: Optional[bool] = None  # 延迟检测


class ParseDispatcher:
    """解析器调度器

    工作流程：
    1. 初始化时加载 parsers.yaml 配置
    2. build extension → parser 映射
    3. dispatch() 时根据扩展名查找解析器，调用并返回结果
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._parsers: Dict[str, BaseParser] = {}  # name → parser instance
        self._extension_map: Dict[str, str] = {}   # .ext → parser name
        self._configs: Dict[str, ParserConfig] = {} # name → config

        self._load_builtin_parsers()
        self._load_config(config_path or DEFAULT_CONFIG_PATH)

    def _load_builtin_parsers(self) -> None:
        """加载内置解析器"""
        for parser in get_all_parsers():
            self._parsers[parser.parser_name] = parser
            logger.debug(f"加载内置解析器: {parser.parser_name} → {parser.supported_extensions}")

    def _load_config(self, config_path: Path) -> None:
        """从 parsers.yaml 加载配置，构建 extension 映射"""
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)

                parsers_config = config.get("parsers", {})
                for name, cfg in parsers_config.items():
                    pc = ParserConfig(
                        name=name,
                        cli=cfg.get("cli", name),
                        extensions=cfg.get("extensions", []),
                        description=cfg.get("description", ""),
                        timeout=cfg.get("timeout", 300),
                        enabled=cfg.get("enabled", True),
                    )
                    self._configs[name] = pc

                    # 构建 extension → parser name 映射
                    if pc.enabled and name in self._parsers:
                        for ext in pc.extensions:
                            self._extension_map[ext] = name

                logger.info(f"加载配置: {config_path}，{len(self._configs)} 个解析器")
            except Exception as e:
                logger.warning(f"加载配置失败: {e}，使用默认映射")
                self._build_default_mapping()
        else:
            logger.info(f"配置文件不存在: {config_path}，使用默认映射")
            self._build_default_mapping()

    def _build_default_mapping(self) -> None:
        """构建默认的扩展名映射（无配置文件时）"""
        for parser in self._parsers.values():
            for ext in parser.supported_extensions:
                self._extension_map[ext] = parser.parser_name

    def detect_type(self, file_path: Path) -> str:
        """检测文件类型（返回解析器名称）"""
        ext = file_path.suffix.lower()
        return self._extension_map.get(ext, "text")  # 默认当文本处理

    def can_parse(self, file_path: Path) -> bool:
        """判断是否能解析该文件"""
        ext = file_path.suffix.lower()
        return ext in self._extension_map

    def get_parser_for(self, file_path: Path) -> Optional[BaseParser]:
        """获取适合处理该文件的解析器"""
        ext = file_path.suffix.lower()
        parser_name = self._extension_map.get(ext)
        if parser_name and parser_name in self._parsers:
            return self._parsers[parser_name]
        return None

    def dispatch(self, file_path: Path) -> ParseResult:
        """分派解析任务

        Args:
            file_path: 文件路径

        Returns:
            ParseResult: 标准化解析结果
        """
        file_path = Path(file_path).resolve()

        # 检查文件存在
        if not file_path.exists():
            return error_result(str(file_path), "文件不存在")

        if not file_path.is_file():
            return error_result(str(file_path), "不是文件")

        # 查找解析器
        ext = file_path.suffix.lower()
        parser_name = self._extension_map.get(ext)

        if not parser_name:
            # 未知格式，尝试当文本处理
            logger.warning(f"未知文件格式 {ext}，尝试作为文本处理")
            parser_name = "text"

        parser = self._parsers.get(parser_name)
        if not parser:
            return error_result(str(file_path), f"解析器 '{parser_name}' 未加载")

        # 调用解析器
        logger.info(f"解析: {file_path.name} → {parser_name}")
        try:
            result = parser.parse(file_path)
        except Exception as e:
            logger.error(f"解析器 '{parser_name}' 异常: {e}")
            return error_result(str(file_path), f"解析器异常: {e}", ext.lstrip("."))

        # 校验输出
        try:
            validate_output(result.to_dict())
        except Exception as e:
            logger.error(f"解析器 '{parser_name}' 输出不符合契约: {e}")
            return error_result(str(file_path), f"输出不符合契约: {e}", ext.lstrip("."))

        return result

    def list_parsers(self) -> List[Dict[str, object]]:
        """列出所有已注册的解析器及其状态"""
        result = []
        for name, parser in self._parsers.items():
            config = self._configs.get(name)
            result.append({
                "name": name,
                "extensions": parser.supported_extensions,
                "description": config.description if config else "",
                "enabled": config.enabled if config else True,
                "cli": config.cli if config else name,
            })
        return result

    def list_supported_extensions(self) -> Set[str]:
        """列出所有支持的文件扩展名"""
        return set(self._extension_map.keys())
