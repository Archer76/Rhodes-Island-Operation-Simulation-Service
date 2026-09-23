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
#: ⚠ **排程的载体**，住 `frontend/`（不依赖 `battle/`）。本轮起 `run()` 把排程
#: **同时**写进它和模拟器：迁移期两边都对得上（`Schedule.diff` 可核），
#: 切过去之后只留它。见 `frontend/schedule.py` 的模块文档串。
from .frontend.schedule import Schedule
from .frontend.operator_view import operator_view
from .frontend.stage_env import FPS as _FPS, stage_env
from .battle.talents import find_glider_mobility, find_power_attack, squad_cost_bonus
from .battle.traits import (apply_splash_talent, read_combo_attack,
                            read_hp_drain, read_trait_splash)
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
    #: ★ **第三态：具名拒跑**（没跑，不是打输）。非空即拒跑，内容是理由。
    #: `unsupported` 非空时由 `simgo/verifier.py::_refusal_verdict` 填。
    #: ⚠ **读判决的人要先看这一栏**：拒跑时数值栏全是 0，把它当「0 杀 N 漏」
    #: 就会去查一场根本没打的仗。
    refused: list[str] = field(default_factory=list)
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
                 use_range_table: bool = True, engine: str = "go") -> None:
        #: 用哪一份模拟器跑战斗。
        #:
        #: ⚠ **默认已改成 `"go"`**（博士 2026-09-19 裁定：怀黍离全部关卡对拍通过
        #: 之后把默认模拟器切到 Go 版，Python 那份退为对拍基准、不再作为运行时引擎）。
        #: 裁定原文与门槛见 `docs/` 与进度文件的对应小节；切换前的判据是
        #: `tools/parity_plan.py` 17 份计划四项全归零 ＋ `tools/check_mech_parity.py`
        #: 三判据（一致 + 反证 + 落位咬到机制）无失败。
        #:
        #: * `"go"` —— `rios-sim` 那一份，接入点在 `ak_tactic/simgo/verifier.py`。
        #:   规格不支持时会**当场退回 Python** 并在判决的 `diagnosis` 里写清楚，
        #:   绝不静默换（这条不因默认值改变而改变）。
        #: * `"python"` —— `battle/sim.py`，**权威实现**。它现在只该被两类调用点
        #:   显式点名：① 对拍基准（`tools/parity_plan.py::PyCapture`）；
        #:   ② `check_battle.py` 那套自检（期望值是照 Python 写死的）。
        #:   ⚠ 仓里凡是"必须拿到 Python 结果"的地方，都要**显式**传 `engine="python"`：
        #:   默认值一改，裸 `Verifier()` 就全变成 Go 了，而那是**静默**的语义变化。
        self.engine = engine
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

    def _unit_key(self, entry: dict[str, Any]) -> tuple:
        """一次练度的缓存键——`_unit_cache` 与 `unit_kw` 共用这一份算法。

        ⚠ 抽出来是因为它**必须只有一处**：两处各写一遍，将来改了口径
        （比如多一个字段进键）就会出现"缓存命中不了"或者更糟——
        "两个不同的练度命中同一条"。
        """
        return (entry["char_id"], entry["elite"], entry["level"],
                int(entry.get("trust") or 0), entry.get("potential", 1),
                entry.get("module") or None,
                int(entry.get("module_level") or 0))

    def unit_kw(self, entry: dict[str, Any]) -> dict[str, Any]:
        """一次练度的**构造参数**（不是造好的单位）。

        规格层要的是这一份（`frontend/operator_view.py` 拿它做视图），
        而 `unit()` 要的是活的对象——两者同源，所以缓存的是 `kw` 本身。
        """
        key = self._unit_key(entry)
        if key not in self._unit_cache:
            self.unit(entry)          # 走一遍原路，顺带把 kw 存进缓存
        return self._unit_cache[key]

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
        key = self._unit_key(entry)
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
        # 天赋「强击瓶专家」（焰狐龙梓兰）：部署后首次开技起，接下来 50 次
        # **攻击**的攻击力倍率。取数与判据在 `battle/talents.find_power_attack`。
        pow_atk = find_power_attack(
            self.talents.for_operator(cid, elite=entry["elite"],
                                      level=entry["level"],
                                      potential=entry.get("potential", 1)))
        # 天赋「翔虫机动」（焰狐龙梓兰 天赋2）：限时攻击力加成 + 落位放宽 +
        # 离场不累加再部署惩罚。取数与键的归属见 `battle/talents.GliderMobility`。
        glider = find_glider_mobility(
            self.talents.for_operator(cid, elite=entry["elite"],
                                      level=entry["level"],
                                      potential=entry.get("potential", 1)))
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
            # 怪杰特性「自身生命会不断流失」：每秒流失生命上限的这个比例。
            # 0 = 没有这条特性，模拟器整段跳过。判据见 `traits.read_hp_drain`。
            hp_drain_per_sec=read_hp_drain(c),
            # 普攻连击（焰狐龙梓兰）：1 = 没有这条。
            combo_hits=combo.hits if combo else 1,
            combo_hit_scale=combo.hit_scale if combo else 1.0,
            combo_damage_scale=combo.damage_scale if combo else 1.0,
            # 天赋「强击瓶专家」：0 = 没有这条。
            power_attack_count=pow_atk.count if pow_atk else 0,
            power_attack_scale=pow_atk.scale if pow_atk else 1.0,
            # 天赋「翔虫机动」：没有就全 0 / 空，行为上等价于"没这天赋"。
            mobility_atk_bonus=glider.atk_bonus if glider else 0.0,
            mobility_atk_duration=glider.atk_duration if glider else 0.0,
            mobility_melee_deploy=glider.ignore_build_type if glider else False,
            mobility_deploy_range=glider.deploy_range if glider else "",
            mobility_leftover=glider.projectile if glider else "",
            no_respawn_cost_add=glider.no_respawn_cost_add if glider else False,
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
        #: ⚠ **换引擎那一侧要这份名册**（Go 自造规格要按名册折算练度）。
        #: 为什么不走形参：`_run_other_engine` 是个**被覆写的钩子**
        #: （`tools/golden_go.py::SpecCapture` 覆写了它，只转发固定的几个参数），
        #: 给它加关键字会要求每个覆写点都跟着改——那是「一处口径多处维护」。
        #: 存在实例上，两条路（裸 Verifier 与 GoVerifier）都读得到同一份。
        self._roster_in_use = roster

        #: **难度轴接线**（2026-09-20）：调用方没显式给 `environment_difficulty`
        #: 时，用**关卡自己**那一档（索引里 `#f#` 记的是 `FOUR_STAR`）。
        #:
        #: 不接这条的后果不是报错，而是四星档**安静地按普通档跑**：`runes` 里
        #: `global_lifepoint` / `enemy_attribute_mul` / `env_system_new(FOUR_STAR)`
        #: 一条都不生效，读数与普通档**逐位相同**（实测 `ex01` 与 `s01` 两例，
        #: `spec_sha` 逐位相等）。取证：`docs/hsl-backfill-attribution.md` §四.3。
        #:
        #: 只在**没给**时兜底：显式给了（含 `""` 之外的非空值）一律以调用方为准，
        #: 既有读数因此零变化（判据 `tools/hsl_backfill_probe.py --zero-change`）。
        if not switches.get("environment_difficulty"):
            switches["environment_difficulty"] = (
                str(getattr(stage, "difficulty", "") or "NORMAL"))

        sim = BattleSimulator(
            stage, enemy_at=lib.get, range_provider=provider,
            # 敌人**种类**（PRTS 的「种类」列，住在 enemydb 的 `enemy.category`）。
            # 按种类判的机制（泥岩天赋「手足相惜」：受到来自【萨卡兹】敌人的伤害
            # 降低 30%）靠它。库里没有这个敌人的种类时返回空串 ⇒ 机制不生效——
            # 宁可不动，不许把敌人一概当成萨卡兹。
            species_provider=lib.species_of,
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

        #: ⚠ **排程同时写两份**：`sched`（新家、不依赖 `battle/`）与 `sim`
        #: （原版、迁移期仍是基线）。两边方法名与参数**逐字相同**，所以只是多一行；
        #: 一致性可用 `sched.diff(sim)` 核。等 `battle/` 删掉时，把 `sim.*` 那几行
        #: 去掉、把 `sched` 递下去就完事——不用再想排程该放哪。
        sched = Schedule()

        #: ⚠ **关卡静态那 8 项**（`fps` / `speed_scale` / `ranged_enemies` /
        #: `enemy_windup` / `cost_init` / `cost_max` / `cost_time` / `life`）
        #: 在这里、从**原始构造参数**算出来交给换引擎那一侧。
        #:
        #: 为什么要在这儿算：参数**只有本函数手上有**（它们是 `**switches`）。
        #: `build_spec` 之前是回头去问模拟器要 `sim.speed_scale` 这类值——那是
        #: **派生后**的结果（已经乘过关卡的 `move_multiplier`、夹过零），
        #: 反推不回原始参数；靠猜默认值则会在非默认关卡上悄悄分叉。
        #:
        #: 口径与 `BattleSimulator.__init__`（`sim.py:418-440`）逐字一致——
        #: `stage_env` 就是照那几行搬的。不传 switches 的常见路径得到同一个值。
        env = stage_env(
            stage,
            environment_difficulty=str(
                switches.get("environment_difficulty", "NORMAL") or "NORMAL"),
            fps=switches.get("fps", _FPS),
            speed_scale=switches.get("speed_scale", 1.0),
            ranged_enemies=switches.get("ranged_enemies", True),
            enemy_windup=switches.get("enemy_windup", 0.5))
        #: ⚠ 难度**不是** `ENV_KEYS` 那 8 项之一（那 8 项是要送进规格的字段），
        #: 但下游 `SpecInputs.from_sim` 还要用它去算田地参数
        #: （`frontend/inputs.py:222` 的 `PolluteParams.from_stage`）——
        #: 那里不能只靠 `env` 的 8 个键，所以在这里把它捎上。
        #: 少这一行，“敌人属性倍率/生命点/费用”会跟着难度走，而**田地参数不会**：
        #: 半接线的样子与全没接线在判决上分不开（`act31side_ex08` 的初始污染点
        #: 正常档 `1,1:0`、四星档 `4,4:100`）。
        env["environment_difficulty"] = switches["environment_difficulty"]

        # ---- 排时刻 + 落位合法性守卫
        # 费用模型与 run_sr6 / MAA 自动作战同规则：钱够了就下。给了显式时刻的，
        # 按那一刻结账（费用随经过的时间自然回满再扣）。
        deployed: dict[str, Any] = {}
        #: 费用上做不到的开局。**显式时刻是"请求"**，模拟器照办并把费用夹到 0，
        #: 于是"付不起也落地"会被静默放过。这里如实记下来，交给归因去说。
        cost_notes: list[str] = []
        now = 0.0
        #: 每位干员上一次落点——天赋「翔虫机动」（焰狐龙梓兰）要用它：非首次部署
        #: 时，"上次部署位置周围"（离场留下的静止弹道范围 `x-1`）里的**近战位**
        #: 也合法。这里按 `char_id` 记，与模拟器 `_mobility_spot` 同一口径。
        prev_spot: dict[str, tuple[int, int]] = {}
        for d, entry, tal in squad:
            op = self.unit(entry)
            pos = (int(d.position[0]), int(d.position[1]))
            self._check_terrain(stage, op, pos, d,
                                previous=prev_spot.get(op.char_id))
            prev_spot[op.char_id] = pos
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
            #: ⚠ 一个 `Deployment` **对象**交给两边——不是各造一个内容相同的。
            #: 两边拿到同一批对象，`sched.diff(sim)` 比出来的才是**排程**的差，
            #: 而不是"两次构造是否一致"。
            dep = Deployment(at, op, pos, d.direction, skill=d.skill,
                             skill_mastery=d.mastery,
                             auto_skill=d.auto_skill, talents=tal,
                             #: ⚠ 给规格层备一份**视图**（`frontend/operator_view.py`）：
                             #: `op` 是活的 `OperatorUnit`，跑起来会被就地改写
                             #: （`hp` / `alive` / `hits` / `damage_taken`…），
                             #: 而 `build_spec` 要的是**开局那一组字段**。
                             #: 视图每次部署新造一个（很便宜），所以它不会被跑帧碰到。
                             operator_view=operator_view(self.unit_kw(entry)))
            sched.plan(dep)
            sim.plan(dep)
            deployed[d.operator] = (at, pos, d, entry)

        # 撤退与手动开技能都**按坐标**排（模拟器的接口就是坐标）——
        # 所以要先按下标把人映射回自己的落点。
        for r in plan.retreats:
            _at, pos, _d, _e = deployed[r.operator]
            sched.retreat(pos, r.time)
            sim.retreat(pos, r.time)
        for s in plan.skills:
            _at, pos, _d, _e = deployed[s.operator]
            # 只是**请求**：技力不够就等够了再开，判定在 _skill_tick 里。
            sched.use_skill(pos, s.time)
            sim.use_skill(pos, s.time)

        if self.engine != "python":
            #: 换了引擎（Go 那一份，见 `ak_tactic/simgo/verifier.py`）。
            #: 这里**只留一个挂载点**：怎么跑完一场战斗、怎么把结果变成判决，
            #: 全归 `simgo` 那一层——本文件不该知道 Go 的存在。
            v = self._run_other_engine(sim=sim, plan=plan, stage=stage,
                                      deployed=deployed, title=title,
                                      schedule=sched, env=env)
            if cost_notes:
                v.diagnosis.extend(cost_notes)
            return v

        res = sim.run(max_time=900.0)
        v = self._verdict(plan, stage, sim, res, deployed, title=title)
        if cost_notes:
            v.diagnosis.extend(cost_notes)
        return v

    @property
    def go_fallbacks(self) -> int:
        """**旧名字**（已废，保留只为不改动调用方）：同 `go_refusals`。

        ⚠ 读的人比看上去多，**改名前先看这里**（2026-09-23 实测，`grep go_fallbacks`，
        **用裸模式数**——用 `go_fallbacks|go_refusals` 这种交替模式数，实测会漏掉
        `tools/acceptance.py` 那一整份的 17 处）：

        * 读属性：`tools/acceptance.py:411`、`tools/golden_go.py:138`、
          `tools/bisect_deepwater.py:157`、`tools/engine_identity_probe.py:95`、
          `tools/probe_engine_closeout_dual.py:241`、`tools/parity_ledger.py:223`——
          前五个走 `getattr(v, "go_fallbacks", None)`，**改名会让它们静默读成 `None`**
          （`acceptance.py:420` 那句 `or row["go_fallbacks"]` 于是恒假，闸门永远通过）；
          `tools/probe_gate_snow.py:59,87` 是直接属性访问，改名会当场 `AttributeError`。
        * 写成键：`tools/golden_go.py:138` 把它写进 `fixtures/golden_go.json`，
          **24 条记录**都带这个键 ⇒ 改名要连夹具一起重生成。

        所以改名是**一件要整批做的事**（改名字 + 上面 8 处 + 重生成夹具）。
        本轮只把**规范名**改成 `go_refusals`（语义写在 `simgo/verifier.py` 那头的
        `__init__` 注释里），并留下这个只读别名。别名**没有 setter**：谁再往
        `go_fallbacks` 上赋值都会当场 `AttributeError`，不会静默记到一个没人读的字段里。

        ## 为什么住在 `Verifier` 上，而不是 `GoEngineMixin` 上（两处实测）

        ① 别名的读者是**动态绑定**出来的对象：`ensure_go_engine` 把混入类的方法
           一个个绑到 `Verifier` 实例上，而 `Verifier` **不继承** `GoEngineMixin`
           ⇒ 写在混入类上的属性，这些实例**根本看不到**，`getattr(..., None)`
           静默读成 `None`（＝还是那个静默）。写在 `Verifier` 上则**任何**实例
           （裸的、动态绑的、`GoVerifier`）都从类上解析得到。
        ② 也不能在 `ensure_go_engine` 里把它的 `fget` 绑成实例方法：实例字典里的
           条目**不走描述符协议**，读出来是**方法对象**而不是值 ⇒
           `or row["go_fallbacks"]` 恒真 ⇒ 闸门**永久假红**（本仓：永久假红等于没有判据）。

        `engine="python"` 的实例没有 `go_refusals`，取这个别名会 `AttributeError`
        ——与改名前的行为一致（`getattr(..., None)` 读成 `None`）。
        """
        return self.go_refusals

    def _run_other_engine(self, *, sim, plan, stage, deployed, title,
                          schedule=None, env=None):
        """换引擎时的出口。

        `"go"` 走 `simgo` 那一层；其余字符串照实报错。

        ⚠ **这里必须自己接住 `"go"`，不能只留一句报错**。默认引擎已经切成 `"go"`
        （见 `__init__` 的注释），而 Go 的出口本来只挂在 `GoVerifier`（混入
        `GoEngineMixin`）上——于是全仓那些**裸 `Verifier()`** 会崩在这里，
        而不是跑 Go。实测撞到过：`Verifier().run(...)` 直接抛
        「engine='go' 没有实现」。

        `ensure_go_engine` 是**惰性**的：只在真的要跑 Go 时把混入类那几个方法
        绑到本实例上。`verify.py` 不能 import `simgo`（`simgo.verifier` 反过来
        import 了 `verify`），函数内 import 绕开这条循环边。
        """
        if self.engine == "go":
            from ak_tactic.simgo.verifier import ensure_go_engine
            ensure_go_engine(self)
            # 绑完之后 `self._run_other_engine` 解析到混入类那一份（实例属性优先）。
            return self._run_other_engine(sim=sim, plan=plan, stage=stage,
                                          deployed=deployed, title=title)
        raise ValueError(
            f"engine={self.engine!r} 没有实现：只有 'python'（权威实现）以及"
            f"由 ak_tactic.simgo.GoVerifier 提供的出口")

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

    def mobility_deploy_spots(self, op, stage, previous) -> set[tuple[int, int]]:
        """天赋「翔虫机动」放宽出来、**本来不合法**的那些格（焰狐龙梓兰 天赋2）。

        prts.wiki 该页 `|备注=`：

        > ※非首次部署时，焰狐龙梓兰可以部署在远程位地块／**弹道范围内的近战位
        > 地块**，以此部署的焰狐龙梓兰的部署类型将临时变为全部位

        弹道停在**她上次部署的那一格**，范围代号取天赋黑板里的
        `$ignore_build_type_target_range`（`x-1`）。这里只返回"近战位里落进该
        范围的"，高台位不在放宽之列——她本来就能站高台。
        """
        rng = getattr(op, "mobility_deploy_range", "") or ""
        if previous is None or not rng or not getattr(
                op, "mobility_melee_deploy", False):
            return set()
        cells: set[tuple[int, int]] = set()
        provider = self.range_provider(stage) if self.use_range_table else None
        if provider is not None:
            try:
                cells = {(int(x), int(y))
                         for x, y in provider(op.char_id, op.elite, "Right",
                                              (int(previous[0]), int(previous[1])),
                                              range_id=rng)}
            except Exception:
                cells = set()
        if not cells:
            # 没有范围表时的退化口径：自身格 ＋ 朝前（向右）三格。
            cells = {(int(previous[0]) + i, int(previous[1])) for i in range(4)}
        return cells & set(stage.map.melee_spots)

    def _check_terrain(self, stage, op, pos, d, *, previous=None) -> None:
        """职业与地形必须相容。

        **模拟器不校验地形合法性**：落错了不会报错，只会安静地跑出一个
        "看起来对"的结果。2026-09-16 真踩过——把 MAA 字面量误翻一次，
        术师落到 `tile_end`、先锋落到 `tile_wall`，照样跑出「21 杀 0 漏」，
        只有耗时从 196.6s 变成 203.6s 露了马脚。

        `previous` = 这位干员**上一次**的落点（没有就传 None）。它只为一条
        天赋存在：焰狐龙梓兰的「翔虫机动」把"上次部署位置周围"的近战位也
        变成合法格（`mobility_deploy_spots`）。
        """
        melee = self.is_melee(op.char_id)
        spots = stage.map.melee_spots if melee else stage.map.ranged_spots
        if pos in spots:
            return
        if pos in self.mobility_deploy_spots(op, stage, previous):
            return
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
