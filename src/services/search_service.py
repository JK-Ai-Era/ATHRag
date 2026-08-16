"""搜索服务 - 支持混合检索和重排序"""

import time
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from src.rag_api.config import get_settings
from src.rag_api.models.schemas import (
    SearchRequest, SearchResponse, SearchResult,
    QueryTransformMode, SearchMode,
)
from src.core.embedding import get_embedding_service
from src.core.vector_store import get_vector_store
from src.core.bm25_index import bm25_manager
from src.core.reranker import get_reranker
from src.core.hierarchical_index import hierarchical_search, hierarchical_index
from src.core.query_transformer import (
    get_query_transformer, TransformStrategy, TransformResult,
)
from src.core.context_compressor import get_context_compressor

settings = get_settings()
logger = logging.getLogger(__name__)


class SearchService:
    """搜索服务
    
    支持：
    - 语义搜索（向量）
    - 关键词搜索（BM25）
    - 混合搜索（向量 + BM25 + RRF 融合）
    - 重排序（Reranker）
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.embedding = get_embedding_service()
        self.vector_store = get_vector_store()
    
    async def search(self, request: SearchRequest) -> SearchResponse:
        """执行搜索"""
        start_time = time.time()
        
        # 验证项目是否存在
        from src.rag_api.models.database import Project
        
        project = self.db.query(Project).filter(
            (Project.id == request.project_id) | 
            (Project.name == request.project_id)
        ).first()
        if not project:
            raise ValueError(f"项目不存在: {request.project_id}")
        
        project_id = str(project.id)
        
        # 查询变换
        transform_mode = request.query_transform
        if transform_mode == QueryTransformMode.NONE and settings.QUERY_TRANSFORM_ENABLED:
            transform_mode = QueryTransformMode(settings.QUERY_TRANSFORM_MODE)
        
        transform_result = None
        if transform_mode != QueryTransformMode.NONE:
            try:
                strategy = TransformStrategy(transform_mode.value)
                transformer = get_query_transformer()
                transform_result = await transformer.transform(
                    query=request.query,
                    strategy=strategy,
                    num_variants=settings.QUERY_TRANSFORM_NUM_VARIANTS,
                )
                logger.info(
                    f"查询变换 [{transform_mode.value}]: "
                    f"'{request.query}' → {len(transform_result.expanded_queries)} 个变体"
                )
            except Exception as e:
                logger.warning(f"查询变换失败，使用原始 query: {e}")
                transform_result = None
        
        # 执行检索
        if transform_result and len(transform_result.expanded_queries) > 1:
            # 多 query 检索：对每个变体分别检索，合并结果
            results = await self._multi_query_search(
                request, project_id, transform_result.expanded_queries
            )
        else:
            # 单 query 检索
            results = await self._single_query_search(request, project_id)
        
        # 重排序（如果启用）
        if request.rerank and results:
            results = self._rerank(request.query, results, request.top_k)
        
        # 上下文压缩（如果启用）
        compress = request.context_compress or settings.CONTEXT_COMPRESS_ENABLED
        if compress and results:
            try:
                compressor = get_context_compressor(
                    use_llm=settings.CONTEXT_COMPRESS_USE_LLM
                )
                results = await compressor.compress(
                    query=request.query,
                    results=results,
                    max_chunks=settings.CONTEXT_COMPRESS_MAX_CHUNKS,
                )
            except Exception as e:
                logger.warning(f"上下文压缩失败，保留原始结果: {e}")
        
        # 应用阈值过滤
        if request.score_threshold:
            results = [r for r in results if r.score >= request.score_threshold]
        
        # 分页：先跳过 offset 条，再取 top_k 条
        if request.offset > 0:
            results = results[request.offset:]
        results = results[: request.top_k]
        
        query_time = int((time.time() - start_time) * 1000)
        
        return SearchResponse(
            query=request.query,
            project_id=project_id,
            results=results,
            total=len(results),
            offset=request.offset,
            limit=request.top_k,
            query_time_ms=query_time,
        )
    
    async def _multi_query_search(
        self,
        request: SearchRequest,
        project_id: str,
        queries: List[str],
    ) -> List[SearchResult]:
        """多 query 检索：并发执行，合并去重"""
        import asyncio
        
        # 并发执行所有变体的搜索
        tasks = []
        for q in queries:
            sub_request = SearchRequest(
                project_id=request.project_id,
                query=q,
                top_k=request.top_k,
                search_mode=request.search_mode,
                score_threshold=request.score_threshold,
                filters=request.filters,
                rerank=False,
                query_transform=QueryTransformMode.NONE,
            )
            tasks.append(self._single_query_search(sub_request, project_id))
        
        # 等待所有搜索完成
        all_sub_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 合并去重（按 chunk_id）
        all_results: List[SearchResult] = []
        seen_chunks = set()
        
        for sub_results in all_sub_results:
            if isinstance(sub_results, Exception):
                logger.warning(f"子查询失败: {sub_results}")
                continue
            for r in sub_results:
                if r.chunk_id not in seen_chunks:
                    seen_chunks.add(r.chunk_id)
                    all_results.append(r)
        
        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results
    
    async def _single_query_search(
        self, request: SearchRequest, project_id: str
    ) -> List[SearchResult]:
        """单 query 检索"""
        results = []
        
        # 根据搜索模式执行检索（使用枚举比较）
        if request.search_mode in (SearchMode.SEMANTIC, SearchMode.HYBRID):
            semantic_results = await self._semantic_search(request, project_id)
            results.extend(semantic_results)
        
        if request.search_mode in (SearchMode.KEYWORD, SearchMode.HYBRID):
            keyword_results = await self._keyword_search(request, project_id)
            results.extend(keyword_results)
        
        if request.search_mode == SearchMode.HIERARCHICAL:
            hierarchical_results = await self._hierarchical_search(request, project_id)
            results.extend(hierarchical_results)
        
        # 结果融合（Hybrid 模式）
        if request.search_mode == SearchMode.HYBRID and results:
            results = self._reciprocal_rank_fusion(results)
        
        return results
    
    async def _semantic_search(
        self, 
        request: SearchRequest,
        project_id: str
    ) -> List[SearchResult]:
        """语义搜索（向量检索）"""
        try:
            # 获取查询向量
            query_embedding = await self.embedding.embed_text(request.query)
            
            # 检索向量库
            hits = self.vector_store.search(
                project_id=project_id,
                vector=query_embedding,
                top_k=request.top_k * 2,  # 多取一些用于融合
                score_threshold=None,  # 先不过滤，由 reranker 处理
            )
            
            results = []
            for hit in hits:
                results.append(
                    SearchResult(
                        content=hit.payload.get("content", ""),
                        score=hit.score,
                        search_type="semantic",
                        metadata={
                            "filename": hit.payload.get("filename"),
                            "source_path": hit.payload.get("source_path"),  # 原始文件完整路径
                            "chunk_id": hit.payload.get("chunk_id"),
                            "start_line": hit.payload.get("start_line"),
                            "end_line": hit.payload.get("end_line"),
                            "symbols": hit.payload.get("symbols", []),
                        },
                        document_id=hit.payload.get("document_id", ""),
                        chunk_id=hit.payload.get("chunk_id", ""),
                    )
                )
            
            return results
            
        except Exception as e:
            logger.error(f"语义搜索失败: {e}")
            return []
    
    async def _keyword_search(
        self, 
        request: SearchRequest,
        project_id: str
    ) -> List[SearchResult]:
        """关键词搜索（BM25）"""
        try:
            # 获取或构建 BM25 索引
            bm25_index = bm25_manager.get_index(project_id)
            
            # 如果索引为空，尝试从数据库构建
            if bm25_index.doc_count == 0:
                logger.info(f"BM25 索引为空，从数据库构建: {project_id}")
                bm25_index = bm25_manager.build_index_from_db(project_id, self.db)
            
            # BM25 搜索
            hits = bm25_index.search(
                query=request.query,
                top_k=request.top_k * 2,
                score_threshold=0.0,
            )
            
            if not hits:
                return []
            
            # 批量查询 chunks（优化 N+1 问题）
            from src.rag_api.models.database import Chunk, Document
            import json
            
            chunk_ids = [h[0] for h in hits]
            chunks = self.db.query(Chunk).filter(
                Chunk.id.in_(chunk_ids)
            ).all()
            chunks_by_id = {c.id: c for c in chunks}
            
            # 批量查询 documents
            doc_ids = list(set(c.document_id for c in chunks if c.document_id))
            docs = self.db.query(Document).filter(
                Document.id.in_(doc_ids)
            ).all()
            docs_by_id = {d.id: d for d in docs}
            
            # 转换为 SearchResult
            results = []
            for chunk_id, score in hits:
                chunk = chunks_by_id.get(chunk_id)
                if not chunk:
                    continue
                
                doc = docs_by_id.get(chunk.document_id)
                
                metadata = {}
                if chunk.metadata_json:
                    try:
                        metadata = json.loads(chunk.metadata_json)
                    except:
                        pass
                
                results.append(
                    SearchResult(
                        content=chunk.content,
                        score=score,
                        search_type="keyword",
                        metadata={
                            "filename": doc.filename if doc else None,
                            "source_path": doc.source_path if doc else None,  # 原始文件完整路径
                            "chunk_id": chunk_id,
                            "start_line": metadata.get("start_line"),
                            "end_line": metadata.get("end_line"),
                            "symbols": metadata.get("symbols", []),
                        },
                        document_id=chunk.document_id,
                        chunk_id=chunk_id,
                    )
                )
            
            return results
            
        except Exception as e:
            logger.error(f"关键词搜索失败: {e}")
            return []
    
    async def _hierarchical_search(
        self, 
        request: SearchRequest,
        project_id: str
    ) -> List[SearchResult]:
        """层次化搜索（摘要 → chunks）
        
        先搜索文档摘要找到相关文档，再在这些文档中搜索详细内容。
        """
        try:
            # 执行层次化搜索
            summaries, chunks = await hierarchical_search.search(
                project_id=project_id,
                query=request.query,
                top_k=request.top_k,
                summary_top_k=min(5, request.top_k),
                chunks_per_doc=3
            )
            
            if not chunks:
                return []
            
            # 转换为 SearchResult
            results = []
            for chunk_data in chunks:
                results.append(
                    SearchResult(
                        content=chunk_data.get("content", ""),
                        score=chunk_data.get("score", 0.0),
                        search_type="hierarchical",
                        metadata={
                            "filename": chunk_data.get("filename"),
                            "source_path": chunk_data.get("source_path"),  # 原始文件完整路径
                            "chunk_id": chunk_data.get("chunk_id"),
                            "summary": next(
                                (s["summary"] for s in summaries if s["document_id"] == chunk_data.get("document_id")),
                                None
                            ),
                        },
                        document_id=chunk_data.get("document_id", ""),
                        chunk_id=chunk_data.get("chunk_id", ""),
                    )
                )
            
            return results
            
        except Exception as e:
            logger.error(f"层次化搜索失败: {e}")
            return []
    
    def _reciprocal_rank_fusion(
        self, results: List[SearchResult], k: int = 60
    ) -> List[SearchResult]:
        """RRF 结果融合
        
        公式: score = sum(1 / (k + rank_i))
        其中 rank_i 是结果在第 i 个检索系统中的排名
        
        注意：此方法创建新的 SearchResult 对象，不修改输入对象
        """
        from collections import defaultdict
        
        # 按 (search_type, chunk_id) 分组统计排名
        rank_scores = defaultdict(float)  # chunk_id -> 累积分数
        items = {}  # chunk_id -> SearchResult
        
        # 按搜索类型分组计算排名
        type_results = {"semantic": [], "keyword": []}
        for r in results:
            type_results[r.search_type].append(r)
        
        for search_type, type_hits in type_results.items():
            for rank, result in enumerate(type_hits):
                chunk_id = result.chunk_id
                # RRF 分数（标准公式：rank 从 1 开始，需加 1）
                rank_scores[chunk_id] += 1.0 / (k + rank + 1)
                
                if chunk_id not in items:
                    items[chunk_id] = result
        
        # 按融合分数排序
        sorted_chunks = sorted(rank_scores.items(), key=lambda x: x[1], reverse=True)
        
        final_results = []
        for chunk_id, score in sorted_chunks:
            original = items[chunk_id]
            # 创建新的 SearchResult 对象，避免修改原始对象
            result = SearchResult(
                content=original.content,
                score=score,
                search_type="hybrid",
                metadata=original.metadata,
                document_id=original.document_id,
                chunk_id=original.chunk_id,
            )
            final_results.append(result)
        
        return final_results
    
    def _rerank(
        self, 
        query: str, 
        results: List[SearchResult],
        top_k: int
    ) -> List[SearchResult]:
        """使用 Reranker 重排序"""
        try:
            reranker = get_reranker()
            return reranker.rerank(query, results, top_k=top_k * 2)
        except Exception as e:
            logger.warning(f"重排序失败，使用原始排序: {e}")
            return results
    
    async def build_bm25_index(self, project_id: str) -> int:
        """为项目构建 BM25 索引
        
        Args:
            project_id: 项目 ID
            
        Returns:
            索引文档数量
        """
        bm25_index = bm25_manager.build_index_from_db(project_id, self.db)
        return bm25_index.doc_count
    
    async def update_bm25_index(
        self, 
        project_id: str, 
        chunk_id: str, 
        content: str,
        action: str = "add"
    ) -> None:
        """增量更新 BM25 索引
        
        Args:
            project_id: 项目 ID
            chunk_id: Chunk ID
            content: 文档内容
            action: 操作类型 (add/remove)
        """
        bm25_index = bm25_manager.get_index(project_id)
        
        if action == "add":
            bm25_index.add_document(chunk_id, content)
        elif action == "remove":
            bm25_index.remove_document(chunk_id)
        
        # 保存更新后的索引
        bm25_index.save()