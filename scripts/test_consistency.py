#!/usr/bin/env python3
"""测试一致性检查功能

用法:
    python test_consistency.py <项目名称>
    
示例:
    python test_consistency.py yunxi
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.rag_api.config import get_settings
from src.rag_api.models.database import Project
from src.watcher.sync import ConsistencyChecker, ProjectMapping

settings = get_settings()


def get_db_session():
    """获取数据库会话"""
    engine = create_engine(f"sqlite:///{settings.DB_PATH}")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def test_consistency(project_name: str):
    """测试指定项目的一致性"""
    db = get_db_session()
    
    try:
        # 查找项目
        project = db.query(Project).filter(Project.name == project_name).first()
        if not project:
            print(f"❌ 项目不存在: {project_name}")
            return
        
        print(f"\n{'='*60}")
        print(f"一致性检查: {project_name}")
        print(f"项目ID: {project.id}")
        print(f"{'='*60}\n")
        
        # 查找对应的 watcher 根目录
        # 假设项目名就是目录名
        watch_root = Path(f"~/Projects/{project_name}").expanduser()
        if not watch_root.exists():
            # 尝试其他可能的路径
            watch_root = Path(f"/Users/jk/Projects/{project_name}")
        
        print(f"监视目录: {watch_root}")
        print(f"RAG目录: {settings.PROJECTS_DIR / project.id}")
        print()
        
        # 统计当前状态
        from src.rag_api.models.database import Document
        doc_count = db.query(Document).filter(Document.project_id == project.id).count()
        print(f"数据库文档数: {doc_count}")
        
        # 执行一致性检查
        checker = ConsistencyChecker(db, project.id, watch_root)
        stats = checker.check_and_fix()
        
        print(f"\n{'='*60}")
        print("检查结果:")
        print(f"{'='*60}")
        print(f"孤儿文件: {stats['orphaned_files']}")
        print(f"已清理: {stats['cleaned']}")
        print(f"缺失文件: {stats['missing_files']}")
        
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python test_consistency.py <项目名称>")
        sys.exit(1)
    
    project_name = sys.argv[1]
    test_consistency(project_name)
