"""CLI 命令行工具 - 兼容旧接口"""

# 保留旧接口，将命令转发到新模块
# 新接口请使用: ath


@app.command()
def init(
    data_dir: str = typer.Option("./data", "--data-dir", "-d", help="数据目录"),
):
    """初始化系统"""
    console.print("[bold green]初始化 ATHRag系统...[/bold green]")
    
    # 创建目录
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    Path(f"{data_dir}/projects").mkdir(parents=True, exist_ok=True)
    Path(f"{data_dir}/vector_db").mkdir(parents=True, exist_ok=True)
    Path("./db").mkdir(parents=True, exist_ok=True)
    
    # 初始化数据库
    from src.rag_api.models.database import init_db
    init_db()
    
    console.print("[bold green]✓[/bold green] 初始化完成！")


@app.command()
def project_create(
    name: str = typer.Argument(..., help="项目名称"),
    description: Optional[str] = typer.Option(None, "--desc", help="项目描述"),
):
    """创建项目"""
    from sqlalchemy.orm import Session
    from src.rag_api.models.database import SessionLocal
    from src.rag_api.models.schemas import ProjectCreate
    from src.services.project_service import ProjectService
    
    db: Session = SessionLocal()
    try:
        service = ProjectService(db)
        project = service.create_project(
            ProjectCreate(name=name, description=description)
        )
        console.print(f"[bold green]✓[/bold green] 项目创建成功: {project.name} (ID: {project.id})")
    finally:
        db.close()


@app.command()
def project_list():
    """列出所有项目"""
    from sqlalchemy.orm import Session
    from src.rag_api.models.database import SessionLocal
    from src.services.project_service import ProjectService
    
    db: Session = SessionLocal()
    try:
        service = ProjectService(db)
        projects = service.list_projects()
        
        table = Table(title="项目列表")
        table.add_column("ID", style="cyan")
        table.add_column("名称", style="magenta")
        table.add_column("描述", style="green")
        table.add_column("文档数", justify="right")
        table.add_column("创建时间", style="dim")
        
        for p in projects:
            table.add_row(
                p.id[:8] + "...",
                p.name,
                p.description or "-",
                str(p.document_count),
                p.created_at.strftime("%Y-%m-%d %H:%M"),
            )
        
        console.print(table)
    finally:
        db.close()


@app.command()
def project_delete(
    project_id: str = typer.Argument(..., help="项目ID"),
    force: bool = typer.Option(False, "--force", "-f", help="强制删除，不确认"),
):
    """删除项目"""
    if not force:
        confirm = typer.confirm(f"确定要删除项目 {project_id} 吗？这将删除所有相关数据！")
        if not confirm:
            console.print("已取消")
            raise typer.Exit()
    
    from sqlalchemy.orm import Session
    from src.rag_api.models.database import SessionLocal
    from src.services.project_service import ProjectService
    
    db: Session = SessionLocal()
    try:
        service = ProjectService(db)
        service.delete_project(project_id)
        console.print(f"[bold green]✓[/bold green] 项目 {project_id} 已删除")
    except ValueError as e:
        console.print(f"[bold red]✗[/bold red] {e}")
    finally:
        db.close()


@app.command()
def ingest(
    project_id: str = typer.Argument(..., help="项目ID"),
    path: Path = typer.Argument(..., help="文件或目录路径"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="递归处理目录"),
):
    """摄取文档"""
    import asyncio
    
    async def do_ingest():
        from sqlalchemy.orm import Session
        from src.rag_api.models.database import SessionLocal
        from src.services.ingest_service import IngestService
        
        db: Session = SessionLocal()
        try:
            service = IngestService(db)
            
            files = []
            if path.is_file():
                files = [path]
            elif path.is_dir():
                pattern = "**/*" if recursive else "*"
                files = list(path.glob(pattern))
                files = [f for f in files if f.is_file()]
            
            console.print(f"[bold blue]发现 {len(files)} 个文件[/bold blue]")
            
            for file_path in files:
                console.print(f"处理: {file_path.name} ...", end=" ")
                try:
                    # 模拟 UploadFile
                    from fastapi import UploadFile
                    from io import BytesIO
                    
                    content = file_path.read_bytes()
                    upload_file = UploadFile(
                        filename=file_path.name,
                        file=BytesIO(content),
                    )
                    
                    result = await service.upload_document(
                        project_id=project_id,
                        file=upload_file,
                    )
                    console.print(f"[green]✓ {result['status']}[/green]")
                except Exception as e:
                    console.print(f"[red]✗ {e}[/red]")
        finally:
            db.close()
    
    asyncio.run(do_ingest())


@app.command()
def search(
    project_id: str = typer.Argument(..., help="项目ID"),
    query: str = typer.Argument(..., help="查询内容"),
    top_k: int = typer.Option(20, "--top-k", "-k", help="返回数量"),
):
    """搜索知识库"""
    async def do_search():
        from sqlalchemy.orm import Session
        from src.rag_api.models.database import SessionLocal
        from src.rag_api.models.schemas import SearchRequest
        from src.services.search_service import SearchService
        
        db: Session = SessionLocal()
        try:
            service = SearchService(db)
            request = SearchRequest(
                project_id=project_id,
                query=query,
                top_k=top_k,
            )
            result = await service.search(request)
            
            console.print(f"\n[bold]查询:[/bold] {query}")
            console.print(f"[dim]耗时: {result.query_time_ms}ms | 结果: {result.total}[/dim]\n")
            
            for i, r in enumerate(result.results, 1):
                console.print(f"[bold cyan]{i}.[/bold cyan] [dim]({r.search_type}, 分数: {r.score:.3f})[/dim]")
                # 截断显示
                content = r.content[:200] + "..." if len(r.content) > 200 else r.content
                console.print(f"   {content}\n")
        finally:
            db.close()
    
    asyncio.run(do_search())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="监听地址"),
    port: int = typer.Option(8000, "--port", "-p", help="监听端口"),
    reload: bool = typer.Option(False, "--reload", help="开发模式（热重载）"),
):
    """启动 API 服务"""
    import uvicorn
    
    console.print(f"[bold green]启动服务: http://{host}:{port}[/bold green]")
    uvicorn.run(
        "src.rag_api.main:app",
        host=host,
        port=port,
        reload=reload,
    )


def main():
    app()


if __name__ == "__main__":
    main()
