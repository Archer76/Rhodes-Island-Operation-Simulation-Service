#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中文散文里的半角引号检查（`9d16e3ae`：同一规矩一晚犯两次 ⇒ 能变检查的变检查）。

**规则**：**中文散文**里引用措辞一律用「」，不用半角 `"`。
**不算违规**：代码（Go/Python 字符串字面量、Markdown 围栏内的代码、行内代码 `` `...` ``）。

用法：
    python tools/cjk_quote_lint.py                      # 默认范围＝**产品在库文件**（git ls-files）
    python tools/cjk_quote_lint.py --disk               # ★ 显式开关：扫**工作区磁盘**（含未入库的内部件）
    python tools/cjk_quote_lint.py -- rios-sim/mech/chain.go docs/x.md
    python tools/cjk_quote_lint.py --quiet              # 只报计数

退出码：0＝干净；1＝有违规；**2＝输入无效（有不存在的路径，本轮不给判定）**；
**5＝检查没能作出判定**（自己崩了，或范围定不下来）。★ 5 与业务态不重叠，见下。

★ 判据自身的两个坑（都实测踩过）：
  ① **围栏内的 Go 代码原文不能算违规**——`catch(chain.go)` 的原文行会被抄进 Markdown，
     若不过滤围栏，检查会把自己的证据当成违规（第一版就误报了 3 处）。
  ② **行内代码先剥掉再判**——`{"attack@chain.atk_scale": 0.75}` 这种 JSON 片段属于代码，
     正确改法是包反引号，而不是把它改成「」。

★★ 第三个坑（2026-09-20 修，PM 派单）：**判据的输出依赖了终端编码**
  · 实测（改前对象：113 行 / content sha16 `343be4a102026032`）：stdout 为 **GBK** 时，
    总结行里的 `⇒`（U+21D2）编不进 GBK ⇒ `UnicodeEncodeError` ⇒ **0 处违规也 rc=1（假红）**；
  · 而同一份**违规**文件在 GBK 下**同样** rc=1 —— **那个红是崩溃给的、不是判据给的**
    （`06c2d722`：脚本红了≠判据红了），且**两侧读数同值 ⇒ 这道闸门在 GBK 终端上零分辨力**；
  · ★ 更要紧的是**触发面**：本机 `sys.stdout.encoding` **默认就是 gbk**（`PYTHONIOENCODING` 未设）
    ⇒ **默认路径本来就是坏的**，不是"只有被强制 GBK 才坏"（`e7be3da5`：默认路径最危险）。
  · 处置三条：**① 只放宽错误处理器、不改编码**（改编码会让现有中文输出在 GBK 终端变乱码），
    编不出的字符退化成**转义文本**（反斜杠加码位）——**信息不丢**，比 `?` 好；
    **② 新增 ASCII 机读判定行**（`VERDICT=…`），终端编码不是这道检查能控制的变量；
    **③ 给自己「崩了」留一个与业务态不重叠的退出码（5）**，否则崩溃会被读成「有违规」。
  · ★ 既有输出行的形状**一行都没动**：那一栏是别人的接口（`63d7976f`）。

★★ 第四个坑（2026-09-20 修）：**范围源与「找不到」**
  · 旧版把**不存在的路径静默跳过**，却仍算进「扫 N 个文件」⇒ 印「扫 1 个文件：0 处」＋ rc=0
    ⇒ **「要扫的」与「扫了的」被印成同一个数，「找不到」被读成「通过」**（`bd07345f`）。
    实测它当场咬过我一次：把冻结副本放进嵌套目录后 `ROOT=parents[1]` 变了，相对路径拼出
    不存在的文件 ⇒「违规文件 rc=0」差点被我写成「工具检测不到违规」。
    ⇒ 本版：**有不存在的路径即 rc=2（不给判定）**，并逐条印 `MISSING=`。
  · 旧版默认范围扫的是**工作区磁盘**（`tools/*.py`、`ak_tactic/**/*.py`、`rios-sim/**`、`docs/*.md`），
    而 `fd052cf` 把 98 个内部件从索引摘出、**磁盘一律保留** ⇒ 全仓闸门**从此恒红**
    （实测 2751 处／217 文件；改前/改后同一份文件表对照 2751=2751 ⇒ 与任何单笔改动无关）。
    ★ **恒红的闸门一定会被绕过**（而它当晚刚抓过三次真错）。
    ⇒ 本版：**默认范围＝产品在库文件**（`git ls-files` **就是权威定义**，不是缓存目录），
      **保留 `--disk` 显式扫磁盘**；★ 收窄的代价写在这里：**未入库的磁盘文件不再被默认扫到**，
      内部件要扫必须显式加 `--disk`（＝"收窄"不许做成"没人管"）。
    ⇒ 输出恒带 `SCOPE=INDEX|DISK|PATH` 与 `REQUESTED=/SCANNED=/MISSING=`，**范围源与两个数一起印**。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u4e00-\u9fff]")
INLINE_CODE = re.compile(r"`[^`]*`")
#: ★ 收窄：**引号里含中文**才算「散文引用」。注释里举例一个键名（`"atk_scale"`）是技术写法，
#: 不是中文正文引用——不收窄的话全仓库会报 2933 处（实测），判据宽到没用。
PROSE_QUOTE = re.compile(r'"[^"]*[\u4e00-\u9fff][^"]*"')
DEFAULT_GLOBS = ("rios-sim/**/*.go", "rios-sim/**/*.md", "tools/*.py", "tools/*.md",
                 "docs/*.md", "ak_tactic/**/*.py")

RC_CLEAN, RC_VIOLATIONS, RC_MISSING, RC_CRASH = 0, 1, 2, 5
#: ★ 四个值互不重叠：**「查了有问题」（1）／「我没查成」（2）／「我根本没判成」（5）** 是三个结论，
#: 压成一个值正是这一晚反复出现的那个病（把两种不同的东西压成同一个值）。


def _glob_to_re(pat: str) -> re.Pattern[str]:
    r"""把仓库里用的 glob 写法翻成正则（`**/` 匹配零层或多层目录，`*` 不跨 `/`）。

    ★ 为什么要自己翻：`Path.glob` 只能扫磁盘，而默认范围要落在**在库**文件上；
      `fnmatch` 的 `*` 会跨 `/`，与 `tools/*.py` 的原意不符。两条都不合用，故显式写死，
      并由调用方把两种范围各跑一次、把两个数都印出来（口径可对账）。
    """
    out: list[str] = []
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append(r"(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(r".*")
            i += 2
        elif pat[i] == "*":
            out.append(r"[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


SCOPE_RES = tuple(_glob_to_re(g) for g in DEFAULT_GLOBS)


def index_files() -> tuple[list[Path] | None, str]:
    """默认范围的文件表＝**产品在库文件**。返回 `(文件表, 说明)`；文件表为 None 表示**定不下范围**。

    ★ `git ls-files` 在这里**就是权威定义**（量的就是「谁在库」）—— `d785c3f8` 那条
      「本地缓存目录不是权威清单」说的是「谁取过」，不适用于这里。
    ★ 用**文件句柄**接子进程输出，不用 `capture_output`：后者在本机的受限沙箱档下
      会因开不了命名管道而抛 `PermissionError`（`_winapi.CreatePipe`），而这条闸门
      本身要能在尽可能多的档下工作；文件句柄那条不依赖命名管道。
    """
    import tempfile
    try:
        with tempfile.TemporaryFile() as t:
            r = subprocess.run(["git", "ls-files", "-z"], cwd=str(ROOT),
                               stdout=t, stderr=subprocess.STDOUT)
            t.seek(0)
            blob = t.read()
    except Exception as e:  # noqa: BLE001 - 定不下范围要大声失败，不许偷偷退回扫磁盘
        return None, f"git 起不来: {type(e).__name__}: {e}"
    text = blob.decode("utf-8", errors="replace")
    if r.returncode != 0:
        return None, f"git ls-files rc={r.returncode}: {text.strip()[:160]}"
    names = [n for n in text.split("\0") if n]
    keep = [n for n in names if any(rx.match(n) for rx in SCOPE_RES)]
    return [ROOT / n for n in sorted(set(keep))], f"git ls-files 报在库 {len(names)} 个、命中本范围 {len(keep)} 个"


def violations_in(path: Path) -> list[tuple[int, str]]:
    """返回 [(行号, 该行原文)]——只报**散文行**里的半角引号。"""
    out: list[tuple[int, str]] = []
    suffix = path.suffix
    in_fence = False
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = line.strip()
        if suffix == ".md":
            if s.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:                       #: ★ 坑①：围栏内是代码，不算散文
                continue
        elif suffix == ".go":
            if not s.startswith("//"):         #: Go 字符串字面量是代码
                continue
        elif suffix == ".py":
            if not s.startswith("#"):
                continue
        if not CJK.search(line) or '"' not in line:
            continue
        body = INLINE_CODE.sub("", line)           #: ★ 坑②：行内代码里的引号不算
        if not PROSE_QUOTE.search(body):
            continue
        out.append((i, s))
    return out


def _show(p: Path) -> str:
    """显示的路径：仓库内用相对路径；**仓库外用绝对路径**。

    ★ 这里曾崩过：`p.relative_to(ROOT)` 对仓库外的文件抛 `ValueError`，
    于是合成反例那条的 rc=1 是**崩溃**给的、不是判据给的（`06c2d722`：脚本红了≠判据红了）。
    """
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def _make_output_safe() -> None:
    """★ 判据的输出不许依赖终端编码（模块头第三个坑）。

    **只放宽错误处理器，不改编码**：改编码会让现有中文输出在 GBK 终端整片变乱码，
    而放宽处理器只是把编不出的字符退化成转义文本——**信息不丢**，现有形状也不变。
    ★ 被替换成无 encoding 约束的流（别人用 StringIO 接）会抛 AttributeError：
    那正是**「不适用」**这一态，不是失败（`13274c48`）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except Exception:  # noqa: BLE001 - 不支持 reconfigure 的流 ⇒ 不适用，继续
            pass


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--"]
    quiet = "--quiet" in args
    fix = "--fix" in args
    disk = "--disk" in args                     #: ★ 显式开关：扫工作区磁盘（含未入库的内部件）
    args = [a for a in args if not a.startswith("--")]
    if args:
        files = [Path(a) if Path(a).is_absolute() else ROOT / a for a in args]
        scope, scope_why = "PATH", "调用方显式给了路径"
    elif disk:
        files = sorted({p for g in DEFAULT_GLOBS for p in ROOT.glob(g)})
        scope, scope_why = "DISK", "显式 --disk：扫工作区磁盘"
    else:
        got, scope_why = index_files()
        if got is None:
            #: ★ 定不下范围就**不给判定**（不许悄悄退回扫磁盘：那会让口径两副面孔）
            print(f"SCOPE_ERROR={scope_why}")
            print("VERDICT=SCOPE_ERROR")
            return RC_CRASH
        files, scope = got, "INDEX"
    total, hit_files, scanned, missing = 0, 0, 0, []
    for p in files:
        if not p.is_file():
            #: ★ 不许静默跳过（模块头第四个坑）。有不存在的路径 ⇒ 下面直接 rc=2，不给判定。
            missing.append(_show(p))
            continue
        scanned += 1
        v = violations_in(p)
        if not v:
            continue
        hit_files += 1
        total += len(v)
        if not quiet:
            for n, text in v:
                print(f"  {_show(p)}:{n}: {text[:96]}")
        if fix:
            #: ★ 「能变检查的变检查」的下一步：**规则机械化了，修法也机械化**
            #: （人眼看 9 处、手改 9 处，就会漏 —— 实测我写新段落时又漏了 9 处，是这道检查抓住的）
            lines = p.read_text(encoding="utf-8").splitlines(keepends=False)
            for n, _t in v:
                lines[n - 1] = PROSE_QUOTE.sub(lambda m: "「" + m.group(0)[1:-1] + "」", lines[n - 1])
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"  ✎ 已修 {_show(p)} 的 {len(v)} 行")
    print(f"  ⇒ 扫 {len(files)} 个文件：{hit_files} 个文件有违规、共 {total} 处"
          f"（散文行半角引号；围栏代码与行内代码已排除）{'【已 --fix】' if fix else ''}")
    #: ★ 以下三行是新增的（上面那一行的形状**一个字都没动**）：
    #: ① 范围源与「请求数/实际扫到数/缺失数」一起印——旧版把请求数当成扫到的数，
    #:    于是「扫 1 个文件：0 处」既可能是真干净、也可能是**一个文件都没扫**（`bd07345f`）；
    #: ② 机读判定行一律 ASCII，让机器消费者不必去解析中文散文。
    for m in missing:
        print(f"MISSING={m}")
    print(f"SCOPE={scope} REQUESTED={len(files)} SCANNED={scanned} MISSING={len(missing)}")
    print(f"SCOPE_NOTE={scope_why}")
    if missing:
        #: ★ 「我没查成」与「查了有问题」是两个结论，不许压成一个值（PM 裁定 C）。
        print(f"VERDICT=INVALID_INPUT missing={len(missing)} files={hit_files} hits={total}")
        return RC_MISSING
    print(f"VERDICT={'CLEAN' if total == 0 else 'VIOLATIONS'} files={hit_files} hits={total}")
    return RC_CLEAN if total == 0 else RC_VIOLATIONS


if __name__ == "__main__":
    _make_output_safe()
    try:
        _rc = main(sys.argv)
    except BaseException as _e:  # noqa: BLE001 - ★ 崩了必须是一个与业务态不重叠的值
        print(f"VERDICT=SELFCHECK_CRASH EXC={type(_e).__name__}: {_e}")
        _rc = RC_CRASH
    try:
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(_rc)
