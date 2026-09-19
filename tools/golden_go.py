#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Go 金标准：把"切换后这一版"的判决与规格摘要固化成基线，供**摘除 `ak_tactic/battle/`**
的迁移期做逐项比对。

## 为什么现在就要做

下一步要把 `build_spec` 从"读一个活的 `BattleSimulator`"改成"从 gamedata + 计划 +
干员计算器直接构建"，并最终删掉 `battle/`（9280 行）。这类改动的典型事故是
**规格悄悄变了但判决没变**（或反过来），而原版对拍三件套已经按裁定删除了——
没有基线，迁移之后"一致"这两个字就无从检验。

⚠ 基线的口径是 **Go 自己**（不是 Go vs Python）：`battle/` 即将不存在，
留着的 Python 数字没有复核能力。这份基线记的是"迁移前 Go 在这些计划上算出什么"。

## 记什么

每份计划两样：

* **判决四数**：杀 / 漏 / 用时 / 伤害 —— 排序档用的就是它们。
* **规格摘要**：`build_spec` 产出的整份 dict 的规范化 SHA-256（`sort_keys=True`）。
  规格是这次要重写的东西，所以它必须被哈希；只比判决会漏掉"规格变了但这一局
  恰好没受影响"。

## 怎么拿到规格

`build_spec(sim)` 要一个**排好程、还没跑**的 `sim`，而排程住在 `Verifier.run` 里。
不复制那段逻辑，而是**借它的挂载点**：`_run_other_engine(sim=...)` 拿到的就是那个
排好程的 sim。子类在那个点上抄一份规格，再把活交回给基类走 Go。

用法:
    python tools\\golden_go.py                 # 跑 out/plan-*.json，写到 out/golden_go.json
    python tools\\golden_go.py --check         # 与已有基线比对，有差则退出码 1
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.plan import Plan, Roster                      # noqa: E402
from ak_tactic.simgo import build_spec                       # noqa: E402
from ak_tactic.verify import Verifier                        # noqa: E402

OUT = ROOT / "out"
GOLDEN = OUT / "golden_go.json"


def _find(name: str) -> Path:
    """按名字找夹具。⚠ 要**带 .json 再试一遍**：`roster_max_modelled` 是别名，
    磁盘上叫 `roster_max_modelled.json`，而名册也可能落在姊妹 checkout
    （`ak-tactic-head/out/`）里——对拍三件套删掉之后，原来那份查找逻辑没了。"""
    names = [name] if name.endswith(".json") else [name, f"{name}.json"]
    for n in names:
        for cand in (ROOT / "out" / n, ROOT.parent / "ak-tactic-head" / "out" / n,
                     ROOT / n, ROOT / "data" / "skland" / n):
            if cand.exists():
                return cand
    raise SystemExit(f"找不到：{name}（试过 {names}）")


class SpecCapture(Verifier):
    """在"排好程、还没跑"那个点上抄一份规格，然后照常走 Go。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.spec = None
        self.spec_error = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title,
                          schedule=None, **kw):
        """⚠ 必须收 `**kw`：基类的这个钩子**加过参数**（`schedule`），
        而本类只是"路过抄一份规格"。写死签名会让基类一加参数、这里就
        `TypeError`，而它会被 `spec_error` 记成"规格抄不到"——
        **工具的红被读成代码的红**，正是本项目反复吃亏的那类假信号。
        """
        try:
            self.spec = build_spec(sim, allow_devices=True)
        except Exception as e:                                # noqa: BLE001
            #: 抄不到不是这一路的事——照实记下，让基类继续把这一局跑完。
            self.spec_error = f"{type(e).__name__}: {e}"
        # 交回给基类：它会 ensure_go_engine，再走混入类那一份（不是本方法）。
        return Verifier._run_other_engine(self, sim=sim, plan=plan, stage=stage,
                                          deployed=deployed, title=title)


def canonical_sha(obj) -> str:
    """规范化摘要。**不哈希活对象**——只哈希它的 JSON 投影。"""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def run_one(plan_file: Path, roster_file: Path) -> dict:
    raw = json.loads(plan_file.read_text(encoding="utf-8-sig"))
    v = SpecCapture()
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(roster_file)
    r = v.run(plan, roster=roster)
    return {
        "kills": r.kills, "leaks": r.leaks,
        "elapsed": round(float(r.elapsed), 4),
        "damage": round(float(r.damage), 1),
        "engine": v.engine,
        "go_runs": getattr(v, "go_runs", None),
        "go_fallbacks": getattr(v, "go_fallbacks", None),
        "spec_sha": canonical_sha(v.spec) if v.spec is not None else None,
        "spec_error": v.spec_error,
    }


def main() -> int:
    check = "--check" in sys.argv
    roster = _find("roster_max_modelled")
    plans = sorted(OUT.glob("plan-*.json"))
    if not plans:
        raise SystemExit("out/ 下没有 plan-*.json")

    got: dict[str, dict] = {}
    for p in plans:
        try:
            got[p.name] = run_one(p, roster)
            g = got[p.name]
            print(f"  {p.name:<22} {g['kills']}杀 {g['leaks']}漏 "
                  f"{g['elapsed']:.4f}s {g['damage']:.1f}  "
                  f"spec={'—' if g['spec_sha'] is None else g['spec_sha'][:12]}")
            if g["spec_error"]:
                print(f"        ⚠ 抄规格失败：{g['spec_error']}")
        except Exception as e:                                # noqa: BLE001
            got[p.name] = {"error": f"{type(e).__name__}: {e}"}
            print(f"  {p.name:<22} ❌ {type(e).__name__}: {e}")

    if not check:
        GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=2,
                                     sort_keys=True), encoding="utf-8")
        print(f"\n基线已写入 {GOLDEN.relative_to(ROOT)}（{len(got)} 份计划）")
        return 0

    if not GOLDEN.exists():
        raise SystemExit(f"没有基线可比：{GOLDEN} 不存在，先跑一次不带 --check 的")
    base = json.loads(GOLDEN.read_text(encoding="utf-8"))
    bad = 0
    keys = ["kills", "leaks", "elapsed", "damage", "spec_sha"]
    for name in sorted(set(base) | set(got)):
        b, g = base.get(name), got.get(name)
        if b is None or g is None:
            bad += 1
            print(f"  ❌ {name}：一边缺（{'新' if b is None else '基线'}里没有）")
            continue
        diff = [k for k in keys if b.get(k) != g.get(k)]
        if diff:
            bad += 1
            print(f"  ❌ {name}：{'、'.join(diff)} 不一致")
            for k in diff:
                print(f"        {k}: 基线={b.get(k)!r}  现在={g.get(k)!r}")
    print(f"\n{'❌ 有 %d 份不一致' % bad if bad else '✅ 全部 %d 份与基线逐项一致' % len(base)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
