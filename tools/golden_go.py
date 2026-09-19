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
        #: **量测三件套之①：仪器身份与输入身份**（判决/规格是"结果"，这两栏是"用谁测的"）。
        #: ⚠ 实证：同一份基线、同一批 19 份、同一条 `--check`，只因一枚是共享 exe（19:08 构建、
        #: 落后 16 个提交）一枚是当轮私有构建，`hsex8_max.json` 一处 814.0333s/591046.1、
        #: 一处 221.6667s/282276.8 ——**条目里没有这两栏时，事后无法归因**。
        #: 这两栏**只记录、不参与判定**（判定键见 `keys`）：换仪器导致的差异是"仪器差"，
        #: 不是"模型漂移"，读红绿之前先钉仪器。
        "engine_bin": engine_identity()[0],
        "engine_bin_sha16": engine_identity()[1],
        "engine_bin_mtime": engine_identity()[2],
        "roster_sha16": hashlib.sha256(Path(roster_file).read_bytes()).hexdigest()[:16],
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
    ap.add_argument("--why", default="", help="换基线的理由（--rebless 必填）")
    return ap.parse_args()


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
    changes: list[tuple[str, dict]] = []
    keys = ["kills", "leaks", "elapsed", "damage", "spec_sha"]
    new_names: list[str] = []
    for name in sorted(set(base) | set(got)):
        b, g = base.get(name), got.get(name)
        if b is None or g is None:
            #: `--extend`：**判据集长大**（迁入新夹具）与"某一份不见了"是两件事。
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
        if bad:
            print(f"\n❌ 拒绝扩展：已有 {bad} 份与基线不一致——扩展**不许**顺手掩盖改动")
            return 1
        merged = dict(base)
        merged.update({n: got[n] for n in new_names})
        GOLDEN.write_text(json.dumps(merged, ensure_ascii=False, indent=2,
                                     sort_keys=True), encoding="utf-8")
        print(f"\n✅ 已有 {len(base)} 份逐项一致；新增 {len(new_names)} 份已并入 "
              f"{GOLDEN.relative_to(ROOT)}（共 {len(merged)} 份）")
        return 0
    print(f"\n{'❌ 有 %d 份不一致' % bad if bad else '✅ 全部 %d 份与基线逐项一致' % len(base)}")
    #: 仪器身份**只报不判**：与基线记的不同 ⇒ 这是"仪器差"，不是"模型漂移"
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
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
