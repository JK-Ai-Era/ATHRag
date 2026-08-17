"""解析队列 Worker — 从 parse_queue 消费任务，调 CLI 解析器

职责：
1. 轮询 parse_queue 表获取 pending 任务
2. 调用 ParseDispatcher（CLI 解析器）
3. 将解析结果喂给 DocumentService 完成后续处理（分块、向量化、索引）
4. 更新任务状态（done / failed / retry）

崩溃恢复：
- 主线程定期检查 worker 线程健康状态，死了自动重启
- 启动时清理 stale running 任务（死 worker 残留）
- 每个任务处理前更新心跳时间戳
"""

import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text as sql_text

from src.core.parse_dispatcher import ParseDispatcher
from src.rag_api.config import get_settings
from src.rag_api.models.database import (
    ParseQueue,
    Project,
    get_db_session_sync,
)

settings = get_settings()
logger = logging.getLogger(__name__)

# 任务处理超时（秒）：超过此时间认为任务卡死
TASK_TIMEOUT_SECONDS = get_settings().WORKER_TASK_TIMEOUT
# 健康检查间隔（秒）
HEALTH_CHECK_INTERVAL = 30


class ParseWorker:
    """解析队列 Worker

    从 parse_queue 表取任务 → 调 CLI 解析器 → 喂 DocumentService

    支持：
    - 原子任务领取（UPDATE...RETURNING）
    - 任务级超时检测
    - worker 线程崩溃自动重启
    - 启动时清理 stale 任务
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        poll_interval: Optional[float] = None,
        batch_size: Optional[int] = None,
    ):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.poll_interval = poll_interval or settings.WORKER_POLL_INTERVAL
        self.batch_size = batch_size or settings.WORKER_BATCH_SIZE
        self.dispatcher = ParseDispatcher()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._health_thread: Optional[threading.Thread] = None
        self._last_heartbeat: float = 0  # worker 线程最后心跳时间
        self._restart_count = 0

    def start(self):
        """启动 Worker 线程 + 健康监控"""
        if self._running:
            logger.warning(f"Worker {self.worker_id} 已在运行")
            return

        self._cleanup_stale_tasks()
        self._running = True
        self._start_worker_thread()
        self._start_health_thread()
        logger.info(f"ParseWorker {self.worker_id} 已启动（含健康监控）")

    def _start_worker_thread(self):
        """启动 worker 工作线程"""
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"parse-worker-{self.worker_id}",
            daemon=True,
        )
        self._thread.start()

    def _start_health_thread(self):
        """启动健康监控线程"""
        self._health_thread = threading.Thread(
            target=self._health_loop,
            name=f"health-{self.worker_id}",
            daemon=True,
        )
        self._health_thread.start()

    def stop(self):
        """停止 Worker"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        if self._health_thread:
            self._health_thread.join(timeout=5)
        logger.info(f"ParseWorker {self.worker_id} 已停止")

    # ── 主循环 ──────────────────────────────────────────────

    def _run_loop(self):
        """主循环 — 捕获所有异常，保证线程不意外退出"""
        while self._running:
            try:
                self._last_heartbeat = time.monotonic()
                processed = self._process_batch()
                if processed == 0:
                    time.sleep(self.poll_interval)
                self._last_heartbeat = time.monotonic()
            except Exception as e:
                logger.error(f"[{self.worker_id}] Worker 循环异常: {e}", exc_info=True)
                time.sleep(self.poll_interval)
            except BaseException as e:
                # 捕获 SystemExit / KeyboardInterrupt 等，记录后退出
                logger.critical(f"[{self.worker_id}] Worker 致命异常: {type(e).__name__}: {e}")
                break

        logger.warning(f"[{self.worker_id}] Worker 主循环已退出")

    # ── 健康监控 ─────────────────────────────────────────────

    def _health_loop(self):
        """健康监控循环 — 检测 worker 线程是否存活"""
        while self._running:
            try:
                time.sleep(HEALTH_CHECK_INTERVAL)
                if not self._running:
                    break

                # 检查 worker 线程是否还活着
                if self._thread is None or not self._thread.is_alive():
                    self._restart_count += 1
                    logger.warning(
                        f"[{self.worker_id}] Worker 线程已死，第 {self._restart_count} 次自动重启"
                    )
                    # 重置 stale 任务
                    self._cleanup_stale_tasks()
                    # 重启 worker 线程
                    self._start_worker_thread()

                # 检查心跳超时（线程活着但卡住了）
                elif self._last_heartbeat > 0:
                    elapsed = time.monotonic() - self._last_heartbeat
                    if elapsed > TASK_TIMEOUT_SECONDS * 2:
                        logger.warning(
                            f"[{self.worker_id}] Worker 心跳超时 ({elapsed:.0f}s)，"
                            f"可能存在卡死任务"
                        )
                        # 清理超时任务
                        self._cleanup_stale_tasks()

            except Exception as e:
                logger.error(f"[{self.worker_id}] 健康检查异常: {e}")

    # ── Stale 任务清理 ───────────────────────────────────────

    def _cleanup_stale_tasks(self, stale_minutes: int = 10):
        """清理超过指定时间的 running 任务（死 worker 残留）"""
        try:
            db = get_db_session_sync()
            try:
                cutoff = (
                    datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
                ).strftime("%Y-%m-%dT%H:%M:%S")
                result = db.execute(
                    sql_text(
                        """UPDATE parse_queue SET status='pending', worker_id=NULL,
                           started_at=NULL, error_msg='stale task reset'
                           WHERE status='running' AND started_at < :cutoff"""
                    ),
                    {"cutoff": cutoff},
                )
                if result.rowcount > 0:
                    logger.info(
                        f"[{self.worker_id}] 清理 {result.rowcount} 个 stale running 任务"
                        f"（>{stale_minutes}分钟）"
                    )
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[{self.worker_id}] 清理 stale 任务失败: {e}")

    # ── 批量处理 ─────────────────────────────────────────────

    def _process_batch(self) -> int:
        """处理一批任务，返回处理数量"""
        # 原子领取：UPDATE...RETURNING（单条 SQL，SQLite 保证原子性）
        db = get_db_session_sync()
        try:
            result = db.execute(
                sql_text(
                    """
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
                    """
                ),
                {
                    "worker_id": self.worker_id,
                    "started_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    ),
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

        # 并行处理多个任务（用线程池，让 Ollama 持续满载）
        import concurrent.futures
        processed = 0

        def _run_task(tid: str) -> bool:
            try:
                self._process_single_task(tid)
                return True
            except Exception as e:
                logger.error(f"[{self.worker_id}] 任务处理异常 {tid}: {e}")
                self._mark_task_failed(tid, str(e))
                return False

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(task_ids)
        ) as executor:
            futures = {executor.submit(_run_task, tid): tid for tid in task_ids}
            for future in concurrent.futures.as_completed(futures):
                if not self._running:
                    break
                if future.result():
                    processed += 1

        return processed

    # ── 单任务处理 ───────────────────────────────────────────

    def _process_single_task(self, task_id: str):
        """处理单个任务"""
        db = get_db_session_sync()
        try:
            task = db.query(ParseQueue).filter(ParseQueue.id == task_id).first()
            if not task:
                return

            file_path = Path(task.file_path)
            project_id = task.project_id

            # 计算文件哈希（去重检查）
            file_hash = self._compute_hash(file_path)
            if not file_path.exists():
                task.status = "skipped"
                task.error_msg = "文件已不存在"
                task.finished_at = datetime.now(timezone.utc)
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
                task.finished_at = datetime.now(timezone.utc)
                db.commit()
                return
        finally:
            db.close()

        # 调 CLI 解析器（session 已关闭，用局部变量）
        logger.info(f"[{self.worker_id}] 解析: {file_path.name}")
        self._last_heartbeat = time.monotonic()
        parse_result = self.dispatcher.dispatch(file_path)
        self._last_heartbeat = time.monotonic()

        # 用解析结果走 DocumentService pipeline
        self._feed_to_document_service(
            parse_result=parse_result,
            project_id=project_id,
            task_id=task_id,
        )

    # ── DocumentService pipeline ─────────────────────────────

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

        # 从 parse_queue 获取 project_id
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

        # 调 DocumentService
        self._last_heartbeat = time.monotonic()
        doc_service = DocumentService()
        result = doc_service.process_document(
            file_path=dest_path,
            doc_type=doc_type,
            project_id=actual_project_id,
            filename=source.name,
            source_path=str(source),
            metadata=metadata,
        )
        self._last_heartbeat = time.monotonic()

        # 更新任务状态
        db = get_db_session_sync()
        try:
            task = db.query(ParseQueue).filter(ParseQueue.id == task_id).first()
            if task:
                if result.success:
                    task.status = "done"
                    task.result_json = json.dumps(
                        {
                            "document_id": result.document_id,
                            "chunk_count": result.chunk_count,
                            "vector_count": result.vector_count,
                        },
                        ensure_ascii=False,
                    )
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
                task.finished_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    # ── 任务失败处理 ─────────────────────────────────────────

    def _mark_task_failed(self, task_id: str, error_msg: str):
        """标记任务失败，支持重试"""
        db = get_db_session_sync()
        try:
            task = db.query(ParseQueue).filter(ParseQueue.id == task_id).first()
            if not task:
                return

            task.retry_count += 1
            if task.retry_count < task.max_retries:
                task.status = "pending"
                task.worker_id = None
                task.started_at = None
                task.error_msg = (
                    f"重试 {task.retry_count}/{task.max_retries}: {error_msg}"
                )
                logger.warning(
                    f"[{self.worker_id}] 任务 {task_id} 将重试 "
                    f"({task.retry_count}/{task.max_retries})"
                )
            else:
                task.status = "failed"
                task.error_msg = error_msg
                task.finished_at = datetime.now(timezone.utc)
                logger.error(
                    f"[{self.worker_id}] 任务 {task_id} 最终失败: {error_msg}"
                )

            db.commit()
        finally:
            db.close()

    # ── 工具方法 ─────────────────────────────────────────────

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
        """将文件加入解析队列"""
        file_path = Path(file_path).resolve()

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
            if not file_hash:
                file_hash = hashlib.sha256(
                    f"{file_path}:{time.time()}".encode()
                ).hexdigest()

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
