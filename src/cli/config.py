"""配置管理"""

import os
from pathlib import Path
from typing import Optional

import yaml


DEFAULT_CONFIG = {
    "api": {
        "url": "http://localhost:16250",
        "timeout": 30,
    },
    "services": {
        "qdrant": {"host": "localhost", "port": 6333},
        "ollama": {"host": "localhost", "port": 11434},
        "web": {"host": "localhost", "port": 3000},
    },
    "auth": {
        "enabled": True,
        "token_file": "~/.config/ath/token",
    },
    "logging": {
        "level": "INFO",
    },
}


class Config:
    """配置管理类"""

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "ath"
        self.config_file = self.config_dir / "config.yaml"
        self._config = None

    def _ensure_config_dir(self):
        """确保配置目录存在"""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        """加载配置"""
        if self._config is not None:
            return self._config

        self._ensure_config_dir()

        if self.config_file.exists():
            with open(self.config_file, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            # 合并默认配置和用户配置
            self._config = self._merge_config(DEFAULT_CONFIG, user_config)
        else:
            self._config = DEFAULT_CONFIG.copy()
            self.save(self._config)

        return self._config

    def save(self, config: dict):
        """保存配置"""
        self._ensure_config_dir()
        with open(self.config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    def get(self, key: str, default=None):
        """获取配置项"""
        config = self.load()
        keys = key.split(".")
        value = config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value):
        """设置配置项"""
        config = self.load()
        keys = key.split(".")
        target = config
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
        self.save(config)
        self._config = config

    def _merge_config(self, default: dict, user: dict) -> dict:
        """递归合并配置"""
        result = default.copy()
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result

    @property
    def api_url(self) -> str:
        """获取 API URL"""
        return self.get("api.url", "http://localhost:16250")

    @property
    def api_timeout(self) -> int:
        """获取 API 超时时间"""
        return self.get("api.timeout", 30)

    @property
    def token_file(self) -> Path:
        """获取 Token 文件路径"""
        path = self.get("auth.token_file", "~/.config/ath/token")
        return Path(path).expanduser()


# 全局配置实例
config = Config()
