"""解析队列路由 — P4 新增

提供解析队列的管理和查询接口。
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.parse_dispatcher import ParseDispatcher
from src.core.parse_worker import ParseWorker
from src.rag_api.models.database import ParseQueue, get_db
from src.rag_api.models.schemas import APIResponse

router = APIRouter()


class EnqueueRequest(BaseModel):
    """手动入队请求"""
    file_path: str
    project_id: str
    file_type: str = "document"
    priority: int = 10  # 手动上传默认优先级更高


class RetryRequest(BaseModel):
    """重试请求"""
    task_ids: list[str] = []


# ============================================================================
# 队列管理
# ============================================================================

@router.get("/status", response_model=APIResponse)
async def get_queue_status(db: Session = Depends(get_db)):
    """获取解析队列状态统计"""
    from sqlalchemy import func

    stats = {}
    for status in ["pending", "running", "done", "failed", "skipped"]:
        count = db.query(func.count(ParseQueue.id)).filter(
            ParseQueue.status == status
        ).scalar()
        stats[status] = count

    stats["total"] = sum(stats.values())

    return APIResponse(success=True, data=stats)


@router.get("/tasks", response_model=APIResponse)
async def list_tasks(
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """列出队列任务"""
    query = db.query(ParseQueue)

    if status:
        query = query.filter(ParseQueue.status == status)
    if project_id:
        query = query.filter(ParseQueue.project_id == project_id)

    total = query.count()
    tasks = query.order_by(ParseQueue.created_at.desc()).offset(skip).limit(limit).all()

    return APIResponse(success=True, data={
        "total": total,
        "tasks": [
            {
                "id": t.id,
                "file_path": t.file_path,
                "file_type": t.file_type,
                "project_id": t.project_id,
                "status": t.status,
                "priority": t.priority,
                "retry_count": t.retry_count,
                "error_msg": t.error_msg,
                "worker_id": t.worker_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
            }
            for t in tasks
        ],
    })


@router.post("/enqueue", response_model=APIResponse)
async def enqueue_task(request: EnqueueRequest):
    """手动将文件加入解析队列"""
    file_path = Path(request.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=400, detail=f"文件不存在: {request.file_path}")

    task_id = ParseWorker.enqueue(
        file_path=file_path,
        project_id=request.project_id,
        file_type=request.file_type,
        priority=request.priority,
    )

    return APIResponse(success=True, data={"task_id": task_id}, message="已入队")


@router.post("/retry", response_model=APIResponse)
async def retry_failed_tasks(request: RetryRequest, db: Session = Depends(get_db)):
    """重试失败的任务"""
    query = db.query(ParseQueue).filter(ParseQueue.status == "failed")

    if request.task_ids:
        query = query.filter(ParseQueue.id.in_(request.task_ids))

    tasks = query.all()
    count = 0
    for task in tasks:
        task.status = "pending"
        task.retry_count = 0
        task.worker_id = None
        task.started_at = None
        task.error_msg = None
        count += 1

    db.commit()

    return APIResponse(success=True, data={"retried": count}, message=f"已重试 {count} 个任务")


@router.delete("/tasks/{task_id}", response_model=APIResponse)
async def delete_task(task_id: str, db: Session = Depends(get_db)):
    """删除队列任务"""
    task = db.query(ParseQueue).filter(ParseQueue.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    db.delete(task)
    db.commit()

    return APIResponse(success=True, message="任务已删除")


@router.delete("/clear", response_model=APIResponse)
async def clear_completed(db: Session = Depends(get_db)):
    """清理已完成/失败/跳过的任务"""
    deleted = db.query(ParseQueue).filter(
        ParseQueue.status.in_(["done", "failed", "skipped"])
    ).delete()
    db.commit()

    return APIResponse(success=True, data={"deleted": deleted}, message=f"已清理 {deleted} 个任务")
