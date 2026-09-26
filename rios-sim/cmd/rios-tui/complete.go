package main

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// completeDir 对应 Python 的 `ak_tactic/tui/data.py::complete_dir`。
//
// # 它做三件事（原注释的口径）
//
//   - **空输入** → 补成默认目录并带上分隔符，省得从头敲；
//   - **唯一匹配** → 直接补全；补的是目录就带分隔符，好接着往下打；
//   - **多个匹配** → 补到**最长公共前缀**，候选交回给界面显示，不替用户猜。
//
// # 两个坑照原样搬（它们不是"实现细节"，是行为规格）
//
//  1. **分隔符只许一种**：用户在打 `/` 就继续用 `/`，否则用系统的。
//     `/` 与 `\` 在 Windows 上都能用，但混起来（`X:/dir/sub\`）看着像出错了，
//     而补全的全部价值就是让人不用回头检查。
//  2. **公共前缀要大小写不敏感地取**：Windows 路径不区分大小写，
//     而"取公共前缀"的常规做法区分 —— `Alpha-1` 与 `alpha-2` 都命中了 `a`，
//     公共前缀却算成空串，**补完等于没补**（用户看到一点变化都没有）。
//
// # 全用字符串处理，不 resolve
//
// 用户可能正在敲一个还不存在的目录；而 `resolve` 会把不存在的部分原样留下、
// 还会把相对路径锚到 cwd，反而把正在编辑的文本改形。所以只 `ReadDir` 一层。
func completeDir(text, base string) (string, []string) {
	raw := strings.TrimSpace(text)
	sep := string(os.PathSeparator)
	if strings.Contains(raw, "/") && !strings.Contains(raw, "\\") {
		sep = "/"
	}
	if raw == "" {
		root := base
		if root == "" {
			root = defaultGuidesDir()
		}
		return root + sep, nil
	}

	var head, tail string
	if strings.HasSuffix(raw, "/") || strings.HasSuffix(raw, "\\") {
		head, tail = raw, ""
	} else {
		// ⚠ Python 那边要手工把被 `os.path.split` 吃掉的分隔符补回来；
		// Go 的 `filepath.Split` **保留**尾分隔符，所以正好等于它补完的结果 ——
		// 但这条"正好相等"是核对过的，不是想当然：见 selftest 里「补的是目录就带分隔符」。
		head, tail = filepath.Split(raw)
	}

	probe := expandUser(head)
	if probe == "" {
		probe = "."
	}
	st, err := os.Stat(probe)
	if err != nil || !st.IsDir() {
		return raw, nil // 目录不存在：原样退回，不猜
	}
	ents, err := os.ReadDir(probe)
	if err != nil {
		return raw, nil
	}
	names := make([]string, 0, len(ents))
	lowTail := strings.ToLower(tail)
	for _, e := range ents {
		n := e.Name()
		if !strings.HasPrefix(strings.ToLower(n), lowTail) {
			continue
		}
		if e.IsDir() {
			n += sep
		}
		names = append(names, n)
	}
	sort.Strings(names)
	if len(names) == 0 {
		return raw, nil
	}
	if len(names) == 1 {
		return head + names[0], nil
	}
	low := commonPrefixFold(names)
	//: 用**字符**切片而不是字节 —— 目录名可能是中文，按字节切会切断一个字符。
	r, lr := []rune(names[0]), []rune(low)
	if len(lr) > len(r) {
		lr = r
	}
	return head + string(r[:len(lr)]), names
}

// commonPrefixFold 取公共前缀，且**大小写不敏感**。
//
// 与 Python 那边同一个理由：`os.path.commonprefix` 区分大小写，直接用它会把
// `Alpha-3` 与 `alpha-1` 的前缀算成空串。
func commonPrefixFold(names []string) string {
	if len(names) == 0 {
		return ""
	}
	//: 逐**字符**（rune）比，不逐字节 —— 目录名可能是中文。
	prefix := []rune(strings.ToLower(names[0]))
	for _, n := range names[1:] {
		cur := []rune(strings.ToLower(n))
		i := 0
		for i < len(prefix) && i < len(cur) && prefix[i] == cur[i] {
			i++
		}
		prefix = prefix[:i]
		if len(prefix) == 0 {
			break
		}
	}
	return string(prefix)
}

// expandUser 只做 `~` 与 `~/`（对应 Python 的 `os.path.expanduser` 在本项目里的用法）。
func expandUser(p string) string {
	if p == "" || p[0] != '~' {
		return p
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return p
	}
	if p == "~" {
		return home
	}
	if strings.HasPrefix(p, "~/") || strings.HasPrefix(p, "~\\") {
		return filepath.Join(home, p[2:])
	}
	return p
}

// defaultGuidesDir 是「空输入时补到哪」。
//
// ⚠ 还没接线：Python 侧它是配置里的 `guides_dir`（可被 `D` 键改）。
// 这里按**安装布局**推：sqlite 在 `<根>/data/`，作业输出在 `<根>/Guides/`。
// 等 GuidesDir 屏接上配置读写之后，这一处要改成读配置。
func defaultGuidesDir() string {
	if dir := os.Getenv("RIOS_DB"); dir != "" {
		return filepath.Join(filepath.Dir(dir), "Guides")
	}
	return "Guides"
}
