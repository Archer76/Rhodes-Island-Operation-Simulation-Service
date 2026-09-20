# -*- coding: utf-8 -*-
"""关卡无关的「打法」表示：阵容 + 落位 + 朝向 + 部署时机 + 技能时机。

这是 README「阶段 5 · 求解与搜索」的第一步——**把打法变成数据**。

在此之前，验证一件事只能靠在 `tools/` 下写一个关卡专属脚本
（`run_sr6.py` / `run_srx8.py` / `export_srx8.py`），三份脚本各自重复
"载入门票 → 按费用排时刻 → 落位合法性守卫 → 跑 → 打印"。于是
「这个打法能不能三星」这个问题没有一个统一的答案口，换一关就要再写一份。

本模块把那套重复的东西抽出来，只剩下**数据**：

    Plan（JSON 可存可读）+ Roster（练度从哪来）

于是 `ak_tactic/verify.py` 只需要一个关卡号与一份 Plan。

坐标系：**MAA 口径**（原点左上、y 向下），与项目内部一致，也与 MAA 作业的
`location: [x, y]` 一致——所以作业里的坐标可以原样抄进 Plan，**不做换算**。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["DeployOrder", "RetreatOrder", "SkillOrder", "Plan",
           "Roster", "PlanError"]

DIRECTIONS = ("Right", "Left", "Up", "Down")

#: 把 `json.dumps(indent=2)` 拆成多行的两元数组压回一行（只用于 `position`）。
_POS_ML = re.compile(r'"position": \[\s*(\d+),\s*(\d+)\s*\]')


def _skill_from_json(raw: dict[str, Any], where: str) -> Any:
    """把 `skill` 的**对象形态**装成一枚 `SkillLevel`（丙方案，PM 2026-09-20 批准）。

    写法：`{"id": "skchr_angel_3", "level": 7, "mastery": 3}`。

    ★ **为什么这件事只需要改这里**：`frontend/schedule.py:69` 的 `Deployment.skill`
    **类型本来就是 `object`**，它的文档字符串早就写了「也可以直接给一个
    `SkillLevel` 对象」，而 `simgo/spec.py:97-101` 已经在兑现那条分支。
    **形状本来就在，是下面 `from_dict` 里那个 `int(...)` 把它掐窄了。**

    ⚠ **为什么不用 `for_operator(char_id)`**（那一支才是 `SkillBook` 的示例用法）：
    `DeployOrder.operator` 是**中文名**，而那一支要 `char_id`，两者的映射住在
    **名册**里——`Plan.from_dict` 手上**没有名册**（`5383209a`：计划用中文名、
    名册用 charId，是两个键空间）。`skill_id` 是**全局唯一**的，
    所以走 `levels(skill_id)` 这条路**不需要名册**。

    ⚠ **`import` 故意放在函数里**：`plan.py` 今天是**只依赖标准库的叶子模块**，
    把取数/gamedata 那一套拖到模块顶层，会让每个 `import plan` 的地方都先付这份
    代价——而旧夹具一个字段都不用它（走的是下面那条 int 路）。

    ★ **装不出来一律拒跑并具名报错**：不许 `getattr` 兜底、不许把认不出的值当 0
    ——那会把「我写错了字段」静默变成「这一局不带技能」，正好把这条刚打开的路
    反过来焊死。
    """
    if not isinstance(raw, dict):
        raise PlanError(
            f"{where} 只能是 0–3 的整数或一个对象，收到 {type(raw).__name__}")
    sid = raw.get("id") or raw.get("skill_id")
    if not sid:
        raise PlanError(
            f"{where} 缺 `id`（技能编号，如 skchr_angel_3）。"
            f"★ 这里**不认槽位号**：槽位号只在「同一位干员的第几个技能」里有意义，"
            f"而技能编号是全局唯一的——两个键空间，不许混")
    level = int(raw.get("level") or 7)
    mastery = int(raw.get("mastery") or 0)
    #: ⚠ 迟到的 import（理由见 docstring）。
    from ak_tactic.operator.skill import SkillBook, resolve_index
    book = SkillBook()
    if not book.exists(str(sid)):
        raise PlanError(f"{where} 的技能编号 {sid!r} 在技能表里没有")
    levels = book.levels(str(sid))
    idx = resolve_index(level, mastery)
    if idx >= len(levels):
        raise PlanError(
            f"{where} 的 {sid} 只有 {len(levels)} 个等级，"
            f"取不到 level={level} / mastery={mastery}")
    return levels[idx]


class PlanError(ValueError):
    """打法文件有问题。**必须是硬错误**——静默纠正一个错坐标会产出假结果。"""


# ---------------------------------------------------------------- 单条指令

@dataclass
class DeployOrder:
    """一次部署。

    `time=None` 表示**按费用自动排**（"钱够了就下"），与 MAA 的自动作战同规则；
    给了具体秒数则用它。练度三个字段为 `None` 时从名册取。
    """

    operator: str
    position: tuple[int, int]
    direction: str = "Right"
    #: ★ **0–3 的槽位号，或一个技能对象**（丙方案，2026-09-20）。
    #: 对象形态＝`{"id": 技能编号, "level": 1–7, "mastery": 0–3}`，
    #: 装成 `SkillLevel` 之后放进 `self.skill`。
    #: ★ 与 `frontend/schedule.py:69` 的 `Deployment.skill` **同一个类型契约**
    #: （那边本来就是 `object`）——这里今天才跟上。
    skill: object = 0
    mastery: int = 0
    elite: int | None = None
    level: int | None = None
    potential: int | None = None
    #: 信赖 0–100 **内部标度**（= 游戏显示信赖 ÷ 2，100 即满 200%；**不是**森空岛的
    #: 0–200 标度，那边要除以 2）。
    #: 它会影响属性（`calc.stats(trust=…)`），漏了就会算低。
    trust: int | None = None
    module: str | None = None
    #: 模组等级 1–3（`module` 给了才有效）。
    module_level: int | None = None
    time: float | None = None
    auto_skill: bool = True
    #: ★ **对象形态的原始写法**，只用于 `to_dict` 往返。
    #: `skill` 到了这里已经是一枚 `SkillLevel`（不可 JSON 序列化），
    #: 而 `to_dict` 要写出**能被再读回来的**那一份 ⇒ 原件留在这儿。
    #: `repr=False` 避免每次打印都吐一大坨；`compare=False` 让它不参与相等判定。
    _skill_raw: dict[str, Any] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.position = (int(self.position[0]), int(self.position[1]))
        if self.direction not in DIRECTIONS:
            raise PlanError(
                f"{self.operator} 的朝向 {self.direction!r} 不认识，"
                f"只能是 {DIRECTIONS} 之一")
        if isinstance(self.skill, dict):
            #: ★ 对象形态：**在这里**装成 `SkillLevel`（下游一行都不用改：
            #: `spec.py:97` 判的是 `isinstance(spec, int)`，对象自然走「已经绑好」那条）。
            self._skill_raw = self.skill
            self.skill = _skill_from_json(self.skill, f"{self.operator} 的 skill")
        elif not 0 <= int(self.skill) <= 3:
            #: ⚠ 这条**一个字的判定都没改**：旧夹具走的还是这一行。
            raise PlanError(f"{self.operator} 的技能槽 {self.skill} 越界（0–3）")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "operator": self.operator, "position": list(self.position),
            "direction": self.direction,
            #: 对象形态写回**原件**（不是那枚 `SkillLevel`，它序列化不了）
            "skill": self._skill_raw if self._skill_raw is not None else self.skill,
        }
        for k in ("mastery", "elite", "level", "potential", "trust", "module",
                  "module_level", "time"):
            v = getattr(self, k)
            if v is not None and not (k == "mastery" and v == 0):
                out[k] = v
        if not self.auto_skill:
            out["auto_skill"] = False
        return out


@dataclass
class RetreatOrder:
    """一次撤退。"""

    operator: str
    time: float

    def to_dict(self) -> dict[str, Any]:
        return {"operator": self.operator, "time": self.time}


@dataclass
class SkillOrder:
    """一次手动开技能。`auto_skill=False` 的干员靠它出手。"""

    operator: str
    time: float
    slot: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"operator": self.operator, "time": self.time, "slot": self.slot}


# ---------------------------------------------------------------- 名册

@dataclass
class Roster:
    """练度表：名字 → `{char_id, elite, level, potential, module, module_level}`。

    吃两种格式，都是本项目已有的产物：

    * **MAA OperBox 导出**——顶层是**列表**，条目 `{id, name, elite, level,
      own, potential, rarity}`。
    * **森空岛名册**（`tools/roster.py`）——顶层是字典，干员在 `opers` 下，
      条目 `{charId, name, elite, level, potential, module, module_level, …}`。

    只收 `own` 为真的（OperBox 会带上没抽到的干员）。
    """

    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> Roster:
        return cls({})

    @classmethod
    def from_json(cls, path: Path | str) -> Roster:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            rows = data.get("opers") or data.get("chars") or []
        elif isinstance(data, list):
            rows = data
        else:
            raise PlanError(f"名册 {path} 的形状不认识：{type(data).__name__}")
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            if r.get("own") is False:
                continue
            name = r.get("name")
            cid = r.get("charId") or r.get("id")
            if not name or not cid:
                continue
            out[name] = {
                "char_id": cid,
                "elite": int(r.get("elite") or 0),
                "level": int(r.get("level") or 1),
                "potential": int(r.get("potential") or 1),
                "module": r.get("module") or None,
                "module_level": int(r.get("module_level") or 0),
            }
        return cls(out)

    def get(self, name: str) -> dict[str, Any] | None:
        return self.entries.get(name)

    def names(self) -> list[str]:
        return sorted(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, name: object) -> bool:
        return name in self.entries


# ---------------------------------------------------------------- 打法

@dataclass
class Plan:
    """一份完整的打法。"""

    stage: str
    deploys: list[DeployOrder] = field(default_factory=list)
    retreats: list[RetreatOrder] = field(default_factory=list)
    skills: list[SkillOrder] = field(default_factory=list)
    title: str = ""
    notes: str = ""

    # -------------------------------------------------- 校验

    def validate(self) -> None:
        if not self.stage:
            raise PlanError("打法必须有关卡号（`stage`）")
        if not self.deploys:
            raise PlanError("打法里一个部署都没有")
        seen: dict[str, int] = {}
        occupied: dict[tuple[int, int], str] = {}
        for i, d in enumerate(self.deploys):
            if d.operator in seen:
                raise PlanError(
                    f"同一个干员被部署了两次：{d.operator}"
                    f"（第 {seen[d.operator] + 1} 条与第 {i + 1} 条）。"
                    f"要再上一次得先撤退，本版不支持同一人的二次部署")
            seen[d.operator] = i
            # 同一格放两个人：模拟器**不校验**，会安静地让两个单位重叠，
            # 于是输出一个"看起来对"的结果。必须在这里拦下。
            if d.position in occupied:
                raise PlanError(
                    f"两个干员挤在同一格 {d.position}："
                    f"{occupied[d.position]} 与 {d.operator}")
            occupied[d.position] = d.operator
        known = set(seen)
        for r in self.retreats:
            if r.operator not in known:
                raise PlanError(f"撤退了没部署过的干员：{r.operator}")
        for s in self.skills:
            if s.operator not in known:
                raise PlanError(f"给没部署的干员开技能：{s.operator}")

    # -------------------------------------------------- 存取

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"stage": self.stage}
        if self.title:
            out["title"] = self.title
        out["deploys"] = [d.to_dict() for d in self.deploys]
        if self.retreats:
            out["retreats"] = [r.to_dict() for r in self.retreats]
        if self.skills:
            out["skills"] = [s.to_dict() for s in self.skills]
        if self.notes:
            out["notes"] = self.notes
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Plan:
        if not isinstance(data, dict):
            raise PlanError("打法文件的顶层必须是一个对象")
        raw_deploys = data.get("deploys") or data.get("deploy") or []
        deploys = []
        for i, d in enumerate(raw_deploys):
            if not isinstance(d, dict):
                raise PlanError(f"第 {i + 1} 条部署不是对象")
            name = d.get("operator") or d.get("name")
            pos = d.get("position") or d.get("pos") or d.get("location")
            if not name or pos is None:
                raise PlanError(f"第 {i + 1} 条部署缺 `operator` 或 `position`")
            if len(pos) != 2:
                raise PlanError(f"{name} 的坐标 {pos!r} 不是 [x, y] 两元组")
            deploys.append(DeployOrder(
                operator=name, position=(pos[0], pos[1]),
                direction=d.get("direction") or d.get("facing") or "Right",
                #: ★ 丙方案（PM 2026-09-20 批准）：`skill` 除 int 外还可以是一个对象。
                #: ⚠ 判定只加了一层 `isinstance(..., dict)`：**int 那一路一个字符没动**
                #: ⇒ 24 份夹具（`skill` 全是 int）走的分支与改动前**逐字节同一条**。
                #: ⚠ 这里**不**用 `or 0` 兜 dict：空 `{}` 也是 dict，要让它走到
                #: `_skill_from_json` 里**具名报错**，而不是静默变成「不带技能」。
                skill=(d["skill"] if isinstance(d.get("skill"), dict)
                       else int(d.get("skill") or 0)),
                mastery=int(d.get("mastery") or 0),
                elite=None if d.get("elite") is None else int(d["elite"]),
                level=None if d.get("level") is None else int(d["level"]),
                potential=None if d.get("potential") is None else int(d["potential"]),
                trust=None if d.get("trust") is None else int(d["trust"]),
                module=d.get("module"),
                module_level=(None if d.get("module_level") is None
                              else int(d["module_level"])),
                time=None if d.get("time") is None else float(d["time"]),
                auto_skill=bool(d.get("auto_skill", True)),
            ))
        plan = cls(
            stage=str(data.get("stage") or ""),
            deploys=deploys,
            retreats=[RetreatOrder(r["operator"], float(r["time"]))
                      for r in (data.get("retreats") or [])],
            skills=[SkillOrder(s["operator"], float(s["time"]),
                               int(s.get("slot") or 0))
                    for s in (data.get("skills") or [])],
            title=str(data.get("title") or ""),
            notes=str(data.get("notes") or ""),
        )
        plan.validate()
        return plan

    @classmethod
    def load(cls, path: Path | str) -> Plan:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def dump(self, path: Path | str) -> Path:
        """写出打法。

        坐标是**人手要改的字段**，所以把 `"position": [5, 4]` 压回一行——
        `json.dumps(indent=2)` 会把它拆成四行，读起来很难受。
        """
        text = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        text = _POS_ML.sub(r'"position": [\1, \2]', text)
        p = Path(path)
        p.write_text(text + "\n", encoding="utf-8")
        return p

    # -------------------------------------------------- 简写

    @classmethod
    def quick(cls, stage: str, team: str, **kw: Any) -> Plan:
        """从字符串快速搭一份打法（给回归脚本与自检用）。

        `"圣聆初雪:5,4:Right:3; 德克萨斯:6,3:Right:0"`
        —— 每项 `名字:x,y[:朝向[:技能槽[:专精]]]`，末尾可加 `@时刻`
        （如 `阿米娅:5,2:Left:0@1`），不加就是**按费用自动排**。

        分隔符是 **`;`（或 `|`）而不是逗号**：坐标内部就有逗号，
        用逗号分隔会把 `5,4` 切成两半（这个 bug 真写过一次）。
        """
        deploys = []
        text = team.replace("|", ";").replace("；", ";")
        for chunk in text.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            chunk, _, at = chunk.partition("@")
            when = float(at) if at.strip() else None
            parts = [p.strip() for p in chunk.split(":")]
            if len(parts) < 2:
                raise PlanError(f"看不懂这一项：{chunk!r}；至少要「名字:x,y」")
            xs, _, ys = parts[1].replace("，", ",").partition(",")
            try:
                x_i, y_i = int(xs), int(ys)
            except ValueError:
                # 多半是把干员之间的分隔符写成了逗号（坐标内部就有逗号）。
                # 这里必须给**有指向性**的错误：静默取到一半坐标会产出一个
                # "看着对"的结果，比报错危险得多。
                raise PlanError(
                    f"{parts[0]} 的坐标 {parts[1]!r} 解析不了。"
                    f"干员之间要用 `;` 分隔（如 "
                    f"\"阿米娅:5,2:Left:0; 德克萨斯:4,3:Right:0\"），"
                    f"逗号是留给坐标的") from None
            deploys.append(DeployOrder(
                operator=parts[0], position=(x_i, y_i),
                direction=parts[2] if len(parts) > 2 and parts[2] else "Right",
                skill=int(parts[3]) if len(parts) > 3 and parts[3] else 0,
                mastery=int(parts[4]) if len(parts) > 4 and parts[4] else 0,
                time=when,
            ))
        plan = cls(stage=stage, deploys=deploys,
                   title=kw.pop("title", ""), **kw)
        plan.validate()
        return plan
