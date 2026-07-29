"""解析器单元测试 — 验证各解析器的独立行为"""

import json
import struct
import tempfile
import wave
from pathlib import Path

import pytest

from src.contract import ParseResult, validate_output
from src.parsers.metadata import MetadataParser
from src.parsers.features import FeaturesParser
from src.parsers.speech import SpeechParser


# ============================================================================
# 辅助工具
# ============================================================================

def make_wav_file(duration_sec: float = 1.0, sample_rate: int = 16000) -> Path:
    """生成一个合法的 WAV 文件（正弦波）"""
    import math

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    n_samples = int(duration_sec * sample_rate)

    with wave.open(tmp.name, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            value = int(32767 * math.sin(2 * math.pi * 440 * i / sample_rate))
            wf.writeframes(struct.pack("<h", value))

    return Path(tmp.name)


def make_fake_mp3() -> Path:
    """生成一个带最小 MP3 帧头的假文件"""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    # MPEG1 Layer3 frame sync word
    tmp.write(b"\xff\xfb\x90\x00" * 100)
    tmp.close()
    return Path(tmp.name)


# ============================================================================
# MetadataParser 测试
# ============================================================================

class TestMetadataParser:
    """MetadataParser 单元测试"""

    def test_name_and_formats(self):
        p = MetadataParser()
        assert p.name == "metadata"
        assert "mp3" in p.supported_formats
        assert "wav" in p.supported_formats
        assert "flac" in p.supported_formats

    def test_can_parse(self):
        p = MetadataParser()
        assert p.can_parse(Path("test.mp3"))
        assert p.can_parse(Path("test.wav"))
        assert not p.can_parse(Path("test.xyz"))

    def test_parse_wav(self):
        """解析合法 WAV 文件"""
        wav_path = make_wav_file()
        try:
            p = MetadataParser()
            result = p.parse(wav_path)
            assert result.success is True
            assert result.type == "audio"
            assert result.format == "wav"
            assert result.parser == "metadata"
            assert len(result.content) > 0
            assert "filename" in result.metadata
            assert result.metadata["duration"] > 0
            assert result.metadata["sample_rate"] == 16000

            # 契约校验
            validate_output(result.to_dict())
        finally:
            wav_path.unlink()

    def test_parse_nonexistent(self):
        """文件不存在"""
        p = MetadataParser()
        result = p.parse(Path("/nonexistent.mp3"))
        assert result.success is False

    def test_parse_fake_mp3(self):
        """假 MP3 文件 — mutagen 可能解析失败，但仍需符合契约"""
        mp3_path = make_fake_mp3()
        try:
            p = MetadataParser()
            result = p.parse(mp3_path)
            d = result.to_dict()
            assert d["type"] == "audio"
            assert "format" in d
            assert "content" in d
            assert "metadata" in d
        finally:
            mp3_path.unlink()


# ============================================================================
# FeaturesParser 测试
# ============================================================================

class TestFeaturesParser:
    """FeaturesParser 单元测试"""

    def test_name_and_formats(self):
        p = FeaturesParser()
        assert p.name == "features"
        assert "mp3" in p.supported_formats
        assert "wav" in p.supported_formats

    def test_parse_wav(self):
        """解析合法 WAV 文件，提取特征"""
        wav_path = make_wav_file(duration_sec=2.0)
        try:
            p = FeaturesParser()
            result = p.parse(wav_path)
            assert result.success is True
            assert result.type == "audio"
            assert result.format == "wav"
            assert result.parser == "features"

            # 特征数据
            assert result.features is not None
            assert result.features.duration > 0
            assert result.features.sample_rate == 16000
            # tempo 可能为 0（纯正弦波无节拍，beat_track 返回 0）
            assert result.features.tempo >= 0
            assert result.features.key in [
                "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"
            ]

            # 片段
            assert len(result.segments) > 0

            # 内容摘要
            assert "BPM" in result.content
            assert "调性" in result.content

            # 契约校验
            validate_output(result.to_dict())
        finally:
            wav_path.unlink()

    def test_features_values_reasonable(self):
        """特征值在合理范围内"""
        wav_path = make_wav_file(duration_sec=1.0)
        try:
            p = FeaturesParser()
            result = p.parse(wav_path)
            f = result.features
            assert 0.5 <= f.duration <= 2.0
            assert f.sample_rate > 0
            # tempo 可能为 0（纯正弦波无节拍）
            assert f.tempo >= 0
            assert f.loudness >= 0
            assert f.spectral_centroid >= 0
            assert 0 <= f.zero_crossing_rate <= 1
        finally:
            wav_path.unlink()


# ============================================================================
# SpeechParser 测试（轻量级，不实际加载 Whisper 模型）
# ============================================================================

class TestSpeechParser:
    """SpeechParser 单元测试"""

    def test_name_and_formats(self):
        p = SpeechParser()
        assert p.name == "speech"
        assert "mp3" in p.supported_formats
        assert "wav" in p.supported_formats
        assert "flac" in p.supported_formats

    def test_can_parse(self):
        p = SpeechParser()
        assert p.can_parse(Path("test.mp3"))
        assert p.can_parse(Path("test.m4a"))
        assert not p.can_parse(Path("test.xyz"))

    def test_parse_nonexistent(self):
        """文件不存在"""
        p = SpeechParser()
        result = p.parse(Path("/nonexistent.mp3"))
        assert result.success is False


# ============================================================================
# 解析器对比测试
# ============================================================================

class TestParserConsistency:
    """不同解析器对同一文件的输出一致性"""

    def test_metadata_and_features_same_source(self):
        """metadata 和 features 解析同一文件，source 应一致"""
        wav_path = make_wav_file()
        try:
            m = MetadataParser().parse(wav_path)
            f = FeaturesParser().parse(wav_path)
            assert m.source == f.source
            assert m.type == f.type == "audio"
            assert m.format == f.format == "wav"
        finally:
            wav_path.unlink()

    def test_all_parsers_contract_compliant(self):
        """所有解析器输出都符合契约"""
        wav_path = make_wav_file()
        try:
            for parser_cls in [MetadataParser, FeaturesParser]:
                parser = parser_cls()
                result = parser.parse(wav_path)
                d = result.to_dict()
                validate_output(d)
        finally:
            wav_path.unlink()
