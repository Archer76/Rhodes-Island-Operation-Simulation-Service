# maa 包的黄金夹具

这三份是**参照实现（Python）的原样产出**，不是手写的期望值。判据
`../maaexport_test.go` 拿它们逐字节／逐行比对 Go 侧的输出。

出处：`out/zz_maa_golden.py`（真跑一遍 `ak_tactic.maa_export`）产出，随后
**逐字节**复制进来（复制时做了 sha256 对照，相同才落盘）。

| 文件 | 由谁产出 | 对应判据 |
| --- | --- | --- |
| `maajob_golden.json` | `to_maa(plan, roster, difficulty=NORMAL, title=测试, details=详情)` | `TestGoldenWithRoster`（要库） |
| `maajob_golden_noroster.json` | `to_maa(plan, None, …)` —— 名册为 None 的退化路 | `TestGoldenNoRoster`（不要库） |
| `operator_texts.txt` | `used_operators` / `operators_report` / `operators_lines` / `operators_brief` / `difficulty_code` / `module_*` / `skill_usage` 的原样打印 | `TestTexts`、`TestDifficultyCodes`、`TestEmptyPlanTexts` |

三份里的 `plan` 是同一份：3 名干员、2 个模组、专三，关卡 `act54side_ex08`。
三个 `char_id`：`char_1050_chen3` / `char_1015_aglna2` / `char_1046_sbell2`。

## 两条要留意的

1. **行尾是 CRLF**。Python 的 `Path.write_text` 在 Windows 上走文本模式，把 `\n`
   翻成了 `\r\n` —— 那是**写盘产物**，不是它生成的那份 JSON 正文。判据读夹具时
   归一化成 LF 再比；这条文件级分歧单独由 `TestLineEndingDivergence` 见证
   （Python 写 CRLF、Go 写 LF）。
2. **`out/` 不是持久目录**（被外部清理过），所以夹具必须住在仓库里。
   要重新生成：`python out/zz_maa_golden.py`（需要本机能跑 Python 侧）。
   重生成后要重跑判据 —— 变了就说明**行为变了**，别急着覆盖夹具。
