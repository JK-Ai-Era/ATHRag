"""图片解析器 — OCR 文字提取

使用 pytesseract 进行 OCR，支持中英文。
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.contract import ParseResult, error_result
from src.model_config import get_model_config
from src.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class ImageParser(BaseParser):
    """图片解析器（OCR）"""

    parser_name = "image"
    supported_extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"]

    def parse(self, file_path: Path) -> ParseResult:
        file_path = Path(file_path).resolve()

        config = get_model_config("document", "image")
        provider = config.get("provider", "tesseract")
        languages = config.get("languages", "chi_sim+eng")

        if provider == "tesseract":
            return self._parse_tesseract(file_path, languages)
        else:
            return error_result(str(file_path), f"未知 image provider: {provider}", file_path.suffix.lstrip("."))

    def _parse_tesseract(self, file_path: Path, languages: str) -> ParseResult:
        """使用 Tesseract OCR 提取文字"""
        try:
            from PIL import Image
            import pytesseract
        except ImportError:
            return error_result(
                str(file_path),
                "pytesseract 或 Pillow 未安装。请运行: pip install Pillow pytesseract",
                file_path.suffix.lstrip("."),
            )

        try:
            image = Image.open(file_path)

            width, height = image.size
            mode = image.mode
            fmt = image.format or file_path.suffix.lstrip(".")

            text = pytesseract.image_to_string(image, lang=languages)

            if not text.strip():
                return error_result(
                    str(file_path),
                    "图片 OCR 未识别到文本内容",
                    file_path.suffix.lstrip("."),
                )

            content = f"[图片: {file_path.name}]\n\n{text}"

            metadata = {
                "filename": file_path.name,
                "file_size": file_path.stat().st_size,
                "provider": "tesseract",
                "languages": languages,
                "image_width": width,
                "image_height": height,
                "image_mode": mode,
                "image_format": fmt,
            }

            return ParseResult(
                source=str(file_path),
                type="image",
                format=file_path.suffix.lstrip(".").replace("jpg", "jpeg"),
                content=content,
                metadata=metadata,
                parser="image(tesseract)",
            )

        except Exception as e:
            if isinstance(e, ValueError):
                raise
            return error_result(
                str(file_path),
                f"图片 OCR 失败: {e}",
                file_path.suffix.lstrip("."),
            )
