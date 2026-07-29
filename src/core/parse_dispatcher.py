"""解析器调度器 — 读取 parsers.yaml，路由文件到对应 CLI 工具

职责：
1. 加载 parsers.yaml 配置
2. 根据文件扩展名找到对应的解析器 CLI
3. 调用 CLI 工具，获取标准化 JSON 输出
4. 校验输出格式
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.rag_api.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class ParseDispatcher:
    """解析器调度器 — 根据文件扩展名自动路由到对应 CLI"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or (
            Path(__file__).parent.parent.parent / "config" / "parsers.yaml"
        )
        self._parsers: Dict[str, dict] = {}
        self._ext_map: Dict[str, str] = {}  # extension -> parser name
        self._load_config()

    def _load_config(self):
        """加载 parsers.yaml 配置"""
        if not self.config_path.exists():
            logger.warning(f"parsers.yaml 不存在: {self.config_path}")
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        parsers = config.get("parsers", {})
        for name, parser_config in parsers.items():
            if not parser_config.get("enabled", True):
                logger.info(f"解析器 {name} 已禁用，跳过")
                continue

            self._parsers[name] = parser_config

            # 建立扩展名 → 解析器映射
            for ext in parser_config.get("extensions", []):
                ext = ext.lower().lstrip(".")
                self._ext_map[ext] = name

        logger.info(f"加载了 {len(self._parsers)} 个解析器，覆盖 {len(self._ext_map)} 种格式")

    def find_parser(self, file_path: Path) -> Optional[str]:
        """根据文件扩展名查找解析器名称"""
        ext = file_path.suffix.lower().lstrip(".")
        return self._ext_map.get(ext)

    def is_supported(self, file_path: Path) -> bool:
        """检查文件是否支持解析"""
        return self.find_parser(file_path) is not None

    def get_parser_config(self, parser_name: str) -> Optional[dict]:
        """获取解析器配置"""
        return self._parsers.get(parser_name)

    def list_parsers(self) -> Dict[str, dict]:
        """列出所有解析器"""
        return dict(self._parsers)

    def dispatch(self, file_path: Path, parser_name: Optional[str] = None) -> Dict[str, Any]:
        """调度解析器处理文件

        Args:
            file_path: 文件路径
            parser_name: 指定解析器名称（可选，默认自动检测）

        Returns:
            标准化 JSON 输出字典

        Raises:
            ValueError: 不支持的格式或 CLI 执行失败
        """
        file_path = Path(file_path).resolve()

        if not file_path.exists():
            raise ValueError(f"文件不存在: {file_path}")

        # 确定解析器
        if not parser_name:
            parser_name = self.find_parser(file_path)
            if not parser_name:
                raise ValueError(
                    f"没有能处理 {file_path.suffix} 格式的解析器"
                )

        parser_config = self._parsers.get(parser_name)
        if not parser_config:
            raise ValueError(f"未知解析器: {parser_name}")

        cli_name = parser_config["cli"]
        timeout = parser_config.get("timeout", 120)
        venv = parser_config.get("venv", "")

        # 查找 CLI 工具（优先从 venv 的 bin 目录找）
        cli_path = None
        if venv:
            # 解析 venv 路径（相对于项目根目录）
            project_root = Path(__file__).parent.parent.parent
            venv_bin = project_root / venv / "bin" / cli_name
            if venv_bin.exists():
                cli_path = str(venv_bin)
        if not cli_path:
            cli_path = shutil.which(cli_name)
        if not cli_path:
            raise ValueError(f"CLI 工具未找到: {cli_name}，请先安装")

        # 调用 CLI
        logger.info(f"调度 {cli_name} 解析: {file_path.name}")
        try:
            result = subprocess.run(
                [cli_path, str(file_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise ValueError(
                f"{cli_name} 处理超时（超过 {timeout}s）: {file_path.name}"
            )
        except Exception as e:
            raise ValueError(f"{cli_name} 执行失败: {e}")

        if result.returncode != 0:
            raise ValueError(
                f"{cli_name} 返回错误 (code={result.returncode}): "
                f"{result.stderr[:200]}"
            )

        # 解析 JSON 输出
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"{cli_name} 输出非法 JSON: {e}\n"
                f"stdout[:200]: {result.stdout[:200]}"
            )

        # 校验必填字段
        self._validate_output(output, file_path)

        logger.info(
            f"解析完成: {file_path.name} → "
            f"content={len(output.get('content', ''))} chars"
        )

        return output

    def _validate_output(self, output: dict, file_path: Path):
        """校验解析器输出是否符合契约"""
        required = {"source", "type", "format", "content", "metadata"}
        missing = required - set(output.keys())
        if missing:
            raise ValueError(f"解析器输出缺少必填字段: {missing}")

        if not isinstance(output["content"], str):
            raise ValueError(
                f"content 必须是字符串，实际是 {type(output['content']).__name__}"
            )

        if not isinstance(output["metadata"], dict):
            raise ValueError(
                f"metadata 必须是字典，实际是 {type(output['metadata']).__name__}"
            )

    def get_supported_extensions(self) -> List[str]:
        """获取所有支持的文件扩展名"""
        return sorted(self._ext_map.keys())
