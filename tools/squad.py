# -*- coding: utf-8 -*-
"""从森空岛名册造干员：把**真实专精、模组、信赖**接进模拟器。

为什么需要这一层
----------------
先前 `run_srx8.build()` 直接吃 MAA 的 OperBox 导出，而那份数据里
① 没有专精 ② 没有模组 ③ 没有信赖。于是所有模拟都跑在
「技能 7 级 / 专精 0 / 无模组 / 信赖 100%」的假口径上，实测差距很大：
机械师槽1「聚类分析」专三后单次伤害 **+40.9%**，而提丰的信赖只有 **32.5%**。

`Roster` 是模拟器取干员的**唯一入口**：

    load()     读 data/skland/roster_<uid>.json（skland.py + roster.py 产出）
    stats()    按真实信赖/潜能/模组算属性
    unit()     造 OperatorUnit
    mastery()  查某个技能槽的专精等级——按 `SkillBook` 的 slot 对齐，
               不靠技能 id 的尾号猜（阿米娅的槽1 叫 `skcom_magic_rage[3]`，
               尾号是 3，猜法会串到槽3）
    rank()     按练度排序，对应需求「优先从我练度最高的干员里选」

模组的三种不算数的情况已在 `tools/roster.py` 里剔除，这里只读结论
（`module` 为空就表示没有可用模组）。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ak_tactic.battle.unit import OperatorUnit          # noqa: E402
from ak_tactic.operator import OperatorCalculator, SkillBook  # noqa: E402
from ak_tactic.operator.attack_speed import attack_speed_bonus  # noqa: E402

ROSTER_DIR = ROOT / "data" / "skland"
SKILL_LEVEL = 7          # 普通等级 1–7，专精另计


def default_roster_path() -> pathlib.Path:
    files = sorted(ROSTER_DIR.glob("roster_*.json"))
    if not files:
        raise SystemExit(
            f"{ROSTER_DIR} 下没有 roster_*.json。\n"
            f"先跑：python tools/skland.py login <手机号> <验证码>\n"
            f"      python tools/skland.py fetch\n"
            f"      python tools/roster.py")
    return files[-1]


class RosterError(RuntimeError):
    pass


class Roster:
    """一份玩家名册 + 按它造干员的能力。"""

    def __init__(self, path: pathlib.Path | str | None = None):
        self.path = pathlib.Path(path) if path else default_roster_path()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.uid = data.get("uid")
        self.nick = data.get("nickName")
        self.rows: list[dict] = data["opers"]
        self.by_id = {r["charId"]: r for r in self.rows}
        self.calc = OperatorCalculator()
        self.book = SkillBook()
        #: 一个名字可能对应多个 charId（阿米娅的升变形态）；
        #: 优先取算符算得出的那个基础形态，否则取名册里第一个。
        self.by_name: dict[str, dict] = {}
        for r in self.rows:
            n = r["name"]
            if n not in self.by_name:
                self.by_name[n] = r
            elif (not self.calc.exists(self.by_name[n]["charId"])
                  and self.calc.exists(r["charId"])):
                self.by_name[n] = r

    # ------------------------------------------------------------ 取条目
    def get(self, name: str) -> dict:
        r = self.by_name.get(name) or self.by_id.get(name)
        if r is None:
            raise RosterError(f"名册里没有「{name}」")
        return r

    def has(self, name: str) -> bool:
        return name in self.by_name or name in self.by_id

    def names(self) -> list[str]:
        return [r["name"] for r in self.rows]

    # ------------------------------------------------------------ 属性
    def stats(self, name: str):
        """按真实信赖/潜能/模组算属性。"""
        r = self.get(name)
        return self.calc.stats(
            r["charId"], elite=r["elite"], level=r["level"],
            trust=r["trust"], potential=r["potential"],
            module=r["module"], module_level=r["module_level"])

    def unit(self, name: str) -> OperatorUnit:
        """造一个 OperatorUnit。阻挡数只能从 stats().total 取。

        `heals` 判的是**特性文本**里有没有"恢复友方单位生命"，不是职业名。
        理由：守望者（凯尔希·思衡托）职业也是 MEDIC、特性同样以治疗开头，
        但它另外还会起飞；而反过来「咒愈师」这类子职业的平A虽带伤害，
        特性文本照样写着治疗。按职业推会在这两种上都判错。

        `attack_type` 同样取**特性文本**：写了"法术伤害"就是法术，否则物理。
        这一条曾经整个漏掉——`OperatorUnit` 的默认值是 PHYSICAL，而构造时
        没人传，于是**名册里每一个人都退化成物理**。在 SR-EX-8 上后果很重：
        圣聆初雪是 CASTER（阵法术师），实际打法术，而本关有 RES 99 的
        吓人路灯和"法术免疫"的 BOSS 形态，把她当物理算会凭空多出成吨输出。
        """
        r = self.get(name)
        t = self.stats(name).total
        c = self.calc.character(r["charId"])
        ph = c.get("phases") or []
        trait = (c.get("description") or "")
        # 「弱点伤害」（赤刃明霄陈天赋「形意洞照」）：出手时两系都算、取更高的一系。
        # 天赋文本里带标记 `<$ba.weaknessatk>弱点伤害</>`，所以按纯文本"弱点伤害"找，
        # 与特性/技能文本分开判——它只出现在天赋里。
        tal_text = " ".join(
            (cand.get("description") or "")
            for t_ in (c.get("talents") or [])
            for cand in (t_.get("candidates") or []))
        # 攻速 = 基础 100 + 天赋 + 模组特性，**必须单独取**：`stats().total`
        # 里的 `attackSpeed` 只有基础值，天赋的 +16 与模组改写的 +8 都不在
        # 里面。漏掉这一句，赤刃明霄陈的出手频率会低 24%（1.008s 变成 1.25s）。
        aspd = attack_speed_bonus(
            self.calc, r["charId"], elite=r["elite"], level=r["level"],
            potential=r["potential"], module=r["module"],
            module_level=r["module_level"])
        return OperatorUnit(
            name=r["name"], char_id=r["charId"],
            max_hp=t["maxHp"], atk=t["atk"], defense=t["def"],
            res=t["magicResistance"],
            attack_interval=t.get("baseAttackTime") or 1.0,
            block_cnt=int(t.get("blockCnt") or 1),
            deploy_cost=int(t.get("cost") or 0),
            elite=r["elite"],
            attack_speed=float(t.get("attackSpeed") or 100) + aspd.flat,
            aspd_when_free=aspd.when_free,
            attack_type="MAGIC" if "法术伤害" in trait else "PHYSICAL",
            heals="恢复友方单位生命" in trait,
            weakness_damage="弱点伤害" in tal_text)

    # ------------------------------------------------------------ 技能
    def slots(self, name: str):
        """该干员的技能槽列表（OperatorSkill，带 .slot / .skill_id）。"""
        return self.book.for_operator(self.get(name)["charId"])

    def mastery(self, name: str, slot: int) -> int:
        """某个技能槽的专精等级 0–3。按 slot 对齐，不猜 id 尾号。"""
        r = self.get(name)
        for s in self.slots(name):
            if s.slot == slot:
                return int(r["mastery"].get(s.skill_id, 0))
        return 0

    def default_slot(self, name: str) -> int:
        """名册里记的默认技能槽（玩家当前在游戏里选的那个）。"""
        r = self.get(name)
        sid = r.get("defaultSkillId") or ""
        for s in self.slots(name):
            if s.skill_id == sid:
                return s.slot
        return 1

    def skill_name(self, name: str, slot: int) -> str:
        for s in self.slots(name):
            if s.slot == slot:
                return s.name
        return "—"

    # ------------------------------------------------------------ 练度
    def investment(self, name: str) -> float:
        """练度分：用于「优先从练度最高的干员里选」。

        权重是**人为定的**，但方向明确——精英阶段与等级是门槛，专精与模组
        是质变，潜能与信赖是边际。信赖按实际百分比给分（这台账号里
        机械师 61.5%、提丰 32.5%，不满就是不満）。
        """
        r = self.get(name)
        spec = sum(r["mastery"].values())
        mod = r["module_level"] if r["module"] else 0
        return (r["elite"] * 1000.0 + r["level"] * 1.0
                + spec * 60.0 + mod * 40.0
                + r["potential"] * 8.0 + r["trust"] * 0.3)

    def rank(self, *, min_elite: int = 2, limit: int = 40) -> list[tuple[str, float]]:
        out = []
        seen = set()
        for r in self.rows:
            if r["elite"] < min_elite:
                continue
            row = self.get(r["name"])          # 升变形态会折回基础形态
            if row["charId"] in seen:
                continue
            seen.add(row["charId"])
            out.append((row["name"], self.investment(row["name"])))
        out.sort(key=lambda kv: -kv[1])
        return out[:limit]

    def profile(self, name: str) -> str:
        """一行摘要，写日志/报告用。"""
        r = self.get(name)
        tail = {}
        for s in self.slots(name):
            tail[s.slot] = r["mastery"].get(s.skill_id, 0)
        spec = "/".join({0: "—", 1: "一", 2: "二", 3: "三"}[tail.get(i, 0)]
                        for i in (1, 2, 3))
        mod = (f"{r['module']} Lv{r['module_level']}" if r["module"]
               else "无可用模组")
        return (f"{r['name']:<12}E{r['elite']} L{r['level']:<3} "
                f"潜{r['potential']} 信赖{r['trust']:g}% 专精[{spec}] {mod}")
