// extract_go_comments.go - Go AST 注释提取器
//
// 使用 go/ast 和 go/parser 解析 Go 代码，准确提取注释
//
// 用法: cat file.go | go run extract_go_comments.go
// 或者: go run extract_go_comments.go < file.go

package main

import (
	"bufio"
	"fmt"
	"go/parser"
	"go/token"
	"os"
	"regexp"
	"strings"
)

func main() {
	// 从 stdin 读取代码（增大缓冲区以支持长行）
	const maxLineLength = 10 * 1024 * 1024 // 10MB
	var content strings.Builder
	scanner := bufio.NewScanner(os.Stdin)
	
	// 设置更大的缓冲区
	buf := make([]byte, 0, 64*1024)
	scanner.Buffer(buf, maxLineLength)
	
	for scanner.Scan() {
		content.WriteString(scanner.Text())
		content.WriteString("\n")
	}
	
	if err := scanner.Err(); err != nil {
		fmt.Fprintf(os.Stderr, "Error reading stdin: %v\n", err)
		os.Exit(1)
	}
	
	code := content.String()
	
	// 解析 Go 代码
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, "", code, parser.ParseComments)
	if err != nil {
		// 解析失败，使用正则回退
		comments := extractWithRegex(code)
		if len(comments) > 0 {
			fmt.Println(formatOutput(comments))
		}
		return
	}
	
	// 提取所有注释
	seen := make(map[string]bool)
	var comments []string
	
	// 文件级别的注释
	if file.Doc != nil {
		for _, comment := range file.Doc.List {
			text := cleanComment(comment.Text)
			if text != "" && !seen[text] {
				comments = append(comments, "[Package] "+text)
				seen[text] = true
			}
		}
	}
	
	// 提取所有注释组
	for _, commentGroup := range file.Comments {
		for _, comment := range commentGroup.List {
			text := cleanComment(comment.Text)
			if text != "" && !seen[text] {
				comments = append(comments, text)
				seen[text] = true
			}
		}
	}
	
	if len(comments) == 0 {
		return
	}
	
	fmt.Println(formatOutput(comments))
}

func cleanComment(text string) string {
	text = strings.TrimSpace(text)
	
	if strings.HasPrefix(text, "//") {
		text = strings.TrimPrefix(text, "//")
	} else if strings.HasPrefix(text, "/*") && strings.HasSuffix(text, "*/") {
		text = text[2 : len(text)-2]
	}
	
	text = strings.TrimSpace(text)
	
	lines := strings.Split(text, "\n")
	var cleanedLines []string
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "*") {
			line = strings.TrimPrefix(line, "*")
			line = strings.TrimSpace(line)
		}
		if line != "" && !isMeaningless(line) {
			cleanedLines = append(cleanedLines, line)
		}
	}
	
	if len(cleanedLines) == 0 {
		return ""
	}
	
	result := strings.Join(cleanedLines, "\n")
	if len(result) > 500 {
		result = result[:500] + "..."
	}
	
	return result
}

func isMeaningless(text string) bool {
	if len(text) < 3 {
		return true
	}
	
	matched, _ := regexp.MatchString(`^[-=_\s*]+$`, text)
	if matched {
		return true
	}
	
	matched, _ = regexp.MatchString(`^TODO[:\s]*$`, text)
	if matched {
		return true
	}
	matched, _ = regexp.MatchString(`^FIXME[:\s]*$`, text)
	if matched {
		return true
	}
	
	return false
}

func extractWithRegex(content string) []string {
	var comments []string
	seen := make(map[string]bool)
	
	reLine := regexp.MustCompile(`//[^\n]*`)
	lineMatches := reLine.FindAllString(content, -1)
	for _, m := range lineMatches {
		text := strings.TrimPrefix(m, "//")
		text = strings.TrimSpace(text)
		if text != "" && !isMeaningless(text) && !seen[text] {
			comments = append(comments, text)
			seen[text] = true
		}
	}
	
	reBlock := regexp.MustCompile(`/\*[\s\S]*?\*/`)
	blockMatches := reBlock.FindAllString(content, -1)
	for _, m := range blockMatches {
		text := m[2 : len(m)-2]
		text = cleanComment("/*" + text + "*/")
		if text != "" && !seen[text] {
			comments = append(comments, text)
			seen[text] = true
		}
	}
	
	return comments
}

func formatOutput(comments []string) string {
	var lines []string
	lines = append(lines, "# File: stdin")
	lines = append(lines, "")
	lines = append(lines, "## Comments")
	lines = append(lines, "")
	
	for i, comment := range comments {
		if strings.Contains(comment, "\n") {
			lines = append(lines, fmt.Sprintf("### Comment %d", i+1))
			lines = append(lines, "")
			lines = append(lines, comment)
			lines = append(lines, "")
		} else {
			lines = append(lines, fmt.Sprintf("%d. %s", i+1, comment))
		}
	}
	
	return strings.Join(lines, "\n")
}