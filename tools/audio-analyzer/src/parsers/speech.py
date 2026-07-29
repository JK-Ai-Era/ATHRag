"""语音识别解析器 — provider 分发架构

通过 models.yaml 的 provider 配置切换实现：
- whisper-local: 本地 Whisper 模型
- openai-api: OpenAI Whisper API
- funasr: 阿里 FunASR（预留）
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ..contract import ParseResult, AudioSegment, error_result
from ..model_config import get_model_config
from .base import AudioParser


class SpeechParser(AudioParser):
    """语音识别解析器

    通过 provider 配置切换底层实现，输出格式不变。
    """

    name = "speech"
    supported_formats = ["mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "wma", "aiff"]

    def parse(self, file_path: Path, **options) -> ParseResult:
        """语音识别 — 根据 provider 分发"""
        if not file_path.exists():
            return error_result(str(file_path), "文件不存在", self._get_format(file_path))

        config = get_model_config("audio", "speech")
        provider = config.get("provider", "whisper-local")

        if provider == "whisper-local":
            return self._parse_whisper_local(file_path, config, **options)
        elif provider == "openai-api":
            return self._parse_openai_api(file_path, config, **options)
        else:
            return error_result(str(file_path), f"未知 speech provider: {provider}", self._get_format(file_path))

    # ========================================================================
    # Provider: whisper-local
    # ========================================================================

    def _parse_whisper_local(self, file_path: Path, config: dict, **options) -> ParseResult:
        """本地 Whisper 识别"""
        try:
            import whisper
        except ImportError:
            return error_result(str(file_path), "whisper 未安装。pip install openai-whisper", self._get_format(file_path))

        model_name = options.get("model") or config.get("model", "base")
        language = options.get("language") or config.get("language")

        try:
            model = whisper.load_model(model_name)
            result = model.transcribe(str(file_path), language=language, verbose=False)

            content = result.get("text", "").strip()
            if not content:
                return error_result(str(file_path), "未识别到语音内容", self._get_format(file_path))

            segments = self._extract_whisper_segments(result.get("segments", []))

            return ParseResult(
                source=str(file_path.resolve()),
                type="audio",
                format=self._get_format(file_path),
                content=content,
                metadata={
                    "filename": file_path.name,
                    "file_size": file_path.stat().st_size,
                    "provider": "whisper-local",
                    "model": model_name,
                    "language": result.get("language", "unknown"),
                    "segment_count": len(segments),
                },
                segments=segments,
                parser=self.name,
            )
        except Exception as e:
            return error_result(str(file_path), f"Whisper 识别失败: {e}", self._get_format(file_path))

    def _extract_whisper_segments(self, raw_segments: list) -> List[AudioSegment]:
        """提取 Whisper 语音片段"""
        return [
            AudioSegment(
                start=seg.get("start", 0.0),
                end=seg.get("end", 0.0),
                text=seg.get("text", "").strip(),
                confidence=seg.get("avg_logprob", 0.0),
                label="speech",
            )
            for seg in raw_segments
        ]

    # ========================================================================
    # Provider: openai-api
    # ========================================================================

    def _parse_openai_api(self, file_path: Path, config: dict, **options) -> ParseResult:
        """OpenAI Whisper API 识别"""
        import os

        api_key = config.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
        base_url = config.get("base_url", "https://api.openai.com/v1").rstrip("/")

        if not api_key:
            return error_result(str(file_path), "OPENAI_API_KEY 未设置", self._get_format(file_path))

        language = options.get("language") or config.get("language")

        try:
            import httpx

            with open(file_path, "rb") as f:
                resp = httpx.post(
                    f"{base_url}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (file_path.name, f)},
                    data={
                        "model": "whisper-1",
                        **({"language": language} if language else {}),
                        "response_format": "verbose_json",
                    },
                    timeout=300,
                )

            if resp.status_code != 200:
                return error_result(str(file_path), f"OpenAI API 错误 ({resp.status_code}): {resp.text[:200]}", self._get_format(file_path))

            data = resp.json()
            content = data.get("text", "").strip()

            if not content:
                return error_result(str(file_path), "OpenAI API 未返回识别结果", self._get_format(file_path))

            # 提取片段
            segments = []
            for seg in data.get("segments", []):
                segments.append(AudioSegment(
                    start=seg.get("start", 0.0),
                    end=seg.get("end", 0.0),
                    text=seg.get("text", "").strip(),
                    confidence=seg.get("avg_logprob", 0.0),
                    label="speech",
                ))

            return ParseResult(
                source=str(file_path.resolve()),
                type="audio",
                format=self._get_format(file_path),
                content=content,
                metadata={
                    "filename": file_path.name,
                    "file_size": file_path.stat().st_size,
                    "provider": "openai-api",
                    "model": "whisper-1",
                    "language": data.get("language", "unknown"),
                    "duration": data.get("duration", 0.0),
                    "segment_count": len(segments),
                },
                segments=segments,
                parser=self.name,
            )

        except httpx.TimeoutException:
            return error_result(str(file_path), "OpenAI API 超时", self._get_format(file_path))
        except Exception as e:
            return error_result(str(file_path), f"OpenAI API 调用失败: {e}", self._get_format(file_path))
