"""查询变换模块 - 检索前的 Query 预处理

支持三种变换策略：
1. HyDE（Hypothetical Document Embeddings）- 生成假设性答案，用答案的 embedding 检索
2. Multi-Query Expansion - 将 query 扩展为多个不同角度的变体
3. Sub-Query Decomposition - 复杂问题拆解为子问题

三种策略可以组合使用，由配置控制。
"""

import asyncio
import logging
from enum import Enum
from typing import List, Optional
from dataclasses import dataclass

from src.core.llm_client import LLMClient
from src.rag_api.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class TransformStrategy(str, Enum):
    """查询变换策略"""
    NONE = "none"
    HYDE = "hyde"
    MULTI_QUERY = "multi_query"
    SUB_QUERY = "sub_query"
    COMBINED = "combined"  # multi_query + sub_query 组合


@dataclass
class TransformResult:
    """查询变换结果"""
    original_query: str
    strategy: TransformStrategy
    expanded_queries: List[str]  # 变换后的 query 列表（含原始 query）
    hyde_doc: Optional[str] = None  # HyDE 生成的假设文档


class QueryTransformer:
    """查询变换器
    
    使用 LLM 对原始 query 进行变换，提升检索效果。
    """
    
    def __init__(self, model: str = None):
        self.model = model or settings.OLLAMA_SUMMARY_MODEL
        self.llm = LLMClient(model=self.model)
    
    async def close(self):
        """关闭连接"""
        await self.llm.close()
    
    async def transform(
        self, 
        query: str, 
        strategy: TransformStrategy = TransformStrategy.MULTI_QUERY,
        num_variants: int = 3,
    ) -> TransformResult:
        """执行查询变换
        
        Args:
            query: 原始查询
            strategy: 变换策略
            num_variants: 扩展变体数量（multi_query 模式）
            
        Returns:
            TransformResult 包含变换后的 queries
        """
        if strategy == TransformStrategy.NONE:
            return TransformResult(
                original_query=query,
                strategy=strategy,
                expanded_queries=[query],
            )
        
        try:
            if strategy == TransformStrategy.HYDE:
                return await self._hyde(query)
            elif strategy == TransformStrategy.MULTI_QUERY:
                return await self._multi_query(query, num_variants)
            elif strategy == TransformStrategy.SUB_QUERY:
                return await self._sub_query(query)
            elif strategy == TransformStrategy.COMBINED:
                # 组合：先 multi_query，再对每个变体做 sub_query
                return await self._combined(query, num_variants)
            else:
                return TransformResult(
                    original_query=query,
                    strategy=strategy,
                    expanded_queries=[query],
                )
        except Exception as e:
            logger.warning(f"查询变换失败，使用原始 query: {e}")
            return TransformResult(
                original_query=query,
                strategy=strategy,
                expanded_queries=[query],
            )
    
    async def _call_llm(self, prompt: str, max_tokens: int = 500) -> str:
        """调用 Ollama LLM（复用连接）"""
        return await self.llm.chat(prompt, max_tokens=max_tokens)
    
    async def _hyde(self, query: str) -> TransformResult:
        """HyDE：生成假设性文档
        
        让 LLM 假装自己知道答案，生成一段"理想文档"，
        用这段文档的 embedding 去检索，语义匹配度更高。
        """
        prompt = f"""请根据以下问题，生成一段可能包含答案的文档内容。
要求：
1. 假装你完全知道答案，写出一段专业的、信息丰富的文档
2. 内容要具体、有细节，不要泛泛而谈
3. 控制在 200-300 字
4. 直接输出文档内容，不要加任何前缀说明

问题：{query}"""
        
        hyde_doc = await self._call_llm(prompt, max_tokens=400)
        
        return TransformResult(
            original_query=query,
            strategy=TransformStrategy.HYDE,
            expanded_queries=[query, hyde_doc],
            hyde_doc=hyde_doc,
        )
    
    async def _multi_query(self, query: str, num_variants: int = 3) -> TransformResult:
        """Multi-Query：多角度扩展
        
        将一个 query 扩展为 N 个不同表述角度的 query，
        分别检索后合并结果，提升召回率。
        """
        prompt = f"""请将以下查询从 {num_variants} 个不同角度重新表述，用于文档检索。

要求：
1. 每个变体表达相同的意图，但用不同的措辞和角度
2. 变体应该涵盖：具体表述、抽象表述、相关概念表述
3. 每个变体单独一行
4. 只输出变体，不要编号，不要加其他说明

原始查询：{query}"""
        
        response = await self._call_llm(prompt, max_tokens=300)
        
        # 解析变体
        variants = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if line and line != query:
                # 去掉可能的编号前缀
                import re
                line = re.sub(r'^[\d]+[\.\)、]\s*', '', line)
                if line:
                    variants.append(line)
        
        # 确保原始 query 在列表首位
        all_queries = [query] + variants[:num_variants]
        
        return TransformResult(
            original_query=query,
            strategy=TransformStrategy.MULTI_QUERY,
            expanded_queries=all_queries,
        )
    
    async def _sub_query(self, query: str) -> TransformResult:
        """Sub-Query Decomposition：子问题分解
        
        将复杂问题拆解为多个简单的子问题，
        分别检索后综合答案。
        """
        prompt = f"""请将以下复杂查询分解为 2-4 个简单的子问题，每个子问题聚焦查询的一个方面。

要求：
1. 子问题应该能独立检索到相关信息
2. 子问题覆盖原始查询的所有关键方面
3. 每个子问题单独一行
4. 只输出子问题，不要编号，不要加其他说明

原始查询：{query}"""
        
        response = await self._call_llm(prompt, max_tokens=300)
        
        # 解析子问题
        sub_queries = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if line and line != query:
                import re
                line = re.sub(r'^[\d]+[\.\)、]\s*', '', line)
                if line:
                    sub_queries.append(line)
        
        # 确保原始 query 在列表首位
        all_queries = [query] + sub_queries[:4]
        
        return TransformResult(
            original_query=query,
            strategy=TransformStrategy.SUB_QUERY,
            expanded_queries=all_queries,
        )
    
    async def _combined(self, query: str, num_variants: int = 3) -> TransformResult:
        """组合策略：multi_query + sub_query"""
        # 先做 multi_query
        mq_result = await self._multi_query(query, num_variants)
        
        # 再对原始 query 做 sub_query
        sq_result = await self._sub_query(query)
        
        # 合并去重
        all_queries = []
        seen = set()
        for q in mq_result.expanded_queries + sq_result.expanded_queries:
            q_normalized = q.strip().lower()
            if q_normalized and q_normalized not in seen:
                seen.add(q_normalized)
                all_queries.append(q.strip())
        
        return TransformResult(
            original_query=query,
            strategy=TransformStrategy.COMBINED,
            expanded_queries=all_queries,
        )


# 全局单例
_query_transformer: Optional[QueryTransformer] = None


def get_query_transformer(model: str = None) -> QueryTransformer:
    """获取查询变换器单例"""
    global _query_transformer
    if _query_transformer is None or (model and model != _query_transformer.model):
        _query_transformer = QueryTransformer(model=model)
    return _query_transformer
