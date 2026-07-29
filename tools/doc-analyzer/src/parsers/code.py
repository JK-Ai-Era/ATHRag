"""代码注释提取器

从代码文件中提取注释部分，用于 RAG 索引。
只提取注释，不提取代码本身，避免分块破坏语法结构。

支持：
- Python: AST 解析，准确区分注释和字符串
- JavaScript/TypeScript: 正则提取
- Go: 正则提取
- 通用: 正则兜底
"""

from __future__ import annotations

import ast
import io
import logging
import re
import tokenize
from pathlib import Path
from typing import List, Optional

from src.contract import ParseResult, error_result
from src.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# 代码文件扩展名
CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".java", ".go", ".rs",
    ".cpp", ".c", ".h", ".hpp", ".cc",
    ".sh", ".bash", ".zsh",
    ".rb", ".php",
}

# 配置文件扩展名（不入索引）
CONFIG_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf",
    ".env", ".properties",
    ".xml",
}


class CodeParser(BaseParser):
    """代码注释提取器"""

    parser_name = "code"
    supported_extensions = list(CODE_EXTENSIONS)

    # 最大文件大小（避免处理超大文件）
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    def parse(self, file_path: Path) -> ParseResult:
        file_path = Path(file_path).resolve()

        # 文件大小检查
        if file_path.stat().st_size > self.MAX_FILE_SIZE:
            return error_result(
                str(file_path),
                f"代码文件过大（>{self.MAX_FILE_SIZE // 1024 // 1024}MB），跳过索引",
                file_path.suffix.lstrip("."),
            )

        # 跳过配置文件
        if file_path.suffix.lower() in CONFIG_EXTENSIONS:
            return error_result(
                str(file_path),
                "配置文件不入索引",
                file_path.suffix.lstrip("."),
            )

        try:
            comments = self._extract_comments(file_path)
        except Exception as e:
            return error_result(
                str(file_path),
                f"代码注释提取失败: {e}",
                file_path.suffix.lstrip("."),
            )

        if not comments or not comments.strip():
            return error_result(
                str(file_path),
                "代码文件无注释内容",
                file_path.suffix.lstrip("."),
            )

        metadata = {
            "filename": file_path.name,
            "file_size": file_path.stat().st_size,
            "parser_backend": "builtin",
            "language": self._detect_language(file_path),
            "encoding": self._detect_encoding(file_path),
        }

        return ParseResult(
            source=str(file_path),
            type="document",
            format=file_path.suffix.lstrip("."),
            content=comments,
            metadata=metadata,
            parser="code",
        )

    def _extract_comments(self, file_path: Path) -> str:
        """根据文件类型提取注释"""
        ext = file_path.suffix.lower()

        if ext == ".py":
            return self._extract_python_comments(file_path)
        elif ext in (".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs",
                      ".cpp", ".c", ".h", ".hpp", ".cc", ".rb", ".php"):
            return self._extract_c_style_comments(file_path)
        elif ext in (".sh", ".bash", ".zsh"):
            return self._extract_shell_comments(file_path)
        else:
            return self._extract_generic_comments(file_path)

    def _extract_python_comments(self, file_path: Path) -> str:
        """使用 Python AST 精确提取注释和 docstring"""
        try:
            content = self._read_text_file(file_path)
            tree = ast.parse(content)
        except SyntaxError:
            # AST 解析失败，回退到 tokenize
            return self._extract_python_comments_tokenize(file_path)
        except Exception:
            return self._extract_generic_comments(file_path)

        comments: List[str] = []

        # 提取模块级 docstring
        module_docstring = ast.get_docstring(tree)
        if module_docstring:
            comments.append(module_docstring)

        # 提取函数和类的 docstring
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                docstring = ast.get_docstring(node)
                if docstring:
                    name = node.name
                    kind = "类" if isinstance(node, ast.ClassDef) else "函数"
                    comments.append(f"[{kind}: {name}]\n{docstring}")

        # 使用 tokenize 提取行注释
        line_comments = self._extract_line_comments_tokenize(file_path)
        if line_comments:
            comments.extend(line_comments)

        return "\n\n".join(c.strip() for c in comments if c.strip())

    def _extract_python_comments_tokenize(self, file_path: Path) -> str:
        """使用 tokenize 提取 Python 注释（AST 失败时的回退）"""
        comments = self._extract_line_comments_tokenize(file_path)
        return "\n\n".join(c.strip() for c in comments if c.strip())

    def _extract_line_comments_tokenize(self, file_path: Path) -> List[str]:
        """使用 tokenize 提取行注释"""
        try:
            content = self._read_text_file(file_path)
            tokens = tokenize.generate_tokens(io.StringIO(content).readline)
            comments = []
            for tok_type, tok_string, *_ in tokens:
                if tok_type == tokenize.COMMENT:
                    comment = tok_string.lstrip("#").strip()
                    if comment:
                        comments.append(comment)
            return comments
        except Exception:
            return []

    def _extract_c_style_comments(self, file_path: Path) -> str:
        """提取 C 风格注释（// 和 /* */）"""
        try:
            content = self._read_text_file(file_path)
        except Exception:
            return ""

        comments: List[str] = []

        # 多行注释 /* ... */
        for match in re.finditer(r"/\*\s*(.*?)\s*\*/", content, re.DOTALL):
            comment = match.group(1).strip()
            # 清理每行的前导 *
            lines = [re.sub(r"^\s*\*\s?", "", line) for line in comment.split("\n")]
            comment = "\n".join(line.strip() for line in lines if line.strip())
            if comment:
                comments.append(comment)

        # 单行注释 //
        for match in re.finditer(r"//\s*(.+)$", content, re.MULTILINE):
            comment = match.group(1).strip()
            if comment and not comment.startswith("noinspection"):
                comments.append(comment)

        return "\n\n".join(comments)

    def _extract_shell_comments(self, file_path: Path) -> str:
        """提取 Shell 脚本注释"""
        try:
            content = self._read_text_file(file_path)
        except Exception:
            return ""

        comments: List[str] = []
        for match in re.finditer(r"#\s*(.+)$", content, re.MULTILINE):
            comment = match.group(1).strip()
            # 跳过 shebang 和编码声明
            if comment and not comment.startswith("!") and "coding" not in comment:
                comments.append(comment)

        return "\n\n".join(comments)

    def _extract_generic_comments(self, file_path: Path) -> str:
        """通用注释提取（正则兜底）"""
        try:
            content = self._read_text_file(file_path)
        except Exception:
            return ""

        comments: List[str] = []

        # 匹配各种注释风格
        patterns = [
            r"#\s*(.+)$",           # # 注释
            r"//\s*(.+)$",          # // 注释
            r"/\*\s*(.*?)\s*\*/",   # /* 注释 */
            r"--\s*(.+)$",          # -- 注释 (SQL/Lua)
            r";\s*(.+)$",           # ; 注释 (ASM)
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
                comment = match.group(1).strip()
                if comment and len(comment) > 2:  # 跳过太短的
                    comments.append(comment)

        return "\n\n".join(comments)

    def _detect_language(self, file_path: Path) -> str:
        """检测编程语言"""
        ext_map = {
            ".py": "python", ".js": "javascript", ".jsx": "javascript",
            ".ts": "typescript", ".tsx": "typescript",
            ".java": "java", ".go": "go", ".rs": "rust",
            ".cpp": "cpp", ".c": "c", ".h": "c", ".hpp": "cpp", ".cc": "cpp",
            ".sh": "shell", ".bash": "shell", ".zsh": "shell",
            ".rb": "ruby", ".php": "php",
        }
        return ext_map.get(file_path.suffix.lower(), "unknown")
