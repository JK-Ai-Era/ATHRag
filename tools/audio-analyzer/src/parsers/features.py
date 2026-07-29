"""音频特征解析器 — 使用 librosa 提取音频特征"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..contract import ParseResult, AudioFeatures, AudioSegment, error_result
from .base import AudioParser


class FeaturesParser(AudioParser):
    """音频特征解析器

    使用 librosa 提取音频的声学特征：
    - 时长、采样率、声道数
    - BPM（节拍）
    - 响度
    - 频谱质心
    - 过零率
    - MFCC 特征
    """

    name = "features"
    supported_formats = ["mp3", "wav", "flac", "ogg", "opus", "m4a", "aac"]

    def parse(self, file_path: Path, **options) -> ParseResult:
        """提取音频特征"""
        try:
            import librosa
            import numpy as np
        except ImportError:
            return error_result(str(file_path), "librosa 未安装", self._get_format(file_path))

        try:
            # 加载音频
            y, sr = librosa.load(str(file_path), sr=None, mono=False)

            # 确保单声道用于分析
            if y.ndim > 1:
                y_mono = librosa.to_mono(y)
            else:
                y_mono = y

            # 提取特征
            features = self._extract_features(y_mono, sr, file_path)

            # 检测静音段和语音段
            segments = self._detect_segments(y_mono, sr)

            # 构造内容摘要
            content = self._build_content(features, file_path)

            return ParseResult(
                source=str(file_path.resolve()),
                type="audio",
                format=self._get_format(file_path),
                content=content,
                metadata={
                    "filename": file_path.name,
                    "file_size": file_path.stat().st_size,
                    "duration": features.duration,
                    "sample_rate": features.sample_rate,
                    "channels": features.channels,
                },
                segments=segments,
                features=features,
                parser=self.name,
            )

        except Exception as e:
            return error_result(str(file_path), f"特征提取失败: {e}", self._get_format(file_path))

    def _extract_features(self, y, sr: int, file_path: Path) -> AudioFeatures:
        """提取音频特征"""
        import librosa
        import numpy as np

        # 基本信息
        duration = librosa.get_duration(y=y, sr=sr)

        # 节拍检测
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        if hasattr(tempo, '__len__'):
            tempo = float(tempo[0]) if len(tempo) > 0 else 0.0
        else:
            tempo = float(tempo)

        # 响度
        rms = librosa.feature.rms(y=y)
        loudness = float(np.mean(rms))

        # 频谱质心
        spectral_centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))

        # 过零率
        zero_crossing_rate = float(np.mean(librosa.feature.zero_crossing_rate(y)))

        # 调性检测
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        key_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        key_index = int(np.argmax(np.mean(chroma, axis=1)))
        key = key_names[key_index]

        return AudioFeatures(
            duration=duration,
            sample_rate=sr,
            channels=1 if y.ndim == 1 else y.shape[0],
            format=self._get_format(file_path),
            tempo=tempo,
            key=key,
            loudness=loudness,
            spectral_centroid=spectral_centroid,
            zero_crossing_rate=zero_crossing_rate,
        )

    def _detect_segments(self, y, sr: int) -> List[AudioSegment]:
        """检测音频片段（静音/非静音）"""
        import librosa

        segments = []

        # 使用 librosa 的静音检测
        non_silent_intervals = librosa.effects.split(y, top_db=30)

        for i, (start, end) in enumerate(non_silent_intervals):
            start_time = start / sr
            end_time = end / sr
            segments.append(AudioSegment(
                start=start_time,
                end=end_time,
                label="audio",
            ))

        return segments

    def _build_content(self, features: AudioFeatures, file_path: Path) -> str:
        """构造内容摘要"""
        parts = [f"音频文件: {file_path.name}"]
        parts.append(f"时长: {int(features.duration // 60)}:{int(features.duration % 60):02d}")
        parts.append(f"采样率: {features.sample_rate} Hz")
        parts.append(f"声道数: {features.channels}")
        parts.append(f"BPM: {features.tempo:.1f}")
        parts.append(f"调性: {features.key}")
        parts.append(f"响度: {features.loudness:.4f}")
        parts.append(f"频谱质心: {features.spectral_centroid:.1f} Hz")
        parts.append(f"过零率: {features.zero_crossing_rate:.4f}")
        return "\n".join(parts)
