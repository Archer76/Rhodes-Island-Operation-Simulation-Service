#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""kind ↔ Go 落点 映射表（C 档乙，第二版）。

**这是「谁对应谁」的表，不是「该不该建模」的判断**。

════════════════════════════════════════════════════════════════════════
判据（**先写后跑**，2026-09-20 预注册；第二版的改动见文末「版本变更」）
════════════════════════════════════════════════════════════════════════
L 列（机制种类）：`ak_tactic/formula.py` 的 `RULES[*].kind` 的**确切字面值**。
    身份＝代码本身（跑起来 import 出来的值），不是中文机制名、不是我的概念。
M 列（Python 落点写出的字段名）：从 formula.py 里 `t.kind` 分支块中**机械抽取**
    `note("名字")` 的第一个实参与 `out.<名字>`；每条都带**行号**与**抽取方式**
    —— 这两项合起来就是「**给的是什么、凭什么**」的答案。
R 列（Go 侧机制标识）**四态**，顺序即优先级：

    · **有落点**：M 列任一 cand 在 `rios-sim/**/*.go`（**排除 `*_test.go`**、
      **剥掉整行与行尾注释**）里以**整词、大小写敏感**命中 ⇒ 列 `文件:行` ＋ **原文行**。
      ★ 附原文行是必须的：命中会被通用词骗（`60b84b37`）。
    · **待换尺子**：0 命中，且**存在 cand 与 kind 名不同源**（kind 名不是 cand 的子串）。
      ⇒ 这是**问错了名字**，不是「Go 侧没有」：**要先回答「这个 kind 该抽哪个字段名」**。
      实例（验收对账实测）：`regen` 的 cand 被抽成 `heal_scale`（与 `heal` 共用），
      而 Go 侧真落点是 `RegenAura`／`regenPerSec`／`Farmland.RegenPerSecond`。
    · **未核**：0 命中且 cand 与 kind 名同源（要读 Go 确认），**或** Python 侧根本没有可抽的
      字段名（那把尺子量不到，两件事分开计数）。
    · **无落点**：**本轮一律不填**。它需要「逐条读过 Go 侧 + 写明取证范围」才算
      （`fac4b7de`：全称量词要么有穷举证据要么不写）。**不许由 0 命中推出**（`7f782586`／`1865d35a`）。

★ **两个口径分开写**（`6dd6739c`：两套分母的数不许并列）：
  「有落点」既报 **kind 计数**，也报 **distinct cand 字段计数**——`damage` 与 `ep_damage`
  共用 cand `damage_type`，所以 kind 计数 > 净字段计数。

反向守卫（`--check`，必须能红）：
    ① 敏感性：把一个**已知有落点**的 kind 的候选名人为清空 ⇒ 必须变「未核」；
    ② 控制组：锚**从索自身取**（不许拿「记忆里该存在」的名字当锚）⇒ 必须判「有落点」；
    ③ **两种注释口径逐行判决不变**：行尾注释剥与不剥，23 行态必须逐行相同；
    ④ **新态可行使**：`regen` 必须落在「待换尺子」（落错档 = 这一档是空架子，红）。
    任一条不成立 ⇒ `rc=1`。

用法：
    python tools/kind_mech_map.py --md docs/kind-mech-map.md   # 出表
    python tools/kind_mech_map.py --check                      # 反向守卫

版本变更（2026-09-20）：
    v1 → v2 起因＝验收对账（`msg-mu8xg2iz-f4`／`msg-mu8yghyg-fa`）与 PM 裁定（`msg-mu8yg0hb-f8`）：
    ① 新增第四态「待换尺子」（`regen` 由「未核」改判——0 命中是尺子读数，不是机制事实）；
    ② M 列增列**抽取方式**，并新增「逐格交代」节回答「给的是什么、凭什么」；
    ③ 「有落点」按 kind／distinct cand 两个口径分列，`ep_damage` 的归属标未核；
    ④ `go_index()` 剥掉**行尾注释**（词表 1508 → 1490），并断言两种口径判决逐行不变。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORMULA = ROOT / "ak_tactic" / "formula.py"
GO_ROOT = ROOT / "rios-sim"

_KIND_IN = re.compile(r"""t\.kind\s+in\s*\(([^)]*)\)""")
_KIND_EQ = re.compile(r"""t\.kind\s*==\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_QUOTED = re.compile(r"""["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_NOTE = re.compile(r"""note\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_OUT = re.compile(r"""\bout\.([A-Za-z_][A-Za-z0-9_]*)""")
_WORD = re.compile(r"""[A-Za-z_][A-Za-z0-9_]*""")

#: 这些名字**不是落点**：Go/Python 内建或纯占位（实测 `append` 会把 `control` 骗成「有落点」）
_NOT_A_LANDING = frozenset("append other value len make range min max sum print".split())

#: ★ **本轮新增的 Go 文件**——表里要把「含它／不含它」两个读数分开印，否则会**自指**：
#: 我新写的 `rios-sim/mech/chain.go` 里带着 `json:"atk_scale"` 等标签，会让 `targets`／`damage`
#: 的「有落点」多出落在我自己文件上的那几处。验收那一版是**没有这个文件**的树，
#: 两个读数不可比（`515530a8`：比对树是否相同要写死两个 sha）。
#:
#: ★★ 但这个集合**本身有身份问题**（PM `msg-mu8zychr-fp` 把验收的建议升格为硬要求）：
#: **「本轮」是随时间漂移的词**——只印 6，读者无法判断它是否可比。所以：
#: ① 表里必须印**被排除文件清单**（路径 ＋ 首次入库 sha ＋ 时间），② 那一列的表头要写明
#: 「排除的是清单里这些」，③ **划界规则也写出来**：本集合＝**手工列出的路径**（不是 tag、不是起点 sha），
#: 每加一个文件都要在这里补一行——**清单要能被人拿去复核，而不是只能被相信**。
_NEW_THIS_ROUND = frozenset({"rios-sim/mech/chain.go"})

#: 划界规则（写进表里，供复核）
_NEW_THIS_ROUND_RULE = ("手工枚举的路径集合（不是 tag、不是起点 sha）："
                        "本轮新增且会被同一把尺子算成落点的文件")


def new_file_provenance() -> list[tuple[str, str, str]]:
    """每个「本轮新增文件」的**首次入库 sha 与时间**（现算，不写死）。

    返回 [(相对路径, sha 或「未入库」, 时间或「—」)]。
    ★ 用 `--diff-filter=A`（Added）取**最早一次**入库那条；未入库的文件如实写「未入库」，
    不许留空——留空会被读成「已入库但我懒得写」（同族 `bd07345f`：找不到会被读成通过）。
    """
    out: list[tuple[str, str, str]] = []
    for rel in sorted(_NEW_THIS_ROUND):
        p = subprocess.run(
            ["git", "log", "--diff-filter=A", "--format=%h|%ad", "--date=format:%Y-%m-%d %H:%M:%S",
             "--", rel], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        lines = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
        if p.returncode != 0:
            out.append((rel, "取不到（git 报错）", "—"))
        elif not lines:
            out.append((rel, "未入库", "—"))
        else:
            sha, _, when = lines[-1].partition("|")
            out.append((rel, sha, when))
    return out

_GO_KEYWORDS = frozenset("""func return struct interface package import range string int
bool error make append len nil true false type var const for if else switch case default
byte rune uint64 int64 uint32 int32 float64 float32 defer go chan map""".split())

#: 疑似通用词：没有 `_` 的短英文名。命中了也**要单独标出来**——通用词命中会被当落点
#: （`60b84b37`：判「有消费点」要摆原文行；命中数会被通用词骗）。
_GENERIC = frozenset("""damage heal buff debuff control cost sp flag range prob pen shield
dodge regen count targets summon trait duration value time""".split())


def kinds_and_rules() -> dict[str, list[str]]:
    """L 列：kind → 规则名清单（身份＝跑起来的 `RULES`，不是抄文档）。"""
    sys.path.insert(0, str(ROOT))
    from ak_tactic import formula as F

    out: dict[str, list[str]] = {}
    for r in F.RULES:
        out.setdefault(r.kind, []).append(r.name)
    return out


def landing_fields() -> dict[str, list[tuple[str, int, str]]]:
    """M 列：kind → [(字段名, formula.py 行号, 抽取方式)]，机械抽取，带行号。

    `抽取方式` ∈ {"note", "out"}：**这就是「凭什么叫这个名字」的答案**——
    要么是 `formula.py:行` 的 `note("名字")` 第一个实参，要么是同处 `out.<名字>` 赋值。

    ★ 第一版**串了块**：`cur` 一直保留到文件末尾，于是 `control` 那一行里混进了 1800 行以后
    的 `append`／`true_damage`（实测被 `append` 这个 Go 内建名骗成「有落点」）。
    修法＝记住 kind 行自身的缩进，**缩进回到该层且本行不是 kind 行就复位**。
    ★ 第二个自伤（v2 修）：kind 条件里**除 kind 之外的字符串**也被当成了 kind——
    `elif t.kind == "targets" and t.op == "enemy":` 里的 `"enemy"` 被登记成一个幽灵 kind，
    于是 `max_target` 被算成「与 `enemy` 共用」。修法＝**只认 `t.kind` 那一段**：
    `in (…)` 取括号内的表、`==` 只取第一个字面量。
    """
    lines = FORMULA.read_text(encoding="utf-8").splitlines()
    out: dict[str, list[tuple[str, int, str]]] = {}
    cur: list[str] = []
    cur_indent = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        m_in = _KIND_IN.search(line)
        m_eq = _KIND_EQ.search(line)
        if m_in or m_eq:
            cur = _QUOTED.findall(m_in.group(1)) if m_in else [m_eq.group(1)]
            cur_indent = indent
        elif cur and stripped and indent <= cur_indent:
            cur = []          #: 出块即复位（空行不复位，块内的空行不算出块）
        pairs = [(n, "note") for n in _NOTE.findall(line)] + [(n, "out") for n in _OUT.findall(line)]
        for name, how in pairs:
            if name in _NOT_A_LANDING:
                continue
            for k in cur:
                out.setdefault(k, [])
                if (name, i, how) not in out[k]:
                    out[k].append((name, i, how))
    return out


def _strip_go_comment(line: str) -> str:
    """剥掉 Go 行尾注释（`code //: 注释`），**引号内的 `//` 不算注释**。

    验收对账定位（`msg-mu8yghyg-fa`）：只跳整行注释会让**行尾注释里的词**混进词表
    （差 18 个词，如 `STUN`／`UNABLE_ACTION`／`vs`）。`1bd38acb` 的同族：**注释被当证据**。
    """
    out = []
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'`":
            quote = ch
            out.append(ch)
        elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def go_index(strip_comments: bool = True, exclude: frozenset = frozenset()) -> dict[str, list[tuple[str, int, str]]]:
    """Go 生产代码的词 → [(文件, 行, 原文行)]（排除 `*_test.go`、跳过整行注释）。

    `strip_comments=False` 保留行尾注释（v1 口径）——**只用于守卫里做两种口径对拍**，
    判决一律用 `True`。
    `exclude` ＝**本轮新增的文件**（相对仓库根的 posix 路径）——用于把「不含本轮新增」的
    读数与验收那一版对齐。★ 不加这一项就会**自指**：我本轮新写的 `rios-sim/mech/chain.go`
    里有 `json:"atk_scale"` 等标签，于是 `targets` 的「有落点」会有一条落在我自己刚写的文件上
    （同族 `35c2d66d` ②：文档里写名字去证明「它不在仓库里」⇒ grep 命中命令自己）。
    """
    idx: dict[str, list[tuple[str, int, str]]] = {}
    if not GO_ROOT.exists():
        return idx
    n_files = 0
    for p in sorted(GO_ROOT.rglob("*.go")):
        if p.name.endswith("_test.go"):
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel in exclude:
            continue
        n_files += 1
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.lstrip().startswith("//"):
                continue          #: ★ 整行注释不算落点
            body = _strip_go_comment(line) if strip_comments else line
            if not body.strip():
                continue
            for w in set(_WORD.findall(body)):
                idx.setdefault(w, []).append((rel, i, body.strip()[:110]))
    idx["__files__"] = [("", n_files, "")]      #: 索的非空性证据（守卫要用）
    return idx


def anchor_word(idx: dict) -> str:
    """控制组的锚**必须从索自身取**——不许拿「记忆里该存在」的名字当锚。

    2026-09-20 实测：第一版锚写死 `TakeDamage`，而 Go 侧根本没有这个名字 ⇒ 控制组红，
    红的是**锚**不是判据（同族 `557ee93b`「找不到先证明工具自己是活的」）。
    """
    best, n = "", 0
    for w, hits in idx.items():
        if w.startswith("__") or w in _GO_KEYWORDS or len(w) < 5:
            continue
        if len(hits) > n:
            best, n = w, len(hits)
    return best


def _same_source(kind: str, cand: str) -> bool:
    """cand 与 kind 名**同源**吗——判据：kind 名是 cand 的子串或与之相等。

    · `heal` ← `heal_scale` ✓ 同源（cand 名里带着 kind 名）
    · `regen` ← `heal_scale` ✗ **不同源** ⇒ 拿它去 Go 里找「regen 的落点」是**问错了名字**
      （2026-09-20 验收对账实测：Go 侧有 `RegenAura`/`regenPerSec`/`Farmland.RegenPerSecond`）。
    ★ 这条只判**名字的同源关系**，不判语义等价——语义那一步正是「待换尺子」要人去回答的。
    """
    return cand == kind or kind in cand


def hits_of(cands: list[tuple[str, int, str]], idx: dict) -> list[tuple[str, str, int, str]]:
    """命中清单：**按 `文件:行` 去重**。

    ★ 验收对账顶回的第一处（`msg-mu8ymgmc-ff`）：v2 曾把同一个 Go 行数了三遍——
    cand 抽取按 `formula.py` 行逐条出候选（`atk_scale＠1669·out`／`＠1670·out`／`＠1671·note`），
    命中表又按**候选项**展开 ⇒ 「处数」随 Python 侧抽取次数变化（0～N 倍）。
    **这与幽灵 kind 同源：都是按「抽取次数」计数，不是按「对象」计数。**
    修法＝同名 cand 先合并，命中行再按 `(文件, 行)` 去重。
    """
    out: list[tuple[str, str, int, str]] = []
    for name in dict.fromkeys(c for c, _l, _h in cands):
        seen: set[tuple[str, int]] = set()
        for rel, ln, text in idx.get(name, []):
            if (rel, ln) in seen:
                continue
            seen.add((rel, ln))
            out.append((name, rel, ln, text))
    return out


def state_of(kind: str, cands: list[tuple[str, int, str]], idx: dict) -> str:
    """四态判定（PM `msg-mu8yg0hb-f8` 裁定后的形状）。顺序即优先级。"""
    if hits_of(cands, idx):
        return "有落点"
    if not cands:
        return "未核"                      #: ① Python 侧就没有可抽的字段名
    if any(not _same_source(kind, c) for c, _l, _h in cands):
        return "待换尺子"                  #: ★ 新态：先换尺子，不是读 Go
    return "未核"                          #: ② 同源 cand、Go 生产代码 0 命中 ⇒ 读 Go 确认


def diagnostics(cands: list[tuple[str, int, str]], idx: dict) -> list[dict]:
    """**不计入态**的诊断：只看「同词不同大小写」与「蛇形→驼峰」。

    ★ 为什么要有这一列：Go 侧标识符是驼峰（`Heal`），而 Python 落点字段名是全小写
    （`heal_scale`）⇒ **大小写敏感的尺子会把「有」读成「未核」**。这条软处必须写在表里，
    否则下一个人会把『未核』读成『Go 侧没有』——那正是本表**不许**下的结论。
    """
    low = {w.lower(): (w, h) for w, h in idx.items() if not w.startswith("__")}
    out: list[dict] = []
    for name, _l, _h in cands:
        if name in idx:
            continue
        if name.lower() in low:
            w, h = low[name.lower()]
            out.append({"cand": name, "matched": w, "file": h[0][0], "line": h[0][1],
                        "text": h[0][2], "how": "同词不同大小写"})
            continue
        camel = "".join(p[:1].upper() + p[1:] for p in name.split("_") if p)
        if camel in idx:
            h = idx[camel]
            out.append({"cand": name, "matched": camel, "file": h[0][0], "line": h[0][1],
                        "text": h[0][2], "how": "蛇形→驼峰"})
    return out


REASON_NOCAND = "formula.py 里该 kind 没有可抽的落点字段名（`note()`／`out.` 都没出现）⇒ **这把尺子量不到**，不是「Go 侧没有」"
REASON_NOHIT = "同源 cand、Go 生产代码 0 命中 ⇒ 要读 Go 确认（grep 0 命中 ≠ 无落点）"
REASON_RENAME = "**cand 与 kind 名不同源** ⇒ 先回答「这个 kind 该抽哪个字段名」，不是去 Go 里找（换错名字 = 0 命中）"


def build(strip_comments: bool = True) -> dict:
    rules = kinds_and_rules()
    fields = landing_fields()
    idx = go_index(strip_comments=strip_comments)
    #: ★ 本轮新增的文件：把「不含本轮新增」的读数也算出来（与验收那一版对齐）
    idx_x = go_index(strip_comments=strip_comments, exclude=_NEW_THIS_ROUND)
    #: 共用 cand：同一个字段名被多个 kind 抽到（damage 与 ep_damage 共用 damage_type）
    used: dict[str, list[str]] = {}
    for k, cs in fields.items():
        for n, _l, _h in cs:
            used.setdefault(n, []).append(k)
    rows = []
    for kind in sorted(rules):
        cands = fields.get(kind, [])
        hits = hits_of(cands, idx)
        state = state_of(kind, cands, idx)
        rows.append({
            "kind": kind, "rules": sorted(rules[kind]),
            "cands": [{"name": n, "line": l, "how": h,
                       "same_source": _same_source(kind, n),
                       "shared_with": sorted(set(used.get(n, [])) - {kind})} for n, l, h in cands],
            "state": state,
            "reason": {"未核": REASON_NOCAND if not cands else REASON_NOHIT,
                       "待换尺子": REASON_RENAME}.get(state, ""),
            "generic": sorted({c for c, _l, _h in cands if c in _GENERIC}),
            "diag": diagnostics(cands, idx),
            "hits": [{"cand": c, "file": f, "line": l, "text": t} for c, f, l, t in hits],
        })
    landed = [r for r in rows if r["state"] == "有落点"]
    distinct = sorted({h["cand"] for r in landed for h in r["hits"]})
    #: ★ 两个 scope 分开（`6dd6739c`：两套分母不许并列）
    shared_landed = sorted({h["cand"] for r in landed for h in r["hits"]
                            if len(set(used.get(h["cand"], []))) > 1})
    shared_all = sorted(n for n, ks in used.items() if len(set(ks)) > 1)
    by_cand_lines: dict[str, set[tuple[str, int]]] = {}
    for r in landed:
        for h in r["hits"]:
            by_cand_lines.setdefault(h["cand"], set()).add((h["file"], h["line"]))
    #: 不含本轮新增文件的命中处数（逐 cand）
    by_cand_lines_x: dict[str, set[tuple[str, int]]] = {}
    #: ★ 验收建议（`msg-mu8zxdwu-fo`）：**把被排除的文件清单印出来，连它们贡献了哪几处一起**。
    #: 理由：只印树 HEAD 拦不住这件事——下一个人看到 12 与 6 两个数时，
    #: 不知道差的是**哪几个文件**；印清单就等于把分母消掉。
    excluded_by_cand: dict[str, set[tuple[str, int]]] = {}
    for r in landed:
        for name, rel, ln, _t in hits_of(fields.get(r["kind"], []), idx):
            if rel in _NEW_THIS_ROUND:
                excluded_by_cand.setdefault(name, set()).add((rel, ln))
    for r in landed:
        for name, rel, ln, _t in hits_of(fields.get(r["kind"], []), idx_x):
            by_cand_lines_x.setdefault(name, set()).add((rel, ln))
    return {"rows": rows, "go_words": len(idx) - 1,
            "go_files": idx.get("__files__", [("", 0, "")])[0][1],
            "go_words_x": len(idx_x) - 1,
            "go_files_x": idx_x.get("__files__", [("", 0, "")])[0][1],
            "new_files": sorted(_NEW_THIS_ROUND),
            "excluded_by_cand": {c: sorted(v) for c, v in sorted(excluded_by_cand.items())},
            "distinct_cands": distinct, "shared_cands": shared_landed,
            "shared_cands_all": shared_all, "used": {n: sorted(set(k)) for n, k in used.items()},
            "hit_lines_by_cand": {c: len(v) for c, v in sorted(by_cand_lines.items())},
            "hit_lines_by_cand_x": {c: len(v) for c, v in sorted(by_cand_lines_x.items())}}


def check() -> int:
    """反向守卫：四条，任一不成立即 rc=1。"""
    rules = kinds_and_rules()
    fields = landing_fields()
    idx = go_index(strip_comments=True)
    rows = {r["kind"]: r for r in build()["rows"]}
    ok = True

    print("  ① 敏感性：找一个已知『有落点』的 kind 来破坏")
    landed = [k for k, r in rows.items() if r["state"] == "有落点"]
    if not landed:
        print("     ✗ 没有任何 kind 判『有落点』 ⇒ 这条守卫**无处行使**（不是通过）")
        ok = False
    else:
        victim = landed[0]
        state = state_of(victim, [], idx)
        print(f"     取 `{victim}`，候选名人为清空 ⇒ 判定 `{state}`（应为『未核』）")
        if state != "未核":
            print("     ✗ 清空候选后仍不是『未核』 ⇒ 判据红不起来")
            ok = False
        else:
            print("     ✓ 能红")

    print("  ② 控制组：锚**从索自身取**（不许用「记忆里该存在」的名字）")
    n_files = idx.get("__files__", [("", 0, "")])[0][1]
    anchor = anchor_word(idx)
    print(f"     Go 生产代码 {n_files} 个 .go、{len(idx) - 1} 个词；取命中最多的 `{anchor}` 当锚")
    if n_files < 5 or not anchor:
        print("     ✗ 索太空/取不到锚 ⇒ 『未核』不值得信（不是通过）")
        ok = False
    else:
        state = state_of("__synth__", [(anchor, 0, "note")], idx)
        hits = hits_of([(anchor, 0, "note")], idx)
        print(f"     ⇒ `{state}`，命中 {len(hits)} 处；首处={hits[0][1]}:{hits[0][2]}")
        if state != "有落点":
            print("     ✗ 控制组没绿 ⇒ 判据（或 Go 索引）坏了")
            ok = False
        else:
            print("     ✓ 控制组绿")

    print("  ③ 两种注释口径逐行对拍：行尾注释剥/不剥，态必须逐行相同")
    idx_keep = go_index(strip_comments=False)
    diff = []
    for kind in sorted(rules):
        cs = fields.get(kind, [])
        if state_of(kind, cs, idx) != state_of(kind, cs, idx_keep):
            diff.append(kind)
    print(f"     词表：剥={len(idx) - 1}／不剥={len(idx_keep) - 1}；态不同的 kind={diff or '无'}")
    if diff:
        print("     ✗ 判决受注释口径影响 ⇒ 必须先说清用哪种口径")
        ok = False
    else:
        print("     ✓ 逐行判决不变")

    print("  ④ 新态可行使：`regen` 必须落在『待换尺子』")
    got = state_of("regen", fields.get("regen", []), idx)
    print(f"     `regen` ⇒ `{got}`（cand={[c for c, _l, _h in fields.get('regen', [])]}）")
    if got != "待换尺子":
        print("     ✗ 新档是空架子（落错档）⇒ 这一档不能算数")
        ok = False
    else:
        print("     ✓ 新档可行使")

    print(f"  ⇒ 反向守卫{'通过' if ok else '失败'}（rc={0 if ok else 1}）")
    return 0 if ok else 1


def md(d: dict) -> str:
    rows = d["rows"]
    st = {s: [r for r in rows if r["state"] == s] for s in ("有落点", "待换尺子", "未核")}
    n_nocand = sum(1 for r in st["未核"] if not r["cands"])
    n_nohit = sum(1 for r in st["未核"] if r["cands"])
    hub = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip() or "未知"
    L: list[str] = []
    L.append("# kind ↔ Go 落点 映射表（C 档乙·第二版）")
    L.append("")
    L.append(f"> **生成物，不许手改**：由 `tools/kind_mech_map.py` 生成（`--md`）。生成时所在树 HEAD=`{hub}`。")
    L.append("> **表不问「该不该建模」**——它只记「谁对应谁」；判据（先写后跑）见该文件头部。")
    L.append("> **本版改动**（PM `msg-mu8yg0hb-f8` ＋ 验收对账）：新增第四态「待换尺子」（`regen` 改判）；"
             "M 列增「抽取方式」并加「逐格交代」节；「有落点」按 kind／distinct cand 两个口径分列；"
             "`go_index()` 剥掉**行尾注释**（词表 1508 → 1490）。")
    L.append("")
    L.append(f"左列＝`ak_tactic/formula.py` 的 `RULES` 里 `kind` 的**确切字面值**（共 **{len(rows)} 种**）；"
             f"M 列＝该 kind 在 Python 落点写出的**字段名**（带行号与抽取方式）；"
             f"R 列＝Go 生产代码 {d['go_files']} 个 `.go`（排除 `*_test.go`、剥掉整行与行尾注释，"
             f"词表 {d['go_words']} 个）里的整词命中。")
    L.append("")
    L.append("## 计数（**五个数各自独立，不许相加成一个数，也不许跨行并列**）")
    L.append("")
    L.append(f"| 口径 | 数 | 说明 |")
    L.append(f"| --- | --- | --- |")
    L.append(f"| 有落点（**kind 计数**） | **{len(st['有落点'])}** | "
             f"{'、'.join('`' + r['kind'] + '`' for r in st['有落点'])} |")
    L.append(f"| 有落点（**distinct cand 字段**） | **{len(d['distinct_cands'])}** | "
             f"{'、'.join('`' + c + '`' for c in d['distinct_cands'])} —— 口径＝**所有产生命中的 cand 名去重** |")
    L.append(f"| 去重后**命中处数**（按 `文件:行` 去重） | "
             f"**{sum(d['hit_lines_by_cand'].values())}** | "
             + "、".join(f"`{c}` {n} 处" for c, n in d['hit_lines_by_cand'].items())
             + " —— ★ 与上面两行**不是同一口径**：这行数的是 Go 侧的**行** |")
    L.append(f"| 　└ **不含本轮新增文件**（＝**下面「本轮新增文件清单」里的那些**） | "
             f"**{sum(d['hit_lines_by_cand_x'].values())}** | "
             + "、".join(f"`{c}` {n} 处" for c, n in d['hit_lines_by_cand_x'].items())
             + " —— ★ **这一行才与验收那一版可比**（它量时那种文件还不存在）；"
               "**「排除清单」在下面单独一节，连首次入库 sha 与时间一起印** |")
    L.append(f"| 共用字段（**只在「有落点」范围内**） | **{len(d['shared_cands'])}** | "
             f"{'、'.join('`' + c + '`' for c in d['shared_cands']) or '—'} |")
    L.append(f"| 共用字段（**全表范围**） | **{len(d['shared_cands_all'])}** | "
             f"{'、'.join('`' + c + '`' for c in d['shared_cands_all']) or '—'} —— "
             f"★ 多出的 `heal_scale`（`heal`／`regen`）不在有落点范围内，"
             f"**而它正是 `regen` 那格缺陷的本体** |")
    L.append("")
    L.append("### 本轮新增文件清单（**「不含本轮新增」那一列的口径来源**）")
    L.append("")
    L.append(f"划界规则：**{_NEW_THIS_ROUND_RULE}**。★ 为什么必须印这一节（PM `msg-mu8zychr-fp` "
             "把验收的建议升格为硬要求）：**「本轮」是随时间漂移的词**——同一个 `6`，"
             "在这一轮与下一轮的意思不同（下一轮若又新增了带 `json:\"atk_scale\"` 的文件，`6` 就变了）。"
             "**只印 `6`，读者无法判断它是否可比；印出清单，`6` 才有身份**（同族 `515530a8`："
             "表的身份先于数值）。")
    L.append("")
    L.append("| 路径 | 首次入库 sha | 入库时间 |")
    L.append("| --- | --- | --- |")
    for rel, sha, when in new_file_provenance():
        L.append(f"| `{rel}` | `{sha}` | {when} |")
    L.append("")
    L.append("★ **被排除的命中处**（现算，故行号会随该文件改动而漂移——**这正是不能写死行号的理由**；"
             "验收 07:05 独立算的是 `atk_scale` ← `chain.go:34,70`、`max_target` ← `:33,67,111,114`，"
             "**本轮重生成后行号已经变了**，因为我随后又改过那个文件）：")
    L.append("")
    L.append("| cand | 被排除的 `文件:行` |")
    L.append("| --- | --- |")
    for cand, locs in d["excluded_by_cand"].items():
        L.append(f"| `{cand}` | " + "、".join(f"`{f}:{n}`" for f, n in locs) + " |")
    L.append("")
    L.append("★ **四个量分开写，因为它们回答的是四个不同的问题**（`6dd6739c`／`fd544d68`）："
             "kind 计数（几个**机制种类**有落点）／distinct 字段（几个**字段名**命中）／"
             "共用字段（一个字段名被几个 kind 抽到）／命中处数（Go 侧几个**行**命中）。"
             "**跨行不可比、不许相加。**")
    L.append("")
    L.append("★ **「净字段 2 vs 3」这一场争议的结论是两边各错一半——并且它的署名要写三方槽**"
             "（对账 `msg-mu8xg2iz-f4`／`msg-mu8ymgmc-ff`／署名更正 `msg-mu8zychr-fp`）："
             "**① 归因源头＝PM 的广播推断**（它从我的汇报里推出「v1 主表把 `atk_scale` 藏了」，"
             "**且当时没标『这是我推的』**）；**② 写入产物＝我**（把这句推断当结论写进了 v2 表）；"
             "**③ 引用方＝验收**（它按产物署名归给了我，并在对账里查明源头另有其人）。"
             "★ 通则：**「产物里写着」与「这是谁说的」是两个槽**。"
             "**另外两边各错一半**：验收量到 2，是它自己打印时 `hits[:3]` 截掉了排第 4 的 `atk_scale`"
             "（**与我的主表显示无关**——这一点是它自己查出来并自纠的）；而我的**命中处数**把同一个 Go 行"
             "数了三遍（按**抽取次数**计数，不是按**对象**计数，**与幽灵 kind 同源**）。"
             "**现在的口径**：处数按 `文件:行` 去重，`atk_scale` **1 处**／`max_target` **1 处**／"
             "`damage_type` **4 处**。")
    L.append(f"| 待换尺子 | **{len(st['待换尺子'])}** | cand 与 kind 名不同源 ⇒ 先换尺子 |")
    L.append(f"| 未核·**Python 侧无可抽字段名** | **{n_nocand}** | 这把尺子量不到，不是「Go 侧没有」 |")
    L.append(f"| 未核·**同源 cand 但 Go 0 命中** | **{n_nohit}** | 要读 Go 确认 |")
    L.append(f"| 无落点 | **0** | **本轮一格不填**：要逐条读 Go ＋ 写明取证范围 |")
    L.append("")
    L.append("## 主表")
    L.append("")
    L.append("| kind（确切名字） | 规则条数 | Python 落点 cand（名字＠行·抽取方式） | 同源? | Go 侧机制标识 | 态 |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for r in rows:
        cands = "、".join(f"`{c['name']}`＠{c['line']}·{c['how']}" for c in r["cands"]) or "—"
        if not r["cands"]:
            same = "—"
        elif r["state"] == "有落点":
            same = "（不适用：已命中）"
        else:
            same = "✓" if all(c["same_source"] for c in r["cands"]) else "**✗**"
        if r["state"] == "有落点":
            by_cand: dict[str, list[dict]] = {}
            for h in r["hits"]:
                by_cand.setdefault(h["cand"], []).append(h)
            cells = []
            for cand, hs in by_cand.items():
                mark = "⚠通用词 " if cand in _GENERIC else ""
                sw = next((c["shared_with"] for c in r["cands"]
                           if c["name"] == cand and c["shared_with"]), [])
                tag = ("（与 " + "、".join("`" + s + "`" for s in sw)
                       + " 共用 ⇒ **归属未核**）") if sw else ""
                #: ★ 本轮新增的文件排在后面并标出来，否则读表的人会以为落点在引擎里
                hs = sorted(hs, key=lambda h: (h["file"] in _NEW_THIS_ROUND, h["file"], h["line"]))
                locs = []
                for h in hs[:2]:
                    nf = "（**本轮新增**）" if h["file"] in _NEW_THIS_ROUND else ""
                    locs.append(f"`{h['file']}:{h['line']}`{nf}")
                cells.append(f"{mark}`{cand}`（{len(hs)} 处）→ " + "、".join(locs) + tag)
            go = "<br>".join(cells)
        elif r["state"] == "待换尺子" and r["diag"]:
            go = "**先换尺子**（0 命中）"
        elif r["diag"]:
            d0 = r["diag"][0]
            go = (f"⚠ 同词不同大小写命中（**诊断，不计入态**）：`{d0['matched']}` @ `{d0['file']}:{d0['line']}`"
                  + (f"（另 {len(r['diag']) - 1} 条）" if len(r["diag"]) > 1 else ""))
        else:
            go = "—"
        L.append(f"| `{r['kind']}` | {len(r['rules'])} | {cands} | {same} | {go} | **{r['state']}** |")
    L.append("")
    L.append("## 逐格交代：20 格「未核／待换尺子」的 cand 给的是什么、凭什么")
    L.append("")
    L.append("| kind | cand | 凭什么（`formula.py` 行·抽取方式） | 同源? | 与谁共用 | 态 |")
    L.append("| --- | --- | --- | --- | --- | --- |")
    for r in rows:
        if r["state"] not in ("未核", "待换尺子"):
            continue
        if not r["cands"]:
            L.append(f"| `{r['kind']}` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **{r['state']}** |")
            continue
        for c in r["cands"]:
            shared = "、".join("`" + s + "`" for s in c["shared_with"]) or "—"
            L.append(f"| `{r['kind']}` | `{c['name']}` | `formula.py:{c['line']}`·`{c['how']}` | "
                     f"{'✓' if c['same_source'] else '**✗**'} | {shared} | **{r['state']}** |")
    L.append("")
    L.append("★ 每格都能**报出自己来自哪一块、哪一行**（PM 对「串块」那条的判据）——报不出来就是解析器串了块。")
    L.append("")
    L.append("## 共用 cand（一个字段名被多个 kind 抽到）——**这类缺陷的探测器**")
    L.append("")
    L.append("★ 验收对账的原话：**「共用表不是附注，是这类缺陷的探测器」**——"
             "若共用表一开始就列 `heal_scale`，`regen → heal_scale` 那格**当场显形**。"
             "所以本节**按 cand 去重、每行一个 cand**（v2 曾把 `damage_type` 印两遍、且漏了 `heal_scale`）。")
    L.append("")
    L.append("| cand | 被哪些 kind 抽到 | 其中有落点? | 与「待换尺子」的关系 |")
    L.append("| --- | --- | --- | --- |")
    swap = {r["kind"] for r in rows if r["state"] == "待换尺子"}
    for cand in d["shared_cands_all"]:
        kinds = d["used"].get(cand, [])
        landed_kinds = [r["kind"] for r in st["有落点"] if any(c["name"] == cand for c in r["cands"])]
        rel = ("★ **就是 `" + "`／`".join(sorted(k for k in kinds if k in swap))
               + "` 那格的 cand**：它抽到这个名字，而 Go 侧落点叫别的名字") if any(k in swap for k in kinds) else "—"
        L.append(f"| `{cand}` | {'、'.join('`' + k + '`' for k in kinds)} | "
                 f"{'、'.join('`' + k + '`' for k in landed_kinds) or '都不是'} | {rel} |")
    L.append("")
    L.append("★ **归属未核**：`ep_damage` 现在这一态是**靠共用 cand `damage_type` 撑起来的**——"
             "「一个字段名同时清两个键」是 `180eab0c` 的同族问题，**`damage_type` 是不是 ep 的落点，"
             "本表不当既成事实**：要么补证据，要么标未核。**本轮标未核。**")
    L.append("")
    L.append("## 脚注：四态各是怎么定出来的")
    L.append("")
    L.append("* **有落点（机械命中）**＝cand 在 Go 生产代码里整词命中。**命中数会被通用词骗**，"
             "所以带 ⚠ 标记**并把原文行一并交出**——判读材料与数字同权。")
    L.append(f"* **待换尺子**＝0 命中 且 **cand 与 kind 名不同源**。理由写死：{REASON_RENAME}")
    L.append(f"* **未核②**＝0 命中 且 cand 与 kind 名同源。理由写死：{REASON_NOHIT}")
    L.append(f"* **未核①**＝Python 侧抽不到字段名。理由写死：{REASON_NOCAND}")
    L.append("* **无落点：本轮一个都不填。** 它要「逐条读过 Go 侧＋写明取证范围」才算（`fac4b7de`）；"
             "**不许由 0 命中推出**——Go 里换个名字就 grep 不到（`7f782586`、`1865d35a`）。")
    L.append("")
    L.append("### 两处软处（写在表里，不许只写在脑子里）")
    L.append("")
    L.append("1. **通用词命中**：cand 若是不含 `_` 的短英文名（`damage`／`control`／`heal`…），命中**可能来自别处的同名词**。")
    L.append("2. **大小写尺子**：本表按**整词、大小写敏感**匹配，而 Go 标识符是驼峰、Python 落点字段名是全小写 ⇒ "
             "**大小写差异会把「有」读成「未核」**。这类行在右列写 `⚠ 同词不同大小写命中（诊断，不计入态）`。")
    L.append("3. **注释口径（v2 修）**：只跳整行注释会让**行尾注释里的词**混进词表（实测差 18 个词，"
             "如 `STUN`／`UNABLE_ACTION`／`vs`）。v2 剥掉行尾注释（引号内的 `//` 不算注释），"
             "并在守卫里断言**两种口径下 23 行态逐行相同**。")
    L.append("")
    L.append("## 附：有落点各条的原文行（判读材料）")
    L.append("")
    for r in rows:
        if r["state"] != "有落点":
            continue
        L.append(f"### `{r['kind']}`")
        for h in r["hits"][:6]:
            L.append(f"* `{h['cand']}` @ `{h['file']}:{h['line']}`")
            L.append(f"  ```go\n  {h['text']}\n  ```")
        L.append("")
    L.append("## 附：反向守卫（`python tools/kind_mech_map.py --check`）")
    L.append("")
    L.append("① **敏感性**：取一个已判『有落点』的 kind，把候选名人为清空 ⇒ 必须变『未核』；"
             "② **控制组**：锚从索自身取 ⇒ 必须判『有落点』；"
             "③ **两种注释口径逐行相同**；④ **新态可行使**（`regen` 必须落在『待换尺子』）。"
             "任一条不成立即 rc=1。")
    L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", help="表写到这个文件")
    ap.add_argument("--json", help="原始数据写到这个文件")
    ap.add_argument("--check", action="store_true", help="跑反向守卫")
    a = ap.parse_args()
    if a.check:
        return check()
    d = build()
    rows = d["rows"]
    n_land = sum(1 for r in rows if r["state"] == "有落点")
    n_swap = sum(1 for r in rows if r["state"] == "待换尺子")
    n_nocand = sum(1 for r in rows if r["state"] == "未核" and not r["cands"])
    n_nohit = sum(1 for r in rows if r["state"] == "未核" and r["cands"])
    print(f"  kind 共 {len(rows)} 种；有落点 **{n_land}** 种（**净落点字段 {len(d['distinct_cands'])}**："
          f"{'、'.join(d['distinct_cands'])}）；无落点 0 种（本轮不填）")
    print(f"  待换尺子 **{n_swap}** 种：{[r['kind'] for r in rows if r['state'] == '待换尺子']}")
    print(f"  未核 **{n_nocand + n_nohit}** 种，两种来源分开报："
          f"①Python 侧无可抽字段名 **{n_nocand}** ／ ②同源 cand 但 Go 0 命中 **{n_nohit}**")
    print(f"  Go 生产代码 .go 文件 {d['go_files']} 个、词表 {d['go_words']} 个（已剥行尾注释）")
    if a.md:
        Path(a.md).write_text(md(d), encoding="utf-8")
        print(f"  表已写：{a.md}")
    if a.json:
        Path(a.json).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  数据已写：{a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
