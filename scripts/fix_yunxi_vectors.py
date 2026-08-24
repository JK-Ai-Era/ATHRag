#!/usr/bin/env python3
"""修复 yunxi 项目向量数据一致性

根因：add_vectors_batch 对大文档一次性 upsert 到 Qdrant 导致超时
修复：已将 add_vectors_batch 改为分批写入（500条/批），本脚本重置并重新向量化

用法:
    python scripts/fix_yunxi_vectors.py --stats     # 查看统计
    python scripts/fix_yunxi_vectors.py --dry-run    # 预览
    python scripts/fix_yunxi_vectors.py --fix        # 执行修复
    python scripts/fix_yunxi_vectors.py --fix-docs   # 只修复 failed 文档
    python scripts/fix_yunxi_vectors.py --fix-pending # 只修复 completed 中的 pending chunks
"""

import sys
sys.path.insert(0, '/Users/jk/Projects/ATHRag')

import sqlite3
import argparse
import logging
import json
import time
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("fix-vectors")

DB_PATH = Path("/Users/jk/Projects/ATHRag/db/metadata.db")
PROJECT_ID = "a4f08741-c093-4f93-ad19-f94d0dc1040f"


def get_stats():
    """详细统计"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 总体
    cursor.execute("""
        SELECT 
          d.status,
          COUNT(DISTINCT d.id) as doc_count,
          SUM(CASE WHEN c.vector_status='pending' THEN 1 ELSE 0 END) as pending,
          SUM(CASE WHEN c.vector_status='failed' THEN 1 ELSE 0 END) as failed,
          SUM(CASE WHEN c.vector_status='success' THEN 1 ELSE 0 END) as success
        FROM documents d
        LEFT JOIN chunks c ON c.document_id = d.id
        WHERE d.project_id = ?
        GROUP BY d.status
    """, (PROJECT_ID,))
    
    print("\n=== yunxi 项目向量状态 ===")
    print(f"{'状态':<12} {'文档数':>6} {'pending':>10} {'failed':>10} {'success':>10}")
    print("-" * 55)
    for row in cursor.fetchall():
        status, docs, pending, failed, success = row
        print(f"{status:<12} {docs:>6} {pending:>10} {failed:>10} {success:>10}")
    
    # failed 文档详情
    cursor.execute("""
        SELECT d.filename, d.chunk_count,
               SUM(CASE WHEN c.vector_status='pending' THEN 1 ELSE 0 END) as pend,
               SUM(CASE WHEN c.vector_status='failed' THEN 1 ELSE 0 END) as fail,
               c2.vector_error
        FROM documents d
        LEFT JOIN chunks c ON c.document_id = d.id
        LEFT JOIN chunks c2 ON c2.document_id = d.id AND c2.vector_status = 'failed'
        WHERE d.project_id = ? AND d.status = 'failed'
        GROUP BY d.id
        ORDER BY d.chunk_count DESC
    """, (PROJECT_ID,))
    
    print(f"\n=== failed 文档详情 (共 23 个) ===")
    for row in cursor.fetchall():
        fname, chunks, pend, fail, err = row
        err_short = (err[:60] + '...') if err and len(err) > 60 else (err or '')
        print(f"  {fname[:50]:<50} chunks={chunks:>6}  pend={pend:>6}  fail={fail:>6}  err={err_short}")
    
    # completed 中有 pending 的
    cursor.execute("""
        SELECT d.filename, 
               SUM(CASE WHEN c.vector_status='pending' THEN 1 ELSE 0 END) as pend
        FROM documents d
        JOIN chunks c ON c.document_id = d.id
        WHERE d.project_id = ? AND d.status = 'completed' AND c.vector_status = 'pending'
        GROUP BY d.id
        ORDER BY pend DESC
    """, (PROJECT_ID,))
    
    pending_in_completed = cursor.fetchall()
    if pending_in_completed:
        print(f"\n=== completed 文档中有 pending chunks ({len(pending_in_completed)} 个) ===")
        for fname, pend in pending_in_completed:
            print(f"  {fname[:50]:<50} pending={pend}")
    
    conn.close()


def reset_failed_docs():
    """重置 failed 文档：文档状态 → processing，chunks 状态 → pending"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 获取 failed 文档 ID
    cursor.execute("""
        SELECT id, filename FROM documents 
        WHERE project_id = ? AND status = 'failed'
    """, (PROJECT_ID,))
    failed_docs = cursor.fetchall()
    
    if not failed_docs:
        print("没有 failed 文档需要重置")
        conn.close()
        return 0
    
    doc_ids = [d[0] for d in failed_docs]
    placeholders = ",".join("?" * len(doc_ids))
    
    # 重置文档状态
    cursor.execute(f"""
        UPDATE documents 
        SET status = 'processing', error_message = NULL, 
            vector_count = 0, updated_at = ?
        WHERE id IN ({placeholders}) AND project_id = ?
    """, [datetime.now().isoformat()] + doc_ids + [PROJECT_ID])
    docs_reset = cursor.rowcount
    
    # 重置 chunks 状态
    cursor.execute(f"""
        UPDATE chunks 
        SET vector_status = 'pending', vector_id = NULL, 
            vector_error = NULL, vector_retry_count = 0
        WHERE document_id IN ({placeholders}) AND project_id = ?
    """, doc_ids + [PROJECT_ID])
    chunks_reset = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    print(f"✅ 重置 {docs_reset} 个文档状态 → processing")
    print(f"✅ 重置 {chunks_reset} 个 chunks 状态 → pending")
    return len(failed_docs)


def reset_pending_in_completed():
    """重置 completed 文档中的 pending chunks"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.project_id = ? AND d.status = 'completed' 
          AND c.vector_status = 'pending' AND c.vector_id IS NULL
    """, (PROJECT_ID,))
    count = cursor.fetchone()[0]
    
    if count == 0:
        print("completed 文档中没有 pending chunks")
        conn.close()
        return 0
    
    # 这些 chunks 的 vector_status 已经是 pending，只需确认 vector_id 为 NULL
    # 不需要额外操作，reindex 时会处理
    print(f"completed 文档中有 {count} 个 pending chunks（将在 reindex 时处理）")
    conn.close()
    return count


def reindex_documents(project_id: str, doc_limit: int = None):
    """通过 API 重新索引文档"""
    import httpx
    
    # 获取 token
    client = httpx.Client(timeout=300.0)
    resp = client.post(
        "http://localhost:16250/api/v1/auth/login",
        content="username=admin&password=576Gzq1616",
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 获取需要处理的文档列表
    resp = client.get(
        f"http://localhost:16250/api/v1/projects/{project_id}/documents?page_size=500",
        headers=headers
    )
    data = resp.json().get("data", {})
    all_docs = data.get("items", [])
    
    # 筛选出 status != completed 或有 pending/failed chunks 的文档
    need_reindex = []
    for doc in all_docs:
        # 通过 API 无法直接看 chunk 状态，只看文档状态
        if doc.get("status") != "completed":
            need_reindex.append(doc)
    
    if doc_limit:
        need_reindex = need_reindex[:doc_limit]
    
    print(f"\n需要重新索引的文档: {len(need_reindex)} 个")
    
    success = 0
    failed = 0
    
    for i, doc in enumerate(need_reindex):
        doc_id = doc["id"]
        fname = doc["filename"]
        chunks = doc.get("chunk_count", 0)
        print(f"\n[{i+1}/{len(need_reindex)}] {fname} ({chunks} chunks)...")
        
        try:
            resp = client.post(
                f"http://localhost:16250/api/v1/projects/{project_id}/documents/{doc_id}/reindex",
                headers=headers,
                timeout=600.0  # 大文档需要更长时间
            )
            result = resp.json()
            if result.get("success"):
                data = result.get("data", {})
                vec_count = data.get("vector_count", 0)
                chunk_count = data.get("chunk_count", 0)
                print(f"  ✅ {chunk_count} chunks, {vec_count} vectors")
                success += 1
            else:
                err = result.get("message", "unknown error")
                print(f"  ❌ {err}")
                failed += 1
        except Exception as e:
            print(f"  ❌ 请求失败: {e}")
            failed += 1
    
    client.close()
    print(f"\n=== 完成: {success} 成功, {failed} 失败 ===")
    return success, failed


def fix_completed_pending(project_id: str):
    """修复 completed 文档中的 pending chunks（不删除文档，只向量化缺失的）"""
    import httpx
    from src.core.embedding import get_embedding_service
    from src.core.vector_store import get_vector_store
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 找出有 pending chunks 的 completed 文档
    cursor.execute("""
        SELECT d.id, d.filename, COUNT(c.id) as pending_count
        FROM documents d
        JOIN chunks c ON c.document_id = d.id
        WHERE d.project_id = ? AND d.status = 'completed' 
          AND c.vector_status = 'pending' AND c.vector_id IS NULL
        GROUP BY d.id
        ORDER BY pending_count DESC
    """, (PROJECT_ID,))
    
    docs = cursor.fetchall()
    if not docs:
        print("没有需要修复的 completed 文档")
        conn.close()
        return
    
    print(f"\n需要修复的 completed 文档: {len(docs)} 个")
    
    embedding = get_embedding_service()
    vs = get_vector_store()
    
    total_fixed = 0
    total_failed = 0
    
    for doc_id, filename, pending_count in docs:
        print(f"\n  {filename}: {pending_count} pending chunks")
        
        # 获取 pending chunks
        cursor.execute("""
            SELECT id, content, metadata_json
            FROM chunks
            WHERE document_id = ? AND vector_status = 'pending' AND vector_id IS NULL
            ORDER BY chunk_index
        """, (doc_id,))
        chunks = cursor.fetchall()
        
        fixed = 0
        failed = 0
        
        # 分批处理，每批 500
        batch_size = 500
        for batch_start in range(0, len(chunks), batch_size):
            batch = chunks[batch_start:batch_start + batch_size]
            texts = [c[1] for c in batch]  # content
            
            # embedding
            try:
                results = []
                for text in texts:
                    try:
                        emb = embedding.embed_text_sync(text)
                        results.append(emb)
                    except Exception as e:
                        logger.warning(f"Embedding 失败: {e}")
                        results.append(None)
            except Exception as e:
                logger.error(f"Batch embedding 失败: {e}")
                failed += len(batch)
                continue
            
            # 构建向量数据
            vectors = []
            payloads = []
            valid_chunks = []
            
            for (chunk_id, content, meta_json), emb in zip(batch, results):
                if emb is None:
                    failed += 1
                    continue
                
                metadata = json.loads(meta_json) if meta_json else {}
                payload = {
                    "chunk_id": chunk_id,
                    "document_id": doc_id,
                    "content": content,
                    "filename": filename,
                    "start_line": metadata.get("start_line"),
                    "end_line": metadata.get("end_line"),
                }
                vectors.append(emb)
                payloads.append(payload)
                valid_chunks.append(chunk_id)
            
            # 写入 Qdrant
            if vectors:
                try:
                    vector_ids = vs.add_vectors_batch(
                        project_id=PROJECT_ID,
                        vectors=vectors,
                        payloads=payloads,
                    )
                    
                    # 更新 SQLite
                    for chunk_id, vid in zip(valid_chunks, vector_ids):
                        if vid:
                            cursor.execute("""
                                UPDATE chunks 
                                SET vector_id = ?, vector_status = 'success', vector_error = NULL
                                WHERE id = ?
                            """, (vid, chunk_id))
                            fixed += 1
                        else:
                            failed += 1
                    
                    conn.commit()
                    
                except Exception as e:
                    logger.error(f"Qdrant 写入失败: {e}")
                    failed += len(vectors)
            
            print(f"    batch {batch_start}-{batch_start+len(batch)}: fixed={fixed}, failed={failed}")
        
        total_fixed += fixed
        total_failed += failed
        print(f"  结果: {fixed} fixed, {failed} failed")
    
    conn.close()
    print(f"\n=== 总计: {total_fixed} fixed, {total_failed} failed ===")


def main():
    parser = argparse.ArgumentParser(description="修复 yunxi 项目向量数据")
    parser.add_argument("--stats", action="store_true", help="查看统计")
    parser.add_argument("--dry-run", action="store_true", help="预览")
    parser.add_argument("--fix", action="store_true", help="执行完整修复")
    parser.add_argument("--fix-docs", action="store_true", help="只修复 failed 文档（重置+reindex）")
    parser.add_argument("--fix-pending", action="store_true", help="只修复 completed 中的 pending chunks")
    parser.add_argument("--limit", type=int, help="限制处理文档数")
    args = parser.parse_args()
    
    if args.stats:
        get_stats()
        return
    
    if args.dry_run:
        get_stats()
        print("\n[DRY RUN] 预览完成，使用 --fix 执行修复")
        return
    
    if args.fix:
        print("=" * 60)
        print("开始完整修复 yunxi 项目向量数据")
        print("=" * 60)
        
        # Step 1: 重置 failed 文档
        print("\n--- Step 1: 重置 failed 文档 ---")
        reset_failed_docs()
        
        # Step 2: 重新索引 failed 文档（通过 API）
        print("\n--- Step 2: 重新索引 failed 文档 ---")
        reindex_documents(PROJECT_ID, doc_limit=args.limit)
        
        # Step 3: 修复 completed 中的 pending chunks
        print("\n--- Step 3: 修复 completed 中的 pending chunks ---")
        fix_completed_pending(PROJECT_ID)
        
        # Step 4: 最终统计
        print("\n--- Step 4: 最终统计 ---")
        get_stats()
        return
    
    if args.fix_docs:
        print("--- 修复 failed 文档 ---")
        reset_failed_docs()
        reindex_documents(PROJECT_ID, doc_limit=args.limit)
        get_stats()
        return
    
    if args.fix_pending:
        print("--- 修复 completed 中的 pending chunks ---")
        fix_completed_pending(PROJECT_ID)
        get_stats()
        return
    
    parser.print_help()


if __name__ == "__main__":
    main()
