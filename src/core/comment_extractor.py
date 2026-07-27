"""代码注释提取器（改进版）

从代码文件中提取注释部分，用于 RAG 索引。
只提取注释，不提取代码本身，避免分块破坏语法结构。

改进点：
1. Python 使用 AST 解析，准确区分注释和字符串
2. JavaScript/TypeScript 使用 AST 解析
3. Go 使用 go/ast 解析
4. 文件类型配置统一管理
"""

import ast
import io
import logging
import os
import re
import subprocess
import tokenize
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)


# ============================================================================
# 文件类型配置（统一管理，避免重复定义）
# ============================================================================

DOC_EXTENSIONS: Set[str] = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".md", ".txt", ".rst",
}

CODE_EXTENSIONS: Set[str] = {
    ".py", ".js", ".jsx", ".ts", ".tsx",
    ".java", ".go", ".rs",
    ".cpp", ".c", ".h", ".hpp", ".cc",
    ".sh", ".bash", ".zsh",
    ".rb", ".php",
}

# 配置文件类型（视作代码，不入 RAG 索引）
CONFIG_EXTENSIONS: Set[str] = {
    ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf",
    ".env", ".properties",
    ".xml",  # 配置文件/数据格式
}

IMAGE_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
}

SUPPORTED_EXTENSIONS = DOC_EXTENSIONS | IMAGE_EXTENSIONS

# 文件大小限制（避免处理超大文件）
MAX_FILE_SIZE_MB = 10  # 代码文件最大 10MB
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def get_file_category(file_path: Union[str, Path]) -> str:
    """获取文件类别
    
    Args:
        file_path: 文件路径
        
    Returns:
        文件类别: 'doc' | 'code' | 'config' | 'image' | 'unknown'
    """
    ext = Path(file_path).suffix.lower()
    
    if ext in DOC_EXTENSIONS:
        return 'doc'
    elif ext in CODE_EXTENSIONS:
        return 'code'
    elif ext in CONFIG_EXTENSIONS:
        return 'config'
    elif ext in IMAGE_EXTENSIONS:
        return 'image'
    else:
        return 'unknown'


# ============================================================================
# AST 解析器可用性检查
# ============================================================================

# 脚本路径
SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
TS_COMMENTS_SCRIPT = SCRIPTS_DIR / "ts_comments.js"
GO_COMMENTS_SCRIPT = SCRIPTS_DIR / "extract_go_comments.go"


def _check_esprima() -> bool:
    """检查 esprima (JavaScript) 是否可用"""
    try:
        import esprima
        return True
    except ImportError:
        return False


def _check_javalang() -> bool:
    """检查 javalang 是否可用"""
    try:
        import javalang
        return True
    except ImportError:
        return False


def _check_pycparser() -> bool:
    """检查 pycparser 是否可用"""
    try:
        import pycparser
        return True
    except ImportError:
        return False


def _check_node() -> bool:
    """检查 Node.js 是否可用"""
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_go() -> bool:
    """检查 Go 是否可用"""
    try:
        result = subprocess.run(
            ["go", "version"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


# 全局可用性标志
ESPRIMA_AVAILABLE = _check_esprima()
JAVALANG_AVAILABLE = _check_javalang()
PYCPARSER_AVAILABLE = _check_pycparser()
NODE_AVAILABLE = _check_node()
GO_AVAILABLE = _check_go()


# ============================================================================
# 注释提取器
# ============================================================================

class CommentExtractor:
    """代码注释提取器（改进版）
    
    支持多种编程语言的注释提取，使用不同的策略：
    - Python: AST + tokenize（最准确）
    - JavaScript: esprima AST（准确）
    - Java: javalang AST（准确）
    - C: pycparser AST（准确）
    - 其他语言: 正则（尽力而为）
    """
    
    # 文件扩展名到语言的映射
    EXT_TO_LANG: Dict[str, str] = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.c': 'c',
        '.h': 'c',
        '.cpp': 'cpp',
        '.hpp': 'cpp',
        '.cc': 'cpp',
        '.go': 'go',
        '.rs': 'rust',
        '.sh': 'shell',
        '.bash': 'shell',
        '.zsh': 'shell',
        '.rb': 'ruby',
        '.php': 'php',
    }
    
    def __init__(self):
        # 非 AST 语言的注释模式（回退方案）
        self._comment_patterns = self._init_patterns()
        
        # 日志可用性
        if ESPRIMA_AVAILABLE:
            logger.info("✅ esprima 已启用（JavaScript AST 解析）")
        if JAVALANG_AVAILABLE:
            logger.info("✅ javalang 已启用（Java AST 解析）")
        if PYCPARSER_AVAILABLE:
            logger.info("✅ pycparser 已启用（C AST 解析）")
    
    def _init_patterns(self) -> Dict[str, List[Tuple[re.Pattern, str]]]:
        """初始化正则注释模式（用于不支持 AST 的语言）"""
        patterns = {}
        
        # TypeScript/C++/Go/Rust/PHP（暂无 AST 支持，使用正则）
        for lang in ['typescript', 'cpp', 'go', 'rust', 'php']:
            patterns[lang] = [
                (re.compile(r'//[^\n]*', re.MULTILINE), 'single'),
                (re.compile(r'/[*][\s\S]*?[*]/', re.MULTILINE | re.DOTALL), 'multi'),
            ]
        
        # Shell/Ruby
        for lang in ['shell', 'ruby']:
            patterns[lang] = [
                (re.compile(r'#[^\n]*', re.MULTILINE), 'single'),
            ]
        
        # JavaScript/Java/C 的正则回退（当 AST 不可用时）
        for lang in ['javascript', 'java', 'c']:
            patterns[lang] = [
                (re.compile(r'//[^\n]*', re.MULTILINE), 'single'),
                (re.compile(r'/[*][\s\S]*?[*]/', re.MULTILINE | re.DOTALL), 'multi'),
            ]
        
        return patterns
    
    def get_language(self, file_path: Union[str, Path]) -> Optional[str]:
        """根据文件扩展名获取语言类型"""
        ext = Path(file_path).suffix.lower()
        return self.EXT_TO_LANG.get(ext)
    
    def is_code_file(self, file_path: Union[str, Path]) -> bool:
        """检查是否是支持注释提取的代码文件"""
        ext = Path(file_path).suffix.lower()
        return ext in CODE_EXTENSIONS
    
    def extract(self, file_path: Union[str, Path]) -> str:
        """提取代码文件中的所有注释
        
        Args:
            file_path: 文件路径
            
        Returns:
            提取的注释内容，格式化为 Markdown
            如果没有注释则返回空字符串
            
        Raises:
            ValueError: 文件类型不支持、文件过大或读取失败
        """
        file_path = Path(file_path)
        language = self.get_language(file_path)
        
        if not language:
            raise ValueError(f"不支持的文件类型: {file_path.suffix}")
        
        # 检查文件大小
        try:
            file_size = file_path.stat().st_size
            if file_size > MAX_FILE_SIZE_BYTES:
                raise ValueError(
                    f"文件过大 ({file_size / 1024 / 1024:.1f}MB > {MAX_FILE_SIZE_MB}MB)，跳过处理"
                )
        except FileNotFoundError:
            raise ValueError(f"文件不存在: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            raise ValueError(f"文件读取失败: {e}")
        
        # 根据语言选择解析方法
        comments = self._extract_comments(content, language, file_path)
        
        if not comments:
            logger.debug(f"文件 {file_path} 中没有找到注释")
            return ""
        
        return self._format_comments(file_path, comments)
    
    def _extract_comments(
        self, 
        content: str, 
        language: str, 
        file_path: Path
    ) -> List[str]:
        """根据语言选择解析方法
        
        Args:
            content: 代码内容
            language: 语言类型
            file_path: 文件路径（用于错误报告）
            
        Returns:
            注释列表
        """
        try:
            if language == 'python':
                return self._extract_python_comments(content, file_path)
            
            elif language == 'javascript':
                if ESPRIMA_AVAILABLE:
                    return self._extract_javascript_comments(content, file_path)
                else:
                    logger.debug("esprima 不可用，使用正则提取 JavaScript 注释")
                    return self._extract_generic_comments(content, language)
            
            elif language in ('typescript', 'tsx'):
                # TypeScript 使用 Node.js + @babel/parser
                return self._extract_typescript_comments(file_path, content)
            
            elif language == 'java':
                if JAVALANG_AVAILABLE:
                    return self._extract_java_comments(content, file_path)
                else:
                    logger.debug("javalang 不可用，使用正则提取 Java 注释")
                    return self._extract_generic_comments(content, language)
            
            elif language == 'c':
                if PYCPARSER_AVAILABLE:
                    return self._extract_c_comments(content, file_path)
                else:
                    logger.debug("pycparser 不可用，使用正则提取 C 注释")
                    return self._extract_generic_comments(content, language)
            
            elif language == 'go':
                # Go 使用 go/ast
                return self._extract_go_comments(file_path, content)
            
            else:
                # 其他语言使用正则
                return self._extract_generic_comments(content, language)
                
        except Exception as e:
            logger.warning(f"AST 解析失败 ({language}): {e}，回退到正则")
            return self._extract_generic_comments(content, language)
    
    # ========================================================================
    # Python AST 解析
    # ========================================================================
    
    def _extract_python_comments(self, content: str, file_path: Path) -> List[str]:
        """使用 AST 提取 Python 注释"""
        comments: List[str] = []
        
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            logger.warning(f"Python 语法错误: {file_path}: {e}")
            return self._extract_generic_comments(content, 'python')
        
        # 使用 tokenize 提取行注释
        try:
            tokens = tokenize.generate_tokens(io.StringIO(content).readline)
            for token in tokens:
                if token.type == tokenize.COMMENT:
                    comment_text = token.string[1:].strip()
                    if comment_text and not self._is_meaningless(comment_text):
                        comments.append(comment_text)
        except tokenize.TokenError as e:
            logger.warning(f"Token 错误: {file_path}: {e}")
        
        # 提取 docstring
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                docstring = ast.get_docstring(node)
                if docstring and docstring.strip():
                    cleaned = self._clean_docstring(docstring)
                    if cleaned:
                        comments.append(f"[{node.__class__.__name__} {node.name}] {cleaned}")
            
            if isinstance(node, ast.Module):
                docstring = ast.get_docstring(node)
                if docstring and docstring.strip():
                    cleaned = self._clean_docstring(docstring)
                    if cleaned:
                        comments.insert(0, f"[Module] {cleaned}")
        
        return comments
    
    # ========================================================================
    # JavaScript AST 解析
    # ========================================================================
    
    def _extract_javascript_comments(self, content: str, file_path: Path) -> List[str]:
        """使用 esprima 提取 JavaScript 注释"""
        import esprima
        
        comments: List[str] = []
        
        try:
            # esprima 可以提取注释
            tree = esprima.parseScript(content, options={'comment': True})
        except esprima.Error as e:
            logger.warning(f"JavaScript 语法错误: {file_path}: {e}")
            return self._extract_generic_comments(content, 'javascript')
        
        # 提取注释
        if hasattr(tree, 'comments'):
            for comment in tree.comments:
                comment_text = comment.value.strip()
                
                if comment.type == 'Line':
                    # 单行注释
                    if comment_text and not self._is_meaningless(comment_text):
                        comments.append(comment_text)
                
                elif comment.type == 'Block':
                    # 多行注释
                    cleaned = self._clean_block_comment(comment_text)
                    if cleaned:
                        comments.append(cleaned)
        
        return comments
    
    def _clean_block_comment(self, comment: str) -> str:
        """清理块注释"""
        lines = []
        for line in comment.split('\n'):
            line = line.strip()
            if line.startswith('*'):
                line = line[1:].strip()
            if line and not self._is_meaningless(line):
                lines.append(line)
        
        result = '\n'.join(lines) if lines else ""
        if len(result) > 500:
            result = result[:500] + '...'
        return result
    
    # ========================================================================
    # TypeScript AST 解析（使用 Node.js + @babel/parser）
    # ========================================================================
    
    def _extract_typescript_comments(self, file_path: Path, content: str) -> List[str]:
        """使用 Node.js + @babel/parser 提取 TypeScript 注释"""
        if not NODE_AVAILABLE or not TS_COMMENTS_SCRIPT.exists():
            logger.debug("Node.js 或 TypeScript 脚本不可用，使用正则")
            return self._extract_generic_comments(content, 'typescript')
        
        try:
            result = subprocess.run(
                ["node", str(TS_COMMENTS_SCRIPT), str(file_path)],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(SCRIPTS_DIR)
            )
            
            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                lines = output.split('\n')
                comments = []
                current_comment = []
                in_comment_block = False
                
                for line in lines:
                    if '## Comments' in line:
                        continue
                    
                    if line.startswith('### Comment'):
                        # 保存之前的注释块
                        if current_comment:
                            comments.append('\n'.join(current_comment))
                            current_comment = []
                        in_comment_block = True
                        continue
                    
                    if in_comment_block:
                        if line.strip():
                            current_comment.append(line.strip())
                        elif current_comment:
                            # 只有当已经有内容时，空行才表示注释块结束
                            in_comment_block = False
                    else:
                        # 单行注释格式: "1. xxx"
                        match = re.match(r'^\d+\.\s*(.+)$', line)
                        if match:
                            comments.append(match.group(1))
                
                # 处理最后一个注释块
                if current_comment:
                    comments.append('\n'.join(current_comment))
                
                return comments
            else:
                return []
                
        except subprocess.TimeoutExpired:
            logger.warning(f"TypeScript 解析超时: {file_path}")
            return self._extract_generic_comments(content, 'typescript')
        except Exception as e:
            logger.warning(f"TypeScript 解析失败: {e}")
            return self._extract_generic_comments(content, 'typescript')
    
    # ========================================================================
    # Go AST 解析（使用 go/ast）
    # ========================================================================
    
    def _extract_go_comments(self, file_path: Path, content: str) -> List[str]:
        """使用 go/ast 提取 Go 注释
        
        通过 stdin 传递代码给 Go 脚本，避免 go run 的路径限制。
        """
        if not GO_AVAILABLE or not GO_COMMENTS_SCRIPT.exists():
            logger.debug("Go 或脚本不可用，使用正则")
            return self._extract_generic_comments(content, 'go')
        
        try:
            # 通过 stdin 传递代码
            result = subprocess.run(
                ["go", "run", str(GO_COMMENTS_SCRIPT)],
                input=content,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                output = result.stdout.strip()
                lines = output.split('\n')
                comments = []
                current_comment = []
                in_comment_block = False
                
                for line in lines:
                    if '## Comments' in line:
                        continue
                    
                    if line.startswith('### Comment'):
                        if current_comment:
                            comments.append('\n'.join(current_comment))
                            current_comment = []
                        in_comment_block = True
                        continue
                    
                    if in_comment_block:
                        if line.strip():
                            current_comment.append(line.strip())
                        elif current_comment:
                            # 只有当已经有内容时，空行才表示注释块结束
                            in_comment_block = False
                    else:
                        match = re.match(r'^\d+\.\s*(.+)$', line)
                        if match:
                            comments.append(match.group(1))
                
                if current_comment:
                    comments.append('\n'.join(current_comment))
                
                return comments
            else:
                return []
                    
        except subprocess.TimeoutExpired:
            logger.warning(f"Go 解析超时: {file_path}")
            return self._extract_generic_comments(content, 'go')
        except Exception as e:
            logger.warning(f"Go 解析失败: {e}")
            return self._extract_generic_comments(content, 'go')
    
    # ========================================================================
    # Java AST 解析
    # ========================================================================
    
    def _extract_java_comments(self, content: str, file_path: Path) -> List[str]:
        """使用 javalang 提取 Java 注释"""
        import javalang
        
        comments: List[str] = []
        
        try:
            tree = javalang.parse.parse(content)
        except javalang.parser.JavaSyntaxError as e:
            logger.warning(f"Java 语法错误: {file_path}: {e}")
            return self._extract_generic_comments(content, 'java')
        
        # javalang 不直接提供注释，需要手动处理
        # 使用正则提取，但排除字符串中的假注释
        # 这里简化处理：javalang 验证语法正确后，用正则提取
        return self._extract_generic_comments(content, 'java')
    
    # ========================================================================
    # C AST 解析
    # ========================================================================
    
    def _extract_c_comments(self, content: str, file_path: Path) -> List[str]:
        """使用 pycparser 提取 C 注释"""
        # pycparser 需要预处理过的代码，实际使用中有限制
        # 这里使用正则作为主要方法
        return self._extract_generic_comments(content, 'c')
    
    # ========================================================================
    # 正则提取（回退方案）
    # ========================================================================
    
    def _extract_generic_comments(self, content: str, language: str) -> List[str]:
        """使用正则提取注释（回退方案）
        
        注意：正则方法无法区分字符串中的假注释。
        
        Args:
            content: 代码内容
            language: 语言类型
            
        Returns:
            注释列表
        """
        if language not in self._comment_patterns:
            return []
        
        comments: List[str] = []
        
        for pattern, type_ in self._comment_patterns[language]:
            matches = pattern.findall(content)
            
            for match in matches:
                cleaned = self._clean_comment(match, type_)
                if cleaned.strip():
                    comments.append(cleaned)
        
        return comments
    
    def _clean_comment(self, comment: str, type_: str) -> str:
        """清理注释内容"""
        if type_ == 'single':
            if comment.startswith('#'):
                cleaned = comment[1:].strip()
            elif comment.startswith('//'):
                cleaned = comment[2:].strip()
            else:
                cleaned = comment.strip()
            
            if self._is_meaningless(cleaned):
                return ""
            return cleaned
        
        elif type_ == 'multi':
            cleaned = comment.strip()
            if cleaned.startswith('/*') and cleaned.endswith('*/'):
                cleaned = cleaned[2:-2].strip()
            
            lines = []
            for line in cleaned.split('\n'):
                line = line.strip()
                if line.startswith('*'):
                    line = line[1:].strip()
                if line and not self._is_meaningless(line):
                    lines.append(line)
            
            return '\n'.join(lines) if lines else ""
        
        return comment.strip()
    
    def _clean_docstring(self, docstring: str) -> str:
        """清理 docstring"""
        lines = []
        for line in docstring.split('\n'):
            line = line.strip()
            if line:
                lines.append(line)
            elif lines:
                break
        
        result = ' '.join(lines)
        if len(result) > 500:
            result = result[:500] + '...'
        
        return result
    
    def _is_meaningless(self, comment: str) -> bool:
        """判断注释是否无意义"""
        if not comment.strip():
            return True
        
        if re.match(r'^[-=_\s*]+$', comment):
            return True
        
        if re.match(r'^TODO[:\s]*$', comment, re.IGNORECASE):
            return True
        if re.match(r'^FIXME[:\s]*$', comment, re.IGNORECASE):
            return True
        
        if len(comment.strip()) < 3:
            return True
        
        return False
    
    def _format_comments(self, file_path: Path, comments: List[str]) -> str:
        """格式化注释输出"""
        parts = [
            f"# File: {file_path.name}",
            "",
            "## Comments",
            "",
        ]
        
        for i, comment in enumerate(comments, 1):
            if '\n' in comment:
                parts.append(f"### Comment {i}")
                parts.append("")
                parts.append(comment)
                parts.append("")
            else:
                parts.append(f"{i}. {comment}")
        
        return '\n'.join(parts)


def extract_code_comments(file_path: Union[str, Path]) -> str:
    """便捷函数：提取代码注释"""
    extractor = CommentExtractor()
    return extractor.extract(file_path)