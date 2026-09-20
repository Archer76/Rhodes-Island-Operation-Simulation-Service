#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""怀黍离补齐 · 归因探针（**只读**：不跑引擎、不写判据集）。

用途：给「18 关零作业」逐关取证**先卡在哪一环**。四类成因是四件不同的事
（数据 / 夹具 / 基线 / 机制），本工具只负责其中能被机械取到的两件：

1. `--data`   ：关卡数据取不取得到（走 `level_index` ＋ 本树缓存目录，两侧分列）。
2. `--spec`   ：拿一份**已有夹具**（或 `--stage` 覆写关卡号）建一次规格，
                把闸门面摆出来：`unsupported` / `mechanisms` / `fallback` /
                `environment_difficulty` / `spec_sha`。

★ 为什么要有 `--stage` 覆写：`#f#`（四星限定）在关卡索引里是**独立条目**、
   但 `data_path` 与普通版**同一个文件**（实测 12 份全部如此）。于是
   「把同一份作业的 stage 改成 `<base>#f#`」正好是**检验难度轴接没接线**的
   最小实验：规格与判决若与普通版**逐位相同**，就是"变量没生效"
   （记忆 `06192463` 那一类：变体读数逐位相同＝变量没生效）。

⚠ 本工具**不跑引擎**：`SpecProbe._run_other_engine` 里抄完规格就
   `raise SystemExit(0)`（与 `tools/parity_plan.py` 的 `GoCapture` 同一手法），
   所以没有仪器身份这回事——它量的是**规格**，不是判决。判决读数请用
   `tools/gate_ledger.py` / `tools/golden_go.py`（那两个会钉引擎）。

用法:
    python tools\\hsl_backfill_probe.py --data
    python tools\\hsl_backfill_probe.py --spec fixtures\\plan-hsex01.json
    python tools\\hsl_backfill_probe.py --spec fixtures\\plan-hsex01.json --stage act31side_ex01#f#
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.frontend.inputs import SpecInputs          # noqa: E402
from ak_tactic.plan import DeployOrder, Plan, Roster      # noqa: E402
from ak_tactic.simgo import build_spec                    # noqa: E402
from ak_tactic.verify import Verifier                     # noqa: E402

FIXTURES = ROOT / "fixtures"
CACHE = ROOT / "data" / "gamedata" / "map.ark-nights.com" / "levels" / "activities"

#: 全量口径的**唯一权威来源**：关卡索引里 `act31side` 前缀的条目（36 条）。
INDEX = ROOT / "data" / "gamedata" / "_level_index.json"


def canonical_sha(obj) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class SpecProbe(Verifier):
    """抄一份规格就撤——**不跑任何引擎**。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.held: tuple | None = None
        self.spec_error: str | None = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title,
                          schedule=None, env=None, **kw):
        try:
            self.held = (stage, build_spec(SpecInputs.from_sim(sim),
                                           allow_devices=True,
                                           schedule=schedule, env=env))
        except Exception as e:                                  # noqa: BLE001
            self.spec_error = f"{type(e).__name__}: {e}"
        raise SystemExit(0)


def do_data(args) -> int:
    """逐关列出：索引条目 / data_path / 缓存文件在不在。"""
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    rows = {k: v for k, v in index.items() if k.startswith("act31side")}
    if args.stage:
        rows = {k: v for k, v in rows.items() if args.stage in k}
    print(f"关卡索引里的 act31side 条目：{len(rows)} 条"
          f"（来源 {INDEX.relative_to(ROOT)}）")
    n_cache = n_missing = 0
    for k in sorted(rows):
        path = rows[k]["data_path"]
        f = (ROOT / "data" / "gamedata" / "map.ark-nights.com"
             / "levels" / path)
        ok = f.exists()
        if ok:
            n_cache += 1
        else:
            n_missing += 1
        print(f"  {k:24} {rows[k]['difficulty']:10} {path:52} "
              f"{'缓存有 ' + str(f.stat().st_size) + 'B' if ok else '缓存无（源上有索引）'}")
    print(f"\n索引 {len(rows)} 条；本树缓存命中 {n_cache} 条、未取 {n_missing} 条")
    print("⚠ 分母是**索引**不是缓存目录：缓存只反映'过去谁取过'"
          "（记忆 d785c3f8）。")
    return 0


def do_spec(args) -> int:
    src = Path(args.spec)
    if not src.is_absolute():
        src = ROOT / src
    raw = json.loads(src.read_text(encoding="utf-8-sig"))
    if args.stage:
        raw = dict(raw, stage=args.stage)
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(ROOT / "fixtures" / "roster_max_modelled.json")
    p = SpecProbe()
    try:
        p.run(plan, roster=roster)
    except SystemExit:
        pass
    print(f"夹具 {src.name} → stage={plan.stage}（{len(plan.deploys)} 手）")
    if p.held is None:
        print(f"  ❌ 规格建不出来：{p.spec_error}")
        return 1
    stage, spec = p.held
    uns = list(spec.get("unsupported") or [])
    print(f"  关卡对象的 difficulty = {getattr(stage, 'difficulty', '<无此属性>')!r}")
    print(f"  spec['environment_difficulty'] = {spec.get('environment_difficulty')!r}")
    print(f"  unsupported ×{len(uns)}")
    for u in uns:
        print(f"      · {u}")
    print(f"  mechanisms = {spec.get('mechanisms')}")
    print(f"  families   = {spec.get('families')}")
    print(f"  出怪表 {len(spec.get('spawns') or [])} 条；装置 "
          f"{len(spec.get('device_deployments') or spec.get('devices') or [])} 项")
    print(f"  spec_sha = {canonical_sha(spec)}")
    return 0


def _auto_plan(v: SpecProbe, stage_id: str, roster: Roster) -> Plan:
    """**没有夹具的关**也要能建规格：用本关自己的可部署格凑一份最小作业。

    用途只有一个是正当的：把 `spec['unsupported']` / `mechanisms` 摆出来，
    看这一关**要的机制面**在哪一条闸门上。它**不是**一份打法——判决读数
    不能拿这份东西报（它没打算赢）。
    """
    stage = v.stage(stage_id)
    melee, ranged = stage.map.melee_spots, stage.map.ranged_spots
    if not melee:
        raise SystemExit(f"{stage_id}：本关没有地面可部署格，凑不出最小作业")

    def pick(want_melee: bool) -> str | None:
        for n in roster.names():
            e = roster.get(n) or {}
            if not e.get("char_id"):
                continue
            if bool(v.is_melee(e["char_id"])) is want_melee:
                return n
        return None

    m = pick(True)
    r = pick(False) if ranged else None
    if not m:
        raise SystemExit(f"{stage_id}：名册里挑不出地面干员")
    print(f"  [凑作业] 本关地面格 {len(melee)} 个、高台格 {len(ranged)} 个")
    ds = [DeployOrder(m, melee[0])]
    if r and ranged[0] != melee[0]:
        ds.append(DeployOrder(r, ranged[0]))
    return Plan(stage=stage_id, deploys=ds,
                title="探针用最小作业（不入判据集）")


def do_auto(args) -> int:
    """对**没有夹具**的关卡建一次规格（用本关自己的可部署格凑最小作业）。"""
    roster = Roster.from_json(ROOT / "fixtures" / "roster_max_modelled.json")
    for sid in args.auto:
        v = SpecProbe()
        try:
            plan = _auto_plan(v, sid, roster)
        except SystemExit as e:
            print(f"{sid}: {e}")
            continue
        except Exception as e:                                  # noqa: BLE001
            print(f"{sid}: 取关卡失败 {type(e).__name__}: {e}")
            continue
        v2 = SpecProbe()
        try:
            v2.run(plan, roster=roster)
        except SystemExit:
            pass
        except Exception as e:                                  # noqa: BLE001
            print(f"{sid}: 建规格抛错 {type(e).__name__}: {e}")
            continue
        print(f"{sid}:")
        if v2.held is None:
            print(f"  ❌ 规格建不出来：{v2.spec_error}")
            continue
        stage, spec = v2.held
        uns = list(spec.get("unsupported") or [])
        print(f"  difficulty={getattr(stage, 'difficulty', '<无此属性>')!r} "
              f"spec.environment_difficulty={spec.get('environment_difficulty')!r}")
        print(f"  unsupported ×{len(uns)}：{uns}")
        print(f"  mechanisms={spec.get('mechanisms')} "
              f"fallback={spec.get('fallback')} "
              f"spawns={len(spec.get('spawns') or [])}")
        print(f"  spec_sha={canonical_sha(spec)}")
    return 0


def do_zero_change(args) -> int:
    """**零变化证明**：新代码下，判据集里每一份夹具的 spec 与基线记的 spec_sha 比。

    规格是纯 Python 算的（不碰引擎），所以这一条能在**不跑引擎**的前提下
    证明「这次改动对既有 20 份一字未动」。
    """
    base = json.loads((FIXTURES / "golden_go.json").read_text(encoding="utf-8"))
    roster = Roster.from_json(FIXTURES / "roster_max_modelled.json")
    n_same = n_diff = n_missing = n_err = 0
    for p in sorted(FIXTURES.glob("*.json")):
        if p.name == "golden_go.json":
            continue
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
        if not (isinstance(raw, dict) and "deploys" in raw and "stage" in raw):
            continue
        want = (base.get(p.name) or {}).get("spec_sha")
        v = SpecProbe()
        try:
            v.run(Plan.from_dict(raw), roster=roster)
        except SystemExit:
            pass
        except Exception as e:                                  # noqa: BLE001
            print(f"  ❌ {p.name}: {type(e).__name__}: {e}")
            n_err += 1
            continue
        if want is None:
            print(f"  ⚠ {p.name}: 基线里没有这一份（新夹具？）")
            n_missing += 1
            continue
        got = canonical_sha(v.held[1]) if v.held else None
        if got == want:
            n_same += 1
        else:
            n_diff += 1
            print(f"  ❌ {p.name}: 规格变了 基线={want[:16]} 现在="
                  f"{(got or '')[:16]}")
    print(f"\n判据集 {n_same + n_diff} 份：spec_sha 一致 {n_same}、变了 {n_diff}、"
          f"基线缺 {n_missing}、抛错 {n_err}")
    return 1 if (n_diff or n_err) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", action="store_true", help="列关卡数据可达性")
    ap.add_argument("--spec", default="", help="建规格的夹具路径")
    ap.add_argument("--stage", default="", help="覆写 stage（如 act31side_ex01#f#）")
    ap.add_argument("--auto", nargs="*", default=None,
                    help="对没有夹具的关卡建规格（用本关可部署格凑最小作业）")
    ap.add_argument("--zero-change", action="store_true",
                    help="判据集 20 份的 spec_sha 与基线逐份对")
    args = ap.parse_args()
    if args.data:
        return do_data(args)
    if args.spec:
        return do_spec(args)
    if args.auto is not None:
        return do_auto(args)
    if args.zero_change:
        return do_zero_change(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
