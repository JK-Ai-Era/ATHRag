"""契约测试 — 验证 ParseResult 输出符合标准化契约"""

import json
import pytest
from pathlib import Path

from src.contract import (
    ParseResult, SemanticInfo, ChunkInfo, AudioSegment, AudioFeatures,
    error_result, validate_output, validate_and_parse, ContractViolation,
)


# ============================================================================
# 数据结构测试
# ============================================================================

class TestParseResult:
    """ParseResult 数据结构测试"""

    def test_basic_creation(self):
        """基本创建"""
        result = ParseResult(
            source="/test.mp3",
            type="audio",
            format="mp3",
            content="测试内容",
            metadata={"duration": 120.0},
        )
        assert result.source == "/test.mp3"
        assert result.type == "audio"
        assert result.success is True

    def test_to_dict(self):
        """转字典"""
        result = ParseResult(
            source="/test.mp3",
            type="audio",
            format="mp3",
            content="测试",
            metadata={"duration": 60.0},
        )
        d = result.to_dict()
        assert d["source"] == "/test.mp3"
        assert d["type"] == "audio"
        assert "error" not in d  # 空值不包含

    def test_to_json(self):
        """序列化为 JSON"""
        result = ParseResult(
            source="/test.mp3",
            type="audio",
            format="mp3",
            content="测试",
            metadata={},
        )
        j = result.to_json()
        data = json.loads(j)
        assert data["source"] == "/test.mp3"

    def test_with_segments(self):
        """包含音频片段"""
        segments = [
            AudioSegment(start=0.0, end=5.0, text="Hello", label="speech"),
            AudioSegment(start=5.0, end=10.0, text="World", label="speech"),
        ]
        result = ParseResult(
            source="/test.mp3",
            type="audio",
            format="mp3",
            content="Hello World",
            metadata={},
            segments=segments,
        )
        d = result.to_dict()
        assert len(d["segments"]) == 2
        assert d["segments"][0]["text"] == "Hello"

    def test_with_features(self):
        """包含音频特征"""
        features = AudioFeatures(
            duration=120.0,
            sample_rate=44100,
            channels=2,
            format="mp3",
            tempo=120.0,
            key="C",
            loudness=0.5,
            spectral_centroid=2000.0,
            zero_crossing_rate=0.05,
        )
        result = ParseResult(
            source="/test.mp3",
            type="audio",
            format="mp3",
            content="音频文件: test.mp3",
            metadata={},
            features=features,
        )
        d = result.to_dict()
        assert d["features"]["tempo"] == 120.0
        assert d["features"]["key"] == "C"

    def test_with_semantic(self):
        """包含语义信息"""
        semantic = SemanticInfo(
            summary="这是一首快节奏的音乐",
            keywords=["快节奏", "流行"],
            categories=["音乐"],
        )
        result = ParseResult(
            source="/test.mp3",
            type="audio",
            format="mp3",
            content="测试",
            metadata={},
            semantic=semantic,
        )
        d = result.to_dict()
        assert d["semantic"]["summary"] == "这是一首快节奏的音乐"
        assert len(d["semantic"]["keywords"]) == 2

    def test_error_result(self):
        """错误结果构造"""
        result = error_result("/test.mp3", "文件不存在", "mp3")
        assert result.success is False
        assert result.error == "文件不存在"
        assert result.type == "audio"


# ============================================================================
# 校验函数测试
# ============================================================================

class TestValidateOutput:
    """validate_output 测试"""

    def test_valid_output(self):
        """合法输出通过校验"""
        data = {
            "source": "/test.mp3",
            "type": "audio",
            "format": "mp3",
            "content": "测试内容",
            "metadata": {"duration": 60.0},
        }
        validate_output(data)  # 不抛异常

    def test_missing_field(self):
        """缺少必填字段"""
        data = {
            "source": "/test.mp3",
            "type": "audio",
            "format": "mp3",
            # 缺少 content
            "metadata": {},
        }
        with pytest.raises(ContractViolation, match="缺少必填字段"):
            validate_output(data)

    def test_invalid_type(self):
        """type 不是 audio"""
        data = {
            "source": "/test.mp3",
            "type": "document",  # 错误
            "format": "mp3",
            "content": "测试",
            "metadata": {},
        }
        with pytest.raises(ContractViolation, match="type 必须是"):
            validate_output(data)

    def test_content_not_string(self):
        """content 不是字符串"""
        data = {
            "source": "/test.mp3",
            "type": "audio",
            "format": "mp3",
            "content": 123,  # 错误
            "metadata": {},
        }
        with pytest.raises(ContractViolation, match="content 必须是字符串"):
            validate_output(data)

    def test_metadata_not_dict(self):
        """metadata 不是字典"""
        data = {
            "source": "/test.mp3",
            "type": "audio",
            "format": "mp3",
            "content": "测试",
            "metadata": "错误",  # 错误
        }
        with pytest.raises(ContractViolation, match="metadata 必须是字典"):
            validate_output(data)


# ============================================================================
# validate_and_parse 测试
# ============================================================================

class TestValidateAndParse:
    """validate_and_parse 测试"""

    def test_basic_parse(self):
        """基本解析"""
        data = {
            "source": "/test.mp3",
            "type": "audio",
            "format": "mp3",
            "content": "测试内容",
            "metadata": {"duration": 60.0},
        }
        result = validate_and_parse(json.dumps(data))
        assert result.source == "/test.mp3"
        assert result.type == "audio"

    def test_parse_with_segments(self):
        """解析包含片段的输出"""
        data = {
            "source": "/test.mp3",
            "type": "audio",
            "format": "mp3",
            "content": "Hello World",
            "metadata": {},
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "Hello", "label": "speech"},
            ],
        }
        result = validate_and_parse(json.dumps(data))
        assert len(result.segments) == 1
        assert result.segments[0].text == "Hello"

    def test_parse_with_features(self):
        """解析包含特征的输出"""
        data = {
            "source": "/test.mp3",
            "type": "audio",
            "format": "mp3",
            "content": "测试",
            "metadata": {},
            "features": {
                "duration": 120.0,
                "sample_rate": 44100,
                "tempo": 120.0,
                "key": "C",
            },
        }
        result = validate_and_parse(json.dumps(data))
        assert result.features is not None
        assert result.features.tempo == 120.0
