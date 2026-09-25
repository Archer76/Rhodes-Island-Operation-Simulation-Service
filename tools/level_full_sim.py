#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一关一份台账：**算得出 / 跑得动 / 机制真被行使** 三层读数的同一入口。

## 它答什么

对**一个关卡 id**，按 `docs/level-full-sim-ledger.md` 的三层口径给出读数，并把它
**落成一份可复核的行**（命令原样印在输出里，任何人可以重跑）：

| 层 | 读什么 | 判红的形状 |
| --- | --- | --- |
| A 算得出 | `buildspec` 的 19 键是否造齐；`missing_keys`／`gated_keys`；闸门 `reasons` | 缺键、或被闸门拒跑（已登记的拒跑要具名） |
| B 跑得动 | `sim` 的判决四数 | 跑不起来、或判决缺字段 |
| C 机制真被行使 | 机制清单（`tools/level_mech_inventory.py`）**对齐**运行期痕迹 | 清单里有、痕迹里没有 |

## C 层为什么是「对齐」而不是「数痕迹」

只数痕迹不看清单，会漏掉**「清单里有、痕迹里没有」**那一类——它正是「算了但没生效」
的样子（本仓在 `hp_drain_per_sec` 上真栽过一次：判决一模一样，机制根本没跑）。
反过来只看清单也不行：清单是**数据里声明**的键，不是**运行期走到**的机制。
⇒ 两栏并排，`未恒等` 的那一栏由人判（工具不替人下结论）。

## 用法

    python tools\\level_full_sim.py main_00-01
    python tools\\level_full_sim.py main_00-01 --json out\\row.json

★ 纪律：`RIOS_SIM_BIN` **必须显式给**（脚本会替你设默认路径并印出来）；
仪器 sha256(16) 与 `source_sig` 一并印出——没有它，将来的绿红翻转没人判得了是
对象变了还是仪器换了。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
ROSTER = str(ROOT / "fixtures" / "roster_max_modelled.json")


def call(reqs: list[dict], trace: bool = False) -> tuple[list[dict], str]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    if trace:
        env["RIOS_TRACE"] = "1"
    else:
        env.pop("RIOS_TRACE", None)
    p = subprocess.run([GO_BIN], input=("\n".join(json.dumps(r) for r in reqs) + "\n")
                       .encode("utf-8"), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    out = [json.loads(x) for x in p.stdout.decode("utf-8", "replace").strip().splitlines()]
    return out, p.stderr.decode("utf-8", "replace")


def tag_counts(stderr: str) -> dict:
    """从痕迹里数标签。**只认「首列是大写标签」的行**——别把普通日志算进去。"""
    import re
    c: dict[str, int] = {}
    for line in stderr.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*) ", line)
        if m:
            c[m.group(1)] = c.get(m.group(1), 0) + 1
    return c


def identity() -> dict:
    p = Path(GO_BIN)
    if not p.is_file():
        raise SystemExit("仪器不在盘上：%s" % p)
    go_src = sorted((ROOT / "rios-sim").glob("*.go"))
    sig = hashlib.sha256(
        "\n".join("%s:%s" % (f.name, hashlib.sha256(f.read_bytes()).hexdigest())
                  for f in go_src).encode("utf-8")).hexdigest()[:16]
    return {"exe": str(p), "exe_sha16": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
            "source_sig": sig, "n_go": len(go_src)}


def synthetic_plan(level: str) -> dict:
    """一份**明确标成合成**的单干员计划（只给「这关能不能算/能不能跑」用）。

    ⚠ 它**不是**这一关的基线作业：B 层的判决四数在它身上只说明「这一关跑得动」，
    不说明「这一关有人能过」。读数里必须带着这个限定，否则会被当成关卡结论。
    """
    return {"stage": level, "_synthetic": True,
            "deploys": [{"operator": "克洛丝", "position": [1, 1], "direction": "Right",
                         "skill": 0, "elite": 1, "level": 55, "potential": 6,
                         "module_level": 0}]}


def main() -> int:
    ap = argparse.ArgumentParser(description="一关三层读数的同一入口")
    ap.add_argument("level")
    ap.add_argument("--json", help="把这一行写到文件（机器可读）")
    ap.add_argument("--synthetic-plan", action="store_true",
                    help="没有作业夹具时，造一份**合成**单干员计划硬跑（读数按合成计划读）")
    a = ap.parse_args()

    import level_mech_inventory as MI                          # noqa: PLC0415

    idx = MI.load_index()
    by_key = MI.load_enemies()
    plan = MI.plan_fixture(a.level)
    row: dict = {"level": a.level, "identity": identity()}

    print("仪器：%s" % GO_BIN)
    print("      exe sha256(16)=%s  source_sig=%s（%d 个 .go）"
          % (row["identity"]["exe_sha16"], row["identity"]["source_sig"],
             row["identity"]["n_go"]))
    print("关卡：%s；作业夹具：%s" % (a.level, plan.name if plan else "（无，走空计划）"))
    print()

    #: ---- A 算得出 ----------------------------------------------------------
    #: ⚠⚠ **没有作业夹具的关卡，A/B/C 三层都取不到**——这不是 bug，是入口的性质：
    #: `buildspec` 要求计划里有 `stage`（报错「打法必须有关卡号（stage）」）
    #: **并且至少一个部署**（报错「打法里一个部署都没有」）。
    #: 旧写法在没夹具时传 `{}`，于是 10 关一律 A 层失败，而那个失败看起来像
    #: 「这一关算不出来」，不是「这个入口需要一份计划」。
    #:
    #: 处置：**默认大声拒跑**，并说清缺什么；要硬跑就用 `--synthetic-plan`
    #: （它造一份**明确标成合成**的单干员计划，读数必须按合成计划读）。
    if plan is None and not a.synthetic_plan:
        print("A 算得出：⊘ **不适用于本入口**——这一关没有作业夹具，而 A/B/C 三层")
        print("           都要求一份计划（`buildspec` 需要 `stage` ＋ 至少一个部署）。")
        print("           ⇒ 量它要么先产出计划（搜索器那一支），要么用 --synthetic-plan")
        print("             造一份**合成**单干员计划（读数按合成计划读，不是这一关的基线）。")
        row["A"] = {"ok": False, "not_applicable": "no_plan_fixture"}
        if a.json:
            Path(a.json).write_text(json.dumps(row, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        return 3
    plan_arg = str(plan) if plan else synthetic_plan(a.level)
    body = {"plan": plan_arg, "roster": ROSTER}
    req = {"id": 1, "cmd": "buildspec", "level": a.level, "spec": body}
    b, _ = call([req])
    b = b[0]
    if not b.get("ok"):
        row["A"] = {"ok": False, "error": b.get("error")}
        print("A 算得出：✗ %s" % b.get("error"))
        if a.json:
            Path(a.json).write_text(json.dumps(row, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        return 1
    bs = b["build_spec"]
    spec = bs["spec"]
    keys = sorted(spec)
    row["A"] = {"ok": True, "n_keys": len(keys), "keys": keys,
                "missing_keys": bs.get("missing_keys") or [],
                "gated_keys": bs.get("gated_keys") or [],
                "unsupported": spec.get("unsupported")}
    print("A 算得出：✓ %d 个顶层键；missing_keys=%d／gated_keys=%d；unsupported=%s"
          % (len(keys), len(row["A"]["missing_keys"]), len(row["A"]["gated_keys"]),
             json.dumps(spec.get("unsupported"), ensure_ascii=False)[:120]))

    #: ---- B 跑得动（＋ C 的痕迹那一半：同一次跑，开 RIOS_TRACE） -------------
    r, err = call([{"id": 2, "cmd": "sim", "spec": spec}], trace=True)
    r = r[0]
    v = r.get("verdict") or {}
    row["B"] = {"ok": bool(r.get("ok")), "verdict": v, "error": r.get("error")}
    if not r.get("ok"):
        print("B 跑得动：✗ %s" % r.get("error"))
    else:
        print("B 跑得动：✓ won=%s life=%s kills=%s leaks=%s elapsed=%.2f"
              % (v.get("won"), v.get("life"), v.get("kills"), v.get("leaks"),
                 float(v.get("elapsed") or 0)))
    tags = tag_counts(err)
    row["C_trace"] = tags
    print("C 痕迹：%d 种标签 —— %s"
          % (len(tags), "、".join("%s×%d" % kv for kv in
                                 sorted(tags.items(), key=lambda kv: -kv[1])[:12])
             or "（一条都没有 —— 先确认这次跑成功了再看它）"))

    #: ---- C 的另一半：这一关引用了哪些机制（数据侧现算） ---------------------
    raw = MI.level_raw(idx, a.level)
    if raw is None:
        print("C 清单：✗ 关卡文件取不到")
    else:
        refs = [x["id"] for x in (raw.get("enemyDbRefs") or [])
                if isinstance(x, dict) and x.get("id")]
        bb, sk = set(), set()
        for k in refs:
            m = MI.enemy_keys(by_key, k)
            bb |= set(m["blackboard"])
            sk |= set(m["skills"])
        ops = []
        if plan is not None:
            import sqlite3
            conn = sqlite3.connect("file:%s?mode=ro" % MI.AKDB.as_posix(), uri=True)
            conn.row_factory = sqlite3.Row
            d = json.loads(plan.read_text(encoding="utf-8"))
            for dp in (d.get("deploys") or []):
                ops.append({"name": dp.get("operator"), "skill": dp.get("skill"),
                            "mech": MI.operator_mechanisms(conn, dp.get("operator"))})
        row["C_inventory"] = {"enemies": refs, "enemy_blackboard_keys": sorted(bb),
                              "enemy_skills": sorted(sk),
                              "option_keys": MI.option_keys(raw),
                              "operators": ops}
        print("C 清单：敌人 %d（黑板键 %d／技能 %d）／选项键 %d／干员 %d"
              % (len(refs), len(bb), len(sk), len(MI.option_keys(raw)), len(ops)))
        for o in ops:
            m = o["mech"] or {}
            print("       · %s（skill=%s → 技 %d）特性「%s」"
                  % (o["name"], o["skill"], int(o["skill"] or 1), m.get("trait")))

    print()
    print("★ 两栏并排读：`清单里有、痕迹里没有` ⇒ 要么没实现、要么本关触发条件不满足、"
          "要么走了别的键名（**未核 ≠ 没实现**）。工具不替你下这个结论。")
    if a.json:
        Path(a.json).write_text(json.dumps(row, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print("已写 %s" % a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
