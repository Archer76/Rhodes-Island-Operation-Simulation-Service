#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""kind ↔ Go 落点 映射表（C 档乙，第一版）。

**这是「谁对应谁」的表，不是「该不该建模」的判断**（PM msg-mu8x8xvt-ex 第 3 条）。

════════════════════════════════════════════════════════════════════════
判据（**先写后跑**，2026-09-20 预注册；跑之前没有看过任何一行的结果）
════════════════════════════════════════════════════════════════════════
L 列（机制种类）：`ak_tactic/formula.py` 的 `RULES[*].kind` 的**确切字面值**。
    身份＝代码本身（跑起来 import 出来的值），不是中文机制名、不是我的概念。
M 列（Python 落点写出的字段名）：从 formula.py 里 `t.kind` 分支块中**机械抽取**
    `note("名字")` 的第一个实参与 `out.<名字>`；每条都带**行号**（可复核到原文行）。
R 列（Go 侧机制标识）三态，机械判据：
    · **有落点**：M 列任一候选名在 `rios-sim/**/*.go`（**排除 `*_test.go`**、跳过整行注释）
      里以**整词**命中 ⇒ 记为「有落点（机械命中）」，并列出 `文件:行` 与**原文行**。
      ★ 附原文行是必须的：命中会被通用词骗（`60b84b37`），所以把判读材料一起交出去。
    · **未核**：0 命中 ⇒ **一律未核**，理由写死「Go 生产代码里未命中；未逐条读语义
      （grep 0 命中 ≠ 无落点，同族 `7f782586`／`1865d35a`）」。
    · **无落点**：本轮**一律不填**。它需要「逐条读过 Go 侧 + 写明取证范围」才算
      （`fac4b7de`：全称量词要么有穷举证据要么不写）。留给下一步，不许由 0 命中推出。

反向守卫（`--check`，必须能红）：
    ① 敏感性：把一个**已知有落点**的 kind 的候选名人为清空 ⇒ 它必须变成「未核」；
    ② 控制组：一个候选名取 `TakeDamage`（Go 里确定存在）的合成 kind ⇒ 必须判「有落点」。
    两条任一不成立 ⇒ 打印失败原因并 `rc=1`。

用法：
    python tools/kind_mech_map.py --md docs/kind-mech-map.md   # 出表
    python tools/kind_mech_map.py --check                      # 反向守卫
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

_KIND_LINE = re.compile(r"""t\.kind\s*(?:==|in)\s*(.+?):""")
_NOTE = re.compile(r"""note\(\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_OUT = re.compile(r"""\bout\.([A-Za-z_][A-Za-z0-9_]*)""")
_WORD = re.compile(r"""[A-Za-z_][A-Za-z0-9_]*""")


def kinds_and_rules() -> dict[str, list[str]]:
    """L 列：kind → 规则名清单（身份＝跑起来的 `RULES`，不是抄文档）。"""
    sys.path.insert(0, str(ROOT))
    from ak_tactic import formula as F

    out: dict[str, list[str]] = {}
    for r in F.RULES:
        out.setdefault(r.kind, []).append(r.name)
    return out


def landing_fields() -> dict[str, list[tuple[str, int]]]:
    """M 列：kind → [(字段名, formula.py 行号)]，机械抽取，带行号。

    ★ 第一版**串了块**：`cur` 一直保留到文件末尾，于是 `control` 那一行里混进了 1800 行以后
    的 `append`／`true_damage`（实测被 `append` 这个 Go 内建名骗成「有落点」）。
    修法＝记住 kind 行自身的缩进，**缩进回到该层且本行不是 kind 行就复位**。
    """
    lines = FORMULA.read_text(encoding="utf-8").splitlines()
    out: dict[str, list[tuple[str, int]]] = {}
    cur: list[str] = []
    cur_indent = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        m = _KIND_LINE.search(line)
        if m:
            cur = re.findall(r"""["']([A-Za-z_][A-Za-z0-9_]*)["']""", m.group(1))
            cur_indent = indent
        elif cur and stripped and indent <= cur_indent:
            cur = []          #: 出块即复位（空行不复位，块内的空行不算出块）
        for name in list(_NOTE.findall(line)) + list(_OUT.findall(line)):
            if name in _NOT_A_LANDING:
                continue
            for k in cur:
                out.setdefault(k, [])
                if (name, i) not in out[k]:
                    out[k].append((name, i))
    return out


#: 这些名字**不是落点**：Go/Python 内建或纯占位（实测 `append` 会把 `control` 骗成「有落点」）
_NOT_A_LANDING = frozenset("append other value len make range min max sum print".split())


def go_index() -> dict[str, list[tuple[str, int, str]]]:
    """Go 生产代码的词 → [(文件, 行, 原文行)]（排除 `*_test.go`，跳过整行注释）。"""
    idx: dict[str, list[tuple[str, int, str]]] = {}
    if not GO_ROOT.exists():
        return idx
    n_files = 0
    for p in sorted(GO_ROOT.rglob("*.go")):
        if p.name.endswith("_test.go"):
            continue
        n_files += 1
        rel = p.relative_to(ROOT).as_posix()
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.lstrip().startswith("//"):
                continue          #: ★ 注释不算落点（`1bd38acb`：注释被当证据会让结论反转）
            for w in set(_WORD.findall(line)):
                idx.setdefault(w, []).append((rel, i, line.strip()[:110]))
    idx["__files__"] = [("", n_files, "")]      #: 索的非空性证据（守卫要用）
    return idx


def anchor_word(idx: dict) -> str:
    """控制组的锚**必须从索自身取**——不许拿"记忆里该存在"的名字当锚。

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


_GO_KEYWORDS = frozenset("""func return struct interface package import range string int
bool error make append len nil true false type var const for if else switch case default
byte rune uint64 int64 uint32 int32 float64 float32 defer go chan map""".split())

#: 疑似通用词：没有 `_` 的短英文名。命中了也**要单独标出来**——通用词命中会被当落点
#: （`60b84b37`：判「有消费点」要摆原文行；命中数会被通用词骗）。
_GENERIC = frozenset("""damage heal buff debuff control cost sp flag range prob pen shield
dodge regen count targets summon trait duration value time""".split())


def verdict(kind: str, cands: list[tuple[str, int]], idx: dict, override: dict | None = None):
    """三态判定。返回 (状态, 命中清单)。"""
    names = [c for c, _l in (override.get(kind, cands) if override else cands)]
    hits: list[tuple[str, str, int, str]] = []
    for name in dict.fromkeys(names):
        for rel, ln, text in idx.get(name, [])[:3]:
            hits.append((name, rel, ln, text))
    if hits:
        return "有落点", hits
    return "未核", []


def diagnostics(cands: list[tuple[str, int]], idx: dict) -> list[dict]:
    """**不计入态**的诊断：只看「同词不同大小写」与「作为词的一部分」。

    ★ 为什么要有这一列：Go 侧标识符是驼峰（`Heal`），而 Python 落点字段名是全小写
    （`heal_scale`）⇒ **大小写敏感的尺子会把「有」读成「未核」**。这条软处必须写在表里，
    否则下一个人会把『未核』读成『Go 侧没有』——那正是本表**不许**下的结论。
    """
    low = {w.lower(): (w, h) for w, h in idx.items() if not w.startswith("__")}
    out: list[dict] = []
    for name, _l in cands:
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


REASON_NOCAND = "formula.py 里该 kind 没有可抽的落点字段名（`note()`/`out.` 都没出现）"
REASON_NOHIT = ("Go 生产代码里未命中；未逐条读语义（grep 0 命中 ≠ 无落点，同族 7f782586／1865d35a）")


def build() -> dict:
    rules = kinds_and_rules()
    fields = landing_fields()
    idx = go_index()
    rows = []
    for kind in sorted(rules):
        cands = fields.get(kind, [])
        state, hits = verdict(kind, cands, idx)
        rows.append({
            "kind": kind, "rules": sorted(rules[kind]),
            "cands": [{"name": n, "line": l} for n, l in cands],
            "state": state,
            "reason": "" if cands else REASON_NOCAND,
            "generic": sorted({c for c, _l in cands if c in _GENERIC}),
            "diag": diagnostics(cands, idx),
            "hits": [{"cand": c, "file": f, "line": l, "text": t} for c, f, l, t in hits],
        })
    return {"rows": rows, "go_words": len(idx) - 1,
            "go_files": idx.get("__files__", [("", 0, "")])[0][1]}


def check() -> int:
    """反向守卫：敏感性 + 控制组，任一不成立即 rc=1。"""
    rules = kinds_and_rules()
    fields = landing_fields()
    idx = go_index()
    rows = {r["kind"]: r for r in build()["rows"]}
    ok = True

    landed = [k for k, r in rows.items() if r["state"] == "有落点"]
    print(f"  ① 敏感性：找一个已知『有落点』的 kind 来破坏——候选 {len(landed)} 个")
    if not landed:
        print("     ✗ 没有任何 kind 判『有落点』 ⇒ 这条守卫**无处行使**（不是通过）")
        ok = False
    else:
        victim = landed[0]
        state, _ = verdict(victim, fields.get(victim, []), idx, override={victim: []})
        print(f"     取 `{victim}`，把它的候选名人为清空 ⇒ 判定变成 `{state}`"
              f"（应为『未核』）")
        if state != "未核":
            print("     ✗ 清空候选后仍然不是『未核』 ⇒ 判据红不起来")
            ok = False
        else:
            print("     ✓ 能红")

    print("  ② 控制组：锚**从索自身取**（不许用「记忆里该存在」的名字——第一版锚定了 Go 里不存在的名字，红的是锚不是判据）")
    n_files = len(idx.get("__files__", [])) and idx["__files__"][0][1] or 0
    anchor = anchor_word(idx)
    print(f"     Go 生产代码：{n_files} 个 .go 文件、{len(idx) - 1} 个词；取命中最多的词 `{anchor}` 当锚"
          f"（{len(idx.get(anchor, []))} 处）")
    if n_files < 5 or not anchor:
        print("     ✗ 索太空/取不到锚 ⇒ 判据的『未核』不值得信（这不是通过）")
        ok = False
    else:
        state, hits = verdict("__synth__", [(anchor, 0)], idx)
        first = f"{hits[0][1]}:{hits[0][2]}" if hits else "—"
        text = hits[0][3][:60] if hits else ""
        print(f"     ⇒ 判定 `{state}`，命中 {len(hits)} 处；首处={first} {text}")
        if state != "有落点":
            print("     ✗ 控制组没绿 ⇒ 判据（或 Go 索引）坏了")
            ok = False
        else:
            print("     ✓ 控制组绿")

    print(f"  ⇒ 反向守卫{'通过' if ok else '失败'}（rc={0 if ok else 1}）")
    return 0 if ok else 1


def md(d: dict) -> str:
    rows = d["rows"]
    n_land = sum(1 for r in rows if r["state"] == "有落点")
    n_nocand = sum(1 for r in rows if r["state"] == "未核" and not r["cands"])
    n_nohit = sum(1 for r in rows if r["state"] == "未核" and r["cands"])
    hub = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip() or "未知"
    L = []
    L.append("# kind ↔ Go 落点 映射表（C 档乙·第一版）")
    L.append("")
    L.append(f"> **生成物，不许手改**：由 `tools/kind_mech_map.py` 生成（`--md`）。"
             f"生成时所在树 HEAD=`{hub}`。")
    L.append("> **表不问「该不该建模」**——它只记「谁对应谁」；判据（先写后跑）见该文件头部与下表脚注。")
    L.append("")
    L.append(f"左列＝`ak_tactic/formula.py` 的 `RULES` 里 `kind` 的**确切字面值**；"
             f"共 **{len(rows)} 种 kind**。中列＝该 kind 在 Python 落点里写出的**字段名**（带行号，可复核到原文行）。"
             f"右列＝Go 侧机制标识，三态。Go 侧索＝`rios-sim/**/*.go` 生产文件 **{d['go_files']}** 个"
             f"（排除 `*_test.go`、跳过整行注释），词表 {d['go_words']} 个。")
    L.append("")
    L.append(f"**计数（四种来源各自独立，不许相加成一个数）**：有落点 **{n_land}** 种 ／ "
             f"未核·**Python 侧无可抽字段名** **{n_nocand}** 种 ／ "
             f"未核·**有字段名但 Go 0 命中** **{n_nohit}** 种 ／ 无落点 **0** 种（本轮**不填**，见脚注）。")
    L.append("")
    L.append("| kind（确切名字） | 规则条数 | Python 落点字段名（行号） | Go 侧机制标识 | 态 |")
    L.append("| --- | --- | --- | --- | --- |")
    for r in rows:
        cands = "、".join(f"`{c['name']}`({c['line']})" for c in r["cands"]) or "—"
        if r["state"] == "有落点":
            cells = []
            for h in r["hits"][:2]:
                mark = "⚠通用词 " if h["cand"] in _GENERIC else ""
                cells.append(f"{mark}`{h['cand']}` → `{h['file']}:{h['line']}`")
            go = "<br>".join(cells) + (f"（另有 {len(r['hits']) - 2} 处）" if len(r["hits"]) > 2 else "")
        else:
            go = "—"
            if r["diag"]:
                d0 = r["diag"][0]
                go = (f"⚠ 同词不同大小写命中（**诊断，不计入态**）："
                      f"`{d0['matched']}` @ `{d0['file']}:{d0['line']}`"
                      + (f"（另 {len(r['diag']) - 1} 条）" if len(r["diag"]) > 1 else ""))
        L.append(f"| `{r['kind']}` | {len(r['rules'])} | {cands} | {go} | **{r['state']}** |")
    L.append("")
    L.append("## 脚注：三态各是怎么定出来的")
    L.append("")
    L.append("* **有落点（机械命中）**＝中列任一字段名在 `rios-sim/**/*.go`（**排除 `*_test.go`**、跳过整行注释）里以整词命中。"
             "**命中数会被通用词骗**，所以下表把**原文行**一并交出，判读材料与数字同权。")
    L.append(f"* **未核**＝0 命中。理由写死：{REASON_NOHIT}")
    L.append("* **两处软处（写在表里，不许只写在脑子里）**：")
    L.append("  1. **通用词命中**：候选名若是不含 `_` 的短英文名（`damage`／`control`／`heal`…），"
             "命中**可能来自别处的同名词**。表里带 ⚠ 标记，**并且把原文行一并交出**，判读材料与数字同权。")
    L.append("  2. **大小写尺子**：本表按**整词、大小写敏感**匹配，而 Go 侧标识符是驼峰（`Heal`）、"
             "Python 落点字段名是全小写（`heal_scale`）⇒ **大小写差异会把「有」读成「未核」**。"
             "有这类情况的行在右列写 `⚠ 同词不同大小写命中（诊断，不计入态）`——"
             "**它不改变态**，只是防止下一个人把『未核』读成『Go 侧没有』。")
    L.append("* **无落点：本轮一个都不填。** 它要「逐条读过 Go 侧＋写明取证范围」才算（`fac4b7de`）；"
             "**不许由 0 命中推出**——Go 里换个名字就 grep 不到（`7f782586`、`1865d35a`）。")
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
    L.append("① **敏感性**：取一个已判『有落点』的 kind，把候选名人为清空 ⇒ 必须变成『未核』；"
             "② **控制组**：合成候选名 `TakeDamage` ⇒ 必须判『有落点』。两条任一不成立即 rc=1。"
             "（这不是形式——它证明「状态真的会翻」，否则整张表的『未核』可能只是尺子坏了。）")
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
    n_nocand = sum(1 for r in rows if r["state"] == "未核" and not r["cands"])
    n_nohit = sum(1 for r in rows if r["state"] == "未核" and r["cands"])
    print(f"  kind 共 {len(rows)} 种；有落点 {n_land} 种、无落点 0 种（本轮不填）")
    print(f"  未核 {n_nocand + n_nohit} 种，**两种来源分开报**："
          f"①Python 侧就没有可抽的落点字段名 **{n_nocand}** 种 ／ "
          f"②有字段名但 Go 生产代码 0 命中 **{n_nohit}** 种")
    print(f"  Go 生产代码 .go 文件 {d['go_files']} 个、词表 {d['go_words']} 个")
    if a.md:
        Path(a.md).write_text(md(d), encoding="utf-8")
        print(f"  表已写：{a.md}")
    if a.json:
        Path(a.json).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  数据已写：{a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
