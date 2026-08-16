"""音频元数据解析器 — 使用 mutagen 提取音频文件元数据"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..contract import ParseResult, error_result
from .base import AudioParser


class MetadataParser(AudioParser):
    """音频元数据解析器

    使用 mutagen 提取音频文件的元数据（标题、艺术家、专辑等）。
    轻量级解析，不进行音频分析或语音识别。
    """

    name = "metadata"
    supported_formats = [
        "mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "wma",
        "aiff", "aif", "ape", "wv", "mpc", "spx", "tta",
    ]

    def parse(self, file_path: Path, **options) -> ParseResult:
        """解析音频元数据"""
        try:
            import mutagen
            from mutagen.easyid3 import EasyID3
            from mutagen.mp3 import MP3
            from mutagen.flac import FLAC
            from mutagen.wave import WAVE
        except ImportError:
            return error_result(str(file_path), "mutagen 未安装", self._get_format(file_path))

        try:
            audio_file = mutagen.File(str(file_path))
            if audio_file is None:
                return error_result(str(file_path), "无法识别音频格式", self._get_format(file_path))

            # 提取元数据
            metadata = self._extract_metadata(audio_file, file_path)

            # 构造内容摘要
            content = self._build_content(metadata, file_path)

            return ParseResult(
                source=str(file_path.resolve()),
                type="audio",
                format=self._get_format(file_path),
                content=content,
                metadata=metadata,
                parser=self.name,
            )

        except Exception as e:
            return error_result(str(file_path), f"元数据解析失败: {e}", self._get_format(file_path))

    def _extract_metadata(self, audio_file: Any, file_path: Path) -> Dict[str, Any]:
        """提取元数据"""
        metadata = {
            "filename": file_path.name,
            "file_size": file_path.stat().st_size,
        }

        # 基本信息
        if hasattr(audio_file, "info"):
            info = audio_file.info
            metadata["duration"] = getattr(info, "length", 0.0)
            metadata["sample_rate"] = getattr(info, "sample_rate", 0)
            metadata["channels"] = getattr(info, "channels", 0)
            metadata["bitrate"] = getattr(info, "bitrate", 0)
            metadata["bits_per_sample"] = getattr(info, "bits_per_sample", 0)

        # ID3 标签（MP3）
        if hasattr(audio_file, "tags") and audio_file.tags:
            tags = audio_file.tags
            # 尝试 EasyID3
            try:
                if hasattr(tags, "as_dict"):
                    for key, values in tags.as_dict().items():
                        if values:
                            metadata[key] = values[0] if len(values) == 1 else values
            except Exception:
                # 通用标签提取
                for key in ["TIT2", "TPE1", "TALB", "TDRC", "TCON", "TRCK"]:
                    if key in tags:
                        metadata[key] = str(tags[key])

            # FLAC 标签
            if hasattr(tags, "get"):
                for key in ["title", "artist", "album", "date", "genre", "tracknumber"]:
                    val = tags.get(key)
                    if val:
                        metadata[key] = val[0] if isinstance(val, list) else val

        return metadata

    def _build_content(self, metadata: Dict[str, Any], file_path: Path) -> str:
        """构造内容摘要"""
        parts = [f"音频文件: {file_path.name}"]

        if "title" in metadata:
            parts.append(f"标题: {metadata['title']}")
        if "artist" in metadata:
            parts.append(f"艺术家: {metadata['artist']}")
        if "album" in metadata:
            parts.append(f"专辑: {metadata['album']}")
        if "duration" in metadata:
            dur = metadata["duration"]
            parts.append(f"时长: {int(dur // 60)}:{int(dur % 60):02d}")
        if "sample_rate" in metadata:
            parts.append(f"采样率: {metadata['sample_rate']} Hz")
        if "bitrate" in metadata:
            parts.append(f"比特率: {metadata['bitrate']} bps")

        return "\n".join(parts)
