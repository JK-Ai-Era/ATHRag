# RAG 代码定位增强方案

## 问题
当前 RAG 只能定位到文件级别，无法精确到代码行号或函数位置。

## 解决方案

### 1. 代码文件特殊处理
在 `chunker.py` 中添加代码感知分块：

```python
def chunk_code(self, text: str, file_path: str) -> List[dict]:
    """对代码文件进行语义分块，保留结构信息"""
    # 按函数/类/方法分块
    # 每个 chunk 包含：
    # - 起始行号、结束行号
    # - 函数/类名
    # - 代码内容
    # - 文件路径
```

### 2. 增强 Chunk Metadata
在 `chunks.metadata_json` 中存储：

```json
{
  "start_line": 45,
  "end_line": 78,
  "symbol": "calculateWuxing",
  "symbol_type": "function",
  "file_path": "algorithm/src/core/wuxing/Wuxing.ts",
  "language": "typescript"
}
```

### 3. 搜索结果显示位置
修改 `SearchResult` 结构：

```python
class SearchResult(BaseModel):
    content: str
    score: float
    file_path: str
    location: CodeLocation  # 新增
    
class CodeLocation(BaseModel):
    start_line: int
    end_line: int
    symbol: Optional[str]  # 函数/类名
    symbol_type: Optional[str]  # function, class, method
```

### 4. 索引代码结构
创建 `code_symbols` 表存储代码符号索引：

```sql
CREATE TABLE code_symbols (
    id VARCHAR(36) PRIMARY KEY,
    project_id VARCHAR(36),
    document_id VARCHAR(36),
    symbol_name VARCHAR(255),
    symbol_type VARCHAR(50),  -- function, class, variable
    start_line INTEGER,
    end_line INTEGER,
    signature TEXT  -- 函数签名
);
```

## 实现优先级

1. **高优先**: 在 chunk metadata 中添加行号信息（改动小，效果明显）
2. **中优先**: 搜索结果显示文件路径和行号
3. **低优先**: 代码符号索引（需要解析 AST）

## 预期效果

用户提问后，AI 可以回答：
> "在 `algorithm/src/core/wuxing/Wuxing.ts` 第 45-78 行的 `calculateWuxing` 函数中..."

而不是：
> "在 Wuxing.ts 文件中..."
