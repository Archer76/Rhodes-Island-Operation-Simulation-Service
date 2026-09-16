"""量纲审计：把描述里出现的每一个黑板键按「量纲判据」分类，产出人工可核对的清单。

**每一需要裁定的行都带一名所属干员**：量纲判不出来时，人能做的动作是回去翻那个
干员的原文，所以行里必须能追到人（`所属干员`），并留一栏 `裁定` 供填。

`裁定` 一栏的内容在重新生成本文件时**会被读回来续用**，不会被冲掉；建议填
`比例` / `绝对值` / `倍率` / `存疑`，或写别的自由文本（原样保留）。

为什么要单独出这份文件：描述里的数字有两种量纲——**比例**（`{atk:0%}` 值 0.14
即 +14%）与**绝对值**（`{attack_speed}` 值 8 即攻速 +8）。判定错了不会报错，
只会静默差 100 倍。所以判据必须可审计、判不出的必须显式列出来由人裁定。

判据优先级（见 `ak_tactic.formula.Num.unit`）：
  ① 文面直接跟 `%`          → PCT（值已是百分数，**不再乘 100**）
  ② 格式说明符含 `%`        → RATIO
  ③ 键名在 RATIO_KEYS/后缀  → RATIO
  ④ 键名在 FLAT_KEYS        → FLAT
  ⑤ 上下文邻字（秒/点/格/倍）→ FLAT / SCALE
  ⑥ 都不成立                → UNKNOWN（本文件要人看的就是这一档）

用法：
    python tools/unit_audit.py              # 写 docs/formula-units.md 并打印摘要
    python tools/unit_audit.py --stdout     # 只打印，不写文件
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ak_tactic.formula import (FLAT_KEYS, PLACEHOLDER_RE, RATIO_KEYS, RATIO_SUFFIX,  # noqa: E402
                               RULED_FLAT_KEYS, TAG_RE, Num, _base_key, load_corpus,
                               normalize, nums_in)

DEFAULT_DB = ROOT / "data" / "akdb.sqlite"
DEFAULT_OUT = ROOT / "docs" / "formula-units.md"


# ------------------------------------------------------------ 谁在用这个键

def _compress(items: list[tuple[str, bool]]) -> tuple[str, bool]:
    """一名干员直接用名字；共用的键显示前两名 + 共几个——表格里放不下长名单。

    返回 `(名字串, 是否真干员)`：**只要有一个真干员在用，就算真干员所属**。
    """
    uniq = sorted({n for n, _ in items if n})
    is_op = any(flag for _, flag in items)
    if not uniq:
        return "", is_op
    if len(uniq) <= 2:
        return "／".join(uniq), is_op
    return f"{uniq[0]} 等 {len(uniq)} {'人' if is_op else '个'}", is_op


def _owners(db: pathlib.Path) -> dict[str, dict[str, Any]]:
    """三条归属索引：skill_id → 干员、char_id → 干员、module_id → 干员。

    技能会被多名干员共用（升变形态、召唤物），所以值是**压缩后的名字串**而不是单个；
    同时带上 `is_operator`——生息演算建筑与召唤物也在 operator 表里，但它们不是人，
    列进「所属干员」会让人以为能去翻某个干员的原文（`is_operator=1` 才是真干员）。
    """
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    named = {r[0]: (r[1], bool(r[2])) for r in
             conn.execute("SELECT char_id, name, is_operator FROM operator")}
    skills: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    modules: dict[str, tuple[str, bool]] = {}
    try:
        for skill_id, char_id in conn.execute(
                "SELECT skill_id, char_id FROM operator_skill WHERE skill_id IS NOT NULL"):
            name, is_op = named.get(char_id, ("", False))
            if name:
                skills[skill_id].append((name, is_op))
        for module_id, char_id in conn.execute(
                "SELECT module_id, char_id FROM module WHERE char_id IS NOT NULL"):
            modules[module_id] = named.get(char_id, ("", False))
    finally:
        conn.close()
    return {"skill": {k: _compress(v) for k, v in skills.items()},
            "char": named, "module": modules}


def _owner_of(src: str, ident: str, owners: dict) -> tuple[str, bool]:
    """语料标识 → (名字, 是不是真干员)。标识形如 `skx#L7` / `char_x:G0C0`。"""
    if src == "skill":
        return owners["skill"].get(ident.rsplit("#L", 1)[0], ("", False))
    if src == "module":
        return owners["module"].get(ident.split(":", 1)[0], ("", False))
    return owners["char"].get(ident.split(":", 1)[0], ("", False))


# ------------------------------------------------------------ 裁定栏的续用

_RULING_COL = "裁定"


def load_rulings(path: pathlib.Path) -> dict[tuple[str, str], str]:
    """把上一版文档里已填的 `裁定` 读回来。

    为什么要这么做：这份文件是生成的，而 `裁定` 是人手写的——重新生成时如果
    直接覆盖，博士填过的东西就没了。所以**只认带 `裁定` 列的表**（旧版没有这一列，
    它的最后一栏是建议/语境，不能被当答案读进来）。
    """
    if not path.exists():
        return {}
    out: dict[tuple[str, str], str] = {}
    section, has_col, ncol = "", False, 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section, has_col, ncol = line[3:].strip(), False, 0
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        if not cells:
            continue
        if _RULING_COL in cells:
            has_col, ncol = True, len(cells)
            continue
        # 列名带后缀也算（台账那节叫「裁定」但历史上写过「裁定原文」）——
        # 只认全等的话，整张表会被静默跳过，人填的内容全部读不回来。
        if any(c.startswith(_RULING_COL) for c in cells):
            has_col, ncol = True, len(cells)
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        if not has_col:
            continue
        if len(cells) > ncol:
            # 人直接在 markdown 里敲了 `|`：表格被多切出几栏，而那几栏本来就是最后一栏的内容。
            # 不并回去的话，裁定值会被悄悄截断成最后半截——比报错更难发现。
            cells = cells[:ncol - 1] + ["|".join(cells[ncol - 1:])]
        key, val = cells[0].strip("`"), cells[-1].replace("\\|", "|")
        if key and val:
            out[(section, key)] = val
    return out


def _cell(text: str) -> str:
    """markdown 单元格转义：`|` 会切断表格，换行会切断行。"""
    return re.sub(r"\s+", " ", (text or "").replace("|", "\\|")).strip()


def _why(num: Num) -> str:
    """这条判据是谁定的——要能回溯到规则，才谈得上审计。"""
    if num.pct:
        return "文面百分号"
    if num.spec.endswith("%"):
        return "格式说明符"
    k = _base_key(num.key or "")
    if k in RATIO_KEYS or k.endswith(RATIO_SUFFIX):
        return "键名(比例)"
    if k in FLAT_KEYS:
        return "键名(绝对值)"
    if num.hint:
        return "上下文邻字"
    return "**无判据**"


def audit(db: pathlib.Path) -> dict:
    corpus = load_corpus(db)
    owners = _owners(db)
    stat: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "specs": Counter(), "samples": [], "srcs": Counter(),
                 "units": Counter(), "whys": Counter(), "hint": "",
                 "op_owners": Counter(), "dev_owners": Counter()})

    for src, ident, text, bb in corpus:
        clean = TAG_RE.sub("", text)
        flat, slots = normalize(text)
        nums = nums_in(flat, slots, bb)
        who, is_op = _owner_of(src, ident, owners)
        for m in PLACEHOLDER_RE.finditer(text):
            k, _, spec = m.group(1).partition(":")
            k, spec = k.strip(), spec.strip()
            # 同一个键可能出现多次、每次语境不同，故逐次记录量纲；
            # 只按"最后一次"覆盖会掩盖前后不一致——那恰恰最该被人看到。
            num = next((c for c in nums if c.key == k), None)
            if num is None:
                continue
            rec = stat[k]
            rec["n"] += 1
            rec["specs"][spec or "(空)"] += 1
            rec["srcs"][src] += 1
            rec["units"][num.unit] += 1
            rec["whys"][_why(num)] += 1
            rec["hint"] = num.hint
            (rec["op_owners"] if is_op else rec["dev_owners"])[who or "—"] += 1
            if len(rec["samples"]) < 8:
                idx = clean.find(k)
                frag = clean[max(0, idx - 26):idx + 22] if idx >= 0 else clean[:48]
                rec["samples"].append({"frag": re.sub(r"\s+", " ", frag),
                                       "who": who, "is_op": is_op})

    for rec in stat.values():
        mixed = [u for u, _ in rec["units"].most_common() if u != "UNKNOWN"]
        rec["unit"] = rec["units"].most_common(1)[0][0]
        rec["why"] = rec["whys"].most_common(1)[0][0]
        rec["mixed"] = "混合" if len(mixed) > 1 else ""

    by_unit = Counter(r["unit"] for r in stat.values())
    occ_by_unit = Counter()
    for r in stat.values():
        occ_by_unit[r["unit"]] += r["n"]
    unknown = {k: r for k, r in stat.items() if r["unit"] == "UNKNOWN"}
    ctx = {k: r for k, r in stat.items() if r["why"] == "上下文邻字"}
    mixed = {k: r for k, r in stat.items() if r.get("mixed")}
    return {"corpus": len(corpus), "keys": stat, "by_unit": by_unit,
            "occ_by_unit": occ_by_unit, "unknown": unknown, "ctx": ctx,
            "mixed": mixed}


SEC_UNK = "二、仍需博士裁定的键（判不出量纲）"
SEC_MIX = "三、**同一键被判出两种量纲**的键（最该先看）"
SEC_CTX = "四、上下文判定的键（抽查用）"


def _pick(rec: dict) -> dict | None:
    """代表：**优先挑真干员那一条**——装置不是人，翻不到「它的原文」这个动作。

    语境片段必须与代表同源（截图与出处对不上是最难查的那种错），故两者一起挑。
    """
    samples = rec["samples"]
    if not samples:
        return None
    return next((s for s in samples if s["is_op"]), samples[0])


def _who_cell(rec: dict) -> str:
    """所属干员。纯装置所属的键不能写成干员名，否则等于指了个不存在的人。"""
    pick = _pick(rec)
    if pick is None or not pick["who"]:
        return "—"
    if pick["is_op"]:
        n = len([k for k in rec["op_owners"] if k != "—"])
        return f"{pick['who']}（共 {n} 人）" if n > 1 else pick["who"]
    n = len([k for k in rec["dev_owners"] if k != "—"])
    tail = f"（共 {n} 个）" if n > 1 else ""
    return f"装置「{pick['who']}」{tail}"


def _sample(rec: dict) -> str:
    pick = _pick(rec)
    return _cell(pick["frag"] if pick else "")


def _ruling(rules: dict[tuple[str, str], str], section: str, key: str) -> str:
    """裁定栏要**转义后**写入：填的内容里若有 `|`，不转义会把表格切断、下次也读不回来。"""
    return _cell(rules.get((section, key), ""))


def _ruling_any(rules: dict[tuple[str, str], str], key: str) -> str:
    """这个键的裁定原文——**不看它现在被归在哪一节**。

    键一旦被裁定采纳，就不再落入"未定"或"按邻字"两张表，若只按节名取，
    人写的备注（「原文此处是固定的费用-1」这类）会随表格一起消失。
    所以最后还要扫一遍**所有**小节——台账那节正是靠这一步才读得回来；
    占位符（以「（」开头）不算原文，否则它会自我固化、再也换不回来。
    """
    for sec in (SEC_UNK, SEC_MIX, SEC_CTX):
        text = rules.get((sec, key))
        if text:
            return text
    for _sec, k in rules:
        text = rules[(_sec, k)]
        if k == key and text and not text.startswith("（"):
            return text
    return ""


def render_md(a: dict, rulings: dict[tuple[str, str], str] | None = None) -> str:
    rules = rulings or {}
    st, unk = a["keys"], a["unknown"]
    total_occ = sum(r["n"] for r in st.values())
    lines: list[str] = []
    lines.append("# 描述里黑板键的量纲清单")
    lines.append("")
    lines.append("> 由 `python tools/unit_audit.py` 生成，勿手改；判据定义见 "
                 "`ak_tactic/formula.py` 的 `Num.unit`。")
    lines.append(">")
    lines.append("> **最后一栏 `裁定` 是给人填的**，重新生成时会被读回续用，不会冲掉。"
                 "填 `绝对值` / `固定值`（两者同义，都是 FLAT）、`比例` / `倍率` / `存疑`，"
                 "也可写自由文本。"
                 "`所属干员` 是那条例句的出处（先回它的原文核对）；"
                 "只出现在召唤物/生息演算建筑上的键标作 `装置「…」`，那不是人。")
    lines.append(">")
    lines.append("> 已落地的裁定会并入 `ak_tactic/formula.py` 的 "
                 "`RULED_FLAT_KEYS`（判据是人给的，与从语料核出来的 `FLAT_KEYS` 分开放）。"
                 "**填了却没被采纳的会列在文末**——那是因为数据与裁定相反，需要复核。")
    lines.append("")
    lines.append(f"语料 {a['corpus']} 条，描述里出现的**占位符键 {len(st)} 种、"
                 f"共 {total_occ} 次**。")
    lines.append("")
    lines.append("## 一、判定结果总览")
    lines.append("")
    lines.append("| 量纲 | 键数 | 出现次数 | 含义 |")
    lines.append("|---|---:|---:|---|")
    meaning = {
        "PCT": "文面已写 `%`，值就是百分数（210 就是 210%），**不再乘 100**",
        "RATIO": "黑板里的比例/倍率，0.14 → 14%、2.1 → 210%",
        "FLAT": "绝对值，8 就是 8（秒/点/格/个/层）",
        "SCALE": "「提升至 N 倍」的倍率，1.4 → 1.4 倍",
        "UNKNOWN": "**判不出**，需人工裁定（见第二节）",
    }
    for u in ("PCT", "RATIO", "FLAT", "SCALE", "UNKNOWN"):
        if a["by_unit"].get(u):
            lines.append(f"| {u} | {a['by_unit'][u]} | {a['occ_by_unit'][u]} | "
                         f"{meaning[u]} |")
    lines.append("")
    ctx_n = sum(r["n"] for r in a["ctx"].values())
    lines.append(f"其中靠**上下文邻字**（`{N_DOC}`）救回的有 {len(a['ctx'])} 种、"
                 f"{ctx_n} 次——这些键名本身毫无线索，"
                 f"单位写在它后面那个字里。")
    lines.append("")

    lines.append(f"## {SEC_UNK}")
    lines.append("")
    if not unk:
        lines.append("**无。** 全部键都定了量纲。")
    else:
        lines.append(f"共 {len(unk)} 种、{sum(r['n'] for r in unk.values())} 次。"
                     "下表按出现次数降序；`我的建议` 一栏为空即表示键名与上下文都没线索，"
                     "`裁定` 一栏请填。")
        lines.append("")
        lines.append("| 键名 | 次数 | 说明符 | 来源 | 所属干员 | 出现语境 | "
                     "我的建议 | 裁定 |")
        lines.append("|---|---:|---|---|---|---|---|---|")
        for k, r in sorted(unk.items(), key=lambda kv: -kv[1]["n"]):
            specs = "/".join(f"{s}×{c}" for s, c in r["specs"].most_common(3))
            srcs = "/".join(f"{s}×{c}" for s, c in r["srcs"].most_common(3))
            lines.append(f"| `{k}` | {r['n']} | {specs} | {srcs} | {_who_cell(r)} | "
                         f"{_sample(r)} | {_suggest(k, r)} | "
                         f"{_ruling(rules, SEC_UNK, k)} |")
    lines.append("")

    lines.append(f"## {SEC_MIX}")
    lines.append("")
    if not a.get("mixed"):
        lines.append("**无。** 每个键在所有语境下量纲一致。")
    else:
        lines.append(f"共 {len(a['mixed'])} 种。这类键要么是**同键不同义**（数据侧的问题），"
                     "要么是我的判据在某个语境下判错了——两种都必须由人看一眼。")
        lines.append("")
        lines.append("| 键名 | 各量纲出现次数 | 次数 | 所属干员 | 语境 | 裁定 |")
        lines.append("|---|---|---:|---|---|---|")
        for k, r in sorted(a["mixed"].items(), key=lambda kv: -kv[1]["n"]):
            dist = "/".join(f"{u}×{c}" for u, c in r["units"].most_common())
            lines.append(f"| `{k}` | {dist} | {r['n']} | {_who_cell(r)} | "
                         f"{_sample(r)} | {_ruling(rules, SEC_MIX, k)} |")
    lines.append("")

    lines.append(f"## {SEC_CTX}")
    lines.append("")
    lines.append("这些键的量纲是**按邻字**定的，不是按键名。请重点抽查有没有"
                 "「邻字是点、实际却是比例」这类反例。")
    lines.append("")
    lines.append("| 键名 | 判为 | 邻字 | 次数 | 所属干员 | 语境 | 裁定 |")
    lines.append("|---|---|---|---:|---|---|---|")
    # 次数前 60 名 + **已填过裁定的**——平局时排序不稳，只按 60 条裁剪会把
    # 人已经填好的行挤出表格，裁定随之消失（`skill_max_trigger_time` 就这样丢过一次）。
    ctx_sorted = sorted(a["ctx"].items(), key=lambda kv: -kv[1]["n"])
    head = ctx_sorted[:60]
    seen = {k for k, _ in head}
    head += [(k, r) for k, r in ctx_sorted[60:]
             if _ruling_any(rules, k) and k not in seen]
    for k, r in head:
        lines.append(f"| `{k}` | {r['unit']} | {r['hint']} | {r['n']} | {_who_cell(r)} | "
                     f"{_sample(r)} | {_ruling(rules, SEC_CTX, k)} |")
    lines.append("")

    # 已采纳的裁定：这些键已不在上面任何一张表里，但**原文必须留档**。
    adopted = [k for k in sorted(RULED_FLAT_KEYS)
               if k in st or _base_key(k) in {_base_key(x) for x in st}]
    if adopted:
        lines.append("## 五、已采纳的裁定台账（判据已进 `RULED_FLAT_KEYS`）")
        lines.append("")
        lines.append("这些键的量纲已按裁定定死，故不再出现在上面三节里。"
                     "**原文留在此处**，改判据时按这张表回查。")
        lines.append("")
        lines.append("| 键名 | 量纲 | 语料出现次数 | 所属干员 | 裁定 |")
        lines.append("|---|---|---:|---|---|")
        for k in adopted:
            rec = st.get(k) or st.get(_base_key(k))
            n = rec["n"] if rec else 0
            who = _who_cell(rec) if rec else "—"
            text = _ruling_any(rules, k) or "（并入时原文未留）"
            lines.append(f"| `{k}` | FLAT | {n} | {who} | {_cell(text)} |")
        lines.append("")

    # 填了却没被采纳的：裁定写"绝对值/固定值"，但判出来的不是 FLAT。
    # 必须显式列出来——静默地不采纳等于把人的判断丢掉。
    conflicts: list[str] = []
    for sec, judged in ((SEC_MIX, a.get("mixed") or {}),
                        (SEC_CTX, a.get("ctx") or {})):
        for k, r in judged.items():
            text = _ruling(rules, sec, k)
            if any(w in text for w in ("绝对值", "固定值")) and r["unit"] != "FLAT":
                conflicts.append(f"`{k}` —— 判为 {r['unit']}，裁定写「{text}」"
                                 f"（出处：{_who_cell(r)}）")
    if conflicts:
        lines.append("## 六、**填了但未采纳**的裁定（须复核）")
        lines.append("")
        lines.append("这些行的 `裁定` 写的是绝对值，但**正文与黑板值都指向倍率**"
                     "（原文有「倍」字、黑板值是 1.x），所以没有并进 `RULED_FLAT_KEYS`。"
                     "若以裁定为准，把它们加进 `ak_tactic/formula.py` 的 "
                     "`RULED_FLAT_KEYS` 即可；若以数据为准，请把这几行的 `裁定` "
                     "改成 `倍率`。")
        lines.append("")
        for c in conflicts:
            lines.append(f"* {c}")
        lines.append("")
    return "\n".join(lines)


N_DOC = "秒 / 点 / 格 / 名 / 个 / 次 / 层 / 枚 / 发 / 份 / 颗 / 倍"

#: 对未定键的一句建议。**是建议不是结论**——最终由博士裁定后写回
#: `RATIO_KEYS` / `FLAT_KEYS`，或补一条上下文判据。
_SUGGEST: dict[str, str] = {
    "sp": "绝对值（技力点数）",
    "sleep": "绝对值（秒）",
    "silence": "绝对值（秒）",
    "constraint": "绝对值（秒）",
    "cold": "绝对值（秒）",
    "levitate": "绝对值（秒）",
    "def_penetrate_fixed": "绝对值（防御点数）",
    "magic_resist_penetrate_fixed": "绝对值（法抗点数）",
    "stun_duration": "绝对值（秒）",
    "shield_duration": "绝对值（秒）",
    "buff_duration": "绝对值（秒）",
    "multi_times": "绝对值（次数）",
    "max_cnt": "绝对值（个数）",
    "chain_times": "绝对值（次数）",
    "produce": "绝对值（份数，生息演算）",
    "score": "绝对值（评分，生息演算）",
    "next_score": "绝对值（评分，生息演算）",
    "electric_value": "绝对值（电力，生息演算）",
    "damage": "**需看原技能**：语境是「用{damage}的攻击力攻击」，疑为比例",
    "sp_cost": "绝对值（魔力点）",
    "cooldown": "绝对值（秒）",
    "interval": "绝对值（秒）",
    "cost_period": "绝对值（费用）",
    "scale_delta_to_one": "倍率（值 1.4）",
}


def _suggest(key: str, rec: dict) -> str:
    base = _base_key(key)
    if base in _SUGGEST:
        return _SUGGEST[base]
    if base.startswith("attack@"):
        inner = base.split("@", 1)[1]
        if inner in _SUGGEST:
            return _SUGGEST[inner]
    specs = rec["specs"]
    if any(s and s[0].isdigit() and "." in s for s in specs):
        return "疑为绝对值（说明符 `0.0`）"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="黑板键量纲审计")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--stdout", action="store_true", help="只打印不写文件")
    args = ap.parse_args()

    a = audit(pathlib.Path(args.db))
    out = pathlib.Path(args.out)
    rules = load_rulings(out)
    md = render_md(a, rules)
    print(f"键 {len(a['keys'])} 种，未定 {len(a['unknown'])} 种 / "
          f"{sum(r['n'] for r in a['unknown'].values())} 次；"
          f"上下文判定 {len(a['ctx'])} 种；混合量纲 {len(a.get('mixed', {}))} 种")
    for u, n in a["by_unit"].most_common():
        print(f"  {u:<8} 键 {n:>4}  {a['occ_by_unit'][u]:>5} 次")
    if rules:
        print(f"续用上一版已填的裁定 {len(rules)} 条")
    if not args.stdout:
        out.write_text(md, encoding="utf-8")
        print(f"已写 {out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
