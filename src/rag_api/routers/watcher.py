"""文件监控 API 路由

提供监控启停、状态查询和统计接口。
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.rag_api.models.database import get_db
from src.watcher.manager import get_watcher_manager

logger = logging.getLogger(__name__)
router = APIRouter()


# ========== 请求/响应模型 ==========

class WatcherDataResponse(BaseModel):
    """统一的数据包装响应"""
    success: bool
    data: Dict[str, Any]


class WatcherStartResponse(BaseModel):
    """启动监控响应"""
    success: bool
    message: str
    data: Dict[str, Any]


class WatcherStopResponse(BaseModel):
    """停止监控响应"""
    success: bool
    message: str
    data: Dict[str, Any]


class WatcherStatusResponse(BaseModel):
    """监控状态响应（已废弃，使用 WatcherDataResponse）"""
    is_running: bool
    started_at: Optional[str] = None
    stopped_at: Optional[str] = None
    projects_root: str
    watched_projects: list[str]
    error_count: int
    recent_errors: list[str]


class WatcherStatsResponse(BaseModel):
    """监控统计响应（已废弃，使用 WatcherDataResponse）"""
    global_stats: Dict[str, Any]
    projects: Dict[str, Dict[str, Any]]


class WatcherActionResponse(BaseModel):
    """通用操作响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class WatcherRefreshRequest(BaseModel):
    """刷新监控请求"""
    project_name: str = Field(..., description="项目名称")
    watcher_enabled: bool = Field(..., description="是否启用监控")


# ========== API 端点 ==========

@router.post("/watcher/start", response_model=WatcherStartResponse)
async def start_watcher(db: Session = Depends(get_db)):
    """
    启动文件系统监控
    
    开始监控 ~/Projects/ 目录下的所有项目，自动同步文件变更到 RAG。
    """
    try:
        manager = get_watcher_manager()
        result = manager.start()
        
        return WatcherStartResponse(
            success=result["success"],
            message=result["message"],
            data=result["status"],
        )
    except Exception as e:
        logger.error(f"Error starting watcher: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start watcher: {str(e)}")


@router.post("/watcher/stop", response_model=WatcherStopResponse)
async def stop_watcher(db: Session = Depends(get_db)):
    """
    停止文件系统监控
    
    停止所有文件系统监控，不再自动同步变更。
    """
    try:
        manager = get_watcher_manager()
        result = manager.stop()
        
        return WatcherStopResponse(
            success=result["success"],
            message=result["message"],
            data=result["status"],
        )
    except Exception as e:
        logger.error(f"Error stopping watcher: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop watcher: {str(e)}")


@router.get("/watcher/status", response_model=WatcherDataResponse)
async def get_watcher_status(db: Session = Depends(get_db)):
    """
    获取监控状态
    
    返回当前监控器的运行状态，包括是否在运行、监控的项目列表等。
    """
    try:
        manager = get_watcher_manager()
        status = manager.get_status()
        
        return WatcherDataResponse(
            success=True,
            data=status,
        )
    except Exception as e:
        logger.error(f"Error getting watcher status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.get("/watcher/stats", response_model=WatcherDataResponse)
async def get_watcher_stats(db: Session = Depends(get_db)):
    """
    获取同步统计信息
    
    返回各项目的文件同步统计，包括创建、更新、删除的文件数量等。
    """
    try:
        manager = get_watcher_manager()
        stats = manager.get_stats()
        
        return WatcherDataResponse(
            success=True,
            data={
                "global_stats": stats["global"],
                "projects": stats["projects"],
            },
        )
    except Exception as e:
        logger.error(f"Error getting watcher stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.post("/watcher/reset-stats", response_model=WatcherActionResponse)
async def reset_watcher_stats(
    project_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    重置统计信息
    
    重置文件同步的统计计数器。可以指定项目名称，不指定则重置所有项目。
    
    Args:
        project_name: 可选，指定要重置的项目名称
    """
    try:
        manager = get_watcher_manager()
        result = manager.reset_stats(project_name)
        
        return WatcherActionResponse(
            success=result["success"],
            message=result["message"],
        )
    except Exception as e:
        logger.error(f"Error resetting stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset stats: {str(e)}")


@router.post("/watcher/scan", response_model=WatcherActionResponse)
async def force_scan(
    project_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    强制扫描项目
    
    强制重新扫描项目目录，同步所有文件。可以指定项目名称，不指定则扫描所有项目。
    
    Args:
        project_name: 可选，指定要扫描的项目名称
    """
    try:
        manager = get_watcher_manager()
        result = manager.force_scan(project_name)
        
        return WatcherActionResponse(
            success=result["success"],
            message=result["message"],
            data={
                "scanned": result.get("scanned", []),
                "errors": result.get("errors", []),
            } if result.get("scanned") or result.get("errors") else None,
        )
    except Exception as e:
        logger.error(f"Error scanning projects: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to scan: {str(e)}")


@router.post("/watcher/refresh", response_model=WatcherActionResponse)
async def refresh_project_watch(
    request: WatcherRefreshRequest,
    db: Session = Depends(get_db)
):
    """
    刷新项目监控状态
    
    根据 watcher_enabled 状态即时添加或移除项目监控，无需重启 watcher 服务。
    
    适用场景：
    - 修改数据库 watcher_enabled 后需要即时生效
    - 动态调整监控项目列表
    
    Args:
        request: 包含 project_name 和 watcher_enabled 的请求体
    """
    try:
        manager = get_watcher_manager()
        result = manager.refresh_project_watch(
            request.project_name, 
            request.watcher_enabled
        )
        
        return WatcherActionResponse(
            success=result["success"],
            message=result["message"],
        )
    except Exception as e:
        logger.error(f"Error refreshing project watch: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh: {str(e)}")


@router.post("/watcher/sync-all", response_model=WatcherActionResponse)
async def sync_all_watcher_enabled(db: Session = Depends(get_db)):
    """
    同步所有 watcher_enabled 项目
    
    扫描数据库中所有 watcher_enabled=1 的项目，确保 watcher 监控状态一致。
    
    适用场景：
    - watcher 启动后数据库配置发生变化
    - 手动修改数据库后批量同步
    """
    try:
        from src.rag_api.models.database import Project
        
        manager = get_watcher_manager()
        
        # 获取所有 watcher_enabled=1 的项目
        enabled_projects = db.query(Project).filter(
            Project.watcher_enabled == 1
        ).all()
        
        synced_count = 0
        for project in enabled_projects:
            result = manager.refresh_project_watch(project.name, True)
            if result["success"]:
                synced_count += 1
                logger.info(f"Synced project: {project.name}")
        
        return WatcherActionResponse(
            success=True,
            message=f"已同步 {synced_count} 个项目的监控状态",
            data={"synced_count": synced_count},
        )
    except Exception as e:
        logger.error(f"Error syncing all watcher enabled: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync: {str(e)}")
