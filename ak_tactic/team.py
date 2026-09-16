"""组队建议：按职介 / 子职业 / 标签 + 名册练度挑人。

**为什么要有这一层**：`search` 在没给 `--team` 时取「名册前 N 名」——那是按
*练度* 排的，与这一关需要什么*角色*无关。名册里练度最高的五个很可能全是输出。

三条打法经验落在这里（前两条博士 2026-09-16 给出，第三条 2026-09-17）：

* 「先锋干员基本都有回费技能，可以优先使用桃金娘，或者风笛加任意执旗手的
  组合」→ **执旗手**是核心（子职业「执旗手」），冲锋手是可选搭配。
* 「面对一次性的特高伤害攻击可以用低费用的快速复活干员骗掉，常用的是砾」
  → **处决者**按部署费用从低到高挑。
* 「焰狐龙梓兰（有模组）／麒麟R夜刀／缄默德克萨斯是**输出型**快速复活干员，
  这类干员与砾那种**骗伤害型**同样是随用随部署，用完就撤退或者当时就被击倒」
  → 「随用随部署」是一条**用法**，不是一个子职业；判别见下面的用法分表。

判据全部来自本地数据：`operator.profession` / `sub_profession_name` /
`tag_list` 给角色，`operator_attr.cost` 给部署费用，名册给练度。

五个口径上的坑，都是实测踩出来的：

* **特殊模式专属的干员要整批剔掉，不能只剔「预备干员」四个字**。
  `operator.is_not_obtainable` 圈住的是**两批**：预备干员（13 条）与集成战略／
  危机合约等模式专属（Misery、Sharp、Stormeye、Pith、Touch、Mechanist、
  Raidian、郁金香、暮落、盟约·辅助干员、领主·Sharp）。它们正常关卡用不了。
  漏剔的代价很具体：**Misery 也是处决者、6 星、7 费、再部署 18s**，光看
  角色判据它是个完美的骗伤位。
* **「快速复活」标签不能当处决者的判据**——它还挂着行商、情报官、傀儡师，
  甚至「焰狐龙梓兰（重射手）」。要判能不能低成本反复送死，看子职业
  `处决者`（11 名）。标签是给玩家看的，子职业才是机制。
  （要从标签数一遍得现查，别抄数：
  `SELECT sub_profession_name, COUNT(*) FROM operator WHERE is_operator=1
  AND tag_list LIKE '%快速复活%' GROUP BY 1`。）
* **子职业 `处决者` 里还混着机器人**：THRM-EX 也是处决者、**只有 3 费**，
  比砾还便宜——但它的特性是「不受部署数量限制，但**再部署时间极长**」，
  再部署 **200 秒**（标准处决者是 18 秒）。它是**一次性**的，骗不了第二次，
  按费用排会把排在第一。判据必须带 `respawn_time`，不能只看费用。
* **「先锋基本都有回费」是统计不是定义**：46 名先锋里 43 名带「费用回复」，
  例外是 CONFESS-47、夜刀、预备干员-近战。所以回费判定走**标签**，不走职介。
* **部署费用随精英段变，不能读基础档**：砾 精英0 是 6 费、精英1/2 是 8 费。
  照 `phase=0` 读会把每个练起来的干员都算便宜 2 费——而"便宜"正是这一层排序
  的唯一依据，错了就整个反了。费用一律按**名册里的实际精英段**查。

### 「随用随部署」的用法分表

同一条用法（落地、干完就撤、或者当场被击倒）横跨两类干员，判据不是子职业
一条，而是「子职业 + `tag_list` 里的**用途**标签」：

| 用法 | 子职业 | 用途标签 | 再部署 | 落地是去干什么的 |
|---|---|---|---|---|
| 骗伤害 | 处决者 | 防护 | 18s | 吃掉一次性的特高伤害，死了换下一个（**砾**） |
| 输出 | 处决者 | 输出 / 爆发 | 18s | 打一轮爆发，打完立刻撤退等下一轮（**缄默德克萨斯**、**麒麟R夜刀**） |
| 输出（靠加成达标） | **重射手** | 输出 + 快速复活 | 基础 **70s** | 同上，但"快"是靠天赋与模组挣来的（**焰狐龙梓兰**） |
| 控场 | 处决者 | 控场 | 18s | 反复补控（卡夫卡、红） |
| 一次性 | 处决者 | 爆发（**没有**「快速复活」） | **200s** | THRM-EX：只送得起一次 |

两条容易踩的：

* **`operator_attr.respawn_time` 是基础值**，天赋与模组的再部署减免**不在这一列**
  ——它们分别在 `operator_talent.blackboard` 与 `module_level.attribute_blackboard`
  的 `respawn_time` 键里。焰狐龙梓兰库里是 70s，靠天赋「翔虫机动」
  （`respawn_time` `-15`，精 2 起还「不提高部署费用」）与模组「梓兰特制箭靶」
  （`-25`）才够格。所以「再部署 ≤ 30s」这条判据会**漏掉靠加成达标的人**，
  与本函数末尾「已知未建模」记的天赋减费是同一类缺口。
  （这两笔减免是**秒**还是**比例**尚未裁定，别在代码里直接相加。）
* **用途标签判的是"去干什么"，不是"能不能反复送"**。能不能反复送只看
  `respawn_time`：THRM-EX 挂着「爆发」、只要 3 费，却要等 200 秒。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .db.api import connect
from .db.build import DEFAULT_DB_PATH
from .db.store import rows
from .plan import Roster

#: 「费用回复」标签——回费先锋的判据
DP_TAG = "费用回复"
#: 执旗手：以回费为唯一职能的先锋，回费效率最高
FLAG_BEARER = "执旗手"
#: 处决者：再部署时间最短的特种，专门用来送死
EXECUTIONER = "处决者"
#: 骗伤位的再部署时间上限（秒）。标准处决者是 18s（弑君者 22s），
#: 机器人 THRM-EX 是 200s——它便宜但只送得起一次，不算骗伤位。
BAIT_MAX_RESPAWN = 30.0

#: 低费位的候选稀有度。3★ 上限就是精1 55 级，4★ 里也有一批便宜且够用的。
LOW_STARS = ("TIER_3", "TIER_4")
#: 初始费用低于这个值 = **低费用环境**：开局连一个中等费用的干员都下不去，
#: 得等回费。实测 60 关里 initialCost 是 10（41 关）/15（3）/20（6）/50（1）
#: /0（4）/3（3）/5（1）/8（1）——10 与 10 以下才是常态，15 以上是宽裕的。
LOW_COST_INITIAL = 12.0
#: 低费位要**早落地**这么多秒，才值得占一个名额。
#: 参照：初始 10 费、每秒回 1 费时，9 费的 3★ 香草当场落地，21 费的
#: 6★ 赤刃明霄陈要等 11 秒、24 费的圣聆初雪要等 14 秒。
LOW_COST_GAIN = 4.0

ROLE_DP = "回费先锋"
ROLE_BAIT = "骗伤"
ROLE_CHEAP = "低费位"


@dataclass(frozen=True)
class Pick:
    """一个被推荐的人，连同推荐理由。"""

    name: str
    role: str
    sub: str
    cost: int | None
    elite: int
    level: int
    why: str
    #: 再部署时间（秒）。骗伤位的**真正**判据，见模块 docstring 第二条。
    respawn: float | None = None

    @property
    def power(self) -> int:
        """练度粗排：精英段优先，再看等级。"""
        return self.elite * 1000 + self.level

    def line(self) -> str:
        cost = "?" if self.cost is None else str(self.cost)
        rs = "" if self.respawn is None else f"，再部署 {self.respawn:.0f}s"
        return (f"{self.name}（{self.sub}，{cost} 费{rs}，"
                f"精英{self.elite} Lv{self.level}）— {self.why}")


@dataclass
class TeamSuggestion:
    """一份组队建议：角色位 + 填充位。"""

    #: 有明确角色理由的（回费先锋、骗伤处决者）
    picks: list[Pick] = field(default_factory=list)
    #: 按练度补足的其余位置
    filler: list[Pick] = field(default_factory=list)
    #: 看着像角色位、实际不能用的（如再部署 200s 的机器人处决者）。
    #: 留着是为了报告里能说明"为什么没选它"——不然每次都要重查一遍。
    rejected: list[Pick] = field(default_factory=list)
    #: 费用环境的判定结果 `(是否低费用环境, 说明)`；没给 --stage 时是 `(False, …)`
    cost_note: tuple[bool, str] = (False, "")
    #: 没出低费位时的理由，报告里如实写出来
    notes: list[str] = field(default_factory=list)

    @property
    def all(self) -> list[Pick]:
        return [*self.picks, *self.filler]

    def team(self) -> list[str]:
        """给 `search --team` 用的名字列表：**角色位在前**。

        顺序即建议的部署顺序——回费先锋要最先落地，骗伤位要在高伤攻击
        到来之前就位。搜索器本身会重排落位，但初值给对能省掉大量搜索。
        """
        return [p.name for p in self.all]

    def report(self) -> str:
        out = ["组队建议："]
        tight, note = self.cost_note
        if note:
            out.append(f"  费用环境：{note}")
        if self.picks:
            out.append("  角色位：")
            out += [f"    - {p.line()}" for p in self.picks]
        if self.filler:
            out.append("  练度补齐：")
            out += [f"    - {p.line()}" for p in self.filler]
        if not self.all:
            out.append("  （名册里没有可用的人）")
        for n in self.notes:
            out.append(f"  未出低费位：{n}")
        if self.rejected:
            out.append("  看着像、其实不能用：")
            out += [f"    - {p.line()}" for p in self.rejected]
        return "\n".join(out)


def _phase_attrs(conn: sqlite3.Connection,
                 char_ids: Sequence[str]) -> dict[str, dict[int, dict[str, float]]]:
    """每个干员各精英段的部署费用与再部署时间。

    只收 `kind='phase'`——`operator_attr` 里还有 `kind='trust'` 的行，
    那些的 cost 是 0，混进来会把所有人算成 0 费。
    """
    if not char_ids:
        return {}
    marks = ",".join("?" * len(char_ids))
    got = rows(conn, f"""
        SELECT char_id, phase, cost, respawn_time FROM operator_attr
        WHERE kind = 'phase' AND char_id IN ({marks})
    """, tuple(char_ids))
    out: dict[str, dict[int, dict[str, float]]] = {}
    for r in got:
        c = r.get("cost")
        if c is None or c <= 0:
            continue
        out.setdefault(r["char_id"], {})[int(r["phase"])] = {
            "cost": float(c),
            "respawn": float(r.get("respawn_time") or 0.0),
        }
    return out


def _profiles(conn: sqlite3.Connection,
              char_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """角色档案：职介 / 子职业 / 标签 / 各段费用 / 是否特殊模式专属。"""
    if not char_ids:
        return {}
    marks = ",".join("?" * len(char_ids))
    got = rows(conn, f"""
        SELECT char_id, name, profession, sub_profession_name, tag_list,
               is_not_obtainable, rarity_str
        FROM operator WHERE char_id IN ({marks})
    """, tuple(char_ids))
    costs = _phase_attrs(conn, char_ids)
    out: dict[str, dict[str, Any]] = {}
    for r in got:
        tags: list[str] = []
        try:
            parsed = json.loads(r.get("tag_list") or "[]")
            if isinstance(parsed, list):
                tags = [str(t) for t in parsed]
        except (TypeError, ValueError):
            tags = []
        out[r["char_id"]] = {
            "name": r.get("name"),
            "profession": r.get("profession") or "",
            "sub": r.get("sub_profession_name") or "",
            "tags": tags,
            "phase": costs.get(r["char_id"], {}),
            "special_mode": bool(r.get("is_not_obtainable")),
            "rarity": r.get("rarity_str") or "",
        }
    return out


def _normal_stage_usable(prof: dict[str, Any]) -> bool:
    """这个干员在**正常关卡**里用得了吗。

    判据是 `operator.is_not_obtainable`——它圈住的不是一类人，而是**两批**：

    * **预备干员**（13 条：先锋/近战/狙击/术师/医疗/重装/辅助/近卫/特种/后勤），
      教学与特殊模式才给；
    * **集成战略／危机合约等模式专属干员**（Misery、Sharp、Stormeye、Pith、
      Touch、Mechanist、Raidian、郁金香、暮落、盟约·辅助干员、领主·Sharp）。

    两批都只在特殊模式出现，正常关卡的名册里不会有、也不该被推荐。
    **只按名字剔「预备干员」是不够的**：Misery 也是处决者、6 星、7 费，
    看起来是个完美的骗伤位，实际用不了。
    """
    return not prof.get("special_mode")


def _at(prof: dict[str, Any], elite: int, field: str) -> float | None:
    """按名册里的**实际**精英段取一项分段属性（见模块 docstring 第四条）。

    名册精英段在库里没有（数据代差）时，退到不高于它的最高段。
    """
    by_phase = prof.get("phase") or {}
    if not by_phase:
        return None
    phase = elite if elite in by_phase else None
    if phase is None:
        lower = [p for p in by_phase if p <= elite]
        phase = max(lower) if lower else min(by_phase)
    return by_phase[phase].get(field)


def _cost_at(prof: dict[str, Any], elite: int) -> int | None:
    v = _at(prof, elite, "cost")
    return None if v is None else int(v)


def _respawn_at(prof: dict[str, Any], elite: int) -> float | None:
    return _at(prof, elite, "respawn")


def _entry_pick(name: str, e: dict[str, Any], prof: dict[str, Any],
                role: str, why: str) -> Pick:
    elite = int(e.get("elite") or 0)
    return Pick(name=name, role=role, sub=prof.get("sub") or "—",
                cost=_cost_at(prof, elite), respawn=_respawn_at(prof, elite),
                elite=elite, level=int(e.get("level") or 1), why=why)


def _is_dp(prof: dict[str, Any]) -> bool:
    return DP_TAG in (prof.get("tags") or [])


def cost_delay(cost: float | None, initial: float, inc: float) -> float:
    """这个费用的干员最早**第几秒**能落地。

    `延迟 = max(0, (费用 − 初始费用) × 每点耗时)`。`costIncreaseTime` 就是
    "每回 1 点费用要几秒"（实测 59/60 关是 1.0，`act31side_mo01` 是 999
    ——那种关给一大笔初始费用、几乎不回费，两者相抵后延迟恒为 0）。
    """
    if cost is None:
        return 0.0
    return max(0.0, (float(cost) - initial) * inc)


def stage_cost_env(level_id: str) -> tuple[float, float]:
    """关卡的费用环境 `(初始费用, 每点耗时)`；取不到就抛。"""
    from .gamedata.source import GameDataSource
    opts = (GameDataSource().level(level_id) or {}).get("options") or {}
    return (float(opts.get("initialCost") or 0.0),
            float(opts.get("costIncreaseTime") or 1.0))


def low_cost_env(level_id: str | None) -> tuple[bool, str]:
    """这一关算不算**低费用环境**，以及给一句人话理由。

    判据只有一条：**初始费用够不够开局下一个人**（`LOW_COST_INITIAL`）。
    为什么不用"平均费用"之类的相对口径——绝对口径能直接对着关卡数据核，
    相对口径会把「初始 20 费、人均 21 费」这种宽裕局也判成紧张。
    """
    if not level_id:
        return False, "没给 --stage，不判费用环境"
    try:
        initial, inc = stage_cost_env(level_id)
    except Exception as exc:                       # 关卡取不到不该挡住建议
        return False, f"关卡 {level_id} 读不到费用参数（{exc}），不判费用环境"
    if inc >= 100:                                 # act31side_mo01：不回费
        return False, (f"{level_id} 初始 {initial:.0f} 费、几乎不回费"
                       "——一次性给足，没有先后之争")
    tight = initial < LOW_COST_INITIAL
    return tight, (f"{level_id} 初始 {initial:.0f} 费、每点 {inc:g}s"
                   f"（阈值 {LOW_COST_INITIAL:g}）"
                   + ("：低费用环境" if tight else "：费用宽裕"))


def low_cost_pick(roster: Roster, conn: sqlite3.Connection, *,
                  reference_cost: float | None,
                  initial: float, inc: float,
                  exclude: Iterable[str] = ()) -> tuple[Pick | None, str]:
    """低费位人选。

    池子是名册里**全部 3★/4★**（不设练度门槛），按练度降序、同练度按费用升序。
    取第一个比 `reference_cost`（练度最高的补齐候选）**早落地 ≥ `LOW_COST_GAIN` 秒**
    的人——只按练度排会选出 32 费的远山，那就不是低费位了，所以这道费用门是必须的。

    **不按子职业去重**（2026-09-16 博士裁定）：判据是"适不适合这一关"，不是
    "有没有和已有角色位撞职业"。多一个同子职业的人未必多余——两个战术家各自
    铺一路是常见打法，而为了避开重复去挑一个更贵或更弱的人，反而把这一位的
    意义（**便宜、早落地**）丢掉了。曾加过一道子职业去重，已撤。

    返回 `(人选, 说明)`；没人合格时人选为 None、说明里写清为什么。
    """
    profs = _profiles(conn, [e["char_id"] for e in roster.entries.values()
                             if e.get("char_id")])
    skip = set(exclude)
    pool: list[tuple[int, float, str, dict[str, Any], dict[str, Any]]] = []
    for name, e in roster.entries.items():
        if name in skip:
            continue
        p = profs.get(e.get("char_id") or "")
        if not p or p.get("rarity") not in LOW_STARS:
            continue
        if not _normal_stage_usable(p):
            continue
        elite = int(e.get("elite") or 0)
        cost = _cost_at(p, elite)
        if cost is None:
            continue
        pool.append((-int(elite) * 1000 - int(e.get("level") or 1), float(cost),
                     name, e, p))
    if not pool:
        return None, "名册里没有可用的 3★/4★"
    pool.sort(key=lambda x: (x[0], x[1]))          # 练度降序 → 费用升序

    ref_delay = cost_delay(reference_cost, initial, inc)
    for _, cost, name, e, p in pool:
        gain = ref_delay - cost_delay(cost, initial, inc)
        if gain >= LOW_COST_GAIN:
            why = (f"{cost:.0f} 费，比练度最高的补齐候选早落地 {gain:.0f}s"
                   f"（低费用环境下便宜就是先手）")
            return _entry_pick(name, e, p, ROLE_CHEAP, why), ""
    best = pool[0]
    return None, (f"池里最便宜的两个也早不了 {LOW_COST_GAIN:g}s"
                  f"（{best[2]} {best[1]:.0f} 费）")


def dp_vanguards(roster: Roster, conn: sqlite3.Connection) -> list[Pick]:
    """回费先锋，执旗手优先。

    排序：执旗手 → 其他回费先锋；同类里练度高的在前。
    执旗手优先是**机制**上的理由，不是偏好：执旗手的技能直接把费用打进
    账上，冲锋手要靠击杀/受击攒，开局那 10 秒的差别是线性的。
    """
    profs = _profiles(conn, [e["char_id"] for e in roster.entries.values()
                             if e.get("char_id")])
    out: list[Pick] = []
    for name, e in roster.entries.items():
        p = profs.get(e.get("char_id") or "")
        if not p or not _is_dp(p) or not _normal_stage_usable(p):
            continue
        flag = p["sub"] == FLAG_BEARER
        why = ("执旗手：技能直接回费，开局最快" if flag
               else "回费先锋，作为执旗手的搭配位")
        out.append(_entry_pick(name, e, p, ROLE_DP, why))
    out.sort(key=lambda x: (x.sub != FLAG_BEARER, -x.power))
    return out


def bait_candidates(roster: Roster, conn: sqlite3.Connection,
                    *, max_cost: int | None = None
                    ) -> tuple[list[Pick], list[Pick]]:
    """骗伤位候选，返回 `(可用, 淘汰)`。

    判据两道，缺一不可：子职业 `处决者`（不是「快速复活」标签），且
    **再部署时间 ≤ `BAIT_MAX_RESPAWN`**（不是只有费用低）。第二道是必需的
    ——THRM-EX 也是处决者、只要 3 费，但再部署 200 秒，骗不了第二次，
    只看费用会把它排在第一。

    **已知未建模**：干员天赋里写的「自身部署费用-1」（砾的「快速部署」、
    「小个子支援」）**没有**计进 `operator_attr.cost`——那是基础属性，
    天赋减费在结算层。所以名册里同为 18s 再部署的砾（表 8 费）与卡夫卡
    （表 7 费）实际可能同费，本函数会把卡夫卡排在前面。要精确排序得先把
    天赋的 cost 修正接进来；在那之前这个顺序只在**同天赋条件**下可信。
    """
    profs = _profiles(conn, [e["char_id"] for e in roster.entries.values()
                             if e.get("char_id")])
    ok: list[Pick] = []
    bad: list[Pick] = []
    for name, e in roster.entries.items():
        p = profs.get(e.get("char_id") or "")
        if not p or p["sub"] != EXECUTIONER:
            continue
        if not _normal_stage_usable(p):
            continue        # 预备干员 / 模式专属：正常关卡用不了，不参与排序
        elite = int(e.get("elite") or 0)
        cost = _cost_at(p, elite)
        if max_cost is not None and cost is not None and cost > max_cost:
            continue
        rs = _respawn_at(p, elite)
        if rs is None or rs > BAIT_MAX_RESPAWN:
            bad.append(_entry_pick(
                name, e, p, ROLE_BAIT,
                f"再部署 {rs:.0f}s，送不起第二次——不做骗伤位"
                if rs is not None else "库里没有再部署时间，不敢当骗伤位"))
            continue
        ok.append(_entry_pick(name, e, p, ROLE_BAIT,
                              f"再部署 {rs:.0f}s，骗掉一次性高伤后能再来"))
    ok.sort(key=lambda x: (x.cost if x.cost is not None else 99, -x.power))
    return ok, bad


def bait_units(roster: Roster, conn: sqlite3.Connection,
               *, max_cost: int | None = None) -> list[Pick]:
    """骗伤位：可反复送死的处决者，按**实际**部署费用从低到高。"""
    return bait_candidates(roster, conn, max_cost=max_cost)[0]


def suggest(roster: Roster, *, conn: sqlite3.Connection | None = None,
            size: int = 8, path: Path | str | None = None,
            with_charger: bool = True,
            stage: str | None = None) -> TeamSuggestion:
    """组一份建议队伍。

    结构：先占**角色位**（回费先锋、骗伤处决者，低费用环境下再加一个低费位），
    其余按练度补齐。练度补齐那部分与 `search` 原来的「名册前 N 名」是同一
    口径——这一层不改变"谁强"，只在上面**加几个位置**，因为缺的从来不是强的
    人，而是开局费用和一次性的替死鬼。

    :param stage: 关卡（level id 或显示名）；给了才判费用环境、才可能出低费位
    """
    own = conn is not None
    conn = conn or connect(path or DEFAULT_DB_PATH, readonly=True)
    try:
        sug = TeamSuggestion()
        picked: set[str] = set()

        dps = dp_vanguards(roster, conn)
        if dps:
            sug.picks.append(dps[0])
            picked.add(dps[0].name)
            # 「风笛加任意执旗手的组合」——执旗手之外再来一个回费（冲锋手
            # 之类），但只在它确实练起来了的时候才值得占位
            if with_charger:
                for cand in dps[1:]:
                    if cand.sub != FLAG_BEARER and cand.power >= 1500:
                        sug.picks.append(cand)
                        picked.add(cand.name)
                        break

        baits, rejects = bait_candidates(roster, conn)
        sug.rejected.extend(rejects)
        for cand in baits:
            if cand.name not in picked:
                sug.picks.append(cand)
                picked.add(cand.name)
                break

        ranked = sorted(
            (n for n in roster.entries if n not in picked),
            key=lambda n: -(int(roster.entries[n].get("elite") or 0) * 1000
                            + int(roster.entries[n].get("level") or 1)))
        # 补齐位也要过同一道门：名册里若混进了预备干员/模式专属（森空岛在某些
        # 情况下会把它们列出来），按练度排它们很可能直接进前几名。
        profs = _profiles(conn, [roster.entries[n].get("char_id") or ""
                                 for n in ranked])
        usable = [n for n in ranked if _normal_stage_usable(
            profs.get(roster.entries[n].get("char_id") or "", {}))]

        # ---- 低费位：只在**低费用环境**下出，判据是关卡初始费用 ----
        sug.cost_note = low_cost_env(stage)
        tight, note = sug.cost_note
        if tight and usable:
            ref = _cost_at(profs.get(roster.entries[usable[0]].get("char_id")
                                     or "", {}), int(roster.entries[usable[0]]
                                                     .get("elite") or 0))
            initial, inc = stage_cost_env(stage or "")
            pick, why = low_cost_pick(roster, conn, reference_cost=ref,
                                      initial=initial, inc=inc, exclude=picked)
            if pick is not None:
                sug.picks.append(pick)
                picked.add(pick.name)
            else:
                sug.notes.append(why)
        elif not tight:
            sug.notes.append(note)

        want = max(0, size - len(sug.picks))
        for name in usable:
            if len(sug.filler) >= want:
                break
            if name in picked:
                continue
            e = roster.entries[name]
            sug.filler.append(_entry_pick(name, e, profs.get(e["char_id"] or "", {}),
                                          "补齐", "按练度补足"))
        return sug
    finally:
        if not own:
            conn.close()
