"""解析队列 Worker — 从 parse_queue 消费任务，调 CLI 解析器

职责：
1. 轮询 parse_queue 表获取 pending 任务
2. 调用 ParseDispatcher（CLI 解析器）
3. 将解析结果喂给 DocumentService 完成后续处理（分块、向量化、索引）
4. 更新任务状态（done / failed / retry）
"""

import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from src.core.parse_dispatcher import ParseDispatcher
from src.rag_api.config import get_settings
from src.rag_api.models.database import (
    ParseQueue,
    Project,
    get_db_session,
    get_db_session_immediate,
    get_db_session_sync,
)

settings = get_settings()
logger = logging.getLogger(__name__)


class ParseWorker:
    """解析队列 Worker

    从 parse_queue 表取任务 → 调 CLI 解析器 → 喂 DocumentService

    支持并发控制、重试机制、文件去重。
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        poll_interval: float = 2.0,
        batch_size: int = 5,
    ):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.dispatcher = ParseDispatcher()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """启动 Worker 线程"""
        if self._running:
            logger.warning(f"Worker {self.worker_id} 已在运行")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"parse-worker-{self.worker_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"ParseWorker {self.worker_id} 已启动")

    def stop(self):
        """停止 Worker"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info(f"ParseWorker {self.worker_id} 已停止")

    def _run_loop(self):
        """主循环"""
        while self._running:
            try:
                processed = self._process_batch()
                if processed == 0:
                    time.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Worker 循环异常: {e}")
                time.sleep(self.poll_interval)

    def _process_batch(self) -> int:
        """处理一批任务，返回处理数量"""
        from sqlalchemy import text as sql_text

        # 原子领取：UPDATE...RETURNING（单条 SQL，SQLite 保证原子性）
        db = get_db_session_sync()
        try:
            result = db.execute(
                sql_text("""
                    UPDATE parse_queue
                    SET status = 'running',
                        worker_id = :worker_id,
                        started_at = :started_at
                    WHERE id IN (
                        SELECT id FROM parse_queue
                        WHERE status = 'pending'
                        ORDER BY priority ASC, created_at ASC
                        LIMIT :batch_size
                    )
                """),
                {
                    "worker_id": self.worker_id,
                    "started_at": datetime.utcnow().isoformat(),
                    "batch_size": self.batch_size,
                },
            )
            claimed = result.rowcount
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        if claimed == 0:
            return 0

        # 读取刚领取的任务
        db = get_db_session_sync()
        try:
            tasks = (
                db.query(ParseQueue)
                .filter(
                    ParseQueue.worker_id == self.worker_id,
                    ParseQueue.status == "running",
                )
                .all()
            )
            task_ids = [t.id for t in tasks]
        finally:
            db.close()

        # 逐个处理
        processed = 0
        for task_id in task_ids:
            try:
                self._process_single_task(task_id)
                processed += 1
            except Exception as e:
                logger.error(f"任务处理异常 {task_id}: {e}")
                self._mark_task_failed(task_id, str(e))

        return processed

    def _process_single_task(self, task_id: str):
        """处理单个任务"""
        db = get_db_session_sync()
        try:
            task = db.query(ParseQueue).filter(ParseQueue.id == task_id).first()
            if not task:
                return

            file_path = Path(task.file_path)
            project_id = task.project_id  # 提取到局部变量，避免 detached 访问

            # 计算文件哈希（去重检查）
            file_hash = self._compute_hash(file_path)
            if not file_path.exists():
                task.status = "skipped"
                task.error_msg = "文件已不存在"
                task.finished_at = datetime.utcnow()
                db.commit()
                return

            # 去重：检查同文件同项目是否已有 done 的任务
            existing = (
                db.query(ParseQueue)
                .filter(
                    ParseQueue.file_hash == file_hash,
                    ParseQueue.project_id == project_id,
                    ParseQueue.status == "done",
                    ParseQueue.id != task.id,
                )
                .first()
            )
            if existing:
                task.status = "skipped"
                task.error_msg = "重复任务（已有完成记录）"
                task.finished_at = datetime.utcnow()
                db.commit()
                return
        finally:
            db.close()

        # 调 CLI 解析器（session 已关闭，用局部变量）
        logger.info(f"[{self.worker_id}] 解析: {file_path.name}")
        parse_result = self.dispatcher.dispatch(file_path)

        # 用解析结果走 DocumentService pipeline
        self._feed_to_document_service(
            parse_result=parse_result,
            project_id=project_id,
            task_id=task_id,
        )

    def _feed_to_document_service(
        self,
        parse_result: dict,
        project_id: str,
        task_id: str,
    ):
        """将解析结果喂给 DocumentService"""
        from src.services.document_service import DocumentService

        content = parse_result.get("content", "")
        if not content:
            self._mark_task_failed(task_id, "解析结果 content 为空")
            return

        source_path = parse_result.get("source", "")
        metadata = parse_result.get("metadata", {})
        file_type = parse_result.get("type", "document")
        file_format = parse_result.get("format", "unknown")

        doc_type_map = {
            "document": file_format,
            "audio": "audio",
            "image": "image",
        }
        doc_type = doc_type_map.get(file_type, file_format)

        # 从 parse_queue 获取 project_id（短事务）
        db = get_db_session_sync()
        try:
            task = db.query(ParseQueue).filter(ParseQueue.id == task_id).first()
            if not task:
                return
            actual_project_id = task.project_id or project_id
        finally:
            db.close()

        # 复制文件到项目目录
        source = Path(source_path)
        project_dir = settings.PROJECTS_DIR / actual_project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        dest_path = project_dir / source.name
        if dest_path.exists() and dest_path.resolve() != source.resolve():
            file_hash = self._compute_hash(source)[:8]
            dest_path = project_dir / f"{file_hash}_{source.name}"

        if not dest_path.exists() and source.exists():
            import shutil
            shutil.copy2(source, dest_path)

        # 调 DocumentService（内部自管理事务）
        doc_service = DocumentService()
        result = doc_service.process_document(
            file_path=dest_path,
            doc_type=doc_type,
            project_id=actual_project_id,
            filename=source.name,
            source_path=str(source),
            metadata=metadata,
        )

        # 更新任务状态（短事务）
        db = get_db_session_sync()
        try:
            task = db.query(ParseQueue).filter(ParseQueue.id == task_id).first()
            if task:
                if result.success:
                    task.status = "done"
                    task.result_json = json.dumps({
                        "document_id": result.document_id,
                        "chunk_count": result.chunk_count,
                        "vector_count": result.vector_count,
                    }, ensure_ascii=False)
                    logger.info(
                        f"[{self.worker_id}] 完成: {source.name} → "
                        f"{result.chunk_count} chunks, "
                        f"{result.vector_count} vectors"
                    )
                else:
                    task.status = "failed"
                    task.error_msg = result.error_message
                    logger.error(
                        f"[{self.worker_id}] 处理失败: {source.name}: "
                        f"{result.error_message}"
                    )
                task.finished_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

    def _mark_task_failed(self, task_id: str, error_msg: str):
        """标记任务失败，支持重试"""
        db = get_db_session_sync()
        try:
            task = db.query(ParseQueue).filter(ParseQueue.id == task_id).first()
            if not task:
                return

            task.retry_count += 1
            if task.retry_count < task.max_retries:
                # 重试：状态改回 pending
                task.status = "pending"
                task.worker_id = None
                task.started_at = None
                task.error_msg = f"重试 {task.retry_count}/{task.max_retries}: {error_msg}"
                logger.warning(f"任务 {task_id} 将重试 ({task.retry_count}/{task.max_retries})")
            else:
                # 超过重试次数，标记为 failed
                task.status = "failed"
                task.error_msg = error_msg
                task.finished_at = datetime.utcnow()
                logger.error(f"任务 {task_id} 最终失败: {error_msg}")

            db.commit()
        finally:
            db.close()

    @staticmethod
    def _compute_hash(file_path: Path) -> str:
        """计算文件 SHA256 哈希"""
        try:
            h = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    @staticmethod
    def enqueue(
        file_path: Path,
        project_id: str,
        file_type: str = "document",
        priority: int = 0,
    ) -> str:
        """将文件加入解析队列

        Args:
            file_path: 文件路径
            project_id: 项目 ID
            file_type: 文件类型（document / audio / image / code）
            priority: 优先级（越小越优先）

        Returns:
            任务 ID
        """
        file_path = Path(file_path).resolve()

        # 计算哈希
        h = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            file_hash = h.hexdigest()
        except Exception:
            file_hash = ""

        db = get_db_session_sync()
        try:
            # 空哈希（文件不存在）用文件路径+时间戳作为哈希
            if not file_hash:
                import time
                file_hash = hashlib.sha256(f"{file_path}:{time.time()}".encode()).hexdigest()

            # 去重：检查是否已有 pending 或 running 的同文件任务
            existing = (
                db.query(ParseQueue)
                .filter(
                    ParseQueue.file_hash == file_hash,
                    ParseQueue.project_id == project_id,
                    ParseQueue.status.in_(["pending", "running"]),
                )
                .first()
            )
            if existing:
                logger.debug(f"文件已在队列中: {file_path.name} (task={existing.id})")
                return existing.id

            task = ParseQueue(
                file_path=str(file_path),
                file_hash=file_hash,
                file_type=file_type,
                project_id=project_id,
                priority=priority,
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            logger.info(f"入队: {file_path.name} → task={task.id}")
            return task.id
        finally:
            db.close()
