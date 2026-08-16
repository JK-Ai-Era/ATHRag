"""doc-analyze CLI 入口

用法：
    # 解析单个文件（输出 JSON）
    doc-analyze /path/to/file.pdf

    # 指定输出格式
    doc-analyze /path/to/file.pdf --format json

    # 解析目录下所有文件
    doc-analyze --batch /path/to/directory/

    # 列出支持的格式
    doc-analyze --list-formats

    # 检查解析器状态
    doc-analyze --status
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import List

from doc_analyzer.dispatcher import ParseDispatcher
from doc_analyzer.contract import ParseResult, error_result

logger = logging.getLogger("doc-analyze")


def main(argv: List[str] | None = None) -> int:
    """CLI 入口"""
    args = parse_args(argv)
    setup_logging(args.verbose)

    dispatcher = ParseDispatcher()

    # 列出支持的格式
    if args.list_formats:
        return cmd_list_formats(dispatcher)

    # 检查解析器状态
    if args.status:
        return cmd_status(dispatcher)

    # 批量解析
    if args.batch:
        return cmd_batch(dispatcher, args.batch, args.output)

    # 单文件解析
    if args.file:
        return cmd_single(dispatcher, args.file, args.output)

    # 没有参数，打印帮助
    print("用法: doc-analyze <file> [--format json]")
    print("      doc-analyze --batch <directory>")
    print("      doc-analyze --list-formats")
    print("      doc-analyze --status")
    print("      doc-analyze --help")
    return 1


def parse_args(argv: List[str] | None) -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        prog="doc-analyze",
        description="ATHRag 文档解析器 — 将文档解析为标准化 JSON",
    )

    parser.add_argument(
        "file",
        nargs="?",
        help="要解析的文件路径",
    )

    parser.add_argument(
        "--batch",
        metavar="DIR",
        help="批量解析目录下的所有文件",
    )

    parser.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="输出格式（默认: json）",
    )

    parser.add_argument(
        "-o", "--output",
        metavar="FILE",
        help="输出到文件（默认: stdout）",
    )

    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="列出所有支持的文件格式",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="检查解析器状态",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细日志输出",
    )

    return parser.parse_args(argv)


def setup_logging(verbose: bool) -> None:
    """配置日志"""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def output_result(result: ParseResult, output_path: str | None) -> int:
    """输出解析结果"""
    json_str = result.to_json(indent=2)

    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding="utf-8")
        logger.info(f"结果已写入: {out_path}")
    else:
        print(json_str)

    return 0 if result.success else 1


def cmd_single(dispatcher: ParseDispatcher, file_path: str, output: str | None) -> int:
    """单文件解析"""
    path = Path(file_path)
    if not path.exists():
        result = error_result(str(path), "文件不存在")
        return output_result(result, output)

    start = time.time()
    result = dispatcher.dispatch(path)
    elapsed = time.time() - start

    logger.info(f"解析完成: {path.name} ({elapsed:.2f}s, {len(result.content)} 字符)")
    return output_result(result, output)


def cmd_batch(dispatcher: ParseDispatcher, dir_path: str, output: str | None) -> int:
    """批量解析目录"""
    directory = Path(dir_path)
    if not directory.exists():
        print(f"错误: 目录不存在: {directory}", file=sys.stderr)
        return 1

    if not directory.is_dir():
        print(f"错误: 不是目录: {directory}", file=sys.stderr)
        return 1

    supported = dispatcher.list_supported_extensions()
    results = []
    total = 0
    success = 0
    failed = 0

    start = time.time()

    for file_path in sorted(directory.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in supported:
            continue

        total += 1
        logger.info(f"[{total}] 解析: {file_path.name}")

        result = dispatcher.dispatch(file_path)
        results.append(result.to_dict())

        if result.success:
            success += 1
        else:
            failed += 1
            logger.warning(f"  失败: {result.error}")

    elapsed = time.time() - start

    # 输出结果
    batch_output = {
        "source_dir": str(directory),
        "total": total,
        "success": success,
        "failed": failed,
        "elapsed_seconds": round(elapsed, 2),
        "results": results,
    }

    json_str = json.dumps(batch_output, ensure_ascii=False, indent=2)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding="utf-8")
        print(f"批量解析完成: {success}/{total} 成功，{failed} 失败，结果写入 {out_path}")
    else:
        print(json_str)

    return 0 if failed == 0 else 1


def cmd_list_formats(dispatcher: ParseDispatcher) -> int:
    """列出支持的格式"""
    print("支持的文件格式：\n")

    for info in dispatcher.list_parsers():
        status = "✅" if info["enabled"] else "❌"
        extensions = ", ".join(info["extensions"])
        print(f"  {status} {info['name']:12s}  {extensions}")
        if info["description"]:
            print(f"     {'':12s}  {info['description']}")
        print()

    return 0


def cmd_status(dispatcher: ParseDispatcher) -> int:
    """检查解析器状态"""
    print("解析器状态：\n")

    for info in dispatcher.list_parsers():
        status = "✅ 可用" if info["enabled"] else "❌ 禁用"
        print(f"  {info['name']:12s}  {status}")

    print(f"\n共 {len(dispatcher.list_parsers())} 个解析器")
    print(f"支持 {len(dispatcher.list_supported_extensions())} 种文件扩展名")

    return 0


if __name__ == "__main__":
    sys.exit(main())
