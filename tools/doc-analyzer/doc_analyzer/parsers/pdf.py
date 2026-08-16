"""PDF 解析器

支持两种后端：
1. MinerU — 高质量 PDF 解析（需要 Python 3.11 环境）
2. pypdf — 轻量级回退方案
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from doc_analyzer.contract import ParseResult, error_result
from doc_analyzer.model_config import get_model_config
from doc_analyzer.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# MinerU 脚本路径（相对于 ATHRag 项目根目录）
MINERU_SCRIPT_CANDIDATES = [
    Path(__file__).parent.parent.parent.parent.parent / "scripts" / "mineru.sh",
    Path.home() / "Projects" / "ATHRag" / "scripts" / "mineru.sh",
]


class PDFParser(BaseParser):
    """PDF 解析器"""

    parser_name = "pdf"
    supported_extensions = [".pdf"]

    def __init__(self):
        self.mineru_script = self._find_mineru()
        self.mineru_available = self._check_mineru()

    def _find_mineru(self) -> Path | None:
        """查找 MinerU 脚本"""
        for candidate in MINERU_SCRIPT_CANDIDATES:
            if candidate.exists():
                return candidate
        return None

    def _check_mineru(self) -> bool:
        """检查 MinerU 是否可用"""
        if not self.mineru_script:
            return False
        try:
            venv_path = self.mineru_script.parent.parent / ".venv-311"
            if not venv_path.exists():
                return False
            result = subprocess.run(
                [str(venv_path / "bin" / "python"), "-c", "import magic_pdf"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception as e:
            logger.debug(f"MinerU 检测失败: {e}")
            return False

    def parse(self, file_path: Path) -> ParseResult:
        file_path = Path(file_path).resolve()

        config = get_model_config("document", "pdf")
        provider = config.get("provider", "auto")

        if provider == "mineru":
            if self.mineru_available:
                return self._parse_with_mineru(file_path)
            else:
                logger.warning("MinerU 不可用，回退到 pypdf")
                return self._parse_with_pypdf(file_path)
        elif provider == "pypdf":
            return self._parse_with_pypdf(file_path)
        else:  # auto
            if self.mineru_available:
                try:
                    return self._parse_with_mineru(file_path)
                except Exception as e:
                    logger.warning(f"MinerU 解析失败，回退到 pypdf: {e}")
            return self._parse_with_pypdf(file_path)

    def _parse_with_mineru(self, file_path: Path) -> ParseResult:
        """使用 MinerU 解析 PDF"""
        try:
            result = subprocess.run(
                [str(self.mineru_script), str(file_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                raise RuntimeError(f"MinerU 执行失败: {result.stderr}")

            output = result.stdout.strip()
            # MinerU 输出最后一行是 JSON
            lines = output.split("\n")
            for line in reversed(lines):
                line = line.strip()
                if line and line.startswith("{"):
                    try:
                        data = json.loads(line)
                        if data.get("success"):
                            text = data.get("text", "")
                            return self._build_result(file_path, text, "mineru")
                        else:
                            raise RuntimeError(f"MinerU 处理失败: {data.get('error')}")
                    except json.JSONDecodeError:
                        continue

            # 如果没找到 JSON，用整个输出
            return self._build_result(file_path, output, "mineru")

        except subprocess.TimeoutExpired:
            raise ValueError("MinerU 处理超时（超过 2 分钟）")

    def _parse_with_pypdf(self, file_path: Path) -> ParseResult:
        """使用 pypdf 解析 PDF"""
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(file_path))
            text_parts = []

            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)

            content = "\n\n".join(text_parts)

            if not content.strip():
                return error_result(str(file_path), "PDF 未提取到文本内容", "pdf")

            return self._build_result(file_path, content, "pypdf")

        except Exception as e:
            return error_result(str(file_path), f"PDF 解析失败: {e}", "pdf")

    def _build_result(self, file_path: Path, content: str, parser_backend: str) -> ParseResult:
        """构造标准化结果"""
        metadata = {
            "filename": file_path.name,
            "file_size": file_path.stat().st_size,
            "parser_backend": parser_backend,
        }

        # 尝试提取页数
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            metadata["pages"] = len(reader.pages)
        except Exception:
            pass

        return ParseResult(
            source=str(file_path),
            type="document",
            format="pdf",
            content=content,
            metadata=metadata,
            parser=f"pdf({parser_backend})",
        )
