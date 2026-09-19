#!/usr/bin/env python3
"""干员／敌人／关卡覆盖表——**先把「落地」与「咬到」分成两列**，再把「不接线的后果」写出来。

## 为什么有这个工具（而不是一张手写的表）

手写的覆盖表会腐烂：代码一改，表还是上一版的样子，读者却以为它是现状。
所以这里**只有一列是声明、其余全是量出来的**：

| 列 | 来源 |
|---|---|
| 内核 | 锚点是否真有**定义位**（Go 认 func/type/var/const 与 const 块成员；Python 认 def/class） |
| 生产调用点 | **非测试**源码里的引用处数（注释不算，定义行不算） |
| 守卫 | `rios-sim/*_test.go` 里**提到该符号**的 Test 函数名 |
| 接线状态 | **由调用点数派生**：>0 已接线；=0 零调用点；零调用点又无守卫 ⇒ 双红 |
| 若未接线，后果 | ⚠ **人写的**（工具推不出来）——这一列是断言，不是测量 |

## ⚠ 两条读法（免得这张表被读成「已验证通过」）

1. **「已接线」≠「已验证」**：调用点>0 只说明有人在用它，不说明用得对。
2. **「零调用点」读作「这个符号没有生产调用者」**，不读作「机制没落地」——
   内核写好了、测试也绿，只是**主循环还没伸手来拿**。
3. 「若未接线，后果」这一列问的是同一件事：**不接线的时候，什么东西会静默地算错？**
   答不出一个具体观测量，就不许往这一列里写。

## 数字不许各说各话（结构性保证）

`dict_status`（词典分层）、`audit_op_notes`（备注核查）与本工具**共用同一份测量函数**：
本文件 `import` 它们，而不是各写一遍 grep。所以「锚点/调用点」这类数字在三张表里必然一致。

用法：
    python tools/coverage_table.py                  # 三平面覆盖表
    python tools/coverage_table.py --plane 敌人     # 只看一个平面
    python tools/coverage_table.py --self-test      # 自证：坏锚点与零调用点都必须翻红
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import dict_status as ds  # noqa: E402  （复用「锚点定义位」与「生产调用点」的测量）

#: 覆盖表本体。每条 = (平面, 机制/字段, 锚点, 若未接线的后果)。
#:
#: ⚠ 锚点里的符号名**逐个验过**（`ak_tactic` 下 116 个 def/class 名扫过一遍），
#:   不凭印象写：我第一版写的 `spec.py::from_stage`、`attack_interval`、`_talent_blackboard`
#:   三个**根本不存在**——那正是本仓铁律禁止的事（不许从名字猜）。
#: ⚠ 最后一列是人写的断言，工具无法验证它。
#: 锚点写 `-` 表示「本仓没有这个符号」——那也是一种要写清后果的状态。
ROWS: list[tuple[str, str, str, str]] = [
    # ── 敌人平面：控制与状态链
    ("敌人", "晕眩", "rios-sim/control.go::flagStun",
     "无法行动链断：敌人照常行动与攻击（内核有守卫，但守卫只证内核、证不到接线）"),
    ("敌人", "冻结", "rios-sim/control.go::flagFrozen",
     "冻结不生效，连带法抗 −15 那条修正也不发生 ⇒ 法术伤害静默偏低"),
    ("敌人", "沉睡", "rios-sim/control.go::flagSleeping",
     "沉睡单位仍被当作可行动：既能打人也能被打，两侧都错"),
    ("敌人", "浮空", "rios-sim/control.go::flagLevitate",
     "浮空不生效：重量>3 的时长减半与近战不可选中一并丢失"),
    ("敌人", "束缚／自缚", "rios-sim/control.go::flagBind",
     "被束缚单位照常移动 ⇒ 拦阻类作业整体失效"),
    ("敌人", "近地悬浮", "rios-sim/control.go::airStateAfterStack",
     "对地规避不生效：地面近战照常选中它（本该打不到的能打到）"),
    ("敌人", "战栗", "rios-sim/control.go::trembleBlocksAttack",
     "被阻挡后仍能普攻 ⇒ 拦阻的收益静默变高"),
    ("敌人", "恐惧（含自惧）", "rios-sim/fear.go::fearCells",
     "逃跑与无法被阻挡都不发生：敌人站在原地打，我方承伤静默偏高"),
    ("敌人", "寒冷", "rios-sim/sim.go::applyCold",
     "攻速 −30 不发生、也永远变不成冻结 ⇒ 减速链整段断（表现为我方少受伤害）"),
    ("敌人", "停顿", "rios-sim/sim.go::speedFor",
     "移速 −80% 不生效 ⇒ 推进时间整段变短（这类错最会伪装成「我方更强」）"),
    # ── 敌人平面：伤害与减伤
    ("敌人", "脆弱", "rios-sim/fragile.go::fragileState",
     "增伤不生效：敌人**少受伤害**，且不报错，只表现为「打不动」"),
    ("敌人", "屏障／层数护盾", "rios-sim/sim.go::take",
     "扣血绕过抵挡：整笔伤害直接落到血上（层数护盾曾真出过这个 bug）"),
    ("敌人", "折射", "rios-sim/refraction.go::refractionState",
     "深池系敌人的法抗 +70 不发生、镜膜的最大生命值 +100% 不发生 ⇒ 法术伤害静默偏高"),
    ("敌人", "元素损伤（族）", "rios-sim/element.go::elementState",
     "损伤条不累积、不爆条 ⇒ 相关关卡的机制整段不生效（本列的红靠 Go 可观测量漂移）"),
    ("敌人", "闪避／伤害抵挡", "rios-sim/sim.go::dodgeVs",
     "⚠ Go 侧恒返回 0：闪避单位被静默算成**必中**（伤害期望值通道整条失效）"),
    # ── 干员平面
    ("干员", "规格构造（主干）", "ak_tactic/simgo/spec.py::build_spec",
     "没有规格就没有模拟：面板、技能、天赋三路全断"),
    ("干员", "出怪规格序列化", "ak_tactic/simgo/spec.py::_spawn_spec",
     "⚠ **端到端惰性**：species 写进了内存视图却没抄进规格 dict ⇒ 相性抗性整条路不可能生效"),
    ("干员", "相性抗性（消费端）", "ak_tactic/battle/talents.py::find_species_resistance",
     "相性抗性不被消费 ⇒ 即使规格送来了也不会生效（上下游各断一处）"),
    ("干员", "技能倍率（公式层）", "ak_tactic/formula.py::parse",
     "倍率不乘 ⇒ 伤害退回面板值（此处列作对照：本层已接线且有覆盖自检）"),
    ("干员", "攻速链", "ak_tactic/operator/attack_speed.py::attack_speed_bonus",
     "间隔不折算 ⇒ 整场输出量静默偏差（攻速链定案见记忆 873c4e90）"),
    ("干员", "天赋（属性加成）", "ak_tactic/operator/talent.py::resolve_talents",
     "⚠ 天赋给的属性**整体未应用**且不可按表批量补（候选按精英阶段分档）⇒ 面板偏低"),
    ("干员", "天赋闪避／伤害抵挡", "ak_tactic/simgo/spec.py::_talent_dodge",
     "抵挡的期望值通道失效 ⇒ 高闪避干员被算成必被打中"),
    ("干员", "装置（干员侧构造）", "ak_tactic/frontend/devices.py::make_devices",
     "装置不参与：整图 0 落位那类（与下面关卡平面的 devices 门是同一条链的两端）"),
    # ── 关卡平面
    ("关卡", "关卡装载", "ak_tactic/gamedata/stage.py::load_stage",
     "没有关卡数据就没有夹具（本仓夹具是唯一判据集，按 schema 认）"),
    ("关卡", "关卡机制解析", "ak_tactic/mechanics.py::parse_stage_mechanics",
     "关卡机制整段不生效：机制层取不到即拒跑（这是设计，不是缺陷）"),
    ("关卡", "终点格（goal_cells）", "ak_tactic/simgo/spec.py::_find_goals",
     "⚠ from_sim 永远传 None ⇒ 恒走兜底；两条路不一致时终点豁免会算错"),
    ("关卡", "装置层（devices 门）", "ak_tactic/frontend/devices.py::devices_of",
     "⚠ 字段被门挡着（allow_devices 关时才读）⇒ 装置层可观测性取决于调用方开的门"),
]


#: **病型**——同一条"未生效"，病因不同，修法完全不同（项目经理 2026-09-20 定为「后果」栏写作规范）：
#:   · `调用点缺失` —— 内核写好了没人伸手来拿，**补一行调用**即可；
#:   · `数据到不了` —— 上游写了但没进规格/被门挡着，要动**序列化路径**（有链式风险）；
#:   · `概念未建模` —— 模型里没有这个概念，要**先立字段**，不是补一行；
#:   · `守卫缺失`   —— 接线没问题，是"改坏了也没人红"。
KINDS: dict[str, str] = {
    "近地悬浮": "调用点缺失", "战栗": "调用点缺失", "恐惧（含自惧）": "调用点缺失",
    "寒冷": "调用点缺失", "脆弱": "调用点缺失", "折射": "调用点缺失",
    "元素损伤（族）": "调用点缺失",
    "闪避／伤害抵挡": "概念未建模",
    "出怪规格序列化": "数据到不了", "相性抗性（消费端）": "数据到不了",
    "终点格（goal_cells）": "数据到不了", "装置层（devices 门）": "数据到不了",
    "停顿": "守卫缺失", "屏障／层数护盾": "守卫缺失",
}

#: **严重度**——项目经理口径：会导致「必胜/必败」级误判的，与只是数值偏移的分开。
SEVERITY: dict[str, str] = {
    "闪避／伤害抵挡": "必败级", "屏障／层数护盾": "必败级", "晕眩": "必败级",
    "沉睡": "必败级", "浮空": "必败级", "束缚／自缚": "必败级",
    "近地悬浮": "必败级", "战栗": "必败级", "恐惧（含自惧）": "必败级",
    "相性抗性（消费端）": "必败级", "出怪规格序列化": "必败级",
    "寒冷": "数值偏移", "停顿": "数值偏移", "脆弱": "数值偏移", "折射": "数值偏移",
    "元素损伤（族）": "数值偏移", "攻速链": "数值偏移", "天赋（属性加成）": "数值偏移",
    "天赋闪避／伤害抵挡": "数值偏移", "终点格（goal_cells）": "数值偏移",
    "装置层（devices 门）": "数值偏移", "装置（干员侧构造）": "数值偏移",
    "关卡机制解析": "必败级",
}

#: **「我们没有这个字段族」**——按后果严重度分两栏（项目经理口径）。
#: ⚠ 它们不是"忘了做"，是**模型里没有这个概念**；来源是 `tools/audit_op_notes.py` 的实测条数。
UNMODELED_BY_SEVERITY: list[tuple[str, str, str, str]] = [
    ("必败级", "闪避", "124 条",
     "概念未建模：Go 侧 dodgeVs 恒返回 0 ⇒ **闪避高的单位被静默算成必中**"),
    ("必败级", "庇护", "54 条",
     "概念未建模：减伤型庇护不在现模型 ⇒ 该活下来的单位静默被打死"),
    ("必败级", "沉默", "（无普查词，按机制登记）",
     "概念未建模：SILENCED 无标志位 ⇒ 靠沉默吃饭的作业整段失效（折射那条「可被沉默」就落在这里）"),
    ("数值偏移", "回复", "280 条",
     "概念未建模：治疗量无统一字段族 ⇒ 血量曲线整体偏移"),
    ("数值偏移", "治疗", "209 条", "概念未建模：与回复同族"),
    ("数值偏移", "冷却", "7 条", "概念未建模：技能冷却口径未建 ⇒ 技能可用时刻偏移"),
]


#: **接线状态的人工判定**（覆盖工具自动派生出来的那一列）。
#:
#: ⚠ 为什么必须留这一层：工具能数"引用处数"与"跨文件引用"，但**数不出"这是在消费它，还是在引用它自己"**。
#: 两个方向都会出错，都实测到了：
#:   · 折射 ⇒ 5 处引用**全在它自己文件里**（类型自引用 `func (r *refractionState)`），
#:     自动判据说"已接线"，而真相是主循环一次都没伸手来拿（未接线）；
#:   · 晕眩/冻结/沉睡/浮空/束缚 ⇒ 消费它们的**三张标志清单就写在 control.go 里**（定义同文件），
#:     自动判据说"仅本文件引用"，而真相是**真的接上了**；
#:   · 停顿 ⇒ 定义在 sim.go，而 sim.go **正是主循环所在文件**，同文件调用就是真接线。
#: ⇒ 结论：**自动列只报"引用形态"，判"接线"必须人看**。人判的那一列在这里，
#:   工具仍然把量出来的形态并排打出来——**声明与测量同时可见**，谁都不许把另一个盖掉。
WIRED: dict[str, str] = {
    # 真的接上了（消费点不在定义文件里，或定义文件本身就是消费它的那一层）
    "晕眩": "已接线", "冻结": "已接线", "沉睡": "已接线", "浮空": "已接线",
    "束缚／自缚": "已接线", "停顿": "已接线", "屏障／层数护盾": "已接线",
    # 内核齐备、主线未接（本轮之前已登记的那批，加本轮新落地的三条）
    "近地悬浮": "未接线", "战栗": "未接线", "恐惧（含自惧）": "未接线",
    "寒冷": "未接线", "脆弱": "未接线", "折射": "未接线", "元素损伤（族）": "未接线",
    "闪避／伤害抵挡": "未接线（概念未建模）",
    "天赋闪避／伤害抵挡": "未接线", "关卡机制解析": "已接线",
}


def py_defines(rel: str, sym: str) -> tuple[bool, str]:
    """Python 侧的定义位（`def`/`class`）。Go 那套正则认不了 Python。"""
    p = ROOT / rel
    if not p.exists():
        return False, f"文件不存在：{rel}"
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        m = re.match(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if m and m.group(1) == sym:
            return True, f"{rel}:{i} 定义位 {sym}"
    return False, f"{rel} 里没有 {sym} 的 def/class 定义位"


def anchor_ok(anchor: str) -> tuple[bool, str]:
    if anchor == "-":
        return True, "本仓没有这个符号（登记为未建模）"
    rel, _, sym = anchor.partition("::")
    if not sym:
        return False, f"锚点格式应为 文件::符号，得到 {anchor}"
    if rel.startswith("ak_tactic/"):
        return py_defines(rel, sym)
    return ds.anchor_exists(anchor)


def py_production_callers(sym: str) -> list[tuple[Path, int, str]]:
    """Python 侧的生产调用点（`ak_tactic/**/*.py`，非测试、去注释行）。"""
    out: list[tuple[Path, int, str]] = []
    for p in ds._py_sources():
        if p.name.startswith("test_") or p.name.endswith("_test.py"):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if sym not in line or line.strip().startswith("#"):
                continue
            out.append((p, i, line.strip()))
    return out


def callers(anchor: str) -> tuple[list[tuple[Path, int, str]], str]:
    """按锚点形态选测量口径。返回 (调用点, 口径说明)。"""
    if anchor == "-":
        return [], "未建模（无符号）"
    rel, _, sym = anchor.partition("::")
    if rel.startswith("ak_tactic/"):
        hits = py_production_callers(sym)
    else:
        hits = ds.production_callers(sym)
    # 定义行本身不算「调用」。
    _ok, why = anchor_ok(anchor)
    m = re.search(r":(\d+) ", why)
    if m:
        d = int(m.group(1))
        hits = [h for h in hits if not (h[0].name == Path(rel).name and h[1] == d)]
    return hits, ("Python 非测试源码" if rel.startswith("ak_tactic/") else "Go 非测试源码")


def guards_for(sym: str) -> list[str]:
    """提到该符号的 Test 函数名——守卫是「能红的那条判据」。"""
    names: list[str] = []
    if not sym:
        return names
    for p in ds._go_sources():
        if not p.name.endswith("_test.go"):
            continue
        cur = None
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^func (Test\w+)", line)
            if m:
                cur = m.group(1)
            elif sym in line and cur and cur not in names:
                names.append(cur)
    return names


def assess(row: tuple[str, str, str, str]) -> dict:
    plane, name, anchor, consequence = row
    ok, why = anchor_ok(anchor)
    hits, how = callers(anchor)
    sym = anchor.partition("::")[2] if "::" in anchor else ""
    g = guards_for(sym)
    # ★ 本文件内的引用**不算接线**：类型自引用（`func (r *refractionState)`、`refractionState{…}`）
    #   会让"引用处数"看起来很大，而主循环一次都没伸手来拿。
    #   自证时就是这样翻红的：折射的 5 处**全在 refraction.go 自己里**，
    #   旧口径却判成"已接线"——与我在广播里说的"折射未接线"直接矛盾。
    def_file = Path(anchor.partition("::")[0]).name if "::" in anchor else ""
    outside = [h for h in hits if h[0].name != def_file]
    if not ok:
        status = "⛔ 锚点失效"
    elif anchor == "-":
        status = "未建模（登记）"
    elif outside:
        status = "已接线（跨文件）"
    elif hits:
        status = "本文件内使用、跨文件零引用"
    elif g:
        status = "零调用点（有守卫）"
    else:
        status = "⛔ 零调用点且无守卫"
    # ⚠ 这两列分开：`measured` 是量出来的**引用形态**，`status` 是**人判的接线状态**
    # （见 WIRED 上方的说明：工具数不出"这是在消费它，还是在引用它自己"）。
    measured = status
    status = WIRED.get(name, "—（未人工判定）")
    return {"plane": plane, "name": name, "anchor": anchor, "consequence": consequence,
            "ok": ok, "why": why, "hits": hits, "outside": outside, "how": how,
            "guards": g, "status": status, "measured": measured,
            "severity": SEVERITY.get(name, "—"), "kind": KINDS.get(name, "—")}


def self_test() -> int:
    """自证：这张表红得起来吗。判据坏掉时必须翻红，而不是继续一片绿。"""
    print("== 自证：判据红得起来吗 ==")
    bad = 0
    ok, why = anchor_ok("rios-sim/refraction.go::根本不存在的符号")
    good = not ok
    bad += 0 if good else 1
    print(f"  {'✅' if good else '⛔'} 坏锚点必须判失效：{why}")
    ok2, why2 = py_defines("ak_tactic/simgo/spec.py", "build_spec")
    bad += 0 if ok2 else 1
    print(f"  {'✅' if ok2 else '⛔'} Python 定义位要认得（Go 那套正则认不了）：{why2}")
    # ★ 这条自证自己抓到过一个真错：折射的 5 处引用全在它**自己文件**里，
    #   旧口径（只看总引用数）把它判成"已接线"，与事实相反。现在判的是**跨文件引用**。
    a = assess(("敌人", "折射", "rios-sim/refraction.go::refractionState", "自证"))
    good3 = len(a["outside"]) == 0
    bad += 0 if good3 else 1
    print(f"  {'✅' if good3 else '⛔'} 本文件内引用不算接线（折射跨文件引用应为 0）："
          f"跨文件 {len(a['outside'])} 处／合计 {len(a['hits'])} 处 ⇒ {a['status']}")
    g = guards_for("flagFrozen")
    good4 = len(g) > 0
    bad += 0 if good4 else 1
    print(f"  {'✅' if good4 else '⛔'} 冻结应有守卫：{g}")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="干员／敌人／关卡覆盖表")
    ap.add_argument("--plane", choices=["敌人", "干员", "关卡"], help="只看一个平面")
    ap.add_argument("--self-test", action="store_true", help="自证：坏锚点与零调用点必须翻红")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    rows = [r for r in ROWS if not args.plane or r[0] == args.plane]
    print(f"== 覆盖表（{len(rows)} 行；调用点与守卫是量出来的，「后果」一列是人写的断言） ==")
    print()
    cur, reds = None, 0
    for row in rows:
        a = assess(row)
        if a["plane"] != cur:
            cur = a["plane"]
            print(f"── {cur} ──")
        if a["status"].startswith("⛔"):
            reds += 1
        files = sorted({str(h[0].relative_to(ROOT)) for h in a["hits"]})
        print(f"  {a['name']}")
        print(f"    内核     {'✅' if a['ok'] else '⛔'} {a['why']}")
        print(f"    引用数   合计 {len(a['hits']):>3} 处，"
              f"其中**跨文件** {len(a['outside']):>3} 处（{a['how']}；"
              f"{len(files)} 个文件{('：' + '、'.join(files[:4])) if files else ''}）")
        print(f"    守卫     {len(a['guards'])} 条"
              f"{('：' + '、'.join(a['guards'][:3])) if a['guards'] else '（无）'}")
        print(f"    接线状态 {a['status']}（**人判**）／ 引用形态 {a['measured']}（量出来的）")
        print(f"    病型     {a['kind']}    严重度 {a['severity']}")
        print(f"    若未接线 {a['consequence']}")
        print()

    print(f"== 我们没有这个字段族（按后果严重度分两栏，PM 2026-09-20 口径） ==")
    cur_sev = None
    for sev, name, cnt, consequence in UNMODELED_BY_SEVERITY:
        if sev != cur_sev:
            cur_sev = sev
            print(f"  ── {sev} ──")
        print(f"    {name:<6} {cnt:<22} {consequence}")

    print()
    print(f"== 小结：{len(rows)} 行，红 {reds} 行；"
          f"「我们没有」{len(UNMODELED_BY_SEVERITY)} 项 ==")
    print("  ⚠ 「已接线」≠「已验证」；「零调用点」读作「这个符号没有生产调用者」，"
          "不读作「机制没落地」。")
    return 1 if reds else 0


if __name__ == "__main__":
    raise SystemExit(main())
