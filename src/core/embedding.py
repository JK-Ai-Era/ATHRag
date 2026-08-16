"""Embedding 服务"""

import threading
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.rag_api.config import get_settings
from src.core.model_config import get_embedding_config

settings = get_settings()
logger = logging.getLogger(__name__)

# 全局线程池，用于异步执行同步操作
_executor: Optional[ThreadPoolExecutor] = None


def _get_executor() -> ThreadPoolExecutor:
    """获取全局线程池"""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="embedding-")
    return _executor


class EmbeddingService:
    """Embedding 服务 - 使用 Ollama
    
    提供同步和异步两种调用方式：
    - embed_text() / embed_batch(): 异步方法，不阻塞事件循环
    - embed_text_sync(): 同步方法，用于同步上下文
    """
    
    def __init__(self):
        _cfg = get_embedding_config()
        self.provider = _cfg["provider"]
        self.host = _cfg["host"]
        self.model = _cfg["model"]
        self.timeout = _cfg["timeout"]
        self.embed_dim = _cfg["dimension"]
        self._async_client: Optional[httpx.AsyncClient] = None
        self._local = threading.local()  # thread-local 存储
    
    @property
    def async_client(self) -> httpx.AsyncClient:
        """懒加载异步客户端"""
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self.timeout)
        return self._async_client
    
    @property
    def sync_client(self) -> httpx.Client:
        """线程安全的同步客户端（每个线程独立实例）"""
        if not hasattr(self._local, 'client') or self._local.client is None:
            self._local.client = httpx.Client(timeout=self.timeout)
        return self._local.client
    
    async def embed_text(self, text: str) -> List[float]:
        """对单个文本进行向量化（异步）
        
        使用异步HTTP请求，不阻塞事件循环。
        与 embed_text_sync 行为一致：零向量/空向量抛异常，不返回零向量污染下游。
        """
        if not text or not text.strip():
            raise ValueError("文本为空，无法向量化")
        
        # 截断过长文本
        max_chars = settings.MAX_CHUNK_SIZE
        if len(text) > max_chars:
            logger.warning(f"文本过长 ({len(text)} 字符)，截断到 {max_chars}")
            text = text[:max_chars]
        
        try:
            response = await self.async_client.post(
                f"{self.host}/api/embeddings",
                json={
                    "model": self.model,
                    "prompt": text,
                },
            )
            response.raise_for_status()
            
            data = response.json()
            embedding = data.get("embedding", [])
            
            if not embedding:
                logger.warning("Ollama 返回空向量")
                raise ValueError("Ollama 返回空向量")
            
            # 检查零向量
            if all(v == 0.0 for v in embedding):
                logger.warning("Ollama 返回零向量（可能服务未就绪）")
                raise ValueError("零向量，服务可能未就绪")
            
            return embedding
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 500:
                error_text = e.response.text
                if "input length exceeds" in error_text.lower():
                    logger.error(f"输入过长导致 Ollama 500: {len(text)} 字符")
                    raise ValueError(f"输入过长 ({len(text)} 字符)，需要进一步切分")
            logger.error(f"Embedding HTTP 错误: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Embedding 请求错误: {e}")
            raise
        except Exception as e:
            logger.error(f"Embedding 失败: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        # 只 retry 网络错误和 HTTP 错误，不 retry ValueError（空文本/输入过长）
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        reraise=True
    )
    def embed_text_sync(self, text: str) -> List[float]:
        """对单个文本进行向量化（同步，带 retry）
        
        用于同步上下文，如 Watcher 事件处理。
        
        只对网络错误和 HTTP 错误进行 retry（最多 3 次）。
        ValueError（空文本/输入过长）不 retry，直接抛出。
        
        Raises:
            ValueError: 文本为空或输入过长（不可重试）
            httpx.RequestError: 网络错误（会 retry）
            httpx.HTTPStatusError: HTTP 错误（会 retry，除非是输入过长的 500）
        """
        if not text or not text.strip():
            # ⚠️ 不返回零向量！抛出异常避免污染数据库
            # ValueError 不触发 retry
            raise ValueError("文本为空，无法向量化")
        
        # 硬性上限保护（防止 Ollama 500）
        max_chars = settings.MAX_CHUNK_SIZE
        if len(text) > max_chars:
            logger.warning(f"文本过长 ({len(text)} 字符)，截断到 {max_chars}")
            text = text[:max_chars]
        
        try:
            response = self.sync_client.post(
                f"{self.host}/api/embeddings",
                json={
                    "model": self.model,
                    "prompt": text,
                },
            )
            response.raise_for_status()
            
            data = response.json()
            embedding = data.get("embedding", [])
            
            if not embedding:
                logger.warning("Ollama 返回空向量")
                raise ValueError("Ollama 返回空向量")  # 触发 retry
            
            # 检查零向量（可能服务未就绪）
            if all(v == 0.0 for v in embedding):
                logger.warning("Ollama 返回零向量（可能服务未就绪）")
                raise ValueError("零向量，服务可能未就绪")  # 触发 retry
            
            return embedding
            
        except httpx.HTTPStatusError as e:
            # 500 错误可能是输入过长，不 retry
            if e.response.status_code == 500:
                error_text = e.response.text
                if "input length exceeds" in error_text.lower():
                    logger.error(f"输入过长导致 Ollama 500: {len(text)} 字符")
                    # ⚠️ 不返回零向量！抛出异常让调用方处理
                    # 调用方会保留 chunk，可通过 sync_missing_vectors.py 重新处理
                    raise ValueError(f"输入过长 ({len(text)} 字符)，需要进一步切分")
            logger.error(f"Embedding HTTP 错误: {e.response.status_code}")
            raise  # 其他 HTTP 错误触发 retry
        except httpx.RequestError as e:
            logger.error(f"Embedding 请求错误: {e}")
            raise  # 网络错误触发 retry
        except Exception as e:
            logger.error(f"Embedding 失败: {e}")
            raise  # 其他错误触发 retry
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def embed_batch(self, texts: List[str], batch_size: int = 10) -> Tuple[List[Optional[List[float]]], List[int]]:
        """批量向量化（异步）
        
        使用并发HTTP请求提高效率，每个批次内并行处理。
        添加重试机制，最多重试3次。
        
        Args:
            texts: 待向量化的文本列表
            batch_size: 每批次处理的数量，默认10
            
        Returns:
            (results, failed_indices): results 中失败位置为 None，failed_indices 记录失败索引
        """
        if not texts:
            return [], []
        
        results: List[Optional[List[float]]] = [None] * len(texts)
        failed_indices: List[int] = []
        
        for i in range(0, len(texts), batch_size):
            batch_indices = list(range(i, min(i + batch_size, len(texts))))
            batch_texts = [texts[j] for j in batch_indices]
            
            # 并发处理批次内的文本
            tasks = [self.embed_text(text) for text in batch_texts]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for idx, result in zip(batch_indices, batch_results):
                if isinstance(result, Exception):
                    logger.warning(f"Embedding 失败 (索引 {idx}): {result}")
                    failed_indices.append(idx)
                else:
                    results[idx] = result
        
        if failed_indices:
            logger.warning(f"批量向量化完成，{len(failed_indices)}/{len(texts)} 个失败")
        
        return results, failed_indices
    
    async def embed_batch_sync_fallback(self, texts: List[str]) -> Tuple[List[Optional[List[float]]], List[int]]:
        """批量向量化（使用线程池执行同步方法）
        
        当异步方法有问题时的备选方案。
        """
        loop = asyncio.get_event_loop()
        executor = _get_executor()
        
        results: List[Optional[List[float]]] = [None] * len(texts)
        failed_indices: List[int] = []
        
        for i, text in enumerate(texts):
            try:
                result = await loop.run_in_executor(executor, self.embed_text_sync, text)
                results[i] = result
            except Exception as e:
                logger.error(f"Embedding 失败: {e}")
                failed_indices.append(i)
        
        return results, failed_indices
    
    async def health_check(self) -> bool:
        """检查 Ollama 服务健康状态"""
        try:
            response = await self.async_client.get(f"{self.host}/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama 健康检查失败: {e}")
            return False
    
    async def list_models(self) -> List[str]:
        """列出可用的模型"""
        try:
            response = await self.async_client.get(f"{self.host}/api/tags")
            data = response.json()
            models = data.get("models", [])
            return [m.get("name", "") for m in models]
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return []
    
    async def close(self):
        """关闭连接"""
        if self._async_client:
            await self._async_client.aclose()
            self._async_client = None
        # thread-local 客户端在各线程生命周期内自然回收
        # 主动清理当前线程的 client
        if hasattr(self._local, 'client') and self._local.client is not None:
            self._local.client.close()
            self._local.client = None


# ============================================================================
# 向量状态跟踪辅助函数
# ============================================================================

def update_chunk_vector_status(
    chunk_id: str,
    status: str,
    error: Optional[str] = None,
) -> bool:
    """
    更新 chunk 的向量状态
    
    Args:
        chunk_id: Chunk ID
        status: 'pending' | 'success' | 'failed'
        error: 错误信息（失败时）
        
    Returns:
        是否更新成功
    """
    from src.rag_api.models.database import Chunk as ChunkModel, get_db_session
    
    try:
        now = datetime.utcnow()
        
        with get_db_session() as db:
            chunk = db.query(ChunkModel).filter(ChunkModel.id == chunk_id).first()
            if not chunk:
                logger.warning(f"Chunk 不存在: {chunk_id}")
                return False
            
            chunk.last_vector_attempt = now
            
            if status == "success":
                chunk.vector_status = "success"
                chunk.vector_error = None
            elif status == "failed":
                chunk.vector_status = "failed"
                chunk.vector_error = error[:200] if error else None
                chunk.vector_retry_count = (chunk.vector_retry_count or 0) + 1
            else:  # pending
                chunk.vector_status = "pending"
                chunk.vector_error = None
        
        return True
        
    except Exception as e:
        logger.error(f"更新 chunk 状态失败: {e}")
        return False


def get_failed_chunks(
    project_id: Optional[str] = None,
    max_retry: int = 3,
    limit: int = 100,
) -> List[dict]:
    """
    获取向量失败的 chunks
    
    Args:
        project_id: 项目 ID（可选）
        max_retry: 最大重试次数
        limit: 最大返回数
        
    Returns:
        [{"id": str, "project_id": str, "error": str, "retry_count": int}, ...]
    """
    from src.rag_api.models.database import Chunk as ChunkModel, get_db_session
    
    try:
        with get_db_session() as db:
            query = db.query(ChunkModel).filter(
                ChunkModel.vector_status == "failed",
                ChunkModel.vector_retry_count < max_retry,
            )
            if project_id:
                query = query.filter(ChunkModel.project_id == project_id)
            
            chunks = query.order_by(
                ChunkModel.last_vector_attempt.desc()
            ).limit(limit).all()
            
            return [
                {
                    "id": c.id,
                    "project_id": c.project_id,
                    "error": c.vector_error,
                    "retry_count": c.vector_retry_count,
                    "last_attempt": c.last_vector_attempt.isoformat() if c.last_vector_attempt else None,
                }
                for c in chunks
            ]
        
    except Exception as e:
        logger.error(f"获取失败 chunks 失败: {e}")
        return []


def reset_failed_chunks(
    project_id: Optional[str] = None,
    chunk_ids: Optional[List[str]] = None,
) -> int:
    """
    重置失败的 chunks 为 pending（待重试）
    
    Args:
        project_id: 项目 ID（可选，与 chunk_ids 二选一）
        chunk_ids: Chunk ID 列表（可选）
        
    Returns:
        重置的数量
    """
    from src.rag_api.models.database import Chunk as ChunkModel, get_db_session
    
    try:
        with get_db_session() as db:
            query = db.query(ChunkModel).filter(
                ChunkModel.vector_status == "failed"
            )
            
            if chunk_ids:
                query = query.filter(ChunkModel.id.in_(chunk_ids))
            elif project_id:
                query = query.filter(ChunkModel.project_id == project_id)
            
            chunks = query.all()
            count = len(chunks)
            for c in chunks:
                c.vector_status = "pending"
                c.vector_error = None
            
            logger.info(f"重置 {count} 个失败 chunks 为 pending")
            return count
        
    except Exception as e:
        logger.error(f"重置失败 chunks 失败: {e}")
        return 0


# ============================================================================
# 全局单例管理
# ============================================================================

_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """获取全局 EmbeddingService 单例"""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
