"""项目路由"""

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.rag_api.models.database import get_db, Project, Document, Chunk
from src.rag_api.models.schemas import (
    APIResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)
from src.services.project_service import ProjectService
from src.services.document_service import DocumentService

router = APIRouter()

# revectorize 防重复调用锁（模块级）
_revectorize_locks: dict[str, bool] = {}


class CleanOrphanRequest(BaseModel):
    """清理孤儿项目请求"""
    dry_run: bool = False


@router.post("", response_model=APIResponse)
async def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db),
):
    """创建项目"""
    service = ProjectService(db)
    try:
        result = service.create_project(project)
        return APIResponse(success=True, data=result, message="项目创建成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建项目失败: {str(e)}")


@router.get("", response_model=APIResponse)
async def list_projects(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """列出所有项目"""
    service = ProjectService(db)
    projects = service.list_projects(skip=skip, limit=limit)
    return APIResponse(success=True, data=projects)


@router.get("/{project_id}", response_model=APIResponse)
async def get_project(
    project_id: str,
    db: Session = Depends(get_db),
):
    """获取项目详情"""
    service = ProjectService(db)
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return APIResponse(success=True, data=project)


@router.put("/{project_id}", response_model=APIResponse)
async def update_project(
    project_id: str,
    project_update: ProjectUpdate,
    db: Session = Depends(get_db),
):
    """更新项目"""
    service = ProjectService(db)
    try:
        result = service.update_project(project_id, project_update)
        return APIResponse(success=True, data=result, message="项目更新成功")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新项目失败: {str(e)}")


@router.delete("/{project_id}", response_model=APIResponse)
async def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
):
    """删除项目（连同所有数据）"""
    service = ProjectService(db)
    try:
        service.delete_project(project_id)
        return APIResponse(success=True, message="项目删除成功")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除项目失败: {str(e)}")


@router.post("/clean-orphan", response_model=APIResponse)
async def clean_orphan_projects(
    request: CleanOrphanRequest,
    db: Session = Depends(get_db),
):
    """
    清理孤儿项目（文件夹已删除但数据库记录存在）
    
    扫描所有项目，检查其对应的文件夹是否存在。
    如果文件夹已删除，则删除项目及其所有数据（文档、分块、向量）。
    
    Args:
        request: dry_run=True 只显示不删除，dry_run=False 实际删除
    """
    from src.core.vector_store import get_vector_store
    
    projects_root = Path("~/Projects").expanduser()
    vector_store = get_vector_store()
    
    try:
        # 获取所有项目
        projects = db.query(Project).all()
        
        orphan_projects = []
        
        for project in projects:
            # 检查项目文件夹是否存在
            if project.folder_path:
                folder = Path(project.folder_path)
            else:
                folder = projects_root / project.name
            
            if not folder.exists():
                doc_count = db.query(Document).filter(
                    Document.project_id == str(project.id)
                ).count()
                chunk_count = db.query(Chunk).filter(
                    Chunk.project_id == str(project.id)
                ).count()
                
                orphan_projects.append({
                    "id": str(project.id),
                    "name": project.name,
                    "folder_path": project.folder_path,
                    "document_count": doc_count,
                    "chunk_count": chunk_count,
                })
        
        # 如果是 dry_run，只返回列表
        if request.dry_run:
            return APIResponse(
                success=True,
                data={"orphan_projects": orphan_projects, "count": len(orphan_projects)},
                message=f"发现 {len(orphan_projects)} 个孤儿项目"
            )
        
        # 实际删除
        deleted_count = 0
        for p in orphan_projects:
            project_id = p["id"]
            
            # 删除向量集合
            try:
                vector_store.delete_collection(project_id)
            except Exception:
                pass  # 集合可能不存在
            
            # 删除数据库记录（级联删除文档和分块）
            project_obj = db.query(Project).filter(Project.id == project_id).first()
            if project_obj:
                db.delete(project_obj)
                db.commit()
                deleted_count += 1
        
        return APIResponse(
            success=True,
            data={"orphan_projects": orphan_projects, "deleted_count": deleted_count},
            message=f"已清理 {deleted_count} 个孤儿项目"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}")


@router.post("/{project_id}/revectorize", response_model=APIResponse)
async def revectorize_pending_chunks(
    project_id: str,
    batch_size: int = 200,
    max_chunks: int = 10000,
    db: Session = Depends(get_db),
):
    """
    批量处理 pending 状态的 chunks 向量化
    
    用于恢复因 API 崩溃等原因卡在 pending 状态的 chunks。
    在后台线程中执行，立即返回。
    
    Args:
        project_id: 项目 ID
        batch_size: 每批处理的 chunk 数（默认 200）
        max_chunks: 最多处理的 chunk 总数（默认 10000）
    """
    import threading
    
    # 防重复调用：如果该项目已有 revectorize 在运行，直接返回
    if _revectorize_locks.get(project_id):
        return APIResponse(
            success=False,
            message=f"项目 {project_id} 已有 revectorize 任务在运行中"
        )
    
    # 检查项目是否存在
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 统计 pending 数量
    pending_count = db.query(Chunk).filter(
        Chunk.project_id == project_id,
        Chunk.vector_status == "pending",
    ).count()
    
    if pending_count == 0:
        return APIResponse(
            success=True,
            data={"pending_count": 0},
            message="没有待处理的 chunks"
        )
    
    # 设置运行标志
    _revectorize_locks[project_id] = True
    
    # 后台执行
    def _run():
        try:
            svc = DocumentService()
            result = svc.batch_vectorize_pending(
                project_id=project_id,
                batch_size=batch_size,
                max_chunks=max_chunks,
            )
            logger.info(
                f"revectorize 完成: 项目 {project_id}, "
                f"处理 {result['processed']}, 成功 {result['success']}, "
                f"失败 {result['failed']}, 剩余 {result['remaining']}"
            )
        except Exception as e:
            logger.error(f"revectorize 失败: {project_id}: {e}")
        finally:
            _revectorize_locks[project_id] = False
    
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    
    return APIResponse(
        success=True,
        data={"pending_count": pending_count, "batch_size": batch_size, "max_chunks": max_chunks},
        message=f"已启动后台向量化任务，待处理 chunks: {pending_count}"
    )
