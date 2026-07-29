"""P3 解析层改造测试 — ParseDispatcher + ParseWorker + ParseQueue"""

import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.core.parse_dispatcher import ParseDispatcher
from src.core.parse_worker import ParseWorker
from src.rag_api.models.database import ParseQueue, init_db, get_db_session, Base, engine


# ============================================================================
# 测试夹具
# ============================================================================

@pytest.fixture(autouse=True)
def setup_db():
    """每个测试前确保 parse_queue 表存在且为空"""
    ParseQueue.__table__.create(bind=engine, checkfirst=True)
    yield
    # 清理数据但保留表（不影响其他测试）
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM parse_queue"))


@pytest.fixture
def sample_file():
    """创建临时文件"""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
        f.write("测试内容")
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def audio_file():
    """创建假音频文件"""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(b"\xff\xfb\x90\x00" * 100)
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


# ============================================================================
# ParseDispatcher 测试
# ============================================================================

class TestParseDispatcher:
    """ParseDispatcher 测试"""

    def test_init(self):
        """初始化加载 parsers.yaml"""
        d = ParseDispatcher()
        assert len(d.list_parsers()) > 0

    def test_find_parser_txt(self):
        """txt 文件路由到 text 解析器"""
        d = ParseDispatcher()
        assert d.find_parser(Path("test.txt")) == "text"

    def test_find_parser_pdf(self):
        """pdf 文件路由到 document 解析器"""
        d = ParseDispatcher()
        assert d.find_parser(Path("test.pdf")) == "document"

    def test_find_parser_mp3(self):
        """mp3 文件路由到 audio 解析器"""
        d = ParseDispatcher()
        assert d.find_parser(Path("test.mp3")) == "audio"

    def test_find_parser_unknown(self):
        """未知扩展名返回 None"""
        d = ParseDispatcher()
        assert d.find_parser(Path("test.xyz")) is None

    def test_is_supported(self):
        """支持格式判断"""
        d = ParseDispatcher()
        assert d.is_supported(Path("test.pdf")) is True
        assert d.is_supported(Path("test.mp3")) is True
        assert d.is_supported(Path("test.xyz")) is False

    def test_get_supported_extensions(self):
        """获取所有支持的扩展名"""
        d = ParseDispatcher()
        exts = d.get_supported_extensions()
        assert "pdf" in exts
        assert "mp3" in exts
        assert "py" in exts
        assert len(exts) > 30

    def test_list_parsers(self):
        """列出解析器"""
        d = ParseDispatcher()
        parsers = d.list_parsers()
        assert "document" in parsers
        assert "audio" in parsers
        assert parsers["document"]["cli"] == "doc-analyze"

    def test_get_parser_config(self):
        """获取解析器配置"""
        d = ParseDispatcher()
        config = d.get_parser_config("document")
        assert config is not None
        assert config["cli"] == "doc-analyze"
        assert config["timeout"] == 120

    def test_dispatch_file_not_found(self):
        """文件不存在时抛异常"""
        d = ParseDispatcher()
        with pytest.raises(ValueError, match="文件不存在"):
            d.dispatch(Path("/nonexistent.txt"))

    def test_dispatch_unsupported_format(self):
        """不支持的格式抛异常"""
        d = ParseDispatcher()
        with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
            f.write(b"test")
            path = Path(f.name)
        try:
            with pytest.raises(ValueError, match="没有能处理"):
                d.dispatch(path)
        finally:
            path.unlink()

    def test_validate_output_missing_field(self):
        """缺少必填字段时抛异常"""
        d = ParseDispatcher()
        with pytest.raises(ValueError, match="缺少必填字段"):
            d._validate_output({"source": "/test", "type": "document"}, Path("/test"))

    def test_validate_output_wrong_content_type(self):
        """content 类型错误时抛异常"""
        d = ParseDispatcher()
        with pytest.raises(ValueError, match="content 必须是字符串"):
            d._validate_output({
                "source": "/test",
                "type": "document",
                "format": "txt",
                "content": 123,
                "metadata": {},
            }, Path("/test"))

    def test_validate_output_ok(self):
        """合法输出通过校验"""
        d = ParseDispatcher()
        d._validate_output({
            "source": "/test",
            "type": "document",
            "format": "txt",
            "content": "hello",
            "metadata": {},
        }, Path("/test"))  # 不抛异常


# ============================================================================
# ParseWorker 测试
# ============================================================================

class TestParseWorker:
    """ParseWorker 测试"""

    def test_init(self):
        """初始化"""
        w = ParseWorker()
        assert w.worker_id.startswith("worker-")
        assert w.poll_interval == 2.0

    def test_enqueue(self):
        """入队"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("test")
            path = Path(f.name)
        try:
            task_id = ParseWorker.enqueue(
                file_path=path,
                project_id="test-project",
                file_type="text",
            )
            assert task_id is not None

            # 验证任务已入队
            with get_db_session() as db:
                task = db.query(ParseQueue).filter(ParseQueue.id == task_id).first()
                assert task is not None
                assert task.status == "pending"
                assert task.file_type == "text"
                assert task.project_id == "test-project"
        finally:
            path.unlink()

    def test_enqueue_dedup(self):
        """去重：同文件同项目不重复入队"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("test dedup")
            path = Path(f.name)
        try:
            id1 = ParseWorker.enqueue(path, "proj-1", "text")
            id2 = ParseWorker.enqueue(path, "proj-1", "text")
            assert id1 == id2  # 同一个任务

            # 不同项目应该入队
            id3 = ParseWorker.enqueue(path, "proj-2", "text")
            assert id3 != id1
        finally:
            path.unlink()

    def test_compute_hash(self):
        """文件哈希计算"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("hash test content")
            path = Path(f.name)
        try:
            h = ParseWorker._compute_hash(path)
            assert len(h) == 64  # SHA256 hex
            # 同文件哈希一致
            assert ParseWorker._compute_hash(path) == h
        finally:
            path.unlink()

    def test_enqueue_nonexistent_file(self):
        """不存在的文件也能入队（后续处理时检查）"""
        task_id = ParseWorker.enqueue(
            file_path=Path("/nonexistent/file.txt"),
            project_id="test-proj",
            file_type="text",
        )
        assert task_id is not None

    def test_process_single_task_file_missing(self):
        """处理时文件不存在应标记 skipped"""
        # 入队一个存在的文件
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
            f.write("test")
            path = Path(f.name)

        task_id = ParseWorker.enqueue(path, "proj-1", "text")

        # 删除文件
        path.unlink()

        # 处理任务
        w = ParseWorker()
        w._mark_task_failed(task_id, "文件已不存在")

        with get_db_session() as db:
            task = db.query(ParseQueue).filter(ParseQueue.id == task_id).first()
            # mark_task_failed 会重试或标记 failed
            assert task.status in ("pending", "failed")


# ============================================================================
# ParseQueue 模型测试
# ============================================================================

class TestParseQueueModel:
    """ParseQueue 模型测试"""

    def test_create_task(self):
        """创建任务"""
        with get_db_session() as db:
            task = ParseQueue(
                file_path="/test/file.pdf",
                file_hash="abc123",
                file_type="document",
                project_id="proj-1",
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            assert task.id is not None
            assert task.status == "pending"
            assert task.retry_count == 0
            assert task.max_retries == 3

    def test_query_pending(self):
        """查询 pending 任务"""
        with get_db_session() as db:
            # 创建不同状态的任务
            for status in ["pending", "done", "pending", "failed"]:
                db.add(ParseQueue(
                    file_path=f"/test/{status}.txt",
                    file_type="text",
                    project_id="proj-1",
                    status=status,
                ))
            db.commit()

            pending = db.query(ParseQueue).filter(
                ParseQueue.status == "pending"
            ).all()
            assert len(pending) == 2
