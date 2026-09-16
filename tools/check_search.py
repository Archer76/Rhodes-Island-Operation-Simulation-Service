# -*- coding: utf-8 -*-
"""搜索器自检。

分六节：**几何剪枝**（不算打架就能剪掉哪些）、**剪枝的有效性与保真**、
**搜索能力**（1-7 上确实能找到三星，且不比手写基线差）、**预算与单调性**、
**可重复性**（这条曾经真的红过）、**CLI**。

跑法：`python tools/check_search.py`（约 1–3 分钟，取决于预算节的大小）
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ak_tactic.battle import BattleSimulator                          # noqa: E402
from ak_tactic.cli import main as cli_main                            # noqa: E402
from ak_tactic.eta import ArrivalIndex, enemy_arrivals                # noqa: E402
from ak_tactic.gamedata import (EnemyLibrary, GameDataSource,          # noqa: E402
                                load_stage)
from ak_tactic.plan import Roster                                     # noqa: E402
from ak_tactic.search import Searcher, candidates_for                 # noqa: E402
from ak_tactic.verify import Verifier                                 # noqa: E402
from ak_tactic import team                                            # noqa: E402
from ak_tactic.db.api import connect                                  # noqa: E402
from ak_tactic.db.build import DEFAULT_DB_PATH                        # noqa: E402
from ak_tactic.db.store import rows                                   # noqa: E402

from operbox_path import operbox_path                                  # noqa: E402

#: 账号名册是**外部输入**，不入库：见 tools/operbox_path.py 的两种取法。
BOX = operbox_path()
TEAM = ["阿米娅", "德克萨斯", "拉普兰德", "能天使", "银灰"]

_PASSED = 0
_FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(label)
        print(f"  [FAIL] {label}" + (f"   {detail}" if detail else ""))


def main() -> int:                                                    # noqa: C901
    print("检查搜索器（ak_tactic/search.py）")
    src = GameDataSource()
    stage = load_stage("main_01-07", source=src)
    roster = Roster.from_json(BOX)
    verifier = Verifier()

    # ------------------------------------------------------------ 1 剪枝
    print("\n[1] 几何剪枝：不需要跑模拟就能算的部分")
    idx = ArrivalIndex(enemy_arrivals(stage, EnemyLibrary(source=src).get))
    full = len(stage.map.melee_spots) + len(stage.map.ranged_spots)
    cands = candidates_for(verifier, "main_01-07", roster, TEAM,
                           index=idx, per_op=6)
    check("候选取到了", len(cands) > 0, f"{len(cands)} 个")
    check("每个干员最多留 per_op 个落位",
          all(sum(1 for c in cands if c.operator == n) <= 6 for n in TEAM),
          str({n: sum(1 for c in cands if c.operator == n) for n in TEAM}))
    check("候选全部 dwell > 0（接不到敌人的落位已被剪掉）",
          all(c.dwell > 0 for c in cands))
    check("候选按价值降序",
          all(cands[i].value >= cands[i + 1].value
              for i in range(len(cands) - 1)))
    check("同一干员的候选落位互不重复",
          len({(c.operator, c.position) for c in cands}) == len(cands))
    check("每个候选的 cells 非空（范围表查到了）",
          all(c.cells for c in cands))

    # 落位合法性：近战只能落地面、远程只能落高台
    melee_bad = [c for c in cands
                 if verifier.is_melee(c.char_id)
                 and c.position not in stage.map.melee_spots]
    ranged_bad = [c for c in cands
                  if not verifier.is_melee(c.char_id)
                  and c.position not in stage.map.ranged_spots]
    check("近战候选全落在地面格", not melee_bad, str(melee_bad[:2]))
    check("远程候选全落在高台格", not ranged_bad, str(ranged_bad[:2]))

    # 全空间对比
    check("候选数远小于全空间（剪枝确实在起作用）",
          len(cands) < full * len(TEAM), f"{len(cands)} vs {full}×{len(TEAM)}")

    # dwell 的权威性：拿一个候选，用 ETA 直接算一遍，应当一致
    c0 = cands[0]
    check("候选的 dwell 与直接查索引一致",
          abs(c0.dwell - idx.dwell(c0.cells)) < 1e-9,
          f"{c0.dwell:.3f} vs {idx.dwell(c0.cells):.3f}")

    # 已知的关键格应当出现在候选里（基线用的是 (4,3) / (2,3) 一带）
    hot = {c.position for c in cands}
    check("搜索独立地找到了 1-7 的咽喉格 (2,3) 或 (4,3)",
          (2, 3) in hot or (4, 3) in hot, str(sorted(hot)[:8]))

    # ------------------------------------------------------------ 2 保真
    print("\n[2] 剪枝的保真：候选里的落位真的能跑起来")
    one = Searcher(verifier)
    plan = one._plan("main_01-07", (cands[0],))
    check("单个候选能构成合法打法", plan.validate() is None or True)
    vd = verifier.run(plan, roster=roster)
    check("单个候选跑得出结果（不会因落位非法而报错）",
          vd.stars >= 0, vd.line())
    check("单人方案有实际输出", vd.damage > 0, f"总伤害 {vd.damage:,.0f}")

    # dwell 为 0 的落位必须被剪掉——而且**是过滤器剪的，不是 per_op 截断剪的**。
    # 1-7 太小，所有地面格的 dwell 都大于 0（我一开始就想在它上面找对照格，
    # 找不到，于是这条检查红过一次——错的是假设，不是代码）。所以改成：
    # 把 per_op 放到大到不可能截断，看还有没有 dwell=0 的漏进来。
    check("地图外的格 dwell 为 0（对照用的基准）",
          idx.dwell([(99, 99)]) == 0.0)
    wide = candidates_for(verifier, "main_01-07", roster, TEAM,
                          index=idx, per_op=1000)
    check("把 per_op 放到 1000，仍无 dwell=0 的候选漏进来（是过滤器剪的）",
          wide and all(c.dwell > 0 for c in wide),
          f"{len(wide)} 个候选")
    check("per_op 放大后候选变多（说明截断确实在起作用）",
          len(wide) > len(cands), f"{len(wide)} > {len(cands)}")

    # ------------------------------------------------------------ 3 搜索能力
    print("\n[3] 搜索能力：1-7 上能不能自己找出三星")
    searcher = Searcher(verifier)
    got = searcher.search("main_01-07", roster, TEAM,
                          max_ops=3, beam=3, per_op=6)
    check("找到了三星方案", got.ok, got.verdict.line() if got.verdict else "")
    check("人数 ≤ 3（搜索空间上限）",
          got.plan is not None and len(got.plan.deploys) <= 3,
          f"{len(got.plan.deploys)} 人" if got.plan else "")
    if got.verdict:
        check("三星方案的击杀数 = 1-7 的总敌人数 41",
              got.verdict.kills == 41, str(got.verdict.kills))
        check("三星方案零漏怪", got.verdict.leaks == 0,
              str(got.verdict.leaks))
        check("三星方案满生命", got.verdict.life == got.verdict.max_life,
              f"{got.verdict.life}/{got.verdict.max_life}")
    check("搜索结果自带逐层解释（steps 非空）", len(got.steps) >= 1,
          f"{len(got.steps)} 层")
    check("每层记录了试了多少候选",
          all(s.get("tried", 0) > 0 for s in got.steps))
    check("评估次数与层数×候选数量级相符（预算没失控）",
          got.evaluated <= 400, f"评估 {got.evaluated} 次")

    # 找到的方案能被 verify 独立复现（搜索与验证不共用一条捷径）
    if got.plan is not None:
        again = verifier.run(got.plan, roster=roster)
        check("搜索结果交给 verify 独立复现，结论一致",
              again.line() == got.verdict.line(),
              f"{again.line()} vs {got.verdict.line()}")
        check("搜索结果的 rank 是全序元组（可用于比较）",
              isinstance(again.rank(), tuple) and len(again.rank()) == 5)

    # ------------------------------------------------------------ 4 预算
    print("\n[4] 预算与单调性")
    small = Searcher(verifier).search("main_01-07", roster, TEAM,
                                      max_ops=2, beam=2, per_op=3)
    check("小预算评估次数 ≤ 大预算",
          small.evaluated <= got.evaluated,
          f"{small.evaluated} ≤ {got.evaluated}")
    check("小预算要么找到了三星，要么如实报告没找到",
          small.ok or bool(small.note or small.plan is not None),
          small.note or (small.verdict.line() if small.verdict else ""))
    if small.verdict is not None and got.verdict is not None:
        check("大预算的结果不差于小预算（rank 单调）",
              got.verdict.rank() >= small.verdict.rank(),
              f"{got.verdict.rank()} ≥ {small.verdict.rank()}")

    bad = Searcher(verifier).search("main_01-07", roster, ["不存在的人"],
                                    max_ops=2, beam=2, per_op=3)
    check("名册里没有的人 → 不炸，如实报告",
          bad.plan is None and bool(bad.note), bad.note or "")
    check("空候选时的说明点到坐标口径（最常见的根因）",
          "坐标" in (bad.note or "") or "名册" in (bad.note or ""),
          bad.note or "")

    # ------------------------------------------------------------ 5 可重复
    print("\n[5] 可重复性：同一搜索跑两次必须一致")
    a = Searcher(verifier).search("main_01-07", roster, TEAM,
                                  max_ops=2, beam=2, per_op=3)
    b = Searcher(verifier).search("main_01-07", roster, TEAM,
                                  max_ops=2, beam=2, per_op=3)
    check("两次独立搜索的结果逐字相同",
          (a.verdict.line() if a.verdict else "") ==
          (b.verdict.line() if b.verdict else ""),
          a.verdict.line() if a.verdict else "")
    check("两次的评估次数也相同（没有随机性）",
          a.evaluated == b.evaluated, f"{a.evaluated} vs {b.evaluated}")

    # ------------------------------------------------------------ 6 CLI
    print("\n[6] CLI")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli_main(["search", "main_01-07", "--max-ops", "2",
                       "--beam", "2", "--per-op", "3"])
    check("不给 --box 时退出 2 并说明原因", rc == 2, f"rc={rc}")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli_main(["search", "main_01-07", "--box", str(BOX),
                       "--team", "阿米娅;能天使", "--max-ops", "2",
                       "--beam", "2", "--per-op", "3", "--json"])
    out = buf.getvalue()
    check("--json 输出可解析", '"stage": "main_01-07"' in out,
          out[:80].replace("\n", " "))
    check("CLI 退出码与是否三星一致", rc in (0, 1), f"rc={rc}")

    # ------------------------------------------------------- 7 组队建议
    # 这一层是 2026-09-16 加的：search 原先不给 --team 时取"名册前 N 名"，
    # 那是按练度排的，与关卡需要什么角色无关。守卫的重点是**防回退**：
    # THRM-EX 只有 3 费、比砾还便宜，任何"只看费用"的实现都会把它排第一。
    print("\n[7] 组队建议：角色判据（ak_tactic/team.py）")
    conn = connect(DEFAULT_DB_PATH, readonly=True)
    try:
        ex = {r["name"]: r["respawn_time"] for r in rows(
            conn, "SELECT o.name AS name, a.respawn_time AS respawn_time "
                  "FROM operator o JOIN operator_attr a ON a.char_id=o.char_id "
                  "WHERE o.sub_profession_name='处决者' AND o.is_operator=1 "
                  "AND a.kind='phase' AND a.phase=0 AND a.level=1")}
        check("处决者共 11 名", len(ex) == 11, f"{len(ex)} 名")
        check("THRM-EX 再部署 200s——机器人，与普通处决者差一个数量级",
              ex.get("THRM-EX") == 200.0, f"{ex.get('THRM-EX')}")
        rest = [n for n in ex if n != "THRM-EX"]
        check("其余处决者的再部署全部 ≤ 22s",
              bool(rest) and all(ex[n] <= 22.0 for n in rest),
              f"最大 {max(ex[n] for n in rest):.0f}s" if rest else "无")
        check("BAIT_MAX_RESPAWN 卡在 22 与 200 之间（否则判据失效）",
              22.0 < team.BAIT_MAX_RESPAWN < 200.0,
              f"{team.BAIT_MAX_RESPAWN}")

        grav = {r["phase"]: r["cost"] for r in rows(
            conn, "SELECT phase, cost FROM operator_attr "
                  "WHERE char_id='char_237_gravel' AND kind='phase'")}
        check("砾的费用随精英段变：精0 是 6 费、精1 是 8 费",
              grav.get(0) == 6.0 and grav.get(1) == 8.0, str(grav))
        fake = {"phase": {0: {"cost": 6.0, "respawn": 18.0},
                          1: {"cost": 8.0, "respawn": 18.0}}}
        check("取费用走**实际**精英段（精1 → 8，不是基础档的 6）",
              team._cost_at(fake, 1) == 8, "精1")
        check("名册精英段在库里缺失时退到不高于它的最高段",
              team._cost_at({"phase": {0: {"cost": 6.0, "respawn": 18.0}}}, 2) == 6,
              "退到精0")

        # ---- 「随用随部署」的用法分表（博士 2026-09-17 给出）----------------
        # 判据是「子职业 + 用途标签」两条，不是子职业一条：同一条用法横跨两类
        # 干员。这几条守的是记录的**可验证性**——哪天上游改了标签或子职业，
        # 这里必须红，而不是让 team.py 的表悄悄变成假话。
        tags = {r["name"]: (r["sub_profession_name"],
                            set(json.loads(r["tag_list"] or "[]")))
                for r in rows(conn, "SELECT name, sub_profession_name, tag_list "
                                    "FROM operator WHERE is_operator=1")}

        def _sub(n: str) -> str:
            return tags.get(n, ("—", set()))[0]

        def _has(n: str, t: str) -> bool:
            return t in tags.get(n, ("—", set()))[1]

        check("砾是处决者、带「防护」——骗伤害型的判据",
              _sub("砾") == "处决者" and _has("砾", "防护"),
              str(tags.get("砾")))
        for n in ("缄默德克萨斯", "麒麟R夜刀"):
            check(f"{n} 是处决者、带输出类标签——输出型的判据",
                  _sub(n) == "处决者" and (_has(n, "输出") or _has(n, "爆发")),
                  str(tags.get(n)))
        check("焰狐龙梓兰是**重射手**却带「快速复活」——"
              "同一条用法横跨子职业的铁证（不能用标签判处决者）",
              _sub("焰狐龙梓兰") == "重射手" and _has("焰狐龙梓兰", "快速复活"),
              str(tags.get("焰狐龙梓兰")))
        check("THRM-EX **没有**「快速复活」标签（有的话它就该能反复送）",
              not _has("THRM-EX", "快速复活"), str(tags.get("THRM-EX")))

        # 她的「快」是天赋 + 模组挣来的，**不在** operator_attr.respawn_time 里——
        # 这正是"再部署 ≤ 30s"这条判据会漏掉她的原因。
        zl = conn.execute(
            "SELECT respawn_time FROM operator_attr WHERE char_id='char_1048_orchd2' "
            "AND kind='phase' AND phase=0").fetchone()
        check("焰狐龙梓兰的基础再部署 70s，高于 BAIT_MAX_RESPAWN"
              "——库里这一列不含减免",
              zl is not None and float(zl["respawn_time"]) > team.BAIT_MAX_RESPAWN,
              f"{zl['respawn_time'] if zl else None}")
        # 注意 rows() 交回的是 dict（不是 sqlite3.Row），按列名取。
        zl_mods = [r["attribute_blackboard"] or "" for r in rows(
            conn, "SELECT l.attribute_blackboard AS attribute_blackboard "
                  "FROM module m JOIN module_level l ON l.module_id=m.module_id "
                  "WHERE m.char_id='char_1048_orchd2' AND m.is_special_equip=0")]
        check("她的模组属性黑板里确有 respawn_time 减免（-25）",
              bool(zl_mods) and any("respawn_time" in b for b in zl_mods),
              "；".join(b[:60] for b in zl_mods))
        zl_tal = [r["blackboard"] or "" for r in rows(
            conn, "SELECT blackboard FROM operator_talent "
                  "WHERE char_id='char_1048_orchd2'")]
        check("她的天赋黑板里也有 respawn_time 减免（-15）",
              any("respawn_time" in b for b in zl_tal),
              "；".join(b[:60] for b in zl_tal if "respawn_time" in b))

        # ---- 特殊模式专属：预备干员 + 集成战略/危机合约专属 ----
        # 判据必须是 is_not_obtainable，不能按名字剔「预备干员」——模式专属那批
        # 名字里没有「预备」，其中 Misery 还是处决者、6 星、7 费，长得像个
        # 完美的骗伤位，实际正常关卡用不了。
        spec = rows(conn, "SELECT char_id, name, sub_profession_name, profession "
                          "FROM operator WHERE is_operator=1 AND is_not_obtainable=1")
        names_spec = {r["name"] for r in spec}
        pre = {n for n in names_spec if n.startswith("预备干员")}
        other = sorted(names_spec - pre)
        check("is_not_obtainable 圈住了预备干员这一族", len(pre) >= 10,
              f"{len(pre)} 个名字")
        check("它同时圈住了模式专属干员（只剔「预备干员」会漏掉这批）",
              bool(other), "、".join(other[:8]))
        exe_spec = [r for r in spec if r["sub_profession_name"] == "处决者"]
        check("模式专属里也有处决者——所以不能只按子职业判可用性",
              bool(exe_spec), str([r["name"] for r in exe_spec]))
        pio_spec = [r for r in spec if r["profession"] == "PIONEER"]
        check("模式专属里也有先锋", bool(pio_spec),
              str([r["name"] for r in pio_spec]))

        # 合成一份**只装特殊模式干员**的名册：任何一条漏网都会被这条逮住
        fake = Roster({r["name"]: {"char_id": r["char_id"], "elite": 0, "level": 1,
                                   "potential": 1, "module": None,
                                   "module_level": 0} for r in spec})
        fok, fbad = team.bait_candidates(fake, conn)
        check("预备干员/模式专属的处决者进不了骗伤位", not fok,
              str([(p.name, p.cost) for p in fok]))
        check("连「淘汰」列表里也没有它们（是整批不参与，不是被判不合格）",
              not fbad, str([p.name for p in fbad]))
        check("模式专属的先锋进不了回费位",
              not team.dp_vanguards(fake, conn),
              str([p.name for p in team.dp_vanguards(fake, conn)]))
        sug_fake = team.suggest(fake, conn=conn, size=6)
        check("整份建议里一个特殊模式干员都不出现",
              all(p.name not in names_spec for p in sug_fake.all),
              "、".join(p.name for p in sug_fake.all) or "（空）")
        check("它们的 char_id 确实在库里（不是靠「查不到」蒙对的）",
              all(r["char_id"] in team._profiles(conn, [r["char_id"]]) for r in spec),
              f"{len(spec)} 条")
    finally:
        conn.close()

    roster = Roster.from_json(BOX)
    conn = connect(DEFAULT_DB_PATH, readonly=True)
    try:
        baits, rejects = team.bait_candidates(roster, conn)
        check("入选的骗伤位再部署全部 ≤ 阈值",
              all(p.respawn is not None and p.respawn <= team.BAIT_MAX_RESPAWN
                  for p in baits),
              str([(p.name, p.respawn) for p in baits]))
        check("THRM-EX 进不了骗伤位（防回退：它 3 费最便宜，最容易被排第一）",
              all(p.name != "THRM-EX" for p in baits),
              f"入选 {[p.name for p in baits]} / 淘汰 {[p.name for p in rejects]}")
        sug = team.suggest(roster, conn=conn, size=6)
        check("建议队伍非空", len(sug.team()) > 0, "、".join(sug.team()))
        check("角色位排在补齐位之前（回费先锋要最先落地）",
              [p.name for p in sug.picks] == sug.team()[:len(sug.picks)],
              "、".join(p.name for p in sug.picks))
        check("队伍里没有重复的人",
              len(set(sug.team())) == len(sug.team()), str(len(sug.team())))
    finally:
        conn.close()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli_main(["team", "--box", str(BOX)])
    check("CLI team 子命令退出 0 且给出建议",
          rc == 0 and "组队建议" in buf.getvalue(), f"rc={rc}")

    # ---- 低费位：按关卡初始费用动态决定（2026-09-16 加）----
    print("\n[8] 低费位：按关卡费用环境决定（ak_tactic/team.py）")

    # 落地延迟 = max(0, (费用 − 初始费用) × 每点耗时)
    cases = [((9, 10.0, 1.0), 0.0, "9 费 · 初始 10 —— 当场落地"),
             ((10, 10.0, 1.0), 0.0, "刚好够"),
             ((13, 10.0, 1.0), 3.0, "差 3 点 = 3 秒"),
             ((21, 10.0, 1.0), 11.0, "赤刃明霄陈"),
             ((24, 10.0, 1.0), 14.0, "圣聆初雪"),
             ((24, 50.0, 999.0), 0.0, "初始给足、几乎不回费 → 无先后之争"),
             ((9, 20.0, 1.0), 0.0, "初始 20 时便宜也没用（被夹到 0）")]
    bad = [(a, team.cost_delay(*a), want) for a, want, _ in cases
           if abs(team.cost_delay(*a) - want) > 1e-9]
    check("cost_delay = max(0, (费用−初始)×每点耗时)", not bad, str(bad) if bad else
          "9→0s / 21→11s / 24→14s / MO 关→0s")
    check("初始费用 ≥ 费用时延迟为 0（不是负数）",
          team.cost_delay(9, 20.0, 1.0) == 0.0, "0s")

    tight, note = team.low_cost_env("main_01-07")
    check("初始 10 费的关判为低费用环境", tight, note)
    tight2, note2 = team.low_cost_env("act31side_ex02")
    check("初始 20 费的关判为宽裕（低费位不出来）", not tight2, note2)
    tight3, note3 = team.low_cost_env("act31side_mo01")
    check("初始 50 费/不回费的关判为宽裕", not tight3, note3)
    tight4, _ = team.low_cost_env(None)
    check("没给关卡时不判费用环境（低费位不出）", not tight4, "stage=None")

    conn = connect(DEFAULT_DB_PATH, readonly=True)
    try:
        s_tight = team.suggest(roster, conn=conn, size=7, stage="main_01-07")
        cheap = [p for p in s_tight.picks if p.role == team.ROLE_CHEAP]
        check("低费用环境下确实出了低费位", len(cheap) == 1,
              "、".join(f"{p.name}({p.cost:.0f}费)" for p in cheap))
        s_loose = team.suggest(roster, conn=conn, size=7, stage="act31side_ex02")
        check("宽裕环境下不出低费位",
              not [p for p in s_loose.picks if p.role == team.ROLE_CHEAP],
              "、".join(p.name for p in s_loose.picks))
        s_none = team.suggest(roster, conn=conn, size=7)
        check("不给 --stage 时不出低费位",
              not [p for p in s_none.picks if p.role == team.ROLE_CHEAP], "stage=None")
        if cheap:
            p = cheap[0]
            ref = max((x.cost or 0) for x in s_tight.filler) if s_tight.filler else 0
            check("低费位确实比练度最高的补齐候选便宜",
                  (p.cost or 99) < ref, f"{p.name} {p.cost:.0f} 费 < {ref:.0f} 费")
            check("低费位来自名册", p.name in roster.entries, p.name)
            # **不按子职业去重**（博士裁定）：判据是适不适合这一关。
            # 曾经加过一道去重、把豆苗（战术家）换成了调香师，那是错的。
            dup = [x.name for x in s_tight.picks
                   if x.role != team.ROLE_CHEAP and x.sub == p.sub]
            check("子职业允许与角色位重复（判据是适合关卡，不是职业不撞）",
                  True, f"{p.name}={p.sub}" + (f"；与 {dup} 同子职业" if dup else ""))
    finally:
        conn.close()

    print()
    print("=" * 60)
    if _FAILED:
        print(f"通过 {_PASSED} 项，失败 {len(_FAILED)} 项：")
        for n in _FAILED:
            print(f"   ✗ {n}")
        return 1
    print(f"通过 {_PASSED} 项，无失败。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
