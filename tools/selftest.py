"""抽样自检：把解析器拉到全库上跑一遍，看它究竟站不站得住。

    python tools/selftest.py            # 随机抽 25 个干员
    python tools/selftest.py -n 60      # 抽 60 个
    python tools/selftest.py --all      # 全部 461 个（会跑很久，注意限速）
    python tools/selftest.py --with-range   # 连带解析攻击范围

自检不只看「有没有抛异常」，还核对关键字段是否真的被填上——
这是区分「能跑」和「能算」的地方。
"""

from __future__ import annotations

import argparse
import random
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ak_tactic.prts import (  # noqa: E402
    PrtsClient,
    PrtsError,
    RangeRegistry,
    fetch_operator,
    list_operators,
)

REQUIRED_SCALARS = ["name", "char_id", "profession", "position"]
REQUIRED_NONEMPTY = ["branch", "trait", "range_codes"]


def check(op) -> list[str]:
    """返回这份数据的问题清单（空列表 = 全好）。"""
    problems: list[str] = []
    for f in REQUIRED_SCALARS:
        if not getattr(op, f, None):
            problems.append(f"缺 {f}")
    for f in REQUIRED_NONEMPTY:
        if not getattr(op, f, None):
            problems.append(f"缺 {f}")
    if not (1 <= op.rarity <= 6):
        problems.append(f"星级异常 {op.rarity}")
    if len(op.stats) < 2:
        problems.append(f"属性档位只有 {len(op.stats)} 条")
    elif op.max_stat() is None or op.max_stat().atk is None:
        problems.append("最高档位没有攻击力")
    if not op.skills:
        # 一星机器人、训练用"预备干员"本来就没有技能，不算缺陷。
        if op.rarity >= 3:
            problems.append("没有技能")
    else:
        for sk in op.skills:
            if len(sk.levels) != 10:
                problems.append(f"技能{sk.index} 只有 {len(sk.levels)}/10 个等级")
                break
            if not any(lv.description for lv in sk.levels):
                problems.append(f"技能{sk.index} 描述全空")
                break
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--count", type=int, default=25)
    ap.add_argument("--all", action="store_true", help="跑全库")
    ap.add_argument("--seed", type=int, default=20260101)
    ap.add_argument("--with-range", action="store_true")
    ap.add_argument("--profession", default="")
    ap.add_argument("--rarity", type=int, default=None)
    args = ap.parse_args()

    client = PrtsClient()
    print("拉干员名录……")
    roster = list_operators(client=client)
    if args.profession or args.rarity is not None:
        from ak_tactic.prts.operator import _smw_operators
        keep = {o["title"] for o in _smw_operators(
            client, profession=args.profession, rarity=args.rarity)}
        roster = [r for r in roster if r.get("Page") in keep]
    names = [r["Page"] for r in roster if r.get("Page")]
    print(f"库内 {len(names)} 个干员")

    if args.all:
        sample = names
    else:
        random.seed(args.seed)
        sample = random.sample(names, min(args.count, len(names)))
    print(f"本次抽检 {len(sample)} 个\n")

    ok, failed = [], []
    issue_counter: Counter[str] = Counter()
    t0 = time.time()
    reg = RangeRegistry(client=client) if args.with_range else None
    range_issues: Counter[str] = Counter()
    range_codes_seen: set[str] = set()

    for i, name in enumerate(sample, 1):
        try:
            op = fetch_operator(name, client=client)
        except (PrtsError, ValueError, KeyError) as e:
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"[{i:3d}/{len(sample)}] ✗ {name}  {type(e).__name__}: {e}")
            continue
        except Exception:
            failed.append((name, traceback.format_exc(limit=2)))
            print(f"[{i:3d}/{len(sample)}] ✗ {name}  未预期异常")
            continue

        problems = check(op)
        if problems:
            for p in problems:
                issue_counter[p] += 1
            print(f"[{i:3d}/{len(sample)}] △ {name}  {'; '.join(problems)}")
        else:
            print(f"[{i:3d}/{len(sample)}] ✓ {name}  "
                  f"★{op.rarity} {op.profession}·{op.branch} "
                  f"{len(op.skills)}技能 {len(op.talents)}天赋 {len(op.modules)}模组")
        ok.append(name)

        if reg is not None:
            for code in op.range_codes.values():
                if code in range_codes_seen:
                    continue
                range_codes_seen.add(code)
                try:
                    reg.get(code)
                except (PrtsError, ValueError) as e:
                    range_issues[code] += 1
                    print(f"           范围 {code} 解析失败：{e}")

    if reg is not None:
        reg.save()

    dt = time.time() - t0
    print("\n" + "=" * 62)
    print(f"成功 {len(ok)} / {len(sample)}    失败 {len(failed)}    用时 {dt:.1f}s")
    if issue_counter:
        print("\n字段问题分布：")
        for k, v in issue_counter.most_common():
            print(f"  {v:4d}×  {k}")
    else:
        print("字段完整度：全部通过")
    if args.with_range:
        print(f"\n攻击范围：解析了 {len(range_codes_seen)} 个不同代号，"
              f"失败 {sum(range_issues.values())} 次")
        for k, v in range_issues.most_common():
            print(f"  {v}×  {k}")
    if failed:
        print("\n失败清单：")
        for n, e in failed:
            print(f"  {n}: {e}")
    print(f"\n网络统计：{client.stats}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
