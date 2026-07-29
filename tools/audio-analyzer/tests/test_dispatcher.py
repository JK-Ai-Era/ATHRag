"""调度器测试"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.dispatcher import AudioDispatcher


# ============================================================================
# 调度器测试
# ============================================================================

class TestAudioDispatcher:
    """AudioDispatcher 调度器测试"""

    def test_init(self):
        """初始化"""
        dispatcher = AudioDispatcher()
        assert "metadata" in dispatcher.parsers
        assert "features" in dispatcher.parsers
        assert "speech" in dispatcher.parsers

    def test_list_formats(self):
        """列出格式"""
        dispatcher = AudioDispatcher()
        formats = dispatcher.list_formats()
        assert "metadata" in formats
        assert "mp3" in formats["metadata"]["formats"]
        assert "wav" in formats["speech"]["formats"]

    def test_list_parsers(self):
        """列出解析器"""
        dispatcher = AudioDispatcher()
        parsers = dispatcher.list_parsers()
        assert len(parsers) >= 3
        names = [p["name"] for p in parsers]
        assert "metadata" in names
        assert "features" in names
        assert "speech" in names

    def test_file_not_found(self):
        """文件不存在"""
        dispatcher = AudioDispatcher()
        result = dispatcher.dispatch(Path("/nonexistent.mp3"))
        assert result.success is False
        assert "文件不存在" in result.error

    def test_unknown_parser(self):
        """未知解析器"""
        dispatcher = AudioDispatcher()
        # 创建临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"fake audio")
            temp_path = Path(f.name)

        try:
            result = dispatcher.dispatch(temp_path, parser="nonexistent")
            assert result.success is False
            assert "未知解析器" in result.error
        finally:
            temp_path.unlink()

    def test_unsupported_format(self):
        """不支持的格式"""
        dispatcher = AudioDispatcher()
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            f.write(b"fake audio")
            temp_path = Path(f.name)

        try:
            result = dispatcher.dispatch(temp_path)
            assert result.success is False
            assert "没有能处理" in result.error
        finally:
            temp_path.unlink()


# ============================================================================
# 解析器注册测试
# ============================================================================

class TestParserRegistry:
    """解析器注册表测试"""

    def test_metadata_parser_registered(self):
        """元数据解析器已注册"""
        from src.parsers import PARSERS
        assert "metadata" in PARSERS
        assert PARSERS["metadata"].name == "metadata"

    def test_features_parser_registered(self):
        """特征解析器已注册"""
        from src.parsers import PARSERS
        assert "features" in PARSERS
        assert PARSERS["features"].name == "features"

    def test_speech_parser_registered(self):
        """语音解析器已注册"""
        from src.parsers import PARSERS
        assert "speech" in PARSERS
        assert PARSERS["speech"].name == "speech"

    def test_metadata_supports_formats(self):
        """元数据解析器支持格式"""
        from src.parsers import PARSERS
        parser = PARSERS["metadata"]
        assert "mp3" in parser.supported_formats
        assert "wav" in parser.supported_formats
        assert "flac" in parser.supported_formats

    def test_speech_supports_formats(self):
        """语音解析器支持格式"""
        from src.parsers import PARSERS
        parser = PARSERS["speech"]
        assert "mp3" in parser.supported_formats
        assert "wav" in parser.supported_formats


# ============================================================================
# 契约合规测试
# ============================================================================

class TestDispatcherContractCompliance:
    """调度器契约合规测试"""

    def test_metadata_parser_contract(self):
        """元数据解析器输出符合契约"""
        from src.parsers import PARSERS
        from src.contract import validate_output

        parser = PARSERS["metadata"]

        # 创建临时音频文件
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            # 写入最小 MP3 文件头
            f.write(b'\xff\xfb\x90\x00' * 100)
            temp_path = Path(f.name)

        try:
            result = parser.parse(temp_path)
            # 即使解析失败，也要符合契约结构
            d = result.to_dict()
            assert "source" in d
            assert "type" in d
            assert d["type"] == "audio"
            assert "format" in d
            assert "content" in d
            assert "metadata" in d
        finally:
            temp_path.unlink()

    def test_features_parser_contract(self):
        """特征解析器输出符合契约"""
        from src.parsers import PARSERS
        parser = PARSERS["features"]

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            # 写入最小 WAV 文件头
            f.write(b'RIFF' + b'\x00' * 4 + b'WAVE' + b'\x00' * 100)
            temp_path = Path(f.name)

        try:
            result = parser.parse(temp_path)
            d = result.to_dict()
            assert d["type"] == "audio"
            assert "format" in d
        finally:
            temp_path.unlink()
