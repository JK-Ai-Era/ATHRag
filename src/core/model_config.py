"""模型配置加载器 — 读取 config/models.yaml

提供统一的 get_model_config() 接口，各解析器从这里读配置。
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


def _load_from_path(config_path: Path) -> dict:
    """从指定路径加载并解析配置"""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    return _resolve_dict(config)


def load_models_config(config_path: Optional[Path] = None) -> dict:
    """加载 models.yaml 配置

    Args:
        config_path: 指定配置文件路径。None 则自动查找并缓存。

    Returns:
        配置字典
    """
    global _config_cache

    # 传入自定义路径，不走缓存
    if config_path is not None:
        return _load_from_path(config_path)

    # 走缓存
    if _config_cache is not None:
        return _config_cache

    # 自动查找配置文件
    candidates = [
        Path(__file__).parent.parent.parent / "config" / "models.yaml",
        Path.cwd() / "config" / "models.yaml",
        Path.home() / ".athrag" / "models.yaml",
    ]
    for p in candidates:
        if p.exists():
            _config_cache = _load_from_path(p)
            return _config_cache

    logger.debug("models.yaml 未找到，使用空配置")
    return {}


def get_model_config(category: str, subcategory: Optional[str] = None) -> Dict[str, Any]:
    """获取指定类别的模型配置

    Args:
        category: 顶层类别，如 'embedding', 'audio', 'document'
        subcategory: 子类别，如 'speech', 'classify', 'pdf'

    Returns:
        配置字典
    """
    config = load_models_config()
    section = config.get(category, {})
    if subcategory:
        section = section.get(subcategory, {})
    return section


def get_provider(category: str, subcategory: Optional[str] = None) -> str:
    """获取 provider 名称"""
    cfg = get_model_config(category, subcategory)
    return cfg.get("provider", "")


def _get_settings():
    """延迟导入 settings，避免循环依赖"""
    from src.rag_api.config import get_settings
    return get_settings()


def get_embedding_config() -> dict:
    """获取 embedding 配置，models.yaml 优先，settings 兜底

    Returns:
        {"provider": str, "host": str, "model": str, "dimension": int, "timeout": int}
    """
    cfg = get_model_config("embedding")
    s = _get_settings()
    return {
        "provider": cfg.get("provider", "ollama"),
        "host": cfg.get("host", s.OLLAMA_HOST),
        "model": cfg.get("model", s.OLLAMA_MODEL),
        "dimension": cfg.get("dimension", s.OLLAMA_EMBED_DIM),
        "timeout": cfg.get("timeout", s.OLLAMA_TIMEOUT),
    }


def get_llm_config(purpose: str = "summary") -> dict:
    """获取 LLM 配置，models.yaml 优先，settings 兜底

    Args:
        purpose: "summary" 或 "compress"，区分不同用途的模型

    Returns:
        {"provider": str, "host": str, "model": str}
    """
    cfg = get_model_config("llm")
    s = _get_settings()

    # 优先从 llm.{purpose} 读取，再从 llm 顶层读取
    purpose_cfg = cfg.get(purpose, {}) if isinstance(cfg.get(purpose), dict) else {}

    # 根据 purpose 选择 settings 兜底值
    if purpose == "compress":
        fallback_model = s.OLLAMA_COMPRESS_MODEL
    else:
        fallback_model = s.OLLAMA_SUMMARY_MODEL

    return {
        "provider": purpose_cfg.get("provider", cfg.get("provider", "ollama")),
        "host": purpose_cfg.get("host", cfg.get("host", s.OLLAMA_HOST)),
        "model": purpose_cfg.get("model", cfg.get("model", fallback_model)),
    }


def get_reranker_config() -> dict:
    """获取 reranker 配置，models.yaml 优先，硬编码兜底

    Returns:
        {"provider": str, "model": str}
    """
    cfg = get_model_config("reranker")
    return {
        "provider": cfg.get("provider", "ollama"),
        "model": cfg.get("model", "bge-reranker-v2-m3"),
    }


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
