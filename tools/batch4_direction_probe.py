"""第四批（分析层）方向核对探针 —— 只读，不写产品代码、不改 audit_coverage.py。

用途：把 A 名单（过闸行空间贪心 10 位）覆盖到的键逐条摊开，给每一条附上
「数据侧原文 → 现有消费点 → 可观测量候选」三件证据，供手写方向表落判。

判据（本任务的定义，不是建议）：每一条键必须答得出
「改完之后，哪个可观测的数往哪边动？」
答不出 ⇒ 退回登记；没查过 ⇒ 未核。

用法：
  python tools/batch4_direction_probe.py --keys     # 只复现名单与 84 键
  python tools/batch4_direction_probe.py --facts    # 84 键 + 每键的数据侧事实
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import audit_coverage as AC  # noqa: E402

SCAN3 = ROOT / "out" / "acceptance" / "batch4-scan3.json"
OUT_JSON = ROOT / "out" / "acceptance" / "batch4-direction-keys.json"

PREFIX = re.compile(r"^(attack@|talent@|enemy@)")


def a_list() -> tuple[list[str], dict[str, str], dict[str, set[str]], dict[str, int]]:
    """复现 A 名单：**复用工具自己的 greedy_pick**，不另写一份逻辑。"""
    blob = json.loads(SCAN3.read_text(encoding="utf-8"))["data"]
    ops = AC.all_operators()
    names = dict(ops)
    order = [c for c, _ in ops]
    needs = {c: set(d["keys1"]) for c, d in blob.items() if c in names and d["port"] == []}
    wt: dict[str, int] = {}
    for v in needs.values():
        for k in v:
            wt[k] = wt.get(k, 0) + 1
    picks, trace = AC.greedy_pick(needs, wt, order, 10)
    return picks, names, needs, wt


def self_check(picks: list[str], names: dict[str, str], needs: dict[str, set[str]]) -> int:
    """复现自检：数字对不上就大声失败（不打印一份看着正常的表）。"""
    covered = {k for c in picks for k in needs[c]}
    pairs, total, full = AC.coverage_of(needs, covered)
    got = ([names[c] for c in picks], pairs, total, full, len(covered))
    want = (["贝洛内", "耶拉", "蕾缪安", "维伊", "薇薇安娜", "淬羽赫默", "煌",
             "隐德来希", "斩业星熊", "谬因"], 112, 251, 19, 84)
    print("名单 :", got[0])
    print("覆盖 :", f"{got[1]}/{got[2]}  完全解锁 {got[3]}  覆盖键 {got[4]}")
    if got != want:
        print("!! 复现失败：与 docs/batch4-selection.md §五之一 的读数不一致", file=sys.stderr)
        print("   期望:", want, file=sys.stderr)
        print("   实得:", got, file=sys.stderr)
        return 1
    print("复现自检: 通过（名单逐位相同、112/251、解锁 19、84 键）")
    return 0


def key_facts(picks: list[str], names: dict[str, str], needs: dict[str, set[str]],
              wt: dict[str, int]) -> list[dict]:
    """每键一行：原始字面量、需要的 A 名单成员、权重、数据侧原文行。"""
    blob = json.loads(SCAN3.read_text(encoding="utf-8"))["data"]
    rows: list[dict] = []
    for k in sorted({k for c in picks for k in needs[c]}):
        who = [names[c] for c in picks if k in needs[c]]
        raw = PREFIX.sub("", k)
        vals: list[dict] = []
        for c in picks:
            if k not in needs[c]:
                continue
            kv = blob[c]["kv"]
            for src, kk, v in kv:
                if kk == k:
                    vals.append({"op": names[c], "src": src, "val": v})
        rows.append({"key": k, "raw": raw, "wt": wt[k], "ops": who, "vals": vals})
    return rows


def _hit_patterns(key: str) -> list[re.Pattern]:
    """键的命中模式（**带边界**）。

    ★ 为什么要边界：第一版把裸键当子串查，`charge_time` 命中了源码里的
    `"max_charge_time"`（`ak_tactic/formula.py:96`）——那是**假命中**，
    会把一条真欠账错判成「有人读」。判「有消费点」必须命中**整个标识符**：
    两边不许再连着 `[A-Za-z0-9_@$.]`。`$` 在排除集里，故 `"$projectile"`
    要单列一条带 `$` 的模式；方括号变体键的**条件名**（`[stack]` → `stack`）也是。
    """
    cands = {key, PREFIX.sub("", key)}
    m = re.search(r"\[([^\]]+)\]", key)
    if m:
        cands.add(m.group(1))
    pats = []
    for c in cands:
        if len(c) < 3:
            continue
        e = re.escape(c)
        pats.append(re.compile(r"""["']\$?""" + e + r"""["']"""))      # 引号内的完整键（含 $ 写法）
        pats.append(re.compile(r"(?<![A-Za-z0-9_@$.])" + e + r"(?![A-Za-z0-9_@$.])"))
    return pats


def grep_hits(key: str) -> dict:
    """这个键在两棵树里出现的位置。

    ★ 为什么要两棵树：`tools/audit_coverage.py` 的「无人读」列**只扫
    `ak_tactic/**/*.py`**；而 09-19 起产品引擎是 Go（`rios-sim/`）。⇒ 一个键
    完全可能「Go 已实现、Python 没有」，却仍被判成第 1 类（真没建模）。
    方向核对必须两棵树都看，否则会把已建模的当欠账去接线。
    """
    pats = _hit_patterns(key)
    out: dict[str, list[str]] = {"go": [], "py": [], "py_simgo": []}
    for tree, glob, slot in ((ROOT / "rios-sim", "*.go", "go"),
                             (ROOT / "ak_tactic", "*.py", "py")):
        for p in tree.rglob(glob):
            if "__pycache__" in p.parts:
                continue
            slot2 = "py_simgo" if (slot == "py" and "simgo" in p.parts) else slot
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if any(pp.search(line) for pp in pats):
                    out[slot2].append(f"{p.relative_to(ROOT).as_posix()}:{i}: {line.strip()[:110]}")
    return out


def sem_facts(picks: list[str], names: dict[str, str], needs: dict[str, set[str]],
              wt: dict[str, int]) -> list[dict]:
    """每键一行的**语义取证**：来源技能/天赋名 + 正文 + 同一黑板的全套兄弟键。"""
    import sqlite3

    db = sqlite3.connect(str(ROOT / "data" / "akdb.sqlite"))
    blob = json.loads(SCAN3.read_text(encoding="utf-8"))["data"]
    rows: list[dict] = []
    for k in sorted({k for c in picks for k in needs[c]}):
        who = [names[c] for c in picks if k in needs[c]]
        srcs: list[dict] = []
        for c in picks:
            if k not in needs[c]:
                continue
            for src, kk, v in blob[c]["kv"]:
                if kk != k:
                    continue
                sid = src.split("·", 1)[0] if src.startswith("sk") else None
                desc, sib, sname = "", [], src
                if sid:
                    r = db.execute(
                        "SELECT name, description, blackboard FROM skill_level "
                        "WHERE skill_id=? ORDER BY level DESC LIMIT 1", (sid,)).fetchone()
                    if r:
                        sname, desc = r[0], r[1] or ""
                        try:
                            sib = sorted(json.loads(r[2] or "{}").keys())
                        except Exception:  # noqa: BLE001
                            sib = []
                else:
                    r = db.execute(
                        "SELECT description, blackboard FROM operator_talent "
                        "WHERE char_id=? AND name=? LIMIT 1", (c, src)).fetchone()
                    if r:
                        desc = r[0] or ""
                        try:
                            sib = sorted(json.loads(r[1] or "{}").keys())
                        except Exception:  # noqa: BLE001
                            sib = []
                srcs.append({"op": names[c], "src": src, "skill_id": sid, "skill": sname,
                             "val": v, "desc": desc, "siblings": sib})
        rows.append({"key": k, "raw": PREFIX.sub("", k), "wt": wt[k], "ops": who, "srcs": srcs})
    db.close()
    return rows


def ben_ops(needs: dict[str, set[str]], names: dict[str, str], picks: list[str]) -> dict[str, list[str]]:
    """每个键在**过闸行空间**（169 位）里被谁需要——受益面，不只是 A 名单那几位。"""
    out: dict[str, list[str]] = {}
    for c, ks in needs.items():
        for k in ks:
            out.setdefault(k, []).append(names[c])
    return out


def ports_per_skill(picks: list[str], names: dict[str, str]) -> list[str]:
    """逐技能看第二道闸（复用 `AC.port_reasons_best` 的测试替身做法，不另写判据）。

    ★ 为什么必须逐技能：A 名单的入选判据是「**至少一个**技能能进 Go」
    （`audit_coverage.port_reasons_best` 取理由最少的那次）——它**不保证**
    本批选出的键有落点。本函数的输出就是那张逐技能的落点表。
    """
    from ak_tactic.operator.skill import SkillBook
    from ak_tactic.simgo import skills as sk_mod

    class _Sim:
        effect_source = "blackboard"

    lines = []
    for cid in picks:
        lines.append(f"== {names.get(cid, '?')} ({cid})")
        for sk in SkillBook().for_operator(cid):
            try:
                lv = sk.level(level=7, mastery=3)
            except Exception as exc:  # noqa: BLE001
                lines.append(f"   {sk.skill_id}: 取不到专三 ({type(exc).__name__})")
                continue
            op = type("_Op", (), {})()
            op.skill = lv
            op.effects_override = None
            try:
                rs = list(sk_mod.port_reasons(_Sim(), op))
            except Exception as exc:  # noqa: BLE001
                rs = [f"扫描失败 {type(exc).__name__}: {exc}"]
            lines.append(f"   {sk.skill_id}·{lv.name}: "
                         f"{'可进 Go' if not rs else '挡住 -> ' + '；'.join(rs)}")
    return lines


def talent_phases() -> list[str]:
    """关键天赋**逐档**黑板——判「值是否为 0」与「谁是插值端点」必须按档核。"""
    import sqlite3

    want = [("char_4037_demetr", "家族手段"), ("char_4037_demetr", "街头直觉"),
            ("char_4013_kjera", "低眉"), ("char_1031_slent2", "无声砥柱"),
            ("char_1031_slent2", "丰润羽翼"), ("char_017_huang", "紧急除颤"),
            ("char_017_huang", "严酷训练"), ("char_1044_hsgma2", "鬼之架势"),
            ("char_1044_hsgma2", "业火"), ("char_4010_etlchi", "萃血"),
            ("char_4098_vvana", "燃烛施明"), ("char_4193_lemuen", "逃犯引渡手续")]
    con = sqlite3.connect(f"file:{ROOT / 'data' / 'akdb.sqlite'}?mode=ro", uri=True)
    lines = []
    for cid, tn in want:
        lines.append(f"== {cid} {tn}")
        for name, gi, ci, ph, bb in con.execute(
                "SELECT name, group_index, cand_index, unlock_phase, blackboard "
                "FROM operator_talent WHERE char_id=? AND name=? "
                "ORDER BY group_index, cand_index, unlock_phase", (cid, tn)):
            lines.append(f"   [g{gi}c{ci} ph{ph}] {bb}")
    con.close()
    return lines


def trait_texts(picks: list[str], names: dict[str, str]) -> list[str]:
    """A 名单的**特性正文**（特性键没有 skill 描述，语义只能从这里取）。"""
    import sqlite3

    con = sqlite3.connect(f"file:{ROOT / 'data' / 'akdb.sqlite'}?mode=ro", uri=True)
    lines = []
    for cid in picks:
        for cid2, nm, trait, in con.execute(
                "SELECT char_id, name, trait_text FROM operator WHERE char_id=?", (cid,)):
            lines.append(f"== {nm} ({cid2})\n   trait_text: {trait}")
            for ci, ph, ov, bb in con.execute(
                    "SELECT cand_index, unlock_phase, override_description, blackboard "
                    "FROM operator_trait WHERE char_id=? ORDER BY cand_index", (cid2,)):
                lines.append(f"   [cand{ci} ph{ph}] {ov}   bb={bb}")
    con.close()
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", action="store_true", help="只印名单与键清单")
    ap.add_argument("--facts", action="store_true", help="印每键的数据侧事实")
    ap.add_argument("--evidence", action="store_true", help="两棵树逐键 grep 取证并落盘")
    ap.add_argument("--sem", action="store_true", help="语义取证（技能正文＋兄弟键）并落盘")
    ap.add_argument("--ports", action="store_true", help="逐技能的第二道闸落点表")
    ap.add_argument("--phases", action="store_true", help="关键天赋逐档黑板＋特性正文")
    a = ap.parse_args()
    picks, names, needs, wt = a_list()
    rc = self_check(picks, names, needs)
    if a.ports:
        txt = ROOT / "out" / "acceptance" / "batch4-port-per-skill.txt"
        lines = ports_per_skill(picks, names)
        txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"落点表落盘: {txt.relative_to(ROOT)}（{len(lines)} 行）")
        return rc
    if a.phases:
        txt = ROOT / "out" / "acceptance" / "batch4-talents-traits.txt"
        lines = trait_texts(picks, names) + [""] + talent_phases()
        txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"逐档表落盘: {txt.relative_to(ROOT)}（{len(lines)} 行）")
        return rc
    if a.sem:
        rows = sem_facts(picks, names, needs, wt)
        ben = ben_ops(needs, names, picks)
        for r in rows:
            r["hits"] = grep_hits(r["key"])
            r["beneficiaries"] = ben.get(r["key"], [])
        ev = ROOT / "out" / "acceptance" / "batch4-direction-sem.json"
        ev.write_text(json.dumps({"picks": [names[c] for c in picks], "rows": rows},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
        lines = []
        for r in rows:
            inA = [o for o in r["beneficiaries"] if o in set(r["ops"])]
            lines.append(f"=== {r['key']}  (权重{r['wt']}；A名单 {'、'.join(inA)}；"
                         f"过闸受益面 {len(r['beneficiaries'])}: {'、'.join(r['beneficiaries'])})")
            for s in r["srcs"]:
                lines.append(f"  [{s['op']}] {s['src']}  值={s['val']!r}")
                if s["desc"]:
                    lines.append(f"      正文: {s['desc']}")
                if s["siblings"]:
                    lines.append(f"      同黑板键: {', '.join(s['siblings'])}")
            h = r["hits"]
            lines.append(f"  grep: go={len(h['go'])} py={len(h['py'])} py_simgo={len(h['py_simgo'])}")
            for slot in ("go", "py", "py_simgo"):
                for line in h[slot][:3]:
                    lines.append(f"      {slot}: {line}")
        txt = ROOT / "out" / "acceptance" / "batch4-direction-sem.txt"
        txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"语义取证落盘: {ev.relative_to(ROOT)}")
        print(f"文本落盘: {txt.relative_to(ROOT)}（{len(lines)} 行）")
        return rc
    rows = key_facts(picks, names, needs, wt)
    if a.evidence:
        for r in rows:
            r["hits"] = grep_hits(r["key"])
        ev = ROOT / "out" / "acceptance" / "batch4-direction-evidence.json"
        ev.write_text(json.dumps({"picks": [names[c] for c in picks], "rows": rows},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
        n0 = sum(1 for r in rows if not r["hits"]["go"] and not r["hits"]["py"]
                 and not r["hits"]["py_simgo"])
        print(f"取证落盘: {ev.relative_to(ROOT)}")
        print(f"两棵树都零命中的键: {n0}/{len(rows)}")
        return rc
    if a.facts:
        for r in rows:
            print(f"\n== {r['key']}   权重 {r['wt']}   需要者 {len(r['ops'])}: {'、'.join(r['ops'])}")
            for v in r["vals"][:4]:
                print(f"   [{v['src']}] {v['val']!r}")
    else:
        #: 键清单落盘由 Python 自己写（PowerShell 重定向会把中文按 CP936 错解）。
        lines = [f"{r['key']}\t权重{r['wt']}\t{'、'.join(r['ops'])}" for r in rows]
        txt = ROOT / "out" / "acceptance" / "batch4-direction-keys.txt"
        txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"键清单落盘: {txt.relative_to(ROOT)}（{len(lines)} 行）")
    if not a.keys:
        idn = json.loads(SCAN3.read_text(encoding="utf-8"))["ident"]
        OUT_JSON.write_text(json.dumps(
            {"ident": {"scan3": "out/acceptance/batch4-scan3.json",
                       #: ★ scan3 的 ident **没有 head**（§七 未核项）；取不到就写「不可得」，
                       #: 不留空（留空会被读成「没有这回事」）。
                       "scan3_head": idn.get("head", "不可得（扫描当时未记录）"),
                       "scan3_src_dirty": idn.get("src_dirty", "不可得")},
             "picks": [names[c] for c in picks], "n_keys": len(rows), "rows": rows},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n落盘: {OUT_JSON.relative_to(ROOT)}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
