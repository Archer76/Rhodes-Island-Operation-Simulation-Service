#!/usr/bin/env python3
r"""chain 判据的**独立性实测**：一个变异红几条。

★★★ 第一条纪律（验收 P2 探针后加，PM 转派）：
    **「认不出」必须自己会红，不能靠「恰好没有第二条」。**

前一版把「红了几条」按**判词前缀**归类，只认表内 5 条 ⇒ 表外的判词红了会被**静默丢掉**：
验收的 P2 探针（同块内加一条表外判词）实测 **`go test` 真红 2 行，本脚本报「红 1 条 ✓」、rc=0**
——矩阵漂亮、退出码 0，但那是**通道**漏了，不是读数对。**红行被丢掉且不留痕。**
现在：**按行号认语句种类**（`t.Errorf`／`t.Fatalf`＝判词，`t.Logf`＝日志），
**判词行凡是前缀不在表内的 ⇒ 具名打印 + rc=1**；行号落在任何已知调用区间之外 ⇒ 同样判失败（fail closed）。

★ 「一个改动红几条」＝独立性的判据（PM 提成通则 `msg-mu903tfp-g0`）：
红一条 ⇒ 独立信息；红两条 ⇒ 至少一条多余；红三条以上 ⇒ 同一判据的多份副本。

★ 本脚本自带的检查（不只是纪律）：
  · G1 双向：P2 形态（表外判词 ＋ 表内一条同时红）⇒ 必须 rc≠0 **且具名**；P1 形态（已认判词改名）⇒ 同样 rc≠0 具名
  · G3 锚点两两不同（否则改锚点会留下另一处）
  · G4 四个变异仍各恰好红 1 条、0 条认不出（**不许放宽**）
  · G5 产品树只读（跑前后逐文件 SHA256 相同）
  · **G6 红行的取证范围 ≥ 运行范围**：`-run Chain` 跑的是**整个包**，而旧版把红行的文件名
    写死成 `chain_test.go` ⇒ 同包另一个 `_test.go`（如 `mech/zz_probe_test.go`）里的红**看不见**，
    矩阵照样全绿（验收造树实测：真实 `rc=1`、两文件皆红，旧版报 `rc=0` 全绿）。
    现在正则 `^\s+(\S+_test\.go):(\d+):` **按文件**取语句种类；**非 `chain_test.go` 的红一律
    判「未认出」⇒ 具名 + rc≠0**（fail closed）。
  · **P7 同行两个调用**：`t.Logf(…); t.Errorf(…)` 同行时，按「行内第一个调用」标种类会把同行的红
    吞掉（验收探针 P7 实测旧版 `rc=0`，真值 `rc=1`）⇒ 种类按**集合**取、**「判词」优先于「日志」**。
    ★ 修法与 G6 **不是同一处**：G6 放宽的是**文件名**，P7 丢的是**行的种类** ⇒ G6 关不掉它。
  · ★★★ **PM 裁定「问①」：一行能打出两种文本时，「优先」是选定一个 —— 这里要的是两个都留着。**
    判词优先的**反面**（验收的 faceA 差分）：同行 `Logf` 的**正文**也按判词算 ⇒ 正文里若含表内前缀，
    就被算进表内计数（实测：表内红 **2** 条 `[断言1, 断言5]`，**真值只 1 条**）⇒
    **「恰红 1 条」这条分辨率被打破**。修法：① **行给候选集合**；② **按消息前缀逐条归类**；
    ③ 归属不定的一律进 **⊘ 未定性**，**不参与表内计数、也不参与控制组判定**
    （否则控制组会变成恒真——验收 §14.1 记的那条）；④ 控制组改成**逐桶对期望**，
    其中 **`forbid`＝不许出现的表内 id** 正是 faceA 的分辨率判据（不许出现「断言1」）。
  · **跨度自校验**：任一调用的括号跨度不许**跨过函数边界**（跨过 ⇒ 配平失控 ⇒ 整段被染错种类），
    且配平在**抠掉字面量**后的代码上算（消息里的括号不该参与配平）。
  · 环境自检：stdout 编不出 `✓`(U+2713) / `⇒`(U+21D2) 时**大声失败**并说明这是环境不是判据红
    （无编码约束的 str 流 ⇒ 该检查不适用，见 `console_check`）

    ★ **否证记录（验收构造、实测不成立，但性质必须留痕）**：曾猜「`Logf` 消息含未配平的 ASCII 左括号
      ⇒ 跨度外溢 ⇒ 后续行被标成日志」。**实测：外溢确实发生，但那个 `t.Errorf(` 自己的调用点更晚出现、
      把它自己那行标回「判词」** —— 因为旧写法 `kinds[k] = kind` 是**后写覆盖前写**。
      ⇒ ★ 旧实现的**性质＝标记顺序相关、后者胜**；**P7b 正是这条性质的反面**（Logf 在前就吞掉红）。
      ⇒ ★ 本版**故意去掉这个顺序依赖**：种类按**集合**取、「判词」优先，并把配平改为在**抠掉字面量**
      后的代码上算（`_strip_literals`）＋ 跨度不许跨函数边界（`spans_stay_inside_funcs` 当场红）。
      **不许把「依赖顺序」当地基用** —— 顺序一旦被重排，P7b 那类会以另一种形状回来。

  · ★★★ **验收 §16 的收窄准入（裁定「问B」）：`⊘` 的准入是「结构上不可归属」，不是「这一行有多种种类」。**
    `⊘` 里原本混进了**同行的表外真红**（`faceA 隔离用：表外文案`、`P7 同行被吞的红：78.75`
    都是 `t.Errorf` 的真红，却都进了 ⊘，而**未认出恒为 0**）⇒ **桶换了，数还在**。
    修法：先把每处调用的**首参字面量前缀**抠出来（`%` 动词与换行之后是运行期算的，源码里没有 ⇒ 只能比前缀），
    再拿红行正文与**各调用自己的前缀**比：**恰好 1 个匹配** ⇒ 归属它（日志＝不算红；判词＝表内/未认出）；
    **≥2 个互相覆盖** ⇒ 才进 ⊘；**0 个匹配** ⇒ 未认出（fail closed，不当「不计入」）。
  · ★ **汇总必须按实际取证的栏生成**（验收 F2/F3）：「不适用」要在**明细、括注、汇总三处同口径**；
    没取证产品树的那一轮**不许**在汇总里写「产品树只读」；两棵树的身份**提在最前面无条件打印**
    （证据要在所有出口都能看见，不能只落在需要它的那条分支上）。
  · ★ **表内期望的适用性按内容判，不按路径**（验收 F1）：逐字节相同的拷贝树上不许报「不适用」
    （那是我上一版的**误报**）；判据＝`ASSERTIONS` 每条前缀在该树的判词文件里**存在且唯一**，
    并有一条硬条件：**内容逐字节相同却判「不适用」⇒ 当场判红**。
  · ★ **rc⇔桶 对账**（验收给的最便宜的第二来源）：每行都要求 `rc != 0 ⇔ 三类桶合计 ≥ 1`。
  · ★★★ **运行器对账（根因那笔的强版本）**：`go test -json` 给的是**运行器自己的判决**
    （哪些 Test 失败／哪个包失败／是否编译失败），与我从 `-v` 正文**推**出来的归属是**两个独立来源**。
    逐条对三条：①运行器说失败的每个 Test ⇒ 我必须能**在它的函数区间里**指得出 ≥1 条红行
      （指不出＝**取证范围 < 运行范围**）；②运行器说通过的每个 Test ⇒ 我不许把任何红行归进它；
    ③**编译失败**（go 的 `build-output` 事件，如 `syntax error` / `[build failed]`）⇒ 正文 0 条可认的红行
      ⇒ 桶合计 0 而 rc≠0 ⇒ **当场具名判红**（这一类 `RED_RE` 结构上看不见）。
    ⇒ 于是矩阵里「**失败 Test 恰 1 个**」成了「恰红 1 条」的**第二个来源**（旧版只与常量 1 比）。
    ★ 两个量**分列**：「包判决=fail」（包里有测试失败）与「编译失败=是/否」不是同义词。

用法：`python tools/chain_judge_independence.py`
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "rios-sim"
WORK = ROOT / "out" / "backend2-b1" / "indep" / "rios-sim"
#: ★★ F4（验收 §17）：**产品树的身份不许从脚本位置推**。
#:   脚本被冻到 `out/acceptance/pinned/` 后，`__file__` 推出的「产品树」＝ `out/acceptance/rios-sim` ——
#:   **根本不存在**；而旧版把「取不到」的哨兵直接与真 sha 比 ⇒ 印出「逐字节相同：**False**」（真值 True），
#:   而且那条硬条件（内容相同却判不适用 ⇒ 判红）**在这类运行里永远不可能触发** ⇒
#:   ★ 零信息量的绿、而且**判据在它被设计来服务的那个用法里（冻结副本）失效**。
#:   现在候选按顺序取、**每个具名**，最后还有一条**与路径无关**的 git 对象兜底；
#:   全取不到 ⇒ **大声失败**（不许压成「内容不同」）。
PRODUCT_ENV = "CHAIN_PRODUCT_ROOT"


def product_candidates() -> list[tuple[str, Path]]:
    """产品树的候选位置，按可信度排序，**每个带名字**（身份要能说出它是从哪来的）。"""
    cands: list[tuple[str, Path]] = []
    env = (os.environ.get(PRODUCT_ENV) or "").strip()
    if env:
        cands.append((f"环境变量 {PRODUCT_ENV}={env}", Path(env) / "rios-sim"))
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(ROOT), capture_output=True)
    if top.returncode == 0:
        t = (top.stdout or b"").decode("utf-8", "replace").strip()
        if t:
            cands.append((f"git rev-parse --show-toplevel（{t}）", Path(t) / "rios-sim"))
    cands.append((f"脚本位置（{ROOT}）", ROOT / "rios-sim"))
    return cands


def product_judge_sha() -> tuple[str, str, str, str]:
    """产品树里那个判词文件的身份。**三态**：`可读`（附来源名与 sha）／`不可得`（附试过哪些）。

    ★ 为什么最后要有一条 git 对象兜底：它**与路径无关** —— 脚本冻在哪、cwd 在哪都不影响；
      代价是它量的是 **HEAD 里那一版**、不是工作区里那一版 ⇒ 名字里**写清**，不许混用。
    """
    tried: list[str] = []
    for name, root in product_candidates():
        f = root / "mech" / JUDGE_FILE
        if f.exists():
            return "可读", name, hashlib.sha256(f.read_bytes()).hexdigest(), str(root)
        tried.append(f"{name} ⇒ {f} 不存在")
    blob = subprocess.run(["git", "show", f"HEAD:rios-sim/mech/{JUDGE_FILE}"],
                          cwd=str(ROOT), capture_output=True)
    if blob.returncode == 0 and (blob.stdout or b""):
        return ("可读", f"git 对象 HEAD:rios-sim/mech/{JUDGE_FILE}（**HEAD 那一版，不是工作区那一版**）",
                hashlib.sha256(blob.stdout).hexdigest(), "git 对象")
    tried.append("git show HEAD:rios-sim/mech/chain_test.go 也失败")
    return "不可得", "／".join(tried), "", ""
#: 判词表覆盖的**唯一**文件（＝本脚本的取证范围里唯一「认得」的文件）；
#: ★ 运行范围是**整个包**（`go test ./mech/ -run Chain`）⇒ 取证范围必须 ≥ 运行范围（G6）。
JUDGE_FILE = "chain_test.go"
TEST_REL = "mech/" + JUDGE_FILE

#: 断言的身份：表内 = (id, 判词前缀)。**表外不是「忽略」，是「具名 + rc=1」**。
ASSERTIONS: list[tuple[str, str]] = [
    ("断言1 实现过判据", "实现未过判据："),
    ("断言2 真实参数必须拒绝", "时必须返回 ErrJumpUndetermined"),
    ("断言3 合成反例被抓", "没抓住「"),
    ("断言5 读法判别器", "读法判别器红："),
    ("断言6 分岔点只有 n=3", "n=3 的 "),
]

#: 候选③ 的 n=2 写错（M2 与两个控制组共用一份原文）
M2_OLD = "\t\t} else {\n\t\t\tseq[k-1] = base * scale\n\t\t}"
M2_NEW = "\t\t} else {\n\t\t\tseq[k-1] = base * scale * 1.05\n\t\t}"

#: (名字, 相对 rios-sim 的路径, 旧串, 新串, 预期红哪条断言)
#: ★ G3：验收指出 M1 与 M4 的旧串**逐字相同**（各 1 处命中、不违反 expect 自校验，
#:   但改锚点时只改一处会留下另一处）⇒ 两条锚点各自写长带上上下文，另有「两两不同」自校验兜底。
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    ("M1 实现 n=2 写错（×1.05）", "mech/chain.go",
     "\tcase 1:\n\t\treturn 1.0, nil\n\tcase 2:\n\t\treturn scale, nil",
     "\tcase 1:\n\t\treturn 1.0, nil\n\tcase 2:\n\t\treturn scale * 1.05, nil",
     "断言1 实现过判据"),
    ("M2 候选③ 的 n=2 写错（×1.05）", TEST_REL, M2_OLD, M2_NEW,
     "断言5 读法判别器"),
    ("M3 候选③ 的 n=3 变成与②同值", TEST_REL,
     "\t\tif k == 1 {\n\t\t\tseq[k-1] = base\n\t\t} else {\n\t\t\tseq[k-1] = base * scale\n\t\t}",
     "\t\tif k == 1 {\n\t\t\tseq[k-1] = base\n\t\t} else if k == 3 {\n"
     "\t\t\tseq[k-1] = base * 0.5\n\t\t} else {\n\t\t\tseq[k-1] = base * scale\n\t\t}",
     "断言6 分岔点只有 n=3"),
    ("M4 实现对 scale 不敏感", "mech/chain.go",
     "\tcase 2:\n\t\treturn scale, nil\n\tdefault:\n\t\treturn 0, ErrJumpUndetermined",
     "\tcase 2:\n\t\treturn 1.0, nil\n\tdefault:\n\t\treturn 0, ErrJumpUndetermined",
     "断言1 实现过判据"),
]

#: G6 控制组要往包里加的同包测试文件：**基线下绿、M1 下红**（验收造树的形态）。
PROBE_FILE = "mech/zz_probe_test.go"
PROBE_SRC = '''package mech

import "testing"

// G6 控制组：**同包另一个 _test.go 里的红**。
// 旧版把红行的文件名写死成 chain_test.go ⇒ 这一行的红**看不见**，
// 而运行范围是整个包（`go test ./mech/ -run Chain`）⇒ 矩阵照样全绿。
// 本文件在基线下绿（0.75 == 0.75）、在 M1（实现 n=2 ×1.05）下红 ⇒ 正是可构造的那扇门。
func TestChainProbe_ExtraFile(t *testing.T) {
	got, err := chainJumpScale(2, 0.75)
	if err != nil {
		t.Fatalf("两跳调用不该失败：%v", err)
	}
	if want := 0.75; got != want {
		t.Errorf("P6 外文件的红：chainJumpScale(2, 0.75) = %v，应为 %v", got, want)
	}
}
'''

#: 控制组：**期望脚本红**（这几条就是「认不出必须自己会红」的判据本身）
#: ★ 每条控制组带**自己的期望**（PM 裁定「问①」后加）：不仅看 rc，还要看**三个桶各自的读数**——
#:   否则「⊘ 未定性」这类新桶会让控制组变成恒真（验收 §14.1 记的那条）。
#:   期望字段：`known`＝表内红必须**恰好**是这几条（None＝不约束）；`unknown_min`＝未认出至少几条；
#:   `undet_min`＝未定性至少几条；`forbid`＝**不许出现**的表内 id（专治「日志正文被算进表内计数」）。
P2_ANCHOR = "\t\tif len(bad) > 0 {"
CONTROLS: list[tuple[str, list[tuple[str, str, str]], dict]] = [
    ("P2 同块内加一条**表外**判词（验收探针）", [
        (TEST_REL, M2_OLD, M2_NEW),
        (TEST_REL, P2_ANCHOR,
         "\t\tt.Errorf(\"控制组 P2：表外判词（不在 ASSERTIONS 表内）\")\n" + P2_ANCHOR),
    ], {"known": ["断言5 读法判别器"], "unknown_min": 1}),
    ("P1 把已认的判词**改名**（覆盖内消失）", [
        (TEST_REL, M2_OLD, M2_NEW),
        (TEST_REL, "读法判别器红：", "不通过："),
    ], {"known": [], "unknown_min": 1}),
    #: ★ P7：**同行两个调用、Logf 在前**——按「行内第一个调用」标种类就会把同行的 Errorf 红吞掉
    #:   （验收探针 P7 的形态；我上一版正是这个洞，它实测 rc=0 而我方真值是 rc=1）。
    #:   ★★ 收窄准入后这条红**必须进「未认出」**（两条调用的字面前缀**不同** ⇒ 归属是确定的：
    #:      `Logf` 的正文按它自己的前缀归日志 ⇒ 不算红；那条表外 `Errorf` 归判词 ⇒ 未认出）。
    #:      它同时是「⊘ 不许把真红吃掉」的守卫（与 P8 同形，但 P7 是验收探针的原形）。
    ("P7 同行 Logf+Errorf（表外真红必须进「认不出」，不许进 ⊘）", [
        (TEST_REL, M2_OLD, M2_NEW),
        (TEST_REL, P2_ANCHOR,
         "\t\tif seqs[2][1] != chainBase*chainScale { t.Logf(\"P7 同行日志\"); "
         "t.Errorf(\"P7 同行被吞的红：%v\", seqs[2][1]) }\n" + P2_ANCHOR),
    ], {"known": ["断言5 读法判别器"], "unknown_min": 1, "undet_max": 0}),
    #: ★★★ faceA（验收的差分、PM 裁定「问①」的那一条）：**同行** `Logf` 的正文里塞一个**表内前缀**，
    #:   同行的 `Errorf` 故意用**表外**文案作隔离 ⇒ 真值「M2 下断言1 根本不红」。
    #:   旧版（判词优先 ⇒ 整行算判词）会把 `Logf` 正文算成断言1 ⇒ 表内红 2 条 ⇒ **「恰红 1 条」分辨率被打破**。
    #:   本控制组就是这条分辨率的判据：表内必须**只有**断言5、且**不许出现**断言1。
    #:   ★ 收窄准入后：`Logf` 正文按**它自己的字面前缀**归属 ⇒ 是日志、不算红；
    #:     同行 `Errorf` 的表外文案按**它自己的字面前缀**归属 ⇒ **未认出**（不是 ⊘）。
    ("faceA 同行 Logf 正文含**表内前缀**（不许被算成表内红）", [
        (TEST_REL, M2_OLD, M2_NEW),
        (TEST_REL, P2_ANCHOR,
         "\t\tif seqs[2][1] != chainBase*chainScale { t.Logf(\"实现未过判据：这是日志正文\"); "
         "t.Errorf(\"faceA 隔离用：表外文案\"); }\n" + P2_ANCHOR),
    ], {"known": ["断言5 读法判别器"], "forbid": ["断言1 实现过判据"], "unknown_min": 1, "undet_max": 0}),
    #: ★★★ P8（验收 §16 裁定「问B」给的**反向守卫**）：同行一条 `Logf` ＋ 一条**表外判词** ⇒
    #:   那条表外判词的红**必须进「未认出」**（具名 + rc≠0），**不许进 ⊘**。
    #:   ★ 为什么它是本笔的分辨率判据：旧准入（「该行候选种类 >1 就进 ⊘」）会把这条**真红**
    #:     丢进 ⊘ ⇒ **未认出恒为 0**，桶换了但数还在（验收实测到的两条反例正是这个形态）。
    ("P8 同行 Logf＋**表外判词** ⇒ 必须进「认不出」不许进 ⊘（反向守卫）", [
        (TEST_REL, M2_OLD, M2_NEW),
        (TEST_REL, P2_ANCHOR,
         "\t\tif seqs[2][1] != chainBase*chainScale { t.Logf(\"P8 同行日志正文\"); "
         "t.Errorf(\"P8 同行表外判词：%v\", seqs[2][1]) }\n" + P2_ANCHOR),
    ], {"known": ["断言5 读法判别器"], "unknown_min": 1, "undet_max": 0}),
    #: ★★ P9（收窄准入的**另一侧**）：同行两条调用**字面前缀相同** ⇒ 这条红**结构上不可归属**
    #:   ⇒ 必须进 ⊘。否则「⊘ 未定性」这个桶就成了死代码（只降不放，谁都不进）。
    #:   ★ 这条也顺带守住「⊘ 不是垃圾桶」的另一面：**只有前缀互相覆盖才进**，前缀不同就不许进。
    ("P9 同行两条**同一字面前缀** ⇒ 结构上不可归属 ⇒ 必须进 ⊘", [
        (TEST_REL, M2_OLD, M2_NEW),
        (TEST_REL, P2_ANCHOR,
         "\t\tif seqs[2][1] != chainBase*chainScale { t.Logf(\"P9 同一文案\"); "
         "t.Errorf(\"P9 同一文案\"); }\n" + P2_ANCHOR),
    ], {"known": ["断言5 读法判别器"], "unknown_min": 0, "undet_min": 1}),
    #: ★★★ P10（**根因那笔强版本的控制组**，形态由验收先构造、我在这里做成脚本内控制组）：
    #:   往 `mech/chain.go` 插一行语法错 ⇒ `go test` 必 rc≠0，而 `RED_RE`（要
    #:   `\s+\S+_test\.go:(\d+):`）**一条都匹配不到** ⇒ **桶合计 0 而 rc=1**。
    #:   ⇒ 这一类控制组断言的是**检查器本身**（`reconcile_must_fail`）：`rc⇔桶` 对账必须当场判红、
    #:     且 `go test -json` 的**包级失败**必须自己说出来（第二来源，不靠推断）。
    ("P10 包级失败（chain.go 插语法错）：正文 0 条红行而 rc≠0 ⇒ 对账必须当场判红", [
        ("mech/chain.go", "func chainJumpScale(n int, scale float64) (float64, error) {",
         "func brokenRevGuard( {\nfunc chainJumpScale(n int, scale float64) (float64, error) {"),
    ], {"reconcile_must_fail": True}),
    #: ★ G6：**同包另一个 _test.go 的红**（验收造树实测：真实 rc=1、两文件皆红，旧版报 rc=0 全绿）
    ("G6 同包另一个 _test.go 的红（新增 zz_probe_test.go ＋ M1）", [
        ("mech/chain.go",
         "\tcase 1:\n\t\treturn 1.0, nil\n\tcase 2:\n\t\treturn scale, nil",
         "\tcase 1:\n\t\treturn 1.0, nil\n\tcase 2:\n\t\treturn scale * 1.05, nil"),
        (PROBE_FILE, "", PROBE_SRC),
    ], {"known": ["断言1 实现过判据"], "unknown_min": 1}),
]

RED_RE = re.compile(r"^\s+(\S+_test\.go):(\d+):\s?(.*)$")
CALL_RE = re.compile(r"\bt\.(Errorf|Fatalf|Logf)\(")
#: ★★ F6：覆盖面那一节的**两套口径**（**不许相加**）：
#:   窄＝会自己发一条带 `file:line:` 消息、且被本脚本的行分类器认得的调用（`Errorf`／`Fatalf`）；
#:   宽＝再算上 `t.Fatal(`／`t.Error(`（它们也发消息——`t.Error` ＝ `t.Log` ＋ `t.Fail`——
#:   但**行分类器不认它们**，本笔只作口径对照，不改分类器：那是另一件事，要单独立笔）。
JUDGE_CALL_RE = re.compile(r"\bt\.(Errorf|Fatalf)\(")
WIDE_CALL_RE = re.compile(r"\bt\.(Errorf|Fatalf|Fatal|Error)\(")
FUNC_RE = re.compile(r"^func\s+(\w+)\(")
#: 验收 P4 的口径：`t.Errorf/Fatalf(` 后面紧跟**单行首参字面量**
MSG_RE = re.compile(r't\.(?:Errorf|Fatalf)\(\s*"((?:[^"\\]|\\.)*)"')
#: ★ 收窄准入用（验收裁定「问B」）：取**每个调用自己**的首参字面量（可以跨行、直到闭引号）。
#:   有了它，红行**归属哪一个调用**就不再靠「这一行有几种种类」，而是**按消息对各调用自己的字面前缀**判。
CALL_LIT_RE = re.compile(r't\.(Errorf|Fatalf|Logf)\(\s*(?:\n\s*)?`((?:[^`])*)`'
                         r'|t\.(Errorf|Fatalf|Logf)\(\s*(?:\n\s*)?"((?:[^"\\]|\\.)*)"')
WRAP_RE = re.compile(r"append\(bad,")
#: `fmt.Errorf`——注意：验收 P4 的正则 `t\.(?:Errorf|Fatalf)\(` 会**子串命中**它（`fm`＋`t.Errorf`），
#: 于是它把 helper 的 4 条返回文案也数成「判词调用处」。本脚本用 `\bt\.` ⇒ 不命中。
FMT_RE = re.compile(r"\bfmt\.Errorf\(")
#: 包内所有测试文件（**G6：运行范围是整个包，取证范围必须 ≥ 它**）
TEST_GLOB = "*_test.go"


def console_check() -> int:
    """环境自检：控制台编不出判据里的记号就**大声失败**，并说清它是环境不是判据红。

    ★ 现场（验收字符级更正）：GBK 控制台**先卡住的是 `✓`(U+2713)**，不是 `⇒`(U+21D2)
    —— 类别对（GBK 会让判据假红），字符别差一个。

    ★★ 本检查自己踩过一次假红（验收探针用 `contextlib.redirect_stdout(StringIO)`）：
    `StringIO` **没有** `encoding` 属性 ⇒ 取默认 "ascii" ⇒ 把「无编码约束的 str 流」判成 ascii，
    于是**每一次被重定向的调用都假红**、真读数一条都印不出来。
    修法：`encoding is None`（str 流）⇒ 这条检查**不适用，直接放行**；只有真有编码的文本流才验。
    """
    enc = getattr(sys.stdout, "encoding", None)
    if enc is None:
        return 0                      #: str 流（StringIO 之类）⇒ 编不出字符这件事不存在
    try:
        "✓ ⇒ 「」".encode(enc)
    except (UnicodeEncodeError, LookupError):
        print(f"[ENV] stdout 编码 = {enc}，编不出 U+2713(✓) / U+21D2(⇒) 这类记号。")
        print("[ENV] 这是**环境**不是判据红（同族 06c2d722：脚本红了≠判据红了）。")
        print("[ENV] 处置：设 PYTHONIOENCODING=utf-8 后重跑。")
        return 1
    return 0


def tree_hashes() -> dict[str, str]:
    """G5：产品树里**全部**文件的 SHA256（跑前跑后各取一次）。

    ★ 面5（PM 转派）：旧版只哈希 7 个文件（`go.mod` ＋ `mech/*.go`），而 `rios-sim` 下共 34 个
      ⇒ **哈希范围窄于结论范围**。现在写全树：范围 ≥ 结论，不必再逐个声明「其余为什么不可能被写」。
    """
    files = sorted(p for p in SRC.rglob("*") if p.is_file())
    return {str(p.relative_to(SRC)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def git_evidence() -> tuple[str, str]:
    """脚本**自己手里**的 git 证据（三态：干净／脏／**本树不在 git 索引里 ⇒ 不适用**）。

    ★ 为什么要它：上一轮我说「产品树未变」用的是**外部证据**（别人跑的 `git status`），
      脚本自己手里没有全路径证据 ⇒ 换成别人跑、或树是拷贝出来的，那句话就没人能复核。
    ★ 为什么要有第三态：验收的探针把 `SRC` 指到 `out/...` 的**拷贝树**（`out/` 被 gitignore）
      ⇒ 那里的 `git status` **必然**是空的 ⇒ 若把它读成「产品树干净」就是**假绿**。
      故先问「这棵树在不在 git 索引里」，不在就明说**不适用**，不许当成通过。
    """
    rel = str(SRC.relative_to(ROOT)) if SRC.is_relative_to(ROOT) else None
    if rel is None:
        return "不适用", f"SRC 不在本仓库内（{SRC}）⇒ git 证据对本树无意义"
    probe = subprocess.run(["git", "ls-files", "--", f"{rel}/mech/chain.go"],
                           cwd=str(ROOT), capture_output=True)
    if not (probe.stdout or b"").strip():
        return "不适用", f"{rel} 不在 git 索引里（拷贝树/被忽略）⇒ git 证据对本树无意义"
    st = subprocess.run(["git", "status", "--short", "--", rel], cwd=str(ROOT), capture_output=True)
    dirty = (st.stdout or b"").decode("utf-8", "replace").strip()
    if dirty:
        return "脏", dirty
    return "干净", f"git status --short -- {rel} 空"


def stage() -> None:
    """把包搭到工作目录（mech 包自含，故只需 go.mod ＋ mech/*.go）。**产品树只读。**"""
    if WORK.exists():
        shutil.rmtree(WORK)
    (WORK / "mech").mkdir(parents=True)
    shutil.copy2(SRC / "go.mod", WORK / "go.mod")
    for p in (SRC / "mech").glob("*.go"):
        shutil.copy2(p, WORK / "mech" / p.name)


def discover_tests() -> dict[str, list[str]]:
    """**从树上现算**测试名单：`文件 → [^func Test 名字]`（运行范围不许是写死的常量）。

    ★★ F5（验收 §18）：旧版命令行写死 `-run Chain` ⇒ **运行范围**是一个**未声明的窄范围**，
      而归类器扫的是**全部** `*_test.go` ⇒ **两个来源范围不同**；更要紧的是
      **运行范围 < 树上真实存在的测试集** —— 这是「取证范围 ≥ 运行范围」的**镜像**：
      上五次是**取证**窄于运行，这一次是**运行本身就窄**，**两边都看不见**。
      实测（本次）：树上 `^func Test` **3 个**（`chain_test.go` 2 ＋ `farmland_golden_test.go` 的
      `TestFarmlandGolden`），`-run Chain` 只跑 **2 个** ⇒ 第三个**没有任何一组读数提到它**、rc=0。
    """
    out: dict[str, list[str]] = {}
    for p in sorted((WORK / "mech").glob(TEST_GLOB)):
        names = re.findall(r"^func (Test\w+)\(", p.read_text(encoding="utf-8", errors="replace"), re.M)
        out[p.name] = sorted(set(names))
    return out


def go_test() -> tuple[int, str, dict]:
    """跑 `go test -json`，**一次运行两个来源**：给人看的正文 ＋ 给机器看的判决集合。

    ★★★ 根因那笔的**强版本**（PM 转派）：旧版只用正文里 `file:line:` 形态的红行，
      于是「红行总数」**没有第二个来源**、只与常量 1 比（`f6068d3c`）。
      `go test -json` 给的是**运行器的判决**（哪些 Test 失败／哪个包失败），
      与我从正文**推**出来的归属是**两个独立来源** ⇒ 可以逐条对账。
    ★ 为什么不用两次运行（一次文本一次 json）：**同一个量在同一份产物里只能有一个来源**（`45fab0e7`）——
      两次运行是两个时刻，读数可能不同；这里正文直接从 json 的 `Output` 还原。
    ★★ F5：命令行**不再写 `-run`**（运行整包）—— 运行范围＝树上真实测试集，
      并在 `reconcile_scope` 里逐名对账（**运行范围不许是一个没人为它发声的常量**）。
    """
    p = subprocess.run(["go", "test", "./mech/", "-count=1", "-v", "-json"],
                       cwd=str(WORK), capture_output=True)
    raw = (p.stdout or b"").decode("utf-8", "replace")
    events: list[dict] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if s.startswith("{"):
            try:
                events.append(json.loads(s))
            except json.JSONDecodeError:
                pass
    text = "".join(str(e.get("Output", "")) for e in events)
    if not text:                      #: -json 没解析出东西（老版本 go / 格式变了）⇒ 退回原文，绝不静默
        text = raw + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, text, verdict_from_events(events, raw)


def verdict_from_events(events: list[dict], raw: str) -> dict:
    """从 `go test -json` 的事件流里取**运行器的判决**（第二个来源）。

    ★★ 这里有两个**不同义**的量，必须分列（我第一版把它们都叫「包级失败」⇒ 标签与读数不同义）：
      · `pkg_fail`：**包的判决**是 fail —— 只要包里有任何测试失败，它就是 True（**不代表编译失败**）；
      · `build_failed`：**编译失败** —— 判据是 go 自己发的 `Action="build-output"` 事件
        （实测原文：`mech\\chain.go:103:22: syntax error: unexpected {, expected )` 与
        `FAIL\trios-sim/mech [build failed]`）。★ 这一类**不含** `\\s+\\S+_test\\.go:(\\d+):`
        ⇒ `RED_RE` 一条都匹配不到 ⇒ **桶合计 0 而 rc≠0**（旧版会静默；现在由运行器自己说出来）。
    """
    tests_fail: set[str] = set()
    tests_pass: set[str] = set()
    tests_skip: set[str] = set()
    pkg_fail = False
    build_lines: list[str] = []
    for e in events:
        act, t = e.get("Action"), e.get("Test")
        if act == "build-output":
            s = str(e.get("Output", "")).strip()
            if s:
                build_lines.append(s)
            continue
        if act == "fail":
            if t:
                tests_fail.add(str(t))
            else:
                pkg_fail = True
        elif act == "pass" and t:
            tests_pass.add(str(t))
        elif act == "skip" and t:
            #: ★ 跳过也是**判决的一种**（它出现在运行器判决里）⇒ 范围对账必须把它算进「被提到过」
            tests_skip.add(str(t))
    hints = build_lines[:4]
    if not hints:                     #: 兜底：老版本 go 不发 build-output 时才去扫原文（绝不静默）
        for ln in raw.splitlines():
            s = ln.strip()
            if "[build failed]" in s.lower() or "syntax error" in s.lower():
                hints.append(s[:200])
    return {"pkg_fail": pkg_fail, "tests_fail": sorted(tests_fail), "tests_pass": sorted(tests_pass),
            "tests_skip": sorted(tests_skip),
            "build_failed": bool(build_lines), "build_lines": build_lines[:4], "hints": hints}


def reconcile_scope(discovered: dict[str, list[str]], verdict: dict) -> tuple[bool, list[str], str]:
    """★★★ F5：**运行范围对账** —— 树上现算的测试集 ⇔ 运行器判决里出现过的测试集。

    ★ 为什么必须有它：`-run` 是个**常量**时，没人替运行范围发声 ⇒
      树上有一个失败的测试而**没有一组读数提到它**、rc=0（验收实测到的静默）。
      这条把「运行范围」从**一个写死的常量**变成**一个被对账过的导出量**：
      **少一个就具名报出缺了谁**，多一个也报（那说明我从树上没扫到它 ⇒ 扫描器漏了）。
    """
    bad: list[str] = []
    disc = {n for v in discovered.values() for n in v}
    seen = set(verdict["tests_fail"]) | set(verdict["tests_pass"]) | set(verdict.get("tests_skip") or [])
    missing = sorted(disc - seen)
    extra = sorted(seen - disc)
    if missing:
        bad.append(f"**运行范围 < 树上真实测试集**：树上有 {len(disc)} 个测试，运行器判决里没有 "
                   f"{len(missing)} 个 ⇒ 缺 {missing}（它们**没有被跑**，任何一组读数都不会提到它们）")
    if extra:
        bad.append(f"运行器报出的测试不在树上现算的名单里：{extra} ⇒ 扫描器漏了（或 -run 语义与名字不符）")
    note = (f"运行范围＝**整包**（命令行不写 `-run`）：树上现算 **{len(disc)}** 个测试 "
            f"（{'、'.join(sorted(discovered))}）／运行器判决提到 **{len(seen)}** 个"
            f"（失败 {len(verdict['tests_fail'])}＋通过 {len(verdict['tests_pass'])}"
            f"＋跳过 {len(verdict.get('tests_skip') or [])}）")
    return (not bad), bad, note


def _line2test(per: dict, fname: str, line: int) -> str:
    """红行**落在哪个测试函数里** —— 依据是现扫出来的函数首行表（`enclosing`），不是猜。"""
    got = per.get(fname)
    if not got:
        return "（文件未扫）"
    return enclosing(got[2], line)


def _tests_of(per: dict) -> dict[str, str]:
    """测试函数名 → 它住在哪个文件（运行器只给名字，文件要我自己认）。"""
    out: dict[str, str] = {}
    for fname, (_k, _s, funcs, _sp) in per.items():
        for fn in set(funcs.values()):
            if fn.startswith("Test"):
                out[fn] = fname
    return out


def reconcile_runner(verdict: dict, reds: list[tuple[str, int, str, str, str]],
                     per: dict) -> tuple[bool, list[str]]:
    """★★★ **根因那笔的强版本**：把**运行器的判决**与**我从正文推的归属**逐条对账。

    为什么这才是正身：红行总数此前**没有第二个来源**，只与常量 1 比（`f6068d3c`）。
    `go test -json` 给的是**运行器自己的判决**（哪些 Test 失败／哪个包失败），与我从 `-v` 正文
    **推**出来的归属是**两个独立来源**。对账三条：

    1. **运行器说失败的每个 Test** ⇒ 我必须在**它的函数区间里**指得出 ≥1 条红行
       （指不出 ⇒ **取证范围 < 运行范围**，`60dc63ca`：那正是「矩阵全绿而真实 rc=1」的形状）；
    2. **运行器说通过的每个 Test** ⇒ 我**不许**把任何红行归到它里面
       （归进去 ⇒ 归属错了；这条防的是「把别人的红算到这个函数头上」的反向错）；
    3. **包级失败**（`Action=fail` 且无 `Test`，如 `[build failed]`）⇒ 正文里 0 条可认的红行
       ⇒ 「桶合计 0 而 rc≠0」⇒ **当场具名判红**（这就是验收反向守卫构造的那个静默实例，
       现在由 `go test -json` 这一侧**自己说出来**，不再靠推断）。
    """
    bad: list[str] = []
    name2file = _tests_of(per)
    #: 每条红行落在哪个测试函数里
    red_in: dict[str, int] = {}
    for fname, line, _kind, _bucket, _text in reds:
        red_in[_line2test(per, fname, line)] = red_in.get(_line2test(per, fname, line), 0) + 1
    for t in verdict["tests_fail"]:
        f = name2file.get(t)
        if f is None:
            bad.append(f"运行器说 **{t} 失败**，但我在扫过的 `*_test.go` 里找不到这个测试函数"
                       f"（⇒ 取证范围 < 运行范围）")
            continue
        if red_in.get(t, 0) < 1:
            bad.append(f"运行器说 **{t} 失败**（在 {f}），但我把 0 条红行归进它 ⇒ "
                       f"取证范围 < 运行范围（`{t}` 的红藏在别处）")
    for t in verdict["tests_pass"]:
        if red_in.get(t, 0) > 0:
            bad.append(f"运行器说 **{t} 通过**，但我把 {red_in[t]} 条红行归进了它 ⇒ 归属错了")
    if verdict["build_failed"] or (verdict["pkg_fail"] and not verdict["tests_fail"]):
        bad.append("**编译失败**（go 自己的 `build-output` 事件；无失败的 Test）⇒ 正文里 0 条可认的红行"
                   f" ⇒ 桶合计 0 而 rc≠0（这正是 `RED_RE` 看不见的那一类；go 的原文："
                   f"{verdict['build_lines'] or verdict['hints'] or '（无原文）'}）")
    return (not bad), bad


def _strip_literals(ln: str) -> str:
    """把字符串/字符字面量与行注释抠掉——**括号配平只能在剩下的代码上算**。

    ★ 为什么必须抠：若判词消息里出现一个**未配平的 ASCII 左括号**，整行的配平就永远回不到 0，
      「调用跨度」会一直吞到文件尾 ⇒ 它后面的行全被染成同一种类 ⇒ **日志能吞掉判词**
      （与 P7 同一族：红被丢弃）。验收的探针自己踩过这个形态（它源码注释里写了）。
    """
    out: list[str] = []
    i, n = 0, len(ln)
    while i < n:
        c = ln[i]
        if c in "\"'`":
            quote = c
            i += 1
            while i < n:
                if ln[i] == "\\" and quote != "`":
                    i += 2
                    continue
                if ln[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and ln[i + 1] == "/":
            break
        out.append(c)
        i += 1
    return "".join(out)


def _lit_prefix(raw: str) -> str:
    """把一条消息的字面量首参折成**可比较的前缀**：解转义 → 在前导换行/`%` 动词处截断。

    ★ 为什么要截断：`go test` 的一行只装得下**第一条输出行**（后续行不带 `file:line:`），
      而 `t.Errorf("读法判别器红：\\n  %s", …)` 的第一行正文恰好是「读法判别器红：」
      ⇒ 前缀必须截在 `\\n` 与 `%` 之前，否则一个表内判词会被判成「匹配不上」（假红）。
    ★ 为什么用**字面量前缀**而不是「整条消息」：`%v/%s` 后面的部分是运行时算出来的，
      源码里没有 ⇒ 只能比前缀（验收裁定「问B」给的正是这条）。
    """
    s = raw.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")
    cut = len(s)
    for i, ch in enumerate(s):
        if ch == "%" or ch == "\n":
            cut = i
            break
    return s[:cut].strip()


def _scan_one(path: Path) -> tuple[dict[int, set[str]], dict[int, set[str]], dict[int, str],
                                  list[tuple[int, int, set[str], list[tuple[str, str]]]]]:
    """扫一个测试文件：给行号标**候选种类集合**＋给每行留**每个调用自己的字面前缀**。

    ★ 为什么按行号而不是按消息形状：`-v` 输出里 `t.Logf` 与 `t.Errorf` 长得**一模一样**
    （都是 `    <file>_test.go:NN: 正文`），按形状分不出「日志」与「判词」；但**行号**能
    ——它指向发出该消息的语句。
    ★★ **一行可以打出多种文本**（P7b：`t.Logf(…); t.Errorf(…)` 同行）⇒ 一行只存**一种**种类
      表达不了这件事。上一版把「日志」的否决权拿掉（判词优先）**方向对，但做法错**：
      「优先」是**选定一个**，而这里需要的是**两个都留着** —— 判词优先会让同行的 `Logf` 正文
      也按判词算 ⇒ 正文里若含表内前缀就被算进表内计数（faceA：表内红 2 条 vs 真值只 1 条，
      **「恰红 1 条」这条分辨率被打破**）。
    ★★★ 收窄准入（验收 §16 裁定「问B」）：**一行有多种种类 ≠ 这条消息归属不定**。
      `⊘` 的准入必须是「**结构上不可归属**」——先把每处调用的**首参字面量前缀**抠出来，
      再拿红行的正文去比；**只有两条调用的前缀互相覆盖（都匹配得上）时才进 ⊘**。
      旧准入（「该行候选种类 >1 就进 ⊘」）会把**同行的表外真红**（`faceA 隔离用：表外文案`、
      `P7 同行被吞的红：78.75`）也丢进 ⊘ ⇒ **未认出恒为 0**，桶换了但数还在（验收实测到的反例）。
    ★ 已知区间**不是手写的表**：它是每次运行前从**被测文件现扫**出来的（扫描器与判词表是两个来源）。
    ★ 括号配平在**抠掉字面量**后的代码上算（见 `_strip_literals`）。

    返回 (全部行号→候选集合, 调用首行→候选集合, 函数首行→函数名, 每处调用的跨度＋各调用的前缀)。
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    kinds: dict[int, set[str]] = {}
    starts: dict[int, set[str]] = {}
    funcs: dict[int, str] = {}
    spans: list[tuple[int, int, set[str], list[tuple[str, str]]]] = []
    #: 每个调用在**原始文本**里的字符偏移 → 行号与 (种类, 前缀)：偏移是给「消息属于哪个调用」用的。
    calls_at: dict[int, list[tuple[str, str]]] = {}
    for cm in CALL_LIT_RE.finditer(text):
        kind = "判词" if (cm.group(1) or cm.group(3)) in ("Errorf", "Fatalf") else "日志"
        raw = cm.group(2) if cm.group(2) is not None else cm.group(4)
        line_no = text.count("\n", 0, cm.start()) + 1
        calls_at.setdefault(line_no, []).append((kind, _lit_prefix(raw or "")))
    for i, ln in enumerate(lines, 1):
        fm = FUNC_RE.match(ln)
        if fm:
            funcs[i] = fm.group(1)
        found = list(CALL_RE.finditer(ln))
        if not found:
            continue
        here = {"日志" if m.group(1) == "Logf" else "判词" for m in found}
        starts[i] = set(here)
        code = _strip_literals(ln)
        depth = code.count("(") - code.count(")")
        j = i
        while depth > 0 and j < len(lines):
            j += 1
            nxt = _strip_literals(lines[j - 1])
            depth += nxt.count("(") - nxt.count(")")
        #: 该跨度覆盖的每个调用（含跨行调用）带上它自己的字面前缀 —— 归属就靠它，不靠行号。
        calls = [c for k in range(i, j + 1) for c in calls_at.get(k, [])]
        spans.append((i, j, set(here), calls))
        for k in range(i, j + 1):
            kinds.setdefault(k, set()).update(here)
    return kinds, starts, funcs, spans


def scan_package() -> dict[str, tuple[dict[int, set[str]], dict[int, set[str]], dict[int, str],
                                      list[tuple[int, int, set[str], list[tuple[str, str]]]]]]:
    """扫**包内全部** `*_test.go`（G6：运行范围是整个包 ⇒ 不能只扫一个文件）。"""
    return {p.name: _scan_one(p) for p in sorted((WORK / "mech").glob(TEST_GLOB))}


def spans_stay_inside_funcs(per: dict) -> list[str]:
    """结构自校验：**任一调用的跨度不许跨过函数边界**（跨过 ⇒ 括号配平失控 ⇒ 整段被染错种类）。

    ★ 这条是 `_strip_literals` 的兜底：即便将来某种形态又让配平跑偏，也要**当场大声失败**，
      而不是让日志悄悄吞掉判词（那正是 P2/P7 家族的静默）。
    """
    bad: list[str] = []
    for fname, (_k, _s, funcs, spans) in per.items():
        fstarts = sorted(funcs)
        for a, b, _kind, _calls in spans:
            for f in fstarts:
                if a < f <= b:
                    bad.append(f"{fname}:{a}-{b} 的调用跨度跨过了 {funcs[f]}（第 {f} 行）"
                               f"⇒ 括号配平失控，种类标注不可信")
                    break
    return bad


def enclosing(funcs: dict[int, str], n: int) -> str:
    cand = [k for k in funcs if k <= n]
    return funcs[max(cand)] if cand else "（函数外）"


def coverage_counts(per: dict) -> tuple[dict[str, dict[str, int]], int, int]:
    """逐文件现算调用处数（★ F6：**分行行上的数必须是该文件自己的数**）＋ 一个**独立的整包来源**。

    ★★ F6（验收 §十九／PM 派单）：覆盖面这一节是**读者用来判断取证范围**的地方，
      而它有**两个口径混印在同一块里**：分行行是「整包按文件」，汇总行却只数判词表那一个文件
      ⇒ 产品树上印出「两行各 13、合计也 13」，读者一读就以为其中一行是别人的数（实测 SUM=26 vs 13）。
      ⇒ 修法：①分行**逐文件现算**②`Σ(分行) == 整包独立来源`，**不等判红**③两套口径**分列并写明不许相加**。
    ★ 两套口径（**不许相加**）：
      · **窄**＝`t.Errorf(` / `t.Fatalf(` —— 会**自己发一条带 `file:line:` 的消息**，是本脚本归类的对象；
      · **宽**＝再算上 `t.Fatal(` / `t.Error(` —— 它们也发消息（`t.Error` ＝ `t.Log` ＋ `t.Fail`），
        但本脚本的行分类器不认它们（`CALL_RE` 只管 `Errorf|Fatalf|Logf`）⇒ **只作口径对照，不进分类**。
    ★ 「两行同数」**不是**「同一行重印」：实测两个文件在**窄**口径下**真的各 13 条**；
      要区分这两种情形，只能**改一个文件看另一行动不动**（见守卫 ⑩ 的反向夹具）。
    """
    rows: dict[str, dict[str, int]] = {}
    pkg_narrow = pkg_wide = 0
    for fname, (_k, st, _f, _sp) in per.items():
        text = (WORK / "mech" / fname).read_text(encoding="utf-8")
        lines = text.splitlines()
        rows[fname] = {
            "narrow": sum(1 for _n, ks in st.items() if "判词" in ks),
            "wide": sum(1 for ln in lines if WIDE_CALL_RE.search(ln)),
            "mixed": sum(1 for _n, ks in st.items() if len(ks) > 1),
        }
        pkg_narrow += sum(1 for ln in lines if JUDGE_CALL_RE.search(ln))
        pkg_wide += rows[fname]["wide"]
    return rows, pkg_narrow, pkg_wide


def coverage(per: dict) -> list[str]:
    """G2 ＋ G6：把「不覆盖」的东西**显式印出来并说清为什么可以不覆盖**（理由由结构给出）。

    G6 加的一层：**运行范围是整个包**，故先把包内每个 `*_test.go` 列出来，标出哪个是判词表覆盖的，
    其余文件里**即便有判词也是未覆盖** ⇒ 它们一旦红了就是「未认出」⇒ 具名 + rc=1。
    ★★ F6：每一行的数**逐文件现算**，且与**整包独立来源**（另一次行级扫描）对账，不等 ⇒ 判红。
    """
    print(f"== 归类器覆盖面·**分行**（逐文件现算，包内 {TEST_GLOB}；判词表只覆盖 {JUDGE_FILE}）==")
    rows, pkg_narrow, pkg_wide = coverage_counts(per)
    bad: list[str] = []
    #: ★ 行形状是**接口**：验收的 `tools/acceptance_coverage_count_probe.py` 按
    #:   `· <文件>：判词调用处 N 条` 与 `判词**调用处**共 M 条` 两条正则读本节
    #:   ⇒ **口径声明只能加在括号里，不许动这两个锚**（数字不加粗、顺序不变）。
    for fname, c in rows.items():
        tag = "判词表覆盖" if fname == JUDGE_FILE else "**未覆盖**（红了 ⇒ 认不出 ⇒ rc=1）"
        print(f"   · {fname}：判词调用处 {c['narrow']} 条"
              f"（窄口径 `t.Errorf(`／`t.Fatalf(`；宽口径＋`t.Fatal(`／`t.Error(` ＝ {c['wide']} 条）"
              f"、**同行多调用 {c['mixed']} 行** —— {tag}")
    sum_rows = sum(c["narrow"] for c in rows.values())
    if sum_rows != pkg_narrow:
        bad.append(f"Σ(分行)＝{sum_rows} ≠ 整包独立来源＝{pkg_narrow} ⇒ 分行行上至少有一个数**不是该文件自己的**"
                   f"（或有文件漏扫）⇒ 这一节会误导读者判断取证范围")

    #: ★★ PM 的印法条件（2026-09-20）：**对账与口径声明必须分开印** ——
    #:   不能让读者在同一块里看到 `26` 与 `13` 而以为它们是一套（那正是验收撤回那条的起因）。
    #:   ⇒ 四个**分节**：分行 / 合计（口径＝整包）/ 同口径对账 / 判词表文件内部（口径＝单文件）。
    print(f"== 归类器覆盖面·**合计**（口径＝包内全部 {TEST_GLOB}，与上面的分行数**分属两条数**、不可混读）==")
    print(f"   整包合计：判词**调用处**共 {pkg_narrow} 条（口径＝**包内全部 {TEST_GLOB}** 共 {len(rows)} 个文件、"
          f"含未覆盖的那个；谓词＝窄口径）")
    print(f"   整包两套分母（**不许相加**）：窄 {pkg_narrow} 条、宽 {pkg_wide} 条"
          f"（宽−窄＝{pkg_wide - pkg_narrow} 条是 `t.Error(`／`t.Fatal(`，本脚本的行分类器不认它们）")
    print("== 归类器覆盖面·**同口径对账**（这一层只证「分行没漏对象」；「谓词数得对」它证不了）==")
    print(f"   Σ 分行（窄，{sum_rows}）⇔ 整包独立来源（窄，**另一次行级扫描**，{pkg_narrow}）"
          f"⇒ 对账 {'✓' if sum_rows == pkg_narrow else '✗ 判红'}")
    print("   ★ 这一层证明了什么：**同一谓词两次遍历**（按文件一次、全量行扫一次）一致 ⇒ "
          "**分行没漏文件、没漏行**。★ 它**证不了「谓词本身选错」**——谓词对不对只能靠**跨尺子对照**"
          "（验收用窄／宽两把独立尺子逐位比过我印的两个数）；两层合起来才等于「这一节的数可信」。")

    jf = per.get(JUDGE_FILE)
    if jf is None:
        print(f"   ✗ 判词表覆盖的文件 {JUDGE_FILE} 不在包里 ⇒ 判词表已失效")
        return bad + [f"判词表覆盖的文件 {JUDGE_FILE} 不在包里"]
    lines = (WORK / "mech" / JUDGE_FILE).read_text(encoding="utf-8").splitlines()
    _kinds, starts, funcs, _spans = jf
    judge_starts = [(n, k) for n, k in sorted(starts.items()) if "判词" in k]
    inside = [(n, lines[n - 1].strip()) for n, _k in judge_starts
              if any(p in lines[n - 1] for _i, p in ASSERTIONS)]
    outside = [(n, lines[n - 1].strip()) for n, _k in judge_starts
               if not any(p in lines[n - 1] for _i, p in ASSERTIONS)]
    wrapped = [(i, lines[i - 1].strip()) for i, ln in enumerate(lines, 1) if WRAP_RE.search(ln)]
    msg_lits = MSG_RE.findall("\n".join(lines))
    n_fmt = sum(1 for ln in lines if FMT_RE.search(ln))

    #: ★ F6：这一行**单起一节**，口径写在行里（`判词表覆盖的文件内`），
    #:   不再让读者把它当成上面的整包合计（PM 的印法条件：三条数不许挤在一块）。
    print(f"== 归类器覆盖面·**判词表覆盖的文件内部**（口径＝仅 {JUDGE_FILE} 这一个文件；"
          f"**与上面的整包合计 {pkg_narrow} 分属两条数，不许相加或相减**）==")
    print(f"   判词表覆盖的文件内：判词调用处 {len(judge_starts)} 条（谓词＝窄口径）—— "
          f"表内能认 {len(inside)} 条、**表外 {len(outside)} 条**")
    mixed = sorted(n for n, ks in starts.items() if len(ks) > 1)
    print(f"   ★ 同行多调用（候选种类 >1 ⇒ 消息归属不定 ⇒ 进 ⊘ 未定性）："
          f"{len(mixed)} 行{'：' + '、'.join('L%d' % n for n in mixed) if mixed else '（本树上没有）'}")
    for n, text in outside:
        print(f"     ⊘ L{n}  {text[:66]}")
        print(f"        理由（结构给出）：属于 {enclosing(funcs, n)}；本轮 4 个变异只触碰 "
              f"chainJumpScale 与三个读法生成器 ⇒ 没有变异经过它。"
              f"**它一旦红了 ⇒ 本脚本 rc=1 并具名**（不是忽略）。")
    print(f"   另有 {len(wrapped)} 条只作为 `bad` 的文案出现（`append(bad,…)`）：")
    for n, text in wrapped:
        print(f"     ⊘ L{n}  {text[:66]}")
    print("        理由（结构给出）：它**不自己发消息**，只经 `joinLines(bad)` 随断言5 那一行一起打印 "
          "⇒ 结构上不能独立红。")
    print(f"   口径对账（两套分母**不许相加**）：本脚本按**调用处**数 ＝ {len(judge_starts)}；"
          f"验收 P4 按正则 `t\\.(?:Errorf|Fatalf)\\(` 数 ＝ {len(msg_lits)}"
          f" ＝ {len(judge_starts)} ＋ {n_fmt} 条 **`fmt.Errorf`**。")
    return bad
    print(f"   ★ 机理（现算，不是我的叙述）：那条正则**子串命中**了 `fmt.Errorf`（`fm`＋`t.Errorf`），"
          f"多出的 {n_fmt} 条正是 helper `assertDecayFirstTwo` 的返回文案；加词边界 `\\bt\\.` 即只数 "
          f"{len(judge_starts)}。**两个数不同义，不许相加。**")


def classify_reds(out: str, per: dict) -> list[tuple[str, int, str, str, str]]:
    """红行 → `(文件, 行号, 种类, 桶, 正文)`；桶 ∈ `{'表内','未认出','⊘'}`。

    ★ 与 `classify` 的关系：`classify` 只是把这三桶**投影成给人看的字符串**；
      行号与所属函数留在本函数里给「运行器判决 ⇔ 归属」对账用（`reconcile_runner`）。
      **一次分类、两个出口** —— 不许为了让对账好看而重新分一遍（那会变成两份实现）。
    """
    reds: list[tuple[str, int, str, str, str]] = []
    for ln in out.splitlines():
        m = RED_RE.match(ln)
        if not m:
            continue
        fname, n, text = m.group(1), int(m.group(2)), m.group(3).strip()
        if fname != JUDGE_FILE:
            reds.append((fname, n, "？", "未认出", text))
            continue
        incalls = calls_covering(per.get(fname), n)
        if not incalls:
            reds.append((fname, n, "？", "未认出", text))
            continue
        matched = [(k, p) for k, p in incalls if p and text.startswith(p)]
        if len(matched) >= 2:
            reds.append((fname, n, "？", "⊘", text))
            continue
        if len(matched) == 1:
            kind = matched[0][0]
            if kind == "日志":
                continue                 #: 被认出来了，只是它不是判词 ⇒ 不算红
            hit = [aid for aid, p in ASSERTIONS if p in text]
            reds.append((fname, n, kind, "表内" if hit else "未认出", text))
            continue
        reds.append((fname, n, "？", "未认出", text))
    return reds


def classify(out: str, per: dict) -> tuple[list[str], list[str], list[str]]:
    """把红行分成三桶：**(表内认得的断言 id, 未认出的红行, ⊘ 未定性的红行)**。

    ★★ G6：**取证范围必须 ≥ 运行范围**。`-run Chain` 跑的是整个包 ⇒ 出现在输出里的每个
    `*_test.go` 都要看；**非 `JUDGE_FILE` 的红行一律算「未认出」**（具名 + rc≠0），
    因为判词表**只**覆盖 `JUDGE_FILE` —— 「别的文件里的红」与「认不出的判词」是同一族的漏。

    ★★★ 归属按**消息前缀**判，不按「这一行有几种种类」（验收 §16 收窄准入，PM 记的 `bb29f311`）：
      该行每条红先与**该行各调用自己的字面首参前缀**比 —— `%` 动词之后是运行期算的、源码里没有，
      故只能比前缀。
        · **恰好 1 个调用匹配** ⇒ 归属它：日志 ⇒ 不算红（被认出来了，只是它不是判词）；判词 ⇒
          命中判词表 ⇒ 表内；不命中 ⇒ **未认出**（P2/G1 通道，rc≠0）；
        · **≥2 个调用匹配**（前缀互相覆盖）⇒ **结构上不可归属** ⇒ ⊘ 未定性，
          **不参与表内计数、也不参与控制组判定**；
        · **0 个匹配** ⇒ **未认出**（可能是非字面量首参/包装路径 ⇒ fail closed，不许当「不计入」）。
      ⇒ ★ 旧准入（「该行候选种类 >1 就进 ⊘」）是错的：它把**同行的表外真红**也丢进 ⊘
        ⇒ **未认出恒为 0**（验收实测：`faceA 隔离用：表外文案`、`P7 同行被吞的红：78.75`
        都是 `t.Errorf` 的真红，却都进了 ⊘）—— **桶换了，数还在**。
      ⇒ ★ 只有「**同行两条调用的字面前缀相同／互相覆盖**」才进 ⊘。
    """
    known: list[str] = []
    unknown: list[str] = []
    undet: list[str] = []
    for fname, n, _kind, bucket, text in classify_reds(out, per):
        if bucket == "表内":
            known.extend(aid for aid, p in ASSERTIONS if p in text)
        elif bucket == "⊘":
            incalls = calls_covering(per.get(fname), n)
            matched = [(k, p) for k, p in incalls if p and text.startswith(p)]
            undet.append(f"{fname}:{n}: {text}"
                         f"（该行 {len(matched)} 处调用的字面前缀互相覆盖 "
                         f"{'／'.join(repr(p) for _k, p in matched)} ⇒ 结构上不可归属；"
                         f"不参与表内计数与控制组）")
        elif fname != JUDGE_FILE:
            unknown.append(f"{fname}:{n}: {text}（不在判词表覆盖的文件内 ⇒ 取证范围必须 ≥ 运行范围）")
        elif not calls_covering(per.get(fname), n):
            unknown.append(f"{fname}:{n}: {text}（行号不在任何已知调用跨度内 ⇒ 认不出）")
        elif len([1 for k, p in calls_covering(per.get(fname), n) if p and text.startswith(p)]) == 1:
            unknown.append(f"{fname}:{n}: {text}（表外判词 ⇒ 归类器认不出）")
        else:
            unknown.append(f"{fname}:{n}: {text}（该行 {len(calls_covering(per.get(fname), n))} 处调用的"
                           f"字面前缀都匹配不上 ⇒ 认不出：可能是非字面量首参或包装路径"
                           f"（fail closed，不当「不计入」））")
    return known, unknown, undet


def calls_covering(per_file, n: int) -> list[tuple[str, str]]:
    """第 `n` 行落在哪些调用的跨度里，各带自己的 (种类, 字面前缀)。

    ★ 用**跨度**而不是「调用首行」：跨行调用（首参字面量写在下一行）的红行报的是**调用那一行**，
      但也可能是跨度内的行；两者都要能归属。
    """
    if per_file is None:
        return []
    _k, _s, _f, spans = per_file
    out: list[tuple[str, str]] = []
    for a, b, _ks, calls in spans:
        if a <= n <= b:
            out.extend(calls)
    return out


def judge_text_applicable() -> tuple[bool, list[str]]:
    """**表内期望**在不在这棵树上说得通 —— 按**内容**判，**不按路径**（验收 §16 F1）。

    ★ 为什么不能按路径：验收把 `go.mod ＋ mech/*.go` **逐字节原样**复制成一棵拷贝树 ⇒
      `SRC ≠ 产品树` 为真，但 M1–M4 的读数与产品树**逐项相同** ⇒ 上一版在那棵树上连打 5 次
      「不适用」，**内容相同却宣布「看不清」** —— 那是**误报**（判据用错了东西：
      我想表达的是「这棵树的**判词文案**被改过」，那是一件**内容**事件）。
    ★ 判据取**内容**本身：`ASSERTIONS` 每条前缀在该树的判词文件里**存在且唯一** ⇒ 期望适用；
      哪条不唯一/不存在就具名报出来（那棵树上「表内读数」确实与产品树不同义）。
    ★ 路径只决定**要不要做这项比较**：外部树（`SRC ≠ 产品树`）**照样做**，只是把结论标成
      「非产品树」，并**另有一条硬条件**：内容与产品树逐字节相同却判「不适用」⇒ 判红（见 `main`）。
    """
    f = WORK / "mech" / JUDGE_FILE
    if not f.exists():
        return False, [f"{JUDGE_FILE} 不在树里（{f}）"]
    txt = f.read_text(encoding="utf-8")
    bad = [f"判词前缀「{p}」在该文件里出现 {txt.count(p)} 次（应为 1）"
           for _aid, p in ASSERTIONS if txt.count(p) != 1]
    return (not bad), bad


def judge_file_sha(root: Path) -> str | None:
    """判词文件在给定树里的 SHA256。**取不到返回 None**（第三态），**不许返回哨兵串**。

    ★ F4（验收 §17）：旧版取不到时返回 `（文件不存在）`，于是它被拿去与真 sha 比 ⇒
      **「取不到」被静默压成「内容不同」**（同族 `1b6ee8e9`：两种不同的空压成一个值）。
    """
    f = root / "mech" / JUDGE_FILE
    if not f.exists():
        return None
    return hashlib.sha256(f.read_bytes()).hexdigest()


def mutate(pairs: list[tuple[str, str, str]]) -> None:
    """施加**变异**；每处替换自带 expect 自校验，替换不到就退出（失败不留一份好看的矩阵）。

    `old == ""` 表示**新建文件**（内容为新串）——G6 控制组要往包里加一个同包 `_test.go`。
    """
    for rel, old, new in pairs:
        f = WORK / rel
        if old == "":
            if f.exists():
                raise SystemExit(f"✗ 变异要新建 {rel}，但它已存在 ⇒ 读数无效")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(new, encoding="utf-8")
            continue
        text = f.read_text(encoding="utf-8")
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"✗ 变异锚点在 {rel} 里出现 {n} 次（应为 1）⇒ 变异没到达目标那行，读数无效")
        f.write_text(text.replace(old, new, 1), encoding="utf-8")


def apply_or_skip(pairs: list[tuple[str, str, str]]) -> list[str]:
    """施加**控制组**改动，并区分三种情形（第三种是外部树造成的，必须区别于「没做成」）：

    · 锚点在 ⇒ 替换，正常施加；
    · 锚点不在、但目标改动**已在树里** ⇒ 返回「不适用（外部树已施加该改动）」；
      ★ 验收的 P1 树就是这种：它先把判词改名成「读法判别器不通过：」，
      我的 P1 控制组再找「读法判别器红：」自然 0 命中——**这是「不适用」，不是「锚点坏了」**；
    · 两者都不在 ⇒ 仍**当场退出**（真锚点错误不许被当成不适用吞掉）。

    `old == ""`（新建文件）同理：文件已在且内容一致 ⇒ 不适用；内容不同 ⇒ 当场退出。
    """
    skipped: list[str] = []
    for rel, old, new in pairs:
        f = WORK / rel
        if old == "":
            if f.exists():
                if f.read_text(encoding="utf-8") == new:
                    skipped.append(f"{rel}：该文件已在树里且内容一致（外部施加）⇒ 本控制组**不适用**")
                    continue
                raise SystemExit(f"✗ 控制组要新建 {rel}，但它已存在且内容不同 ⇒ 锚点坏了，读数无效")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(new, encoding="utf-8")
            continue
        text = f.read_text(encoding="utf-8")
        n = text.count(old)
        if n == 1:
            f.write_text(text.replace(old, new, 1), encoding="utf-8")
            continue
        if n == 0 and new in text:
            skipped.append(f"{rel}：目标改动已在树里（外部施加）⇒ 本控制组**不适用**")
            continue
        raise SystemExit(f"✗ 控制组锚点在 {rel} 里出现 {n} 次且目标改动不在 ⇒ 锚点坏了，读数无效")
    return skipped


def anchors_are_distinct() -> list[str]:
    """G3 自校验：**变异之间**旧串两两不同（否则改一处会留下另一处，验收探针第一版就踩了这个）。

    ★ 控制组**故意**复用 M2 的锚点（P1/P2 的定义就是「在 M2 条件下触发」）⇒ 不参与这条检查；
      控制组自身的检查是「**同一次运行内**各锚点不重复」。
    """
    bad: list[str] = []
    olds = [m[2] for m in MUTATIONS]
    dup = {o for o in olds if olds.count(o) > 1}
    for o in dup:
        bad.append(f"变异之间旧串重复（2 处）：{o[:60]!r}")
    for name, pairs, _exp in CONTROLS:
        co = [p[1] for p in pairs]
        if len(set(co)) != len(co):
            bad.append(f"控制组「{name}」内部锚点重复")
    return bad


def reconcile(rc: int, known: list[str], unknown: list[str], undet: list[str]) -> tuple[bool, str]:
    """★ **最便宜的第二来源**（验收 §16 给的判据）：`go test` 的 rc 与三类桶对账。

    `rc != 0 ⇔ 三类桶合计 ≥ 1`。为什么要它：**每一行印的 rc 就是 `go test` 的退出码**，
    但它**从不与桶对账** ⇒ 存在一个可构造的静默实例：`RED_RE` 要求 `\\s+\\S+_test\\.go:(\\d+):`，
    **另一个包的失败**（`FAIL pkg [build failed]` 这类）不匹配 ⇒ **桶合计 0 而 rc=1**。
    本条把那种情形当场判红（「rc 红了但桶里什么都没有」＝读数与来源不一致）。
    """
    total = len(known) + len(unknown) + len(undet)
    ok = (rc != 0) == (total > 0)
    return ok, f"rc⇔桶 对账 {'✓' if ok else '✗'}（rc={rc}、桶合计 {total}）"


class Run:
    """一次运行的全部读数（**同一份产物里的量只在这里现算一次**，`45fab0e7`）。"""

    __slots__ = ("rc", "known", "unknown", "undet", "skipped", "bucket_ok",
                 "runner_ok", "runner_bad", "tests_fail", "tests_pass", "pkg_fail",
                 "build_failed", "hints", "scope_ok", "scope_bad", "scope_note", "tests_skip")

    def __init__(self, rc: int, known: list[str], unknown: list[str], undet: list[str],
                 skipped: list[str], bucket_ok: bool, runner_ok: bool, runner_bad: list[str],
                 verdict: dict, scope_ok: bool, scope_bad: list[str], scope_note: str):
        self.rc, self.known, self.unknown, self.undet, self.skipped = rc, known, unknown, undet, skipped
        self.bucket_ok, self.runner_ok, self.runner_bad = bucket_ok, runner_ok, runner_bad
        self.tests_fail = list(verdict.get("tests_fail") or [])
        self.tests_pass = list(verdict.get("tests_pass") or [])
        self.tests_skip = list(verdict.get("tests_skip") or [])
        self.pkg_fail = bool(verdict.get("pkg_fail"))
        self.build_failed = bool(verdict.get("build_failed"))
        self.hints = list(verdict.get("hints") or [])
        self.scope_ok, self.scope_bad, self.scope_note = scope_ok, scope_bad, scope_note

    @property
    def total(self) -> int:
        return len(self.known) + len(self.unknown) + len(self.undet)

    def line(self) -> str:
        """一行里同时给出**三个来源**：rc⇔桶、运行器判决、运行范围对账。

        ★ 两个量**分列**：`包判决`（包 fail＝包里有测试失败）与 `编译失败`（go 的 build-output 事件）
          不是同义词 —— 我第一版把两者都印成「包级失败」⇒ 标签与读数不同义。
        """
        return (f"rc={self.rc}（{reconcile(self.rc, self.known, self.unknown, self.undet)[1]}）、"
                f"表内红 {len(self.known)} 条 {self.known}、认不出 {len(self.unknown)} 条、"
                f"⊘ 未定性 {len(self.undet)} 条、"
                f"运行器判决：失败 Test {len(self.tests_fail)} 个 {self.tests_fail or '[]'}"
                f"／通过 {len(self.tests_pass)} 个／跳过 {len(self.tests_skip)} 个"
                f"／包判决={'fail' if self.pkg_fail else 'pass'}"
                f"／编译失败={'是' if self.build_failed else '否'}"
                f"（对账 {'✓' if self.runner_ok else '✗'}）"
                f"、运行范围对账 {'✓' if self.scope_ok else '✗'}")


def run_once(pairs: list[tuple[str, str, str]], *, control: bool = False) -> Run:
    stage()
    skipped: list[str] = []
    if pairs:
        skipped = apply_or_skip(pairs) if control else (mutate(pairs), [])[1]
    per = scan_package()
    discovered = discover_tests()                 #: ★ F5：运行范围**现算**，不写死
    rc, out, verdict = go_test()
    reds = classify_reds(out, per)
    known, unknown, undet = classify(out, per)
    rc_ok, _why = reconcile(rc, known, unknown, undet)
    runner_ok, runner_bad = reconcile_runner(verdict, reds, per)
    scope_ok, scope_bad, scope_note = reconcile_scope(discovered, verdict)
    return Run(rc, known, unknown, undet, skipped, rc_ok, runner_ok, runner_bad, verdict,
               scope_ok, scope_bad, scope_note)


def main() -> int:
    if console_check():
        return 1
    before = tree_hashes()
    #: ★★ 问④（验收 §16 F3）：两棵树的具名身份**无条件印在最前面**，不进任何分支 ——
    #:   上一版把它放在 G5 段里，验收那次按 `pats` 过滤的日志里看不到它 ⇒ 看起来「恰好在该需要它的
    #:   分支上缺席」。位置本身就是判据的一部分：**证据要在所有出口都能看见**。
    print(f"== 工作副本：{WORK.relative_to(ROOT) if WORK.is_relative_to(ROOT) else WORK} ==")
    #: ★★★ F4（验收 §17）：产品树的身份**不许从脚本位置推** —— 脚本冻到 `out/acceptance/pinned/` 后，
    #:   `__file__` 推出的「产品树」根本不存在 ⇒ 旧版把「取不到」压成「内容不同」并印成假读数。
    #:   现在**三态**：可读（附来源名）／不可得（附试过哪些，且**大声失败**）。
    p_state, p_src, p_sha, p_root = product_judge_sha()
    print(f"== G5 具名身份：SRC = {SRC}")
    print(f"              产品树身份 = **{p_state}**（来源：{p_src}）")
    if p_state != "可读":
        print("✗ 产品树身份**不可得** ⇒ 不许把它压成「内容不同」（两种不同的空压成一个值）；"
              "本轮的「内容相同/不同」与那条硬条件都**没有判据**⇒ 判失败")
        print(f"   一行修法：设 {PRODUCT_ENV}=<产品树所在仓库根> 后重跑")
        return 1
    if p_root == "git 对象":
        print("   ★ 身份取自 **git 对象**（HEAD 那一版）⇒ 与 SRC **无法比路径**，"
              "本轮不宣称「产品树只读」，只比内容")
        product_hashed = False
    else:
        product_hashed = (SRC.resolve() == Path(p_root).resolve())
        print(f"              SRC 就是产品树：**{product_hashed}** "
              f"⇒ 下面的哈希{'**量的是产品树**' if product_hashed else '**量的是 SRC 树**'}")
    print(f"              产品树判词文件 sha16 = {p_sha[:16]} ==")
    if not product_hashed:
        print("   ★ SRC ≠ 产品树 ⇒ **产品树本次未被触碰**（本脚本写路径只有 SRC／WORK），"
              "**但它没有被本次哈希取证**")
        print("   ★ 「门关着」≠「门被取证过」：要取证产品树只读，请在 SRC ＝ 产品树的那次运行里读这一行。")
    g3 = anchors_are_distinct()
    if g3:
        print("✗ G3 自校验失败（改锚点会留下另一处）：")
        for b in g3:
            print(f"      ↳ {b}")
        return 1
    #: 基线：**只跑一次**（`Run` 对象里同时带 rc⇔桶 与运行器判决两个来源）
    base_run = run_once([])
    per = scan_package()
    sp = spans_stay_inside_funcs(per)
    if sp:
        print("✗ 结构自校验失败（调用跨度跨过函数边界 ⇒ 括号配平失控 ⇒ 种类标注不可信）：")
        for b in sp:
            print(f"      ↳ {b}")
        return 1
    #: ★★ F6：覆盖面那一节的对账**必须能驱动 rc**（它是给读者判断取证范围用的；
    #:   今天它不进判定 ⇒ 只有看这一节的人会被误导，没有任何东西会红）。
    cover_bad = coverage(per)
    if cover_bad:
        print("✗ 覆盖面这一节的计数对不上账（Σ 分行 ≠ 整包独立来源）⇒ 读者会按它判断取证范围：")
        for b in cover_bad:
            print(f"      ↳ {b}")
        return 1
    #: ★★ F1（验收 §16）：**表内期望**的适用性按**内容**判，不按路径；并有一条硬条件：
    #:   内容与产品树**逐字节相同**却判「不适用」 ⇒ 当场判红（那正是上一版的误报）。
    known_ok_content, known_why = judge_text_applicable()
    s_sha = judge_file_sha(SRC)
    #: ★★ 三态（验收 F4 修法③）：**相同／不同／不可得**。`不可得` 不许退化成「不同」。
    if s_sha is None:
        content_state = "不可得（SRC 树里没有判词文件）"
    elif s_sha == p_sha:
        content_state = "相同"
    else:
        content_state = "不同"
    print(f"== 表内期望的适用性（按**内容**判，不按路径）：判词文件 {JUDGE_FILE} "
          f"在 SRC 树里 = **{'适用' if known_ok_content else '⊘ 不适用'}**"
          f"（与产品树该文件：**{content_state}**；产品树身份取自 {p_src}）==")
    for w in known_why:
        print(f"      ⊘ {w}")
    if s_sha is None:
        print("✗ SRC 树里取不到判词文件 ⇒ 「内容相同/不同」是**不可得**（不是「不同」）⇒ 判失败")
        return 1
    if content_state == "相同" and not known_ok_content:
        print("✗ 硬条件被破：SRC 的判词文件与产品树**逐字节相同**，却判「表内期望不适用」"
              "（内容相同就不可能看不清）⇒ 判据用错了东西，读数无效")
        return 1
    print(f"== 基线：{base_run.line()} ==")
    #: ★★★ F5（验收 §18／PM 加硬）：**运行范围**是一个被对账过的导出量，不许是没人为它发声的常量。
    print(f"== 运行范围：{base_run.scope_note} ==")
    for u in base_run.unknown:
        print(f"      ↳ {u}")
    for u in base_run.undet:
        print(f"      ↳ {u}")
    for b in base_run.runner_bad:
        print(f"      ↳ 运行器对账：{b}")
    for b in base_run.scope_bad:
        print(f"      ↳ 运行范围对账：{b}")
    if (base_run.rc != 0 or base_run.total or not base_run.runner_ok
            or not base_run.scope_ok):
        #: ★ 基线把 ⊘ 未定性也算了进来：**这不是让它参与「计数」**，而是「产品树本该一条都没有」——
        #:   产品树里出现同行多调用 ⇒ 归类器从此对那一行**没有归属能力**，必须在基线处就看见。
        print("✗ 基线不是全绿（含 ⊘ 未定性；或运行器／运行范围对账不过）⇒ 后面的矩阵无意义")
        return 1

    ok = True
    #: ★ 矩阵**先算后印**：任何一步异常退出（如锚点找不到）都不会留下一份「看着正常」的矩阵。
    #:   验收 P3 的判据就是这条（旧版先印表头再跑 ⇒ 失败时表头已落地 ⇒ 检查读成「印了矩阵」）。
    rows: list[str] = []
    for name, rel, old, new, expect in MUTATIONS:
        r = run_once([(rel, old, new)])
        #: 面4（PM 转派）：`rc != 0` 免费且严格更强——一个变异若连 go test 都没弄红，这一行不该算过。
        #: ★ 但它**关不掉静默**：P7b 那次的 rc 本来就是 1，缺的是「红行总数」的第二个来源（PM 已登记）。
        #: ★★ 现在有两个：`bucket_ok`（rc⇔桶 对账，验收 §16 给的最便宜的那个）与
        #:   `runner_ok`（**根因那笔的强版本**：`go test -json` 的失败集合与我的逐函数归属逐条对账）。
        #:   ★ 另加一条「恰红 1 条」的**第二来源**：运行器说失败的 Test 必须**恰好 1 个**。
        good = (r.rc != 0 and r.bucket_ok and r.runner_ok and r.scope_ok
                and len(r.tests_fail) == 1
                and len(r.known) == 1 and not r.unknown and not r.undet
                and r.known[0] == expect)
        ok &= good
        rows.append(f"{'✓' if good else '✗'} {name}：{r.line()}（预期只红 {expect}）")
        for u in r.unknown:
            rows.append(f"      ↳ {u}")
        for u in r.undet:
            rows.append(f"      ↳ {u}")
        for b in r.runner_bad:
            rows.append(f"      ↳ 运行器对账：{b}")
        for b in r.scope_bad:
            rows.append(f"      ↳ 运行范围对账：{b}")

    ctrl_rows: list[str] = []
    n_skipped = 0
    n_na = 0
    #: ★★ F1（验收 §16）：**表内期望的适用性按内容判**（`judge_text_applicable`），不看路径。
    #:   上一版按 `SRC ≠ 产品树` 判 ⇒ 验收把文件**逐字节原样**复制成拷贝树后，**连打 5 次「不适用」**
    #:   —— **内容相同却宣布「看不清」**（误报）。现在路径只决定「要不要声明这不是产品树」。
    #:   内容里判词前缀不齐（真被外部改过）⇒ 记 **⊘ 不适用**（具名原因），
    #:   而**通道判据（未认出／未定性／不许出现）照旧生效** —— 否则「不适用」会变成控制组放水的后门。
    for name, pairs, exp in CONTROLS:
        r = run_once(pairs, control=True)
        rc, known, unknown, undet, skipped, rc_ok = (r.rc, r.known, r.unknown, r.undet,
                                                     r.skipped, r.bucket_ok)
        n_skipped += len(skipped)
        #: ★ 控制组的判据从「有未认出」升级成**逐桶对期望**（PM 裁定「问①」后）：
        #:   否则新加的 ⊘ 未定性 桶会让控制组变成恒真（验收 §14.1 记的那条）。
        #:   `⊘` 本身**不参与**这里的判定（它在期望里只以 `undet_min` 的形式出现，那是**断言它的读数**，
        #:   不是拿它当通过条件）——`unknown_min` 与 `forbid` 才是通道判据。
        known_ok: bool | None = True
        if exp.get("known") is not None:
            known_ok = (sorted(set(known)) == sorted(set(exp["known"]))) if known_ok_content else None
        if exp.get("reconcile_must_fail"):
            #: ★★★ P10（根因那笔强版本的**控制组**）：这一类控制组断言的不是分类器，而是**检查器本身**
            #:   —— 「编译失败 ⇒ 正文 0 条红行 ⇒ rc≠0 而桶合计 0」必须**当场被判红**。
            #:   ⇒ 期望写成：rc≠0、**rc⇔桶 对账失败**、编译失败为真、桶合计 0、且运行器那条具名在。
            good = (rc != 0 and not rc_ok and r.build_failed and r.total == 0
                    and bool(r.runner_bad))
        else:
            good = (rc != 0 and rc_ok and r.runner_ok and r.scope_ok
                    and len(unknown) >= exp.get("unknown_min", 0)
                    and len(undet) >= exp.get("undet_min", 0)
                    and len(undet) <= exp.get("undet_max", 10 ** 9)
                    and known_ok is not False
                    and not any(f in known for f in exp.get("forbid", [])))
        if skipped:
            #: ★ 「不适用」**不算通过**：控制组没跑过，通道证明就不完整 ⇒ 不许靠它变绿（fail closed）
            good = False
        if known_ok is None:
            n_na += 1
        ok &= good
        ctrl_rows.append(f"{'✓' if good else ('⊘' if skipped else '✗')} {name}：{r.line()}"
                         f"（期望："
                         + ("**对账必须失败**：rc≠0、桶合计 0、**编译失败**、运行器具名"
                            if exp.get("reconcile_must_fail") else
                            f"表内 {exp.get('known') if known_ok_content else '⊘ 不适用（该树判词文案不齐）'}、"
                            f"未认出≥{exp.get('unknown_min', 0)}、"
                            f"未定性 {exp.get('undet_min', 0)}..{exp.get('undet_max', '∞')}"
                            f"{'、不许出现 ' + '／'.join(exp['forbid']) if exp.get('forbid') else ''}")
                         + "）")
        if known_ok is None:
            ctrl_rows.append(f"      ⊘ 表内期望不适用：**内容**判据给出「{JUDGE_FILE} 的判词前缀在 SRC 树里不齐」"
                             f"（{SRC.name}）⇒ **这一栏不计入判定**；通道判据（未认出／未定性／不许出现）照旧生效")
        if not rc_ok and not exp.get("reconcile_must_fail"):
            ctrl_rows.append("      ✗ rc⇔桶 对账失败：rc 红了但三类桶合计为 0（或反之）"
                             "⇒ rc 与桶不是同一个来源，读数无效")
        for b in r.runner_bad:
            ctrl_rows.append(f"      ↳ 运行器对账：{b}")
        for b in r.scope_bad:
            ctrl_rows.append(f"      ↳ 运行范围对账：{b}")
        for s in skipped:
            ctrl_rows.append(f"      ⊘ 不适用：{s} ⇒ **本树上通道证明不完整**（既不算通过、也不许因此变绿）")
        for u in unknown:
            ctrl_rows.append(f"      ↳ 具名（认不出）：{u}")
        for u in undet:
            ctrl_rows.append(f"      ↳ 具名（⊘ 未定性）：{u}")
        if not unknown and not undet and not skipped and not exp.get("reconcile_must_fail"):
            ctrl_rows.append("      ↳ ✗ 既没认出的红行、也没未定性的行被报出来 ⇒ 「认不出」不会自己红（正是要防的静默）")

    print("== 变异矩阵（G4：每个最小变异**必须恰好红 1 条表内断言、且 0 条认不出**）==")
    for r in rows:
        print(r)
    print("== 控制组（G1/G6：**期望脚本红**——认不出、或别的文件里的红，都必须自己会红）==")
    for r in ctrl_rows:
        print(r)

    #: 面2（PM 转派）：对称于表外的 ⊘ 栏——把「**本轮零变异经过**」的**表内**断言也印出来。
    #: ★ 只印不判（PM 明确：做成硬判据「每个表内断言至少被一个变异经过」会要求补 2 个变异，
    #:   属另一件事；今天 5 条表内断言只经过 3 条 ⇒ 断言2／断言3 零变异经过）。
    exercised = {m[4] for m in MUTATIONS}
    idle = [aid for aid, _p in ASSERTIONS if aid not in exercised]
    print(f"== 变异覆盖到的表内断言：{len(exercised)}/{len(ASSERTIONS)}"
          f"（零变异经过的：{'、'.join(idle) if idle else '无'}）[只印不判，硬判据已由 PM 登记] ==")

    after = tree_hashes()
    same = before == after
    ok &= same
    #: ★★★ 问④（PM 转派，验收量的）：「门关着」≠「门被取证过」。
    #: 哈希走 `SRC.rglob` ⇒ 它量的是 **SRC 树**。我自己跑时 SRC ＝ 产品树 ✓；
    #: **验收把 SRC 指到 `out/` 拷贝树**时，这一条量的就是拷贝树 —— 那一刻
    #: **产品树没被哈希、也没被 git 取证**（git 那侧会正确判「不适用」），只是**结构上未被触碰**
    #: （本脚本的写路径只有 SRC 与 WORK）。⇒ 证据必须**具名它量的是谁**。
    #: ★★ F3（验收 §16）：身份两句**已提到运行最前面无条件打印**（不在这个分支里）——
    #:   位置本身是判据的一部分：**证据要在所有出口都能看见**，不能只落在需要它的那条分支上。
    print(f"== G5 哈希取证：{'✓ 逐文件 SHA256 跑前跑后相同' if same else '✗ 被改动了！'}"
          f"（**全树 {len(before)} 个文件**，{('量的是产品树：' + str(SRC)) if product_hashed else ('量的是 SRC 树（**不是产品树**）：' + str(SRC))}）==")
    if not same:
        for k in sorted(set(before) | set(after)):
            if before.get(k) != after.get(k):
                print(f"      ↳ {k}: {before.get(k)} → {after.get(k)}")
    g_state, g_text = git_evidence()
    print(f"== G5 脚本自带的 git 证据：{g_state} —— {g_text} ==")
    if g_state == "脏":
        ok = False

    #: ★★★ F2/F3（验收 §16）：**汇总必须按实际取证的栏生成**，不许把「明细里 ⊘ 的栏」在汇总里
    #:   说成已经判过；也**不许在没取证产品树的那一轮里宣称「产品树只读」**。
    #:   纪律：**「不适用」必须在明细、括注、汇总三处同口径 —— 只落一处就等于没落。**
    known_col = f"表内断言{'（适用）' if known_ok_content else f'（⊘ 不适用 {n_na} 处：该树判词文案不齐）'}"
    tree_col = ("产品树只读（哈希取证：是）" if product_hashed
                else "**产品树本次未被哈希取证**（哈希量的是 SRC 树 ⇒ 本条不写「产品树只读」）")
    print()
    if ok:
        print(f"== 判定：4/4 变异各行成立（每行 {known_col}、0 认不出、0 未定性、rc⇔桶 对账 ✓、"
              f"**运行器对账 ✓（失败 Test 恰 1 个）**、**运行范围对账 ✓**）、"
              f"{len(CONTROLS)}/{len(CONTROLS)} 控制组都按**自己的期望**红并具名、"
              f"{tree_col} ⇒ 通道与矩阵在**已被取证的栏**上都成立 ==")
    else:
        print("== 判定：✗ 有变异红 ≠1 条，或有「认不出的红行」没被具名，或控制组不满足自己的期望，"
              "或 rc 与桶对不上账，或树被写 ⇒ 判失败 ==")
    if n_skipped:
        print(f"   ★ 另有 {n_skipped} 处控制组「不适用」（外部树已施加该改动）⇒ 本树上通道证明不完整")
    if n_na:
        print(f"   ★ 另有 {n_na} 处「表内期望 ⊘ 不适用」（按**内容**判：该树 {JUDGE_FILE} 的判词前缀不齐）"
              f"⇒ 那一栏没判，但通道判据都判了")
    if not product_hashed:
        print("   ★ 汇总口径声明：本轮**产品树未被哈希取证、也未被 git 取证**（后者在非索引树里正确判"
              "「不适用」）⇒ 读数只覆盖 SRC 树；**「门关着」≠「门被取证过」**")
    print("★ 纪律：「认不出」必须自己会红，不能靠「恰好没有第二条」")
    print("★ 纪律：红行的取证范围必须 ≥ 运行范围（`-run` 跑几个文件，就得看几个文件）")
    print("★ 纪律：一行能打出多种文本时，「优先」是选定一个 —— 这里要的是**两个都留着**"
          "（归属不定的进 ⊘ 未定性，不参与计数与控制组）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
