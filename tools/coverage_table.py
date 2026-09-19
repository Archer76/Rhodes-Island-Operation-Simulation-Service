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

## 退出码只认**量出列**（2026-09-19 修）

`rc=1` ⇔ 有行的**量出列**（`measured`）是 `⛔`。⚠ 这里曾经数的是**人判列**（`WIRED`），
而 `WIRED` 的 17 条里没有任何一条以 `⛔` 开头 ⇒ **退出码结构性恒为 0**：
量出列真出「⛔ 零调用点且无守卫」／「⛔ 锚点失效」也不会红，后面所有判据都会"看起来全绿"
（本项目最贵的那类错：**判据看不见所断言之物**）。
修完必须能回答一句「**它红得起来吗**」——`--mutate` 就是那条反向守卫，没有它不算修好。

用法：
    python tools/coverage_table.py                  # 三平面覆盖表
    python tools/coverage_table.py --plane 敌人     # 只看一个平面
    python tools/coverage_table.py --mutate anchor  # 反向守卫：注入坏锚点 ⇒ 必须 rc=1 并点名
    python tools/coverage_table.py --mutate zero    # 反向守卫：注入"零调用点且无守卫" ⇒ 必须 rc=1 并点名
    python tools/coverage_table.py --self-test      # 自证：坏锚点与零调用点都必须翻红

⚠ 输出含非 ASCII（`✅`／`⛔`）⇒ **重定向到文件**时 Windows 默认 GBK 编码会在打印第一个
符号时就抛 `UnicodeEncodeError`（实测 `rc=1`、输出从第 4 行截断）。本工具在 `main()` 入口
自己 reconfigure 成 UTF-8，**不依赖调用方记得设 `PYTHONIOENCODING`**——默认值比纪律可靠。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
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
    ("敌人", "冻结", "rios-sim/sim.go::runSim",
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
    ("敌人", "停顿", "rios-sim/sim.go::runSim",
     "【停顿】＝拦移动、**不禁攻击**（原版 `unit.py:1533` 早退）不生效 ⇒ 敌人该停不停、推进时间整段变短"),
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
    # ⚠ 2026-09-20 改值（PM 裁定）：这四位是 `control.go` 位图族成员，穷举证据是**整族零消费点**
    #   （见下方 `ZERO_CONSUMER_FAMILY`）。原值「已接线」是**自己知道是假的栏位**——
    #   PM：假栏位比没栏位更糟，它会对下一个人持续撒谎 ⇒ 一律改成「未接线」。
    #   ⚠ 「冻结」**不在此列**：它的**行级**量是 `sim.go:175 freezeTimer`（秒），有真实消费点
    #   （`:732`/`:739`/`:761`，写方 `mech/mech.go:311`），所以该行仍判「已接线」；
    #   位图那一位 `control.go:31` 归入下面那条**独立事实**，不折进行级判定。
    "晕眩": "未接线", "沉睡": "未接线", "浮空": "未接线", "束缚／自缚": "未接线",
    "冻结": "已接线", "停顿": "已接线", "屏障／层数护盾": "已接线",
    # 内核齐备、主线未接（本轮之前已登记的那批，加本轮新落地的三条）
    "近地悬浮": "未接线", "战栗": "未接线", "恐惧（含自惧）": "未接线",
    "寒冷": "未接线", "脆弱": "未接线", "折射": "未接线", "元素损伤（族）": "未接线",
    "闪避／伤害抵挡": "未接线（概念未建模）",
    "天赋闪避／伤害抵挡": "未接线", "关卡机制解析": "已接线",
    # ── 2026-09-19 补：干员／关卡平面的 10 行（此前是「—（未人工判定）」）──
    "规格构造（主干）": "已接线",
    "出怪规格序列化": "已接线",
    "相性抗性（消费端）": "已接线（仅 Python 老引擎／Go 侧无效）",
    "技能倍率（公式层）": "已接线",
    "攻速链": "已接线",
    "天赋（属性加成）": "已接线",
    "装置（干员侧构造）": "已接线",
    "关卡装载": "已接线",
    "终点格（goal_cells）": "已接线（兜底路径恒被执行）",
    "装置层（devices 门）": "未接线（零调用点）",
}

#: ★ **独立事实（不是某一行名的一部分）**：`rios-sim/control.go` 的异常效果**位图族**
#: （`abnormalFlag`：`:28 flagStun`／`:30 flagLevitate`／`:31 flagFrozen`／`:35 flagAsleep`／
#: `:36 flagSleeping`／`:37 flagBind`／`:38 flagSelfBind`）在引擎里**整族零消费点**。
#: 取证四源（互相独立，逐条可追到坐标）：
#:   ① `grep abnormalFlag`（全 `rios-sim/**/*.go` 含测试）**17 处，无一例外落在 `control.go`／`control_test.go`**；
#:   ② `grep '^\s*\w+\s+abnormalFlag'` 只命中 `control_test.go:18` 的局部变量 ⇒ **无任何结构体持有该类型字段**；
#:   ③ 谓词（`blocksAttack:57`／`blocksAbility:66`／`blocksMove:69`／`trembleBlocksAttack:83`／
#:      `canDamageSleepingTarget:111`／`damageVsInvincible:123`／`levitateBuffApplies:191`／
#:      `groundBuffApplies:205`／`heavyDuration:226`／`airStateAfterStack:248`）在非测试代码里
#:      **除自身定义外零调用点**，反向 grep（`flags` 一词／对 `flag*` 的位运算）**全空**；
#:   ④ 引擎自述：`sim.go:1865`（晕眩 `stun_timer` 与闭锁 `locked_timer` 仍未移植）、
#:      `mech/huai_shu_li.go:1379`（只接了 `frozen`）。
#: ⚠ **对照（证明"零"不是扫错了范围）**：`sim.go:174 sluggishTimer`／`:175 freezeTimer` 同族位置
#:   **有真实消费点**（`:732`／`:736-739`／`:760-769`）——同一套方法在有消费点的符号上确实找得到。
#: ⚠ **为什么不折进「冻结」那一行**：一行行名只能指一个量；冻结那行指 `freezeTimer`（秒），
#:   而这条讲的是位图整族（PM 2026-09-20 裁定：「那 17 处零消费点是一个独立发现」）。
ZERO_CONSUMER_FAMILY: tuple[str, ...] = ("晕眩", "冻结", "沉睡", "浮空", "束缚／自缚")

#: ★ **自述栏与依据背离时的登记位**（PM 2026-09-20：「凡表里有自述／状态栏，就必须有判据校验它；
#: 一个没有判据校验的自述栏，长期必然与证据背离」）。规则：`WIRED` 与人判依据在"有没有消费点"
#: 上互相矛盾时——**登记在这里的打印成 ⚠（带出处），未登记的翻 ⛔**。
#: ⚠ 登记不是免罪：登记的每一条都必须是**已上报、等裁定**的，裁定回来后要改值并从这里删掉。
WIRED_PENDING_RULING: dict[str, str] = {
    "闪避／伤害抵挡": "WIRED 写「未接线（概念未建模）」，而依据实测有定义位／消费点／守卫"
                      "（敌人侧 `sim.go:239` 恒 0 且与原版同值）——已上报 PM 待裁（2026-09-20 批次三汇报）",
    "天赋闪避／伤害抵挡": "WIRED 写「未接线」，而依据里有一条已存在的 Go 消费链"
                          "（`wire.go:176-177`→`skill.go:327-338`）——规格侧是否发出非 0 值未核，已上报 PM 待裁",
    "关卡机制解析": "WIRED 写「已接线」，而依据实测**引擎侧零消费**（只有 `cli.py:1686`／`:1691` 命令行通路）"
                    "——「接线」在这一行指什么待 PM 说清（2026-09-20 批次四已报）",
}

#: **人判依据**——每条结论必须能追回"哪一行、哪个符号"（PM 2026-09-19 三态口径）。
#:
#: 为什么单独一栏而不是塞进 `WIRED` 的字符串里：状态要能被程序读（可枚举），依据要能被
#: 人复核（可追回）——两者混在一格里，早晚会有人只写状态。**留白本身也要显式**：
#: 没登记依据的行会打印「⚠ 未登记」，而不是安静地空着（空着与"已核对"在输出上同形）。
WIRED_WHY: dict[str, str] = {
    # 本轮（2026-09-19）逐行取证：这 10 行每条都指到具体行号。
    "规格构造（主干）":
        "生产入口直呼：`ak_tactic/simgo/verifier.py:93` spec = build_spec(SpecInputs.from_sim(sim), "
        "allow_devices=True, schedule=schedule, env=env)（同文件 :89 注明「规格必须在跑之前取」）",
    "出怪规格序列化":
        "同文件调用**落在生产调用树里**：`ak_tactic/simgo/spec.py:1190` "
        "spawns = [_spawn_spec(inp, t, sp, routes) for t, sp in inp.stage.timeline()]，"
        "而它就在 build_spec（:1117 起）体内 —— 与「停顿」同型：定义文件正是消费它的那一层",
    "相性抗性（消费端）":
        "唯一消费点在 **Python 老引擎**：`ak_tactic/battle/sim.py:3186` tal = find_species_resistance(op.talents)"
        "（:95 处 import）；Go 侧无消费点（§3.66 实测：哨兵 provider 被调 149 次、species 仍未进规格 dict）"
        "⇒ 对当前 Go 引擎无效",
    "技能倍率（公式层）":
        "`ak_tactic/operator/skill.py:1465` terms = _formula.parse(self.raw_description, self.blackboard)"
        "（技能正文按公式解析）；同族 consumer 还有 enemy_formula.py:880、mechanics.py:441/468。"
        "⚠ 本行「引用数 238」是**子串匹配**的产物（parse 是 argparse／parse_devices 的子串）⇒ 只当上界读",
    "攻速链":
        "`ak_tactic/verify.py:309` aspd = attack_speed_bonus(（verify.py 是生产入口；:32 处 import）",
    "天赋（属性加成）":
        "`ak_tactic/operator/attack_speed.py:83` for t in resolve_talents(char, elite=…, level=…, potential=…)，"
        "该函数被 verify.py:309 调用 ⇒ **攻速那一路**接通。⚠ 本行只判接线；属性加成那一路是否接通未在本轮复核"
        "（「后果」栏那条是前轮断言，不是本行的依据）",
    "装置（干员侧构造）":
        "`ak_tactic/battle/sim.py:525` self._devices = make_devices(stage) → "
        "`ak_tactic/frontend/inputs.py:153` devices=list(_get(\"_devices\", None) or []) → 进规格；"
        "另一条同源路径 `frontend/inputs.py:213`（from_stage，当前只有判据工具在调）",
    "关卡装载":
        "`ak_tactic/verify.py:190` self._stages[stage_id] = load_stage(stage_id, source=self.source)"
        "（:30 处 import）；CLI 另在 `ak_tactic/cli.py:278` 调",
    "终点格（goal_cells）":
        "同文件调用、在 build_spec 体内：`ak_tactic/simgo/spec.py:405` (inp.goal_cells or _find_goals(inp))、"
        ":1220 写进规格 goal_cells。⚠ §3.66：from_sim 永远传 None ⇒ 左边恒假、**兜底恒被执行**"
        "（这是「恒走兜底」，不是「没接线」）",
    "装置层（devices 门）":
        "⛔ **零调用点**：全仓对 devices_of 的提及只有它自己的定义行（`ak_tactic/frontend/devices.py:236`）"
        "与 `__all__` 导出清单（:41）。⚠ 自动列把这个读成「本文件内使用」，而那个「使用」只是把名字列进"
        "导出表 —— **引用 ≠ 消费**的又一例（与折射那条同为假阳性，方向相反）",
    # ── 批次一（2026-09-19 夜，PM 裁定「一次 3~5 条、逐行取证」）──────────────
    #: 写法：**定义位 + 消费点 + 守卫用例名**，三段都要点出行号；某段查不到**就写查不到**，
    #: 绝不写「我读了觉得是这条」。**这一栏只报不判**：写错一条依据比留 ⚠ 更贵——⚠ 至少诚实，
    #: 写错的依据长得像「已核对」。
    "折射":
        "定义位 `rios-sim/refraction.go:54` type refractionState struct（判据原文抄在文件头：深池术师"
        "「法术抗性增加70（可被沉默）」）；**消费点：零**——全仓非测试 `.go` 里 refractionState／"
        "ApplyResistance／Effective 的出现只落在 `refraction.go` 自身（:54/:66/:80/:88/:97/:111），"
        "**没有第二个文件伸手来拿** ⇒ 与本行登记的「调用点缺失」相符；"
        "守卫：`rios-sim/refraction_test.go` 6 例（:11 InactiveAddsNothing、:22 ActiveAddsCallerDelta、"
        ":37 DeltaIsNotHardcoded、:56 SilencedStopsWorking、:71 RecoversWhenModeSaysSo、:90 LatchesWhenModeSaysSo）"
        "。锚点指向的是哪个量：`refractionState` 就是「折射」这个状态本身（类型定义位 :54），本仓没有第二个同名量",
    "脆弱":
        "定义位 `rios-sim/fragile.go:39` type fragileState struct（:44 Add／:52 Tick／:72 Ratio／:100 Apply）；"
        "**消费点：零**——非测试 `.go` 里 fragileState 只出现在 `fragile.go` 自身。"
        "⚠ 有一条**同名假信号**必须在此点明：`rios-sim/mech/snow.go:597/:617` 的 `f.add(cell)` 是"
        "**积雪的田地集合**，与 fragileState 毫无关系——照名字 grep 会把它读成「脆弱已经被消费」"
        "（记忆 1bd38acb 那一族：同名不同义）；"
        "守卫：`rios-sim/fragile_test.go` 6 例（:18 SameNameTakesMaxNotSum、:31 SameNameOrderIndependent、"
        ":44 DistinctNamesAdd、:55 TimersAreIndependent、:74 IgnoresNonPositiveInput、"
        ":86 ApplyLeavesNonPositiveDamageAlone）"
        "。锚点指向的是哪个量：`fragileState` 就是单位身上那一整套脆弱（类型定义位 :39），"
        "⚠ 与积雪的田地集合**同名不同义**（见上），别把两者混成一个量",
    "恐惧（含自惧）":
        "定义位 `rios-sim/fear.go:103` fearCells（同文件 :134 fearTargets／:162 pick／:199 fearOffset／"
        ":219 activeLure）；**消费点：零**——非测试 `.go` 里这些符号只出现在 `fear.go` 自身 "
        "⇒ 与本行登记的「调用点缺失」相符；"
        "守卫：`rios-sim/fear_test.go` 6 例（:14 SectorIsAwayFromSource、:41 SectorCenterIsTheHitPosition、"
        ":58 NoCellsWhenSourceMeetsHitOrIsSelf、:69 CellsApplyAllFourConditions、"
        ":104 TargetsPickLocalThenFallbackAndPermanentRemoval、:139 OffsetIsASquareNotACircle）"
        "。锚点指向的是哪个量：`fearCells` 是「当次恐惧的可达地块池」的建表入口（:103），"
        "逃跑落点与「永久剔除」都由它推出——本行判的就是这一层，不是移动执行的最终落点",
    "寒冷":
        "定义位 `rios-sim/sim.go:2683` func (e *enemy) applyCold(secs float64, friendly bool)"
        "（判据见 :2675「施加【寒冷】秒数；已在寒冷中则转为【冻结】」）；"
        "**消费点：零——而且不是「被门挡住」的那种零**：全仓 `applyCold` 的出现只有定义 :2683、"
        "两处注释（:198/:2675）与 `status_test.go:105/:114/:128/:129`，**生产路径没有任何调用者**；"
        "机制层的 Ctx 接口（`rios-sim/mech/mech.go`）里有 SetEnemyFrozen(:311)、"
        "**没有任何 Cold/ApplyCold** ⇒ 连「机制施加寒冷」的那道门都还不存在；"
        "守卫：`rios-sim/status_test.go` 3 例（:24 ColdSlowsEnemyAttack、:101 ApplyColdConvertsToFreeze、"
        ":126 ApplyColdRejectsNonPositive），另 `res_frozen_test.go:23` 记的是冻结那条复合判据的另一半"
        "（`frozenSnow` 无条件算友方）"
        "。锚点指向的是哪个量：`applyCold` 就是「施加【寒冷】秒数、已在寒冷中则转冻结」的唯一入口（:2683）——"
        "本行判的是这一支，不是积雪那支满层冻结",
    "停顿":
        "★ **本行已按 PM 2026-09-20 的决定程序第 1~2 步改过锚点**（原锚点 `sim.go::speedFor` 指的是邻居）。"
        "**【第一步·这个量是什么，带取证】** 名字「停顿」对应的是 `sluggish_timer`，量纲 **秒**，语义＝"
        "**拦移动、但照样能开火**：原版 `ak_tactic/battle/unit.py:1533-1537`（`advance()` 里"
        "`if self.sluggish_timer > 0 or self.idle_timer > 0: return`，注释原话「【停顿】/【待机】不能移动。"
        "停顿还能开火」）＋ `ak_tactic/battle/sim.py:4101`（「技能附带的【停顿】：不能移动，但照样能开火」）。"
        "置位三处：`sim.py:3819-3821`（高台溅射）、`sim.py:4102-4104`（技能 `control[\"sluggish\"]`）、"
        "`sim.py:2181`（替身切换）；每帧递减 `sim.py:2685-2686`。"
        "⚠ **它不是移速乘法**：乘法那一支是积雪私有的 `speed_multiplier`（`sim.py:1153-1160`）与 `lock_slow` 层表"
        "（`unit.py:1162-1165`）。⇒ 记忆里「停顿＝移速 −80%」那句与原版实现对不上，「停顿＝拦推进、非速度乘法」那句对得上。"
        "**规格送的是哪个量**：`ak_tactic/simgo/spec.py:810-818` `out[\"highland_splash_sluggish\"] = _slu`"
        "（干员规格键名 `highland_splash_sluggish`，单位秒，源自特性 `attack@sluggish`＝0.5s；`traits.py:66-68` 注明精1 该键为 0）。"
        "**【第二步·为什么锚点换成它】** Go 侧的字段 `sim.go:174 sluggishTimer`、递减 `:736-738`、"
        "**真实消费点＝推进闸门 `sim.go:760-769`**（`&& e.sluggishTimer <= 0` 才调 `advance(...)`），"
        "这三段都在 `runSim`（`sim.go:452`）体内；唯一写入点 `sim.go:2143`（干员高台溅射取 max）。"
        "⚠ **没拿 `sim.go::sluggishTimer` 当锚点**：字段不是顶层定义，我实跑判据本体 `anchor_ok()` ⇒ "
        "判「锚点失效」（结构化字段不在 func/type/var/const 之列）——拿它当锚点会制造**永久假红**，"
        "而永久假红会把真正的锚点失效淹掉。"
        "**守卫**：`*_test.go` 里 `sluggish`／`speedFor`／`speedReq` **零命中**（`status_test.go:40` 只有一句"
        "「与 sluggishTimer 同一类」的注释）⇒ 与本行登记的「守卫缺失」相符；**「零覆盖」是这条判据该抓出来的结论，不是麻烦。**",

    # ---- 批次二：control.go 异常效果位图族（2026-09-20）----
    "晕眩":
        "定义位 `rios-sim/control.go:28`（`const` 块 iota 成员，`flagStun`）。"
        "**消费点：零。** 它只作为清单成员出现：`control.go:44`（`maskBlocksAttack`）、`:47`（`maskBlocksAbility`），"
        "判据函数 `blocksAttack` `control.go:57-63`。穷举取证（`grep abnormalFlag` 于全 `rios-sim/**/*.go` 含测试）："
        "**共 17 处命中，无一例外落在 `control.go` 与 `control_test.go`**；且**没有任何结构体持有该类型的字段**"
        "（`grep '^\\s*\\w+\\s+abnormalFlag'` 只命中 `control_test.go:18` 的局部变量）；"
        "`blocksAttack(`／`blocksMove(`／`blocksAbility(` 在非测试代码里**除自身定义外零调用点**；"
        "全仓亦**没有 `stunTimer` 之类的运行期字段**。⇒ 引擎里没有任何一处按「晕眩」判行为。"
        "★ **引擎自己的自述（同一结论的独立来源）**：`rios-sim/sim.go:1865` 写着「晕眩 `stun_timer` 与闭锁 "
        "`locked_timer` **仍未移植**，理由见 `hurt`」；`mech/huai_shu_li.go:1379` 也写着「只接了 `frozen`："
        "Go 侧还没有 down / stun / idle / disarm 这四种」。⚠ 与本表 `WIRED[\"晕眩\"] = \"已接线\"` **冲突**——"
        "按「只登记、不改判据结构」的约定**上报 PM 裁**（我不擅自改那一栏）。"
        "⚠ **同名不同义的假信号**（按名字搜会误读成「这一族已被消费」）：`rios-sim/stealth.go:132` 的 `flags=%d` "
        "打的是**索敌的 `targetFree` 位集**（参数 `f`，`:127-133`），与 `abnormalFlag` 无关——"
        "与 `mech/snow.go:597` 的 `f.add(cell)` 是同一族陷阱（关键记忆 `1bd38acb`）。"
        "**守卫**：`control_test.go:15 TestAbnormalFlagListsAreExact`（三张清单逐项相等＋反向「不得多一位」）、"
        "`control_test.go:56 TestFlagListsAreNotNested`（`:64-68` 专门断言晕眩**不属于**阻止移动清单）。"
        "锚点指向的是哪个量：`flagStun` 是「晕眩」在**清单位图**里的那一位（成员身份），**不是**运行期状态量——"
        "本行判的是「这一位在不在清单里」，引擎有没有真的按它拦人，本行覆盖不到。",
    "冻结":
        "★ **这一行判的是哪个量（PM 2026-09-20 要求写明）：判的是 `rios-sim/sim.go:175 freezeTimer`（单位：秒）"
        "——不是 `control.go` 的位图。** 下一批的人若只读锚点与行名，请从这句话起读。"
        "定义位（位图那一位）`rios-sim/control.go:31`（`flagFrozen`）——**定义了、查无消费点**："
        "与晕眩同一次穷举（`abnormalFlag` 全仓 17 处、无字段持有、谓词零调用点、反向 grep 全空）⇒ "
        "该位本身零消费点，**归入独立事实 `ZERO_CONSUMER_FAMILY`，不参与本行的行级判定**（PM 裁定：一行行名只能指一个量）。"
        "**本行的行级消费点（有）**：锚点函数 `rios-sim/sim.go::runSim` 体内——`sim.go:732`"
        "（`frozenLatched = e.freezeTimer > 0 || e.frozenSnow`）、`:739`（递减）、`:761`（推进闸门 `frozenLatched`）；"
        "字段 `sim.go:175 freezeTimer`（＋`:759 frozenSnow`）；"
        "写入入口 `rios-sim/mech/mech.go:311 SetEnemyFrozen`（积雪那一侧调用 `mech/snow.go:452-454`）；"
        "抗性下调那一支见 `sim.go` 的 `frozenResDown`（`d7d8319` 21:26）。"
        "★ **已接线的两个来源（各带坐标）**：① **积雪满层**：`mech/snow.go:420-423` 判据 → `:452-454 SetEnemyFrozen`；"
        "② **天赋自冻结**：`sim.go:3049-3058`（`BlessingSave` 免死那一下把 `spec.BlessingSelfFreeze` 写进 `o.freezeTimer`），"
        "形别 `sim.go:2706 e.freezeFriendly = friendly`、消费 `sim.go:2672 friendlyFrozen()`。"
        "⚠ **同一天赋的另一半被自述为未移植**：`rios-sim/wire.go:154-156`（「触发时冻结攻击范围内全体敌人 N 秒"
        "（黑板 `c2e_freeze`）——**未移植**：Go 侧还没有敌人冻结状态…两边不必一致」），原版对应 `battle/sim.py:3381`"
        "（`blessing_save = bless.value(\"c2e_freeze\", 0.0)`，精2 为 8.0）＋ `sim.py:1069-1090` 的消费。"
        "⇒ 这条自述给出的**理由**（「Go 侧还没有敌人冻结状态」）与 `sim.go:179 freezeTimer`／`mech/mech.go:311` 的存在"
        "**已经对不上**；`c2e_freeze` 那一半现在到底接没接，**本批未核**，登记为未核 + 上报（不擅自改注释、不改引擎）。"
        "**守卫**：`res_frozen_test.go:15 TestFrozenResistanceDownFifteen`、`:50 TestFrozenResistanceOnlyForFriendlyFreeze`；"
        "`status_test.go:48 TestFrozenLowersEnemyRes`、`:80 TestHostileFreezeGivesNoResDown`、`:136 TestApplyFreezeTakesMax`；"
        "位图那一侧 `control_test.go:15`。"
        "锚点指向的是哪个量：**锚点已按 PM 2026-09-20 裁定换成消费点所在的函数** `rios-sim/sim.go::runSim`"
        "（消费点在它体内 `:732`／`:739`／`:761`）；而 `control.go:31 flagFrozen` 那一位**定义了、查无消费点**，"
        "已移进本依据（并归入独立事实 `ZERO_CONSUMER_FAMILY`）——**改后锚点与行名指同一个量：`freezeTimer`（秒）**。",
    "沉睡":
        "定义位 `rios-sim/control.go:36`（`flagSleeping`）；⚠ 与 `control.go:35 flagAsleep`（小睡）是**两个位**。"
        "**消费点：零**（同穷举）：只出现在 `control.go:41-48` 的清单反向排除项与 `:93 const maskSleeping = flagUnableAction | flagSleeping`，"
        "而 `maskSleeping` 在全仓**只此一处**；沉睡专用判据 `control.go:111 canDamageSleepingTarget`、"
        "`control.go:123 damageVsInvincible` **同样零调用点**。"
        "**守卫**：`control_test.go:107 TestSleepingFlagsAndSleepIsNotNap`（`:113` 断言 `flagAsleep != flagSleeping`、"
        "`:120` 断言 `maskBlocksAttack&flagSleeping == 0`）、`control_test.go:128 TestCanDamageSleepingTarget`。"
        "锚点指向的是哪个量：`flagSleeping` 是「沉睡」在清单位图里的那一位（且与小睡分属两位）；仓里没有字段保存它，"
        "沉睡的**伤害落点判据**被实现成纯函数，同样没有调用方。",
    "浮空":
        "定义位 `rios-sim/control.go:30`（`flagLevitate`）。"
        "**消费点：零**（同穷举）：作为清单成员出现在 `control.go:44`／`:47`／`:50`（三张表**都**含浮空，这是原文特性）；"
        "同族纯函数 `levitateBuffApplies` `control.go:191`、`groundBuffApplies` `:205`、`heavyDuration` `:226`、"
        "`airStateAfterStack` `:248` 在非测试代码里**全部零调用点**。"
        "**守卫**：`control_test.go:15 TestAbnormalFlagListsAreExact`（三张表都含浮空，逐项相等）、"
        "`control_test.go:154 TestLevitateBuffAppliesThreeConditions`、`control_test.go:235 TestAirStateAfterStack`（6 组输入）。"
        "锚点指向的是哪个量：`flagLevitate` 是「浮空」在**阻止攻击／阻止能力／阻止移动三张清单**里的成员位；"
        "⚠ 本行**未覆盖**「浮空相对 PRTS 行动方式整页原文」那三处历史缺口（已持有浮空／缚地镜像／四分之一累乘）"
        "现在的状态——本批**没有复核**，登记为未核，别把这一行读成「浮空已对齐原文」。",
    "束缚／自缚":
        "定义位 `rios-sim/control.go:37`（`flagBind` 束缚）与 `control.go:38`（`flagSelfBind` 自缚）——**两个位**，本行是族名。"
        "**消费点：零**（同穷举）：作清单成员出现在 `control.go:50 maskBlocksMove = flagBind | flagSelfBind | flagFrozen | flagLevitate`，"
        "判据 `control.go:69 blocksMove`（零调用点）。"
        "⚠ 引擎里真正会**拦推进**的是另一个量：`sim.go:174 sluggishTimer`（停顿）——见上一行；"
        "与「自缚」相邻的**唯一活接线**是怀黍离那一支：`mech/huai_shu_li.go:362 SelfBind`（规格键 `self_bind`）→ "
        "`:384 idleTimer: diver.SelfBind`，那是**待机**通道，**我不主张它等于自缚**（只登记坐标）。"
        "**守卫**：`control_test.go:15 TestAbnormalFlagListsAreExact`（阻止移动 4 项逐项相等＋反向不许多项）、"
        "`control_test.go:56 TestFlagListsAreNotNested`（`:57-59` 断言阻止移动**不是**阻止攻击的子集——束缚/自缚只住在移动那张表里）。"
        "锚点指向的是哪个量：`flagBind` 是「阻止移动」清单里束缚那一位（自缚是紧邻的另一位）；"
        "本行判的是「这两位在不在移动清单里」，不判「引擎有没有真的拦住谁」。",

    # ---- 批次三：近地悬浮／战栗／屏障·层数护盾／元素损伤／闪避·伤害抵挡（2026-09-20）----
    "近地悬浮":
        "定义位 `rios-sim/control.go:248`（`func airStateAfterStack(originallyFlying bool, levitateBuffs, groundBuffs int) airKind`）；"
        "同族纯函数 `levitateBuffApplies` `control.go:191`、`groundBuffApplies` `:205`、`heavyDuration` `:226`。"
        "**消费点：零**（复核：这四个符号在 `control.go` **之外全空**）。"
        "**守卫**：`control_test.go:235 TestAirStateAfterStack`（6 组输入，`:237-254`）、"
        "`control_test.go:154 TestLevitateBuffAppliesThreeConditions`。"
        "锚点指向的是哪个量：`airStateAfterStack` 回答「浮空／缚地叠加之后这只单位**最终**是空中还是地面」（返回 `airKind`）"
        "——即「近地悬浮／浮空／缚地三者叠加」这条纯判据；**它没有调用方**，引擎里没有任何单位状态由它决定。"
        "⚠ 族名拆法：本行＝**叠加后的行动方式**，与「浮空」行（那是清单位图的成员位）**不是同一个量**，两行别互相顶替。",
    "战栗":
        "定义位 `rios-sim/control.go:83`（`func trembleBlocksAttack(trembling, blocking bool) bool`），语义写在 `:81-84`："
        "只回答「这一击能不能出手」，**不负责取消已经出手的那一击**。"
        "**消费点：零**（`trembleBlocksAttack(` 在 `control.go` 之外全空）。"
        "**守卫**：`control_test.go:95 TestTrembleBlocksAttackOnlyWhileBlocking`（三组合：`:96` 无战栗被阻挡照样打、"
        "`:99` 有战栗没被阻挡照常打、`:102` 战栗＋被阻挡 ⇒ 禁普攻）。"
        "⚠ **守卫错位（登记，不改）**：`control_test.go:85 TestTrembleNotInTheAttackList` **名字说战栗、断言却全打在 `flagStun` 上**"
        "（`:87` 前置、`:90 blocksAttack(flagStun, …)`）——战栗位（`flagPalsyShake`）的清单归属其实由 "
        "`control_test.go:15`（正向 `:22-23` ＋ 反向 `:39-41`）覆盖；按「判据改动归 PM」的约定只登记。"
        "⚠ 相邻实现的同名风险：`rios-sim/palsy.go` 有整套「麻痹震颤」（守卫 `palsy_test.go` 8 例，`:19/:37/:60/:99/:116/:128/:160`），"
        "但**它不引用 `flagPalsyShake`**（该 flag 在非测试代码里只出现在 `control.go:45`／`:48` 的清单里）⇒ 两套并存；"
        "**它们是不是同一个量，我不判**——**登记状态：未裁**（只登记坐标，请 PM／博士裁；⚠ **不许读成「已知无害」**，"
        "PM 2026-09-20 明确要求这一条按「未裁」登记——「两套并存是不是同一个量」正是待裁的那件事）。"
        "锚点指向的是哪个量：`trembleBlocksAttack` 是「战栗＋被阻挡 ⇒ 禁普攻」这条纯函数判据。",
    "屏障／层数护盾":
        "锚点 `rios-sim/sim.go::take` 是**干员掉血的唯一入口**（`func (o *operator) take` `sim.go:2984`）。"
        "**本行是族名，按可独立取证拆两半**："
        "**① 层数护盾（次数制，已接线）**：字段 `sim.go:398-404`（`shieldLayers`／`shieldMaxLayers`／`shieldBreaks`／"
        "`shieldTimer`／`shieldInterval`／`shieldBreakHeal`／`shieldBreakSP`）；部署清零与取规格 `sim.go:600-611`、"
        "每 N 秒加层 `sim.go:615-618`；**另一个授予点 `skill.go:75`**；**伤判消费点 `sim.go:2992-2994`**"
        "（`if o.shieldLayers > 0 && amount > 0 { o.shieldLayers--; o.shieldBreaks++ }`）。"
        "规格 `wire.go:365-377 ShieldSpec`（5 键；`:361-364` 说明**送比例不送绝对值**的理由）。"
        "Python 侧（我自己 grep 核过，不用 Go 注释里的引用）：`battle/sim.py:3127-3168`（`shield_layers_on_deploy` `:3137`／"
        "`shield_interval` `:3140`／`shield_break_heal = ratio × max_hp` `:3142`／`shield_break_sp` `:3143`／加层 `:3150-3152`／"
        "节拍 `:3167-3168`）、`sim.py:3207`（⚠ `shield_layers` 是**一个**字段、不分来源）、另一改写点 `sim.py:3229-3233`、伤判侧 `unit.py:437`。"
        "**② 屏障（按生命上限比例吸收、可衰减）**：Python 有——`battle/sim.py:1672`（按最大生命折算、在血量之前被消耗）、"
        "`_grant_barrier` `sim.py:2073`、`_grant_decay_barrier` `sim.py:2087-2104`、`_barrier_decay_tick` `sim.py:2106-2114`"
        "（每秒衰减＝初始量/30）、授予调用点 `sim.py:1788-1790`／`:2496-2498`、节拍 `sim.py:2787`、字段 `unit.py:379`、"
        "语义边界 `unit.py:388`（衰减到 0 不算破裂）。**Go 侧：零**——`grep -i barrier` 于全 `rios-sim/**/*.go`（含测试）"
        "**命中 0 处** ⇒ 族里这一条在 Go 侧**不存在**（不是「没接线」，是**没有这个量**）。"
        "**守卫**：Go 侧**零**（`^func Test\\w*Shield\\w*` 零命中）⇒ 与本行 KINDS「守卫缺失」相符；"
        "Python 侧判据在 `tools/check_battle.py` 那一套，本行未逐条核。"
        "锚点指向的是哪个量：`take` 是护盾扣层的那个入口；而「屏障」在 Go 侧没有对应量。",
    "元素损伤（族）":
        "定义位 `rios-sim/element.go:236`（`type elementState`），构造 `element.go:248 newElementState(max)`。"
        "**消费点：零（引擎里）**——穷举 `elementState`（全 `rios-sim/**/*.go` 含测试）**26 处命中，全部落在 `element.go` "
        "与 `element_test.go`／`element_blackboard_test.go`**；没有任何其他文件持有它或调用 `newElementState`。"
        "⚠ `element.go:45` 的自述「敌人的构造处 `newElementState(maxEP)`，并把 `damage()` 挂到『攻击附带的元素损伤』上」"
        "是**目标形态不是现状**（构造处没有这一行）⇒ 与本行 KINDS「调用点缺失」相符。"
        "**族按可独立取证拆七支**：① EP 累积与归满 `damage` `:287`、`elementDamage` `:90`、`resolveElementDamage` `:106`；"
        "② 爆发 `elementBurst` `:117` ＋ 两张表 `burstOnEnemy` `:141`／`burstOnOperator` `:187` ＋ `burstDuration` `:472`／`startBurst` `:480`；"
        "③ 冷却 `cooling` `:266`／`anyCooling` `:270`；④ 黑板键族 `epKeyKinds` `:328`／`keyHasEpSuffix` `:334`／"
        "`EpCandidates` `:346`／`ResolveEpAmount` `:368`；⑤ 痕迹 `ElementHit` `:411`／`TraceElement` `:456`；"
        "⑥ 节拍 `tick` `:491`／`current` `:512`；⑦ 入口 `ApplyFromBlackboard` `:431`（内部 `:445 s.damage(k, raw)`）。"
        "**守卫**：`element_test.go:17/:44/:64/:100/:116/:149/:166`（7 例）＋ `element_blackboard_test.go:180`"
        "（另有 5 处直接构造 `:144/:158/:181/:195/:215`）。"
        "⚠ 依据的边界（记忆 `7f782586` 的教训）：**字段清单不能从消费端反推**（抗性是标量、数值是黑板键族 40+ 前缀），"
        "本条只登记已核到的 Go 侧坐标，**不据此推数据侧列名／键名**。"
        "锚点指向的是哪个量：`elementState` 指「**一个实体**的元素值状态」——每种元素一份 EP ＋ 一份爆发冷却。"
        "★ **数据侧取证（按 PM 要求先取数据侧列名／键名／量纲，不从消费端反推；2026-09-20 补）**："
        "数据在 `data/gamedata/raw.githubusercontent.com/excel/`（`skill_table.json` **11,447,137 字节**、"
        "`character_table.json` 14,963,727、`battle_equip_table.json` 5,710,707——三份都在；此前我说的「skill_table.json 缺失」是**搜错了目录**，在此更正）。"
        "键名是**黑板条目的值**（形如 key＝`ep_damage_ratio`、value＝0.1 的条目），**不是字典键**——按字典键遍历会得到 0 个，这是我实测踩到的第一种假空。"
        "实测：`skill_table.json` 命中 **477 条／28 个不同键名**、`character_table.json` **92 条／21 个**、`battle_equip_table.json` **151 条／15 个**；"
        "**值类型全部是 float**（477／92／151 无例外）。量纲实测三态并存：比例型 `ep_damage_ratio`＝0.1、倍率型 `ep_damage_scale`＝1.2、"
        "绝对值型 `ep_damage_value`／`element_damage`＝20.0；抗性是**标量** `ep_damage_resistance`＝0.15；"
        "另有 `ep_heal`（30~60，绝对值）／`ep_recovery_per_sec`（25／75）等非损伤键混在同一前缀族里。"
        "⚠ **键名带宿主限定**（这正是 `7f782586` 说的「两套词表须显式映射」的落点）：实测到 `attack@ep_damage_ratio`（81 条）、"
        "`attack@extra_ep_damage_scale`（30）、`ep_damage_ratio[trigger]`（20）、`ep_damage_ratio_token`（20）、"
        "`botany_s1_extra.ep_damage_ratio`（10）、`sea_drown[ally].ep_damage_ratio`（4）、`ep_damage_ratio_boss`（3）、"
        "`attack@ep_damage_ratio_talent`（4）等。**而 Go 侧只认三种后缀**：`element.go:328 epKeyKinds`＝"
        "`ep_damage_ratio`／`ep_damage_value`／`ep_damage_scale`，匹配规则在 `element.go:334-341 keyHasEpSuffix`"
        "（只认「键名等于后缀」「以 `.后缀` 结尾」「以 `@后缀` 结尾」三种形状）。"
        "⇒ **差集已量出**：`ep_damage_ratio[trigger]`／`[damage]`、`attack@extra_ep_damage_scale`、`ep_damage_ratio_token`／`_m`／`_boss`、"
        "`attack@ep_damage_ratio_talent`／`_win`／`_normal`，以及整个 `element_*` 命名族（`element_atk_scale`／`element_damage_scale`／"
        "`element_multiplier`／`element_type`）**都不在 Go 的候选里**（`EpCandidates` 会静默地看不见它们）。"
        "⚠ **未核（不许读成「已出问题」）**：这些未匹配键**在已放行关卡里是否会真的出现在某次元素损伤的黑板上**，本批没查；"
        "且该族在引擎里本来就零消费点（见上），所以这个差集目前**没有可观测量**——登记为未核 + 上报；不擅自改引擎、不改 `docs/spec-element-fields.md`。"
        "★ **痕迹侧（消费 验收 的 `out/acceptance/trace-key-diff.json`，没另起一套）**：该差集共 **131 个去重键**，"
        "按 `ELEMENT`／`EP.`／`BURST`／`NERVOUS`／`EROSION`／`元素`／`损伤`／`爆发` 八种搜法（中英各搜一遍）"
        "在 `only_a`／`only_b`／`count_diff`／`count_diff_in_window` 四个清单里**命中 0 个** ⇒ 同窗痕迹里**没有任何元素损伤键**。"
        "⚠ 按 `dbee841c`：痕迹没有键**不等于**元素损伤没发生，只说明**痕迹覆盖不到这一族**（两引擎都无键）。",
    "闪避／伤害抵挡":
        "锚点 `rios-sim/sim.go::dodgeVs`（`sim.go:239`）**只是族里的一半**，按可独立取证拆三支："
        "**① 敌人侧闪避**：定义位 `sim.go:239 func (e *enemy) dodgeVs(string) float64 { return 0 }`——**恒 0**；"
        "**消费点有**：`sim.go:1238`（敌人 take）、`:1483`、`:1969`（我方打敌方那一侧）。"
        "⚠ 恒 0 的理由写在 `sim.go:233-238`：原版 `battle/sim.py:3921` 读 `target.dodge_phys + target.talent_dodge_phys`，"
        "而 `EnemyUnit.dodge_phys` 是个**没有任何地方写过**的字段、敌人侧也没有天赋抵挡那一对字段 ⇒ **恒 0 与原版同值**"
        "——这是「两边一致的零」，**必须与「零调用点」分开写**。"
        "**② 我方闪避**：定义位 `rios-sim/skill.go:327 func (o *operator) dodgeVs(damageType string) float64`；"
        "消费点 `sim.go:1319`（机制直伤那一路把 `op.dodgeVs(damageType)` 传进结算）。"
        "规格侧对应 `ak_tactic/simgo/spec.py::_talent_dodge`（本表另一行「天赋闪避／伤害抵挡」的锚点）。"
        "**③ 伤害抵挡（期望值法）**：定义位 `sim.go:3133-3134 func resolveDamage(atk float64, damageType string, scale, defense, res, dodge float64) float64`，"
        "语义 `sim.go:3126`（`dodge` 是受击方针对该伤害类型的闪避比例，**原版把它当期望值**）。"
        "**守卫**：`damage_test.go:13 TestResolveDamageDodge` 四支俱全——`:16` 物理折扣、`:20` 法术各取各的、"
        "`:25` **保底与闪避的次序**（先保底后闪避）、`:30` **真伤不吃闪避**（原版 `damage.py:144`）。"
        "⚠ 本行我表里 KINDS 写的是「概念未建模」，与实测**不符**（有定义位、有消费点、有守卫；敌人侧只是恒 0 且与原版同值）"
        "——**登记冲突、上报 PM 裁**（与批次二 `WIRED` 里「晕眩」那一件同类，我不擅自改那一栏）。"
        "锚点指向的是哪个量：`dodgeVs` 是「这只**敌人**针对某伤害类型的闪避比例」——族名里「闪避」的那一半；"
        "「伤害抵挡」落在 `resolveDamage` 的 `dodge` 参数上，**不在锚点里**。",

    # ---- 批次四（收尾）：天赋闪避／伤害抵挡、关卡机制解析（2026-09-20）----
    "天赋闪避／伤害抵挡":
        "定义位 `ak_tactic/simgo/spec.py:523`（`def _talent_dodge(op, d) -> tuple[float, float]`），"
        "调用点 `spec.py:792`（`talent_phys, talent_arts = _talent_dodge(op, d)`）⇒ 由它写出规格里那一对常驻闪避比例。"
        "**Python 侧的同一个量**：字段 `ak_tactic/battle/unit.py:364-365`（`talent_dodge_phys`／`talent_dodge_arts`）、"
        "写入 `battle/sim.py:3467-3468`、**消费（连乘进伤害）** `sim.py:4255-4256`／`4271-4272`／`4349-4350`／`4357-4358`"
        "（我方出手那几路）与 `sim.py:4718-4719`（敌方打我方那一路），写法一律是 "
        "`dodge_phys = op.dodge_phys + op.talent_dodge_phys`。"
        "**Go 侧的消费链**：规格字段 `rios-sim/wire.go:176-177`（`TalentDodgePhys`／`TalentDodgeArts`，说明 `:170-175`）→ "
        "`rios-sim/skill.go:327-338`（`func (o *operator) dodgeVs`：`:333 skillDodge = p.DodgePhys`、"
        "`:336 talent := o.spec.TalentDodgePhys`、`:338 … TalentDodgeArts`）→ 结算 `sim.go:3133-3134 resolveDamage(…, dodge)`。"
        "**守卫**：Python 侧 `tools/check_battle.py:880 def check_dodge(book)`；Go 侧 `damage_test.go:13 TestResolveDamageDodge`"
        "（四支：`:16`／`:20`／`:25` 次序／`:30` 真伤不吃）。⚠ **Go 测试里 `Dodge` 只命中这一个用例** ⇒ 结算那一步有守卫，"
        "**「天赋闪避这一路接上线」没有专门用例**（登记为守卫空缺，不据此改）。"
        "锚点指向的是哪个量：`_talent_dodge` 是「从天赋取那一对**常驻**闪避比例并交给规格」的那段代码——本行族名拆法："
        "**天赋闪避**＝这一对常驻比例（本题）；**伤害抵挡**＝`resolveDamage` 的 `dodge` 参数（坐标见「闪避／伤害抵挡」行）。"
        "⚠ **未核**：规格侧到底会不会发出非 0 值（要看名册里哪些干员带这对天赋）、以及本表 `WIRED` 该行写的「未接线」"
        "与上面这条已存在的消费链是什么关系——**登记未核 + 上报 PM**，不擅自改那一栏。",
    "关卡机制解析":
        "定义位 `ak_tactic/mechanics.py:280`（`def parse_stage_mechanics(title: str, text: str) -> StageMechanics`）；"
        "同文件另一入口 `mechanics.py:296`（`return parse_stage_mechanics(title, client.wikitext(title))`）。"
        "**消费点：引擎侧（`battle/`、`simgo/`）零**——全 `ak_tactic/**/*.py` 里除 `mechanics.py` 自身外，"
        "只有 `cli.py:1686`（import `stage_mechanics`）与 `cli.py:1691`（`sm = stage_mechanics(args.stage)`）"
        "两处**都是命令行通路**；而类型名 `StageMechanics` 在 `mechanics.py` 之外**零命中** ⇒ 引擎与规格都没有引用它。"
        "**守卫**：`tools/check_mechanics.py`（418 行、7 个 check_：`check_parsing`／`check_glossary`／`check_anchors`／"
        "`check_stage_fields`／`check_precision`／`check_non_effect`／`check_coverage`），其中三处**直接调被测函数**"
        "（`:233`／`:238`／`:248`）。"
        "锚点指向的是哪个量：`parse_stage_mechanics` 就是「把 PRTS 关卡页正文解析成 `StageMechanics`」这个解析器本身，"
        "行名「关卡机制解析」指的就是它。"
        "⚠ 本表 `WIRED` 该行写「已接线」，与上面「引擎侧零消费」并置时**含义不清**（是「解析器能跑且有守卫」还是"
        "「引擎消费它」？两种情况结论相反）⇒ **登记冲突、上报 PM 说清并裁定**，我不擅自改那一栏。",
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
            "wired_why": WIRED_WHY.get(name, ""),
            "severity": SEVERITY.get(name, "—"), "kind": KINDS.get(name, "—")}


def _force_utf8_stdout() -> None:
    """把 stdout/stderr 显式设成 UTF-8。

    ⚠ 为什么写进工具而不是留在 README：实测 `python tools/coverage_table.py > out.txt`
    在 Windows 上 rc=1，前 3 行正常、第 4 行打印 `✅` 时抛
    `UnicodeEncodeError: 'gbk' codec can't encode character '\\u2705'`。
    同类工具（`dict_status.py`、`audit_op_notes.py`）同一毛病，实测都是 rc=1。
    ⇒ 口径：**凡打印非 ASCII 符号的工具，输出重定向时必须 rc=0。**
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")     # type: ignore[union-attr]
        except Exception:                            # noqa: BLE001  （非 TextIOWrapper 时跳过）
            pass


#: **反向守卫的注入行**——退出码只有在"量出列真的能变红"时才可信，这里就是让它变红。
#:
#: 两档对应 `assess()` 里两种 `⛔`：
#:   · `anchor` —— 锚点指向一个不存在的符号 ⇒ 量出列 `⛔ 锚点失效`（与仓库内容无关，永远可注入）；
#:   · `zero`   —— 锚点真存在、但**零生产调用点且零守卫提及** ⇒ `⛔ 零调用点且无守卫`。
#: ⚠ `zero` 那档依赖"仓库里今天恰好有个没人用的符号"（实测 2026-09-19 有 114 个候选，
#:   其中含 `continue` 这类被 `_BLOCK_MEMBER` 误当 const 块成员的假候选）。所以它
#:   **运行时复核**：若那个符号被接线/被加守卫了，本守卫**吼出来并 rc=1**（控制组挑错输入
#:   与判据坏掉是两件事，不许混成一个沉默），维护者换一个没人用的符号即可。
MUTATIONS: dict[str, tuple[str, str, str, str]] = {
    # ⚠ 四元组顺序**与 ROWS 一致**：(平面, 名称, 锚点, 后果)。写反了不会报错——
    #   只会让红行点名时把"平面"和"名字"对调（第一版就这样，输出成「敌人 ⇒ ⛔ 锚点失效」）。
    "anchor": ("敌人", "合成·坏锚点", "rios-sim/control.go::这个符号不存在_CG反向守卫",
               "反向守卫用：锚点失效必须在量出列翻红"),
    "zero": ("敌人", "合成·零调用点无守卫", "rios-sim/control.go::blocksMove",
             "反向守卫用：零调用点且无守卫必须在量出列翻红"),
}


def mutation_precheck(kind: str) -> tuple[bool, str]:
    """注入之前先问一句"这条注入真的会红吗"——挑错输入的控制组是空的。"""
    plane, name, anchor, _ = MUTATIONS[kind]
    ok, why = anchor_ok(anchor)
    if kind == "anchor":
        good = not ok
        return good, (f"{anchor} 现在确实是坏锚点（{why}）" if good
                      else f"控制组挑错输入：{anchor} 居然有定义位（{why}）")
    if not ok:
        return False, f"控制组挑错输入：{anchor} 没有定义位（{why}）"
    hits, _how = callers(anchor)
    g = guards_for(anchor.partition("::")[2])
    if hits or g:
        return False, (f"控制组输入已失效：{anchor} 现在有 {len(hits)} 处生产引用 / "
                       f"{len(g)} 条守卫提及 ⇒ 它不再是「零调用点且无守卫」。"
                       f"请在 MUTATIONS['zero'] 里换一个没人用的符号。")
    return True, f"{anchor} 现在真是零调用点（0 处）且零守卫提及"


#: ★★ **判据纪律的可执行出口**（PM 2026-09-20 00:51 指派）。
#:
#: 两条纪律，**必须能从一次运行的输出里读到**，而不是读注释才知道：
#:   ① **「永久假红＝没有判据」**——一条永远红的判据会把真正的红淹掉
#:      （实例：本工具曾经 `rc` 结构性恒 0；另一例：验收入口的 `roster_identity` 判据
#:      第一版把记录值读成了水位基线 ⇒ `记录值=None` ⇒ **控制组当场没绿**，判据会永久假红）。
#:   ② **控制组是三层守卫里唯一能逮住"空判据"的一层**——敏感性问"能不能红"，
#:      反例问"红得对不对"，**控制组问"该绿的时候绿不绿"**。前两层都可能是空判据，
#:      只有控制组能把"永远红／永远绿"这两类**同时**照出来。
#:
#: 数据来源：`tools/acceptance.py --guard-new-items` 写出的 `out/acceptance/guard-matrix.json`
#: （每条判据三层结论 ＋ 控制组"该绿就绿"那一行原话）。
#: ⚠ **矩阵不在场 ⇒ ⚠ 未测，不翻红**：否则我自己就成了"永久假红"。
#:   **只有"控制组测了但没绿"才计入退出码**——那才是"这个判据可能恒红/恒绿"的硬信号。
GUARD_MATRIX = ROOT / "out" / "acceptance" / "guard-matrix.json"


def guard_discipline(matrix: Path | None = None) -> tuple[list[str], list[str], bool | None]:
    """返回 (要打印的行, 计入退出码的红行, 控制组是否全绿)。`None` ＝ 未测（不翻红）。"""
    path = matrix if matrix is not None else GUARD_MATRIX
    L: list[str] = []
    if not path.exists():
        L.append("  ⚠ **控制组未测**（矩阵不在场：" + str(path) + "）")
        L.append("    ⇒ 取得方式：`python tools/acceptance.py --guard-new-items`"
                 "（它会打印每条判据「该绿就绿」那一行并落盘本矩阵）")
        L.append("    ⇒ **没有控制组，就分不出「真的红」与「永远红」**——本行是 **⚠ 不是 ⛔**："
                 "「我还没测控制组」与「控制组没绿」是两件事，把前者判红，就是新的永久假红。")
        return L, [], None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:                                   # noqa: BLE001
        L.append(f"  ⛔ 矩阵读不出来（{e}）⇒ **有矩阵却读不了**与「没有矩阵」不同：判据在这一层失明")
        return L, [f"guard-matrix 读不出：{e}"], False
    crit = d.get("criteria") or {}
    L.append(f"  矩阵：{path.name}　生成于 {d.get('at')}　判据 {len(crit)} 条")
    reds: list[str] = []
    for k, v in crit.items():
        sens = "✅" if v.get("sensitivity") else "❌"
        cex = "✅" if v.get("counterexample") else "—"
        ctl = "✅ 该绿就绿" if v.get("control") else "❌ **没绿/未测**"
        L.append(f"    {k:<24} 敏感性={sens}　反例={cex}　控制组={ctl}")
        if v.get("control_line"):
            L.append(f"      └ 控制组那一行：{v['control_line']}")
        if not v.get("control"):
            reds.append(f"{k}：控制组没绿/未测 ⇒ **该判据可能恒红或恒绿（空判据）**")
    allgreen = bool(crit) and not reds
    L.append(f"  ⇒ " + ("**恒红可辨**（每条判据的控制组都该绿就绿）" if allgreen else
                        "⛔ **有判据的恒红/恒绿不可辨**——控制组没绿，这条判据不许当成判据用"))
    if not crit:
        L.append("  ⚠ 矩阵为空（一条判据都没有）⇒ 本层没有可判之物，**不是通过**")
    return L, reds, allgreen


def red_names(assessed: list[dict]) -> list[tuple[str, str, str]]:
    """**退出码只认这一列**：量出列（`measured`）为 `⛔` 的行。

    ⚠ 不要改回去数 `status`（人判列）：`WIRED` 里没有以 `⛔` 开头的值，
    数它就等于 rc 恒 0 —— 那正是本次修掉的 bug。

    ★★ **已知边界（PM 2026-09-20 要求留档，不许写成"改值无副作用"）**：
    「本次改值不影响 rc。这说明 `WIRED` 栏的校验目前**不参与退出码判决**；因此"改了值 rc 没变"
    不能读成"改对了"，只能读成"这一栏还没进判决面"。」
    实测出处：2026-09-20 把 `WIRED` 里四位（晕眩／沉睡／浮空／束缚／自缚）由「已接线」改成
    「未接线」后，`--self-test` 的 rc 与判决位 ⛔ 均未变化 —— 只认 `measured` 列是**故意的**
    （人判列混进退出码会让 rc 变成"人有没有填字"，不是"接线对不对"），但**边界必须留档**：
    `WIRED` 的校验目前在自检里是 ⚠ 级（未登记背离），**不是** rc 级。**要不要把它纳入 rc 是设计决定，
    归 PM；在它进判决面之前，任何"改了栏位但 rc 没动"的读数都只证明"这一栏还没进判决面"。**
    """
    return [(a["name"], a["measured"], a["why"]) for a in assessed
            if str(a["measured"]).startswith("⛔")]


def _git(*args: str) -> str:
    """跑一条**只读** git 命令。⚠ 失败一律返回空串——调用方必须把它标成「未知」，
    不许拿一个看起来正常的空白顶上去（身份未知是**可以写出来的状态**）。

    ⚠ **只 rstrip 换行，绝不 strip**：`git status --porcelain` 的每行以两列状态码开头，
    其中"已改未暂存"那一类**首行的第一个字符就是空格**（`" M path"`）。整体 strip 会把
    它吃掉，下游按固定列位切路径时就少一个字符——实测第一版把 `docs/parity-ledger-deepwater.md`
    打印成了 `ocs/parity-ledger-deepwater.md`：**只错第一条**，最容易看漏的那种错。
    """
    try:
        p = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return p.stdout.rstrip("\r\n") if p.returncode == 0 else ""


def tree_head() -> str:
    return _git("rev-parse", "--short", "HEAD") or "未知"


def tree_branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD") or "未知"


def source_dirty() -> tuple[int, list[str]]:
    """工作区脏不脏——**这批数字是在哪棵树上量出来的**。

    口径抄 `tools/parity_ledger.py::source_dirty()`（本仓约定：数 `git status --porcelain`
    的行数），这里多带回文件名：只说"脏了 6 个文件"而不说是哪 6 个，读者没法判断要不要重跑，
    也没法判断脏的是不是自己关心的那几个。
    """
    out = _git("status", "--porcelain")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    #: 前两列是状态码（` M` = 已改未暂存、`??` = 未跟踪），从第 4 个字符起才是路径。
    return len(lines), [ln[3:].strip() for ln in lines]


def _sha16(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def provenance_lines(dirty: tuple[int, list[str]], head: str, branch: str) -> list[str]:
    """来源三件套（仪器身份／来源树／脏污）。

    ⚠ **做成纯函数**是为了能在自检里拿合成输入问它两句："干净时不许报警""脏时必须报警
    并点名到文件"。做成一段直接读磁盘的打印代码，这两句就没人验得了——而"提示恒出现"
    与"提示恒不出现"在输出上都不是错误，只会让读者当成噪音或者当成没事。
    """
    n, names = dirty
    lines = [
        "== 来源三件套（缺一即「身份未知」，不许与别的树混进同一张表） ==",
        f"  仪器     {Path(__file__).name} sha256前16={_sha16(Path(__file__))}；"
        f"测量函数在 {Path(ds.__file__).name} sha256前16={_sha16(Path(ds.__file__))}"
        f"（本工具 import 它，不另写一遍 grep）",
        f"  来源     {ROOT}（分支 {branch}）树 HEAD={head}",
    ]
    if n:
        shown = "、".join(names[:6]) + ("…" if n > 6 else "")
        lines.append(f"  脏污     source_dirty={n}（`git status --porcelain` 行数）"
                     f"⇒ ⚠ 下面的数字是在**未提交的工作区**上量出来的：{shown}")
        lines.append("           ⇒ 要读「入库版本」的数字，先 stash，或对上面每个路径按 "
                     "`git show HEAD:<path>` 重数（本工具不做这件事：那会多出第二份测量实现，"
                     "两份实现迟早各说各话）")
    else:
        lines.append("  脏污     source_dirty=0 ⇒ 下面的数字与树 HEAD 一致")
    return lines


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
    # ★ 退出码的两条：一条证明**红得起来**，一条证明**不是恒非零**（控制组）。
    #   少了任何一条，"rc 可信"都只是我自己的说法。
    mutated = [assess(MUTATIONS["anchor"])]
    got_red = bool(red_names(mutated))
    bad += 0 if got_red else 1
    print(f"  {'✅' if got_red else '⛔'} 注入坏锚点后退出码判据必须变红："
          f"{red_names(mutated) or '（没红 ⇒ 退出码仍然恒 0）'}")
    clean = red_names([assess(r) for r in ROWS])
    good6 = not clean
    bad += 0 if good6 else 1
    print(f"  {'✅' if good6 else '⛔'} 控制组：不打注入时现有 {len(ROWS)} 行必须没有红行："
          f"{clean or '（0 行）'}")
    # ★ 人判列的两条**结构**守卫（不是水位）：
    #   ① 每行都必须有人判结论——「—（未人工判定）」这种留白会让整张表看起来"填完了"；
    #   ② WIRED 里不许残留已不存在的行名——改一次行名就会**静默孤立**一条判定。
    missing = [r[1] for r in ROWS if r[1] not in WIRED]
    good7 = not missing
    bad += 0 if good7 else 1
    print(f"  {'✅' if good7 else '⛔'} 每一行都要有人判结论（不许留白）：缺 {missing or '（0 行）'}")
    orphan = sorted(set(WIRED) - {r[1] for r in ROWS})
    good8 = not orphan
    bad += 0 if good8 else 1
    print(f"  {'✅' if good8 else '⛔'} WIRED 不许有已不存在的行名（改名会静默孤立判定）："
          f"{orphan or '（0 条）'}")
    # ⚠ 依据缺失**不判失败**（那会让自检一上来就红、逼人放宽它），但必须逐条点名：
    #   没登记依据的行在输出里会与"已核对"同形，这正是本项目最贵的那类错。
    noev = [r[1] for r in ROWS if r[1] in WIRED and not WIRED_WHY.get(r[1])]
    print(f"  {'⚠' if noev else '✅'} 已登记可追回依据 {len(ROWS) - len(noev)}/{len(ROWS)} 行"
          f"{('；未登记（前轮判定，本轮未复核）：' + '、'.join(noev)) if noev else ''}")
    # ★★ 上面三条（留白／孤立行名／依据缺失）的**反向守卫**。
    #    PM 2026-09-19 定：「留白 0 行」这条下次还要在——**靠人记着不算在，靠注入才算**。
    #    做法与 --mutate 同型：在**内存副本**上把数据改坏，断言那三条判据真的会红。
    #    ⚠ 它证明的是"检测器在合成输入上有效"，**不证明**真实数据那条路是通的
    #      ——后者的证据是上面 good7/good8 在**真实数据**上的结论，两条一起才算完。
    pop_name = next((r[1] for r in ROWS if r[1] in WIRED), None)
    inj_blank = dict(WIRED)
    if pop_name:
        inj_blank.pop(pop_name)
    miss_inj = [r[1] for r in ROWS if r[1] not in inj_blank]
    good7b = bool(miss_inj)
    bad += 0 if good7b else 1
    print(f"  {'✅' if good7b else '⛔'} 反向守卫：抽掉一条判定后「不许留白」必须点名："
          f"{miss_inj[:1] or '（没红 ⇒ 这条判据红不起来）'}")
    orp_inj = sorted((set(WIRED) | {"这个行名不存在_反向守卫"}) - {r[1] for r in ROWS})
    good8b = bool(orp_inj)
    bad += 0 if good8b else 1
    print(f"  {'✅' if good8b else '⛔'} 反向守卫：塞一个不存在的行名后「不许孤立」必须点名："
          f"{orp_inj or '（没红 ⇒ 这条判据红不起来）'}")
    ev_name = next((r[1] for r in ROWS if r[1] in WIRED and WIRED_WHY.get(r[1])), None)
    if ev_name:
        inj_why = dict(WIRED_WHY)
        inj_why.pop(ev_name)
        ne_inj = [r[1] for r in ROWS if r[1] in WIRED and not inj_why.get(r[1])]
        good11b = ev_name in ne_inj
        bad += 0 if good11b else 1
        print(f"  {'✅' if good11b else '⛔'} 反向守卫：抹掉一条依据后「未登记」必须点名到它："
              f"{ne_inj[:1] or '（没红）'}")
    else:
        print("  ⚠ 依据缺失那条没有可注入的样本（0 行登记了依据）——注入不了，别把它当验过")
    # ★ 已登记的依据必须带**证据坐标**（`file:line`）——这是「可追回」的最低机械判据：
    #   一条写着"我核对过"的依据与一条指向 `rios-sim/fragile.go:39` 的依据在输出上同形，
    #   只有坐标能让人按图索骥。**未登记的行不参与这条**（那是上面那条 ⚠ 的职责，
    #   两者分工＝「有没有人判」与「判了有没有出处」）。
    coord_re = re.compile(r"[A-Za-z0-9_./\\-]+\.(?:py|go|md):\d+")
    registered = {n: w for n, w in WIRED_WHY.items() if n in {r[1] for r in ROWS}}
    no_coord = sorted(n for n, w in registered.items() if not coord_re.search(w))
    good12 = not no_coord
    bad += 0 if good12 else 1
    print(f"  {'✅' if good12 else '⛔'} 已登记的依据必须带证据坐标（file:line）："
          f"{len(registered) - len(no_coord)}/{len(registered)} 条"
          f"{('；缺坐标：' + '、'.join(no_coord)) if no_coord else ''}")
    if registered:
        who = sorted(registered)[0]
        inj_coord = dict(registered)
        inj_coord[who] = "这条依据只有结论、没有坐标"
        nc = sorted(n for n, w in inj_coord.items() if not coord_re.search(w))
        good12b = who in nc
        bad += 0 if good12b else 1
        print(f"  {'✅' if good12b else '⛔'} 反向守卫：抽掉坐标后「必须带坐标」必须点名："
              f"{nc[:1] or '（没红 ⇒ 这条判据红不起来）'}")
    # ★ 来源三件套：**两边都要试**——只试一边的话，"提示恒出现"与"提示恒不出现"都算过。
    clean_txt = "\n".join(provenance_lines((0, []), "abc1234", "main"))
    good9 = ("source_dirty=0" in clean_txt) and ("⚠" not in clean_txt)
    bad += 0 if good9 else 1
    print(f"  {'✅' if good9 else '⛔'} 来源三件套：干净树不许出现脏污警告")
    dirty_txt = "\n".join(provenance_lines((2, ["rios-sim/a.go", "rios-sim/b.go"]), "abc1234", "main"))
    good10 = (("source_dirty=2" in dirty_txt) and ("⚠" in dirty_txt)
              and ("rios-sim/a.go" in dirty_txt))
    bad += 0 if good10 else 1
    print(f"  {'✅' if good10 else '⛔'} 来源三件套：脏树必须报警并点名到具体文件")
    # ★ 计数的自洽：报了个数字就必须列得出对应的名字（数词与清单不一致＝最经典的假账）。
    dn, dnames = source_dirty()
    good11 = dn == len(dnames)
    bad += 0 if good11 else 1
    print(f"  {'✅' if good11 else '⛔'} 脏污计数必须与点名清单一致："
          f"source_dirty={dn}，清单 {len(dnames)} 条")
    # ★★ 独立事实：`control.go` 位图族**整族零消费点**（PM 2026-09-20 裁定「那 17 处零消费点是
    #    一个独立发现，不要折进『冻结』这一行」）。判据落在**真实数据**上：族里除「冻结」外
    #    都不许再写「已接线」，而「冻结」的依据必须写出它判的量是 `freezeTimer`。
    fam_bad = [n for n in ZERO_CONSUMER_FAMILY
               if n != "冻结" and WIRED.get(n, "").startswith("已接线")]
    fam_why = "freezeTimer" in WIRED_WHY.get("冻结", "")
    good14 = (not fam_bad) and fam_why
    bad += 0 if good14 else 1
    print(f"  {'✅' if good14 else '⛔'} 位图族零消费点（独立事实）必须与状态栏一致："
          f"族 {len(ZERO_CONSUMER_FAMILY)} 位，仍写「已接线」的 {fam_bad or '（0 位）'}"
          f"；「冻结」依据写明判 `freezeTimer`：{'有' if fam_why else '没有'}")
    inj_fam = dict(WIRED)
    inj_fam["晕眩"] = "已接线"
    fam_bad_inj = [n for n in ZERO_CONSUMER_FAMILY
                   if n != "冻结" and inj_fam.get(n, "").startswith("已接线")]
    good14b = bool(fam_bad_inj)
    bad += 0 if good14b else 1
    print(f"  {'✅' if good14b else '⛔'} 反向守卫：把位图族某一位改回「已接线」必须翻红："
          f"{fam_bad_inj[:1] or '（没红 ⇒ 这条判据红不起来）'}")

    # ★★ 自述／状态栏的**双向**判据（PM 2026-09-20 定：「凡表里有自述／状态栏，就必须有判据
    #    校验它——一个没有判据校验的自述栏，长期必然与证据背离」，起因就是本表的 `WIRED["晕眩"]`）。
    #    ⚠ 用的是**行级用语**：`消费点：零` 表示"这一行指的那个量零消费"；位级／子项的零
    #      （如冻结位 `control.go:31`、屏障在 Go 侧不存在）故意用别的词写，免得两件事混判。
    #    ⚠ 已上报等裁定的背离登记在 `WIRED_PENDING_RULING`：那些打印成 ⚠（带出处）而不是 ⛔
    #      ——登记不等于通过，裁定回来要改值并把它删掉。
    row_zero = "消费点：零"
    zero_marks = ("消费点：零", "零消费点", "零调用点", "跨文件零引用")

    def desc_mismatch(table: dict[str, str]) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for row in ROWS:
            nm = row[1]
            ev = WIRED_WHY.get(nm, "")
            st = table.get(nm, "")
            if not ev or not st:
                continue
            if st.startswith("已接线") and row_zero in ev:
                out.append((nm, "状态写「已接线」而依据写「消费点：零」"))
            elif st.startswith("未接线") and not any(m in ev for m in zero_marks):
                out.append((nm, "状态写「未接线」而依据里没有零消费点的取证"))
        return out

    desc_mism = desc_mismatch(WIRED)
    desc_unreg = [m for m in desc_mism if m[0] not in WIRED_PENDING_RULING]
    good15 = not desc_unreg
    bad += 0 if good15 else 1
    print(f"  {'✅' if good15 else '⛔'} 自述栏与依据必须一致（双向）：未登记的背离 {len(desc_unreg)} 处"
          f"{('；' + '；'.join(f'{n}（{w}）' for n, w in desc_unreg)) if desc_unreg else ''}")
    if WIRED_PENDING_RULING:
        print(f"    ⚠ 已上报等裁定 {len(WIRED_PENDING_RULING)} 处"
              f"（**不算通过**，也不翻红）：{'、'.join(WIRED_PENDING_RULING)}")
    inj_a = dict(WIRED)
    inj_a["近地悬浮"] = "已接线"
    got_a = [m for m in desc_mismatch(inj_a) if m[0] == "近地悬浮"]
    bad += 0 if got_a else 1
    print(f"  {'✅' if got_a else '⛔'} 反向守卫（方向一：状态说「已接线」／依据说零）必须翻红："
          f"{got_a[:1] or '（没红 ⇒ 这条判据红不起来）'}")
    inj_b = dict(WIRED)
    inj_b["停顿"] = "未接线"
    got_b = [m for m in desc_mismatch(inj_b) if m[0] == "停顿"]
    bad += 0 if got_b else 1
    print(f"  {'✅' if got_b else '⛔'} 反向守卫（方向二：状态说「未接线」／依据无零取证）必须翻红："
          f"{got_b[:1] or '（没红 ⇒ 这条判据红不起来）'}")
    return 1 if bad else 0


def main() -> int:
    _force_utf8_stdout()
    ap = argparse.ArgumentParser(description="干员／敌人／关卡覆盖表")
    ap.add_argument("--plane", choices=["敌人", "干员", "关卡"], help="只看一个平面")
    ap.add_argument("--self-test", action="store_true", help="自证：坏锚点与零调用点必须翻红")
    ap.add_argument("--mutate", choices=sorted(MUTATIONS) + ["guardctl"],
                    help="反向守卫：注入一条量出列必定为 ⛔ 的行，退出码必须变非 0 并点名；"
                         "`guardctl` 注入一份**控制组没绿**的守卫矩阵，判据纪律那一节必须翻红")
    ap.add_argument("--guard-matrix", help="判据纪律用的三层守卫矩阵路径（缺省读 out/acceptance/guard-matrix.json）")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    rows = [r for r in ROWS if not args.plane or r[0] == args.plane]
    if args.mutate == "guardctl":
        # ★★ 判据纪律的反向守卫（PM 2026-09-20 00:51 指派的那一条）：**"控制组没绿"必须翻红**，
        #    否则"永久假红"这层纪律自己就是空的（它只会永远打 ⚠ 或永远打 ✅）。
        #    做法与 --mutate 同型：在**内存副本**上把矩阵改坏（控制组翻 false），断言那一节翻 ⛔。
        import copy as _copy
        _src = Path(args.guard_matrix) if args.guard_matrix else GUARD_MATRIX
        if not _src.exists():
            print(f"== 反向守卫注入 --mutate guardctl ==")
            print(f"  ⛔ 控制组挑错输入：矩阵不在场（{_src}）⇒ 无法注入。"
                  f"先跑 `python tools/acceptance.py --guard-new-items` 取一份真矩阵。")
            return 1
        _bad = json.loads(_src.read_text(encoding="utf-8"))
        _n = 0
        for _v in (_bad.get("criteria") or {}).values():
            _v["control"] = False                              # 人为把"该绿就绿"改坏
            _v["control_line"] = "[注入] 控制组被人为改坏"
            _n += 1
        _tmp = ROOT / "out" / "acceptance" / "guard-matrix-injected.json"
        _tmp.parent.mkdir(parents=True, exist_ok=True)
        _tmp.write_text(json.dumps(_bad, ensure_ascii=False, indent=2), encoding="utf-8")
        _lines, _reds, _allgreen = guard_discipline(_tmp)
        print("== 反向守卫注入 --mutate guardctl（把控制组改坏） ==")
        print(f"  注入了 {_n} 条判据的控制组")
        for _l in _lines:
            print(_l)
        print()
        if _reds:
            print(f"  ✅ 红得起来：{len(_reds)} 条判据被点名（这一层不是空的）")
            return 1                                          # ⛔ 注入成功 ⇒ 非 0 才算守卫成立
        print("  ⛔ **没红**：把控制组改坏了这一节还是绿的 ⇒ 「永久假红」这层纪律是空判据")
        return 0

    if args.mutate:
        # ★ 先验控制组再注入：挑错输入的"绿"与判据坏掉的"绿"长得一模一样。
        ok, why = mutation_precheck(args.mutate)
        print(f"== 反向守卫注入 --mutate {args.mutate} ==")
        print(f"  {'✅' if ok else '⛔'} {why}")
        print()
        if not ok:
            return 1
        rows = rows + [MUTATIONS[args.mutate]]

    print(f"== 覆盖表（{len(rows)} 行；调用点与守卫是量出来的，「后果」一列是人写的断言） ==")
    # ⚠ 来源三件套**是标注、不是判据**：脏树不让 rc 变红——否则正常干活（谁的工作区都是脏的）
    #   时这个工具就永远红，人就学会忽略它。代价是"脏树的数字"与"入库的数字"看起来一样，
    #   所以必须把身份打在**同一屏**上，让读的人自己判断——而不是指望他记得去看 git status。
    for line in provenance_lines(source_dirty(), tree_head(), tree_branch()):
        print(line)
    print()
    assessed = [assess(r) for r in rows]
    cur = None
    for a in assessed:
        if a["plane"] != cur:
            cur = a["plane"]
            print(f"── {cur} ──")
        files = sorted({str(h[0].relative_to(ROOT)) for h in a["hits"]})
        print(f"  {a['name']}")
        print(f"    内核     {'✅' if a['ok'] else '⛔'} {a['why']}")
        print(f"    引用数   合计 {len(a['hits']):>3} 处，"
              f"其中**跨文件** {len(a['outside']):>3} 处（{a['how']}；"
              f"{len(files)} 个文件{('：' + '、'.join(files[:4])) if files else ''}）")
        print(f"    守卫     {len(a['guards'])} 条"
              f"{('：' + '、'.join(a['guards'][:3])) if a['guards'] else '（无）'}")
        print(f"    接线状态 {a['status']}（**人判**）／ 引用形态 {a['measured']}（量出来的）")
        print(f"    人判依据 {a['wired_why'] or '⚠ 未登记（前轮判定，本轮未复核）'}")
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

    # ★ 退出码只看**量出列**。这里把红行逐条点名——"哪一行红"必须能从输出里读出来，
    #   否则 rc=1 只是一声没有内容的警报（下游只能靠翻屏找，等于没报）。
    reds = red_names(assessed)
    if reds:
        print()
        print(f"== ⛔ 量出列为红的行（{len(reds)} 行；退出码只认这一列） ==")
        for name, measured, why in reds:
            print(f"    {name}  ⇒ {measured}")
            print(f"      {why}")

    print()
    print("== 判据纪律：三层守卫（敏感性／反例／控制组）——**永久假红＝没有判据** ==")
    disc_lines, disc_reds, disc_green = guard_discipline(
        Path(args.guard_matrix) if args.guard_matrix else None)
    for _l in disc_lines:
        print(_l)
    if disc_reds:
        print(f"  ⛔ 控制组没绿的判据（{len(disc_reds)} 条，**计入退出码**）：")
        for _r in disc_reds:
            print(f"    {_r}")

    print()
    print(f"== 小结：{len(rows)} 行，红 {len(reds)} 行；"
          f"「我们没有」{len(UNMODELED_BY_SEVERITY)} 项；"
          f"判据纪律 {'⚠ 未测' if disc_green is None else ('✅ 恒红可辨' if disc_green else '⛔ 控制组没绿')} ==")
    print("  ⚠ 「已接线」≠「已验证」；「零调用点」读作「这个符号没有生产调用者」，"
          "不读作「机制没落地」。")
    return 1 if (reds or disc_reds) else 0


if __name__ == "__main__":
    raise SystemExit(main())
