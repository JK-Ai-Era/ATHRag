#!/usr/bin/env python3
"""彻底重建 yunxi 项目的向量索引

方案2: 删除所有向量和chunks，重新扫描并索引所有文件
"""

import sys
import json
import time
import shutil
import logging
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.rag_api.config import get_settings
from src.rag_api.models.database import Document, Chunk, Project
from src.core.document_processor import DocumentProcessor
from src.core.chunker import TextChunker
from src.core.embedding import EmbeddingService
from src.core.vector_store import VectorStore

settings = get_settings()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_db_session():
    """获取数据库会话"""
    engine = create_engine(f"sqlite:///{settings.DB_PATH}")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def rebuild_project(project_id: str, watch_root: Path):
    """彻底重建项目
    
    Args:
        project_id: 项目ID
        watch_root: 原项目目录路径
    """
    db = get_db_session()
    
    try:
        # 1. 获取项目信息
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            logger.error(f"项目不存在: {project_id}")
            return False
        
        logger.info(f"{'='*70}")
        logger.info(f"开始彻底重建项目: {project.name}")
        logger.info(f"项目ID: {project_id}")
        logger.info(f"监视目录: {watch_root}")
        logger.info(f"{'='*70}\n")
        
        # 2. 统计重建前状态
        old_docs = db.query(Document).filter(Document.project_id == project_id).count()
        old_chunks = db.query(Chunk).filter(Chunk.project_id == project_id).count()
        
        logger.info(f"重建前统计:")
        logger.info(f"  - 文档数: {old_docs}")
        logger.info(f"  - 片段数: {old_chunks}")
        logger.info(f"  - 项目目录: {settings.PROJECTS_DIR / project_id}")
        
        # 3. 删除 Qdrant Collection 并重建
        logger.info(f"\n[1/5] 删除并重建 Qdrant Collection...")
        vector_store = VectorStore()
        try:
            vector_store.delete_collection(project_id)
            logger.info(f"  ✅ 已删除旧 Collection")
        except Exception as e:
            logger.warning(f"  ⚠️ 删除旧 Collection 失败(可能不存在): {e}")
        
        vector_store.create_collection(project_id)
        logger.info(f"  ✅ 已创建新 Collection")
        
        # 4. 删除数据库中的 chunks 和 documents
        logger.info(f"\n[2/5] 清理数据库...")
        
        # 删除所有 chunks
        chunks_deleted = db.query(Chunk).filter(Chunk.project_id == project_id).delete()
        logger.info(f"  ✅ 已删除 {chunks_deleted} 个 chunks")
        
        # 删除所有 documents
        docs_deleted = db.query(Document).filter(Document.project_id == project_id).delete()
        logger.info(f"  ✅ 已删除 {docs_deleted} 个 documents")
        
        # 重置项目统计
        project.document_count = 0
        project.chunk_count = 0
        db.commit()
        logger.info(f"  ✅ 已重置项目统计")
        
        # 5. 清理 RAG 项目目录
        logger.info(f"\n[3/5] 清理 RAG 项目目录...")
        project_dir = settings.PROJECTS_DIR / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir)
            logger.info(f"  ✅ 已删除目录: {project_dir}")
        
        project_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"  ✅ 已重建目录: {project_dir}")
        
        # 6. 重新扫描并索引所有文件
        logger.info(f"\n[4/5] 开始重新索引所有文件...")
        
        if not watch_root.exists():
            logger.error(f"监视目录不存在: {watch_root}")
            return False
        
        # 初始化服务
        processor = DocumentProcessor()
        chunker = TextChunker()
        embedding = EmbeddingService()
        
        # 收集所有支持的文件
        supported_exts = {
            '.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt',
            '.md', '.txt',
            '.py', '.js', '.ts', '.java', '.go', '.rs', '.cpp', '.c', '.h',
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp',
        }
        
        all_files = []
        for file_path in watch_root.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in supported_exts:
                rel_path = str(file_path.relative_to(watch_root))
                all_files.append((file_path, rel_path))
        
        total_files = len(all_files)
        logger.info(f"  发现 {total_files} 个文件待索引")
        
        # 按批次处理
        batch_size = 5
        stats = {
            "total": total_files,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total_chunks": 0,
            "start_time": time.time()
        }
        
        for i, (file_path, rel_path) in enumerate(all_files, 1):
            logger.info(f"\n[{i}/{total_files}] 处理: {rel_path}")
            
            try:
                # 复制文件到项目目录
                dest_path = project_dir / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest_path)
                
                # 确定文档类型
                ext = file_path.suffix.lower()
                type_map = {
                    '.pdf': 'pdf', '.docx': 'docx', '.doc': 'docx',
                    '.xlsx': 'xlsx', '.xls': 'xlsx', '.pptx': 'pptx', '.ppt': 'pptx',
                    '.md': 'md', '.txt': 'txt',
                    '.png': 'image', '.jpg': 'image', '.jpeg': 'image',
                    '.py': 'code', '.js': 'code', '.ts': 'code', '.java': 'code',
                }
                doc_type = type_map.get(ext, 'other')
                
                # 创建文档记录
                doc = Document(
                    id=str(uuid4()),
                    project_id=project_id,
                    filename=rel_path,
                    doc_type=doc_type,
                    file_size=dest_path.stat().st_size,
                    file_path=str(file_path),
                    status='processing'
                )
                db.add(doc)
                db.commit()
                db.refresh(doc)
                
                # 解析文档
                text = processor.extract_text(dest_path, doc_type)
                
                # 分块
                if doc_type == 'code':
                    chunk_objects = chunker.chunk_code_with_symbols(
                        text,
                        file_path=str(dest_path),
                        language=ext.lstrip('.')
                    )
                else:
                    chunk_objects = chunker.chunk_text_with_location(
                        text,
                        file_path=str(dest_path)
                    )
                
                logger.info(f"  生成 {len(chunk_objects)} 个片段")
                
                # 保存 chunks
                chunk_records = []
                for idx, chunk_obj in enumerate(chunk_objects):
                    metadata = {
                        "start_line": chunk_obj.start_line,
                        "end_line": chunk_obj.end_line,
                        "file_path": str(dest_path),
                    }
                    
                    chunk = Chunk(
                        id=str(uuid4()),
                        document_id=doc.id,
                        project_id=project_id,
                        content=chunk_obj.content,
                        chunk_index=idx,
                        metadata_json=json.dumps(metadata)
                    )
                    db.add(chunk)
                    chunk_records.append(chunk)
                
                db.commit()
                
                # 向量化
                success_vectors = 0
                for chunk in chunk_records:
                    try:
                        vector = embedding.embed_text_sync(chunk.content)
                        vector_id = vector_store.add_vector(
                            project_id=project_id,
                            vector=vector,
                            payload={
                                "chunk_id": chunk.id,
                                "document_id": doc.id,
                                "content": chunk.content,
                                "filename": doc.filename,
                                "start_line": json.loads(chunk.metadata_json).get("start_line"),
                                "end_line": json.loads(chunk.metadata_json).get("end_line"),
                            }
                        )
                        chunk.vector_id = vector_id
                        success_vectors += 1
                    except Exception as e:
                        logger.error(f"    向量化失败: {e}")
                
                db.commit()
                
                # 更新文档状态
                doc.status = 'completed'
                doc.chunk_count = len(chunk_objects)
                db.commit()
                
                # 更新项目统计
                project.document_count += 1
                project.chunk_count += len(chunk_objects)
                db.commit()
                
                stats["success"] += 1
                stats["total_chunks"] += len(chunk_objects)
                
                logger.info(f"  ✅ 完成: {success_vectors}/{len(chunk_objects)} 个向量")
                
            except Exception as e:
                logger.error(f"  ❌ 处理失败: {e}")
                if 'doc' in locals():
                    doc.status = 'failed'
                    doc.error_message = str(e)
                    db.commit()
                stats["failed"] += 1
            
            # 批次休息
            if i % batch_size == 0 and i < total_files:
                logger.info(f"\n  批次完成 ({i}/{total_files})，休息 1 秒...")
                time.sleep(1)
        
        # 7. 最终统计
        elapsed = time.time() - stats["start_time"]
        logger.info(f"\n{'='*70}")
        logger.info(f"重建完成!")
        logger.info(f"{'='*70}")
        logger.info(f"总文件数: {stats['total']}")
        logger.info(f"成功: {stats['success']}")
        logger.info(f"失败: {stats['failed']}")
        logger.info(f"总片段: {stats['total_chunks']}")
        logger.info(f"耗时: {elapsed:.1f} 秒 ({elapsed/60:.1f} 分钟)")
        
        # 验证一致性
        final_docs = db.query(Document).filter(Document.project_id == project_id).count()
        final_chunks = db.query(Chunk).filter(Chunk.project_id == project_id).count()
        chunks_with_vector = db.query(Chunk).filter(
            Chunk.project_id == project_id,
            Chunk.vector_id.isnot(None)
        ).count()
        
        logger.info(f"\n最终验证:")
        logger.info(f"  文档数: {final_docs}")
        logger.info(f"  片段数: {final_chunks}")
        logger.info(f"  有向量的片段: {chunks_with_vector}")
        
        if final_chunks == chunks_with_vector:
            logger.info(f"  ✅ 数据一致性检查通过")
        else:
            logger.warning(f"  ⚠️ 数据不一致: {final_chunks - chunks_with_vector} 个片段无向量")
        
        return True
        
    finally:
        db.close()


if __name__ == "__main__":
    from uuid import uuid4
    
    PROJECT_ID = "76257d95-b898-430e-a9fe-d125f0a40ade"
    WATCH_ROOT = Path("/Users/jk/Projects/yunxi")
    
    print(f"🚀 开始彻底重建 yunxi 项目")
    print(f"项目ID: {PROJECT_ID}")
    print(f"源目录: {WATCH_ROOT}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n⚠️ 警告: 这将删除所有现有数据并重新索引!")
    print(f"10秒后开始...")
    time.sleep(10)
    
    success = rebuild_project(PROJECT_ID, WATCH_ROOT)
    
    if success:
        print("\n✅ 重建成功!")
        sys.exit(0)
    else:
        print("\n❌ 重建失败!")
        sys.exit(1)
