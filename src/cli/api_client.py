"""API 客户端 - 支持自动刷新 Token 和超时控制"""

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urljoin

import requests
from requests.exceptions import Timeout, ConnectionError, RequestException
from rich.console import Console
from rich.prompt import Prompt

from src.cli.config import config

console = Console()

# 超时配置常量
API_SEARCH_TIMEOUT = 30  # 搜索 API 请求超时（秒）
OLLAMA_EMBED_TIMEOUT = 15  # Ollama 向量化超时（秒）
HEALTH_CHECK_TIMEOUT = 3  # 健康检查超时（秒）


def check_api_health(base_url: Optional[str] = None, timeout: int = HEALTH_CHECK_TIMEOUT) -> Dict[str, Any]:
    """检查 RAG API 服务健康状态"""
    url = base_url or config.api_url
    health_url = urljoin(url, "/health")

    start_time = time.time()
    try:
        response = requests.get(health_url, timeout=timeout)
        elapsed_ms = int((time.time() - start_time) * 1000)

        if response.status_code == 200:
            data = response.json()
            return {
                "healthy": True,
                "status": "ok",
                "message": f"RAG API 服务正常运行 (响应时间: {elapsed_ms}ms)",
                "response_time_ms": elapsed_ms,
                "version": data.get("version", "unknown"),
            }
        else:
            return {
                "healthy": False,
                "status": "error",
                "message": f"RAG API 返回错误状态码: {response.status_code}",
            }
    except Timeout:
        return {
            "healthy": False,
            "status": "timeout",
            "message": f"RAG API 服务响应超时（>{timeout}秒），请检查服务状态",
        }
    except ConnectionError:
        return {
            "healthy": False,
            "status": "unreachable",
            "message": "RAG API 服务不可达，请确认服务已启动",
        }
    except RequestException as e:
        return {
            "healthy": False,
            "status": "error",
            "message": f"RAG API 健康检查失败: {str(e)}",
        }
    except json.JSONDecodeError:
        return {
            "healthy": False,
            "status": "error",
            "message": "RAG API 返回非 JSON 格式响应",
        }


# ── JWT helpers ──────────────────────────────────────────────────

def _decode_jwt_exp(token: Optional[str]) -> float:
    """解码 JWT payload 的 exp 字段，返回 Unix 时间戳。

    仅做 base64 解码，不校验签名（CLI 场景无需签名验证）。
    解析失败时返回 0，确保 token 被视为已过期以触发刷新。
    """
    if not token:
        return 0.0
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return 0.0
        payload_b64 = parts[1]
        # 补齐 base64url padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        return float(exp) if exp is not None else 0.0
    except Exception:
        return 0.0


# ── Shell RC 凭据解析 ────────────────────────────────────────────

_USER_PAT = re.compile(r"export\s+RAG_API_USERNAME\s*=\s*[\"']?([^\s\"';]+)")
_PASS_PAT = re.compile(r"export\s+RAG_API_PASSWORD\s*=\s*[\"']?([^\s\"';]+)")


def _read_credentials_from_rc() -> Optional[Tuple[str, str]]:
    """从 ~/.zshrc / ~/.bashrc / ~/.bash_profile 读取 RAG 凭据。"""
    for rc_name in (".zshrc", ".bashrc", ".bash_profile"):
        rc = Path.home() / rc_name
        if not rc.exists():
            continue
        try:
            text = rc.read_text(encoding="utf-8")
        except OSError:
            continue
        user_match = _USER_PAT.search(text)
        pass_match = _PASS_PAT.search(text)
        if user_match and pass_match:
            return user_match.group(1), pass_match.group(1)
    return None


# ── API Client ───────────────────────────────────────────────────

class APIClient:
    """RAG API 客户端 - 支持自动刷新 Token 和超时控制"""

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        self.base_url = base_url or config.api_url
        self.timeout = config.api_timeout
        self.search_timeout = API_SEARCH_TIMEOUT
        self.token = token or self._load_token()

        # 从环境变量读取凭据（可能为空，后续 _ensure_credentials 会兜底）
        self.username: Optional[str] = os.environ.get("RAG_API_USERNAME")
        self.password: Optional[str] = os.environ.get("RAG_API_PASSWORD")

        # 从 JWT 解析真实过期时间（而非客户端假设）
        self.token_expires_at: float = _decode_jwt_exp(self.token)

    # ── Token 文件操作 ────────────────────────────────────────────

    def _load_token(self) -> Optional[str]:
        """从文件加载 Token"""
        token_file = config.token_file
        if token_file.exists():
            token = token_file.read_text().strip()
            if token:
                return token
        return None

    def _save_token(self, token: str, expires_in: int = 3600):
        """保存 Token 到文件"""
        token_file = config.token_file
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token)
        token_file.chmod(0o600)
        # 用服务端返回的 expires_in 设客户端过期提醒（提前 60 秒）
        self.token_expires_at = time.time() + expires_in - 60

    # ── Token 过期判断 ────────────────────────────────────────────

    def _is_token_expired(self) -> bool:
        """检查 Token 是否过期（基于 JWT exp 或客户端记录）"""
        if not self.token:
            return True
        return time.time() >= self.token_expires_at

    # ── 凭据获取 ─────────────────────────────────────────────────

    def _ensure_credentials(self) -> bool:
        """确保凭据可用。优先级：实例属性 → 环境变量 → shell rc 文件。

        Returns:
            True if credentials are available after this call.
        """
        if self.username and self.password:
            return True
        # 尝试环境变量
        self.username = os.environ.get("RAG_API_USERNAME")
        self.password = os.environ.get("RAG_API_PASSWORD")
        if self.username and self.password:
            return True
        # 最后从 shell rc 文件解析
        creds = _read_credentials_from_rc()
        if creds:
            self.username, self.password = creds
            return True
        return False

    # ── HTTP 基础 ────────────────────────────────────────────────

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path)

    # ── 登录 / 刷新 ─────────────────────────────────────────────

    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """登录并保存 Token"""
        username = username or self.username
        password = password or self.password

        if not username:
            username = Prompt.ask("用户名", default="admin")
        if not password:
            password = Prompt.ask("密码", password=True)

        try:
            response = requests.post(
                self._url("/api/v1/auth/login"),
                data={"username": username, "password": password},
                timeout=self.timeout,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    token_data = data.get("data", {})
                    token = token_data.get("access_token")
                    expires_in = token_data.get("expires_in", 3600)
                else:
                    token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)

                if token:
                    self._save_token(token, expires_in)
                    self.token = token
                    self.username = username
                    self.password = password
                    console.print("[green]✓ 登录成功[/green]")
                    return True

            console.print("[red]✗ 登录失败: 用户名或密码错误[/red]")
            return False

        except requests.RequestException as e:
            console.print(f"[red]登录失败: {e}[/red]")
            return False

    def _auto_refresh_token(self) -> bool:
        """自动刷新 Token（内部会尝试多种途径获取凭据）"""
        if not self._ensure_credentials():
            console.print("[yellow]未找到自动登录凭据，请执行 'ath auth setup' 或手动 'ath auth login'[/yellow]")
            return False
        console.print("[dim]Token 已过期，正在自动刷新...[/dim]")
        return self.login(self.username, self.password)

    # ── HTTP 方法 ────────────────────────────────────────────────

    def get(self, path: str, params: Optional[Dict] = None, retry: bool = True, timeout: Optional[int] = None) -> Optional[Dict]:
        """GET 请求"""
        if self._is_token_expired():
            self._auto_refresh_token()

        actual_timeout = timeout or self.timeout

        try:
            response = requests.get(
                self._url(path),
                headers=self._get_headers(),
                params=params,
                timeout=actual_timeout,
            )

            if response.status_code == 401 and retry:
                if self._auto_refresh_token():
                    return self.get(path, params, retry=False, timeout=actual_timeout)

            return self._handle_response(response)

        except Timeout:
            console.print(f"[red]请求超时（>{actual_timeout}秒）：RAG 服务响应缓慢，请检查服务状态[/red]")
            console.print(f"[dim]提示：使用 'ath service status' 查看服务状态[/dim]")
            return None
        except ConnectionError:
            console.print(f"[red]连接失败：RAG API 服务不可达[/red]")
            console.print(f"[dim]提示：使用 'ath service start' 启动服务[/dim]")
            return None
        except requests.RequestException as e:
            console.print(f"[red]请求失败: {e}[/red]")
            return None

    def post(self, path: str, data: Optional[Dict] = None, json_data: Optional[Dict] = None, retry: bool = True, timeout: Optional[int] = None) -> Optional[Dict]:
        """POST 请求"""
        if self._is_token_expired():
            self._auto_refresh_token()

        actual_timeout = timeout or self.timeout

        try:
            kwargs: Dict[str, Any] = {"headers": self._get_headers(), "timeout": actual_timeout}
            if json_data:
                kwargs["json"] = json_data
            elif data:
                kwargs["data"] = data

            response = requests.post(self._url(path), **kwargs)

            if response.status_code == 401 and retry:
                if self._auto_refresh_token():
                    return self.post(path, data, json_data, retry=False, timeout=actual_timeout)

            return self._handle_response(response)

        except Timeout:
            console.print(f"[red]请求超时（>{actual_timeout}秒）：RAG 服务响应缓慢，请检查服务状态[/red]")
            console.print(f"[dim]提示：使用 'ath service status' 查看服务状态[/dim]")
            return None
        except ConnectionError:
            console.print(f"[red]连接失败：RAG API 服务不可达[/red]")
            console.print(f"[dim]提示：使用 'ath service start' 启动服务[/dim]")
            return None
        except requests.RequestException as e:
            console.print(f"[red]请求失败: {e}[/red]")
            return None

    def delete(self, path: str, retry: bool = True) -> Optional[Dict]:
        """DELETE 请求"""
        if self._is_token_expired():
            self._auto_refresh_token()

        try:
            response = requests.delete(
                self._url(path),
                headers=self._get_headers(),
                timeout=self.timeout,
            )

            if response.status_code == 401 and retry:
                if self._auto_refresh_token():
                    return self.delete(path, retry=False)

            return self._handle_response(response)

        except requests.RequestException as e:
            console.print(f"[red]请求失败: {e}[/red]")
            return None

    def _handle_response(self, response: requests.Response) -> Optional[Dict]:
        """处理响应"""
        if response.status_code == 401:
            console.print("[red]认证失败，请先登录 (ath auth login)[/red]")
            return None

        if response.status_code >= 500:
            console.print(f"[red]服务端错误 (HTTP {response.status_code})[/red]")
            console.print(f"[dim]提示：服务可能正在重启或遇到内部错误[/dim]")
            return None

        try:
            return response.json()
        except json.JSONDecodeError:
            return {"success": response.status_code == 200, "data": response.text}

    def upload_file(self, path: str, file_path: Path, metadata: Optional[Dict] = None, retry: bool = True) -> Optional[Dict]:
        """上传文件"""
        if self._is_token_expired():
            self._auto_refresh_token()

        try:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f)}
                data = {"metadata": json.dumps(metadata or {})}
                headers: Dict[str, str] = {}
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"

                response = requests.post(
                    self._url(path),
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=self.timeout * 2,
                )

                if response.status_code == 401 and retry:
                    if self._auto_refresh_token():
                        return self.upload_file(path, file_path, metadata, retry=False)

                return self._handle_response(response)

        except requests.RequestException as e:
            console.print(f"[red]上传失败: {e}[/red]")
            return None


# 全局 API 客户端实例
api_client = APIClient()
