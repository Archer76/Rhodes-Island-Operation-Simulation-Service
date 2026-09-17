"""把一份打法（`ak_tactic.plan.Plan`）编译成 MAA copilot JSON。

这是**包内**的导出入口，`tools/export_srx8.py` 与 TUI 结果屏都走它——
先前 `to_maa()` 只长在 `tools/export_srx8.py` 里且写死 `SR-EX-8`，
TUI 想导出就只能复制一份，那是迟早要漂的写法。

官方协议：<https://docs.maa.plus/zh-cn/protocol/copilot-schema.html>

## 四处口径，都是查文档或实测定下来的，别凭直觉改

### 一、`stage_name` 用 **levelId**，不是 code

文档原文：「关卡名，必选。关卡中文名、code、stageId、levelId 等，**只要能保证唯一均可**」。
四选一都行，那就选**唯一**的那个——而 `code` 恰恰不唯一：
关卡索引 4694 条里有 774 条 `#f#` 突袭变体与普通版**共用同一个 code**
（`SR-EX-8` 同时指着 `act54side_ex08` 与它的四星版）。
写 code 会让 MAA 随机挑一个，写 levelId 不会。

### 二、`module` 编号取的是模组**类型字母**

MAA 文档：「1-5 依次对应 χ、γ、α、Δ、β 模组」。
而 `uniequip_table.equipDict` 的 `typeName2` 实际取值**恰好是五个**：

| `typeName2` | 条数 | MAA 编号 |
|---|---|---|
| `X` (χ) | 301 | **1** |
| `Y` (γ) | 181 | **2** |
| `A` (α) | 20 | **3** |
| `D` (Δ) | 6 | **4** |
| `B` (β) | 1 | **5** |

五个对五个，顺序也是文档给的顺序，这条对应关系是钉死的。

**项目原先写的是 `{"X": 1, "Y": 2, "Z": 3}`，两处错**：
`Z` 在 905 条模组里**一次都没出现过**（死项），而 `D` 漏了——
那 6 条全是 `classify == "ok"` 的**普通专属模组**（黑键、艾拉、**逻各斯**、
伊芙利特、薇薇安娜、棘刺），照旧写法它们的模组要求会被静默丢掉。
之所以一直没暴露，是因为撞见过的干员（赤刃明霄陈 X、圣聆初雪 Y、阿斯卡纶 X、望 X）
全落在 X/Y 上。

`A` 与 `B` 那 21 条实测全是 `isSpecialEquip=True`（特限/特勤证章），
会被模组三道门的第②道挡在外面，普通关用不到——但编号照样写对，
免得哪天口径变了又要回来查。

### 三、没有生效模组时**整个省略 `module` 键**

文档说「0 表示不使用模组」，但博士实机确认写 `0` 会让**整份作业不被识别**
（不是忽略这一条要求，是不识别）。省略 = 不作要求，在两种读法下都安全；
写 0 在其中一种读法下会让文件作废。**取安全的那一侧。**

### 四、`difficulty` 按关卡索引的 difficulty 填

`0` 缺省 / `1` 普通 / `2` 突袭 / `3` 两者皆可。
关卡索引里 `NORMAL` → 1、`FOUR_STAR` → 2，与游戏内「普通（三星）／突袭（四星）」同义。

## 未导出

`module_level` 与 `potential` 协议里有字段但标注「保留接口，暂未实现」，
所以照样**写进去**（未来支持时即刻生效），同时把练度写进 `doc.details` 让人能看。

**每次部署的时刻也不导出**，理由见 `to_maa` 的文档：Deploy 动作没有 `time` 字段，
而 MAA 默认的「费用不够就一直等」与本项目排时刻的规则是同一条，
写 `pre_delay` 会把同一段等待算两遍。

## 两版文档的差异（记下来，免得日后对不上）

`docs.maa.plus` 的**发布版**写着「1-5 依次对应 χ、γ、α、Δ、β 模组」、
「0 表示不使用模组」；GitHub `dev` 分支的**开发版**把这些删了，
改成 `requirements` 整块「保留接口，暂未实现」、默认值一律 0。

两者对 `module` 编号的来源都没给别的解释，而数据侧的 `typeName2` 恰是五个取值，
故采信发布版的 1-5 对应关系（见第二节）。至于「0 表示不使用模组」——
博士实机确认写 `0` 会让**整份作业不被识别**，所以本模块一律**省略**该键：
省略 = 不作要求，在两种读法下都安全，是非曲直留给日后验证。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .plan import DeployOrder, Plan

__all__ = [
    "MaaExportError", "MODULE_SLOT", "DIFFICULTY_CODE",
    "module_type", "module_slot", "skill_usage", "difficulty_code",
    "used_operators", "operators_report", "operators_lines", "operators_brief",
    "to_maa",
    "job_dir", "next_index", "write_job", "plan_from_rows",
]


class MaaExportError(RuntimeError):
    """导出时发现数据不足（例如名册里查不到某个干员）。"""


#: 模组类型字母 → MAA 的 `module` 编号。见模块文档第二节。
MODULE_SLOT: dict[str, int] = {"X": 1, "Y": 2, "A": 3, "D": 4, "B": 5}

#: 关卡索引的 difficulty → MAA 的 difficulty。见模块文档第四节。
DIFFICULTY_CODE: dict[str, int] = {"NORMAL": 1, "FOUR_STAR": 2, "EASY": 0}


# ---------------------------------------------------------------- gamedata 懒加载

_UNI: dict[str, Any] | None = None
_BOOK: Any = None


def _uniequip() -> Mapping[str, Any]:
    """`uniequip_table.equipDict`。**惰性加载**——不导出的人不该为此付代价。"""
    global _UNI
    if _UNI is None:
        from .operator import OperatorCalculator
        # `_load_uniequip` 是私有的，但 `tools/squad.py` 与 `tools/roster.py`
        # 早就这么用了；公开一层再改三处的收益不划算，这里随大流。
        _UNI = OperatorCalculator()._load_uniequip() or {}
    return _UNI


def _skill_book() -> Any:
    global _BOOK
    if _BOOK is None:
        from .operator import SkillBook
        _BOOK = SkillBook()
    return _BOOK


# ---------------------------------------------------------------- 逐项判定

def module_type(module_id: str | None,
                uni: Mapping[str, Any] | None = None) -> str | None:
    """模组 id → `typeName2` 那个字母（`X`/`Y`/`A`/`D`/`B`）。

    取不到返回 `None`。**别解析 id 里的数字**：`uniequip_00N_xxx` 的 N
    只是全表序号——赤刃明霄陈 `uniequip_002_chen3` 是 X、
    圣聆初雪 `uniequip_002_sbell2` 是 Y，N 同为 2 而型别不同。
    """
    if not module_id:
        return None
    table = _uniequip() if uni is None else uni
    letter = str((table.get(module_id) or {}).get("typeName2") or "").strip().upper()
    return letter or None


def module_slot(module_id: str | None,
                uni: Mapping[str, Any] | None = None) -> int | None:
    """模组 id → MAA 的 `module` 编号。

    **返回 `None` 时调用方必须把 `module` 键整个省略**，不能写 0——
    见模块文档第三节。
    """
    return MODULE_SLOT.get(module_type(module_id, uni))


def skill_usage(roster: Any, name: str, slot: int) -> int:
    """MAA 的技能用法。

    文档口径：`1` = 好了就用；`0` = 不自动使用（交给 `actions`）；
    并注明「**如果是全自动的技能，填 0**」。
    所以按**技能的触发方式**分流：`AUTO`（自动触发）填 0，游戏自己会开；
    `MANUAL`（手动触发）填 1，让 MAA 点。

    取不到技能信息时返回 1。理由：`1`（好了就用）在"其实该手动"时会
    频繁开技能、结果偏激进；返回 0 则会让一份依赖技能的打法**根本不开技能**，
    是更坏的一侧。
    """
    if not slot:
        return 0
    e = (roster.get(name) if roster is not None else None) or {}
    cid = e.get("char_id") or e.get("charId")
    if not cid:
        return 1
    try:
        for s in _skill_book().for_operator(cid):
            if s.slot == slot:
                # 触发方式不随专精变化，等级参数取什么都一样
                return 0 if s.level(7, 0).auto_trigger else 1
    except Exception:                                     # noqa: BLE001
        return 1
    return 1


def difficulty_code(difficulty: str | None) -> int:
    """关卡索引的 difficulty（`NORMAL`/`FOUR_STAR`）→ MAA 的 difficulty 编号。"""
    return DIFFICULTY_CODE.get(str(difficulty or "").strip().upper(), 0)


# ---------------------------------------------------------------- 用了哪些干员

def _pick(dep: DeployOrder, entry: Mapping[str, Any], key: str,
          roster_key: str | None = None) -> Any:
    """打法自带的练度优先，退回名册。打法必须自足（见 `search.Searcher._plan`）。"""
    v = getattr(dep, key, None)
    if v is not None:
        return v
    return entry.get(roster_key or key)


def used_operators(plan: Plan, roster: Any = None) -> list[dict[str, Any]]:
    """按部署顺序列出**这份打法用到的干员**及其练度要求。

    这是导出时要"写明"的东西。每一项的键：

    `name` / `position` / `direction` / `skill` / `mastery` / `elite` /
    `level` / `potential` / `trust` / `module` / `module_type` / `module_slot` / `time`
    """
    out: list[dict[str, Any]] = []
    for dep in plan.deploys:
        entry = (roster.get(dep.operator) if roster is not None else None) or {}
        mod = _pick(dep, entry, "module")
        out.append({
            "name": dep.operator,
            "position": list(dep.position),
            "direction": dep.direction,
            "skill": int(dep.skill or 0),
            "mastery": int(_pick(dep, entry, "mastery") or 0),
            "elite": _pick(dep, entry, "elite"),
            "level": _pick(dep, entry, "level"),
            "potential": _pick(dep, entry, "potential"),
            "trust": _pick(dep, entry, "trust"),
            "module": mod,
            "module_type": module_type(mod),
            "module_slot": module_slot(mod),
            "time": dep.time,
        })
    return out


def _mod_text(op: Mapping[str, Any]) -> str:
    """一模组一格：`无` / `uniequip_002_wang(X→1) Lv3`。"""
    if not op.get("module"):
        return "无"
    slot = op.get("module_slot")
    slot_txt = f"{op['module_type']}→{slot}" if slot else "编号未定"
    return f"{op['module']}({slot_txt})"


def operators_report(plan: Plan, roster: Any = None) -> list[str]:
    """「这份作业用了哪些干员」的人读表，返回**逐行**（不含表头）。

    导出写进 `doc.details`、TUI 显示在结果屏，用的是同一份文字——
    两处各写一遍必然会漂。
    """
    ops = used_operators(plan, roster)
    if not ops:
        return ["（这份打法里没有部署任何干员）"]
    lines = ["| # | 干员 | 落位 | 朝向 | 技能 | 精英 | 等级 | 潜能 | 模组 | 部署 |"]
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for i, op in enumerate(ops, 1):
        lv = "-" if op["level"] is None else op["level"]
        pot = "-" if op["potential"] is None else op["potential"]
        t = "-" if op["time"] is None else f"{op['time']:.0f}s"
        lines.append(
            f"| {i} | {op['name']} | {tuple(op['position'])} | {op['direction']} "
            f"| {op['skill'] or '—'}{'（专' + str(op['mastery']) + '）' if op['mastery'] else ''} "
            f"| {op['elite']} | {lv} | {pot} | {_mod_text(op)} | {t} |")
    return lines


def operators_lines(plan: Plan, roster: Any = None) -> list[str]:
    """人读的编队清单，**终端用**（纯文本，非 Markdown）。

    与 `operators_report` 同源（都走 `used_operators`），只是排版不同：
    一个进 `doc.details` 给人看，一个给 TUI 的 Static 显示。
    两处各写一遍取数逻辑必然漂，所以取数只此一份。
    """
    ops = used_operators(plan, roster)
    if not ops:
        return ["（这份打法里没有部署任何干员）"]
    out = []
    for i, op in enumerate(ops, 1):
        lv = "-" if op["level"] is None else str(op["level"])
        pot = "-" if op["potential"] is None else str(op["potential"])
        sk = f"技{op['skill']}" if op["skill"] else "技—"
        if op["mastery"]:
            sk += f"专{op['mastery']}"
        t = "" if op["time"] is None else f"   {op['time']:>5.1f}s"
        x, y = op["position"]
        out.append(f"{i}. {op['name']}：({x},{y}) {op['direction']}  {sk}  "
                   f"精{op['elite']} {lv}  潜{pot}  模组 {_mod_text(op)}{t}")
    return out


def operators_brief(plan: Plan, roster: Any = None) -> str:
    """一句话版：`赤刃明霄陈(精2 60 潜2 技3专3)｜圣聆初雪(…)`。"""
    parts = []
    for op in used_operators(plan, roster):
        seg = f"{op['name']}(精{op['elite']} {op['level']}"
        if op["potential"]:
            seg += f" 潜{op['potential']}"
        if op["skill"]:
            seg += f" 技{op['skill']}"
            if op["mastery"]:
                seg += f"专{op['mastery']}"
        seg += ")"
        parts.append(seg)
    return "｜".join(parts) if parts else "（无干员）"


# ---------------------------------------------------------------- 组装

def plan_from_rows(stage_id: str, rows: Sequence[Sequence[Any]],
                   detail: Sequence[Sequence[Any]] | None = None,
                   *,
                   title: str = "") -> Plan:
    """从「`(名字, 落位, 朝向, 技能)` 列表 + 逐次部署明细」构造 `Plan`。

    `tools/export_srx8.py` 老代码用的就是这两个形状，这里做一层适配，
    免得为了导出把那份脚本的扫描逻辑一起改掉。

    `detail` 的每一项是 `(等待秒, 名字, (x, y), 朝向, 技能, 专精, 费用)`。
    **第一个元素是「距上一次部署等了多久」，不是绝对时刻**——`run_srx8.run_plan`
    里就是 `wait = max(0, (费用 − 当前费用) × 回费间隔)`，绝对时刻由调用方累加
    （源码里那句 `now = sum(d[0] for d in detail) + wait` 就是证据）。
    这里替它累加成绝对时刻，因为 `used_operators` 的「部署」那一列给人看的是时刻。
    """
    bykey: dict[tuple[str, tuple[int, int]], Mapping[str, Any]] = {}
    clock = 0.0
    for row in detail or ():
        wait, name, pos, _d, _slot, mastery, _cost = row
        clock += float(wait or 0.0)
        bykey[(str(name), (int(pos[0]), int(pos[1])))] = {
            "time": clock,
            "mastery": int(mastery or 0),
        }
    deploys = []
    for name, pos, direction, slot in rows:
        key = (str(name), (int(pos[0]), int(pos[1])))
        extra = bykey.get(key) or {}
        deploys.append(DeployOrder(str(name), (int(pos[0]), int(pos[1])),
                                   str(direction), skill=int(slot or 0),
                                   mastery=int(extra.get("mastery") or 0),
                                   time=extra.get("time")))
    return Plan(stage=stage_id, deploys=deploys, title=title)


def to_maa(plan: Plan, roster: Any = None, *,
           stage_name: str = "",
           difficulty: str | None = None,
           title: str = "",
           details: str = "",
           minimum_required: str = "v6.0.0") -> dict[str, Any]:
    """组装 MAA copilot JSON。

    `stage_name` 缺省用 `plan.stage`（即 levelId），**这是刻意的**——见模块文档第一节。

    ## 为什么不写每次部署的时刻

    协议里 Deploy 动作**根本没有 `time` 字段**。计时只有两条路：
    条件（`kills`/`costs`/`cost_changes`/`cooling`/`time_elapsed`）与
    `pre_delay`/`post_delay`（毫秒，且是**条件满足之后**才开始计）。

    而 MAA 对 Deploy 的默认行为是「当费用不够时，会一直等待到费用够」——
    与本项目解算时排时刻的规则**是同一条**（`run_srx8.run_plan` 里
    `wait = max(0, (费用 − 当前费用) × 回费间隔)`）。
    所以不写时刻就是对的；写 `pre_delay` 反而会把同一段等待算两遍。
    `used_operators` 里那个 `time` 只用于给人看，不进作业。
    """
    if not plan.deploys:
        raise MaaExportError("这份打法里一个部署都没有，导出没有意义")

    ops = used_operators(plan, roster)
    opers = []
    for dep, op in zip(plan.deploys, ops):
        req: dict[str, Any] = {
            "elite": op["elite"], "level": op["level"],
            # 官方口径：1–7 是技能等级，8/9/10 即专一/专二/专三
            "skill_level": 7 + int(op["mastery"] or 0),
        }
        # 键序保持 elite → level → skill_level → module → potential。
        # **没有生效模组时这个键整个不写**，见模块文档第三节。
        if op["module_slot"]:
            req["module"] = op["module_slot"]
        if op["potential"] is not None:
            req["potential"] = op["potential"]
        opers.append({
            "name": op["name"],
            "skill": op["skill"],
            "skill_usage": skill_usage(roster, op["name"], op["skill"]),
            "requirements": req,
        })

    actions = []
    for dep, op in zip(plan.deploys, ops):
        act: dict[str, Any] = {
            "type": "Deploy", "name": op["name"],
            "location": list(op["position"]), "direction": op["direction"],
        }
        act["doc"] = (f"{op['name']}  技能{op['skill'] or '—'}"
                      f"（专{op['mastery']}）  精{op['elite']} {op['level']}"
                      f"  潜{op['potential']}")
        actions.append(act)
    for r in plan.retreats:
        actions.append({"type": "Retreat", "name": r.operator})
    actions.append({"type": "SpeedUp"})
    actions.append({"type": "SkillDaemon"})

    # 「写明使用了哪些干员」——人读的那一份进 doc.details，机器读的那一份是 opers。
    head = [f"【编队】{operators_brief(plan, roster)}", ""]
    head += operators_report(plan, roster)
    body = details.strip()
    merged = "\n".join(head) + (("\n\n" + body) if body else "")

    out: dict[str, Any] = {
        "stage_name": stage_name or plan.stage,
        "opers": opers,
        "groups": [],
        "actions": actions,
        "minimum_required": minimum_required,
        "doc": {"title": title or plan.title or f"{len(plan.deploys)} 人",
                "details": merged},
    }
    code = difficulty_code(difficulty)
    if code:
        out["difficulty"] = code
    return out


# ---------------------------------------------------------------- 落盘

_SAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def job_dir(guides_dir: Path | str, stage_code: str) -> Path:
    """`<guides>/<关卡名>/`。关卡名取全称（`SR-EX-8`），**不缩写、不转小写**。"""
    return Path(guides_dir) / stage_code


def next_index(d: Path, stage_code: str) -> int:
    """已有序号的最大值 + 1。**按加入顺序编号**，不覆盖已有作业。"""
    if not d.is_dir():
        return 1
    pat = re.compile(rf"^{re.escape(stage_code)}-(\d+)\.json$", re.IGNORECASE)
    ns = [int(m.group(1)) for p in d.iterdir()
          if (m := pat.match(p.name)) and p.is_file()]
    return max(ns, default=0) + 1


def write_job(data: Mapping[str, Any], guides_dir: Path | str,
              stage_code: str) -> Path:
    """写出 `<guides>/<关卡名>/<关卡名>-<序号>.json`，返回路径。

    序号是**追加**的：同一天导出两次会得到 `-1.json` 与 `-2.json`，
    不会把上一份冲掉。作业文件里写着玩家自己的编队，所以 `Guides/`
    在 `.gitignore` 里。
    """
    name = _SAFE.sub("_", str(stage_code).strip()) or "stage"
    d = job_dir(guides_dir, name)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}-{next_index(d, name)}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return p
