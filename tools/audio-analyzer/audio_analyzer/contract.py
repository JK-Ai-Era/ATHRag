"""音频解析器输出契约定义与校验

所有音频解析器必须输出符合 ParseResult 结构的 JSON。
复用 doc-analyzer 的契约定义，保持一致性。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================================
# 数据结构（与 doc-analyzer 保持一致）
# ============================================================================

@dataclass
class SemanticInfo:
    """语义增强信息（可选）"""
    summary: str = ""
    keywords: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)


@dataclass
class ChunkInfo:
    """预分块信息（可选）"""
    text: str = ""
    position: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioSegment:
    """音频片段信息"""
    start: float = 0.0          # 开始时间（秒）
    end: float = 0.0            # 结束时间（秒）
    text: str = ""              # 识别文本（语音片段）
    confidence: float = 0.0     # 置信度
    label: str = ""             # 标签（如 "speech", "music", "silence"）


@dataclass
class AudioFeatures:
    """音频特征"""
    duration: float = 0.0       # 时长（秒）
    sample_rate: int = 0        # 采样率
    channels: int = 0           # 声道数
    format: str = ""            # 格式（wav, mp3, ...）
    bitrate: int = 0            # 比特率
    tempo: float = 0.0          # BPM
    key: str = ""               # 调性
    loudness: float = 0.0       # 响度（dB）
    spectral_centroid: float = 0.0  # 频谱质心
    zero_crossing_rate: float = 0.0  # 过零率


@dataclass
class ParseResult:
    """音频解析器标准化输出

    所有音频解析器 CLI 必须输出符合此结构的 JSON。

    必填字段：source, type, format, content, metadata
    可选字段：chunks, semantic, segments, features
    """
    # === 必填 ===
    source: str                     # 源文件绝对路径
    type: str                       # 文件类型: audio
    format: str                     # 具体格式: mp3 / wav / flac / ...
    content: str                    # 提取的文本内容（转录文本）
    metadata: Dict[str, Any]        # 元数据字典

    # === 可选 ===
    chunks: List[ChunkInfo] = field(default_factory=list)
    semantic: Optional[SemanticInfo] = None
    segments: List[AudioSegment] = field(default_factory=list)
    features: Optional[AudioFeatures] = None

    # === 内部 ===
    parser: str = ""                # 使用的解析器名称
    success: bool = True            # 是否解析成功
    error: str = ""                 # 错误信息（success=False 时）

    def to_dict(self) -> Dict[str, Any]:
        """转为字典，过滤空值"""
        d = {
            "source": self.source,
            "type": self.type,
            "format": self.format,
            "content": self.content,
            "metadata": self.metadata,
            "parser": self.parser,
            "success": self.success,
        }
        if self.error:
            d["error"] = self.error
        if self.chunks:
            d["chunks"] = [asdict(c) for c in self.chunks]
        if self.semantic and (self.semantic.summary or self.semantic.keywords):
            d["semantic"] = asdict(self.semantic)
        if self.segments:
            d["segments"] = [asdict(s) for s in self.segments]
        if self.features:
            d["features"] = asdict(self.features)
        return d

    def to_json(self, indent: int = 2) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def error_result(source: str, error: str, format: str = "unknown") -> ParseResult:
    """构造解析失败的结果"""
    return ParseResult(
        source=str(source),
        type="audio",
        format=format,
        content="",
        metadata={},
        success=False,
        error=error,
    )


# ============================================================================
# 校验
# ============================================================================

class ContractViolation(Exception):
    """输出不符合契约"""
    pass


REQUIRED_FIELDS = {"source", "type", "format", "content", "metadata"}


def validate_output(data: dict) -> None:
    """校验解析器输出是否符合契约

    Args:
        data: 解析器输出的字典

    Raises:
        ContractViolation: 不符合契约时抛出
    """
    # 检查必填字段
    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ContractViolation(f"缺少必填字段: {missing}")

    # 检查类型
    if not isinstance(data["content"], str):
        raise ContractViolation(f"content 必须是字符串，实际是 {type(data['content']).__name__}")

    if not isinstance(data["metadata"], dict):
        raise ContractViolation(f"metadata 必须是字典，实际是 {type(data['metadata']).__name__}")

    if data["type"] != "audio":
        raise ContractViolation(f"type 必须是 'audio'，实际是 '{data['type']}'")

    if not data["source"]:
        raise ContractViolation("source 不能为空")

    if not data["format"]:
        raise ContractViolation("format 不能为空")


def validate_and_parse(raw_json: str) -> ParseResult:
    """校验 JSON 并转为 ParseResult

    Args:
        raw_json: 解析器输出的 JSON 字符串

    Returns:
        ParseResult 实例

    Raises:
        ContractViolation: 不符合契约时抛出
        json.JSONDecodeError: JSON 格式错误时抛出
    """
    data = json.loads(raw_json)
    validate_output(data)

    # 解析语义信息
    semantic = None
    if "semantic" in data and data["semantic"]:
        s = data["semantic"]
        semantic = SemanticInfo(
            summary=s.get("summary", ""),
            keywords=s.get("keywords", []),
            categories=s.get("categories", []),
        )

    # 解析分块信息
    chunks = []
    if "chunks" in data and data["chunks"]:
        for c in data["chunks"]:
            chunks.append(ChunkInfo(
                text=c.get("text", ""),
                position=c.get("position", ""),
                metadata=c.get("metadata", {}),
            ))

    # 解析音频片段
    segments = []
    if "segments" in data and data["segments"]:
        for s in data["segments"]:
            segments.append(AudioSegment(
                start=s.get("start", 0.0),
                end=s.get("end", 0.0),
                text=s.get("text", ""),
                confidence=s.get("confidence", 0.0),
                label=s.get("label", ""),
            ))

    # 解析音频特征
    features = None
    if "features" in data and data["features"]:
        f = data["features"]
        features = AudioFeatures(
            duration=f.get("duration", 0.0),
            sample_rate=f.get("sample_rate", 0),
            channels=f.get("channels", 0),
            format=f.get("format", ""),
            bitrate=f.get("bitrate", 0),
            tempo=f.get("tempo", 0.0),
            key=f.get("key", ""),
            loudness=f.get("loudness", 0.0),
            spectral_centroid=f.get("spectral_centroid", 0.0),
            zero_crossing_rate=f.get("zero_crossing_rate", 0.0),
        )

    return ParseResult(
        source=data["source"],
        type=data["type"],
        format=data["format"],
        content=data["content"],
        metadata=data["metadata"],
        chunks=chunks,
        semantic=semantic,
        segments=segments,
        features=features,
        parser=data.get("parser", ""),
        success=data.get("success", True),
        error=data.get("error", ""),
    )
