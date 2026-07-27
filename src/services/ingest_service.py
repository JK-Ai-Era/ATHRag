"""文档摄取服务

提供 HTTP API 供手动上传文档。
实际的文档处理逻辑委托给 DocumentService。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from src.rag_api.config import get_settings
from src.rag_api.models.database import Document as DocumentModel
from src.services.document_service import DocumentService

settings = get_settings()
logger = logging.getLogger(__name__)


class IngestService:
    """文档摄取服务"""
    
    def __init__(self, db: Session):
        self.db = db
        self.doc_service = DocumentService(db)
    
    async def upload_document(
        self,
        project_id: str,
        file: UploadFile,
        metadata: Optional[str] = None,
    ) -> Dict[str, Any]:
        """上传并处理文档"""
        # 检查项目是否存在（支持 project_id 或 project_name）
        from src.rag_api.models.database import Project
        
        project = self.db.query(Project).filter(
            (Project.id == project_id) | 
            (Project.name == project_id)
        ).first()
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        
        # 如果传入的是名称，更新为实际的 project_id
        project_id = project.id
        
        # 保存文件
        filename = file.filename
        file_ext = Path(filename).suffix.lower()
        
        project_dir = settings.PROJECTS_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = project_dir / filename
        
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # 解析元数据
        meta_dict = {}
        if metadata:
            try:
                meta_dict = json.loads(metadata)
            except json.JSONDecodeError:
                pass
        
        # 确定文档类型
        doc_type = self._get_doc_type(file_ext)
        
        # 使用 DocumentService 处理文档
        result = self.doc_service.process_document(
            file_path=file_path,
            doc_type=doc_type,
            project_id=project_id,
            filename=filename,
            metadata=meta_dict
        )
        
        if result.success:
            return {
                "id": result.document_id,
                "filename": filename,
                "status": "completed",
                "chunk_count": result.vector_count,
            }
        else:
            return {
                "id": result.document_id,
                "filename": filename,
                "status": "failed",
                "error": result.error_message,
            }
    
    async def reindex_document(self, project_id: str, document_id: str) -> Dict[str, Any]:
        """重新索引文档"""
        doc = self.db.query(DocumentModel).filter(
            DocumentModel.id == document_id,
            DocumentModel.project_id == project_id,
        ).first()
        
        if not doc:
            raise ValueError("文档不存在")
        
        # 先删除旧数据
        self.doc_service.delete_document(document_id, delete_file=False)
        
        # 重新处理
        file_path = settings.PROJECTS_DIR / project_id / doc.filename
        doc_type = doc.doc_type
        
        result = self.doc_service.process_document(
            file_path=file_path,
            doc_type=doc_type,
            project_id=project_id,
            document_id=document_id,
            filename=doc.filename
        )
        
        return {
            "id": doc.id,
            "status": "completed" if result.success else "failed",
            "chunk_count": result.vector_count,
        }
    
    def delete_document(self, project_id: str, document_id: str) -> None:
        """删除文档"""
        doc = self.db.query(DocumentModel).filter(
            DocumentModel.id == document_id,
            DocumentModel.project_id == project_id,
        ).first()
        
        if not doc:
            raise ValueError("文档不存在")
        
        # 使用 DocumentService 删除
        success = self.doc_service.delete_document(document_id, delete_file=True)
        
        if not success:
            raise RuntimeError("删除文档失败")
    
    def _get_doc_type(self, ext: str) -> str:
        """获取文档类型"""
        type_map = {
            ".pdf": "pdf",
            ".docx": "docx",
            ".doc": "docx",
            ".xlsx": "xlsx",
            ".xls": "xlsx",
            ".pptx": "pptx",
            ".ppt": "pptx",
            ".png": "image",
            ".jpg": "image",
            ".jpeg": "image",
            ".gif": "image",
            ".bmp": "image",
            ".tiff": "image",
            ".webp": "image",
            ".md": "md",
            ".txt": "txt",
            ".py": "code",
            ".js": "code",
            ".ts": "code",
            ".java": "code",
            ".go": "code",
            ".rs": "code",
            ".cpp": "code",
            ".c": "code",
            ".h": "code",
        }
        return type_map.get(ext, "other")
