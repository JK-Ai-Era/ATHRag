#!/usr/bin/env python3
"""向量完整性检查和修复工具

检查 SQLite DB 和 Qdrant 向量数据库之间的一致性，并修复不一致。

用法:
    python check_vector_integrity.py <项目ID>
    
示例:
    python check_vector_integrity.py 76257d95-b898-430e-a9fe-d125f0a40ade
"""

import sys
import logging
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.rag_api.config import get_settings
from src.rag_api.models.database import Chunk, Document, Project
from src.core.vector_store import VectorStore

settings = get_settings()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_db_session():
    """获取数据库会话"""
    engine = create_engine(f"sqlite:///{settings.DB_PATH}")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


class VectorIntegrityChecker:
    """向量完整性检查器"""
    
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.db = get_db_session()
        self.vector_store = VectorStore()
        self.stats = {
            "total_chunks": 0,
            "chunks_with_vector_id": 0,
            "orphaned_vectors": 0,
            "missing_vectors": 0,
            "valid_vectors": 0,
        }
    
    def check_integrity(self) -> Dict:
        """
        检查向量完整性
        
        检查项:
        1. DB中有 vector_id 但 Qdrant 中不存在的向量（孤立向量ID）
        2. Qdrant 中有但 DB 中没有的向量（孤儿向量）
        3. DB中无 vector_id 的片段
        
        Returns:
            检查结果统计
        """
        logger.info(f"开始检查项目 {self.project_id} 的向量完整性")
        
        # 1. 获取 DB 中所有带 vector_id 的 chunks
        chunks_with_vector = self.db.query(Chunk).filter(
            Chunk.project_id == self.project_id,
            Chunk.vector_id.isnot(None)
        ).all()
        
        self.stats["chunks_with_vector_id"] = len(chunks_with_vector)
        logger.info(f"DB 中有 vector_id 的 chunks: {len(chunks_with_vector)}")
        
        # 2. 获取 Qdrant 中所有向量
        qdrant_vector_ids = self._get_all_qdrant_vectors()
        logger.info(f"Qdrant 中的向量数量: {len(qdrant_vector_ids)}")
        
        # 3. 对比检查
        db_vector_ids = {chunk.vector_id for chunk in chunks_with_vector}
        
        # DB 中有但 Qdrant 中没有的（丢失的向量）
        missing_in_qdrant = db_vector_ids - qdrant_vector_ids
        self.stats["missing_vectors"] = len(missing_in_qdrant)
        
        # Qdrant 中有但 DB 中没有的（孤儿向量）
        orphaned_in_qdrant = qdrant_vector_ids - db_vector_ids
        self.stats["orphaned_vectors"] = len(orphaned_in_qdrant)
        
        # 两者都有的（有效向量）
        valid_vectors = db_vector_ids & qdrant_vector_ids
        self.stats["valid_vectors"] = len(valid_vectors)
        
        # 4. 获取无 vector_id 的 chunks
        chunks_without_vector = self.db.query(Chunk).filter(
            Chunk.project_id == self.project_id,
            Chunk.vector_id.is_(None)
        ).count()
        
        self.stats["chunks_without_vector_id"] = chunks_without_vector
        
        logger.info(f"\n检查结果:")
        logger.info(f"  有 vector_id 的 chunks: {self.stats['chunks_with_vector_id']}")
        logger.info(f"  无 vector_id 的 chunks: {chunks_without_vector}")
        logger.info(f"  有效向量 (两边都有): {self.stats['valid_vectors']}")
        logger.info(f"  丢失向量 (DB有Qdrant无): {self.stats['missing_vectors']}")
        logger.info(f"  孤儿向量 (Qdrant有DB无): {self.stats['orphaned_vectors']}")
        
        return {
            "missing_vector_ids": list(missing_in_qdrant),
            "orphaned_vector_ids": list(orphaned_in_qdrant),
            **self.stats
        }
    
    def _get_all_qdrant_vectors(self) -> Set[str]:
        """获取 Qdrant 中所有向量的 ID"""
        vector_ids = set()
        offset = None
        
        while True:
            try:
                results, next_offset = self.vector_store.client.scroll(
                    collection_name=f"project_{self.project_id}",
                    limit=1000,
                    offset=offset,
                    with_payload=False,
                    with_vectors=False
                )
                
                if not results:
                    break
                
                for point in results:
                    vector_ids.add(str(point.id))
                
                if next_offset is None:
                    break
                offset = next_offset
                
            except Exception as e:
                logger.error(f"获取 Qdrant 向量失败: {e}")
                break
        
        return vector_ids
    
    def fix_missing_vectors(self, dry_run: bool = False) -> int:
        """
        修复丢失的向量
        
        对 DB 中有 vector_id 但 Qdrant 中没有的 chunks，重新向量化。
        
        Args:
            dry_run: 如果为 True，只打印不执行
            
        Returns:
            修复的向量数量
        """
        from src.core.embedding import EmbeddingService
        
        embedding = EmbeddingService()
        fixed_count = 0
        
        # 获取所有有 vector_id 的 chunks
        chunks_with_vector = self.db.query(Chunk).filter(
            Chunk.project_id == self.project_id,
            Chunk.vector_id.isnot(None)
        ).all()
        
        qdrant_vector_ids = self._get_all_qdrant_vectors()
        
        logger.info(f"\n检查 {len(chunks_with_vector)} 个 chunks 的向量状态...")
        
        for chunk in chunks_with_vector:
            if chunk.vector_id not in qdrant_vector_ids:
                logger.warning(f"Chunk {chunk.id} 的向量 {chunk.vector_id} 丢失，需要重新向量化")
                
                if dry_run:
                    continue
                
                try:
                    # 重新向量化
                    vector = embedding.embed_text_sync(chunk.content)
                    
                    # 添加到 Qdrant
                    import json
                    try:
                        metadata = json.loads(chunk.metadata_json) if chunk.metadata_json else {}
                    except:
                        metadata = {}
                    
                    new_vector_id = self.vector_store.add_vector(
                        project_id=self.project_id,
                        vector=vector,
                        payload={
                            "chunk_id": chunk.id,
                            "document_id": chunk.document_id,
                            "content": chunk.content,
                            "filename": metadata.get("file_path", ""),
                            "start_line": metadata.get("start_line"),
                            "end_line": metadata.get("end_line"),
                        }
                    )
                    
                    if new_vector_id:
                        chunk.vector_id = new_vector_id
                        self.db.commit()
                        fixed_count += 1
                        logger.info(f"  ✅ 已修复 chunk {chunk.id}")
                    else:
                        logger.error(f"  ❌ 修复失败 chunk {chunk.id}: 添加向量返回空")
                        
                except Exception as e:
                    logger.error(f"  ❌ 修复失败 chunk {chunk.id}: {e}")
        
        logger.info(f"\n修复完成: {fixed_count} 个向量已重新生成")
        return fixed_count
    
    def cleanup_orphaned_vectors(self, dry_run: bool = False) -> int:
        """
        清理孤儿向量
        
        删除 Qdrant 中有但 DB 中没有的向量。
        
        Args:
            dry_run: 如果为 True，只打印不执行
            
        Returns:
            清理的向量数量
        """
        # 获取所有 vector_id
        chunks_with_vector = self.db.query(Chunk).filter(
            Chunk.project_id == self.project_id,
            Chunk.vector_id.isnot(None)
        ).all()
        
        db_vector_ids = {chunk.vector_id for chunk in chunks_with_vector}
        qdrant_vector_ids = self._get_all_qdrant_vectors()
        
        # 孤儿向量
        orphaned = qdrant_vector_ids - db_vector_ids
        
        logger.info(f"\n发现 {len(orphaned)} 个孤儿向量")
        
        if dry_run:
            return len(orphaned)
        
        deleted_count = 0
        for vector_id in orphaned:
            try:
                if self.vector_store.delete_vector(self.project_id, vector_id):
                    deleted_count += 1
                    logger.info(f"  ✅ 已删除孤儿向量 {vector_id}")
                else:
                    logger.warning(f"  ⚠️ 删除失败 {vector_id}")
            except Exception as e:
                logger.error(f"  ❌ 删除失败 {vector_id}: {e}")
        
        logger.info(f"\n清理完成: {deleted_count} 个孤儿向量已删除")
        return deleted_count
    
    def cleanup_orphaned_chunks(self, dry_run: bool = False) -> int:
        """
        清理孤儿 chunks
        
        删除 DB 中有 vector_id 但 Qdrant 中没有，且无法修复的 chunks。
        
        Args:
            dry_run: 如果为 True，只打印不执行
            
        Returns:
            清理的 chunks 数量
        """
        chunks_with_vector = self.db.query(Chunk).filter(
            Chunk.project_id == self.project_id,
            Chunk.vector_id.isnot(None)
        ).all()
        
        qdrant_vector_ids = self._get_all_qdrant_vectors()
        
        orphaned_chunks = []
        for chunk in chunks_with_vector:
            if chunk.vector_id not in qdrant_vector_ids:
                orphaned_chunks.append(chunk)
        
        logger.info(f"\n发现 {len(orphaned_chunks)} 个孤儿 chunks")
        
        if dry_run:
            return len(orphaned_chunks)
        
        deleted_count = 0
        for chunk in orphaned_chunks:
            try:
                self.db.delete(chunk)
                deleted_count += 1
                logger.info(f"  ✅ 已删除孤儿 chunk {chunk.id}")
            except Exception as e:
                logger.error(f"  ❌ 删除失败 chunk {chunk.id}: {e}")
        
        self.db.commit()
        
        # 更新项目统计
        project = self.db.query(Project).filter(Project.id == self.project_id).first()
        if project:
            project.chunk_count = self.db.query(Chunk).filter(
                Chunk.project_id == self.project_id
            ).count()
            self.db.commit()
        
        logger.info(f"\n清理完成: {deleted_count} 个孤儿 chunks 已删除")
        return deleted_count
    
    def close(self):
        """关闭数据库会话"""
        self.db.close()


def main():
    if len(sys.argv) < 2:
        print("用法: python check_vector_integrity.py <项目ID> [--fix] [--cleanup]")
        print("  --fix: 修复丢失的向量")
        print("  --cleanup: 清理孤儿向量和 chunks")
        print("  --dry-run: 只检查不执行")
        sys.exit(1)
    
    project_id = sys.argv[1]
    fix_mode = "--fix" in sys.argv
    cleanup_mode = "--cleanup" in sys.argv
    dry_run = "--dry-run" in sys.argv
    
    checker = VectorIntegrityChecker(project_id)
    
    try:
        # 1. 检查完整性
        result = checker.check_integrity()
        
        # 2. 修复模式
        if fix_mode:
            if dry_run:
                logger.info("\n[DRY RUN] 模拟修复模式...")
            fixed = checker.fix_missing_vectors(dry_run=dry_run)
            logger.info(f"修复了 {fixed} 个丢失的向量")
        
        # 3. 清理模式
        if cleanup_mode:
            if dry_run:
                logger.info("\n[DRY RUN] 模拟清理模式...")
            
            # 清理孤儿向量
            orphaned_deleted = checker.cleanup_orphaned_vectors(dry_run=dry_run)
            
            # 清理孤儿 chunks
            chunks_deleted = checker.cleanup_orphaned_chunks(dry_run=dry_run)
            
            logger.info(f"\n清理总计:")
            logger.info(f"  孤儿向量: {orphaned_deleted}")
            logger.info(f"  孤儿 chunks: {chunks_deleted}")
        
        # 4. 最终报告
        if not fix_mode and not cleanup_mode:
            logger.info("\n提示: 使用 --fix 修复丢失的向量，--cleanup 清理孤儿数据")
        
    finally:
        checker.close()


if __name__ == "__main__":
    main()
