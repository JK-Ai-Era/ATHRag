"""RAG API 主模块"""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.rag_api.auth import get_current_active_user
from src.rag_api.config import get_settings
from src.rag_api.routers import auth, documents, projects, search, watcher

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时：检查是否自动启动 Watcher
    auto_start = os.getenv("WATCHER_AUTO_START", "true").lower() == "true"
    if auto_start:
        try:
            from src.watcher.manager import get_watcher_manager
            manager = get_watcher_manager()
            if not manager.get_status()["is_running"]:
                result = manager.start()
                if result["success"]:
                    print(f"[Watcher] Auto-started: {result['message']}")
                else:
                    print(f"[Watcher] Auto-start failed: {result['message']}")
        except Exception as e:
            print(f"[Watcher] Auto-start error: {e}")
    
    yield
    
    # 关闭时：停止 Watcher
    try:
        from src.watcher.manager import get_watcher_manager
        manager = get_watcher_manager()
        if manager.get_status()["is_running"]:
            manager.stop()
            print("[Watcher] Stopped on shutdown")
    except Exception as e:
        print(f"[Watcher] Shutdown error: {e}")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.APP_DEBUG,
    description="本地知识库RAG系统API",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://rag.kwok.vip",
        "https://rag.kwok.vip/",
        "http://localhost:3000",
        "http://localhost:3090",
        "http://localhost:4000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3090",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

# 公开路由（无需认证）
app.include_router(auth.router, prefix="/api/v1/auth", tags=["authentication"])

# 受保护的路由
# 注册路由 - 注意顺序：更具体的路由先注册
app.include_router(
    documents.router,
    prefix="/api/v1/projects",
    tags=["documents"],
    dependencies=[Depends(get_current_active_user)],
)
app.include_router(
    projects.router,
    prefix="/api/v1/projects",
    tags=["projects"],
    dependencies=[Depends(get_current_active_user)],
)
app.include_router(
    search.router,
    prefix="/api/v1",
    tags=["search"],
    dependencies=[Depends(get_current_active_user)],
)
app.include_router(
    watcher.router,
    prefix="/api/v1",
    tags=["watcher"],
    dependencies=[Depends(get_current_active_user)],
)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "auth_enabled": settings.AUTH_ENABLED,
    }


@app.get("/health/detailed")
async def detailed_health_check():
    """详细健康检查 - 检查所有依赖服务"""
    from src.core.embedding import EmbeddingService
    from src.core.vector_store import VectorStore
    from src.watcher.manager import get_watcher_manager
    
    result = {
        "api": "ok",
        "version": settings.APP_VERSION,
        "services": {},
    }
    
    # 检查数据库
    try:
        from src.rag_api.models.database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        result["services"]["database"] = "ok"
    except Exception as e:
        result["services"]["database"] = f"error: {str(e)}"
    
    # 检查 Qdrant
    try:
        vector_store = VectorStore()
        vector_store.client.get_collections()
        result["services"]["qdrant"] = "ok"
    except Exception as e:
        result["services"]["qdrant"] = f"error: {str(e)}"
    
    # 检查 Ollama
    try:
        embedding = EmbeddingService()
        if await embedding.health_check():
            result["services"]["ollama"] = "ok"
        else:
            result["services"]["ollama"] = "unhealthy"
        await embedding.close()
    except Exception as e:
        result["services"]["ollama"] = f"error: {str(e)}"
    
    # 检查 Watcher
    try:
        watcher_manager = get_watcher_manager()
        watcher_status = watcher_manager.get_status()
        result["services"]["watcher"] = "ok" if watcher_status["is_running"] else "stopped"
        result["watcher"] = watcher_status
    except Exception as e:
        result["services"]["watcher"] = f"error: {str(e)}"
    
    # 总体状态
    all_ok = all(v == "ok" for v in result["services"].values())
    result["overall"] = "ok" if all_ok else "degraded"
    
    return result


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "auth_enabled": settings.AUTH_ENABLED,
    }


def main():
    """启动服务"""
    import uvicorn

    uvicorn.run(
        "src.rag_api.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_DEBUG,
        log_level=settings.APP_LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
