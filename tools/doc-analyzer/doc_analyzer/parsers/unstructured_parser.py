"""基于 Unstructured 的 Office 文档解析器

提供高质量的 Word、Excel、PowerPoint 文档解析，保留文档结构和格式。
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field

from unstructured.partition.docx import partition_docx
from unstructured.partition.xlsx import partition_xlsx
from unstructured.partition.pptx import partition_pptx
from unstructured.documents.elements import (
    Table, Text, Title, ListItem,
    NarrativeText, Header, Footer, PageBreak,
    Image as ImageElement, Formula, FigureCaption
)


@dataclass
class ParsedTable:
    """解析后的表格"""
    caption: str = ""
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    html: str = ""
    source_element: Any = None


@dataclass
class ParsedSection:
    """解析后的章节"""
    title: str = ""
    level: int = 0
    content: List[str] = field(default_factory=list)
    start_page: Optional[int] = None


@dataclass
class ParsedDocument:
    """解析后的文档结构"""
    text: str = ""                           # 纯文本内容
    markdown: str = ""                       # Markdown 格式
    metadata: Dict[str, Any] = field(default_factory=dict)
    tables: List[ParsedTable] = field(default_factory=list)
    sections: List[ParsedSection] = field(default_factory=list)
    images: List[Dict] = field(default_factory=list)
    page_count: int = 0


class UnstructuredOfficeParser:
    """Unstructured Office 文档解析器
    
    支持格式:
    - .docx (Word)
    - .xlsx (Excel)  
    - .pptx (PowerPoint)
    
    特性:
    - 自动识别标题层级
    - 表格结构化提取
    - 列表和段落区分
    - 页眉页脚过滤
    - 生成 Markdown 格式
    """

    def __init__(self):
        self.stats = {
            "tables_extracted": 0,
            "sections_extracted": 0,
            "images_extracted": 0,
        }

    def parse_docx(self, file_path: Union[str, Path]) -> ParsedDocument:
        """解析 Word 文档
        
        Args:
            file_path: 文档路径
            
        Returns:
            ParsedDocument: 解析后的文档结构
        """
        file_path = Path(file_path)

        elements = partition_docx(
            filename=str(file_path),
            include_page_breaks=True,
            include_metadata=True,
        )

        return self._process_elements(elements, file_path)

    def parse_xlsx(self, file_path: Union[str, Path]) -> ParsedDocument:
        """解析 Excel 文档
        
        将每个工作表作为章节，每个表格作为结构化数据提取。
        
        Args:
            file_path: 文档路径
            
        Returns:
            ParsedDocument: 解析后的文档结构
        """
        file_path = Path(file_path)

        elements = partition_xlsx(
            filename=str(file_path),
            include_metadata=True,
        )

        return self._process_elements(elements, file_path)

    def parse_pptx(self, file_path: Union[str, Path]) -> ParsedDocument:
        """解析 PowerPoint 文档
        
        将每个幻灯片作为章节，保留幻灯片结构。
        
        Args:
            file_path: 文档路径
            
        Returns:
            ParsedDocument: 解析后的文档结构
        """
        file_path = Path(file_path)

        elements = partition_pptx(
            filename=str(file_path),
            include_metadata=True,
        )

        return self._process_elements(elements, file_path)

    def _process_elements(
        self,
        elements: List[Any],
        file_path: Path
    ) -> ParsedDocument:
        """处理 Unstructured 元素列表
        
        Args:
            elements: Unstructured 解析出的元素列表
            file_path: 原始文件路径
            
        Returns:
            ParsedDocument: 处理后的文档结构
        """
        text_parts = []
        markdown_parts = []
        tables = []
        sections = []
        images = []

        current_section = ParsedSection(title="正文", level=0)
        current_page = 1

        for element in elements:
            element_type = type(element).__name__

            # 获取元素文本
            text = getattr(element, "text", "").strip()
            if not text and not isinstance(element, (Table, ImageElement)):
                continue

            # 获取元数据
            meta = getattr(element, "metadata", None)
            if meta is None:
                meta = {}
            # 兼容对象和字典形式的 metadata
            if hasattr(meta, 'page_number'):
                page_number = meta.page_number or current_page
            else:
                page_number = meta.get("page_number", current_page)

            # 处理分页
            if isinstance(element, PageBreak):
                current_page = page_number
                continue

            # 处理标题
            if isinstance(element, Title):
                # 保存当前章节
                if current_section.content:
                    sections.append(current_section)

                # 确定标题级别
                level = self._detect_heading_level(text, meta)

                current_section = ParsedSection(
                    title=text,
                    level=level,
                    start_page=page_number
                )

                # Markdown 标题
                markdown_parts.append(f"\n{'#' * min(level, 6)} {text}\n")
                text_parts.append(text)

            # 处理表格
            elif isinstance(element, Table):
                table_data = self._extract_table(element, text)
                tables.append(table_data)

                markdown_table = self._table_to_markdown(table_data)
                markdown_parts.append(f"\n{markdown_table}\n")
                text_parts.append(f"\n[表格: {table_data.caption or '数据表'}]\n")

            # 处理列表项
            elif isinstance(element, ListItem):
                markdown_parts.append(f"- {text}")
                current_section.content.append(text)
                text_parts.append(f"• {text}")

            # 处理图片
            elif isinstance(element, ImageElement):
                image_info = {
                    "caption": text,
                    "page": page_number,
                    "type": "image"
                }
                images.append(image_info)
                markdown_parts.append(f"\n![图片]({text})\n")

            # 跳过页眉页脚
            elif isinstance(element, (Header, Footer)):
                continue

            # 处理公式
            elif isinstance(element, Formula):
                markdown_parts.append(f"\n$$ {text} $$\n")
                current_section.content.append(text)
                text_parts.append(text)

            # 普通文本和叙事文本
            elif isinstance(element, (NarrativeText, Text)):
                markdown_parts.append(text)
                current_section.content.append(text)
                text_parts.append(text)

            # 其他类型
            else:
                if text:
                    markdown_parts.append(text)
                    current_section.content.append(text)
                    text_parts.append(text)

        # 保存最后一个章节
        if current_section.content or current_section.title != "正文":
            sections.append(current_section)

        # 提取元数据
        metadata = self._extract_metadata(elements, file_path)

        # 更新统计
        self.stats["tables_extracted"] = len(tables)
        self.stats["sections_extracted"] = len(sections)
        self.stats["images_extracted"] = len(images)

        return ParsedDocument(
            text="\n\n".join(text_parts),
            markdown="\n\n".join(markdown_parts),
            metadata=metadata,
            tables=tables,
            sections=sections,
            images=images,
            page_count=current_page
        )

    def _detect_heading_level(self, text: str, metadata: Any) -> int:
        """检测标题级别
        
        结合元数据和启发式规则确定标题级别。
        """
        # 从 metadata 获取级别信息
        if hasattr(metadata, 'category_depth'):
            level = metadata.category_depth
        elif isinstance(metadata, dict):
            level = metadata.get("category_depth")
        else:
            level = None
            
        if level is not None:
            return min(level + 1, 6)

        # 启发式规则
        # 全大写或包含特定关键词的可能是一级标题
        if text.isupper() or len(text) < 20:
            return 1

        # 包含数字的可能是二级标题 (如 "1. 引言")
        if re.match(r'^\d+[\.\s]', text):
            return 2

        return 2  # 默认二级标题

    def _extract_table(self, element: Table, text: str) -> ParsedTable:
        """提取表格数据
        
        从 Table 元素中提取结构化数据。
        """
        table_data = ParsedTable(
            caption=text if text else "",
            source_element=element
        )

        # 尝试从 metadata 获取 HTML 表示
        meta = getattr(element, "metadata", None)
        if meta is None:
            meta = {}
            
        if hasattr(meta, 'text_as_html'):
            html_content = meta.text_as_html or ""
        elif isinstance(meta, dict):
            html_content = meta.get("text_as_html", "")
        else:
            html_content = ""

        if html_content:
            table_data.html = html_content
            # 解析 HTML 获取行列数据
            headers, rows = self._parse_html_table(html_content)
            table_data.headers = headers
            table_data.rows = rows

        return table_data

    def _parse_html_table(self, html: str) -> tuple:
        """解析 HTML 表格
        
        简单的 HTML 表格解析器。
        """
        try:
            from html.parser import HTMLParser

            class TableParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.in_table = False
                    self.in_row = False
                    self.in_cell = False
                    self.current_cell = ""
                    self.current_row = []
                    self.rows = []
                    self.is_header = False

                def handle_starttag(self, tag, attrs):
                    if tag == "table":
                        self.in_table = True
                    elif tag == "tr":
                        self.in_row = True
                        self.current_row = []
                    elif tag in ["td", "th"]:
                        self.in_cell = True
                        self.current_cell = ""
                        if tag == "th":
                            self.is_header = True

                def handle_endtag(self, tag):
                    if tag == "table":
                        self.in_table = False
                    elif tag == "tr":
                        if self.in_row and self.current_row:
                            self.rows.append(self.current_row)
                        self.in_row = False
                    elif tag in ["td", "th"]:
                        if self.in_cell:
                            self.current_row.append(self.current_cell.strip())
                        self.in_cell = False

                def handle_data(self, data):
                    if self.in_cell:
                        self.current_cell += data

            parser = TableParser()
            parser.feed(html)

            # 第一行作为表头
            if parser.rows:
                return parser.rows[0], parser.rows[1:]
            return [], []

        except Exception:
            return [], []

    def _table_to_markdown(self, table: ParsedTable) -> str:
        """将表格转换为 Markdown 格式
        
        Args:
            table: 解析后的表格数据
            
        Returns:
            str: Markdown 格式的表格
        """
        lines = []

        # 添加标题
        if table.caption:
            lines.append(f"**{table.caption}**")
            lines.append("")

        # 如果没有解析出数据，返回提示
        if not table.headers and not table.rows:
            if table.html:
                return f"[表格内容 - 原始 HTML 长度: {len(table.html)}]"
            return "[表格 - 无数据]"

        # 表头
        if table.headers:
            lines.append("| " + " | ".join(table.headers) + " |")
            lines.append("|" + "|".join([" --- " for _ in table.headers]) + "|")
        elif table.rows:
            # 使用第一行作为表头参考
            first_row = table.rows[0]
            lines.append("| " + " | ".join([f"Col {i+1}" for i in range(len(first_row))]) + " |")
            lines.append("|" + "|".join([" --- " for _ in first_row]) + "|")

        # 数据行
        for row in table.rows:
            # 补齐单元格数量
            while len(row) < len(table.headers):
                row.append("")
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    def _extract_metadata(
        self,
        elements: List[Any],
        file_path: Path
    ) -> Dict[str, Any]:
        """提取文档元数据
        
        Args:
            elements: 元素列表
            file_path: 文件路径
            
        Returns:
            Dict: 元数据字典
        """
        metadata = {
            "filename": file_path.name,
            "file_type": file_path.suffix.lower(),
            "element_count": len(elements),
            "parser": "unstructured",
            "parser_version": "0.18.32"
        }

        # 从第一个元素提取更多元数据
        if elements and hasattr(elements[0], "metadata"):
            meta = elements[0].metadata
            if meta:
                metadata.update({
                    "last_modified": getattr(meta, "last_modified", None),
                    "filesize": getattr(meta, "filesize", None),
                })

        # 统计信息
        metadata["stats"] = {
            "tables": self.stats["tables_extracted"],
            "sections": self.stats["sections_extracted"],
            "images": self.stats["images_extracted"],
        }

        return metadata

    def get_stats(self) -> Dict[str, int]:
        """获取解析统计信息"""
        return self.stats.copy()
