#!/usr/bin/env python3
"""重新索引 yunxi 项目的 Office 文档

使用新的 Unstructured 解析器重新处理所有 Office 文件。
"""

import sys
import json
import time
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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_db_session():
    """获取数据库会话"""
    engine = create_engine(f"sqlite:///{settings.DB_PATH}")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def reindex_office_documents(project_id: str, batch_size: int = 5):
    """重新索引 Office 文档

    Args:
        project_id: 项目 ID
        batch_size: 每批处理的文档数量
    """
    db = get_db_session()

    try:
        # 获取项目信息
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            logger.error(f"项目不存在: {project_id}")
            return

        logger.info(f"项目: {project.name} (ID: {project_id})")
        logger.info(f"当前文档数: {project.document_count}, 片段数: {project.chunk_count}")

        # 获取所有 Office 文档
        office_docs = db.query(Document).filter(
            Document.project_id == project_id,
            Document.doc_type.in_(['docx', 'xlsx', 'pptx'])
        ).all()

        total = len(office_docs)
        logger.info(f"找到 {total} 个 Office 文档待重新索引")

        if total == 0:
            logger.info("没有 Office 文档需要处理")
            return

        # 初始化服务
        processor = DocumentProcessor()
        chunker = TextChunker()
        embedding = EmbeddingService()
        vector_store = VectorStore()

        # 检查 Unstructured 是否可用
        if not processor.unstructured_available:
            logger.error("❌ Unstructured 不可用，无法继续")
            return

        logger.info("✅ Unstructured 解析器已就绪")

        # 统计
        stats = {
            "total": total,
            "success": 0,
            "failed": 0,
            "total_chunks": 0,
            "start_time": time.time()
        }

        # 分批处理
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch = office_docs[batch_start:batch_end]

            logger.info(f"\n{'='*60}")
            logger.info(f"批次 {batch_start//batch_size + 1}/{(total-1)//batch_size + 1} ({batch_start+1}-{batch_end}/{total})")
            logger.info(f"{'='*60}")

            for doc in batch:
                try:
                    logger.info(f"\n处理: {doc.filename} ({doc.doc_type})")

                    # 删除旧的 chunks 和向量
                    old_chunks = db.query(Chunk).filter(Chunk.document_id == doc.id).all()
                    for chunk in old_chunks:
                        if chunk.vector_id:
                            try:
                                vector_store.delete_vector(project_id, chunk.vector_id)
                            except Exception as e:
                                logger.warning(f"删除旧向量失败: {e}")
                        db.delete(chunk)

                    # 更新文档状态
                    doc.status = "processing"
                    doc.chunk_count = 0
                    db.commit()

                    # 使用新的解析器处理
                    file_path = Path(doc.file_path)
                    if not file_path.exists():
                        file_path = settings.PROJECTS_DIR / project_id / doc.filename

                    logger.info(f"  解析文件: {file_path}")

                    # 使用 Unstructured 提取结构化内容
                    structured_data = processor.extract_structured(file_path, doc.doc_type)

                    markdown_content = structured_data.get("markdown", "")
                    tables = structured_data.get("tables", [])
                    sections = structured_data.get("sections", [])

                    logger.info(f"  ✅ 解析成功:")
                    logger.info(f"     - Markdown 长度: {len(markdown_content)} 字符")
                    logger.info(f"     - 表格数量: {len(tables)}")
                    logger.info(f"     - 章节数量: {len(sections)}")

                    # 分块
                    chunk_objects = chunker.chunk_text_with_location(
                        markdown_content,
                        file_path=str(file_path)
                    )

                    logger.info(f"     - 生成片段: {len(chunk_objects)} 个")

                    # 保存 chunks
                    chunk_records = []
                    for i, chunk_obj in enumerate(chunk_objects):
                        metadata = {
                            "start_line": chunk_obj.start_line,
                            "end_line": chunk_obj.end_line,
                            "file_path": str(file_path),
                            "source_doc_type": doc.doc_type,
                        }

                        chunk = Chunk(
                            document_id=doc.id,
                            project_id=project_id,
                            content=chunk_obj.content,
                            chunk_index=i,
                            metadata_json=json.dumps(metadata),
                        )
                        db.add(chunk)
                        chunk_records.append(chunk)

                    db.commit()

                    # 向量化
                    for chunk in chunk_records:
                        try:
                            embedding_vector = embedding.embed_text_sync(chunk.content)

                            vector_id = vector_store.add_vector(
                                project_id=project_id,
                                vector=embedding_vector,
                                payload={
                                    "chunk_id": chunk.id,
                                    "document_id": doc.id,
                                    "content": chunk.content,
                                    "filename": doc.filename,
                                    "start_line": json.loads(chunk.metadata_json).get("start_line"),
                                    "end_line": json.loads(chunk.metadata_json).get("end_line"),
                                },
                            )
                            chunk.vector_id = vector_id
                        except Exception as e:
                            logger.error(f"向量化失败: {e}")

                    db.commit()

                    # 更新文档状态
                    doc.status = "completed"
                    doc.chunk_count = len(chunk_objects)
                    db.commit()

                    stats["success"] += 1
                    stats["total_chunks"] += len(chunk_objects)

                    logger.info(f"  ✅ 完成: {len(chunk_objects)} 个片段已索引")

                except Exception as e:
                    logger.error(f"  ❌ 处理失败: {e}")
                    doc.status = "failed"
                    doc.error_message = str(e)
                    db.commit()
                    stats["failed"] += 1

            # 批次间隔
            if batch_end < total:
                logger.info(f"\n批次完成，休息 2 秒...")
                time.sleep(2)

        # 更新项目统计
        project.chunk_count = db.query(Chunk).filter(Chunk.project_id == project_id).count()
        db.commit()

        # 输出统计
        elapsed = time.time() - stats["start_time"]
        logger.info(f"\n{'='*60}")
        logger.info(f"重新索引完成!")
        logger.info(f"{'='*60}")
        logger.info(f"总计: {stats['total']} 个文档")
        logger.info(f"成功: {stats['success']} 个")
        logger.info(f"失败: {stats['failed']} 个")
        logger.info(f"生成片段: {stats['total_chunks']} 个")
        logger.info(f"耗时: {elapsed:.1f} 秒 ({elapsed/60:.1f} 分钟)")
        logger.info(f"平均: {elapsed/stats['total']:.1f} 秒/文档")

    finally:
        db.close()


if __name__ == "__main__":
    PROJECT_ID = "76257d95-b898-430e-a9fe-d125f0a40ade"

    print("🚀 开始重新索引 yunxi 项目的 Office 文档")
    print(f"项目 ID: {PROJECT_ID}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    reindex_office_documents(PROJECT_ID, batch_size=3)
