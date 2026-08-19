"""文档处理服务 - 统一的文档处理入口

提供文档处理的完整流程：
1. 保存文档记录 + 分块（一个事务）
2. 向量化分块（独立操作，可部分成功）
3. 更新文档状态和项目统计（一个事务）
4. BM25 + 层次化索引（尽力而为的副作用）

设计原则：
- 每个阶段使用独立的短事务，不持有长锁
- 向量化失败不回滚已保存的分块（可重试）
- 不区分"直接模式"和"队列模式"，统一为一套流程
"""

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from src.rag_api.config import get_settings
from src.rag_api.models.database import Chunk as ChunkModel
from src.rag_api.models.database import Document as DocumentModel
from src.rag_api.models.database import Project as ProjectModel
from src.rag_api.models.database import get_db_session
from src.core.chunker import TextChunker, ChunkWithMetadata
from src.core.embedding import get_embedding_service
from src.core.vector_store import get_vector_store
from src.core.bm25_index import bm25_manager
from src.core.hierarchical_index import hierarchical_index

settings = get_settings()
logger = logging.getLogger(__name__)


class DocumentProcessingResult:
    """文档处理结果"""
    
    def __init__(
        self,
        success: bool,
        document_id: Optional[str] = None,
        chunk_count: int = 0,
        vector_count: int = 0,
        error_message: Optional[str] = None
    ):
        self.success = success
        self.document_id = document_id
        self.chunk_count = chunk_count
        self.vector_count = vector_count
        self.error_message = error_message
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "document_id": self.document_id,
            "chunk_count": self.chunk_count,
            "vector_count": self.vector_count,
            "error_message": self.error_message,
        }


class DocumentService:
    """文档处理服务
    
    统一的文档处理入口，被多个模块共用：
    - ParseWorker (parse_worker.py): 异步解析队列消费
    - IngestService (ingest_service.py): API 手动上传
    - FileSync (sync.py): 文件系统自动同步
    
    事务设计：
    - Phase 1（save_doc_and_chunks）：一个事务，原子保存文档记录和所有分块
    - Phase 2（vectorize_chunks）：独立操作，逐个向量化，允许部分失败
    - Phase 3（finalize）：一个事务，更新文档状态和项目统计
    - Phase 4（side_effects）：BM25 + 层次化索引，尽力而为
    """
    
    def __init__(self):
        self.chunker = TextChunker()
        self.embedding = get_embedding_service()
        self.vector_store = get_vector_store()
    
    def process_document(
        self,
        file_path: Path,
        doc_type: str,
        project_id: str,
        document_id: Optional[str] = None,
        filename: Optional[str] = None,
        source_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DocumentProcessingResult:
        """
        处理文档的完整流程
        
        每个阶段使用独立的短事务，不持有长锁。
        
        Args:
            file_path: 文件路径（必须是已复制到项目目录的路径）
            doc_type: 文档类型 (pdf/docx/xlsx/pptx/image/md/txt/code)
            project_id: 项目ID
            document_id: 现有文档ID（重新索引时使用），None则创建新文档
            filename: 文件名，None则使用 file_path.name
            source_path: 原始文件完整路径（用于 Agent read 源文件）
            metadata: 文档元数据
            
        Returns:
            DocumentProcessingResult
        """
        actual_filename = filename or file_path.name
        
        try:
            # Phase 1: 保存文档记录 + 分块（一个事务）
            doc_id, chunk_count, old_chunk_count, is_new = self._save_doc_and_chunks(
                file_path=file_path,
                doc_type=doc_type,
                project_id=project_id,
                document_id=document_id,
                filename=actual_filename,
                source_path=source_path,
                metadata=metadata,
            )
            
            # Phase 2: 向量化（独立操作，允许部分失败）
            vector_result = self._vectorize_chunks(
                doc_id=doc_id,
                project_id=project_id,
                filename=actual_filename,
                source_path=source_path,
            )
            
            # Phase 3: 更新文档状态和项目统计（一个事务）
            self._finalize(
                doc_id=doc_id,
                project_id=project_id,
                chunk_count=chunk_count,
                old_chunk_count=old_chunk_count,
                is_new=is_new,
                vector_result=vector_result,
            )
            
            # Phase 4: 尽力而为的副作用
            self._side_effects(
                project_id=project_id,
                doc_id=doc_id,
                chunk_count=chunk_count,
                filename=actual_filename,
                vector_success=vector_result["success_count"] > 0,
            )
            
            return DocumentProcessingResult(
                success=vector_result["success_count"] > 0,
                document_id=doc_id,
                chunk_count=chunk_count,
                vector_count=vector_result["success_count"],
                error_message=vector_result.get("error_details"),
            )
            
        except Exception as e:
            logger.exception(f"处理文档失败: {actual_filename}: {e}")
            return DocumentProcessingResult(
                success=False,
                document_id=document_id,
                error_message=str(e),
            )
    
    # ========== Phase 1: 保存文档 + 分块 ==========
    
    def _save_doc_and_chunks(
        self,
        file_path: Path,
        doc_type: str,
        project_id: str,
        filename: str,
        document_id: Optional[str] = None,
        source_path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """保存文档记录和所有分块，一个事务完成。
        
        Returns:
            (doc_id, chunk_count, old_chunk_count, is_new)
        """
        from src.core.document_processor import DocumentProcessor
        
        # 提取文本 + 分块（无 DB 操作）
        processor = DocumentProcessor()
        text = processor.extract_text(file_path, doc_type)
        
        if doc_type == "code":
            language = file_path.suffix.lstrip('.')
            chunk_objects = self.chunker.chunk_code_with_symbols(
                text, file_path=str(file_path), language=language
            )
        else:
            chunk_objects = self.chunker.chunk_text_with_location(
                text, file_path=str(file_path)
            )
        
        if not chunk_objects:
            raise ValueError(f"分块结果为空: {filename}")
        
        # 一个事务：创建文档记录 + 保存所有分块
        with get_db_session() as db:
            if document_id:
                doc = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
                if not doc:
                    raise ValueError(f"文档不存在: {document_id}")
                if source_path:
                    doc.source_path = source_path
                old_chunk_count = doc.chunk_count
                is_new = False
            else:
                file_size = file_path.stat().st_size
                doc = DocumentModel(
                    id=str(uuid4()),
                    project_id=project_id,
                    filename=filename,
                    doc_type=doc_type,
                    file_size=file_size,
                    file_path=str(file_path),
                    source_path=source_path,
                    status="processing",
                    metadata_json=json.dumps(metadata) if metadata else None,
                )
                db.add(doc)
                old_chunk_count = 0
                is_new = True
            
            # 先 flush 获取 doc.id
            db.flush()
            doc_id = doc.id
            
            # 删除旧分块（重新索引时）
            if not is_new:
                old_chunks = db.query(ChunkModel).filter(
                    ChunkModel.document_id == doc_id
                ).all()
                for old_chunk in old_chunks:
                    db.delete(old_chunk)
            
            # 保存新分块
            for idx, chunk_obj in enumerate(chunk_objects):
                chunk_metadata = {
                    "start_line": chunk_obj.start_line,
                    "end_line": chunk_obj.end_line,
                    "file_path": chunk_obj.metadata.get("file_path"),
                }
                if chunk_obj.metadata.get("symbols"):
                    chunk_metadata["symbols"] = chunk_obj.metadata["symbols"]
                
                chunk = ChunkModel(
                    document_id=doc_id,
                    project_id=project_id,
                    content=chunk_obj.content,
                    chunk_index=idx,
                    vector_status="pending",
                    metadata_json=json.dumps(chunk_metadata),
                )
                db.add(chunk)
            
            # commit 保存所有数据
            db.commit()
        
        logger.info(f"[{doc_id}] 保存 {len(chunk_objects)} 个分块: {filename}")
        return doc_id, len(chunk_objects), old_chunk_count, is_new
    
    # ========== Phase 2: 向量化 ==========
    
    def _vectorize_chunks(
        self,
        doc_id: str,
        project_id: str,
        filename: str,
        source_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """向量化所有分块，独立操作，允许部分失败。
        
        每个 chunk 独立处理：嵌入 → 写入 Qdrant → 更新 vector_id。
        失败的 chunk 保留（vector_id=None），可通过后续重试修复。
        
        Returns:
            {"success_count": int, "failed_count": int, "error_details": str}
        """
        success_count = 0
        failed_count = 0
        errors = []
        
        with get_db_session() as db:
            chunks = db.query(ChunkModel).filter(
                ChunkModel.document_id == doc_id
            ).order_by(ChunkModel.chunk_index).all()
            
            # 过滤出需要向量化的 chunk
            pending_chunks = [(idx, chunk) for idx, chunk in enumerate(chunks) if not chunk.vector_id]
            skipped = len(chunks) - len(pending_chunks)
            success_count = skipped  # 已有向量的算成功
            
            if not pending_chunks:
                return {"success_count": success_count, "failed_count": 0, "error_details": None}
            
            # 批量 embedding（并发请求，大幅加速）
            texts = [chunk.content for _, chunk in pending_chunks]
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 已有事件循环，用 run_in_executor 调同步回退
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=settings.EMBED_CONCURRENCY) as executor:
                        results = list(executor.map(self.embedding.embed_text_sync, texts))
                else:
                    results = loop.run_until_complete(self.embedding.embed_batch(texts))
                    if isinstance(results, tuple):
                        results = list(results[0])
            except RuntimeError:
                # 没有事件循环，用线程池并发
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=settings.EMBED_CONCURRENCY) as executor:
                    results = list(executor.map(self.embedding.embed_text_sync, texts))
            
            # 批量写入 Qdrant
            vectors_to_write = []
            payloads_to_write = []
            chunks_to_update = []
            
            for (idx, chunk), emb in zip(pending_chunks, results):
                if emb is None:
                    failed_count += 1
                    chunk.vector_status = "failed"
                    chunk.vector_error = "embedding 返回空"
                    errors.append(f"chunk {idx}: embedding 返回空")
                    continue
                
                metadata = json.loads(chunk.metadata_json) if chunk.metadata_json else {}
                payload = {
                    "chunk_id": chunk.id,
                    "document_id": doc_id,
                    "content": chunk.content,
                    "filename": filename,
                    "source_path": source_path,
                    "start_line": metadata.get("start_line"),
                    "end_line": metadata.get("end_line"),
                    "symbols": metadata.get("symbols", []),
                }
                vectors_to_write.append(emb)
                payloads_to_write.append(payload)
                chunks_to_update.append((idx, chunk))
            
            # 批量写入向量
            if vectors_to_write:
                try:
                    vector_ids = self.vector_store.add_vectors_batch(
                        project_id=project_id,
                        vectors=vectors_to_write,
                        payloads=payloads_to_write,
                    )
                    for (idx, chunk), vid in zip(chunks_to_update, vector_ids):
                        if vid:
                            chunk.vector_id = vid
                            chunk.vector_status = "success"
                            chunk.vector_error = None
                            success_count += 1
                        else:
                            failed_count += 1
                            chunk.vector_status = "failed"
                            chunk.vector_error = "向量写入返回空 ID"
                            errors.append(f"chunk {idx}: 向量写入返回空 ID")
                except Exception as e:
                    failed_count += len(vectors_to_write)
                    for (idx, chunk) in chunks_to_update:
                        chunk.vector_status = "failed"
                        chunk.vector_error = str(e)[:200]
                    errors.append(f"批量向量写入失败: {str(e)[:80]}")
            
            # 批量 commit 所有 vector_id 更新
            db.commit()
        
        error_details = None
        if errors:
            if len(errors) <= 5:
                error_details = "; ".join(errors)
            else:
                error_details = "; ".join(errors[:3]) + f"; ... 共 {len(errors)} 个错误"
        
        logger.info(f"[{doc_id}] 向量化完成: {success_count} 成功, {failed_count} 失败")
        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "error_details": error_details,
        }
    
    # ========== Phase 3: 更新状态 ==========
    
    def _finalize(
        self,
        doc_id: str,
        project_id: str,
        chunk_count: int,
        old_chunk_count: int,
        is_new: bool,
        vector_result: Dict[str, Any],
    ) -> None:
        """更新文档状态和项目统计，一个事务完成。"""
        from sqlalchemy import text as sql_text
        with get_db_session() as db:
            doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
            if doc:
                doc.chunk_count = chunk_count
                doc.status = "completed" if vector_result["success_count"] > 0 else "failed"
                if vector_result.get("error_details"):
                    doc.error_message = vector_result["error_details"]
            
            # 用原子 SQL 增量更新计数器，避免多 worker 并发丢失更新
            if is_new:
                db.execute(
                    sql_text("UPDATE projects SET document_count = document_count + 1, chunk_count = chunk_count + :cnt WHERE id = :pid"),
                    {"cnt": chunk_count, "pid": project_id},
                )
            else:
                db.execute(
                    sql_text("UPDATE projects SET chunk_count = chunk_count - :old + :new WHERE id = :pid"),
                    {"old": old_chunk_count, "new": chunk_count, "pid": project_id},
                )
            
            db.commit()
    
    # ========== Phase 4: 副作用 ==========
    
    def _side_effects(
        self,
        project_id: str,
        doc_id: str,
        chunk_count: int,
        filename: str,
        vector_success: bool,
    ) -> None:
        """尽力而为的副作用：BM25 索引 + 层次化索引。"""
        # BM25 索引
        try:
            with get_db_session() as db:
                chunks = db.query(ChunkModel).filter(
                    ChunkModel.document_id == doc_id
                ).all()
                
                bm25_index = bm25_manager.get_index(project_id)
                for chunk in chunks:
                    bm25_index.add_document(chunk.id, chunk.content)
                bm25_index.save()
                
                logger.debug(f"[{doc_id}] BM25 索引已更新: {len(chunks)} 个文档")
        except Exception as e:
            logger.warning(f"[{doc_id}] BM25 索引更新失败: {e}")
        
        # 层次化索引
        if vector_success:
            try:
                with get_db_session() as db:
                    chunk_contents = [c.content for c in db.query(ChunkModel).filter(
                        ChunkModel.document_id == doc_id
                    ).all()]
                
                hierarchical_index.index_document_sync(
                    project_id=project_id,
                    document_id=doc_id,
                    chunks=chunk_contents,
                    filename=filename,
                )
            except Exception as e:
                logger.warning(f"[{doc_id}] 层次化索引失败: {e}")
    
    # ========== 批量处理 pending chunks ==========
    
    def batch_vectorize_pending(
        self,
        project_id: str,
        batch_size: int = 200,
        max_chunks: int = 10000,
    ) -> Dict[str, Any]:
        """批量向量化所有 pending 状态的 chunks。
        
        用于恢复因崩溃等原因卡在 pending 状态的 chunks。
        
        Args:
            project_id: 项目 ID
            batch_size: 每批处理的 chunk 数量
            max_chunks: 最多处理的 chunk 总数
            
        Returns:
            {"processed": int, "success": int, "failed": int, "remaining": int}
        """
        total_success = 0
        total_failed = 0
        total_processed = 0
        
        while total_processed < max_chunks:
            with get_db_session() as db:
                # 获取一批 pending chunks
                pending_rows = db.query(ChunkModel).filter(
                    ChunkModel.project_id == project_id,
                    ChunkModel.vector_status == "pending",
                ).order_by(ChunkModel.created_at).limit(batch_size).all()
                
                if not pending_rows:
                    break
                
                # 获取关联的文档信息
                doc_ids = set(c.document_id for c in pending_rows)
                doc_info = {}
                for doc_id in doc_ids:
                    doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
                    if doc:
                        doc_info[doc_id] = {
                            "filename": doc.filename,
                            "source_path": doc.source_path,
                        }
                
                # 在 session 内提取为纯 Python 对象，避免 detached ORM 访问
                pending = []
                for c in pending_rows:
                    pending.append({
                        "id": c.id,
                        "document_id": c.document_id,
                        "content": c.content,
                        "metadata_json": c.metadata_json,
                    })
                
                texts = [c["content"] for c in pending]
            
            # 批量 embedding
            import asyncio
            import concurrent.futures
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    with concurrent.futures.ThreadPoolExecutor(max_workers=settings.EMBED_CONCURRENCY) as executor:
                        embeddings = list(executor.map(self.embedding.embed_text_sync, texts))
                else:
                    embeddings = loop.run_until_complete(self.embedding.embed_batch(texts))
                    if isinstance(embeddings, tuple):
                        embeddings = list(embeddings[0])
            except RuntimeError:
                with concurrent.futures.ThreadPoolExecutor(max_workers=settings.EMBED_CONCURRENCY) as executor:
                    embeddings = list(executor.map(self.embedding.embed_text_sync, texts))
            
            # 收集需要写入的向量（分离 embedding 失败的 chunk）
            vectors_to_write = []
            payloads_to_write = []
            chunks_to_update = []  # 只存成功 embedding 的 chunk
            failed_chunk_ids = []
            
            for chunk, emb in zip(pending, embeddings):
                if emb is None:
                    total_failed += 1
                    failed_chunk_ids.append(chunk["id"])
                    continue
                
                doc = doc_info.get(chunk["document_id"])
                metadata = json.loads(chunk["metadata_json"]) if chunk["metadata_json"] else {}
                payload = {
                    "chunk_id": chunk["id"],
                    "document_id": chunk["document_id"],
                    "content": chunk["content"],
                    "filename": doc["filename"] if doc else "",
                    "source_path": doc["source_path"] if doc else None,
                    "start_line": metadata.get("start_line"),
                    "end_line": metadata.get("end_line"),
                    "symbols": metadata.get("symbols", []),
                }
                vectors_to_write.append(emb)
                payloads_to_write.append(payload)
                chunks_to_update.append(chunk)
            
            # 立即标记 embedding 失败的 chunk，避免无限重试
            if failed_chunk_ids:
                with get_db_session() as db:
                    for cid in failed_chunk_ids:
                        db_chunk = db.query(ChunkModel).filter(ChunkModel.id == cid).first()
                        if db_chunk:
                            db_chunk.vector_status = "failed"
                            db_chunk.vector_error = "embedding 返回空"
                    db.commit()
            
            # 批量写入 Qdrant
            if vectors_to_write:
                try:
                    vector_ids = self.vector_store.add_vectors_batch(
                        project_id=project_id,
                        vectors=vectors_to_write,
                        payloads=payloads_to_write,
                    )
                    with get_db_session() as db:
                        for chunk, vid in zip(chunks_to_update, vector_ids):
                            db_chunk = db.query(ChunkModel).filter(ChunkModel.id == chunk["id"]).first()
                            if db_chunk:
                                if vid:
                                    db_chunk.vector_id = vid
                                    db_chunk.vector_status = "success"
                                    db_chunk.vector_error = None
                                    total_success += 1
                                else:
                                    db_chunk.vector_status = "failed"
                                    db_chunk.vector_error = "向量写入返回空 ID"
                                    total_failed += 1
                        db.commit()
                except Exception as e:
                    logger.error(f"批量向量写入失败: {e}")
                    with get_db_session() as db:
                        for chunk in chunks_to_update:
                            db_chunk = db.query(ChunkModel).filter(ChunkModel.id == chunk["id"]).first()
                            if db_chunk:
                                db_chunk.vector_status = "failed"
                                db_chunk.vector_error = str(e)[:200]
                        db.commit()
                    total_failed += len(chunks_to_update)
            
            total_processed += len(pending)
            logger.info(
                f"batch_vectorize: 已处理 {total_processed}, "
                f"成功 {total_success}, 失败 {total_failed}"
            )
        
        # 统计剩余 pending 数量
        with get_db_session() as db:
            remaining = db.query(ChunkModel).filter(
                ChunkModel.project_id == project_id,
                ChunkModel.vector_status == "pending",
            ).count()
        
        return {
            "processed": total_processed,
            "success": total_success,
            "failed": total_failed,
            "remaining": remaining,
        }
    
    # ========== 删除文档 ==========
    
    def delete_document(self, document_id: str, delete_file: bool = True) -> bool:
        """删除文档及其所有关联数据。"""
        try:
            with get_db_session() as db:
                doc = db.query(DocumentModel).filter(DocumentModel.id == document_id).first()
                if not doc:
                    logger.warning(f"文档不存在: {document_id}")
                    return False
                
                project_id = doc.project_id
                saved_filename = doc.filename
                saved_file_path = doc.file_path
                saved_source_path = doc.source_path
                
                # 收集 chunks 和向量 ID
                chunks = db.query(ChunkModel).filter(ChunkModel.document_id == document_id).all()
                actual_chunk_count = len(chunks)
                vector_ids = [c.vector_id for c in chunks if c.vector_id]
                chunk_ids_for_bm25 = [c.id for c in chunks]
                
                # 删除 chunks
                for chunk in chunks:
                    db.delete(chunk)
                
                # 删除文档记录
                db.delete(doc)
                db.commit()
            
            # 删除向量（在事务外，允许部分失败）
            failed_vectors = []
            for vector_id in vector_ids:
                try:
                    self.vector_store.delete_vector(project_id, vector_id)
                except Exception as e:
                    logger.error(f"删除向量失败 {vector_id}: {e}")
                    failed_vectors.append(vector_id)
            
            if failed_vectors:
                logger.warning(f"文档 {document_id} 有 {len(failed_vectors)} 个向量删除失败")
            
            # 更新 BM25
            try:
                bm25_index = bm25_manager.get_index(project_id)
                for chunk_id in chunk_ids_for_bm25:
                    bm25_index.remove_document(chunk_id)
                bm25_index.save()
            except Exception as e:
                logger.warning(f"BM25 索引更新失败: {e}")
            
            # 删除层次化索引
            try:
                hierarchical_index.delete_document_summary(project_id, document_id)
            except Exception as e:
                logger.warning(f"删除文档摘要失败: {e}")
            
            # 删除物理文件
            if delete_file:
                self._delete_physical_file(project_id, saved_filename, saved_file_path, saved_source_path)
            
            # 更新项目统计
            with get_db_session() as db:
                project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
                if project:
                    project.document_count = max(0, project.document_count - 1)
                    project.chunk_count = max(0, project.chunk_count - actual_chunk_count)
                    db.commit()
            
            logger.info(f"已删除文档: {document_id}")
            return True
            
        except Exception as e:
            logger.exception(f"删除文档失败: {e}")
            return False
    
    def _delete_physical_file(
        self,
        project_id: str,
        filename: str,
        file_path: Optional[str],
        source_path: Optional[str],
    ) -> None:
        """删除物理文件，按优先级尝试多个路径"""
        candidates = []
        if filename:
            candidates.append(settings.PROJECTS_DIR / project_id / filename)
        if file_path:
            candidates.append(Path(file_path))
        if source_path:
            candidates.append(Path(source_path))
        
        for path in candidates:
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    logger.info(f"已删除物理文件: {path}")
                    return
            except Exception as e:
                logger.warning(f"删除文件失败 {path}: {e}")
        
        logger.debug(f"未找到可删除的物理文件: {filename}")
    
    # ========== 辅助方法 ==========
    
    def reindex_document(self, project_id: str, document_id: str) -> DocumentProcessingResult:
        """重新索引文档。
        
        先保存文档元信息，删除旧数据，再用保存的信息重新处理。
        """
        with get_db_session() as db:
            doc = db.query(DocumentModel).filter(
                DocumentModel.id == document_id,
                DocumentModel.project_id == project_id,
            ).first()
            
            if not doc:
                return DocumentProcessingResult(success=False, error_message="文档不存在")
            
            saved_filename = doc.filename
            saved_doc_type = doc.doc_type
            saved_source_path = doc.source_path
            saved_file_path = doc.file_path
        
        # 删除旧数据（保留物理文件）
        self.delete_document(document_id, delete_file=False)
        
        # 确定文件路径
        file_path = settings.PROJECTS_DIR / project_id / saved_filename
        if not file_path.exists() and saved_file_path:
            file_path = Path(saved_file_path)
        if not file_path.exists() and saved_source_path:
            file_path = Path(saved_source_path)
        
        if not file_path.exists():
            return DocumentProcessingResult(
                success=False,
                error_message=f"文件不存在: {saved_filename}",
            )
        
        # 重新处理（不传 document_id，创建新记录）
        return self.process_document(
            file_path=file_path,
            doc_type=saved_doc_type,
            project_id=project_id,
            filename=saved_filename,
            source_path=saved_source_path,
        )
