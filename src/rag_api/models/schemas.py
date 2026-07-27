"""Pydantic 模型定义"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class DocumentType(str, Enum):
    """文档类型"""
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    IMAGE = "image"
    MD = "md"
    TXT = "txt"
    CODE = "code"
    OTHER = "other"


class SearchMode(str, Enum):
    """搜索模式"""
    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    HYBRID = "hybrid"
    HIERARCHICAL = "hierarchical"  # 层次化搜索（摘要→chunks）


# ========== 项目相关 ==========

class ProjectCreate(BaseModel):
    """创建项目请求"""
    name: str = Field(..., min_length=1, max_length=100, description="项目名称")
    description: Optional[str] = Field(None, max_length=500, description="项目描述")


class ProjectUpdate(BaseModel):
    """更新项目请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    watcher_enabled: Optional[bool] = Field(None, description="是否启用文件同步")


class ProjectResponse(BaseModel):
    """项目响应"""
    id: str
    name: str
    description: Optional[str]
    document_count: int = 0
    chunk_count: int = 0
    watcher_enabled: bool = False
    created_at: datetime
    updated_at: datetime

    @field_validator("watcher_enabled", mode="before")
    @classmethod
    def convert_watcher_enabled(cls, v):
        if isinstance(v, int):
            return bool(v)
        return v
    
    class Config:
        from_attributes = True


# ========== 文档相关 ==========

class DocumentUpload(BaseModel):
    """文档上传元数据"""
    filename: str
    content_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DocumentResponse(BaseModel):
    """文档响应"""
    id: str
    project_id: str
    filename: str
    doc_type: str
    file_size: int
    file_path: Optional[str] = None  # 原始文件路径
    chunk_count: int
    status: str  # pending, processing, completed, failed
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
    
    @classmethod
    def model_validate(cls, obj):
        """自定义验证，处理 metadata_json 字段"""
        import json
        data = {
            'id': obj.id,
            'project_id': obj.project_id,
            'filename': obj.filename,
            'doc_type': obj.doc_type,
            'file_size': obj.file_size,
            'file_path': obj.file_path if hasattr(obj, 'file_path') else None,
            'chunk_count': obj.chunk_count,
            'status': obj.status,
            'created_at': obj.created_at,
            'updated_at': obj.updated_at,
        }
        # 处理 metadata_json 字段
        if hasattr(obj, 'metadata_json') and obj.metadata_json:
            try:
                data['metadata'] = json.loads(obj.metadata_json)
            except:
                data['metadata'] = {}
        else:
            data['metadata'] = {}
        return cls(**data)


class DocumentChunk(BaseModel):
    """文档分块"""
    id: str
    document_id: str
    content: str
    chunk_index: int
    metadata: Optional[Dict[str, Any]]


# ========== 搜索相关 ==========

class QueryTransformMode(str, Enum):
    """查询变换模式"""
    NONE = "none"           # 不变换
    HYDE = "hyde"           # 假设性文档嵌入
    MULTI_QUERY = "multi_query"  # 多角度扩展
    SUB_QUERY = "sub_query"     # 子问题分解
    COMBINED = "combined"       # 组合策略


class SearchRequest(BaseModel):
    """搜索请求"""
    project_id: str = Field(..., description="项目ID")
    query: str = Field(..., min_length=1, max_length=1000, description="查询内容")
    top_k: int = Field(20, ge=1, le=100, description="返回数量")
    offset: int = Field(0, ge=0, description="分页偏移量")
    search_mode: SearchMode = Field(SearchMode.HYBRID, description="搜索模式")
    score_threshold: Optional[float] = Field(None, ge=0, le=1, description="分数阈值")
    filters: Optional[Dict[str, Any]] = Field(None, description="过滤条件")
    rerank: bool = Field(True, description="是否重排序")
    query_transform: QueryTransformMode = Field(
        QueryTransformMode.NONE,
        description="查询变换模式：none/hyde/multi_query/sub_query/combined"
    )
    context_compress: bool = Field(
        False,
        description="是否启用上下文压缩（提取相关内容，减少噪音）"
    )


class SearchResult(BaseModel):
    """搜索结果"""
    content: str
    score: float
    search_type: str  # semantic, keyword
    metadata: Dict[str, Any]
    document_id: str
    chunk_id: str


class SearchResponse(BaseModel):
    """搜索响应"""
    query: str
    project_id: str
    results: List[SearchResult]
    total: int
    offset: int = 0
    limit: int = 0
    query_time_ms: int


# ========== 通用 ==========

class APIResponse(BaseModel):
    """通用API响应"""
    success: bool
    message: Optional[str] = None
    data: Optional[Any] = None


class PaginatedResponse(BaseModel):
    """分页响应"""
    items: List[Any]
    total: int
    page: int
    page_size: int
    pages: int
