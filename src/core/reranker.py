"""Reranker 模块

使用 Cross-Encoder 对检索结果进行重排序，提高搜索精度。
"""

import logging
import os
import threading
from typing import List, Tuple, Optional

from src.rag_api.models.schemas import SearchResult

logger = logging.getLogger(__name__)

# 设置 HuggingFace 镜像（中国用户）
if not os.environ.get('HF_ENDPOINT'):
    os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'


class Reranker:
    """重排序器
    
    使用 Cross-Encoder 对候选结果进行精细打分和重排序。
    支持：
    - 多种预训练模型
    - 批量处理
    - 缓存优化
    """
    
    # 可用的 reranker 模型
    AVAILABLE_MODELS = {
        "bge-reranker-v2-m3": "BAAI/bge-reranker-v2-m3",  # 多语言，推荐
        "bge-reranker-base": "BAAI/bge-reranker-base",  # 英文，快速
        "bge-reranker-large": "BAAI/bge-reranker-large",  # 英文，高精度
        "cohere-rerank": "cohere",  # API 调用
    }
    
    def __init__(
        self, 
        model_name: str = "bge-reranker-v2-m3",
        device: str = "cpu",
        cache_dir: Optional[str] = None
    ):
        """初始化 Reranker
        
        Args:
            model_name: 模型名称，可以是预定义名称或 HuggingFace 模型 ID
            device: 运行设备 (cpu/cuda/mps)
            cache_dir: 模型缓存目录
        """
        self.model_name = model_name
        self.device = device
        self.cache_dir = cache_dir
        self._model = None
        self._initialized = False
        self._init_attempted = False  # 是否尝试过初始化
        self._lock = threading.Lock()
        
    def _ensure_model(self) -> None:
        """确保模型已加载"""
        if self._initialized:
            return
        
        with self._lock:
            # 双重检查
            if self._initialized:
                return
            
            # 如果已尝试过且失败，不再重试
            if self._init_attempted and self._model is None:
                logger.debug("Reranker 模型之前加载失败，跳过重试")
                return
            
            self._init_attempted = True
            
            # 检查是否是预定义模型
            model_id = self.AVAILABLE_MODELS.get(self.model_name, self.model_name)
            
            # Cohere 是 API 模型，跳过本地加载
            if model_id == "cohere":
                logger.info("使用 Cohere Rerank API")
                self._initialized = True
                return
            
            try:
                from sentence_transformers import CrossEncoder
                
                logger.info(f"加载 Reranker 模型: {model_id} (设备: {self.device})")
                
                self._model = CrossEncoder(
                    model_id,
                    max_length=512,
                    device=self.device,
                )
                
                self._initialized = True
                logger.info("Reranker 模型加载完成")
                
            except Exception as e:
                logger.warning(f"加载 Reranker 模型失败: {e}")
                logger.warning("重排序功能将不可用，搜索结果将使用原始排序")
                self._model = None
                self._initialized = True  # 标记为已初始化（但失败）
    
    def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: int = 20,
        batch_size: int = 32,
    ) -> List[SearchResult]:
        """对搜索结果进行重排序
        
        Args:
            query: 查询字符串
            results: 候选搜索结果
            top_k: 返回结果数量
            batch_size: 批处理大小
            
        Returns:
            重排序后的结果列表
        """
        if not results:
            return []
        
        # 确保模型加载
        self._ensure_model()
        
        # 如果没有本地模型，返回原结果
        if self._model is None:
            logger.warning("Reranker 模型不可用，返回原始排序")
            return results[:top_k]
        
        try:
            # 构建查询-文档对
            pairs = [(query, r.content) for r in results]
            
            # 批量打分
            scores = self._model.predict(pairs, batch_size=batch_size)
            
            # 更新分数并排序
            for i, score in enumerate(scores):
                results[i].score = float(score)
                results[i].search_type = "reranked"
            
            # 按分数降序排序
            results.sort(key=lambda x: x.score, reverse=True)
            
            return results[:top_k]
            
        except Exception as e:
            logger.error(f"重排序失败: {e}")
            return results[:top_k]
    
    def rerank_with_threshold(
        self,
        query: str,
        results: List[SearchResult],
        top_k: int = 20,
        score_threshold: float = 0.0,
    ) -> List[SearchResult]:
        """带阈值过滤的重排序
        
        Args:
            query: 查询字符串
            results: 候选搜索结果
            top_k: 返回结果数量
            score_threshold: 分数阈值
            
        Returns:
            重排序并过滤后的结果列表
        """
        reranked = self.rerank(query, results, top_k=top_k * 2)
        
        if score_threshold > 0:
            reranked = [r for r in reranked if r.score >= score_threshold]
        
        return reranked[:top_k]
    
    def score_single(self, query: str, content: str) -> float:
        """对单个查询-文档对打分
        
        Args:
            query: 查询字符串
            content: 文档内容
            
        Returns:
            相关性分数
        """
        self._ensure_model()
        
        if self._model is None:
            return 0.0
        
        try:
            score = self._model.predict([(query, content)])
            return float(score[0])
        except Exception as e:
            logger.error(f"打分失败: {e}")
            return 0.0


class RerankerManager:
    """Reranker 管理器
    
    提供全局 Reranker 实例管理和懒加载。
    线程安全。
    """
    
    _instance: Optional[Reranker] = None
    _config: dict = {}
    _lock = threading.Lock()
    
    @classmethod
    def get_reranker(
        cls,
        model_name: str = "bge-reranker-v2-m3",
        device: str = "cpu",
    ) -> Reranker:
        """获取全局 Reranker 实例"""
        config = {"model_name": model_name, "device": device}
        
        with cls._lock:
            if cls._instance is None or cls._config != config:
                cls._instance = Reranker(model_name=model_name, device=device)
                cls._config = config
        
        return cls._instance
    
    @classmethod
    def clear(cls) -> None:
        """清除实例"""
        with cls._lock:
            cls._instance = None
            cls._config = {}


# 便捷函数
def get_reranker(model_name: str = "bge-reranker-v2-m3") -> Reranker:
    """获取 Reranker 实例"""
    return RerankerManager.get_reranker(model_name=model_name)