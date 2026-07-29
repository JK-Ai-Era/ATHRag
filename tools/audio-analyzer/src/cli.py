"""audio-analyzer CLI 入口

用法：
    # 解析单个文件（自动选择解析器）
    audio-analyze song.mp3

    # 指定解析器
    audio-analyze speech.wav --parser speech

    # 指定 Whisper 模型
    audio-analyze speech.wav --parser speech --model large

    # 列出支持的格式
    audio-analyze --list-formats

    # 列出解析器状态
    audio-analyze --status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .dispatcher import AudioDispatcher


def main():
    parser = argparse.ArgumentParser(
        description="ATHRag 音频解析器 — 将音频文件解析为标准化 JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "file",
        nargs="?",
        help="要解析的音频文件路径",
    )

    parser.add_argument(
        "--parser", "-p",
        help="指定解析器（metadata / features / speech）",
    )

    parser.add_argument(
        "--model", "-m",
        default="base",
        help="Whisper 模型大小（tiny / base / small / medium / large）",
    )

    parser.add_argument(
        "--language", "-l",
        help="指定语言（如 zh, en, ja）",
    )

    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="列出支持的文件格式",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="显示解析器状态",
    )

    parser.add_argument(
        "--pretty",
        action="store_true",
        default=True,
        help="格式化 JSON 输出（默认开启）",
    )

    args = parser.parse_args()

    dispatcher = AudioDispatcher()

    # 列出格式
    if args.list_formats:
        print("支持的音频格式：\n")
        formats = dispatcher.list_formats()
        for name, info in formats.items():
            exts = ", ".join(f".{ext}" for ext in info["formats"])
            print(f"  ✅ {name:12s} {exts}")
            print(f"             {info['description']}")
            print()
        return

    # 状态检查
    if args.status:
        print("解析器状态：\n")
        parsers = dispatcher.list_parsers()
        for p in parsers:
            exts = ", ".join(f".{ext}" for ext in p["formats"])
            print(f"  {p['name']:12s} ✅ 可用  ({exts})")
        print(f"\n共 {len(parsers)} 个解析器")
        return

    # 解析文件
    if not args.file:
        parser.print_help()
        sys.exit(1)

    file_path = Path(args.file)

    # 构造选项
    options = {}
    if args.model:
        options["model"] = args.model
    if args.language:
        options["language"] = args.language

    # 执行解析
    result = dispatcher.dispatch(file_path, parser=args.parser, **options)

    # 输出 JSON
    print(result.to_json(indent=2 if args.pretty else None))

    # 设置退出码
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
