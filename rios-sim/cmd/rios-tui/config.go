package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// 配置：`~/.rios/tui.json`。路径与格式**照 Python 侧**（`ak_tactic/tui/data.py:34-90`）：
//
//	CONFIG_FILE = "tui.json"
//	config_path() = Path.home() / ".rios" / CONFIG_FILE
//	load_config()  -> 不存在／读不出／不是 dict 都当空
//	save_config(**kw) -> mkdir -p ＋ 合并（不是覆盖）＋ json.dumps(ensure_ascii=False, indent=1)
//
// ★ 为什么这一段**不走 Python 子进程**：`ak_tactic/tui/__init__.py` 里写明了
// 「包本身**不导入** textual，第三方依赖只在 `ak_tactic.cli` 的 tui 子命令里惰性导入」。
// 配置只是一只 JSON 文件，起子进程读它等于让启动多背一个解释器 —— 而启动路径
// 越短越好。登录／名册那两条**必须**走 Python（要登录态与 skland 模块），配置不必。
//
// ★ 两处**具名登记的分道扬镳**（都与 Python 不同，且都是有意为之）：
//
//  1. **键序**：Python 的 dict 保插入序，Go 这边 `encoding/json` 对 map **按键排序**。
//     只影响人打开文件时的观感，不影响任何读取方（`load_config` 只当字典用）。
//  2. **写失败不再静默**：Python 的 `save_config` 里是 `except OSError: pass` ——
//     写不进去**一句话都不说**。Go 这边**返回错误**，由界面**具名**报出来
//     （本仓口径：静默退化比失败更坏，它让人以为设置生效了）。
const configFileName = "tui.json"

// configPath 是配置文件的位置；`RIOS_TUI_CONFIG` 可覆盖（判据要用它指向临时文件，
// 免得测试去动玩家真正的配置 —— 与「解释器／仪器路径可指定」同一精神）。
func configPath() string {
	if v := os.Getenv("RIOS_TUI_CONFIG"); v != "" {
		return v
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(".rios", configFileName)
	}
	return filepath.Join(home, ".rios", configFileName)
}

// loadConfig 读配置。不存在／读不出／顶层不是对象，一律当空 —— 照 Python 的语义。
func loadConfig() map[string]any {
	raw, err := os.ReadFile(configPath())
	if err != nil {
		return map[string]any{}
	}
	var cfg map[string]any
	if err := json.Unmarshal(raw, &cfg); err != nil || cfg == nil {
		return map[string]any{}
	}
	return cfg
}

// saveConfig 合并写入（**不是覆盖**）并返回错误（Python 那边把错误吞了，我们报出来）。
func saveConfig(key, val string) error {
	p := configPath()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return fmt.Errorf("建配置目录失败：%w", err)
	}
	cfg := loadConfig()
	cfg[key] = val
	//: indent=1 空格 —— 与 Python 的 `json.dumps(..., indent=1)` 对齐（本机现有那份
	//: `{"login_prompt": ""}` 就是 1 空格缩进）。Go 不像 Python 那样有 ensure_ascii，
	//: 它本来就把中文按 UTF-8 原样写出（等价于 ensure_ascii=False）。
	out, err := json.MarshalIndent(cfg, "", " ")
	if err != nil {
		return fmt.Errorf("序列化配置失败：%w", err)
	}
	if err := os.WriteFile(p, append(out, '\n'), 0o644); err != nil {
		return fmt.Errorf("写 %s 失败：%w", p, err)
	}
	return nil
}

// defaultGuidesDir 是 MAA 作业的默认输出根目录：**本工具根目录下的 `Guides/`**。
//
// 与 Python 的 `default_guides_dir()` 同一个口径（那边是"本工具根目录下"，
// 注释写明刻意**不用** `~/Guides`：数据跟工具放一起，一份克隆就是自包含的）。
// 在 Go 这边"工具根目录"按安装布局推：sqlite 在 `<根>/data/`，作业输出在 `<根>/Guides/`。
func defaultGuidesDir() string {
	if dir := os.Getenv("RIOS_DB"); dir != "" {
		return filepath.Join(filepath.Dir(dir), "Guides")
	}
	if exe, err := os.Executable(); err == nil {
		return filepath.Join(filepath.Dir(exe), "Guides")
	}
	return "Guides"
}

// guidesDir 是**当前生效**的作业输出目录：配置里有就用它（支持 `~`），否则用默认。
func guidesDir() string {
	raw, _ := loadConfig()["guides_dir"].(string)
	if s := strings.TrimSpace(raw); s != "" {
		return expandUser(s)
	}
	return defaultGuidesDir()
}
