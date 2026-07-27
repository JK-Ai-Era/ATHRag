#!/usr/bin/env python3
"""
MinerU PDF 处理器 - 使用 Python 3.11 环境
首次运行需要下载模型 (~1GB)，请耐心等待
"""

import sys
import json
import os
from pathlib import Path

def process_pdf(pdf_path):
    """使用 MinerU 处理 PDF"""
    try:
        from magic_pdf.data.data_reader_writer import FileBasedDataReader
        from magic_pdf.data.dataset import PymuDocDataset, SupportedPdfParseMethod
        from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze
        
        print(f"正在处理 PDF: {pdf_path}", file=sys.stderr)
        
        # 读取 PDF
        reader = FileBasedDataReader("")
        pdf_bytes = reader.read(pdf_path)
        
        # 解析
        dataset = PymuDocDataset(pdf_bytes)
        
        # 根据文档类型选择解析方式
        parse_method = dataset.classify()
        print(f"解析模式: {parse_method}", file=sys.stderr)
        
        if parse_method == SupportedPdfParseMethod.OCR:
            # OCR 模式
            infer_result = dataset.apply(doc_analyze, ocr=True)
            pipe_result = infer_result.pipe_ocr_mode(dataset.get_image_writer())
        else:
            # 文本模式
            infer_result = dataset.apply(doc_analyze, ocr=False)
            pipe_result = infer_result.pipe_txt_mode(dataset.get_image_writer())
        
        # 提取 Markdown 格式文本
        md_content = pipe_result.get_markdown()
        
        return {
            "success": True,
            "text": md_content,
            "pages": len(pipe_result.get_res())
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "error": "缺少 PDF 文件路径"}))
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    result = process_pdf(pdf_path)
    print(json.dumps(result, ensure_ascii=False))
