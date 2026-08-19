#!/usr/bin/env python3
"""清理 yunxi 项目的脏数据

问题：
1. 445 文档只有 112 个唯一文件名，74.8% 是重复的
2. 1,180,619 chunks 全部 pending，需要清理重复后重新索引
3. 卡在 processing 状态的文档需要重置

策略：
1. 按 filename 分组，每个文件只保留最新的一条文档记录
2. 删除旧的重复文档及其 chunks
3. 重置 processing 状态的文档为 failed（允许重新处理）
4. 统计清理结果
"""

import sys
import os
import sqlite3
from pathlib import Path
from datetime import datetime

# 项目路径
PROJECT_ID = "a4f08741-c093-4f93-ad19-f94d0dc1040f"
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "metadata.db")
PROJECTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "projects", PROJECT_ID)

def main():
    dry_run = "--dry-run" in sys.argv
    
    if dry_run:
        print("🔍 DRY RUN 模式 — 只统计，不修改\n")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # ===== 1. 统计现状 =====
    c.execute("SELECT COUNT(*) FROM documents WHERE project_id=?", (PROJECT_ID,))
    total_docs = c.fetchone()[0]
    
    c.execute("SELECT COUNT(DISTINCT filename) FROM documents WHERE project_id=?", (PROJECT_ID,))
    unique_files = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM chunks WHERE project_id=?", (PROJECT_ID,))
    total_chunks = c.fetchone()[0]
    
    c.execute("SELECT status, COUNT(*) FROM documents WHERE project_id=? GROUP BY status", (PROJECT_ID,))
    status_dist = {row[0]: row[1] for row in c.fetchall()}
    
    print("=" * 60)
    print("📊 清理前统计")
    print("=" * 60)
    print(f"  文档总数: {total_docs}")
    print(f"  唯一文件名: {unique_files}")
    print(f"  重复文档: {total_docs - unique_files} ({(total_docs - unique_files) / total_docs * 100:.1f}%)")
    print(f"  Chunk 总数: {total_chunks}")
    print(f"  文档状态分布: {status_dist}")
    print()
    
    # ===== 2. 找出重复文档，每个文件只保留最新 =====
    c.execute("""
        SELECT filename, GROUP_CONCAT(id) as ids, COUNT(*) as cnt
        FROM documents 
        WHERE project_id=?
        GROUP BY filename
        HAVING cnt > 1
        ORDER BY cnt DESC
    """, (PROJECT_ID,))
    duplicates = c.fetchall()
    
    docs_to_delete = []
    chunks_to_delete = 0
    
    for row in duplicates:
        filename = row[0]
        all_ids = row[1].split(",")
        # 保留最新的（最后一个 created_at 最大）
        # 先查每个 doc 的 created_at
        placeholders = ",".join(["?"] * len(all_ids))
        c.execute(f"""
            SELECT id, created_at, status, chunk_count 
            FROM documents 
            WHERE id IN ({placeholders})
            ORDER BY created_at DESC
        """, all_ids)
        doc_infos = c.fetchall()
        
        keep_id = doc_infos[0][0]  # 保留最新的
        for info in doc_infos[1:]:
            docs_to_delete.append(info[0])
            # 估算 chunks 数
            c.execute("SELECT COUNT(*) FROM chunks WHERE document_id=?", (info[0],))
            chunk_cnt = c.fetchone()[0]
            chunks_to_delete += chunk_cnt
    
    print(f"🗑️  待删除重复文档: {len(docs_to_delete)} 个")
    print(f"🗑️  待删除重复 chunks: {chunks_to_delete} 个")
    print()
    
    # ===== 3. 重置 processing 状态的文档 =====
    c.execute("""
        SELECT COUNT(*) FROM documents 
        WHERE project_id=? AND status='processing'
    """, (PROJECT_ID,))
    processing_count = c.fetchone()[0]
    
    print(f"🔄 待重置 processing 文档: {processing_count} 个")
    print()
    
    if dry_run:
        print("🔍 DRY RUN 完成，未做任何修改")
        conn.close()
        return
    
    # ===== 4. 执行清理 =====
    print("🚀 开始清理...")
    
    # 4a. 删除重复文档的 chunks
    deleted_chunks = 0
    for doc_id in docs_to_delete:
        c.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
        deleted_chunks += c.rowcount
        c.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    
    print(f"  ✓ 删除 {len(docs_to_delete)} 个重复文档")
    print(f"  ✓ 删除 {deleted_chunks} 个重复 chunks")
    
    # 4b. 重置 processing 文档为 failed（允许重新处理）
    c.execute("""
        UPDATE documents SET status='failed', error_message='reset from stuck processing'
        WHERE project_id=? AND status='processing'
    """, (PROJECT_ID,))
    print(f"  ✓ 重置 {processing_count} 个 processing 文档为 failed")
    
    # 4c. 更新项目统计
    c.execute("SELECT COUNT(*) FROM documents WHERE project_id=?", (PROJECT_ID,))
    new_doc_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM chunks WHERE project_id=?", (PROJECT_ID,))
    new_chunk_count = c.fetchone()[0]
    
    c.execute("""
        UPDATE projects SET document_count=?, chunk_count=?
        WHERE id=?
    """, (new_doc_count, new_chunk_count, PROJECT_ID))
    
    conn.commit()
    
    print()
    print("=" * 60)
    print("📊 清理后统计")
    print("=" * 60)
    print(f"  文档总数: {new_doc_count} (减少 {total_docs - new_doc_count})")
    print(f"  Chunk 总数: {new_chunk_count} (减少 {total_chunks - new_chunk_count})")
    
    c.execute("SELECT status, COUNT(*) FROM documents WHERE project_id=? GROUP BY status", (PROJECT_ID,))
    new_status_dist = {row[0]: row[1] for row in c.fetchall()}
    print(f"  文档状态分布: {new_status_dist}")
    
    conn.close()
    print()
    print("✅ 清理完成！")
    print(f"   下一步: 调用 POST /api/v1/projects/{PROJECT_ID}/revectorize 重新向量化")

if __name__ == "__main__":
    main()
