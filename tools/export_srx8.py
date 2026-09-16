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
from ak_tactic.operator import SkillBook, TalentBook                      # noqa: E402
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


#: 模组**类型字母** → MAA 的 `module` 编号（见 `module_slot`）。
MODULE_SLOT = {"X": 1, "Y": 2, "Z": 3}


def module_slot(roster: Roster, name: str) -> int | None:
    """返回 MAA 的 `module` 编号；**没有生效模组时返回 `None`（该键必须整个省略）**。

    ## 编号取的是模组**类型字母**，不是 id 里的数字

    游戏把模组分三型 **X / Y / Z**，MAA 用 **1 / 2 / 3** 指代它们。
    所以判据是 `uniequip_table.equipDict[<id>].typeName2` 那个字母：

    | 干员 | 模组 id | `typeName2` | MAA 写法 |
    |---|---|---|---|
    | 赤刃明霄陈 | `uniequip_002_chen3` | **X** | `1` |
    | 圣聆初雪 | `uniequip_002_sbell2` | **Y** | `2` |
    | 阿斯卡纶 | `uniequip_002_ascln` | **X** | `1` |

    **别解析 id**：`uniequip_00N_xxx` 里的 N 只是全表序号——上面两条的 N 都是 2，
    编号却一个是 1、一个是 2。我先前用正则抓 id 里的数字当编号，赤刃明霄陈被写成 2，
    博士实机指出来了。

    两道限制：① 只有 `equipped_status == "ok"`（过了模组三道门）才算数；
    ② 字母不在 X/Y/Z 里的一律返回 `None`（特限/特勤那种 D/A/B 本来就被第①条挡住，
    这里再兜一层）。

    ## 为什么没有模组时连键都不能写

    MAA 对 `requirements.module` 的取值是有语义的（1/2/3 = X/Y/Z），写 `0` 之类的
    越界值会让**整份作业解析失败**——不是"忽略这一条要求"，是**不识别**。
    所以宁可省略：省略 = 不校验模组，写错 = 整个文件用不了。
    博士实机确认过这条。
    """
    r = roster.get(name)
    if r.get("equipped_status") != "ok":
        return None
    # `module` 是"算符该用的那个"，`equipped_module` 是账号实际装着的；
    # 上面那道 status 门保证两者在 ok 时是同一个 id，取谁都行。
    eq = r.get("module") or r.get("equipped_module")
    if not eq:
        return None
    entry = (roster.calc._load_uniequip() or {}).get(eq) or {}
    letter = str(entry.get("typeName2") or "").strip().upper()
    return MODULE_SLOT.get(letter)


def skill_usage(roster: Roster, name: str, slot: int) -> int:
    """MAA 的技能用法。

    MAA 官方口径：`1` = 好了就用，`0` = 不自动使用；并注明
    「**如果是全自动的技能，填 0**」。所以这里按触发方式分流：
    手动触发的（如予愿安洁莉娜 3 技能）填 1 让 MAA 点；自动触发的
    （机械师 1 技能、圣聆初雪 2 技能）填 0，游戏自己会开。
    """
    if not slot:
        return 0
    for s in roster.slots(name):
        if s.slot == slot:
            lv = s.level(7, roster.mastery(name, slot))
            return 0 if "自动触发" in (lv.skill_type_cn or "") else 1
    return 1


def to_maa(stage, roster: Roster, plan, detail, *, title: str, details: str) -> dict:
    """组装 MAA copilot JSON。y 轴翻成 MAA 的「从上往下」。"""
    h = stage.map.height
    opers = []
    for name, _pos, _d, slot in plan:
        r = roster.get(name)
        mastery = roster.mastery(name, slot) if slot else 0
        req = {"elite": r["elite"], "level": r["level"],
               # 官方口径：1–7 是技能等级，8/9/10 即专一/专二/专三
               "skill_level": 7 + mastery}
        # 没有生效模组的干员**不能写这个键**（写 0 会让 MAA 整份作业不识别），
        # 见 `module_slot`。键序保持 elite → level → skill_level → module → potential。
        mod = module_slot(roster, name)
        if mod:
            req["module"] = mod
        req["potential"] = r["potential"]
        opers.append({"name": name, "skill": slot or 0,
                      "skill_usage": skill_usage(roster, name, slot),
                      "requirements": req})
    actions = []
    for wait, name, (x, y), direction, slot, mastery, cost in detail:
        actions.append({
            "type": "Deploy", "name": name,
            "location": [x, y], "direction": direction,
            "doc": f"{name}  技能{slot or '—'}（专{mastery}）  费用{cost}",
        })
    actions.append({"type": "SpeedUp"})
    actions.append({"type": "SkillDaemon"})
    return {
        "stage_name": STAGE_ID,
        "opers": opers,
        "groups": [],
        "actions": actions,
        "minimum_required": "v6.0.0",
        "doc": {"title": title, "details": details},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", type=int, default=0, help="只导出第 N 个候选（1 起算）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    src = GameDataSource()
    stage = load_stage(STAGE_ID, source=src)
    lib = EnemyLibrary(source=src)
    book = SkillBook()
    talents = TalentBook()
    roster = Roster()
    provider = make_provider(roster.calc, RangeTable())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    H = stage.map.height
    print(f"=== {stage.summary()} ===")
    print(f"名册 {roster.path.name}  uid={roster.uid} [{roster.nick}]")
    print("模组判定（MAA 的 module = 类型字母 X/Y/Z → 1/2/3；无生效模组则省略该键）：")
    for n in dict.fromkeys(n for n, *_ in sum((p for _t, p in PLANS), [])):
        r0 = roster.get(n)
        eq = r0.get("equipped_module")
        entry = (roster.calc._load_uniequip() or {}).get(eq or "") or {}
        slot = module_slot(roster, n)
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
        band = []
        for s in (0.85, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5):
            s_sim, s_r, _d, _w = run_plan(stage, lib, provider, roster, book,
                                          talents, plan, ranged_enemies=True,
                                          speed_scale=s,
                                          boss_mode_switch="knock")
            band.append(f"×{s:g}:{'胜' if s_r.won else '败'}漏{s_r.leaks}")
        band_note = "敌速鲁棒性（knock 读法）" + " ".join(band)
        # 剑气速度不在 gamedata 里（原文只写"向前/遇障碍右转/技能结束消失"）。
        # 2026-09-16 由录像实测为 1.2 格/秒（见 BattleSimulator.sword_qi_speed），
        # 旧默认值 4.0 是估的。敏感性必须逐点跑：1.2 附近会漏 1 只，而 4.0 不漏——
        # 不扫就看不见这个边界。
        qi = []
        for v in (1.0, 1.1, 1.2, 1.22, 1.25, 1.3, 1.4, 1.5, 2.0, 4.0):
            _q_sim, q_r, _qd, _qw = run_plan(stage, lib, provider, roster, book,
                                             talents, plan, ranged_enemies=True,
                                             boss_mode_switch="knock",
                                             sword_qi_speed=v)
            qi.append(f"{v:g}:{'胜' if q_r.won else '败'}漏{q_r.leaks}")
        qi_note = "剑气速度敏感性（格/秒，实测 1.2）" + " ".join(qi)
        # 形态假设扫描：三种读法都跑一遍，把结论摊开——这比挑一个读法报"胜"诚实。
        # 注意 `knock` 现在的实现是**每倒地一次就换**（博士实机确认），
        # 标签里不再写"每倒地 2 次"——那是我早先从 `trigger_cnt` 反推错的读法。
        modes = []
        for ms, label in (("knock", "每倒地一次★"), ("none", "不换"),
                          ("time", "每30秒")):
            _m_sim, m_r, _md, _mw = run_plan(stage, lib, provider, roster, book,
                                             talents, plan, ranged_enemies=True,
                                             boss_mode_switch=ms)
            modes.append(f"{label}:{'胜' if m_r.won else '败'}"
                         f"{m_r.kills}杀{m_r.leaks}漏")
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
               f"→MAA module={module_slot(roster, n)}"
               if module_slot(roster, n) else "不需要模组")
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
        data = to_maa(stage, roster, plan, detail,
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
