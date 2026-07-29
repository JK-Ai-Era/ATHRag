"""音频分类解析器 — 使用 PANNs 进行音频事件识别

PANNs (Pre-trained Audio Neural Networks) 在 AudioSet 上训练，
能识别 527 种音频事件，包括：
- 乐器：钢琴、吉他、弦乐、鼓...
- 音乐类型：古典、流行、爵士、摇滚...
- 人声：歌唱、演讲、合唱...
- 环境音：自然、城市、室内...
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..contract import (
    ParseResult, AudioFeatures, AudioSegment, SemanticInfo, error_result,
)
from ..model_config import get_model_config
from .base import AudioParser

logger = logging.getLogger(__name__)

# AudioSet 527 类中与音乐相关的标签（精选）
MUSIC_RELATED_TAGS = {
    # 乐器
    "Musical instrument", "Piano", "Guitar", "Violin, fiddle",
    "Cello", "Double bass", "Flute", "Saxophone", "Trumpet",
    "Drum", "Snare drum", "Bass drum", "Cymbal", "Hi-hat",
    "Electronic organ", "Harmonica", "Accordion", "Harp",
    "Steel guitar, slide guitar", "Acoustic guitar", "Electric guitar",
    "Bass guitar", "Keyboard (musical)", "Synthesizer", "Sampler",
    "Tabla", "Xylophone", "Marimba", "Vibraphone", "Chime",
    "Strings", "Brass", "Woodwind",
    # 音乐类型/风格
    "Music", "Musical genre", "Classical music", "Pop music",
    "Hip hop music", "Rock music", "Country music", "Jazz",
    "Electronic music", "Reggae", "Blues", "Rhythm and blues",
    "Soul music", "Funk", "Gospel music", "Latin music",
    "Ambient music", "New-age music", "Dance music", "Techno",
    "Trance music", "Drum and bass", "Dubstep", "House music",
    "Opera", "Symphony", "Chamber music", "Background music",
    "Theme music", "Video game music",
    # 人声/歌唱
    "Singing", "Vocal music", "Choir", "Chant", "Rapping",
    "Humming", "Yodeling", "Beatboxing",
    # 音乐元素
    "Melody", "Harmony", "Rhythm", "Tempo", "Beat",
    "Bass line", "Drum beat", "Guitar riff",
    # 情绪/氛围
    "Happy music", "Sad music", "Tender music", "Exciting music",
    "Angry music", "Scary music", "Relaxing music",
}


class ClassifyParser(AudioParser):
    """音频分类解析器

    使用 PANNs (CNN14) 识别音频中的事件和场景。
    特别针对音乐场景优化，提取乐器、风格、情绪等语义标签。

    输出：
    - content: 人类可读的音频内容描述
    - semantic: 结构化的标签、分类、摘要
    - segments: 按时间段的分类结果
    """

    name = "classify"
    supported_formats = ["mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "wma", "aiff"]

    def parse(self, file_path: Path, **options) -> ParseResult:
        """音频分类 — 根据 provider 分发"""
        if not file_path.exists():
            return error_result(str(file_path), "文件不存在", self._get_format(file_path))

        config = get_model_config("audio", "classify")
        provider = config.get("provider", "panns")

        if provider == "panns":
            return self._parse_panns(file_path, config, **options)
        elif provider == "none":
            return error_result(str(file_path), "音频分类已禁用", self._get_format(file_path))
        else:
            return error_result(str(file_path), f"未知 classify provider: {provider}", self._get_format(file_path))

    def _parse_panns(self, file_path: Path, config: dict, **options) -> ParseResult:
        """PANNs 音频事件分类"""
        try:
            import torch
            import numpy as np
            from panns_inference import AudioTagging
        except ImportError:
            return error_result(
                str(file_path),
                "panns-inference 或 PyTorch 未安装",
                self._get_format(file_path),
            )

        device = options.get("device") or config.get("device", "auto")
        if device == "auto":
            from ..model_config import get_hardware_device
            device = get_hardware_device()
        top_k = options.get("top_k", 10)

        try:
            # 加载音频
            import librosa
            y, sr = librosa.load(str(file_path), sr=32000, mono=True)

            # PANNs 需要 (1, samples) 的输入
            waveform = torch.tensor(y).unsqueeze(0).float()

            # 推理
            model = AudioTagging(checkpoint_path=None, device=device)
            clipwise_output, embedding = model.inference(waveform)

            # clipwise_output: (1, 527) 每个类别的概率
            probs = clipwise_output[0]

            # 获取 AudioSet 标签
            labels = self._load_labels()
            if not labels:
                return error_result(str(file_path), "无法加载 AudioSet 标签", self._get_format(file_path))

            # 提取 top-k 标签
            top_indices = np.argsort(probs)[::-1][:top_k]
            top_tags = []
            for idx in top_indices:
                tag = labels.get(idx, f"class_{idx}")
                confidence = float(probs[idx])
                if confidence > 0.01:  # 阈值过滤
                    top_tags.append({"tag": tag, "confidence": confidence})

            # 分离音乐标签和环境标签
            music_tags = [t for t in top_tags if t["tag"] in MUSIC_RELATED_TAGS]
            other_tags = [t for t in top_tags if t["tag"] not in MUSIC_RELATED_TAGS]

            # 构造内容描述
            content = self._build_content(file_path, music_tags, other_tags)

            # 构造语义信息
            semantic = SemanticInfo(
                summary=self._build_summary(music_tags, other_tags),
                keywords=[t["tag"] for t in top_tags[:5]],
                categories=self._categorize(music_tags),
            )

            # 构造段落级分析（每 10 秒一段）
            segments = self._analyze_segments(y, sr, model, labels, segment_duration=10.0)

            return ParseResult(
                source=str(file_path.resolve()),
                type="audio",
                format=self._get_format(file_path),
                content=content,
                metadata={
                    "filename": file_path.name,
                    "file_size": file_path.stat().st_size,
                    "duration": len(y) / sr,
                    "sample_rate": sr,
                    "model": "PANNs-CNN14",
                    "top_tags": top_tags,
                    "music_tags": music_tags,
                    "embedding_dim": int(embedding.shape[1]) if embedding is not None else 0,
                },
                semantic=semantic,
                segments=segments,
                parser=self.name,
            )

        except Exception as e:
            logger.exception(f"PANNs 分类失败: {e}")
            return error_result(str(file_path), f"音频分类失败: {e}", self._get_format(file_path))

    def _load_labels(self) -> Dict[int, str]:
        """加载 AudioSet 标签映射（带缓存）"""
        if hasattr(self, "_labels_cache") and self._labels_cache:
            return self._labels_cache

        import csv
        from pathlib import Path

        label_paths = [
            Path.home() / "panns_data" / "class_labels_indices.csv",
            Path("/tmp/class_labels_indices.csv"),
        ]

        for path in label_paths:
            if path.exists():
                labels = {}
                with open(path, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        labels[int(row["index"])] = row["display_name"]
                self._labels_cache = labels
                return labels

        # 在线下载
        try:
            import urllib.request
            url = "http://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv"
            dest = Path.home() / "panns_data" / "class_labels_indices.csv"
            dest.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(url, str(dest))
            return self._load_labels()
        except Exception as e:
            logger.warning(f"下载 AudioSet 标签失败: {e}")
            return {}

    def _build_content(
        self,
        file_path: Path,
        music_tags: List[dict],
        other_tags: List[dict],
    ) -> str:
        """构造人类可读的内容描述"""
        parts = [f"音频文件: {file_path.name}"]

        if music_tags:
            tags_str = ", ".join(
                f"{t['tag']}({t['confidence']:.0%})" for t in music_tags[:5]
            )
            parts.append(f"音乐内容: {tags_str}")

        if other_tags:
            tags_str = ", ".join(
                f"{t['tag']}({t['confidence']:.0%})" for t in other_tags[:3]
            )
            parts.append(f"其他声音: {tags_str}")

        return "\n".join(parts)

    def _build_summary(self, music_tags: List[dict], other_tags: List[dict]) -> str:
        """构造摘要"""
        if not music_tags and not other_tags:
            return "未识别到明显的声音内容"

        parts = []
        if music_tags:
            top_music = music_tags[0]["tag"]
            parts.append(f"主要包含 {top_music}")
            if len(music_tags) > 1:
                others = ", ".join(t["tag"] for t in music_tags[1:3])
                parts.append(f"同时含有 {others}")

        if other_tags:
            top_other = other_tags[0]["tag"]
            parts.append(f"伴有 {top_other}")

        return "。".join(parts)

    def _categorize(self, music_tags: List[dict]) -> List[str]:
        """从音乐标签推断分类"""
        categories = set()
        tag_names = {t["tag"] for t in music_tags}

        # 乐器
        instruments = {
            "Piano", "Guitar", "Violin, fiddle", "Cello", "Drum",
            "Saxophone", "Trumpet", "Flute", "Bass guitar",
            "Electronic organ", "Synthesizer", "Accordion",
        }
        if tag_names & instruments:
            categories.add("乐器")

        # 人声
        vocals = {"Singing", "Vocal music", "Choir", "Rapping", "Chant"}
        if tag_names & vocals:
            categories.add("人声")

        # 流派
        genres = {
            "Classical music", "Pop music", "Rock music", "Jazz",
            "Electronic music", "Hip hop music", "Country music",
            "Blues", "Reggae", "Dance music",
        }
        if tag_names & genres:
            categories.add("音乐流派")

        # 情绪
        moods = {
            "Happy music", "Sad music", "Tender music",
            "Exciting music", "Angry music", "Relaxing music",
        }
        if tag_names & moods:
            categories.add("情绪氛围")

        return sorted(categories) if categories else ["音频"]

    def _analyze_segments(
        self,
        y,
        sr: int,
        model,
        labels: Dict[int, str],
        segment_duration: float = 10.0,
    ) -> List[AudioSegment]:
        """按时间段分析音频"""
        import torch
        import numpy as np

        segments = []
        segment_samples = int(segment_duration * sr)
        total_samples = len(y)

        for start in range(0, total_samples, segment_samples):
            end = min(start + segment_samples, total_samples)
            segment_audio = y[start:end]

            # 跳过太短的片段
            if len(segment_audio) < sr * 0.5:
                continue

            # 推理
            waveform = torch.tensor(segment_audio).unsqueeze(0).float()
            clipwise_output, _ = model.inference(waveform)
            probs = clipwise_output[0]

            # 取 top-3 标签
            top_indices = np.argsort(probs)[::-1][:3]
            top_labels = []
            for idx in top_indices:
                tag = labels.get(idx, f"class_{idx}")
                conf = float(probs[idx])
                if conf > 0.05:
                    top_labels.append(f"{tag}({conf:.0%})")

            label_str = ", ".join(top_labels) if top_labels else "静音"

            segments.append(AudioSegment(
                start=start / sr,
                end=end / sr,
                text=label_str,
                confidence=float(np.max(probs)),
                label=label_str.split("(")[0] if top_labels else "silence",
            ))

        return segments
