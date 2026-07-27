#!/usr/bin/env node
/**
 * TypeScript AST 注释提取器
 * 
 * 使用 @babel/parser 解析 TypeScript/JavaScript 代码，
 * 准确提取注释（不包含字符串中的假注释）
 */

const fs = require('fs');
const path = require('path');

// 动态导入 @babel/parser (如果可用)
let parser = null;
try {
    parser = require('@babel/parser');
} catch (e) {
    // @babel/parser 不可用，回退到正则
}

/**
 * 提取注释
 */
function extractComments(code, filePath) {
    const comments = [];
    
    if (parser) {
        // 使用 Babel parser (支持 TypeScript)
        try {
            const ast = parser.parse(code, {
                sourceType: 'module',
                plugins: [
                    'typescript',
                    'jsx',
                ],
                tokens: false,
                comment: true,
            });
            
            // 提取所有注释
            if (ast.comments) {
                for (const comment of ast.comments) {
                    const text = comment.value.trim();
                    if (comment.type === 'CommentLine') {
                        // 单行注释
                        if (text && !isMeaningless(text)) {
                            comments.push(text);
                        }
                    } else if (comment.type === 'CommentBlock') {
                        // 多行注释
                        const cleaned = cleanBlockComment(text);
                        if (cleaned) {
                            comments.push(cleaned);
                        }
                    }
                }
            }
            return comments;
        } catch (e) {
            // 解析失败，回退到正则
        }
    }
    
    // 回退：使用正则提取
    const lineComments = code.match(/\/\/[^\n]*/g) || [];
    const blockComments = code.match(/\/\*[\s\S]*?\*\//g) || [];
    
    for (const c of lineComments) {
        const text = c.slice(2).trim();
        if (text && !isMeaningless(text)) {
            comments.push(text);
        }
    }
    
    for (const c of blockComments) {
        const text = c.slice(2, -2).trim();
        const cleaned = cleanBlockComment(text);
        if (cleaned) {
            comments.push(cleaned);
        }
    }
    
    return comments;
}

/**
 * 清理块注释
 */
function cleanBlockComment(text) {
    const lines = [];
    for (const line of text.split('\n')) {
        let l = line.trim();
        if (l.startsWith('*')) {
            l = l.slice(1).trim();
        }
        if (l && !isMeaningless(l)) {
            lines.push(l);
        }
    }
    const result = lines.join('\n');
    if (result.length > 500) {
        return result.slice(0, 500) + '...';
    }
    return result || null;
}

/**
 * 判断注释是否无意义
 */
function isMeaningless(text) {
    if (!text || text.trim().length < 3) return true;
    if (/^[-=_\s*]+$/.test(text)) return true;
    if (/^TODO[:\s]*$/i.test(text)) return true;
    if (/^FIXME[:\s]*$/i.test(text)) return true;
    return false;
}

/**
 * 格式化输出
 */
function formatOutput(filePath, comments) {
    const lines = [
        `# File: ${path.basename(filePath)}`,
        '',
        '## Comments',
        '',
    ];
    
    for (let i = 0; i < comments.length; i++) {
        const comment = comments[i];
        if (comment.includes('\n')) {
            lines.push(`### Comment ${i + 1}`);
            lines.push('');
            lines.push(comment);
            lines.push('');
        } else {
            lines.push(`${i + 1}. ${comment}`);
        }
    }
    
    return lines.join('\n');
}

// 主函数
function main() {
    const args = process.argv.slice(2);
    if (args.length === 0) {
        console.error('Usage: ts_comments.js <file>');
        process.exit(1);
    }
    
    const filePath = args[0];
    
    try {
        const code = fs.readFileSync(filePath, 'utf-8');
        const comments = extractComments(code, filePath);
        
        if (comments.length === 0) {
            // 无注释，输出空
            process.exit(0);
        }
        
        console.log(formatOutput(filePath, comments));
    } catch (e) {
        console.error(`Error: ${e.message}`);
        process.exit(1);
    }
}

main();