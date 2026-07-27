"""上下文压缩模块 - 检索后提取相关内容

对检索结果进行压缩，只保留与 query 相关的部分，
减少 LLM 上下文窗口的浪费，提升生成质量。

两种压缩策略：
1. Extractive（提取式）- 从 chunk 中提取相关句子
2. Abstractive（摘要式）- 用 LLM 生成精炼摘要
"""

import asyncio
import logging
import re
from typing import List, Optional
from dataclasses import dataclass

import httpx

from src.rag_api.config import get_settings
from src.rag_api.models.schemas import SearchResult

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class CompressedResult:
    """压缩后的搜索结果"""
    original: SearchResult
    compressed_content: str  # 压缩后的内容
    compression_ratio: float  # 压缩比 (0-1)
    method: str  # 压缩方法


class ContextCompressor:
    """上下文压缩器
    
    对检索结果进行压缩，只保留与 query 相关的内容。
    """
    
    def __init__(self, model: str = None, use_llm: bool = True):
        self.model = model or settings.OLLAMA_COMPRESS_MODEL
        self._ollama_host = settings.OLLAMA_HOST
        self.use_llm = use_llm
    
    async def compress(
        self,
        query: str,
        results: List[SearchResult],
        max_chunks: int = 5,
    ) -> List[SearchResult]:
        """压缩搜索结果
        
        Args:
            query: 原始查询
            results: 搜索结果列表
            max_chunks: 最多处理的 chunk 数量（避免过多 LLM 调用）
            
        Returns:
            压缩后的搜索结果列表（content 被替换为压缩后的内容）
        """
        if not results:
            return results
        
        # 只处理前 N 个结果
        to_compress = results[:max_chunks]
        remaining = results[max_chunks:]
        
        if self.use_llm:
            # LLM 提取式压缩
            compressed = await self._llm_extractive_compression(query, to_compress)
        else:
            # 基于规则的压缩（不需要 LLM）
            compressed = self._rule_based_compression(query, to_compress)
        
        return compressed + remaining
    
    async def _llm_extractive_compression(
        self,
        query: str,
        results: List[SearchResult],
    ) -> List[SearchResult]:
        """LLM 提取式压缩：从每个 chunk 中提取与 query 相关的句子"""
        
        # 逐个处理（避免并发导致 Ollama 超时）
        final_results = []
        for i, r in enumerate(results):
            try:
                compressed = await self._extract_relevant_sentences(query, r)
                final_results.append(compressed)
            except Exception as e:
                logger.warning(f"压缩失败 [{i+1}/{len(results)}]，保留原始内容: {e}")
                final_results.append(r)
        
        return final_results
    
    async def _extract_relevant_sentences(
        self,
        query: str,
        result: SearchResult,
    ) -> SearchResult:
        """从单个 chunk 中提取与 query 相关的句子"""
        content = result.content
        if len(content) < 100:
            # 内容已经很短，不需要压缩
            return result
        
        prompt = f"""请从以下文档片段中，提取与问题直接相关的句子或段落。

要求：
1. 只保留能回答问题的内容
2. 保持原文，不要改写
3. 如果文档内容与问题无关，输出"NONE"
4. 提取的内容应该能独立理解

问题：{query}

文档片段：
{content[:2000]}"""
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self._ollama_host}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "think": False,  # 禁用 thinking 模式
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 300,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
                extracted = data.get("message", {}).get("content", "").strip()
            
            if extracted and extracted != "NONE" and len(extracted) > 20:
                compression_ratio = len(extracted) / len(content)
                if compression_ratio > 0.9:
                    return result
                return SearchResult(
                    content=extracted,
                    score=result.score,
                    search_type=result.search_type,
                    metadata={
                        **result.metadata,
                        "original_length": len(content),
                        "compressed_length": len(extracted),
                        "compression_method": "llm_extractive",
                    },
                    document_id=result.document_id,
                    chunk_id=result.chunk_id,
                )
            else:
                return SearchResult(
                    content=content,
                    score=result.score,
                    search_type=result.search_type,
                    metadata={
                        **result.metadata,
                        "compression_method": "llm_keep_original",
                    },
                    document_id=result.document_id,
                    chunk_id=result.chunk_id,
                )
                
        except Exception as e:
            logger.warning(f"LLM 压缩失败: {type(e).__name__}: {e}")
            return result
    
    def _rule_based_compression(
        self,
        query: str,
        results: List[SearchResult],
    ) -> List[SearchResult]:
        """基于规则的压缩：提取包含查询关键词的句子"""
        # 提取 query 中的关键词（简单分词）
        keywords = set()
        for word in re.split(r'[\s,，。、;；:：]+', query):
            if len(word) >= 2:
                keywords.add(word.lower())
        
        if not keywords:
            return results
        
        compressed_results = []
        for result in results:
            content = result.content
            
            # 按句子分割
            sentences = re.split(r'(?<=[。！？\n])', content)
            sentences = [s.strip() for s in sentences if s.strip()]
            
            # 提取包含关键词的句子
            relevant_sentences = []
            for sentence in sentences:
                sentence_lower = sentence.lower()
                if any(kw in sentence_lower for kw in keywords):
                    relevant_sentences.append(sentence)
            
            if relevant_sentences:
                extracted = ''.join(relevant_sentences)
                compression_ratio = len(extracted) / len(content) if content else 1.0
                
                if compression_ratio < 0.9:
                    compressed_results.append(SearchResult(
                        content=extracted,
                        score=result.score,
                        search_type=result.search_type,
                        metadata={
                            **result.metadata,
                            "compression_method": "rule_based",
                            "original_length": len(content),
                            "compressed_length": len(extracted),
                        },
                        document_id=result.document_id,
                        chunk_id=result.chunk_id,
                    ))
                else:
                    compressed_results.append(result)
            else:
                compressed_results.append(result)
        
        return compressed_results


# 全局单例
_context_compressor: Optional[ContextCompressor] = None


def get_context_compressor(model: str = None, use_llm: bool = True) -> ContextCompressor:
    """获取上下文压缩器单例"""
    global _context_compressor
    if _context_compressor is None:
        _context_compressor = ContextCompressor(model=model, use_llm=use_llm)
    return _context_compressor
