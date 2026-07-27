#!/usr/bin/env python3
"""测试 Unstructured Office 解析器

用法:
    python test_unstructured.py <文件路径>
    python test_unstructured.py --test-all  # 测试所有示例文件

示例:
    python test_unstructured.py ~/Documents/sample.docx
    python test_unstructured.py ~/Documents/sample.xlsx
    python test_unstructured.py ~/Documents/sample.pptx
"""

import sys
import json
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.unstructured_parser import UnstructuredOfficeParser
from src.core.document_processor import DocumentProcessor


def print_separator(title: str):
    """打印分隔线"""
    print(f"\n{'='*70}")
    print(f" {title}")
    print(f"{'='*70}\n")


def test_unstructured_parser(file_path: Path):
    """测试 Unstructured 解析器"""
    doc_type = file_path.suffix.lower().lstrip('.')

    print_separator(f"测试文件: {file_path.name} (类型: {doc_type})")

    parser = UnstructuredOfficeParser()

    try:
        if doc_type == "docx":
            result = parser.parse_docx(file_path)
        elif doc_type == "xlsx":
            result = parser.parse_xlsx(file_path)
        elif doc_type == "pptx":
            result = parser.parse_pptx(file_path)
        else:
            print(f"❌ 不支持的文件类型: {doc_type}")
            return False

        # 输出统计
        print("📊 解析统计:")
        print(f"   • 纯文本长度: {len(result.text)} 字符")
        print(f"   • Markdown 长度: {len(result.markdown)} 字符")
        print(f"   • 表格数量: {len(result.tables)}")
        print(f"   • 章节数量: {len(result.sections)}")
        print(f"   • 图片数量: {len(result.images)}")
        print(f"   • 页数/幻灯片数: {result.page_count}")

        # 输出元数据
        print("\n📋 元数据:")
        for key, value in result.metadata.items():
            if key != "stats":
                print(f"   • {key}: {value}")

        # 输出表格详情
        if result.tables:
            print("\n📈 表格详情:")
            for i, table in enumerate(result.tables, 1):
                print(f"   表格 {i}:")
                print(f"      - 标题: {table.caption or 'N/A'}")
                print(f"      - 列数: {len(table.headers) if table.headers else len(table.rows[0]) if table.rows else 0}")
                print(f"      - 行数: {len(table.rows)}")

        # 输出章节结构
        if result.sections:
            print("\n📑 章节结构:")
            for section in result.sections[:10]:  # 最多显示10个章节
                indent = "  " * section.level
                content_preview = section.content[0][:50] if section.content else ""
                print(f"{indent}{'#' * (section.level + 1)} {section.title}")
                if content_preview:
                    print(f"{indent}   └─ {content_preview}...")

            if len(result.sections) > 10:
                print(f"   ... 还有 {len(result.sections) - 10} 个章节")

        # 输出内容预览
        print("\n📝 Markdown 预览 (前 800 字符):")
        preview = result.markdown[:800]
        print(preview)
        if len(result.markdown) > 800:
            print(f"\n... [还有 {len(result.markdown) - 800} 字符]")

        print("\n✅ Unstructured 解析成功!")
        return True

    except Exception as e:
        print(f"\n❌ Unstructured 解析失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_document_processor(file_path: Path):
    """测试 DocumentProcessor 集成"""
    doc_type = file_path.suffix.lower().lstrip('.')

    print_separator(f"测试 DocumentProcessor: {file_path.name}")

    processor = DocumentProcessor()

    print(f"解析器状态:")
    print(f"   • Unstructured: {'✅ 可用' if processor.unstructured_available else '❌ 不可用'}")
    print(f"   • MinerU: {'✅ 可用' if processor.mineru_available else '❌ 不可用'}")

    try:
        # 测试 extract_text
        print("\n📝 测试 extract_text():")
        text = processor.extract_text(file_path, doc_type)
        print(f"   ✅ 成功提取 {len(text)} 字符")
        print(f"   预览: {text[:200]}...")

        # 测试 extract_structured (仅 Office 文档)
        if doc_type in ["docx", "xlsx", "pptx"]:
            print("\n📊 测试 extract_structured():")
            structured = processor.extract_structured(file_path, doc_type)
            print(f"   ✅ 成功提取结构化数据")
            print(f"   • 表格数: {len(structured.get('tables', []))}")
            print(f"   • 章节数: {len(structured.get('sections', []))}")

        print("\n✅ DocumentProcessor 测试通过!")
        return True

    except Exception as e:
        print(f"\n❌ DocumentProcessor 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def create_sample_files():
    """创建示例测试文件（如果不存在）"""
    test_dir = Path(__file__).parent.parent / "test_files"
    test_dir.mkdir(exist_ok=True)

    # 检查是否已有测试文件
    samples = list(test_dir.glob("*.docx")) + list(test_dir.glob("*.xlsx")) + list(test_dir.glob("*.pptx"))

    if not samples:
        print("ℹ️ 未找到测试文件，请提供 Office 文件进行测试")
        print(f"   建议将测试文件放在: {test_dir}")
    else:
        print(f"ℹ️ 发现 {len(samples)} 个测试文件:")
        for f in samples:
            print(f"   • {f.name}")

    return samples


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python test_unstructured.py <文件路径>")
        print("   或: python test_unstructured.py --test-all")
        print()

        # 尝试查找测试文件
        samples = create_sample_files()

        if samples:
            print("\n测试第一个发现的文件:")
            test_file = samples[0]
        else:
            print("\n❌ 未找到测试文件，请提供文件路径")
            sys.exit(1)
    else:
        arg = sys.argv[1]

        if arg == "--test-all":
            # 测试所有示例文件
            samples = create_sample_files()
            if not samples:
                print("❌ 未找到测试文件")
                sys.exit(1)

            results = []
            for sample in samples:
                success = test_unstructured_parser(sample)
                results.append((sample.name, success))
                print()

            print_separator("测试结果汇总")
            for name, success in results:
                status = "✅ 通过" if success else "❌ 失败"
                print(f"   {status}: {name}")
            return
        else:
            test_file = Path(arg)

    if not test_file.exists():
        print(f"❌ 文件不存在: {test_file}")
        sys.exit(1)

    # 运行测试
    print(f"\n🚀 开始测试: {test_file.absolute()}\n")

    # 测试 Unstructured 解析器
    success1 = test_unstructured_parser(test_file)

    # 测试 DocumentProcessor 集成
    success2 = test_document_processor(test_file)

    # 汇总
    print_separator("测试完成")
    print(f"Unstructured 解析器: {'✅ 通过' if success1 else '❌ 失败'}")
    print(f"DocumentProcessor 集成: {'✅ 通过' if success2 else '❌ 失败'}")

    if success1 and success2:
        print("\n🎉 所有测试通过!")
        sys.exit(0)
    else:
        print("\n⚠️ 部分测试失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
