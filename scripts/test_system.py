#!/usr/bin/env python3
"""ATHRag系统测试脚本"""

import asyncio
import sys
from io import BytesIO

# 确保能导入项目模块
sys.path.insert(0, '/Users/jk/Projects/ATHRag')

from fastapi import UploadFile
from sqlalchemy.orm import Session

from src.rag_api.models.database import SessionLocal, init_db
from src.rag_api.models.schemas import ProjectCreate, SearchRequest
from src.services.project_service import ProjectService
from src.services.ingest_service import IngestService
from src.services.search_service import SearchService
from src.core.vector_store import VectorStore
from src.core.embedding import EmbeddingService


def test_database():
    """测试数据库连接"""
    print("\n=== 测试数据库 ===")
    try:
        init_db()
        print("✓ 数据库初始化成功")
        
        db = SessionLocal()
        db.close()
        print("✓ 数据库连接正常")
    except Exception as e:
        print(f"✗ 数据库测试失败: {e}")
        return False
    return True


def test_vector_store():
    """测试向量数据库"""
    print("\n=== 测试向量数据库 ===")
    try:
        store = VectorStore()
        
        # 检查连接
        collections = store.client.get_collections()
        print(f"✓ Qdrant 连接正常，{len(collections.collections)} 个 collections")
        
        # 测试创建/删除 collection
        test_id = "test_project_123"
        store.create_collection(test_id)
        exists = store.collection_exists(test_id)
        print(f"✓ Collection 创建: {exists}")
        
        store.delete_collection(test_id)
        exists = store.collection_exists(test_id)
        print(f"✓ Collection 删除: {not exists}")
        
    except Exception as e:
        print(f"✗ 向量数据库测试失败: {e}")
        return False
    return True


def test_embedding():
    """测试 Embedding 服务"""
    print("\n=== 测试 Embedding ===")
    try:
        service = EmbeddingService()
        
        # 测试向量化
        text = "这是一个测试文本"
        vector = service.embed_text_sync(text)
        
        print(f"✓ Embedding 成功，维度: {len(vector)}")
        print(f"  前5个值: {vector[:5]}")
        
    except Exception as e:
        print(f"✗ Embedding 测试失败: {e}")
        return False
    return True


def test_project_service():
    """测试项目服务"""
    print("\n=== 测试项目服务 ===")
    try:
        db = SessionLocal()
        service = ProjectService(db)
        
        # 创建测试项目
        project = service.create_project(
            ProjectCreate(name="自动测试项目", description="由测试脚本创建")
        )
        print(f"✓ 项目创建: {project.name} (ID: {project.id})")
        
        # 列出项目
        projects = service.list_projects()
        print(f"✓ 项目列表: {len(projects)} 个项目")
        
        # 获取项目
        p = service.get_project(project.id)
        print(f"✓ 项目查询: {p.name if p else 'Not found'}")
        
        # 清理
        service.delete_project(project.id)
        print(f"✓ 项目删除成功")
        
        db.close()
    except Exception as e:
        print(f"✗ 项目服务测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    return True


async def test_ingest_and_search():
    """测试文档摄取和搜索"""
    print("\n=== 测试文档摄取和搜索 ===")
    try:
        db = SessionLocal()
        
        # 创建项目
        project_service = ProjectService(db)
        project = project_service.create_project(
            ProjectCreate(name="搜索测试项目", description="测试搜索功能")
        )
        print(f"✓ 项目创建: {project.name}")
        
        # 上传文档
        ingest_service = IngestService(db)
        
        test_content = """
# 人工智能概述

人工智能（AI）是计算机科学的一个分支，致力于创建能够执行通常需要人类智能的任务的系统。

## 主要分支

1. **机器学习**: 让计算机从数据中学习
2. **深度学习**: 使用神经网络进行学习
3. **自然语言处理**: 理解和生成人类语言
4. **计算机视觉**: 让计算机"看懂"图像

## 应用场景

- 语音识别
- 图像分类
- 自动驾驶
- 推荐系统
"""
        
        upload_file = UploadFile(
            filename="ai_overview.md",
            file=BytesIO(test_content.encode()),
        )
        
        result = await ingest_service.upload_document(
            project_id=project.id,
            file=upload_file,
        )
        print(f"✓ 文档上传: {result['id']}, 状态: {result['status']}")
        
        # 等待向量化完成
        await asyncio.sleep(1)
        
        # 测试搜索
        search_service = SearchService(db)
        request = SearchRequest(
            project_id=project.id,
            query="人工智能有哪些分支",
            top_k=3,
        )
        
        result = await search_service.search(request)
        print(f"✓ 搜索完成: {result.total} 个结果，{result.query_time_ms}ms")
        
        for i, r in enumerate(result.results[:3], 1):
            content = r.content[:60] + "..." if len(r.content) > 60 else r.content
            print(f"  {i}. [{r.search_type}] {content}")
        
        # 清理
        project_service.delete_project(project.id)
        print(f"✓ 清理完成")
        
        db.close()
    except Exception as e:
        print(f"✗ 文档摄取和搜索测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    return True


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("ATHRag系统功能测试")
    print("=" * 60)
    
    results = []
    
    # 同步测试
    results.append(("数据库", test_database()))
    results.append(("向量数据库", test_vector_store()))
    results.append(("Embedding", test_embedding()))
    results.append(("项目服务", test_project_service()))
    
    # 异步测试
    results.append(("文档摄取和搜索", asyncio.run(test_ingest_and_search())))
    
    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} - {name}")
    
    print("-" * 60)
    print(f"总计: {passed}/{total} 通过")
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
