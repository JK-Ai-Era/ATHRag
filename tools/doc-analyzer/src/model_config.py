"""模型配置加载器 — doc-analyzer 独立使用"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

_config_cache: Optional[dict] = None


def _resolve_dict(d: dict) -> dict:
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
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def load_models_config(config_path: Optional[Path] = None) -> dict:
    global _config_cache
    if _config_cache is not None and config_path is None:
        return _config_cache

    if config_path is None:
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
            return {}

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    config = _resolve_dict(config)
    if config_path is None:
        _config_cache = config
    return config


def get_model_config(category: str, subcategory: Optional[str] = None) -> Dict[str, Any]:
    config = load_models_config()
    section = config.get(category, {})
    if subcategory:
        section = section.get(subcategory, {})
    return section


def get_provider(category: str, subcategory: Optional[str] = None) -> str:
    cfg = get_model_config(category, subcategory)
    return cfg.get("provider", "")
