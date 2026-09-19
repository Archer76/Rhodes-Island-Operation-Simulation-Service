#!/usr/bin/env python3
"""单点溯源：**逐帧追一只敌人的 HP 链**，把"某处值差"定性成「下游」还是「第二个独立分歧」。

## 为什么要单独一支工具（PM 2026-09-20 01:14 指令）

值序列（UI_2b 那边做）告诉你**全窗哪些点不同**；它**回答不了**"某一点是前面那笔的后果，
还是它自己就是一处新分歧"。判据口径（PM 原话）：

* **下游** ⇒ 必须能指出它是前一笔的**传播路径上的量**（给出链：哪个量 → 经由哪一步 → 变成两袋不同）；
* **第二个独立分歧** ⇒ 必须能指出**一条不经过前一笔的通路**；
* **分不出来就写"分不出来"＋已排除的路径**——**不许挑一个像的**。

## 机械口径（本工具真的这么判，不是人看）

对给定的 `敌人/idx`，把两侧的事件按 `(t, 标签)` 对齐，逐事件比 `amount/dealt/hp`：

| 观测 | 读作 |
|---|---|
| 有**第一个**值差事件 `E*`，且在它**之前没有任何一侧独有的事件** | 该实体的分歧**起点**＝`E*` |
| 之后每个共有事件的 `dealt` 差**恒定**（= `E*` 引入的差），且 `hp` 差等于累计差 | 后面那些是**传播**（下游） |
| 出现**一侧独有的事件**且它发生在 `E*` **之前** | ⇒ **第二个独立分歧**（给出那条通路） |
| 实体在一侧 `hp` 归零／不再出现，而另一侧仍有正 `hp`，且归零侧的**累计差**足以解释 | ⇒ 该"消失"是**下游**（并给出死亡时刻） |
| 对齐本身有歧义（同 `(t,标签)` 多行且两侧行数不同 ⇒ 袋不可配对） | ⇒ **分不出**，并列出歧义点 |

⚠ **袋语义**：同一 `(标签, t)` 可以有多行（同帧多段伤害）。本工具**不拿 `t` 当行键**：
配对按 `(t, 标签)` 分组后**按序**对齐，且**行数不同就报歧义**，不猜。

用法：
    python tools/hp_chain.py --a <A.txt> --b <B.txt> --enemy 厌肮 --idx 6 --range 70:95
    python tools/hp_chain.py --a <A.txt> --b <B.txt> --enemy 厌肮          # 该敌全部 idx
"""
#: ⚠ **本文件的行内引号一律用「」**：Windows 上这已经是本会话第三次栽在
#: 「双引号里再嵌双引号」上（`print("…"像的"…")` 直接 SyntaxError）——
#: 写之前就避开，比靠 `py_compile` 事后逮住省一轮。
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_kv  # noqa: E402  （**唯一**的痕迹解析入口）

#: 带"这次打在这一只身上"语义的标签（`SPLASH-CENTER` 是**全场快照**，不按 idx 归属，另用）
PER_HIT = ("DMGENEMY", "HITENEMY", "SPLASH", "OPDMG", "DEPLOYDMG")


def load(path: Path) -> list[tuple[float, str, dict]]:
    out: list[tuple[float, str, dict]] = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        got = trace_kv.parse_trace(ln)
        if got is None:
            continue
        tag, d = got
        try:
            t = float(d.get("t", "nan"))
        except ValueError:
            continue
        if t != t:                                          # NaN
            continue
        out.append((t, tag, d))
    return out


def pick(evs: list[tuple[float, str, dict]], enemy: str | None, idx: str | None,
         t0: float, t1: float) -> list[tuple[float, str, dict]]:
    out = []
    for t, tag, d in evs:
        if not (t0 - 1e-9 <= t <= t1 + 1e-9):
            continue
        if enemy is not None and d.get("enemy") != enemy:
            continue
        if idx is not None and str(d.get("idx")) != str(idx):
            continue
        out.append((t, tag, d))
    return out


def key_of(ev: tuple[float, str, dict]) -> tuple[float, str]:
    return (round(ev[0], 4), ev[1])


def group(evs: list[tuple[float, str, dict]]) -> dict[tuple[float, str], list[dict]]:
    g: dict[tuple[float, str], list[dict]] = {}
    for t, tag, d in evs:
        g.setdefault((round(t, 4), tag), []).append(d)
    return g


def num(d: dict, k: str) -> float | None:
    try:
        return float(d.get(k))
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="单点溯源：逐帧追一只敌人的 HP 链")
    ap.add_argument("--a", required=True, help="老侧 stderr（含 -t 行）")
    ap.add_argument("--b", required=True, help="现代侧 stderr")
    ap.add_argument("--enemy", help="敌人名（如 厌肮）")
    ap.add_argument("--idx", help="敌人 idx（不给＝该敌全部 idx）")
    ap.add_argument("--range", default="0:1e9", help="时间窗 t0:t1（默认全窗）")
    ap.add_argument("--targeting", action="store_true",
                    help="只扫\u300c换目标候选\u300d（实例集口径：名字＋实例数，不看血量文本）")
    args = ap.parse_args()

    t0s, _, t1s = args.range.partition(":")
    t0, t1 = float(t0s), float(t1s)

    ea, eb = load(Path(args.a)), load(Path(args.b))

    #: ★★ **先用"两侧都带 idx 列"把标签筛出来**（本工具第一版栽在这里，留证）：
    #: `HITENEMY` 的 `idx/ecell/resbase/resdown/res/frozen` 是**只在现代侧存在的列**
    #: ⇒ 按 `idx` 过滤会把**老侧整类 HITENEMY 事件全部滤掉**，于是 t=71.5667 那一笔
    #: 被读成「只在 B 侧」＝**假的第二个独立分歧候选**。
    #: （同族：`d37af24f` 的「跨扩列构建比结构差要先取键集交集」——这里字段名就是"列"。）
    tags_a = {tag for _t, tag, d in ea if d.get("idx") not in (None, "")}
    tags_b = {tag for _t, tag, d in eb if d.get("idx") not in (None, "")}
    usable = sorted(tags_a & tags_b)
    skipped = sorted((tags_a | tags_b) - set(usable))
    print(f"  ⚠ 标签可用性：两侧都带 idx 的标签＝{usable}；**跳过** {skipped}"
          f"（它们在某一侧没有 idx 列 ⇒ 无法按个体归属，**不许按 idx 硬比**）")
    if args.idx and not usable:
        print("  ⛔ 没有任何标签在两侧都带 idx ⇒ **分不出**（口径上限），不是「两侧相同」。")
        return 0

    pa = pick([e for e in ea if e[1] in usable], args.enemy, args.idx, t0, t1)
    pb = pick([e for e in eb if e[1] in usable], args.enemy, args.idx, t0, t1)
    who = f"{args.enemy or '（全部敌人）'}" + (f" idx={args.idx}" if args.idx else "")
    print(f"== 单点溯源：{who}　窗 [{t0:g}, {t1:g}] ==")
    print(f"  事件数：A={len(pa)}　B={len(pb)}")
    if not pa or not pb:
        print("  ⛔ 一侧为空 ⇒ **分不出**（不是「没有分歧」）：先确认该实体在这两段痕迹里都有事件。")
        return 0

    ga, gb = group(pa), group(pb)
    keys = sorted(set(ga) | set(gb))
    first_diff: tuple[float, str] | None = None
    one_sided_before: list[tuple[float, str, str]] = []
    ambig: list[tuple[float, str, int, int]] = []
    rows: list[tuple[float, str, dict, dict]] = []
    for k in keys:
        la, lb = ga.get(k, []), gb.get(k, [])
        if not la or not lb:
            side = "A" if la else "B"
            one_sided_before.append((k[0], k[1], side))
            if first_diff is None:
                first_diff = k
            continue
        if len(la) != len(lb):
            ambig.append((k[0], k[1], len(la), len(lb)))
        for da, db in zip(la, lb):
            if (num(da, "dealt"), num(da, "hp"), num(da, "amount")) != \
               (num(db, "dealt"), num(db, "hp"), num(db, "amount")):
                rows.append((k[0], k[1], da, db))
                if first_diff is None:
                    first_diff = k

    if first_diff is None and not one_sided_before:
        print("  ✅ 该实体在该窗内**两侧逐事件相同**（含 hp）⇒ 这里没有分歧。")
        return 0

    if args.targeting:
        scan_targeting(ea, eb, t0, t1)
        return 0

    if first_diff is not None:
        print(f"  ★ 第一处分歧：t={first_diff[0]:.4f}　标签 {first_diff[1]}")
        for t, tag, da, db in rows[:6]:
            mark = "★首处" if (round(t, 4), tag) == first_diff else "  传播"
            print(f"    {mark} t={t:.4f} {tag}　A: amount={da.get('amount')} dealt={da.get('dealt')} hp={da.get('hp')}"
                  f"　B: amount={db.get('amount')} dealt={db.get('dealt')} hp={db.get('hp')}")
        if len(rows) > 6:
            print(f"    …… 其余 {len(rows) - 6} 处值差（见下累计）")

        # 累计差：以 dealt 差是否恒定判断"是否只是传播"
        #: **传播判据（机械）**：老侧多打的每一笔 Δdealt 都应**累加在 hp 差上**，
        #: 即 `hp_A − hp_B` 在每一步都等于"到目前为止 Δdealt≠0 的那些笔之和"。
        #: 这是"同一串事件、只多了偏置"的签名——不是"像"，是等式。
        acc, ok_prop, jumps, trunc = 0.0, True, [], []
        for _t, _tag, a, b in rows:
            d = (num(a, "dealt") or 0) - (num(b, "dealt") or 0)
            if abs(d) > 1e-9:
                acc += d
                jumps.append((_t, d, acc))
            #: ⚠ **截断点不参与传播等式**：一侧 hp 归零后，`dealt` 被夹到"剩余血量"，
            #: 于是 `hp 差 == 累计 Δdealt` 这一步必然不成立——**那是截断，不是新来源**
            #: （实测 t=93.0000：Δdealt=+156.840，而 156.840 = 365.160 − 208.320，
            #:  正是"现代侧这一笔只打到 0"造成的夹零）。
            if (num(a, "hp") or 0) <= 0 or (num(b, "hp") or 0) <= 0:
                trunc.append((_t, d))
                continue
            #: ⚠ **符号**：`d = dealt_A − dealt_B`，而 A 打得少 ⇒ A 的 hp **多** ⇒ `dh = −acc`。
            #: （第一版写成 `dh == acc`，于是四条正确的传播链被判成"不成立"——**判据自身的符号错
            #:  会伪装成"有别的来源"**，这正是"永远红/永远绿"那族要防的。）
            dh = (num(a, "hp") or 0) - (num(b, "hp") or 0)
            if abs(dh + acc) > 0.002:                 # 半个打印刻度内算相等
                ok_prop = False
        if trunc:
            print(f"  ⚠ 截断点 {len(trunc)} 处（一侧 hp=0）**不参与传播等式**："
                  f"{[(f'{t:.4f}', f'Δ{d:+.3f}') for t, d in trunc[:3]]}")
        d0 = (num(rows[0][2], "dealt") or 0) - (num(rows[0][3], "dealt") or 0)
        print(f"  累计：值差事件 {len(rows)} 处；首处 Δdealt = {d0:+.3f}；"
              f"其中 Δdealt≠0 的 {len(jumps)} 处（跳变点）")
        for _t, d, a_ in jumps[:6]:
            print(f"    t={_t:.4f}　Δdealt={d:+.3f}　累计={a_:+.3f}")
        print(f"  ⇒ 传播判据（hp 差 == 累计 Δdealt，逐步等）：{'**成立**' if ok_prop else '不成立 ⇒ 有别的来源'}"
              + (f"；**非截断**跳变是否都是同一个数 {abs(d0):.3f} 的整数倍＝"
                 f"{all(abs(abs(d) - abs(d0)) < 1e-6 for _t, d, _a in jumps if abs(d) > 1e-9)}"
                 if jumps else ""))

    if one_sided_before:
        print(f"  ⚠ **一侧独有的事件** {len(one_sided_before)} 组（前 6）：")
        for t, tag, side in one_sided_before[:6]:
            print(f"    t={t:.4f} {tag} 只在 {side} 侧")
    if ambig:
        print(f"  ⚠ **袋不可配对**（同 (t,标签) 两侧行数不同）{len(ambig)} 组："
              f"{[(f'{t:.4f}', tag, f'A{n}/B{m}') for t, tag, n, m in ambig[:4]]}")
        print("    ⇒ 这些点**不许**按序硬对：**分不出**的候选就在这里。")

    # 结论：机械判据
    #: **"消失"判据（机械）**：一侧最后一笔的 hp，与另一侧同刻的 hp，差是否等于累计偏置。
    if one_sided_before and rows:
        _ta = [t for t, _tag, _s in one_sided_before]
        _side = one_sided_before[0][2]
        _last_common = rows[-1]
        _hpA = num(_last_common[2], "hp") or 0
        _hpB = num(_last_common[3], "hp") or 0
        _acc = 0.0
        for _t, _tag, a, b in rows:
            _acc += (num(a, "dealt") or 0) - (num(b, "dealt") or 0)
        print(f"  ── 消失判据 ──")
        _explained = abs((_hpA - _hpB) + _acc) < 0.002      #: 符号同前：A 打得少 ⇒ hp 多 ⇒ dh = −acc
        print(f"    最后一笔共有事件 t={_last_common[0]:.4f}：A hp={_hpA:.3f}　B hp={_hpB:.3f}"
              f"　实测差={_hpA - _hpB:+.3f}　累计 Δdealt={_acc:+.3f}"
              f"　⇒ 差能由累计解释＝{_explained}")
        print(f"    一侧独有事件：{len(one_sided_before)} 组，最早 t={min(_ta):.4f}（{_side} 侧）"
              f"⇒ 另一侧该个体在 t≈{min(_ta):.4f} 前已不再被记录（**归零/消失**）")

    print("  ── 定性（机械判据，不挑「像的」）──")
    print(f"  口径：只比两侧都带 idx 的标签（{usable}）；被跳过的标签差异属**痕迹口径差**，"
          f"不进本判定。")
    if ambig:
        print("  ⇒ **分不出**：存在袋不可配对点，先解决配对再定性。")
    elif one_sided_before and first_diff is not None and \
            min(t for t, _, _ in one_sided_before) < first_diff[0]:
        print("  ⇒ **第二个独立分歧候选**：一侧独有事件出现在第一处值差**之前** ⇒ 那条通路不经过后面那笔。")
    elif first_diff is not None:
            print("  ⇒ **下游**（链完整）：① 第一处是纯值差（无先行独有事件）；"
              "② 排除截断点后**hp 差 == 累计 Δdealt**逐步成立；"
              "③ 该个体在另一侧的归零可由同一累计差解释。三条都机械成立。")
    elif first_diff is not None:
        print("  ⇒ **分不出**：第一处是值差，但**链有一环没证据**"
              "（或存在先行独有事件却没到'第二通路'的程度）——**不许挑一个像的**，"
              "把已排除的路径与缺口一起写进结论。")
    return 0


def scan_targeting(ea, eb, t0: float, t1: float, limit: int = 12) -> None:
    """**换目标候选**（机械判据，UI_2b 2026-09-20 01:15 的提醒）：

    ⚠ **不许比 `pick=`/`block=` 的文本**——那里带血量，前面的伤害差会让文本天然不同
    （UI_2b 第一版比文本 ⇒ 22 处误标成"索敌差"）。要**拆成"名字＋实例数"的实例集**再比：
    实例集或实例数不同，才算"换目标候选"。
    """
    def inst(d: dict) -> list[str] | None:
        raw = d.get("block")
        if raw is None:
            return None
        raw = raw.strip()
        if not raw:
            return []
        #: `block=厌肮(365)|厌肮(8276)` ⇒ 只取名字，丢掉括号里的血量
        return sorted(x.split("(")[0] for x in raw.split("|") if x)

    ga: dict[tuple[float, str], list[str]] = {}
    gb: dict[tuple[float, str], list[str]] = {}
    for t, tag, d in ea:
        if t0 - 1e-9 <= t <= t1 + 1e-9 and tag == "OPATK":
            v = inst(d)
            if v is not None:
                ga[(round(t, 4), str(d.get("op")))] = v
    for t, tag, d in eb:
        if t0 - 1e-9 <= t <= t1 + 1e-9 and tag == "OPATK":
            v = inst(d)
            if v is not None:
                gb[(round(t, 4), str(d.get("op")))] = v
    hits = [(k, ga[k], gb.get(k)) for k in ga if k in gb and ga[k] != gb[k]]
    print(f"\n== 换目标候选 A：block 的**名字实例集**（不看血量文本）＝ {len(hits)} 处 ==")
    for k, va, vb in hits[:limit]:
        print(f"  t={k[0]:.4f} {k[1]}　A 实例集={va}　B 实例集={vb}")
    if len(hits) > limit:
        print(f"  …… 其余 {len(hits) - limit} 处")
    if not hits:
        print("  ✅ 该窗内**没有**换目标：所有 OPATK 的实例集两侧一致。")

    #: ★ **换目标候选 B：按 idx 比"这一发打在哪只个体身上"**（名字级口径做不到这件事）。
    #: `DMGENEMY` 两侧都带 `idx` ⇒ 用 `(t, src)` 分组比 **idx 集合**：
    #: **同名不同个体**在这里才分得开（实测 t=193.0 两侧都只有一只 厌肮，
    #: 名字实例集完全相同，但挨打的是**不同的个体** ⇒ 名字级判据沉默）。
    ia: dict[tuple[float, str], set[str]] = {}
    ib: dict[tuple[float, str], set[str]] = {}
    for t, tag, d in ea:
        if tag == "DMGENEMY" and t0 - 1e-9 <= t <= t1 + 1e-9 and d.get("idx") not in (None, ""):
            ia.setdefault((round(t, 4), str(d.get("src"))), set()).add(str(d.get("idx")))
    for t, tag, d in eb:
        if tag == "DMGENEMY" and t0 - 1e-9 <= t <= t1 + 1e-9 and d.get("idx") not in (None, ""):
            ib.setdefault((round(t, 4), str(d.get("src"))), set()).add(str(d.get("idx")))
    hits2 = [(k, sorted(ia[k]), sorted(ib[k])) for k in ia if k in ib and ia[k] != ib[k]]
    print(f"\n== 换目标候选 B：**挨打个体的 idx 集合**（同名不同个体在这里才分得开）＝ {len(hits2)} 处 ==")
    for k, va, vb in hits2[:limit]:
        print(f"  t={k[0]:.4f} {k[1]}　A idx={va}　B idx={vb}")
    if len(hits2) > limit:
        print(f"  …… 其余 {len(hits2) - limit} 处")
    if not hits2:
        print("  ✅ 该窗内每一发打的都是同一批个体（idx 集合两侧一致）。")


if __name__ == "__main__":
    raise SystemExit(main())
