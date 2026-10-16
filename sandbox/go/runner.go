// 可信验证进程：解析 AST 校验标准库依赖，然后执行固定的 Go 检查。
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"io"
	"os"
	"os/exec"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
)

type file struct {
	Name    string `json:"name"`
	Content string `json:"content"`
}
type bundle struct {
	Files []file `json:"files"`
}
type stage struct {
	Stage     string  `json:"stage"`
	ExitCode  int     `json:"exit_code"`
	Output    string  `json:"output"`
	Elapsed   float64 `json:"elapsed_ms"`
	Truncated bool    `json:"truncated"`
}
type report struct {
	Status  string  `json:"status"`
	Version string  `json:"go_version"`
	Stages  []stage `json:"stages"`
	Elapsed float64 `json:"elapsed_ms"`
}

// 同时读 stdout/stderr，保留上限以内内容并持续排空，防止大量输出卡住进程。
type bounded struct {
	mu   sync.Mutex
	data bytes.Buffer
	cut  bool
}

func (b *bounded) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	n := len(p)
	left := 16384 - b.data.Len()
	if left > 0 {
		keep := n
		if keep > left {
			keep = left
		}
		b.data.Write(p[:keep])
	}
	if n > left {
		b.cut = true
	}
	return n, nil
}
func run(name string, args ...string) stage {
	started := time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "/usr/local/go/bin/go", args...)
	cmd.Dir = "/work"
	// 父进程环境来自固定镜像，不继承 API 服务的任何凭据。
	cmd.Env = append(os.Environ(), "GOFLAGS=-p=1")
	out := &bounded{}
	cmd.Stdout = out
	cmd.Stderr = out
	err := cmd.Run()
	code := 0
	if err != nil {
		code = 1
		if e, ok := err.(*exec.ExitError); ok {
			code = e.ExitCode()
		}
	}
	if ctx.Err() != nil {
		code = 124
	}
	return stage{name, code, strings.ToValidUTF8(out.data.String(), "�"), float64(time.Since(started).Milliseconds()), out.cut}
}
func validate(b bundle) error {
	raw, err := os.ReadFile("/opt/stdlib.txt")
	if err != nil {
		return err
	}
	allowed := map[string]bool{}
	for _, p := range strings.Fields(string(raw)) {
		allowed[p] = true
	}
	for _, p := range []string{"unsafe", "syscall", "os/exec", "plugin"} {
		delete(allowed, p)
	}
	if len(b.Files) < 2 || len(b.Files) > 8 {
		return fmt.Errorf("必须提供 2–8 个 Go 文件")
	}
	names := map[string]bool{}
	total := 0
	tests := 0
	implementation := false
	safe := regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_]*\.go$`)
	for _, f := range b.Files {
		low := strings.ToLower(f.Name)
		if !safe.MatchString(f.Name) || names[low] {
			return fmt.Errorf("非法或重复文件名")
		}
		names[low] = true
		total += len(f.Content)
		if total > 65536 {
			return fmt.Errorf("源码总量超过 64 KiB")
		}
		tree, err := parser.ParseFile(token.NewFileSet(), f.Name, f.Content, parser.ParseComments)
		if err != nil {
			return err
		}
		if tree.Name.Name != "example" {
			return fmt.Errorf("所有文件必须属于 package example")
		}
		for _, group := range tree.Comments {
			for _, c := range group.List {
				if strings.Contains(c.Text, "go:") || strings.HasPrefix(c.Text, "//line ") {
					return fmt.Errorf("禁止编译指令")
				}
			}
		}
		for _, imp := range tree.Imports {
			p, err := strconv.Unquote(imp.Path.Value)
			if err != nil || !allowed[p] {
				return fmt.Errorf("不允许依赖 %s，只支持受限标准库", imp.Path.Value)
			}
		}
		isTest := strings.HasSuffix(f.Name, "_test.go")
		if !isTest {
			implementation = true
		}
		for _, decl := range tree.Decls {
			if fn, ok := decl.(*ast.FuncDecl); ok && fn.Recv == nil {
				if fn.Name.Name == "TestMain" {
					return fmt.Errorf("禁止 TestMain 绕过测试入口")
				}
				if isTest && strings.HasPrefix(fn.Name.Name, "Test") {
					tests++
				}
			}
		}
	}
	if !implementation || tests == 0 {
		return fmt.Errorf("必须提供实现和至少一个测试函数")
	}
	return nil
}
func testEvents(output string) bool {
	ran, passed, skipped, packagePass := 0, 0, 0, false
	for _, line := range strings.Split(output, "\n") {
		var e struct {
			Action string
			Test   string
		}
		if json.Unmarshal([]byte(line), &e) != nil {
			continue
		}
		if e.Test != "" {
			switch e.Action {
			case "run":
				ran++
			case "pass":
				passed++
			case "skip":
				skipped++
			}
		}
		if e.Test == "" && e.Action == "pass" {
			packagePass = true
		}
	}
	return ran > 0 && passed == ran && skipped == 0 && packagePass
}
func main() {
	started := time.Now()
	r := report{Status: "failed", Version: strings.TrimPrefix(runtime.Version(), "go"), Stages: []stage{}}
	defer func() { r.Elapsed = float64(time.Since(started).Milliseconds()); json.NewEncoder(os.Stdout).Encode(r) }()
	if runtime.Version() != "go1.26.2" {
		r.Status = "unavailable"
		r.Stages = append(r.Stages, stage{Stage: "sandbox", ExitCode: 1, Output: "Go 工具链版本不匹配"})
		return
	}
	decoder := json.NewDecoder(io.LimitReader(os.Stdin, 262145))
	decoder.DisallowUnknownFields()
	var b bundle
	err := decoder.Decode(&b)
	if err == nil {
		err = validate(b)
	}
	if err != nil {
		r.Stages = append(r.Stages, stage{Stage: "policy", ExitCode: 1, Output: err.Error()})
		return
	}
	for _, f := range b.Files {
		if err = os.WriteFile("/work/"+f.Name, []byte(f.Content), 0600); err != nil {
			r.Stages = append(r.Stages, stage{Stage: "sandbox", ExitCode: 1, Output: err.Error()})
			return
		}
	}
	if err = os.WriteFile("/work/go.mod", []byte("module airobot.example\n\ngo 1.26.2\n"), 0600); err != nil {
		r.Status = "unavailable"
		return
	}
	r.Stages = append(r.Stages, stage{Stage: "policy", ExitCode: 0, Output: "单包、源码及标准库依赖校验通过"})
	commands := [][]string{{"compile", "build", "."}, {"vet", "vet", "."}, {"test", "test", "-json", "-count=1", "-timeout=8s", "."}}
	for _, c := range commands {
		s := run(c[0], c[1:]...)
		if s.Stage == "test" && s.ExitCode == 0 && !testEvents(s.Output) {
			s.ExitCode = 1
			s.Output += "\n测试未完整执行、被跳过或日志超出验证上限"
		}
		r.Stages = append(r.Stages, s)
		if s.ExitCode != 0 {
			// exit 124 是阶段 35s 上限（沙箱/工具链级异常），保持终态 timeout；
			// go test 内部 8s 超时（输出含 "test timed out"，即模型代码死锁/死循环）
			// 属于可修复失败，保持默认 failed 交给修复循环处理。
			if s.ExitCode == 124 {
				r.Status = "timeout"
			}
			return
		}
	}
	r.Status = "passed"
}
