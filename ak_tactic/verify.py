# -*- coding: utf-8 -*-
"""通用验证器：给定「关卡 + 打法」，判定能不能三星，并说清为什么不能。

README「阶段 5 · 求解与搜索」的第一步就是它——**先做验证器，再做搜索器**。
道理很直白：搜索器要评估成千上万个候选，没有一个可信的评估函数就没有搜索。
在此之前，"这个打法行不行"只能靠人读一份关卡专属脚本的 print 输出。

    python -m ak_tactic verify act54side_06 --plan p.json
    python -m ak_tactic verify act54side_06 --team "圣聆初雪:5,4:Right:3, 德克萨斯:6,3:Right:0"

与搜索器的分工：本模块只回答**判定**（三星与否 + 归因），不做候选生成。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .battle import BattleSimulator, Deployment, RangeProvider
from .battle.talents import squad_cost_bonus
from .battle.traits import (apply_splash_talent, read_combo_attack,
                            read_trait_splash)
from .battle.unit import OperatorUnit
from .gamedata import EnemyLibrary, GameDataSource, RangeTable, load_stage
from .operator import OperatorCalculator, SkillBook, TalentBook
from .operator.attack_speed import attack_speed_bonus
from .plan import Plan, PlanError, Roster

__all__ = ["Verdict", "verify", "stars_of", "Verifier"]


def stars_of(won: bool, leaks: int, challenge: bool = False) -> int:
    """星级判定。**规则由博士 2026-09-18 实机口述确认，不再是一条假设。**

    * 打赢且**一只没漏** → 三星；突袭（`challenge`）再 +1 → 四星
    * 打赢但**漏了怪** → **二星**。漏几只都一样——只要目标生命没扣完就是二星
    * 目标生命扣完 → 整局失败，**零星**

    **没有"一星"这一档。** 旧实现写的是「漏 2 只及以上 1 星」并自注为"一条
    假设"，那是错的：游戏里星级只看"有没有敌人到达目标点"，漏一只与漏五只
    同档。这条错误一度让 1-7 重排后的结论被误判成一星。

    `Verdict` 仍把 `won` / `life` / `max_life` / `leaks` 原样带出来，真要按
    别的口径判，用那几个字段即可。
    """
    if not won:
        return 0
    if int(leaks) > 0:
        return 2
    return 4 if challenge else 3


@dataclass
class Verdict:
    """一次验证的结论。"""

    stars: int
    won: bool
    life: int
    max_life: int
    kills: int
    leaks: int
    elapsed: float
    damage: float
    title: str = ""
    #: 逐人战报：名字 / 时刻 / 坐标 / 朝向 / 练度 / 出手 / 存活
    operators: list[dict[str, Any]] = field(default_factory=list)
    #: 漏怪明细 `(时刻, 敌人名, 扣几点生命)`
    leak_events: list[tuple[float, str, int]] = field(default_factory=list)
    #: 归因：为什么是这个结果
    diagnosis: list[str] = field(default_factory=list)
    #: 装置（全场总攻击之类）的触发情况
    device: dict[str, Any] = field(default_factory=dict)
    result: Any = None

    @property
    def ok(self) -> bool:
        return self.stars == 3

    def rank(self) -> tuple:
        """给搜索排序用的**全序键**（越大越好）。

        搜索的中间状态大多打不赢（人还没下齐），只按星级排会让整层并列。
        所以键里要带上"离赢还差多少"：先星级，再剩余生命，再击杀数，
        再漏怪扣血，最后总伤害。

        用**扣掉的生命**而不是漏怪只数：`life_cost` 可以是 0（没办法车），
        漏 4 只只扣 3 命——按只数排会把这两种情况混为一谈。
        """
        lost = sum(c for _t, _n, c in self.leak_events)
        return (self.stars, self.life, self.kills, -lost, self.damage)

    def line(self) -> str:
        star = "★" * self.stars + "☆" * (3 - self.stars)
        return (f"{star}  {'胜利' if self.won else '失败'}  {self.elapsed:.1f}s  "
                f"击杀 {self.kills}  漏怪 {self.leaks}  "
                f"生命 {self.life}/{self.max_life}  "
                f"总伤害 {self.damage:,.0f}")

    def report(self) -> str:
        """人读的战报（这也是 README 阶段 6 要的「可分享的战报文本」）。"""
        out = [self.title or "打法", self.line(), ""]
        if self.operators:
            out.append("部署与表现：")
            for o in self.operators:
                tail = (f"阵亡于 {o['death_time']:.1f}s"
                        if not o["alive"] else f"存活 {o['hp']:,.0f} HP")
                out.append(f"  {o['time']:6.1f}s  {o['name']:<12} "
                           f"{str(o['position']):<9} 朝{o['direction']:<5} "
                           f"精{o['elite']}{o['level']}级 技能{o['skill']}  "
                           f"出手 {o['hits']} 次  {tail}")
        if self.leak_events:
            out.append("")
            out.append("漏怪：")
            for t, name, cost in self.leak_events:
                out.append(f"  {t:6.1f}s  {name}  −{cost} 生命")
        if self.device:
            out.append("")
            out.append("装置：" + "  ".join(f"{k}={v}" for k, v in self.device.items()))
        if self.diagnosis:
            out.append("")
            out.append("归因：")
            for d in self.diagnosis:
                out.append(f"  · {d}")
        return "\n".join(out)


# ---------------------------------------------------------------- 环境

class Verifier:
    """可复用的验证环境。

    `GameDataSource` / `OperatorCalculator` / `SkillBook` 这些载入一次要几秒，
    搜索器要跑上千次验证，**必须复用**——每次重建会把搜索变成不可用。
    """

    def __init__(self, *, source: GameDataSource | None = None,
                 effect_source: str = "merge", verbose: bool = False,
                 use_range_table: bool = True) -> None:
        self.source = source or GameDataSource()
        self.calc = OperatorCalculator()
        self.skill_book = SkillBook()
        self.talents = TalentBook()
        self.range_table = RangeTable()
        self.effect_source = effect_source
        self.verbose = verbose
        #: 是否给模拟器接**真实攻击范围**（gamedata `range_table.json`）。
        #:
        #: 为 `False` 时模拟器会退回到「自身格 + 朝向前方三格」那个近似
        #: （`sim._range_of` 里明确标为"退化"）。**两者结果不同**：
        #: 1-7 无技能基线在真实范围下是 133.0s，在退化回退下是 137.0s
        #: （`tools/check_battle.py` 的基线锚的就是退化那条路，它防的是
        #: "新代码改坏旧路径"，不是精度）。默认用真实范围。
        self.use_range_table = use_range_table
        self._stages: dict[str, Any] = {}
        self._libs: dict[int, EnemyLibrary] = {}
        #: 单位构造的缓存。搜索器要跑成百上千次验证，同一份练度会被反复
        #: 构造——`calc.stats` 要走等级插值 + 信赖 + 潜能 + 模组，不便宜。
        self._unit_cache: dict[tuple, OperatorUnit] = {}
        #: 落位合法性检查的缓存（关卡 × 职业 × 坐标）。
        self._terrain_ok: dict[tuple, bool] = {}

    # -------------------------------------------------- 关卡与敌人

    def stage(self, stage_id: str):
        if stage_id not in self._stages:
            self._stages[stage_id] = load_stage(stage_id, source=self.source)
        return self._stages[stage_id]

    def library(self, stage):
        key = id(stage)
        if key not in self._libs:
            self._libs[key] = EnemyLibrary(source=self.source)
        return self._libs[key]

    # -------------------------------------------------- 干员

    def range_provider(self, stage) -> RangeProvider:
        calc = self.calc

        def range_id_of(char_id: str, elite: int) -> str:
            phases = calc.character(char_id).get("phases") or []
            e = max(0, min(elite, len(phases) - 1))
            return phases[e].get("rangeId") or "1-1"

        return RangeProvider(self.range_table, range_id_of,
                             block_of=lambda c, e: 1)

    def is_melee(self, char_id: str) -> bool:
        """`position == "MELEE"` 即近战（站地面），否则高台。"""
        return (self.calc._load_chars().get(char_id) or {}).get(
            "position") == "MELEE"

    def unit(self, entry: dict[str, Any]) -> OperatorUnit:
        """练度 → 战斗单位。

        走 `OperatorCalculator`，与 `stats` / `squad.Roster.unit` 同一套语义。
        **三个从文本推出来的字段不能省**（它们不在数值表里）：

        * `attack_type` —— 特性文本写了「法术伤害」才是法术，否则物理。
          这一条整个漏掉过一次：`OperatorUnit` 的默认值是 `PHYSICAL`，
          构造时没人传，于是**名册里每个人都退化成物理**。在 SR-EX-8 上
          后果很重——圣聆初雪是 CASTER 阵法术师，实际打法术，而本关有
          RES 99 的吓人路灯与「法术免疫」的 BOSS 形态，把她当物理算会
          凭空多出成吨输出。
        * `heals` —— 判的是**特性文本**里有没有「恢复友方单位生命」，
          不是职业名：守望者（凯尔希·思衡托）职业也是 MEDIC、特性同样
          以治疗开头，但它另外还会起飞；反过来「咒愈师」这类子职业的平A
          虽带伤害，特性文本照样写着治疗。按职业推两种都会判错。
        * `weakness_damage` —— 赤刃明霄陈天赋「形意洞照」的「弱点伤害」，
          出手时两系都算取更高的一系。它只出现在**天赋**文本里，
          所以与特性文本分开找。
        """
        cid = entry["char_id"]
        key = (cid, entry["elite"], entry["level"],
               int(entry.get("trust") or 0), entry.get("potential", 1),
               entry.get("module") or None,
               int(entry.get("module_level") or 0))
        # 缓存的是**构造参数**，不是造好的单位。
        # 模拟器会原地改写 OperatorUnit（hp / alive / hits / damage_taken），
        # 把同一个对象交给第二局，第二局就是接着上一局的残局打——
        # 症状是搜索器里"多下一个人反而 0 击杀"，因为那个单位的 hp 早就见底了。
        # 贵的部分是 calc.stats（等级插值+信赖+潜能+模组），那个仍然只算一次。
        kw = self._unit_cache.get(key)
        if kw is not None:
            return OperatorUnit(**kw)
        st = self.calc.stats(
            cid, elite=entry["elite"], level=entry["level"],
            trust=int(entry.get("trust") or 0),
            potential=entry.get("potential", 1),
            module=entry.get("module") or None,
            module_level=entry.get("module_level") or 0)
        t = st.total
        c = self.calc.character(cid)
        trait = c.get("description") or ""
        # 特性里的**结构化**黑板（撼地者溅射那种）。`verify` 是把「数据 → 战斗
        # 单位」走完的最后一站，所以特性溅射也在这里落地。天赋那一半要叠上去，
        # 于是这里把该练度的天赋再解一次——与 `run()` 里那次同一口径、同一组
        # 参数，这点开销可以忽略（`_unit_cache` 会把整组构造参数缓存住）。
        splash = apply_splash_talent(
            read_trait_splash(c),
            self.talents.for_operator(cid, elite=entry["elite"],
                                      level=entry["level"],
                                      potential=entry.get("potential", 1)))
        # 「普攻连击 + 结算后缩放」（焰狐龙梓兰的隐藏天赋）。它与特性溅射一样
        # 是从**原始 JSON**读的：`c["talents"]` 里连隐藏天赋一起在，
        # 而库里的 `operator_talent` 只按 `is_hide_talent` 标记、名字是 null，
        # 走库反而要多一次查询。
        combo = read_combo_attack(c)
        tal_text = " ".join(
            (cand.get("description") or "")
            for t_ in (c.get("talents") or [])
            for cand in (t_.get("candidates") or []))
        aspd = attack_speed_bonus(
            self.calc, cid, elite=entry["elite"], level=entry["level"],
            potential=entry.get("potential", 1),
            module=entry.get("module") or None,
            module_level=entry.get("module_level") or 0)
        kw = dict(
            name=st.name, char_id=cid, elite=entry["elite"],
            # 主职业代号（TANK/WARRIOR/…）。按职业发光环的天赋要它——
            # 与 `team_id`（阵营）不是一回事，别混。
            profession=str(c.get("profession") or ""),
            nation_id=str(c.get("nationId") or ""),
            max_hp=float(t["maxHp"]), atk=float(t["atk"]),
            defense=float(t["def"]),
            res=float(t.get("magicResistance", 0) or 0),
            attack_interval=float(t.get("baseAttackTime", 1.0) or 1.0),
            block_cnt=int(t.get("blockCnt", 0) or 0),
            deploy_cost=int(t.get("cost", 0) or 0),
            attack_speed=float(t.get("attackSpeed", 100) or 100) + aspd.flat,
            aspd_when_free=aspd.when_free,
            aspd_high_ground=aspd.when_high_ground,
            attack_type="MAGIC" if "法术伤害" in trait else "PHYSICAL",
            heals="恢复友方单位生命" in trait,
            weakness_damage="弱点伤害" in tal_text,
            # 特性溅射（撼地者）：0 = 没有这条，模拟器整段跳过。
            splash_radius=splash.radius if splash else 0.0,
            splash_scale=splash.scale if splash else 0.0,
            splash_damage_scale=splash.damage_scale if splash else 1.0,
            highland_splash_scale=splash.highland_scale if splash else 0.0,
            highland_splash_sluggish=splash.highland_sluggish if splash else 0.0,
            # 普攻连击（焰狐龙梓兰）：1 = 没有这条。
            combo_hits=combo.hits if combo else 1,
            combo_hit_scale=combo.hit_scale if combo else 1.0,
            combo_damage_scale=combo.damage_scale if combo else 1.0,
        )
        self._unit_cache[key] = kw
        return OperatorUnit(**kw)

    # -------------------------------------------------- 跑一次

    def run(self, plan: Plan, *, roster: Roster | None = None,
            title: str = "", **switches: Any) -> Verdict:
        plan.validate()
        stage = self.stage(plan.stage)
        lib = self.library(stage)
        provider = self.range_provider(stage) if self.use_range_table else None
        roster = roster or Roster.empty()

        sim = BattleSimulator(
            stage, enemy_at=lib.get, range_provider=provider,
            skill_book=self.skill_book, verbose=self.verbose,
            effect_source=self.effect_source, **switches)

        # ---- 先把全队的练度与天赋解出来。天赋要在**排部署时刻之前**知道：
        # 「编入队伍后额外获得初始部署费用」会改变第一个干员的落地时刻。
        squad = []
        for d in plan.deploys:
            entry = self._entry(d, roster)
            tal = self.talents.for_operator(
                entry["char_id"], elite=entry["elite"],
                level=entry["level"], potential=entry.get("potential", 1))
            squad.append((d, entry, tal))

        rate = float(stage.options.cost_increase_time)
        cost = float(stage.options.initial_cost) + sum(
            squad_cost_bonus(t) for *_, t in squad)

        # ---- 排时刻 + 落位合法性守卫
        # 费用模型与 run_sr6 / MAA 自动作战同规则：钱够了就下。给了显式时刻的，
        # 按那一刻结账（费用随经过的时间自然回满再扣）。
        deployed: dict[str, Any] = {}
        #: 费用上做不到的开局。**显式时刻是"请求"**，模拟器照办并把费用夹到 0，
        #: 于是"付不起也落地"会被静默放过。这里如实记下来，交给归因去说。
        cost_notes: list[str] = []
        now = 0.0
        for d, entry, tal in squad:
            op = self.unit(entry)
            pos = (int(d.position[0]), int(d.position[1]))
            self._check_terrain(stage, op, pos, d)
            if d.time is None:
                need = max(0.0, op.deploy_cost - cost)
                at = now + need * rate
                cost = cost + need - op.deploy_cost
            else:
                at = float(d.time)
                if at > now:
                    cost += (at - now) / rate
                if cost < op.deploy_cost:
                    cost_notes.append(
                        f"{d.operator} {at:.1f}s 落地需要 {op.deploy_cost} 费，"
                        f"当时只有 {cost:.0f} 费（初始 "
                        f"{stage.options.initial_cost:g} + 回复 "
                        f"{at / rate:.1f}s）——**这一手在游戏里做不出来**")
                cost = max(0.0, cost - op.deploy_cost)
            now = at
            sim.plan(Deployment(at, op, pos, d.direction, skill=d.skill,
                                skill_mastery=d.mastery,
                                auto_skill=d.auto_skill, talents=tal))
            deployed[d.operator] = (at, pos, d, entry)

        # 撤退与手动开技能都**按坐标**排（模拟器的接口就是坐标）——
        # 所以要先按下标把人映射回自己的落点。
        for r in plan.retreats:
            _at, pos, _d, _e = deployed[r.operator]
            sim.retreat(pos, r.time)
        for s in plan.skills:
            _at, pos, _d, _e = deployed[s.operator]
            # 只是**请求**：技力不够就等够了再开，判定在 _skill_tick 里。
            sim.use_skill(pos, s.time)

        res = sim.run(max_time=900.0)
        v = self._verdict(plan, stage, sim, res, deployed, title=title)
        if cost_notes:
            v.diagnosis.extend(cost_notes)
        return v

    # -------------------------------------------------- 内部

    def _entry(self, d, roster: Roster) -> dict[str, Any]:
        """练度来源：打法里写了就用它，否则查名册。两边都没有就报错。"""
        base = roster.get(d.operator)
        if base is None and (d.elite is None or d.level is None):
            raise PlanError(
                f"「{d.operator}」的练度没着落：打法里没写 elite/level，"
                f"名册里也没有这个人。要么在打法里写全，要么用 --box 指一份名册")
        entry = dict(base or {})
        for k in ("elite", "level", "potential", "trust", "module",
                  "module_level"):
            v = getattr(d, k, None)
            if v is not None:
                entry[k] = v
        entry.setdefault("elite", 0)
        entry.setdefault("level", 1)
        entry.setdefault("potential", 1)
        if not entry.get("char_id"):
            cid = self._by_name(d.operator)
            if cid is None:
                raise PlanError(f"干员「{d.operator}」在数据里找不到")
            entry["char_id"] = cid
        return entry

    def _by_name(self, name: str) -> str | None:
        chars = self.calc._load_chars()
        for cid, c in chars.items():
            if c.get("name") == name and c.get("profession") not in (
                    "TRAP", "TOKEN"):
                return cid
        return None

    def _check_terrain(self, stage, op, pos, d) -> None:
        """职业与地形必须相容。

        **模拟器不校验地形合法性**：落错了不会报错，只会安静地跑出一个
        "看起来对"的结果。2026-09-16 真踩过——把 MAA 字面量误翻一次，
        术师落到 `tile_end`、先锋落到 `tile_wall`，照样跑出「21 杀 0 漏」，
        只有耗时从 196.6s 变成 203.6s 露了马脚。
        """
        melee = self.is_melee(op.char_id)
        spots = stage.map.melee_spots if melee else stage.map.ranged_spots
        if pos not in spots:
            tile = stage.map.tile(*pos).key
            raise PlanError(
                f"落点非法：{d.operator} 落在 {pos}（{tile}），"
                f"但它需要{'地面' if melee else '高台'}可部署格。"
                f"坐标是 MAA 口径（原点左上、y 向下），不要再翻一次。")

    def _verdict(self, plan, stage, sim, res, deployed, *, title="") -> Verdict:
        max_life = int(getattr(stage.options, "max_life_point", 1) or 1)
        by_name = {o.name: o for o in sim.operators}
        ops = []
        for name, (at, pos, d, entry) in deployed.items():
            o = by_name.get(name)
            if o is None:
                continue
            ops.append({
                "name": name, "time": at, "position": pos,
                "direction": d.direction, "skill": d.skill,
                "elite": entry["elite"], "level": entry["level"],
                "hits": o.hits, "alive": o.alive, "hp": o.hp,
                "death_time": float(getattr(o, "death_time", 0.0) or 0.0),
                "damage_taken": float(getattr(o, "damage_taken", 0.0) or 0.0),
            })
        ops.sort(key=lambda x: x["time"])

        # 装置（全场总攻击）的触发情况。**它常常是这关输出的主要来源**，
        # 「触发 0 次」与「触发 15 次」是两个完全不同的世界。
        device: dict[str, Any] = {}
        ta = getattr(sim, "total_attack", None)
        if ta is not None and hasattr(ta, "to_dict"):
            raw = ta.to_dict()
            device = {"触发次数": raw.get("triggers"),
                      "装置总伤害": f"{raw.get('total_damage', 0):,.0f}"}
            if raw.get("last_blocker"):
                device["卡在"] = raw["last_blocker"]

        v = Verdict(
            stars=stars_of(res.won, res.leaks,
                           challenge=bool(getattr(stage.options,
                                                  "is_hard_training", False))),
            won=res.won, life=res.life,
            max_life=max_life, kills=res.kills, leaks=res.leaks,
            elapsed=res.elapsed, damage=res.damage_dealt,
            title=title or plan.title, operators=ops,
            leak_events=list(getattr(res, "leak_events", []) or []),
            device=device, result=res)
        v.diagnosis = self._diagnose(v, sim, res, max_life)
        return v

    def _diagnose(self, v: Verdict, sim, res, max_life: int) -> list[str]:
        out: list[str] = []
        if v.won and v.leaks == 0:
            out.append("三星：没有敌人到达目标点。")
        if not v.won:
            # **跑满上限 ≠ 生命归零**。原先这里只有一句话，于是"生命还剩 3 点、
            # 一只都没漏"的局也会被说成「生命归零（初始 3 点，共漏 0 只、扣了
            # 0 点）」——自相矛盾。两种收场要分开说，而且要说清场上剩的是什么。
            if getattr(res, "timed_out", False):
                left = getattr(res, "leftover_units", []) or []
                names: dict[str, int] = {}
                for n, _id, is_prop in left:
                    key = f"{n}（装置召唤）" if is_prop else n
                    names[key] = names.get(key, 0) + 1
                who = ("、".join(f"{n}×{c}" for n, c in names.items())
                       if names else "（没有留下任何东西）")
                placed = int(getattr(res, "spawns_placed", 0) or 0)
                total = int(getattr(res, "spawns_total", 0) or 0)
                if placed < total:
                    out.append(
                        f"跑满时间上限（{v.elapsed:.0f}s）：这一波**还没放完**"
                        f"（出怪表 {placed}/{total} 条），场上还剩 {who}。")
                else:
                    out.append(
                        f"跑满时间上限（{v.elapsed:.0f}s）：出怪表已经放完，"
                        f"但场上还留着 {who}——「既打不死又不会离场」的单位"
                        f"不挡结算（见 `BattleSimulator._cannot_clear`），"
                        f"所以是别的东西让它收不了场。")
            else:
                out.append(f"失败：生命归零（初始 {max_life} 点，"
                           f"共漏 {v.leaks} 只、扣了 "
                           f"{sum(c for _t, _n, c in v.leak_events)} 点）。")
        elif v.leaks:
            out.append(f"通关但只有 {v.stars} 星：漏了 {v.leaks} 只。")
        if v.leak_events:
            first = min(t for t, _n, _c in v.leak_events)
            last = max(t for t, _n, _c in v.leak_events)
            names: dict[str, int] = {}
            for _t, n, _c in v.leak_events:
                names[n] = names.get(n, 0) + 1
            top = "、".join(f"{n}×{c}" for n, c in
                            sorted(names.items(), key=lambda kv: -kv[1])[:5])
            out.append(f"漏怪时段 {first:.1f}s–{last:.1f}s，主要是 {top}。")
        dead = [o for o in v.operators if not o["alive"]]
        if dead:
            out.append("阵亡：" + "、".join(
                f"{o['name']}（{o['death_time']:.1f}s，承受 "
                f"{o['damage_taken']:,.0f}）" for o in dead))
        if v.device:
            if not v.device.get("触发次数"):
                out.append("全场总攻击装置一次都没触发——这关的输出大半来自它，"
                           "先看是不是有敌人永远不倒地（相性免疫或阈值太高）。")
            elif v.device.get("卡在"):
                out.append(f"装置被 {v.device['卡在']} 卡住过（它不满足倒地条件）。")
        if v.won and v.leaks == 0 and not dead:
            out.append("无人阵亡，可以再压练度试更省的方案。")
        return out


def verify(plan: Plan, *, roster: Roster | None = None,
           verifier: Verifier | None = None, **switches: Any) -> Verdict:
    """跑一次验证。没有可复用的 `Verifier` 时会现建一个（慢，仅适合单次）。"""
    v = verifier or Verifier()
    return v.run(plan, roster=roster, **switches)
