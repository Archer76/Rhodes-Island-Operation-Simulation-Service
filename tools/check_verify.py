# -*- coding: utf-8 -*-
"""通用验证器自检。

分七节：**打法数据**（Plan 的存取与守卫）、**名册**（两种格式）、
**落位守卫**、**星级规则**、**三关基线回归**、**构造保真度**、**CLI**。

跑法：`python tools/check_verify.py`
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from ak_tactic.plan import (DeployOrder, Plan, PlanError, Roster,   # noqa: E402
                            RetreatOrder, SkillOrder)
from ak_tactic.verify import Verifier, stars_of, verify             # noqa: E402

_PASSED = 0
_FAILED: list[str] = []

from operbox_path import operbox_path                                  # noqa: E402

#: 账号名册是**外部输入**，不入库：见 tools/operbox_path.py 的两种取法。
BOX = operbox_path()

#: 1-7 无技能三人组。**这就是 `tools/check_battle.py` 的基线**，
#: 落位与**时刻**逐字对齐它，只为证明验证器与既有脚本同一口径。
#:
#: **2026-09-18 时刻已按真实费用机制重排**（原为 1.0 / 5.0 / 9.0s）。1-7 初始
#: 10 费、1 秒回 1 点，而三人是 18 / 13 / 19 费共 50 费——旧时刻在真实规则下
#: **做不出来**，模拟器会逐笔记进 `BattleResult.cost_denied`（1.0s 阿米娅差 7 费、
#: 9.0s 拉普兰德差 13 费，只有 5.0s 的德克萨斯够）。旧口径等于**替玩家免了
#: 39 秒的费**。重排取各自最早付得起的时刻再加 1 秒余量（不加余量会卡在离散
#: 回费节拍的缝里）。新结论 39 杀 / 2 漏 / 58650，耗时仍是 137.0s。
BASELINE_17 = [
    ("阿米娅", (5, 2), "Left", 0, dict(elite=2, level=80, trust=100,
                                       potential=6), 9.0),
    ("德克萨斯", (4, 3), "Right", 0, dict(elite=2, level=1), 22.0),
    ("拉普兰德", (2, 3), "Right", 0, dict(elite=2, level=1), 41.0),
]


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(label)
        print(f"  [FAIL] {label}" + (f"   {detail}" if detail else ""))


def close(a, b, tol: float = 0.05) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def raises(fn) -> str:
    """跑一下，返回异常文本；没抛就返回空串。"""
    try:
        fn()
    except Exception as exc:                       # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    return ""


def plan_17(**kw) -> Plan:
    return Plan(stage="main_01-07", title="1-7 基线", deploys=[
        DeployOrder(n, pos, d, slot, time=t, **extra)
        for n, pos, d, slot, extra, t in BASELINE_17], **kw)


# ---------------------------------------------------------------- 1 打法数据

def check_plan() -> None:
    print("\n[1] 打法数据：Plan 的存取与守卫")
    p = plan_17()
    check("构造成功、三个部署", len(p.deploys) == 3)

    blob = json.dumps(p.to_dict(), ensure_ascii=False)
    back = Plan.from_dict(json.loads(blob))
    check("JSON 往返后逐条相同",
          [d.to_dict() for d in back.deploys] == [d.to_dict() for d in p.deploys],
          blob[:70])
    d0 = back.deploys[0]
    check("往返保住坐标、朝向、时刻",
          d0.position == (5, 2) and d0.direction == "Left" and close(d0.time, 9.0),
          f"{d0.position} {d0.direction} {d0.time}")
    check("往返保住信赖与潜能（影响属性，不能丢）",
          d0.trust == 100 and d0.potential == 6,
          f"trust={d0.trust} potential={d0.potential}")

    with tempfile.TemporaryDirectory() as td:
        f = pathlib.Path(td) / "p.json"
        p.dump(f)
        check("写到文件再读回来一致",
              Plan.load(f).deploys[2].operator == "拉普兰德")
        check("文件是可读的中文 JSON（不是 \\u 转义）",
              "阿米娅" in f.read_text(encoding="utf-8"))
        check("坐标写在一行（人手要改的字段，不能被 indent 拆成四行）",
              '"position": [5, 2]' in f.read_text(encoding="utf-8"))

    # —— 守卫：每一条都对应一类"模拟器不会替你拦下"的错误 ——
    check("同一格放两个人被拦下",
          "挤在同一格" in raises(lambda: Plan(stage="x", deploys=[
              DeployOrder("甲", (1, 1)), DeployOrder("乙", (1, 1))]).validate()))
    check("同一人部署两次被拦下",
          "部署了两次" in raises(lambda: Plan(stage="x", deploys=[
              DeployOrder("甲", (1, 1)), DeployOrder("甲", (2, 2))]).validate()))
    check("空打法被拦下",
          "一个部署都没有" in raises(lambda: Plan(stage="x").validate()))
    check("没写关卡号被拦下",
          "关卡号" in raises(lambda: Plan(stage="", deploys=[
              DeployOrder("甲", (1, 1))]).validate()))
    check("朝向写错被拦下（拼错的朝向不会静默当 Right）",
          "不认识" in raises(lambda: DeployOrder("甲", (1, 1), "right")))
    check("技能槽越界被拦下",
          "越界" in raises(lambda: DeployOrder("甲", (1, 1), "Right", 4)))
    check("撤退了没部署的人被拦下",
          "没部署过" in raises(lambda: Plan(stage="x", deploys=[
              DeployOrder("甲", (1, 1))],
              retreats=[RetreatOrder("乙", 10.0)]).validate()))
    check("给没部署的人开技能被拦下",
          "没部署" in raises(lambda: Plan(stage="x", deploys=[
              DeployOrder("甲", (1, 1))],
              skills=[SkillOrder("乙", 10.0)]).validate()))

    # —— quick 语法 ——
    q = Plan.quick("main_01-07",
                   "阿米娅:5,2:Left:0@1; 德克萨斯:4,3:Right:0@5")
    check("quick 用 `;` 分隔干员、`,` 留给坐标",
          [d.operator for d in q.deploys] == ["阿米娅", "德克萨斯"])
    check("quick 的 `@时刻` 生效",
          close(q.deploys[0].time, 1.0) and close(q.deploys[1].time, 5.0),
          f"{q.deploys[0].time} / {q.deploys[1].time}")
    check("quick 不给时刻就是 None（按费用自动排）",
          Plan.quick("x", "甲:1,1").deploys[0].time is None)
    check("quick 写成逗号分隔会给出可读的错误，而不是错坐标",
          "分隔" in raises(lambda: Plan.quick("x", "阿米娅:5,4:Left, 德克萨斯:6,3"))
          or "分隔" in raises(lambda: Plan.quick("x", "阿米娅:5,4, 德克萨斯:6,3")),
          raises(lambda: Plan.quick("x", "阿米娅:5,4, 德克萨斯:6,3"))[:70])
    check("quick 抛的是 PlanError（不是裸 ValueError，调用方能统一接住）",
          raises(lambda: Plan.quick("x", "阿米娅:5,4, 德克萨斯:6,3")
                 ).startswith("PlanError"))


# ---------------------------------------------------------------- 2 名册

def check_roster() -> None:
    print("\n[2] 名册：两种格式都能吃")
    if not BOX.exists():
        check("OperBox 文件在（没有就跳过本节）", False, str(BOX))
        return
    r = Roster.from_json(BOX)
    check(f"OperBox 载入 {len(r)} 人", len(r) > 100)
    check("阿米娅在名册里", "阿米娅" in r)
    a = r.get("阿米娅")
    check("条目含 char_id/elite/level/potential",
          bool(a.get("char_id")) and a["elite"] is not None
          and a["level"] is not None and a["potential"] is not None,
          str(a))
    check("`own=false` 的不收（没抽到的干员不算练度）",
          all(r.entries.values()))

    fake = {"uid": "1", "nickName": "x", "count": 1, "opers": [
        {"charId": "char_002_amiya", "name": "阿米娅", "elite": 2,
         "level": 80, "potential": 6, "module": None, "module_level": 0}]}
    with tempfile.TemporaryDirectory() as td:
        f = pathlib.Path(td) / "roster.json"
        f.write_text(json.dumps(fake, ensure_ascii=False), encoding="utf-8")
        r2 = Roster.from_json(f)
    check("森空岛名册（`opers` 在字典里）也能吃",
          len(r2) == 1 and r2.get("阿米娅")["char_id"] == "char_002_amiya")


# ---------------------------------------------------------------- 3 落位守卫

def check_terrain() -> None:
    print("\n[3] 落位守卫：模拟器不校验地形，验证器必须替它校验")
    v = Verifier()
    stage = v.stage("main_01-07")
    # 阿米娅是 CASTER（高台），(5,2) 是高台；德克萨斯是先锋，(4,3) 是地面
    ok = Plan(stage="main_01-07", deploys=[
        DeployOrder("阿米娅", (5, 2), "Left", elite=2, level=80)])
    check("术师站高台合法", not raises(lambda: v.run(ok)))

    bad = Plan(stage="main_01-07", deploys=[
        DeployOrder("阿米娅", (4, 3), "Left", elite=2, level=80)])
    msg = raises(lambda: v.run(bad))
    check("术师站地面被拦下（否则会安静地跑出一个'看起来对'的结果）",
          "落点非法" in msg, msg[:80])

    bad2 = Plan(stage="main_01-07", deploys=[
        DeployOrder("德克萨斯", (5, 2), "Right", elite=2, level=1)])
    check("先锋站高台被拦下", "落点非法" in raises(lambda: v.run(bad2)))
    check("提示里点明坐标口径，免得有人再翻一次",
          "MAA 口径" in msg)


# ---------------------------------------------------------------- 4 星级

def check_stars() -> None:
    print("\n[4] 星级规则（**规则由博士 2026-09-18 实机口述确认**）")
    check("不漏怪 = 三星", stars_of(True, 0) == 3)
    check("漏 1 只 = 二星", stars_of(True, 1) == 2)
    check("漏 2 只**也是二星**（漏几只同档）", stars_of(True, 2) == 2)
    check("漏 5 只仍是二星（只要生命没扣完）", stars_of(True, 5) == 2)
    # 这条是**负向**守卫：旧实现写的是「漏 2 只及以上 1 星」，而游戏里
    # 根本没有一星这一档。留着它，那个错误就再也回不来。
    check("**没有一星这一档**（漏多少只都不给 1 星）",
          all(stars_of(True, n) != 1 for n in range(0, 30)))
    check("没打赢 = 0 星（无论漏几只）", stars_of(False, 0) == 0)
    check("没打赢且漏光 = 0 星", stars_of(False, 10) == 0)
    check("突袭无漏 = 四星", stars_of(True, 0, challenge=True) == 4)
    check("突袭漏怪 = 二星（突袭加成只在无漏时给）",
          stars_of(True, 1, challenge=True) == 2)

    p = plan_17()
    v = Verifier().run(p)
    check("Verdict 原样带出 won/life/max_life/leaks 供改判",
          v.won and v.leaks == 2 and v.life == v.max_life - v.leaks > 0,
          f"won={v.won} life={v.life}/{v.max_life} leaks={v.leaks}")


# ---------------------------------------------------------------- 5 回归

def check_baselines() -> None:
    print("\n[5] 基线回归（1-7 两条路 / 怀黍离普通 01 与 05）")

    # —— 1-7。**两条路都要锚** ——
    real = Verifier().run(plan_17())
    check("1-7 真实范围：133.0s",
          close(real.elapsed, 133.0, 0.2), f"实得 {real.elapsed:.1f}s")
    check("1-7 真实范围：39 杀 / 2 漏 / 58650（按真实费用重排后的数）",
          real.kills == 39 and real.leaks == 2 and close(real.damage, 58650, 1),
          f"{real.kills} 杀 {real.leaks} 漏 {real.damage:,.0f}")
    # 重排前是 41 杀 / 0 漏 / 60750 三星；那三个时刻在真实费用下做不出来，
    # 晚上场 39 秒就必然漏掉两只。所以这里**如实钉住二星**——要三星得改方案，
    # 不能把期望值改回三星了事。
    check("1-7 真实范围：二星（重排后漏 2 只，如实钉住）", real.stars == 2,
          f"实得 {real.stars} 星")

    deg = Verifier(use_range_table=False).run(plan_17())
    check("1-7 退化范围：137.0s（= check_battle 锚的那条路）",
          close(deg.elapsed, 137.0, 0.2), f"实得 {deg.elapsed:.1f}s")
    check("两条路的击杀与伤害相同、只差耗时（说明差异来自覆盖格数）",
          deg.kills == real.kills and close(deg.damage, real.damage, 1)
          and deg.elapsed > real.elapsed,
          f"{deg.kills}/{real.kills} 杀，{deg.elapsed:.1f} vs {real.elapsed:.1f}s")

    # —— 怀黍离（act31side）普通关两条 ——
    #
    # **2026-09-18 换基线**：原先是月行水上（act54side）的 SR-6 与 SR-EX-8 四人
    # 剑气作业。换掉的理由不是它们"过期"，而是**它们失去了真值来源**：
    # 该活动在真实游戏里已经结束，博士没法再实机复核；而那两条数字又只在
    # 「技能倍率乘两次」的旧口径下成立——裁定改口径后实测，SR-EX-8 从
    # `38 杀 / 1 漏 / 剩 2 命` 掉到 `10 杀 / 3 漏 / 命 0`（伤害 1,510,762 →
    # 475,444），SR-6 的耗时从 196.6s 走到 271.1s（击杀/漏怪/总伤害不变）。
    # 详见 `docs/uncertainties.md` §二十一「裁定与后果」。
    #
    # 新基线取怀黍离普通第一关与第五关，**练度写死在用例里**（不读名册、不读
    # 账号导出）：坐标自洽、谁都能复跑。两条各锚一条不同的通道——
    # 01 关是「技能 + 积雪」的常规路径，05 关单干员走**技3（五锤）**那条通道。
    hs1 = Verifier().run(Plan(stage="act31side_01", deploys=[
        DeployOrder("圣聆初雪", (4, 4), "Right", skill=2, mastery=3,
                    elite=2, level=90),
        DeployOrder("怒潮凛冬", (2, 5), "Right", skill=2, mastery=3,
                    elite=2, level=60)]))
    check("怀黍离 01「赴大荒」两人：128.7s / 50 杀 / 0 漏 / 3 命",
          close(hs1.elapsed, 128.7, 0.2) and hs1.kills == 50 and hs1.leaks == 0
          and hs1.life == 3,
          f"{hs1.elapsed:.1f}s {hs1.kills}杀 {hs1.leaks}漏 命{hs1.life}")
    check("怀黍离 01：三星", hs1.stars == 3, f"{hs1.stars} 星")

    hs5 = Verifier().run(Plan(stage="act31side_05", deploys=[
        DeployOrder("怒潮凛冬", (9, 4), "Up", skill=3, mastery=3,
                    elite=2, level=60)]))
    check("怀黍离 05「纺绫罗」单干员（怒潮凛冬技3）：201.4s / 46 杀 / 0 漏 / 3 命",
          close(hs5.elapsed, 201.4, 0.2) and hs5.kills == 46 and hs5.leaks == 0
          and hs5.life == 3,
          f"{hs5.elapsed:.1f}s {hs5.kills}杀 {hs5.leaks}漏 命{hs5.life}")
    check("怀黍离 05：三星", hs5.stars == 3, f"{hs5.stars} 星")
    check("  技3 真的开出来了（否则这条基线覆盖不到五锤那条通道）",
          getattr(hs5.result, "skill_activations", 0) > 0,
          f"开技 {getattr(hs5.result, 'skill_activations', '?')} 次")

    # 漏怪明细要有内容——换一份必定漏怪的极端阵容来验
    weak = Verifier().run(Plan(stage="main_01-07", deploys=[
        DeployOrder("德克萨斯", (4, 3), "Right", elite=2, level=1)]))
    check("真的漏怪时 leak_events 有内容、且带时刻与扣血",
          bool(weak.leak_events) and all(
              isinstance(t, float) and isinstance(n, str) and isinstance(c, int)
              for t, n, c in weak.leak_events),
          f"{len(weak.leak_events)} 条，首条 {weak.leak_events[:1]}")


# ---------------------------------------------------------------- 6 保真度

def check_fidelity() -> None:
    print("\n[6] 构造保真度：验证器造的单位要与 tools/squad.py 逐字段一致")
    try:
        from squad import Roster as SquadRoster
    except ImportError:
        check("squad.py 不可用，跳过", False)
        return
    sq = SquadRoster()
    v = Verifier()
    names = [n for n in ("赤刃明霄陈", "圣聆初雪", "凯尔希·思衡托",
                         "予愿安洁莉娜", "阿米娅") if sq.has(n)]
    fields = ("max_hp", "atk", "defense", "res", "attack_interval",
              "block_cnt", "deploy_cost", "attack_type", "heals",
              "weakness_damage")
    for n in names:
        r = sq.get(n)
        mine = v.unit({"char_id": r["charId"], "elite": r["elite"],
                       "level": r["level"], "potential": r["potential"],
                       "trust": r["trust"], "module": r.get("module"),
                       "module_level": r.get("module_level")})
        theirs = sq.unit(n)
        diff = [(f, getattr(mine, f), getattr(theirs, f)) for f in fields
                if getattr(mine, f) != getattr(theirs, f)]
        check(f"{n}：{len(fields)} 个字段全一致", not diff, str(diff))
    check("攻法类型不是全都退化成物理（曾整片踩过）",
          len({v.unit({"char_id": sq.get(n)["charId"],
                       "elite": sq.get(n)["elite"], "level": sq.get(n)["level"],
                       "potential": sq.get(n)["potential"],
                       "trust": sq.get(n)["trust"],
                       "module": sq.get(n).get("module"),
                       "module_level": sq.get(n).get("module_level"),
                       }).attack_type for n in names}) > 1)


# ---------------------------------------------------------------- 7 CLI

def check_cli() -> None:
    print("\n[7] CLI 与报告")
    from ak_tactic.cli import main as cli_main
    import io
    import contextlib

    # 不给 --box 又没有练度：必须**报错退出而不是猜一个默认练度**
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli_main(["verify", "main_01-07", "--team", "阿米娅:5,2:Left:0@1"])
    check("练度没着落时退出 2、且提示要点明原因", rc == 2,
          f"rc={rc}；{buf.getvalue().strip()[:60]}")

    if not BOX.exists():
        check("CLI 正常路径（需要 OperBox，跳过）", False, str(BOX))
        return
    # 这节测的是 **CLI 管道**（存盘、往返、退出码），不是某一份具体方案。
    # 所以样例必须是一份**真能三星**的阵容——否则退出码会如实变成 1，
    # 把"管道坏了"和"样例本来就打不过"混成同一条红灯。
    # 用不带 `@时刻` 的写法，交给自动排期（它会按真实费用排到付得起为止）。
    team = ("拉普兰德:2,3:Left:0; 能天使:3,1:Down:0; 银灰:4,3:Left:0")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli_main(["verify", "main_01-07", "--team", team,
                       "--box", str(BOX), "--json"])
    out = buf.getvalue()
    check("`verify … --json` 退出码 0", rc == 0, f"rc={rc}；{out[:80]}")
    data = json.loads(out)
    check("JSON 里有 stars/won/life/operators",
          all(k in data for k in ("stars", "won", "life", "operators")),
          str(sorted(data))[:80])
    check("三星时 stars=3", data["stars"] == 3, str(data["stars"]))
    check("JSON 里不含 BattleResult 这种活对象",
          data.get("result") is None, str(type(data.get("result"))))

    # 存盘 → 只给 --plan 再跑（关卡号不该被要求重复输入）
    with tempfile.TemporaryDirectory() as td:
        f = pathlib.Path(td) / "p.json"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc1 = cli_main(["verify", "main_01-07", "--team", team,
                            "--box", str(BOX), "--save-plan", str(f), "--json"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc2 = cli_main(["verify", "--plan", str(f), "--box", str(BOX),
                            "--json"])
        check("存盘 → 只给 --plan（不重复关卡号）也能跑", rc1 == 0 and rc2 == 0,
              f"save={rc1} load={rc2}")
        check("两条路的结论一致",
              json.loads(buf.getvalue())["stars"] == data["stars"])

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli_main(["verify", "--team", "德克萨斯:4,3:Right:0"])
    check("用 --team 却不给关卡号 → 退出 2 并说明原因", rc == 2, f"rc={rc}")

    from ak_tactic.verify import Verdict
    v = Verdict(stars=1, won=True, life=2, max_life=3, kills=39, leaks=1,
                elapsed=100.0, damage=1234.0, title="样例",
                leak_events=[(36.0, "源石虫·α", 1)],
                diagnosis=["通关但只有 1 星：漏了 1 只。"])
    rep = v.report()
    check("报告含星级、漏怪明细与归因",
          "★☆☆" in rep and "源石虫·α" in rep and "归因" in rep)
    check("`ok` 只对三星为真", not v.ok)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli_main(["verify", "main_01-07"])
    check("既没给 --plan 也没给 --team 时报错退出 2（不给默认阵容）",
          rc == 2, f"rc={rc}")


# ---------------------------------------------------------------- 8 可重复性

def check_reuse() -> None:
    """同一个 Verifier 复用多次必须逐字相同。

    这是**搜索器的前提**——搜索要用同一个验证器跑几百上千次。曾经在这里
    栽过一次：给 `Verifier.unit` 加缓存时缓存了造好的 `OperatorUnit` 而不是
    构造参数，而模拟器会原地改写它（hp/alive/hits）。症状是搜索器里
    「多下一个人反而 0 击杀」——那个单位的血在上一局就打光了。
    """
    print("\n[8] 可重复性：同一个 Verifier 复用多次必须逐字相同")
    roster = Roster.from_json(BOX)
    v = Verifier()
    dev = [DeployOrder("拉普兰德", (2, 3), "Left"),
           DeployOrder("能天使", (3, 1), "Down"),
           DeployOrder("银灰", (4, 3), "Left")]
    runs = [v.run(Plan(stage="main_01-07", deploys=dev),
                  roster=roster).line() for _ in range(3)]
    check("同一方案连跑 3 次结果逐字相同（单位不能被跨局复用）",
          len(set(runs)) == 1,
          runs[0] if len(set(runs)) == 1 else f"{len(set(runs))} 种：{runs}")
    check("复用后仍是三星（没有被上一局的残血拖垮）",
          "★★★" in runs[-1], runs[-1])

    alt = []
    for _ in range(2):
        a = v.run(Plan(stage="main_01-07", deploys=dev),
                  roster=roster).line()
        b = v.run(Plan(stage="main_01-07", deploys=[
            DeployOrder("拉普兰德", (2, 3), "Left")]),
            roster=roster).line()
        alt.append((a, b))
    check("两个方案交替跑，各自结果稳定（不互相污染）",
          alt[0] == alt[1], f"{alt[0][0]} | {alt[0][1]}")
    check("单人方案与三人方案确实不同（交替不是因为都没生效）",
          alt[0][0] != alt[0][1], f"{alt[0][0]} != {alt[0][1]}")


def main() -> int:
    print("检查通用验证器（ak_tactic/plan.py + ak_tactic/verify.py）")
    check_plan()
    check_roster()
    check_terrain()
    check_stars()
    check_baselines()
    check_fidelity()
    check_cli()
    check_reuse()
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
