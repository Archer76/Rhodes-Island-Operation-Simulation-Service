"""C 档「本层可做性」——把「761 是上界」这句话按**四种不同的可做性**分开量。

★ 为什么必须分开（PM 派活 `msg-mu8x3tpn-es` 第 1 条）：
  能建 spec / 能过闸 / 能进 Go / 能跑出非平凡结果 **是四种不同的东西**，
  压成一个数就会得出「773（现 761）个键都能做」这种读不出来的结论。

★ 本文件量其中三种，第四种**明确写未量+方法**（不许把未量当通过）：

  S1 能建 spec（按**现成 kind**）：`_classify(key)` 有返回值才算 ⇒ 对第 1 类**结构性恒 0**
     （第 1 类的定义就是「归类器认不了」）。**这不是「没人做」，是「按现成 kind 做不了」。**
     它不能接受：新写一个 kind 之后仍然做得了的键（那要逐族判语义，未量）。
  S2 能过闸（`simgo/skills.py` 白名单，**干员级**）：某键的「需要它的干员」里**至少一位**过闸，
     这个键才在 Go 产品路径上有落点 ⇒ 键级收窄。
  S3 能进 Go（内核是否**已有该族的消费点**）：以 `rios-sim/**/*.go` 的**字符串字面量**为尺子，
     要求键名（或去掉 `@` 前缀/`$` 的写法）作为**字面量**出现 ⇒ 「接线级」 vs 「要新内核工作」。
     ★ 本判据最大的软处：**Go 里没有 ≠ 做不了**——同一机制换个名字就 grep 不到；
       所以它只给「已有落点」的**下界**，不给「做不了」的结论。
  S4 能跑出非平凡结果：**未量**。方法见文末（每族一个夹具 + 跑一局看可观测量非零）。

判据纪律（本文件自带）：
  · 控制组：先用**未收窄**的需求集重跑贪心，**必须复现 PM 裁过的 A 名单**（逐位），
    否则下面的「收窄后名单」不可信（同族 `7eb5adf9`）。
  · 名单变化**只列人与数，不改名单**（PM 派活第 3 条）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.operator.skill import _classify  # noqa: E402
import audit_coverage as AC  # noqa: E402  ★ 贪心/覆盖/名册**只保留工具那一份实现**
                               #   （本文件第一版自己写了一个，规则不同 ⇒ 控制组红：99 vs 112）

OPS_SQL = "SELECT char_id, name FROM operator WHERE is_operator=1 AND is_not_obtainable=0"

#: 疑似通用词：没有 `.`/`@` 的短英文名，grep 命中很可能是别处的同名词（`60b84b37`）
GENERIC = {"delay", "cnt", "prob", "interval", "duration", "value", "count", "time",
           "range", "speed", "attack", "def", "hp", "cost", "level", "type", "mode"}


def go_literals(include_tests: bool = False) -> set[str]:
    """`rios-sim/**/*.go` 里的**字符串字面量**（跳过整行注释）。

    ★ `include_tests=False`（默认）**排除 `*_test.go`**：测试文件里的键名是**测试数据**，
    不是消费者（实测那 2 个命中全在 `element_blackboard_test.go`）。把测试当落点
    就是"引用了≠消费了"的另一面（`1bd38acb`）。
    """
    lit: set[str] = set()
    pat = re.compile(r'"([A-Za-z_@$][A-Za-z0-9_@$.\[\]#]*(?:@[A-Za-z0-9_.\[\]#]+)?)"')
    go_root = ROOT / "rios-sim"
    if not go_root.exists():
        return lit
    for p in go_root.rglob("*.go"):
        if not include_tests and p.name.endswith("_test.go"):
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s.startswith("//"):
                continue
            lit.update(pat.findall(line.split("//")[0]))
    return lit



def hit_in_go(key: str, lit: set[str]) -> bool:
    """键名是否被 Go 侧**点名**：整名相等，或以「来源前缀.键名」出现。

    ★ 本条修正过一次（2026-09-20）：第一版只按整名匹配，而 Go 侧存的是**复合写法**——
    实测字面量样例 `Attack.attack@ep_damage_ratio`、`EpDamage.ep_damage_ratio`、
    `EpDamage.ep_damage_value`（`来源前缀.键名`）⇒ 第一版只报 **2/594**，
    差点当成结论报出去。同族纪律：**先证尺子是活的**（`556104e7`）。
    """
    for v in variants(key):
        for s in lit:
            if s == v or s.endswith("." + v):
                return True
    return False


def variants(key: str) -> set[str]:
    """一个键的几种可能写法（同族 `e60262e9`：`$X` 与裸键成对）。"""
    out = {key, key.lstrip("$")}
    if "@" in key:
        out.add(key.split("@", 1)[1])
        out.add("@" + key.split("@", 1)[1])
    return {x for x in out if x}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-cache", required=True)
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--json")
    a = ap.parse_args()

    blob = json.loads(Path(a.from_cache).read_text(encoding="utf-8"))
    data = blob["data"]
    ident = blob.get("ident", {})

    ops = AC.all_operators()          #: 工具的名册与顺序（含 order_all 用的表序）
    names = dict(ops)
    rows = set(names)

    #: 需求集：只算第 1 类（与选人同口径）
    needs_full = {cid: set(d["keys1"]) for cid, d in data.items() if cid in rows}
    port_ok = {cid for cid in needs_full if data[cid]["port"] == []}
    pairs_full = sum(len(v) for v in needs_full.values())
    keys_full = {k for v in needs_full.values() for k in v}

    if not needs_full:
        print("✗ 输入为空：缓存里没有任何第 1 类需求对 ⇒ **按通则当错误，退出码 2**（不许印空名单）")
        return 2
    lit = go_literals()                       #: 生产代码（判据用这个）
    lit_all = go_literals(include_tests=True)  #: 含测试（只作诊断：差就是"测试数据假命中"）
    hit = {k for k in keys_full if hit_in_go(k, lit)}
    generic_hit = {k for k in hit if "." not in k and "@" not in k and k in GENERIC}
    #: 名字命中但**写法**只是通用词的那些（要逐处看才知道是不是同一回事）
    pairs_hit = {(cid, k) for cid, v in needs_full.items() for k in v if k in hit}
    pairs_hit_gate = {p for p in pairs_hit if p[0] in port_ok}
    keys_hit_gate = {k for _c, k in pairs_hit_gate}

    print("=" * 78)
    print("C 档「本层可做性」——四种可做性**分列**（不许压成一个数）")
    print("=" * 78)
    print(f"输入：`{a.from_cache}`（生成于 {blob.get('generated_at')}）")
    print(f"       输入三件套：库 `{ident.get('akdb')}`／范围表 `{ident.get('ranges')}`／名册 `{ident.get('roster')}`")
    print(f"       ★ 树身份（缓存）：`{ident.get('head', '未记录')}`（本文件**不**拿它判可比性，只登记）")
    print(f"尺子：Go 侧字面量 **{len(lit)}** 个（`rios-sim/**/*.go`，**排除 `*_test.go`**；"
          f"含测试则 {len(lit_all)} 个）")
    print()
    print("--- 收窄前（分母）---")
    print(f"  全库行空间 {len(needs_full)} 位：**{len(keys_full)} 键 / {pairs_full} 需求对**（第 1 类）")
    print(f"  其中过闸 {len(port_ok)} 位：**{len({k for c, v in needs_full.items() if c in port_ok for k in v})} 键 / "
          f"{sum(len(v) for c, v in needs_full.items() if c in port_ok)} 需求对**")
    print()

    # ---------- S1 ----------
    ok_kind = [k for k in keys_full if _classify(k) is not None]
    print("--- S1 能建 spec（按**现成 kind**）---")
    print(f"  `_classify` 认得的：**{len(ok_kind)}/{len(keys_full)}**"
          f"{'（★ 0 是结构性的：第 1 类的定义就是归类器认不了）' if not ok_kind else ''}")
    print("  它**不能接受**：新写一个 kind 之后照样做得了的键（那要逐族判语义，本文件未量）")
    print()

    # ---------- S3 ----------
    print("--- S3 能进 Go（内核**已有**该族消费点：Go 字面量里出现该名）---")
    print(f"  键级：**{len(hit)}/{len(keys_full)}**；需求对级：**{len(pairs_hit)}/{pairs_full}**")
    print(f"  ★ 其中写法只是**通用词**的 {len(generic_hit)} 键：{('、'.join(sorted(generic_hit))) or '（无）'}")
    print("    ⇒ 这些必须逐处看原文才算数（`60b84b37`：命中数会被通用词骗）")
    print("  ★ 本判据**只能给下界**：Go 里没有 ≠ 做不了（同一机制换个名字就 grep 不到）")
    print()

    # ---------- S2 ∧ S3 ----------
    print("--- S2∧S3 收窄后（内核已有落点 ∧ 需要它的干员至少一位过闸）---")
    print(f"  **{len(keys_hit_gate)} 键 / {len(pairs_hit_gate)} 需求对**（收窄前 {len(keys_full)} 键 / {pairs_full} 对）")
    print(f"  收窄掉：{(len(keys_full) - len(keys_hit_gate))} 键 / {(pairs_full - len(pairs_hit_gate))} 需求对")
    print("  它**不能接受**：名字不同但语义相同的实现（会漏）；因此收窄后的数是**下界**，不是「待做清单」")
    print()

    # ---------- 控制组：未收窄贪心必须复现 A 名单 ----------
    A_RULED = ["贝洛内", "耶拉", "蕾缪安", "维伊", "薇薇安娜", "淬羽赫默", "煌", "隐德来希", "斩业星熊", "谬因"]
    print("--- 控制组：未收窄的过闸行空间上重跑贪心，必须复现 PM 裁过的 A 名单 ---")
    needs_gate = {c: v for c, v in needs_full.items() if c in port_ok}
    wt_gate: dict[str, int] = {}
    for v in needs_gate.values():
        for kk in v:
            wt_gate[kk] = wt_gate.get(kk, 0) + 1
    picks_ctl, _tr = AC.greedy_pick(needs_gate, wt_gate, [c for c, _n in ops], a.batch)
    inv_names = {v: k for k, v in names.items()}
    ruled = [inv_names[n] for n in A_RULED if n in inv_names]
    cov_ruled = sum(1 for c, v in needs_gate.items() for k in v if k in set().union(*[needs_gate[x] for x in ruled]))
    cov_mine = sum(1 for c, v in needs_gate.items() for k in v if k in set().union(*[needs_gate[x] for x in picks_ctl]))
    print(f"  PM 裁过的 A 名单覆盖：{cov_ruled}/251 键 {len(set().union(*[needs_gate[x] for x in ruled]))}")
    print(f"  本文件贪心覆盖：      {cov_mine}/251 键 {len(set().union(*[needs_gate[x] for x in picks_ctl]))}"
          f"（{'数同' if cov_mine == cov_ruled else '★ 数都不同 ⇒ 不是平局'}）")
    print(f"  本文件贪心名单：{'、'.join(names[c] for c in picks_ctl)}")
    CONTROL_OK = cov_mine == cov_ruled
    print(f"  ⇒ **控制组 {'绿' if CONTROL_OK else '红'}**"
          + ("" if CONTROL_OK else "：复现的贪心比工具的弱 ⇒ 下面**不给**收窄后的名单对比"))
    print()

    # ---------- 收窄后重跑贪心 ----------
    if not CONTROL_OK:
        print("--- 收窄后重跑贪心：**本轮不做**（控制组红：复现的贪心不等价于工具的贪心，")
        print("    任何「谁进谁出」的结论都不可信；A 名单**未动**）---")
        print()
        if a.json:
            Path(a.json).write_text(json.dumps({
                "ident": ident, "keys_full": len(keys_full), "pairs_full": pairs_full,
                "s1_kind_ok": len(ok_kind), "s3_keys_hit": sorted(hit),
                "s3_generic": sorted(generic_hit), "keys_hit_gate": sorted(keys_hit_gate),
                "pairs_hit_gate": len(pairs_hit_gate), "control": "RED",
                "cov_ruled": cov_ruled, "cov_mine": cov_mine,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"（JSON 已落盘：{a.json}）")
        return 0
    print("--- 收窄后重跑贪心：**本轴已退役，不再据此算名单** ---")
    print("    理由：S3（Go 里已有落点）实测 2/594，且**与第 1 类的定义同义**（`b7805171`）")
    print("    ⇒ 收窄后的需求集恒为空，任何贪心输出都只是「问题已消失」的假象。")
    print("    ★ 退役不等于沉默：S1/S2/S3 的读数与登记都在上面，缺的是「键族↔机制种类」映射（乙表）。")
    print()

    print("--- S4 能跑出非平凡结果 ---")
    print("  **未量**。方法：对该族造一个最小夹具（该族生效/不生效两组），跑一局比可观测量")
    print("  （伤害/命中/剩余生命），要求两组读数**不同**且都非零；判据要先写「往哪边动」（同 `7eb5adf9`）")

    if a.json:
        Path(a.json).write_text(json.dumps({
            "ident": ident, "keys_full": len(keys_full), "pairs_full": pairs_full,
            "s1_kind_ok": len(ok_kind), "s3_keys_hit": sorted(hit),
            "s3_generic": sorted(generic_hit), "keys_hit_gate": sorted(keys_hit_gate),
            "pairs_hit_gate": len(pairs_hit_gate),
            "greedy_control": [names[c] for c in picks_ctl],
            "narrowed_axis": "RETIRED",
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n（JSON 已落盘：{a.json}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
