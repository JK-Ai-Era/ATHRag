"""项目服务"""

from typing import List, Optional

from sqlalchemy.orm import Session

from src.rag_api.models.database import Project as ProjectModel
from src.rag_api.models.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from src.core.vector_store import get_vector_store


def _notify_watcher_project_changed(project_name: str, watcher_enabled: bool) -> None:
    """
    通知 watcher 项目监控状态发生变化
    
    Args:
        project_name: 项目名称
        watcher_enabled: 新的监控状态
    """
    try:
        # 延迟导入避免循环依赖
        from src.watcher.manager import get_watcher_manager
        manager = get_watcher_manager()
        result = manager.refresh_project_watch(project_name, watcher_enabled)
        if result["success"]:
            print(f"[Watcher] {result['message']}")
    except Exception as e:
        # 通知失败不应影响主流程
        print(f"[Watcher] Failed to notify watcher: {e}")


class ProjectService:
    """项目服务类"""
    
    def __init__(self, db: Session):
        self.db = db
        self.vector_store = get_vector_store()
    
    def create_project(self, project: ProjectCreate) -> ProjectResponse:
        """创建项目"""
        # 检查项目名是否已存在
        existing = self.db.query(ProjectModel).filter(
            ProjectModel.name == project.name
        ).first()
        if existing:
            raise ValueError(f"项目名称 '{project.name}' 已存在")
        
        # 创建项目（默认关闭 watcher）
        db_project = ProjectModel(
            name=project.name,
            description=project.description,
            watcher_enabled=0,  # 新建项目默认关闭同步
        )
        self.db.add(db_project)
        self.db.commit()
        self.db.refresh(db_project)
        
        # 创建 Qdrant Collection
        self.vector_store.create_collection(str(db_project.id))
        
        return ProjectResponse.model_validate(db_project)
    
    def list_projects(self, skip: int = 0, limit: int = 100) -> List[ProjectResponse]:
        """列出所有项目"""
        projects = self.db.query(ProjectModel).offset(skip).limit(limit).all()
        return [ProjectResponse.model_validate(p) for p in projects]
    
    def get_project(self, project_id: str) -> Optional[ProjectResponse]:
        """获取项目详情"""
        project = self.db.query(ProjectModel).filter(
            ProjectModel.id == project_id
        ).first()
        if project:
            return ProjectResponse.model_validate(project)
        return None
    
    def update_project(
        self, project_id: str, project_update: ProjectUpdate
    ) -> ProjectResponse:
        """更新项目（支持 project_id 或 project_name）"""
        project = self.db.query(ProjectModel).filter(
            (ProjectModel.id == project_id) | 
            (ProjectModel.name == project_id)
        ).first()
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        
        # 检查新名称是否冲突
        if project_update.name and project_update.name != project.name:
            existing = self.db.query(ProjectModel).filter(
                ProjectModel.name == project_update.name
            ).first()
            if existing:
                raise ValueError(f"项目名称 '{project_update.name}' 已存在")
            project.name = project_update.name
        
        if project_update.description is not None:
            project.description = project_update.description
        
        watcher_enabled_changed = False
        new_watcher_enabled = None
        
        if project_update.watcher_enabled is not None:
            new_watcher_enabled = 1 if project_update.watcher_enabled else 0
            watcher_enabled_changed = (project.watcher_enabled != new_watcher_enabled)
            project.watcher_enabled = new_watcher_enabled
        
        self.db.commit()
        
        # 如果 watcher_enabled 发生变化，通知 watcher
        if watcher_enabled_changed and new_watcher_enabled is not None:
            _notify_watcher_project_changed(
                project.name, 
                bool(new_watcher_enabled)
            )
        self.db.refresh(project)
        
        return ProjectResponse.model_validate(project)
    
    def delete_project(self, project_id: str) -> None:
        """删除项目（支持 project_id 或 project_name）"""
        project = self.db.query(ProjectModel).filter(
            (ProjectModel.id == project_id) | 
            (ProjectModel.name == project_id)
        ).first()
        if not project:
            raise ValueError(f"项目不存在: {project_id}")
        
        actual_id = str(project.id)
        
        # 删除 Qdrant Collection（主 Collection + 摘要 Collection）
        self.vector_store.delete_collection(actual_id)
        try:
            from src.core.hierarchical_index import HierarchicalIndex
            hi = HierarchicalIndex()
            summary_collection = hi._get_summary_collection_name(actual_id)
            self.vector_store.client.delete_collection(summary_collection)
        except Exception as e:
            logger.warning(f"删除摘要 Collection 失败（可能不存在）: {e}")
        
        # 删除 BM25 索引文件
        try:
            import shutil
            bm25_path = settings.PROJECTS_DIR / actual_id / "bm25_index.pkl"
            if bm25_path.exists():
                bm25_path.unlink()
                logger.debug(f"已删除 BM25 索引: {bm25_path}")
            # 清除内存中的 BM25 缓存
            from src.core.bm25_index import bm25_manager
            bm25_manager.clear_cache(actual_id)
        except Exception as e:
            logger.warning(f"删除 BM25 索引失败: {e}")
        
        # 删除项目文件目录
        try:
            project_dir = settings.PROJECTS_DIR / actual_id
            if project_dir.exists():
                import shutil
                shutil.rmtree(project_dir)
                logger.debug(f"已删除项目目录: {project_dir}")
        except Exception as e:
            logger.warning(f"删除项目目录失败: {e}")
        
        # 删除数据库记录（级联删除文档和分块）
        self.db.delete(project)
        self.db.commit()
    
    def list_documents(
        self, 
        project_id: str, 
        skip: int = 0, 
        limit: int = 100,
        filename: str = None,
    ):
        """列出项目下的文档
        
        Args:
            project_id: 项目 ID
            skip: 跳过数量（分页偏移）
            limit: 返回数量
            filename: 文件名搜索（模糊匹配）
        """
        from src.rag_api.models.database import Document
        from src.rag_api.models.schemas import DocumentResponse
        
        query = self.db.query(Document).filter(
            Document.project_id == project_id
        )
        
        # 文件名搜索（模糊匹配）
        if filename:
            query = query.filter(Document.filename.ilike(f"%{filename}%"))
        
        # 获取总数
        total = query.count()
        
        # 分页查询
        documents = query.offset(skip).limit(limit).all()
        
        return {
            "items": [DocumentResponse.model_validate(d) for d in documents],
            "total": total,
            "skip": skip,
            "limit": limit,
        }
    
    def get_document(self, document_id: str):
        """获取文档"""
        from src.rag_api.models.database import Document
        from src.rag_api.models.schemas import DocumentResponse
        
        doc = self.db.query(Document).filter(
            Document.id == document_id
        ).first()
        if doc:
            return DocumentResponse.model_validate(doc)
        return None
