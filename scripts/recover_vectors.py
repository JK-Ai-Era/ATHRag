#!/usr/bin/env python3
"""高性能向量恢复脚本 - 直接从 SQLite pending chunks 向量化并写入 Qdrant

绕过 API 逐文档 reindex，直接批量处理所有 pending chunks。
使用分批 embedding + 分批写入 Qdrant，支持并发。

用法:
    python scripts/recover_vectors.py --stats
    python scripts/recover_vectors.py --dry-run
    python scripts/recover_vectors.py --run
    python scripts/recover_vectors.py --run --doc-limit 5       # 只处理前5个文档
    python scripts/recover_vectors.py --run --concurrency 10    # 10并发
"""

import sys
sys.path.insert(0, '/Users/jk/Projects/ATHRag')

import sqlite3
import json
import time
import argparse
import logging
import concurrent.futures
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("recover-vectors")

DB_PATH = Path("/Users/jk/Projects/ATHRag/db/metadata.db")
PROJECT_ID = "a4f08741-c093-4f93-ad19-f94d0dc1040f"
QDRANT_BATCH_SIZE = 500   # 每批写入 Qdrant 的数量
EMBED_BATCH_SIZE = 50     # 每批 embedding 的数量


def get_pending_docs() -> List[Dict[str, Any]]:
    """获取所有有 pending chunks 的文档"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("""
        SELECT d.id, d.filename, d.status,
               COUNT(c.id) as pending_count
        FROM documents d
        JOIN chunks c ON c.document_id = d.id
        WHERE d.project_id = ? AND c.vector_status = 'pending' AND c.vector_id IS NULL
        GROUP BY d.id
        ORDER BY pending_count DESC
    """, (PROJECT_ID,))
    
    docs = [dict(row) for row in c.fetchall()]
    conn.close()
    return docs


def get_pending_chunks(doc_id: str, limit: int = None) -> List[Dict[str, Any]]:
    """获取文档的 pending chunks"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    query = """
        SELECT id, content, metadata_json
        FROM chunks
        WHERE document_id = ? AND vector_status = 'pending' AND vector_id IS NULL
        ORDER BY chunk_index
    """
    if limit:
        query += f" LIMIT {limit}"
    
    c.execute(query, (doc_id,))
    chunks = [dict(row) for row in c.fetchall()]
    conn.close()
    return chunks


def embed_texts_sync(texts: List[str], concurrency: int = 5) -> List[Optional[List[float]]]:
    """批量 embedding，使用线程池并发调用 Ollama"""
    from src.core.embedding import get_embedding_service
    embedding = get_embedding_service()
    
    results = [None] * len(texts)
    
    def _embed(idx_text):
        idx, text = idx_text
        try:
            return idx, embedding.embed_text_sync(text)
        except Exception as e:
            logger.warning(f"Embedding 失败 (idx={idx}): {e}")
            return idx, None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        for idx, result in executor.map(_embed, enumerate(texts)):
            results[idx] = result
    
    return results


def write_vectors_to_qdrant(project_id: str, vectors: List, payloads: List) -> List[Optional[str]]:
    """写入向量到 Qdrant（使用新的分批逻辑）"""
    from src.core.vector_store import get_vector_store
    vs = get_vector_store()
    return vs.add_vectors_batch(
        project_id=project_id,
        vectors=vectors,
        payloads=payloads,
        batch_size=QDRANT_BATCH_SIZE,
    )


def process_document(doc_id: str, filename: str, concurrency: int = 5) -> Dict[str, int]:
    """处理单个文档的所有 pending chunks"""
    chunks = get_pending_chunks(doc_id)
    total = len(chunks)
    
    if total == 0:
        return {"total": 0, "embedded": 0, "written": 0, "failed": 0}
    
    embedded = 0
    written = 0
    failed = 0
    
    # 分批处理
    for batch_start in range(0, total, EMBED_BATCH_SIZE):
        batch = chunks[batch_start:batch_start + EMBED_BATCH_SIZE]
        texts = [c["content"] for c in batch]
        
        # 批量 embedding
        embeddings = embed_texts_sync(texts, concurrency=concurrency)
        
        # 构建向量数据
        vectors = []
        payloads = []
        valid_chunks = []
        
        for chunk, emb in zip(batch, embeddings):
            if emb is None:
                failed += 1
                # 标记为 failed
                conn = sqlite3.connect(DB_PATH)
                conn.execute("UPDATE chunks SET vector_status='failed', vector_error='embedding failed' WHERE id=?",
                    (chunk["id"],))
                conn.commit()
                conn.close()
                continue
            
            metadata = json.loads(chunk["metadata_json"]) if chunk["metadata_json"] else {}
            payload = {
                "chunk_id": chunk["id"],
                "document_id": doc_id,
                "content": chunk["content"],
                "filename": filename,
                "start_line": metadata.get("start_line"),
                "end_line": metadata.get("end_line"),
                "symbols": metadata.get("symbols", []),
            }
            vectors.append(emb)
            payloads.append(payload)
            valid_chunks.append(chunk["id"])
            embedded += 1
        
        # 写入 Qdrant
        if vectors:
            try:
                vector_ids = write_vectors_to_qdrant(PROJECT_ID, vectors, payloads)
                
                # 更新 SQLite
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                for chunk_id, vid in zip(valid_chunks, vector_ids):
                    if vid:
                        c.execute("UPDATE chunks SET vector_id=?, vector_status='success', vector_error=NULL WHERE id=?",
                            (vid, chunk_id))
                        written += 1
                    else:
                        c.execute("UPDATE chunks SET vector_status='failed', vector_error='vector_id is None' WHERE id=?",
                            (chunk_id,))
                        failed += 1
                conn.commit()
                conn.close()
                
            except Exception as e:
                logger.error(f"Qdrant 写入失败: {e}")
                failed += len(vectors)
                # 标记失败
                conn = sqlite3.connect(DB_PATH)
                for chunk_id in valid_chunks:
                    conn.execute("UPDATE chunks SET vector_status='failed', vector_error=? WHERE id=?",
                        (str(e)[:200], chunk_id))
                conn.commit()
                conn.close()
        
        # 进度
        processed = batch_start + len(batch)
        if processed % (EMBED_BATCH_SIZE * 5) == 0 or processed == total:
            logger.info(f"  [{filename[:40]}] {processed}/{total}  embedded={embedded}  written={written}  failed={failed}")
    
    # 更新文档状态
    conn = sqlite3.connect(DB_PATH)
    if failed == 0 and written > 0:
        conn.execute("UPDATE documents SET status='completed', error_message=NULL, updated_at=datetime('now') WHERE id=?",
            (doc_id,))
    elif written > 0:
        conn.execute("UPDATE documents SET status='completed', error_message=?, updated_at=datetime('now') WHERE id=?",
            (f"部分成功: {written}/{total} vectors, {failed} failed", doc_id))
    else:
        conn.execute("UPDATE documents SET status='failed', error_message=?, updated_at=datetime('now') WHERE id=?",
            (f"全部失败: {failed} chunks", doc_id))
    conn.commit()
    conn.close()
    
    return {"total": total, "embedded": embedded, "written": written, "failed": failed}


def main():
    parser = argparse.ArgumentParser(description="高性能向量恢复")
    parser.add_argument("--stats", action="store_true", help="查看统计")
    parser.add_argument("--dry-run", action="store_true", help="预览")
    parser.add_argument("--run", action="store_true", help="执行恢复")
    parser.add_argument("--doc-limit", type=int, help="限制处理文档数")
    parser.add_argument("--concurrency", type=int, default=5, help="embedding 并发数")
    args = parser.parse_args()
    
    if args.stats:
        docs = get_pending_docs()
        total_pending = sum(d["pending_count"] for d in docs)
        print(f"\n=== 待恢复统计 ===")
        print(f"待处理文档: {len(docs)}")
        print(f"待处理 chunks: {total_pending}")
        print(f"\n文档详情:")
        for d in docs:
            print(f"  {d['filename'][:55]:<55} pending={d['pending_count']:>6}  status={d['status']}")
        return
    
    if args.dry_run:
        docs = get_pending_docs()
        if args.doc_limit:
            docs = docs[:args.doc_limit]
        total = sum(d["pending_count"] for d in docs)
        print(f"\n[DRY RUN] 将处理 {len(docs)} 个文档，共 {total} 个 chunks")
        print(f"并发数: {args.concurrency}")
        for d in docs:
            print(f"  {d['filename'][:55]:<55} pending={d['pending_count']:>6}")
        return
    
    if args.run:
        docs = get_pending_docs()
        if args.doc_limit:
            docs = docs[:args.doc_limit]
        
        total_chunks = sum(d["pending_count"] for d in docs)
        print(f"\n{'='*60}")
        print(f"开始恢复向量数据")
        print(f"文档数: {len(docs)}, 总 chunks: {total_chunks}")
        print(f"并发数: {args.concurrency}")
        print(f"{'='*60}\n")
        
        start_time = time.time()
        total_stats = {"total": 0, "embedded": 0, "written": 0, "failed": 0}
        
        for i, doc in enumerate(docs):
            print(f"\n[{i+1}/{len(docs)}] {doc['filename']} ({doc['pending_count']} chunks)")
            stats = process_document(doc["id"], doc["filename"], concurrency=args.concurrency)
            
            for k in total_stats:
                total_stats[k] += stats[k]
            
            elapsed = time.time() - start_time
            rate = total_stats["embedded"] / elapsed if elapsed > 0 else 0
            remaining = (total_chunks - total_stats["total"]) / rate if rate > 0 else 0
            print(f"  → 完成: {stats['written']} written, {stats['failed']} failed  |  "
                  f"总进度: {total_stats['total']}/{total_chunks}  "
                  f"速率: {rate:.0f} chunks/s  剩余: {remaining/60:.0f}min")
        
        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"恢复完成！耗时: {elapsed/60:.1f} 分钟")
        print(f"  总 chunks: {total_stats['total']}")
        print(f"  成功写入: {total_stats['written']}")
        print(f"  失败: {total_stats['failed']}")
        print(f"  速率: {total_stats['embedded']/elapsed:.0f} chunks/s")
        print(f"{'='*60}")
        
        # 最终验证
        from src.core.vector_store import get_vector_store
        vs = get_vector_store()
        count = vs.count_vectors(PROJECT_ID)
        print(f"\nQdrant 向量数: {count}")
        
        return
    
    parser.print_help()


if __name__ == "__main__":
    main()
