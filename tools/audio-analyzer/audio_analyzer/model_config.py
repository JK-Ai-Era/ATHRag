"""模型配置加载器 — 读取 config/models.yaml

audio-analyzer 独立使用，不依赖 ATHRag 主程序。
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

_config_cache: Optional[dict] = None


def _resolve_dict(d: dict) -> dict:
    """递归解析字典中的环境变量"""
    resolved = {}
    for k, v in d.items():
        if isinstance(v, dict):
            resolved[k] = _resolve_dict(v)
        elif isinstance(v, str):
            resolved[k] = _resolve_vars(v)
        else:
            resolved[k] = v
    return resolved


def _resolve_vars(value: str) -> str:
    """解析字符串中的 ${ENV_VAR} 占位符"""
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def load_models_config(config_path: Optional[Path] = None) -> dict:
    """加载 models.yaml 配置"""
    global _config_cache
    if _config_cache is not None and config_path is None:
        return _config_cache

    if config_path is None:
        # 尝试多个位置
        candidates = [
            Path(__file__).parent.parent.parent / "config" / "models.yaml",
            Path.cwd() / "config" / "models.yaml",
            Path.home() / ".athrag" / "models.yaml",
        ]
        for p in candidates:
            if p.exists():
                config_path = p
                break
        else:
            logger.debug("models.yaml 未找到，使用空配置")
            return {}

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    config = _resolve_dict(config)

    if config_path is None:
        _config_cache = config

    return config


def get_model_config(category: str, subcategory: Optional[str] = None) -> Dict[str, Any]:
    """获取指定类别的模型配置"""
    config = load_models_config()
    section = config.get(category, {})
    if subcategory:
        section = section.get(subcategory, {})
    return section


def get_provider(category: str, subcategory: Optional[str] = None) -> str:
    """获取 provider 名称"""
    cfg = get_model_config(category, subcategory)
    return cfg.get("provider", "")


def get_hardware_device() -> str:
    """检测硬件设备"""
    config = load_models_config()
    device = config.get("hardware", {}).get("device", "auto")

    if device != "auto":
        return device

    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass

    return "cpu"
