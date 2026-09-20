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
    python tools\\golden_go.py                     # **默认只检查**（不再默认写基线）
    python tools\\golden_go.py --check             # 同上；与已有基线比对，有差则 rc=1
    python tools\\golden_go.py --write             # 首次建立基线（写，要显式说）
    python tools\\golden_go.py --extend            # 判据集长大了：先验已有的一致，再并入新的
    python tools\\golden_go.py --rebless --why "…"  # 已有条目换数（必须解释为什么）

⚠ **破坏性默认值是缺陷**：本脚本原先用 `"--x" in sys.argv` 判定，任何未知参数或打错字
都会掉进「无参数 ⇒ 重写基线」那条分支——`--help` 也能把基线静默重写（真发生过）。
现在改成 argparse：未知参数 ⇒ rc≠0 并列出可用开关；**不给动作时默认只检查**。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.plan import Plan, Roster                      # noqa: E402
from ak_tactic.simgo import build_spec                       # noqa: E402
#: ★ **闸门口径的唯一来源**（PM 裁定④ 2026-09-20「走乙」）。产物里的 `gate` 栏
#: 由它生成、由它校验：**与这里不符即 rc≠0**。
#: ⚠ 这里同时 import **模块本身**：校验时按**调用时刻**读那两个常量
#: （不是在 import 时刻快照）——否则「改了常量」这条判据会量到一个旧值上，
#: 而反向守卫也没法把它拨一下试试。
from ak_tactic.simgo import verifier as simgo_verifier          # noqa: E402
from ak_tactic.simgo.verifier import gate_declaration          # noqa: E402
from ak_tactic.verify import Verifier                        # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs               # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine_pin import EngineBuildError, ensure_pinned        # noqa: E402

OUT = ROOT / "out"
#: 判据集与基线**必须在版本控制里**（通告 #6 四）：`out/` 是易失的临时目录
#: （`.gitignore` 里有它），把门引用的夹具与金标准基线放在那儿，等于**门没有历史**
#: ——有人重跑覆盖基线，没有任何人会发现。所以 `fixtures/` 优先，`out/` 只作后备
#: （迁移期两处并存时以 `fixtures/` 为准）。
FIXTURES = ROOT / "fixtures"
GOLDEN = (FIXTURES / "golden_go.json") if FIXTURES.is_dir() else (OUT / "golden_go.json")


def _find(name: str) -> Path:
    """按名字找夹具。⚠ 要**带 .json 再试一遍**：`roster_max_modelled` 是别名，
    磁盘上叫 `roster_max_modelled.json`，而名册也可能落在姊妹 checkout
    （`ak-tactic-head/out/`）里——对拍三件套删掉之后，原来那份查找逻辑没了。"""
    names = [name] if name.endswith(".json") else [name, f"{name}.json"]
    for n in names:
        for cand in (FIXTURES / n, ROOT / "out" / n,
                     ROOT.parent / "ak-tactic-head" / "out" / n,
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
            self.spec = build_spec(SpecInputs.from_sim(sim), allow_devices=True)
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
        #: **量测三件套之①：仪器身份与输入身份**（判决/规格是「结果」，这两栏是「用谁测的」）。
        #: ⚠ 实证：同一份基线、同一批 19 份、同一条 `--check`，只因一枚是共享 exe（19:08 构建、
        #: 落后 16 个提交）一枚是当轮私有构建，`hsex8_max.json` 一处 814.0333s/591046.1、
        #: 一处 221.6667s/282276.8 ——**条目里没有这两栏时，事后无法归因**。
        #: 这两栏**只记录、不参与判定**（判定键见 `keys`）：换仪器导致的差异是「仪器差」，
        #: 不是「模型漂移」，读红绿之前先钉仪器。
        "engine_bin": engine_identity()[0],
        "engine_bin_sha16": engine_identity()[1],
        "engine_bin_mtime": engine_identity()[2],
        "roster_sha16": hashlib.sha256(Path(roster_file).read_bytes()).hexdigest()[:16],
        #: ★★ **量测三件套之外的第四栏：闸门口径**（PM 裁定④ 2026-09-20「走乙」）。
        #:
        #: `simgo/verifier.py` 一律 `allow_devices=True`，而 `simgo/spec.py:112-123`
        #: 写明这个口子**要带证据开** ⇒ **带装置的关，它的读数是在「装置运行期被
        #: 关掉」的前提下取的**。主线 433 行里 **196 行（45.3%）带装置**
        #: （`tools/mainline_devices.py`；表见 `docs/mainline-stages.md` §九）。
        #:
        #: ⚠ 这一栏**必须与四项读数同屏**——口径只活在散文里，下一个读的人不会去看它。
        #: 它同时是**可判的**：`--check` 会拿它跟 `simgo.verifier` 的现值逐位比，
        #: 不符即 rc≠0；缺栏也 rc≠0（守卫见 `gate_problems`）。
        "gate": getattr(v, "gate", None),
    }


def engine_identity() -> tuple[str, str, str]:
    """(文件名, sha16, mtime) —— 这台读数用的是什么可执行文件。"""
    raw = os.environ.get("RIOS_SIM_BIN", "").strip()
    p = Path(raw) if raw and Path(raw).exists() else (ROOT / "rios-sim" / "rios-sim.exe")
    if not p.exists():
        return "", "", ""
    return (p.name if raw else f"(默认){p.name}",
            hashlib.sha256(p.read_bytes()).hexdigest()[:16],
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)))


def plan_files() -> list[Path]:
    """判据集里的作业。**按 schema 认，不按文件名**：`deploys` + `stage` 两个键都在。

    ⚠ 按 `plan-*.json` 认名字会漏掉 `hsex8_max.json`（八人满练度深水用例，本树唯一
    能走到长线的那份）——据通告 #5 三迁入、#6 四随判据集一起进版本控制。
    """
    src = FIXTURES if FIXTURES.is_dir() else OUT
    found: list[Path] = []
    for p in sorted(src.glob("*.json")):
        if p.name == "golden_go.json":
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:                                        # noqa: BLE001
            continue
        if isinstance(d, dict) and "deploys" in d and "stage" in d:
            found.append(p)
    return found


def _parse_args():
    """⚠ **破坏性默认值是缺陷，不是风格。**

    这个脚本原先全是 `"--x" in sys.argv` 的成员判定：**任何未知参数或打错字都会掉进
    「无参数 ⇒ 重写基线」那条分支**——`--help` 也能把 `fixtures/golden_go.json` 静默重写
    （真发生过，靠 `git checkout` 还原）。修复判据：
      * 未知参数 / 拼错的开关 ⇒ **rc≠0 且列出可用开关**；
      * **不给动作时不再写基线**：默认动作改成 `--check`（只读），要写必须显式说。
    """
    ap = argparse.ArgumentParser(
        prog="golden_go.py",
        description="Go 金标准：判决四数 + 规格摘要（spec_sha）。**默认只检查，不写基线**。",
        epilog="写入类动作：--write（首次建基线）/ --extend（判据集长大）/ "
               "--rebless --why <理由>（已有条目换数）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true",
                   help="只与已有基线比对，有差则 rc=1（**默认动作**）")
    g.add_argument("--write", action="store_true", help="写基线（首次建立时用）")
    g.add_argument("--extend", action="store_true",
                   help="判据集长大：先验已有条目逐项一致，再并入新的")
    g.add_argument("--rebless", action="store_true",
                   help="已有条目换数（**必须**带 --why；会逐条打印 旧→新 并记台账）")
    g.add_argument("--backfill-gate", action="store_true",
                   help="只把 `gate` 栏补进已有基线（不重跑、不碰四数；幂等）")
    g.add_argument("--gate-selftest", action="store_true",
                   help="闸门口径那条判据的反向守卫（合成缺栏/改口径，必须变红）")
    ap.add_argument("--why", default="", help="换基线的理由（--rebless 必填）")
    return ap.parse_args()


def runtime_gate() -> dict:
    """**这一刻**实际生效的闸门口径（按调用时刻读常量，不 import 时快照）。"""
    return {
        "allow_devices": simgo_verifier.GATE_ALLOW_DEVICES,
        "allow_skills": simgo_verifier.GATE_ALLOW_SKILLS,
    }


#: `provenance` 只许这两个值——**不许把「不知道」塞进来**（三态要分开写）。
GATE_PROVENANCE = ("run", "backfill")


def gate_problems(entry: object, *, who: str) -> list[str]:
    """闸门口径那一栏的问题清单（空列表＝没问题）。**这就是裁定④那三条里的第②条。**

    判据三条，缺一条这栏就白记了：

    1. **缺栏即红**。`gate` 不在、或不是 dict ⇒ 问题。这就是裁定原话
       「当 `allow_devices` 被强制关（或将来被改成按证据开）时，该字段必须出现；
       **没出现即 rc≠0**」——**放宽判据必须同时写下它不能再接受什么**。
    2. **与运行期实际口径不符即红**。比 `allow_devices` / `allow_skills` 两个布尔。
       ⇒ 这才是"乙不是不判"：有人把 `simgo/verifier.py` 的常量改成按证据开，
       **基线当场响，不会静静过期**（否则改完口径，旧读数还挂着旧口径，没人知道）。
    3. **`provenance` 不是 `run` / `backfill` 之一即红**。两值分开是有意的：
       `run`＝这一栏是这次真跑抄的；`backfill`＝2026-09-20 回填（那些基线录的时候
       还没有这一栏，回填有据——见 `gate_declaration()` 的 docstring）。
    """
    if not isinstance(entry, dict):
        return []                       #: 别的形态（比如 `{"error": …}`）不归这条判据管
    got = entry.get("gate")
    if got is None:
        return [f"{who}：缺 `gate` 栏（闸门口径没被记下来 ⇒ 读的人不知道这一份的"
                f"「装置运行期已关」前提）"]
    if not isinstance(got, dict):
        return [f"{who}：`gate` 栏形状不对（{type(got).__name__}，应当是 dict）"]
    out: list[str] = []
    want = runtime_gate()
    for k, v in want.items():
        if got.get(k) != v:
            out.append(f"{who}：`gate.{k}` 记的是 {got.get(k)!r}，而**现在实际生效的是"
                       f" {v!r}** —— 口径变过而这份产物没跟着重录")
    if got.get("provenance") not in GATE_PROVENANCE:
        out.append(f"{who}：`gate.provenance`={got.get('provenance')!r} 不在 "
                   f"{list(GATE_PROVENANCE)} 里")
    return out


def gate_selftest() -> int:
    """**反向守卫**：合成输入 → 必须变红；不动它 → 必须为空。

    三种"该红的"各一条，外加**一条真把口径拨一下**的敏感性检查——最后那条才是关键：
    它证明第 2 条判据量的是**运行期的值**，而不是一个写死的常量。
    """
    print("=" * 78)
    print("闸门口径 · 反向守卫（合成输入 → 必须变红；不动它 → 必须为空）")
    print("=" * 78)
    ok = True

    good = {"gate": {**runtime_gate(), "ruling_ref": "x", "provenance": "run"}}
    n = len(gate_problems(good, who="控制组"))
    print(f"  控制组（原样）                  → {n} 条 {'✓' if n == 0 else '❌'}")
    ok &= (n == 0)

    cases = [
        ("缺 `gate` 栏", {"kills": 1}),
        ("`allow_devices` 被改过", {"gate": {**runtime_gate(), "allow_devices":
                                            not runtime_gate()["allow_devices"],
                                            "provenance": "run"}}),
        ("`provenance` 是三值外的东西", {"gate": {**runtime_gate(),
                                                 "provenance": "unknown"}}),
    ]
    for label, ent in cases:
        msgs = gate_problems(ent, who="敏感性")
        print(f"  敏感性（{label}） → {len(msgs)} 条"
              f"{'  ✓' if msgs else '  ❌ 该红没红'}")
        ok &= (len(msgs) > 0)

    #: ★ 敏感性②：把**真口径**拨一下，已录好的那一栏必须当场对不上。
    #: 没有这一条，判据可能只是「与一个写死的常量比」，改了常量它也不会响。
    saved = simgo_verifier.GATE_ALLOW_DEVICES
    try:
        simgo_verifier.GATE_ALLOW_DEVICES = not saved
        flipped = len(gate_problems(good, who="敏感性·拨常量"))
    finally:
        simgo_verifier.GATE_ALLOW_DEVICES = saved
    print(f"  敏感性（把 GATE_ALLOW_DEVICES 拨反）→ {flipped} 条"
          f"{'  ✓' if flipped else '  ❌ 判据没在量运行期的值'}")
    ok &= (flipped > 0)

    restored = len(gate_problems(good, who="还原"))
    print(f"  还原（拨回去）                  → {restored} 条 {'✓' if restored == 0 else '❌'}")
    ok &= (restored == 0)

    print()
    print("  ✓ 这栏红得起来、也绿得下来" if ok else "  ❌ 反向守卫不成立")
    return 0 if ok else 1


def backfill_gate() -> int:
    """把 `gate` 栏**补进已经录好的基线**：只补栏，**不重跑、不碰任何读数**。

    ## 为什么回填是合法的（有据，不是「我觉得」）

    那些基线录的时候这一栏还不存在。取证：

    * `allow_devices=True` 在 `ak_tactic/simgo/verifier.py` 里**只进来过一次**
      （`git log -S` 全历史只有 `046944a`，2026-09-19）；
    * 首个基线提交 `3bab699` **是 `046944a` 的后代**（`git merge-base --is-ancestor` rc=0），
      且 `3bab699` 那一版的 verifier.py **已经是 `True`**。

    ⇒ **23 份基线全部是在这个口径下录的**，没有一份是 `False` 录的。
    所以回填记的是**事实**，只是"这一栏不是当次现场抄的"——那份差别用
    `provenance: "backfill"` 写出来，**不冒充 `run`**。

    幂等：已经有栏的条目**一概不动**；有栏但与现口径不符 ⇒ **拒绝**（rc=2）。
    """
    if not GOLDEN.exists():
        print(f"❌ 没有基线可回填：{GOLDEN} 不存在")
        return 2
    base = json.loads(GOLDEN.read_text(encoding="utf-8"))
    want = runtime_gate()
    added, refused, kept = [], [], 0
    for name, ent in base.items():
        if not isinstance(ent, dict):
            continue
        if ent.get("gate") is not None:
            kept += 1
            if any(ent["gate"].get(k) != v for k, v in want.items()):
                refused.append(name)
            continue
        ent["gate"] = gate_declaration(provenance="backfill")
        added.append(name)
    print(f"  已有 `gate` 栏（不动）：{kept} 份；本次补上：{len(added)} 份；"
          f"口径不符：{len(refused)} 份")
    if refused:
        print(f"❌ 拒绝回填：{len(refused)} 份已有栏但与现口径不符"
              f"（{', '.join(sorted(refused)[:5])}）——它们要**重录**，不是补栏")
        return 2
    if not added:
        print(f"✅ 无栏可补（已经全部带上 `gate`）")
        return 0
    GOLDEN.write_text(json.dumps(base, ensure_ascii=False, indent=2, sort_keys=True),
                      encoding="utf-8")
    print(f"✅ 已给 {len(added)} 份补上 `gate`（provenance=backfill）"
          f"→ {GOLDEN.relative_to(ROOT)}")
    for n in sorted(added)[:5]:
        print(f"    {n}")
    if len(added) > 5:
        print(f"    … 另有 {len(added) - 5} 份")
    print("  ⚠ 只补了栏，**四数一栏都没动**；要复核就再跑一次 `--check`")
    return 0


def instrument_line() -> str:
    """**仪器身份**（量测三件套第一条）。

    ⚠ 这条不是装饰：实测过一次事故——同一条 `--check`、同一份基线、同一批 19 份，
    **只因为一个用了钉住的私有构建、一个走了默认（共享 exe）**，`hsex8_max.json` 一处绿一处红
    （221.6667s/282276.8 vs 814.0333s/591046.1）。**报告里没有仪器身份，两台仪器就会被当成一台。**
    """
    raw = os.environ.get("RIOS_SIM_BIN", "").strip()
    if raw and Path(raw).exists():
        p = Path(raw)
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        return f"RIOS_SIM_BIN 已钉：{p.name}（sha16 {h}，{p.stat().st_size}B）"
    shared = ROOT / "rios-sim" / "rios-sim.exe"
    if shared.exists():
        h = hashlib.sha256(shared.read_bytes()).hexdigest()[:16]
        stamp = time.strftime("%m-%d %H:%M", time.localtime(shared.stat().st_mtime))
        return (f"⚠ **未钉 RIOS_SIM_BIN** ⇒ 用的是共享 `{shared.relative_to(ROOT)}`"
                f"（sha16 {h}，构建于 {stamp}）——**它可能与基线不是同一台仪器**，"
                f"红/绿都先按仪器差读")
    return "⚠ **未钉 RIOS_SIM_BIN**，也没有共享 exe ⇒ 引擎来源不明"


def main() -> int:
    args = _parse_args()
    #: 这两条**不需要引擎**（一条只补栏、一条只验判据本身），所以挡在 `ensure_pinned()`
    #: 前面：否则「想看一眼这条判据红不红」要先付一次构建二进制的代价。
    if args.gate_selftest:
        return gate_selftest()
    if args.backfill_gate:
        return backfill_gate()
    check, extend, rebless = args.check, args.extend, args.rebless
    if not (check or extend or rebless or args.write):
        check = True          #: 默认＝只检查（**不再默认写基线**）
    why = args.why.strip()
    #: ⚠ **自建自钉**（`52c89a4` 之后 `find_binary()` 未设即抛）：本工具要跑 Go 引擎，
    #: 就不许让读数落到一枚来源不明的 exe 上；没钉就自己构建一枚再钉住。
    try:
        _exe, _sha, _sig = ensure_pinned()
    except EngineBuildError as e:
        print(f"❌ {e}")
        return 3
    print(f"仪器：{instrument_line()}")
    roster = _find("roster_max_modelled")
    roster = _find("roster_max_modelled")
    plans = plan_files()
    if not plans:
        raise SystemExit(f"{FIXTURES if FIXTURES.is_dir() else OUT} 下没有作业（deploys+stage）")

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

    if args.write:
        GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=2,
                                     sort_keys=True), encoding="utf-8")
        print(f"\n基线已写入 {GOLDEN.relative_to(ROOT)}（{len(got)} 份计划）")
        return 0

    if not GOLDEN.exists():
        raise SystemExit(f"没有基线可比：{GOLDEN} 不存在，首次建立请显式跑 `--write`")
    base = json.loads(GOLDEN.read_text(encoding="utf-8"))
    bad = 0
    #: ★ 闸门口径的问题数（裁定④ ②）。**与 `bad` 分开计数**：两种原因不许压成一个值。
    gate_bad = 0
    changes: list[tuple[str, dict]] = []
    keys = ["kills", "leaks", "elapsed", "damage", "spec_sha"]
    new_names: list[str] = []
    for name in sorted(set(base) | set(got)):
        b, g = base.get(name), got.get(name)
        #: ★ 闸门口径的判据（裁定④ ②）**放在「缺一边」分支之前**——这样
        #: `--extend` 收进来的新条目也会被盖到（新条目是从 `run_one` 来的，
        #: 它本来就该带栏；这条判据防的是「哪天有人把 `run_one` 那一栏删了」）。
        for who, ent in (("基线", b), ("现在", g)):
            if ent is None:
                continue
            for msg in gate_problems(ent, who=f"{name}·{who}"):
                gate_bad += 1
                print(f"  ❌ {msg}")
        if b is None or g is None:
            #: `--extend`：**判据集长大**（迁入新夹具）与「某一份不见了」是两件事。
            #: 新的一份照收；**丢了一份要报出来**——那通常意味着有人删了判据。
            if b is None and extend and g is not None:
                new_names.append(name)
                print(f"  ＋ {name}：基线里没有，按 --extend 收下"
                      f"（{g.get('kills')}杀 {g.get('leaks')}漏 {g.get('elapsed')}s）")
            else:
                bad += 1
                print(f"  ❌ {name}：一边缺（{'新' if b is None else '基线'}里没有）")
            continue
        diff = [k for k in keys if b.get(k) != g.get(k)]
        if diff:
            if rebless:
                changes.append((name, {k: (b.get(k), g.get(k)) for k in diff}))
                print(f"  ~ {name}：{'、'.join(diff)} 将换数")
                for k in diff:
                    print(f"        {k}: 旧={b.get(k)!r}  新={g.get(k)!r}")
            else:
                bad += 1
                print(f"  ❌ {name}：{'、'.join(diff)} 不一致")
                for k in diff:
                    print(f"        {k}: 基线={b.get(k)!r}  现在={g.get(k)!r}")
    if rebless:
        if not why:
            print(f"\n❌ 拒绝改基线：`--rebless` 必须带 `--why \"<为什么改>\"`"
                  f"——**改动必须被解释**，这正是不让基线被无声挪走的那道门")
            return 2
        errs = [n for n, g in got.items() if g.get("error")]
        if errs:
            print(f"\n❌ 拒绝改基线：{len(errs)} 份这次**没跑成功**"
                  f"（{', '.join(errs[:3])}{'…' if len(errs) > 3 else ''}）"
                  f"——失败不许写成基线")
            return 1
        merged = dict(base)
        merged.update(got)
        GOLDEN.write_text(json.dumps(merged, ensure_ascii=False, indent=2,
                                     sort_keys=True), encoding="utf-8")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log = ROOT / "out" / "acceptance" / "golden-rebless.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== {stamp}（{len(changes)} 份换数 / 基线共 {len(merged)} 份）\n")
            fh.write(f"理由：{why}\n")
            for name, ch in changes:
                fh.write(f"  {name}: " + "; ".join(f"{k} {a}→{b}" for k, (a, b) in ch.items())
                         + "\n")
        print(f"\n✅ 已按理由改基线：{len(changes)} 份换数（共 {len(merged)} 份）；"
              f"台账 `{log.relative_to(ROOT)}`")
        return 0
    if extend:
        if bad or gate_bad:
            print(f"\n❌ 拒绝扩展：已有 {bad} 份与基线不一致、另有 {gate_bad} 条"
                  f"闸门口径问题——扩展**不许**顺手掩盖改动")
            return 1
        merged = dict(base)
        merged.update({n: got[n] for n in new_names})
        GOLDEN.write_text(json.dumps(merged, ensure_ascii=False, indent=2,
                                     sort_keys=True), encoding="utf-8")
        print(f"\n✅ 已有 {len(base)} 份逐项一致；新增 {len(new_names)} 份已并入 "
              f"{GOLDEN.relative_to(ROOT)}（共 {len(merged)} 份）")
        return 0
    print(f"\n{'❌ 有 %d 份不一致' % bad if bad else '✅ 全部 %d 份与基线逐项一致' % len(base)}")
    #: ★ 闸门口径一栏单独报——**它红的时候不该被读成「读数漂了」**（两种因不许压成一个值）。
    if gate_bad:
        print(f"❌ 另有 {gate_bad} 条**闸门口径**问题（见上面每行的 `gate` 那条）——"
              f"这不是判决漂移，是**这一份读数挂在哪个口径下**没记全/记错了；"
              f"口径原文见 `ak_tactic/simgo/verifier.py` 顶部（PM 裁定④ 2026-09-20「走乙」）")
    else:
        print(f"✅ 闸门口径一栏：{len(base)} 份都有、且与运行期实际口径一致"
              f"（allow_devices={runtime_gate()['allow_devices']}、"
              f"allow_skills={runtime_gate()['allow_skills']}）")
    #: 仪器身份**只报不判**：与基线记的不同 ⇒ 这是「仪器差」，不是「模型漂移」
    idiff = [(n, base[n].get("engine_bin_sha16"), got[n].get("engine_bin_sha16"))
             for n in sorted(set(base) & set(got))
             if base[n].get("engine_bin_sha16") and got[n].get("engine_bin_sha16")
             and base[n]["engine_bin_sha16"] != got[n]["engine_bin_sha16"]]
    if idiff:
        b = sorted({x[1] for x in idiff})
        g = sorted({x[2] for x in idiff})
        print(f"⚠ **仪器与基线记录不同**（{len(idiff)} 份）：基线记的 {b} ↔ 这次用的 {g}"
              f"——**这不是漂移**，是仪器差；要判红绿先把二进制钉成基线那一枚")
    if bad and "未钉" in instrument_line():
        print("⚠ **先看上面那行仪器身份**：未钉 RIOS_SIM_BIN 时，这份红**不能当源码差**读"
              "——换一枚二进制就可能翻绿（实测：同一批 19 份、同一份词表，"
              "共享 exe 红 1 份、私有构建全绿）。要归因就先钉住二进制再跑一次。")
    return 1 if (bad or gate_bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
