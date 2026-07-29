"""解析器信息路由 — P4 新增

提供解析器能力和状态查询接口。
"""

from fastapi import APIRouter

from src.core.parse_dispatcher import ParseDispatcher
from src.rag_api.models.schemas import APIResponse

router = APIRouter()

dispatcher = ParseDispatcher()


@router.get("", response_model=APIResponse)
async def list_parsers():
    """列出所有解析器及其支持的格式"""
    parsers = dispatcher.list_parsers()
    return APIResponse(success=True, data=parsers)


@router.get("/formats", response_model=APIResponse)
async def list_supported_formats():
    """列出所有支持的文件扩展名"""
    exts = dispatcher.get_supported_extensions()
    return APIResponse(success=True, data={
        "extensions": exts,
        "count": len(exts),
    })


@router.get("/check/{extension}", response_model=APIResponse)
async def check_format_support(extension: str):
    """检查某个扩展名是否支持"""
    from pathlib import Path
    test_path = Path(f"test.{extension.lstrip('.')}")
    parser_name = dispatcher.find_parser(test_path)

    if parser_name:
        config = dispatcher.get_parser_config(parser_name)
        return APIResponse(success=True, data={
            "supported": True,
            "parser": parser_name,
            "cli": config["cli"],
            "description": config.get("description", ""),
        })
    else:
        return APIResponse(success=True, data={
            "supported": False,
        })
