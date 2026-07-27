"""搜索路由"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.rag_api.models.database import get_db
from src.rag_api.models.schemas import APIResponse, SearchRequest, SearchResponse
from src.services.search_service import SearchService

router = APIRouter()


@router.post("/search", response_model=APIResponse)
async def search(
    request: SearchRequest,
    db: Session = Depends(get_db),
):
    """搜索知识库"""
    service = SearchService(db)
    try:
        results = await service.search(request)
        return APIResponse(success=True, data=results)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@router.get("/search/simple", response_model=APIResponse)
async def simple_search(
    project_id: str,
    q: str,
    top_k: int = 20,
    db: Session = Depends(get_db),
):
    """简单搜索（GET方式）"""
    service = SearchService(db)
    try:
        request = SearchRequest(
            project_id=project_id,
            query=q,
            top_k=top_k,
        )
        results = await service.search(request)
        return APIResponse(success=True, data=results)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")
