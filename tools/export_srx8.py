"""把 SR-EX-8 的一套站位导出成 MAA copilot JSON，供实机对照。

**这份导出器的唯一职责是「与模拟同源」。** 动作顺序、落点、朝向、技能槽
全部取自同一次 `BattleSimulator` 运行所用的同一份 plan；JSON 里刻意不写
部署时刻——MAA 与本项目的模拟器用的是同一套规则（按费用够不够依次部署），
所以写死时刻反而会造成两边不一致。

坐标：本项目**内部就是 MAA 口径**（原点左上、y 自上而下），所以
`location: [x, y]` 直接写项目坐标即可，**没有任何换算**。

干员口径走森空岛名册（`tools/squad.py`）：**真实专精、真实模组、真实信赖**。

`requirements` 的字段名与取值范围以 MAA 官方协议为准
（https://docs.maa.plus/zh-cn/protocol/copilot-schema.html）：

* `module` 是**模组类型编号**——游戏里模分 X / Y / Z 三型，MAA 写 1 / 2 / 3。
  **不是**模组 id，也**不是** `uniequip_00N_xxx` 里的 N（见 `module_slot`）。
* **没有生效模组的干员必须整个省略这个键**：写 `0` 会让 MAA 不识别整份作业
  （实测，博士指出）。省略 = 不校验模组。
* `module_level` 在协议里有字段，但 `requirements` 整块官方标注
  「保留接口，暂未实现」，所以模组等级只能写进 `doc.details` 让人看，
  指望不上机器校验。

    python tools/export_srx8.py                 # 跑全部候选，导出全部
    python tools/export_srx8.py --plan 1        # 只导出第 1 个候选
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from ak_tactic.gamedata import (                                          # noqa: E402
    EnemyLibrary, GameDataSource, RangeTable, load_stage,
)
from ak_tactic import maa_export as maa                                   # noqa: E402
from ak_tactic.operator import SkillBook, TalentBook                      # noqa: E402
from ak_tactic.parallel import pmap                                       # noqa: E402
from run_srx8 import make_provider, run_plan, PlanError                   # noqa: E402
from squad import Roster                                                  # noqa: E402

STAGE_ID = "act54side_ex08"
OUT_DIR = pathlib.Path(__file__).resolve().parents[1] / "out"

#: 落点是**本项目坐标 = MAA 口径**（原点左上、y 向下），导出时原样写入
#: `location: [x, y]`，不做任何换算。（改口径前的注释写的是「y 从下往上」，
#: 那些行列早已按 `y_新 = H-1-y_旧` 换过，别再翻第二次。）
#:
#: ## 这一版为什么换了人：剑气
#:
#: 此前的编队（机械师 / 圣聆初雪 / 予愿安洁莉娜 / 凯尔希 / 阿斯卡纶）在
#: **本关真正的规则**下是过不去的——BOSS「死志的凝结」**每倒地一次就翻转一次
#: 免疫类型**（博士实机确认），而相性「免疫」是**该类型伤害全部归零**。
#: 于是 `Mode_A`（物弱·法免）里物理才能攒击破值、`Mode_B`（物免·法弱）里只有
#: 法术才碰得动它，**任何单一伤害类型的队伍都会在它另一半形态里彻底哑火**。
#: 旧编队在 knock 读法下的实测是 31 杀 3 漏 / 22 杀 4 漏，全部失败。
#:
#: 破解它的是**赤刃明霄陈**：天赋「形意洞照」把她的攻击变成**弱点伤害**——
#: 每次结算都同时按物理与法术各算一遍，取高的那一种。免疫归零之后，"高的那种"
#: 自然就是**当前没被免疫的那种**，所以她**在 BOSS 的两套形态里都打得动、
#: 都能攒击破值**。技3 的剑气（向前、遇障碍右转、20 秒）再从侧面反复扫同一条
#: 走廊，拐弯时命中状态刷新，一次技能可以扫过同一个敌人好几遍。
#:
#: 实测：四人（赤刃明霄陈 + 予愿安洁莉娜 + 凯尔希·思衡托 + 圣聆初雪）
#: 在「不换 / 每 30 秒 / 每倒地一次」三种读法、敌速 ×0.85–×1.5 的全部组合下
#: **全胜、0 漏、剩 3 命**，BOSS 倒地 15 次。旧编队的两个方案在同一条件下全败。
#:
#: ## 两个必须随作业一起说出去的未知量
#:
#: * **剑气速度**：原文没写。默认 4 格/秒。扫描 v=3…20 全胜 0 漏；v=2 勉强胜
#:   （2 漏剩 1 命）；v≤1.5 会败。这条作业因此**依赖剑气不太慢**。
#: * **BOSS 换形态的节奏**已经定案（每倒地一次），不再是不确定项。
PLANS: list[tuple[str, list]] = [
    ("四人·剑气主方案（三种读法全胜；实测剑气速度 1.2 下 38 杀 1 漏，非三星）",
     [("赤刃明霄陈", (4, 2), "Left", 3),
      ("予愿安洁莉娜", (1, 4), "Right", 3),
      ("凯尔希·思衡托", (8, 3), "Right", 2),
      ("圣聆初雪", (10, 4), "Right", 2)]),
    ("五人·剑气备选（多一个阿斯卡纶，打右簇更厚）",
     [("赤刃明霄陈", (4, 2), "Left", 3),
      ("予愿安洁莉娜", (1, 4), "Right", 3),
      ("凯尔希·思衡托", (8, 3), "Right", 2),
      ("阿斯卡纶", (11, 4), "Left", 3),
      ("圣聆初雪", (10, 4), "Right", 2)]),
]


#: 模组**类型字母** → MAA 的 `module` 编号。判据与对应表见 `ak_tactic.maa_export` 的模块文档。
#:
#: 老实现写的是 `{"X": 1, "Y": 2, "Z": 3}`，**两处错**：`Z` 在 905 条模组里一次都没出现过
#: （死项），而 `D` 漏了。那 6 条 D 型（黑键/艾拉/**逻各斯**/伊芙利特/薇薇安娜/棘刺）
#: 全是 `classify == ok` 的普通专属模组，照旧写法它们的模组要求会被静默丢掉。
#: 一直没暴露，是因为撞见过的干员（赤刃明霄陈 X、圣聆初雪 Y、阿斯卡纶 X、望 X）全在 X/Y 上。
MODULE_SLOT = maa.MODULE_SLOT


def roster_module_slot(roster: Roster, name: str) -> int | None:
    """名册里的干员 → MAA 的 `module` 编号；**没有生效模组时返回 `None`（该键整个省略）**。

    两道门：① `equipped_status == "ok"`——模组三道门（非基础证章、非特限/特勤、有战斗数值）
    由 `tools/roster.py` 建名册时就判好了；② 类型字母在 `MODULE_SLOT` 里。
    编号的取法、为什么不能解析 id 里的数字，全在 `ak_tactic.maa_export` 的模块文档里。

    **没有模组时必须整个省略 `module` 键**，不能写 `0`——博士实机确认写 `0` 会让
    **整份作业不被 MAA 识别**（不是"忽略这一条要求"，是"不识别"）。
    省略 = 不作要求，在两种读法下都安全。
    """
    r = roster.get(name)
    if r.get("equipped_status") != "ok":
        return None
    # `module` 是"算符该用的那个"，`equipped_module` 是账号实际装着的；
    # 上面那道 status 门保证两者在 ok 时是同一个 id，取谁都行。
    return maa.module_slot(r.get("module") or r.get("equipped_module"))


def skill_usage(roster: Roster, name: str, slot: int) -> int:
    """MAA 的技能用法。转发到 `ak_tactic.maa_export.skill_usage`——那边是唯一实现。

    原先这里和 `to_maa` 各有一份判 `自动触发` 的代码，与包内那份迟早要漂。
    """
    return maa.skill_usage(roster, name, slot)


def build_context():
    """把关卡 / 敌人库 / 范围提供者 / 名册 / 技能书 / 天赋书建起来。

    抽成函数是为了**让并行 worker 用与主进程逐字同源的构造代码**。这些东西
    **全都不可 pickle**（`EnemyLibrary`/`SkillBook`/`TalentBook` 内部有
    `_thread.lock`，`RangeProvider` 是闭包），所以扫描不能把它们当参数投给
    子进程，只能让子进程自己重建一遍。
    """
    src = GameDataSource()
    stage = load_stage(STAGE_ID, source=src)
    lib = EnemyLibrary(source=src)
    book = SkillBook()
    talents = TalentBook()
    roster = Roster()
    provider = make_provider(roster.calc, RangeTable())
    return stage, lib, provider, roster, book, talents


#: worker 进程里建一次的共同前提。键与 `build_context` 的返回值对应。
_SWEEP_CTX: dict = {}


def _sweep_init() -> None:
    """每个 worker 建一次扫描前提——**不是每个扫描点建一次**。"""
    (stage, lib, provider, roster, book,
     talents) = build_context()
    _SWEEP_CTX.update(stage=stage, lib=lib, provider=provider,
                      roster=roster, book=book, talents=talents)


def _sweep_one(spec):
    """跑一个扫描点。

    `spec = (kind, value, plan)`：`kind` 是 speed / qi / mode，`plan` 是候选
    编队（它本身就是纯 tuple 列表，可 pickle）。返回**只有标量**——`run_plan`
    还回一个 `sim`，那是活对象，不能跨进程传。

    主结果与敏感性用的是**同一个 `run_plan`、同一套开关**，并行只改变
    "在哪个进程里跑"，不改变算法。
    """
    kind, value, plan = spec
    kw: dict = {"ranged_enemies": True, "boss_mode_switch": "knock",
                "affinity_blocks_damage": True}
    if kind == "speed":
        kw["speed_scale"] = value
    elif kind == "qi":
        kw["sword_qi_speed"] = value
    elif kind == "mode":
        kw["boss_mode_switch"] = value
    else:
        raise ValueError(f"未知的扫描维度：{kind}")
    _sim, r, _d, _w = run_plan(_SWEEP_CTX["stage"], _SWEEP_CTX["lib"],
                               _SWEEP_CTX["provider"], _SWEEP_CTX["roster"],
                               _SWEEP_CTX["book"], _SWEEP_CTX["talents"],
                               plan, **kw)
    return (kind, value, r.won, r.leaks, r.kills)


#: 扫描点。三组放在一起投递，是为了**跨过并行的最小批量门槛**——单独一组
#: （剑速 10 点、敌速 7 点、形态 3 点）都太小，进程池的开销盖过收益。
SPEED_SCALES = (0.85, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5)
QI_SPEEDS = (1.0, 1.1, 1.2, 1.22, 1.25, 1.3, 1.4, 1.5, 2.0, 4.0)
BOSS_MODES = (("knock", "每倒地一次★"), ("none", "不换"), ("time", "每30秒"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=int, default=0, help="只导出第 N 个候选（1 起算）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    (stage, lib, provider, roster, book,
     talents) = build_context()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    H = stage.map.height
    print(f"=== {stage.summary()} ===")
    print(f"名册 {roster.path.name}  uid={roster.uid} [{roster.nick}]")
    print("模组判定（MAA 的 module = 类型字母 X/Y/A/D/B → 1/2/3/4/5；无生效模组则省略该键）：")
    for n in dict.fromkeys(n for n, *_ in sum((p for _t, p in PLANS), [])):
        r0 = roster.get(n)
        eq = r0.get("equipped_module")
        entry = (roster.calc._load_uniequip() or {}).get(eq or "") or {}
        slot = roster_module_slot(roster, n)
        print(f"    {n:<12} {eq or '—':<26} typeName2={entry.get('typeName2') or '—':<3} "
              f"status={r0.get('equipped_status')} → "
              f"{'module=' + str(slot) if slot else '省略 module'}")
    print()

    todo = [(args.plan, PLANS[args.plan - 1])] if args.plan else list(enumerate(PLANS, 1))
    written = []
    for idx, (title, plan) in todo:
        missing = [n for n, *_ in plan if not roster.has(n)]
        if missing:
            print(f"【{idx} {title}】跳过——名册里没有：{missing}")
            continue
        try:
            # 主跑一律用**已确认的规则**：相性免疫 = 该类型伤害归零
            # （`affinity_blocks_damage=True`），且 BOSS **每倒地一次换一次**形态
            # （`boss_mode_switch="knock"`）。别再用"不换"当默认值报成绩——
            # 那是虚构的读法，会让一份实机必崩的作业看起来很漂亮。
            sim, r, detail, warns = run_plan(stage, lib, provider, roster, book,
                                             talents, plan, verbose=args.verbose,
                                             ranged_enemies=True,
                                             boss_mode_switch="knock",
                                             affinity_blocks_damage=True)
        except PlanError as e:
            print(f"【{idx} {title}】{e}")
            continue
        dev = sim.total_attack
        trig = dev.triggers if dev else 0
        blocker = dev.to_dict()["last_blocker"] if dev else "—"
        knocks = max(sim._knocks.values()) if sim._knocks else 0
        # 余量 = 收场时最虚弱的**活着**的干员还剩多少血。阵亡者单列——
        # 把阵亡算成"余量 0%"会把"人死了但没漏怪"和"全线崩"混成一句话。
        alive = [o for o in sim.operators if o.alive]
        head = min((o.hp_ratio for o in alive), default=0.0)
        thinnest = min(alive, key=lambda o: o.hp_ratio, default=None)
        dead = "、".join(f"{o.name}（{o.death_time:.0f}s 阵亡）"
                         for o in sim.operators if not o.alive and o.death_time)
        head_note = (f"收场余量：生还最低 {head * 100:.0f}%"
                     f"（{thinnest.name} {thinnest.hp:,.0f}/{thinnest.max_hp:,.0f}）"
                     if thinnest else "收场余量：无人阵亡且全满")
        if dead:
            head_note += f"；阵亡 {dead}"
        # 敌速敏感性：0.85–1.5 全胜才算"稳"。校准误差是 1.4%（1-7 实机对齐），
        # 所以这个区间远宽于误差。**这一列也在 knock 读法下跑**，与主结果同规则。
        # 三组扫描点**一次投出去并行跑**。它们与主结果共用同一个 `run_plan`
        # 和同一套开关，并行只改"在哪个进程里跑"，不改算法，所以逐点结果与
        # 串行完全一致（下面 check_search 的对照断言钉住这一点）。
        # 合并投递还有个理由：单独一组都跨不过并行的最小批量门槛
        # （剑速 10 / 敌速 7 / 形态 3 个点），合成 20 个点才值得开池。
        swept = {(k, v): (won, leaks, kills) for k, v, won, leaks, kills in
                 pmap(_sweep_one,
                      [("speed", s, plan) for s in SPEED_SCALES]
                      + [("qi", v, plan) for v in QI_SPEEDS]
                      + [("mode", m, plan) for m, _ in BOSS_MODES],
                      init=_sweep_init, key="srx8-sweep")}
        band = [f"×{s:g}:{'胜' if swept[('speed', s)][0] else '败'}"
                f"漏{swept[('speed', s)][1]}" for s in SPEED_SCALES]
        band_note = "敌速鲁棒性（knock 读法）" + " ".join(band)
        # 剑气速度不在 gamedata 里（原文只写"向前/遇障碍右转/技能结束消失"）。
        # 2026-09-16 由录像实测为 1.2 格/秒（见 BattleSimulator.sword_qi_speed），
        # 旧默认值 4.0 是估的。敏感性必须逐点跑：1.2 附近会漏 1 只，而 4.0 不漏——
        # 不扫就看不见这个边界。
        qi = [f"{v:g}:{'胜' if swept[('qi', v)][0] else '败'}漏{swept[('qi', v)][1]}"
              for v in QI_SPEEDS]
        qi_note = "剑气速度敏感性（格/秒，实测 1.2）" + " ".join(qi)
        # 形态假设扫描：三种读法都跑一遍，把结论摊开——这比挑一个读法报"胜"诚实。
        # 注意 `knock` 现在的实现是**每倒地一次就换**（博士实机确认），
        # 标签里不再写"每倒地 2 次"——那是我早先从 `trigger_cnt` 反推错的读法。
        modes = [f"{label}:{'胜' if swept[('mode', m)][0] else '败'}"
                 f"{swept[('mode', m)][2]}杀{swept[('mode', m)][1]}漏"
                 for m, label in BOSS_MODES]
        mode_note = "BOSS 换相性读法 " + "  ".join(modes)
        print(f"    {mode_note}")
        print(f"    {qi_note}")
        print(f"【{idx} {title}】")
        for w in warns:
            print(f"    {w}")
        print(f"    模拟预测：{'胜利' if r.won else '失败'}  {r.elapsed:.1f}s  "
              f"击杀 {r.kills}  漏怪 {r.leaks}  剩余生命 {r.life}  "
              f"总伤害 {r.damage_dealt:,.0f}  BOSS 倒地 {knocks} 次  "
              f"装置触发 {trig} 次  {head_note}")
        print(f"    {band_note}")
        healed = "  ".join(f"{o.name}治{o.healing_done:,.0f}"
                           for o in sim.operators if o.healing_done)
        if healed:
            print(f"    治疗量：{healed}")
        print("    部署序列（费用够就下，MAA 同规则）：")
        t = 0.0
        for wait, name, pos, d, slot, mastery, cost in detail:
            t += wait
            r0 = roster.get(name)
            print(f"      {t:6.1f}s  {name:<12} 项目{pos}（= MAA location，同口径）"
                  f"朝{d}  技能{slot or '—'}(专{mastery})  费用{cost}  "
                  f"E{r0['elite']}{r0['level']} 潜{r0['potential']} 信赖{r0['trust']:.0f}%")
        if trig == 0:
            print(f"    装置一次都没触发（卡在：{blocker}）")
        print()

        roster_note = "；".join(
            f"{n} E{roster.get(n)['elite']}{roster.get(n)['level']}"
            f"专{roster.mastery(n, s) if s else '-'}"
            + (f"模组{(roster.get(n).get('equipped_module') or '无')}"
               f"→MAA module={roster_module_slot(roster, n)}"
               if roster_module_slot(roster, n) else "不需要模组")
            for n, _p, _d, s in plan)
        details = (
            f"由 ak-tactic 模拟器导出（干员口径取自森空岛名册，含真实专精/模组/信赖），"
            f"与本地模拟逐条同源。\n"
            f"模拟预测：{'胜利' if r.won else '失败'}，{r.elapsed:.1f}s，"
            f"击杀 {r.kills}，漏怪 {r.leaks}，剩余生命 {r.life}，"
            f"总伤害 {r.damage_dealt:,.0f}，BOSS 倒地 {knocks} 次，"
            f"总攻击装置触发 {trig} 次"
            + (f"（卡在：{blocker}）" if trig == 0 else "") + "。\n"
            f"{head_note}。\n"
            f"{band_note}。\n"
            f"{qi_note}。\n"
            f"{mode_note}。\n"
            f"本作业依赖的练度：{roster_note}。"
            f"`requirements.module` 写的是**模组类型编号**（X/Y/Z → 1/2/3，"
            f"不是模组 id 里的序号）；**没有生效模组的干员已整个省略该键**"
            f"（写 0 会让 MAA 不识别整份作业）。`requirements` 整块官方标注"
            f"「保留接口，暂未实现」，所以模组等级请人工确认："
            f"赤刃明霄陈与圣聆初雪各需其专属模组 Lv3。\n"
            f"**这一版为什么会赢**：BOSS「死志的凝结」每倒地一次就翻转一次免疫类型"
            f"（Mode_A 物弱法免 / Mode_B 物免法弱），而相性「免疫」是**该类型伤害全部归零**"
            f"——所以任何单一伤害类型的队伍都会在它的另一半形态里彻底哑火。"
            f"赤刃明霄陈的天赋「形意洞照」把她的攻击变成**弱点伤害**：每次结算按物理与"
            f"法术各算一遍取高者，免疫归零之后自动落在**当前没被免疫**的那一侧，"
            f"于是她在两套形态里都打得动、都攒得动击破值。技3 的剑气（向前、遇障碍右转、"
            f"20 秒）再从侧面反复扫过 y=6 走廊，拐弯时命中状态刷新，同一敌人会被扫到多遍。\n"
            f"**两个未知量**：① 剑气速度原文没写，默认 4 格/秒——上行的扫描是它的敏感度；"
            f"② 敌人的攻击动作长度同样不在数据里（模拟器取 0.5s，0–1s 区间不影响结论）。\n"
            f"已建模的关卡/敌人机制：伤害相性（弱点/免疫/反射）+ 击破与倒地 + 全场总攻击"
            f"装置、BOSS 双形态与其换相性、BOSS 重生（倒下 10s 后满血归来）、"
            f"吓人路灯屏障（+25%最大生命）、挥铳圣像飞行不可阻挡、没办法车漏掉不扣命"
            f"且击倒 +50 费、远程敌人（applyWay=RANGED）边走边打（只在攻击动作期间停一下）、"
            f"敌人按「最后部署」选目标、治疗（医疗干员平A治疗 + 技能 heal_scale + "
            f"天赋增益治疗光环）、技能的【停顿】（不能移动但能开火）与【待机】/【缴械】、"
            f"技能改写的真实伤害、天赋、模组、信赖、专精。"
            f"**伤害类型按干员特性文本判定**（写「法术伤害」即法术，其余物理）；"
            f"**技能持续时间按描述文本判定**：「立即…」类是一次性爆发，「持续时间无限」"
            f"才是永续——过去一律按无限处理，会把圣聆初雪技1 的 430 每秒误算成 2,577 每秒。\n"
            f"未建模：元素损伤、咆哮铳炸膛与吓人路灯屏障引起的弱点失效、召唤物、"
            f"嘲讽等级、凯尔希·思衡托天赋2 的护盾层与【罗德岛】翻倍（护盾没给数值，"
            f"翻倍按不加处理——两处都偏保守）、圣聆初雪技1「可充能2次」的第二层充能、"
            f"结城理天赋2 的 450% 真实伤害。"
        )
        # 组装走包内的 `ak_tactic.maa_export`——那边是 TUI 导出用的同一个实现，
        # 两处各写一份 to_maa 必然漂（本轮就是这么发现 `module` 编号漏了 D 型的）。
        # `stage_name` 用 levelId：官方文档说 code/levelId 皆可，**但 code 不唯一**
        # （774 条 `#f#` 突袭变体与普通版共用同一个 code），所以取唯一的那个。
        job = maa.plan_from_rows(STAGE_ID, plan, detail, title=title)
        data = maa.to_maa(job, roster, stage_name=STAGE_ID, difficulty="NORMAL",
                          title=f"SR-EX-8 {title}", details=details)
        path = OUT_DIR / f"srx8-{chr(64+idx).lower()}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        written.append((path, r.won, r.leaks, trig))
        print()

    print("=== 已写出 ===")
    for p, won, leaks, trig in written:
        print(f"    {p}   {'胜利' if won else '失败'} 漏{leaks} 装置{trig}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
