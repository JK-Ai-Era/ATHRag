"""MCP Server - Model Context Protocol 实现

为 Agent 提供标准化的 ATHRag工具接口。
保留现有 API 不变，通过 MCP 协议暴露功能。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.types import TextContent, Tool

from src.rag_api.config import get_settings
from src.rag_api.models.schemas import SearchRequest
from src.services.project_service import ProjectService
from src.services.search_service import SearchService

settings = get_settings()

# 创建 MCP Server
server = Server(settings.MCP_SERVER_NAME)


def _get_db_session():
    """获取数据库会话上下文管理器
    
    使用示例:
        with _get_db_session() as db:
            # 使用 db
            pass
        # 自动关闭
    """
    from contextlib import contextmanager
    from src.rag_api.models.database import SessionLocal
    
    @contextmanager
    def _session():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    return _session()


def _find_project(db, project_identifier: str):
    """通过 ID 或名称查找项目"""
    project_service = ProjectService(db)
    
    # 先尝试按 ID 查找
    project_obj = project_service.get_project(project_identifier)
    if project_obj:
        return project_obj
    
    # 再尝试按名称查找
    projects = project_service.list_projects()
    for p in projects:
        if p.name == project_identifier:
            return p
    
    return None


@server.list_tools()
async def list_tools() -> List[Tool]:
    """列出可用工具"""
    return [
        Tool(
            name="rag_search",
            description="搜索本地知识库，返回相关文本片段",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "项目名称或ID",
                    },
                    "query": {
                        "type": "string",
                        "description": "搜索查询内容",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量，默认20，最大50",
                        "default": 20,
                    },
                },
                "required": ["project", "query"],
            },
        ),
        Tool(
            name="rag_list_projects",
            description="列出所有可用的知识库项目，包含文档数量和片段数量统计",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="rag_get_project_info",
            description="获取指定项目的详细信息",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "项目名称或ID",
                    },
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="rag_list_documents",
            description="列出项目下的所有文档",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "项目名称或ID",
                    },
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="rag_export_document",
            description="导出文档的完整解析内容，用于深度分析",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "项目名称或ID",
                    },
                    "document_id": {
                        "type": "string",
                        "description": "文档ID",
                    },
                },
                "required": ["project", "document_id"],
            },
        ),
        Tool(
            name="rag_upload_document",
            description="上传文档到指定项目（文档路径必须在本地文件系统可访问）",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "项目名称或ID",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "本地文件绝对路径",
                    },
                },
                "required": ["project", "file_path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """调用工具"""
    handlers = {
        "rag_search": _handle_search,
        "rag_list_projects": _handle_list_projects,
        "rag_get_project_info": _handle_get_project_info,
        "rag_list_documents": _handle_list_documents,
        "rag_export_document": _handle_export_document,
        "rag_upload_document": _handle_upload_document,
    }
    
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=f"未知工具: {name}")]
    
    # 使用上下文管理器确保数据库会话正确关闭
    with _get_db_session() as db:
        return await handler(db, arguments)


async def _handle_search(db, arguments: Dict[str, Any]) -> List[TextContent]:
    """处理搜索请求"""
    project = arguments.get("project")
    query = arguments.get("query")
    top_k = min(arguments.get("top_k", 20), 50)  # 默认20，限制最大50
    
    if not project or not query:
        return [TextContent(type="text", text="缺少必要参数: project 和 query")]
    
    # 查找项目
    project_obj = _find_project(db, project)
    if not project_obj:
        return [TextContent(type="text", text=f"找不到项目: {project}")]
    
    # 执行搜索
    search_service = SearchService(db)
    request = SearchRequest(
        project_id=project_obj.id,
        query=query,
        top_k=top_k,
        search_mode="hybrid",
    )
    
    result = await search_service.search(request)
    
    if not result.results:
        return [TextContent(type="text", text=f"在项目 '{project_obj.name}' 中未找到与 '{query}' 相关的结果。")]
    
    # 返回 JSON 格式，便于 Agent 解析处理
    response = {
        "project": project_obj.name,
        "project_id": project_obj.id,
        "query": query,
        "total": result.total,
        "time_ms": result.query_time_ms,
        "results": [
            {
                "content": r.content,
                "score": round(r.score, 3),
                "source": r.metadata.get("filename", "未知"),
                "document_id": r.metadata.get("document_id", ""),
            }
            for r in result.results
        ]
    }
    
    return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]


def _handle_list_projects(db, arguments: Dict[str, Any]) -> List[TextContent]:
    """处理列出项目请求"""
    project_service = ProjectService(db)
    projects = project_service.list_projects()
    
    if not projects:
        return [TextContent(type="text", text=json.dumps({"projects": []}, ensure_ascii=False))]
    
    response = {
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description or "",
                "document_count": p.document_count,
                "chunk_count": p.chunk_count,
            }
            for p in projects
        ]
    }
    
    return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]


def _handle_get_project_info(db, arguments: Dict[str, Any]) -> List[TextContent]:
    """处理获取项目信息请求"""
    project = arguments.get("project")
    
    if not project:
        return [TextContent(type="text", text="缺少必要参数: project")]
    
    project_obj = _find_project(db, project)
    if not project_obj:
        return [TextContent(type="text", text=f"找不到项目: {project}")]
    
    response = {
        "id": project_obj.id,
        "name": project_obj.name,
        "description": project_obj.description or "",
        "document_count": project_obj.document_count,
        "chunk_count": project_obj.chunk_count,
        "created_at": project_obj.created_at.isoformat() if project_obj.created_at else None,
        "updated_at": project_obj.updated_at.isoformat() if project_obj.updated_at else None,
    }
    
    return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]


def _handle_list_documents(db, arguments: Dict[str, Any]) -> List[TextContent]:
    """处理列出文档请求"""
    project = arguments.get("project")
    
    if not project:
        return [TextContent(type="text", text="缺少必要参数: project")]
    
    project_obj = _find_project(db, project)
    if not project_obj:
        return [TextContent(type="text", text=f"找不到项目: {project}")]
    
    project_service = ProjectService(db)
    documents = project_service.list_documents(project_obj.id)
    
    response = {
        "project": project_obj.name,
        "project_id": project_obj.id,
        "documents": [
            {
                "id": doc.id,
                "filename": doc.filename,
                "doc_type": doc.doc_type,
                "file_size": doc.file_size,
                "file_path": doc.file_path if hasattr(doc, 'file_path') else None,
                "chunk_count": doc.chunk_count,
                "status": doc.status,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
            for doc in documents
        ]
    }
    
    return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]


def _handle_export_document(db, arguments: Dict[str, Any]) -> List[TextContent]:
    """处理导出文档请求"""
    from src.rag_api.models.database import Chunk
    
    project = arguments.get("project")
    document_id = arguments.get("document_id")
    
    if not project or not document_id:
        return [TextContent(type="text", text="缺少必要参数: project 和 document_id")]
    
    project_obj = _find_project(db, project)
    if not project_obj:
        return [TextContent(type="text", text=f"找不到项目: {project}")]
    
    # 获取文档信息
    project_service = ProjectService(db)
    document = project_service.get_document(document_id)
    
    if not document or document.project_id != project_obj.id:
        return [TextContent(type="text", text=f"文档不存在或不属于该项目")]
    
    # 获取所有文本块
    chunks = db.query(Chunk).filter(
        Chunk.document_id == document_id
    ).order_by(Chunk.chunk_index).all()
    
    response = {
        "document_id": document_id,
        "filename": document.filename,
        "doc_type": document.doc_type,
        "file_path": document.file_path if hasattr(document, 'file_path') else None,
        "chunk_count": len(chunks),
        "status": document.status,
        "content": "\n\n".join([c.content for c in chunks])
    }
    
    return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]


async def _handle_upload_document(db, arguments: Dict[str, Any]) -> List[TextContent]:
    """处理上传文档请求"""
    from src.services.ingest_service import IngestService
    from fastapi import UploadFile
    import io
    
    project = arguments.get("project")
    file_path = arguments.get("file_path")
    
    if not project or not file_path:
        return [TextContent(type="text", text="缺少必要参数: project 和 file_path")]
    
    project_obj = _find_project(db, project)
    if not project_obj:
        return [TextContent(type="text", text=f"找不到项目: {project}")]
    
    path = Path(file_path)
    if not path.exists():
        return [TextContent(type="text", text=f"文件不存在: {file_path}")]
    
    if not path.is_file():
        return [TextContent(type="text", text=f"路径不是文件: {file_path}")]
    
    try:
        # 创建 UploadFile 对象
        with open(path, "rb") as f:
            content = f.read()
        
        upload_file = UploadFile(
            filename=path.name,
            file=io.BytesIO(content),
        )
        
        # 上传文档
        ingest_service = IngestService(db)
        result = await ingest_service.upload_document(
            project_id=project_obj.id,
            file=upload_file,
        )
        
        response = {
            "success": True,
            "message": f"文档上传成功: {path.name}",
            "document_id": result.get("id"),
            "filename": result.get("filename"),
            "status": result.get("status"),
        }
        
        return [TextContent(type="text", text=json.dumps(response, ensure_ascii=False, indent=2))]
        
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False))]


def main():
    """启动 MCP Server"""
    import asyncio
    from mcp.server.stdio import stdio_server
    
    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    
    asyncio.run(run())


if __name__ == "__main__":
    main()
