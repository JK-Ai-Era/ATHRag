"""契约测试 — 验证解析器输出符合标准化契约"""

import json
import tempfile
from pathlib import Path

import pytest

from src.contract import (
    ParseResult,
    SemanticInfo,
    ChunkInfo,
    error_result,
    validate_output,
    validate_and_parse,
    ContractViolation,
)


class TestParseResult:
    """ParseResult 数据结构测试"""

    def test_minimal_result(self):
        """最小合法结果"""
        r = ParseResult(
            source="/tmp/test.pdf",
            type="document",
            format="pdf",
            content="hello world",
            metadata={"filename": "test.pdf"},
        )
        d = r.to_dict()
        assert d["source"] == "/tmp/test.pdf"
        assert d["type"] == "document"
        assert d["format"] == "pdf"
        assert d["content"] == "hello world"
        assert d["success"] is True
        assert "error" not in d

    def test_result_with_semantic(self):
        """带语义增强的结果"""
        r = ParseResult(
            source="/tmp/test.pdf",
            type="document",
            format="pdf",
            content="hello",
            metadata={},
            semantic=SemanticInfo(
                summary="摘要",
                keywords=["关键词1", "关键词2"],
                categories=["分类"],
            ),
        )
        d = r.to_dict()
        assert "semantic" in d
        assert d["semantic"]["summary"] == "摘要"
        assert len(d["semantic"]["keywords"]) == 2

    def test_result_with_chunks(self):
        """带预分块的结果"""
        r = ParseResult(
            source="/tmp/test.pdf",
            type="document",
            format="pdf",
            content="hello world",
            metadata={},
            chunks=[
                ChunkInfo(text="hello", position="page:1"),
                ChunkInfo(text="world", position="page:2"),
            ],
        )
        d = r.to_dict()
        assert "chunks" in d
        assert len(d["chunks"]) == 2
        assert d["chunks"][0]["text"] == "hello"

    def test_error_result(self):
        """错误结果"""
        r = error_result("/tmp/test.pdf", "解析失败")
        assert r.success is False
        assert r.error == "解析失败"
        assert r.content == ""

    def test_to_json(self):
        """JSON 序列化"""
        r = ParseResult(
            source="/tmp/test.pdf",
            type="document",
            format="pdf",
            content="hello",
            metadata={"key": "value"},
        )
        j = r.to_json()
        data = json.loads(j)
        assert data["source"] == "/tmp/test.pdf"

    def test_empty_semantic_not_in_output(self):
        """空的 semantic 不出现在输出中"""
        r = ParseResult(
            source="/tmp/test.pdf",
            type="document",
            format="pdf",
            content="hello",
            metadata={},
            semantic=SemanticInfo(),  # 全空
        )
        d = r.to_dict()
        assert "semantic" not in d

    def test_empty_chunks_not_in_output(self):
        """空的 chunks 不出现在输出中"""
        r = ParseResult(
            source="/tmp/test.pdf",
            type="document",
            format="pdf",
            content="hello",
            metadata={},
            chunks=[],
        )
        d = r.to_dict()
        assert "chunks" not in d


class TestValidation:
    """输出校验测试"""

    def test_valid_output(self):
        """合法输出通过校验"""
        data = {
            "source": "/tmp/test.pdf",
            "type": "document",
            "format": "pdf",
            "content": "hello",
            "metadata": {},
        }
        validate_output(data)  # 不抛异常

    def test_missing_source(self):
        """缺少 source"""
        data = {
            "type": "document",
            "format": "pdf",
            "content": "hello",
            "metadata": {},
        }
        with pytest.raises(ContractViolation, match="source"):
            validate_output(data)

    def test_missing_content(self):
        """缺少 content"""
        data = {
            "source": "/tmp/test.pdf",
            "type": "document",
            "format": "pdf",
            "metadata": {},
        }
        with pytest.raises(ContractViolation, match="content"):
            validate_output(data)

    def test_invalid_type(self):
        """无效的 type"""
        data = {
            "source": "/tmp/test.pdf",
            "type": "invalid",
            "format": "pdf",
            "content": "hello",
            "metadata": {},
        }
        with pytest.raises(ContractViolation, match="type"):
            validate_output(data)

    def test_content_not_string(self):
        """content 不是字符串"""
        data = {
            "source": "/tmp/test.pdf",
            "type": "document",
            "format": "pdf",
            "content": 123,
            "metadata": {},
        }
        with pytest.raises(ContractViolation, match="content"):
            validate_output(data)

    def test_metadata_not_dict(self):
        """metadata 不是字典"""
        data = {
            "source": "/tmp/test.pdf",
            "type": "document",
            "format": "pdf",
            "content": "hello",
            "metadata": "invalid",
        }
        with pytest.raises(ContractViolation, match="metadata"):
            validate_output(data)


class TestValidateAndParse:
    """validate_and_parse 集成测试"""

    def test_roundtrip(self):
        """ParseResult → JSON → validate_and_parse → ParseResult"""
        original = ParseResult(
            source="/tmp/test.pdf",
            type="document",
            format="pdf",
            content="hello world",
            metadata={"filename": "test.pdf", "pages": 10},
            semantic=SemanticInfo(summary="摘要", keywords=["kw1"]),
            chunks=[ChunkInfo(text="chunk1", position="p1")],
        )

        json_str = original.to_json()
        parsed = validate_and_parse(json_str)

        assert parsed.source == original.source
        assert parsed.type == original.type
        assert parsed.content == original.content
        assert parsed.semantic.summary == "摘要"
        assert len(parsed.chunks) == 1

    def test_invalid_json(self):
        """无效 JSON"""
        with pytest.raises(json.JSONDecodeError):
            validate_and_parse("not json")

    def test_missing_fields(self):
        """缺少必填字段"""
        with pytest.raises(ContractViolation):
            validate_and_parse('{"source": "/tmp/test.pdf"}')
