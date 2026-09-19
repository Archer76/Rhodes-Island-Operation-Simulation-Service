# -*- coding: utf-8 -*-
"""机制词典（PRTS《敌人一览/数据》的 `mc-tooltips`）逐条落地审计。

为什么要有它：`docs/mechanics-dictionary.md` 的「现状总表」是 **2026-09-19 的一份快照**，
而此后 Go 侧陆续落了 `control.go` / `fear.go` / `palsy.go` / `resist.go` / `element.go` …
**那份表里的「未建模」已有相当一部分不成立**。表一旦过期会同时害两头：
接手者去重做已有的东西，或者以为「20 条欠账」而放弃。

判据（本工具的核心，别改成 grep 计数）：
    词典文档自己写着「命中数是**首过**统计，用于排序，**不作建模判据**」。
    所以「落地」由**具名锚点**判：每条机制声明 `文件::符号`，工具去源码里找**那个符号的定义位**。
    锚点找不到就是**红**——说明实现被改名或被删，报表必须跟着变红，而不是继续报「已有」。

每条机制报三态，缺一不可：
    内核    —— Go 侧有没有实现（具名锚点在）
    调用点  —— 有没有**非测试**的生产调用（`element.go` 的教训：内核齐备、零调用点，
               对拍看起来全绿，机制其实一次都没跑）
    守卫    —— `*_test.go` 里有没有盯这个锚点

用法：
    python tools/dict_status.py --discover     # 发现模式：列原始命中，供人工定锚点
    python tools/dict_status.py                # 报表模式：按锚点表判三态，锚点失效即红
    python tools/dict_status.py --check        # 自检模式：只报红（无红退出码 0）
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 词典 25 条（`docs/mechanics-dictionary.md` 第一节的词条列，逐条照抄、顺序照抄）。
ENTRIES: list[str] = [
    "隐匿", "神经损伤", "沉睡", "浮空", "元素损伤", "凋亡损伤", "灼燃损伤", "起飞",
    "侵蚀损伤", "寒冷", "脆弱", "抵抗", "近地悬浮", "迷彩", "恐惧", "麻痹", "战栗",
    "折射", "元素脆弱", "狂躁损伤", "晕眩", "停顿", "屏障", "束缚", "冻结",
]

#: 统称，不是独立机制——单列出来是为了不漏、也不重复计数。
UMBRELLA: list[str] = ["异常状态", "异常组合"]

#: **PRTS 权威表 `异常效果` 的内部 ID**（词条 -> `内部ID(编号)`）。
#:
#: 取证时间 2026-09-19，来源 `https://prts.wiki/w/异常效果?action=raw`（客户端 2.7.61，
#: 43 个异常效果 + 2 异常组合 + 9 种抗性）。**第三方内容不入库**，原文落在 `tmp/prts/`。
#:
#: 为什么值得单独列一栏：它把"词典词条"与"引擎里的那个开关"对上号，
#: 而且能暴露一类**词典没说的**结构事实——见下面的 `NOT_A_FLAG`。
PRTS_FLAG: dict[str, str] = {
    "神经损伤": "—（不是异常效果：是元素损伤轴）",
    "沉睡": "SLEEPING(组合 0)",
    "浮空": "LEVITATE(25)",
    "元素损伤": "—（不是异常效果：是元素值轴，见 ELEMENT_FREE_ALL(21) 元素免疫）",
    "凋亡损伤": "—（同上）",
    "灼燃损伤": "—（同上）",
    "侵蚀损伤": "—（同上）",
    "狂躁损伤": "—（同上）",
    "寒冷": "COLD(23)",
    "抵抗": "—（不是异常效果：是时长口径，非开关）",
    "近地悬浮": "MOTION_TARGET_FREE(35) 对地规避（无法被行动方式为地面的不同阵营单位选中）",
    "隐匿": "INVISIBLE(9)",
    "迷彩": "CAMOUFLAGE(17)",
    "恐惧": "FEARED(33) + FEARED_PRIVATE(42) 自惧",
    "麻痹": "PALSY(39) → PALSYING(40) 麻痹震颤",
    "战栗": "DISARMED_COMBAT(31)",
    "晕眩": "STUNNED(0)；另有 STUNNED_NO_AMPLIFY_DAMAGE(19) 无法行动",
    "停顿": "—（不是异常效果：是 Buff 造成的移速降低）",
    "屏障": "—（不是异常效果：是 Buff/伤判效果）",
    "束缚": "UNMOVABLE(13)；另有 UNMOVABLE_PRIVATE(22) 自缚",
    "冻结": "FROZEN(16)",
}

#: **不是异常效果（Buff）** 的词典词条。这一条栏位存在的理由是：
#: `异常效果` 权威表里逐行核对后，有几条词典词条**根本不在那张表上**——
#: 它们是 **Buff / 伤判效果**，实现位置与异常开关完全不同。
#: 若不区分，就会去"找那个开关"，然后永远找不到（或更糟：把别的开关当它）。
NOT_A_FLAG: dict[str, str] = {
    "脆弱": "Buff 类（不在 `异常效果` 表里）：受到的伤害提升，同名取最高；"
            "公式层已归 `fragile`/`受到伤害`，**引擎零消费**",
    "元素脆弱": "Buff 类（同上表里没有）；公式层有 `ep_fragile`",
    "起飞": "不是独立异常效果；Go 侧只有一句注释，**不是**实现",
}

#: 已建模项的锚点表：词条 -> (文件::符号, 备注)。
#: 锚点是**断言**，本工具负责证伪它。
ANCHORS: dict[str, tuple[str, str]] = {
    # ── 控制链（control.go）：异常标志位＋三张清单，锚到**那个标志位本身**
    "晕眩": ("rios-sim/control.go::flagStun", "三张清单都含它"),
    "沉睡": ("rios-sim/control.go::flagSleeping", "「无敌且无法行动」；另见 maskSleeping 与 canDamageSleepingTarget"),
    "浮空": ("rios-sim/control.go::flagLevitate", "空中单位；重量>3 时长减半见 heavyDuration"),
    "战栗": ("rios-sim/control.go::trembleBlocksAttack", "被阻挡后不能普攻"),
    "束缚": ("rios-sim/control.go::flagBind", "三张清单的「能否移动」含束缚与自缚"),
    "近地悬浮": ("rios-sim/control.go::airStateAfterStack", "与浮空同族、敌人侧独有；airKind 记层叠后的状态"),
    "冻结": ("rios-sim/control.go::flagFrozen", "另见 sim.go::applyFreeze；法抗 −15 见词典文档"),
    # ── 元素损伤族（element.go）：内核齐备、**零生产调用点**（看报表的调用点列）
    "元素损伤": ("rios-sim/element.go::elementState", "统称：状态机＋五行爆发表"),
    "神经损伤": ("rios-sim/element.go::elemSanity", "累计至 1000 ⇒ 1000 真伤＋晕眩 10 秒"),
    "侵蚀损伤": ("rios-sim/element.go::elemWater", "永久 −100 防御＋800 物伤"),
    "灼燃损伤": ("rios-sim/element.go::elemFire", "10 秒 −20 法抗＋1200 法伤"),
    "凋亡损伤": ("rios-sim/element.go::elemDark", "15 秒禁技能＋每秒 −1 技力＋100 法伤"),
    "狂躁损伤": ("rios-sim/element.go::elemAnger", "词典里引用最少的一条，与其余同类共用内核"),
    # ── 其余已建模
    "寒冷": ("rios-sim/sim.go::applyCold", "攻速 −30；再受一次变冻结"),
    "抵抗": ("rios-sim/resist.go::resistFactor", "时长倍率，不是把「减半」写死；麻痹每 5 秒流失 1 层"),
    "麻痹": ("rios-sim/palsy.go::palsyState", "层数＋震颤；流失走 palsyDecayInterval"),
    "恐惧": ("rios-sim/fear.go::fearCells", "无法被阻挡并四散逃跑；几何与选格在这一层"),
    "停顿": ("rios-sim/sim.go::speedFor", "移速乘区（−80%）；sluggish 秒数另计时"),
    "屏障": ("rios-sim/sim.go::take", "次数制护盾与屏障都走扣血入口 take（记忆 2d5ea43f）"),
}

#: **未建模**：这里是本目标要落地的欠账。写出来而不是让它「缺项」，
#: 是为了让报表能把「确认没有」与「忘了填」分开。
#:
#: ⚠ 说明文字**以 PRTS 权威原文为准**（`异常效果` 页 raw wikitext，2026-09-19），
#: 不再照抄词典 tooltip——实测有几条 tooltip 的判读与原文不符，最典型是隐匿。
UNMODELED: dict[str, str] = {
    "隐匿": "权威原文 `INVISIBLE(9)`：**无法被不同阵营选中**（无法选择类效果）。"
            "⚠ **词典判读已更正**：词典写的是「不阻挡时不成为敌方攻击目标」，"
            "而原文明确「隐匿与『阻挡时解除』没有直接关系，该机制通常由其他效果实现」。"
            "Go 侧零真实命中（只有一处注释提及）",
    "迷彩": "权威原文 `CAMOUFLAGE(17)`：无法被对立阵营的**部分能力与部分弹道**选中；"
            "会因隐匿免疫而失效，但失效时依旧能被检测到；**由特殊逻辑实现，不属于无法选择效果**"
            "（⇒ 不能与隐匿同一处判）。Go 侧零命中",
    "折射": "生效时法术抗性 +70；敌人侧独有；Go 侧零命中（权威页未覆盖，判读仍待取证）",
    "起飞": "**不是独立异常效果**（权威表 46 行里没有它）；Go 侧只有一句注释"
            "说「起飞的干员仍是地面单位」，**不是**实现",
}

#: **未建模 · Buff 类**：不在 `异常效果` 权威表上的词条——实现位置与异常开关完全不同。


def _go_sources() -> list[Path]:
    return sorted(p for p in (ROOT / "rios-sim").rglob("*.go"))


def _py_sources() -> list[Path]:
    return sorted(p for p in (ROOT / "ak_tactic").rglob("*.py") if "__pycache__" not in p.parts)


def _hits(needle: str, paths: list[Path]) -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for p in paths:
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if needle in line:
                    out.append((p, i, line.strip()))
        except (OSError, UnicodeDecodeError):
            continue
    return out


_SYM = {
    "func": re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)"),
    "type": re.compile(r"^type\s+([A-Za-z_][A-Za-z0-9_]*)"),
    "var": re.compile(r"^var\s+([A-Za-z_][A-Za-z0-9_]*)"),
    "const": re.compile(r"^const\s+([A-Za-z_][A-Za-z0-9_]*)"),
}

#: **const/var 块里的成员**也算定义位。
#:
#: 为什么必须支持：本词典最要紧的那批符号（flagStun / flagLevitate / flagFrozen、
#: elemSanity…elemAnger）全都写在 const 块里，形如
#:     制表符 flagStun         abnormalFlag = 1 << iota //: 晕眩 STUN
#:     制表符 flagUnableAction                          //: 无法行动（iota 续行，没有等号）
#: 只认顶层定义会把它们全判成「锚点失效」——**那是工具自己的假红**，
#: 而假红会把真实的欠账淹掉（与记忆 a312e69c 同型：报错指向了错的东西）。
_BLOCK_MEMBER = (
    re.compile(r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s+[A-Za-z_][A-Za-z0-9_.\[\]*]*\s*="),
    re.compile(r"^\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?://.*)?$"),
)


def _defines(line: str, sym: str) -> bool:
    for rx in _SYM.values():
        m = rx.match(line)
        if m and m.group(1) == sym:
            return True
    for rx in _BLOCK_MEMBER:
        m = rx.match(line)
        if m and m.group(1) == sym:
            return True
    return False


def anchor_exists(anchor: str) -> tuple[bool, str]:
    """锚点在不在？返回 (bool, 说明)。"""
    if "::" not in anchor:
        return False, f"锚点格式应为 文件::符号，得到 {anchor}"
    rel, sym = anchor.split("::", 1)
    p = ROOT / rel
    if not p.exists():
        return False, f"文件不存在：{rel}"
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if _defines(line, sym):
            return True, f"{rel}:{i} 定义位 {sym}"
    return False, f"{rel} 里没有 {sym} 的定义位（顶层 func/type/var/const 或 const 块成员）"


def production_callers(sym: str) -> list[tuple[Path, int, str]]:
    """`sym` 在**非测试** Go 源码里被引用的地方（定义行与注释行除外）。"""
    out = []
    for p in _go_sources():
        if p.name.endswith("_test.go"):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if sym not in line or line.strip().startswith("//"):
                continue  # 注释不算（记忆 9659644b：拿注释当证据会把结论弄反）
            if _defines(line, sym):
                continue
            out.append((p, i, line.strip()))
    return out


def guard_mentions(sym: str) -> list[tuple[Path, int, str]]:
    """测试文件里有没有盯这个符号——**忽略大小写的近似判据**。

    ⚠ 为什么必须忽略大小写（实测踩到的假红）：元素损伤的锚点是类型 `elementState`，
    而测试里写的是构造函数 `newElementState`——**中间那个 E 是大写**，
    所以「`elementState` in line」一次都匹配不到，报表就报「无守卫」，
    可它明明有 6 处测试在用。假红会把真实欠账淹掉，所以这里按小写比。
    代价是它只能当**近似**：它证明"测试提到过这个名字"，不证明"机制被咬到"。
    """
    needle = sym.lower()
    out = []
    for p in _go_sources():
        if not p.name.endswith("_test.go"):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if needle in line.lower():
                out.append((p, i, line.strip()))
    return out


def discover() -> int:
    go = [p for p in _go_sources() if not p.name.endswith("_test.go")]
    got = [p for p in _go_sources() if p.name.endswith("_test.go")]
    py = _py_sources()
    print("词条             Go实现  Go测试  Py    首个 Go 命中")
    print("-" * 92)
    for e in ENTRIES + UMBRELLA:
        hg, ht, hp = _hits(e, go), _hits(e, got), _hits(e, py)
        first = ""
        if hg:
            rel = hg[0][0].relative_to(ROOT)
            first = f"{rel}:{hg[0][1]}  {hg[0][2][:44]}"
        print(f"{e:<16} {len(hg):>5} {len(ht):>6} {len(hp):>5}  {first}")
    print("\n⚠ 这张表**不能**当判据：命中多半是注释。判据是下面的锚点表。")
    return 0


def report(check_only: bool) -> int:
    print("词条            判定          调用点    守卫     PRTS 权威表")
    print("-" * 108)
    reds: list[str] = []
    for e in ENTRIES:
        flag = PRTS_FLAG.get(e, "（未登记）")
        if e in NOT_A_FLAG:
            print(f"{e:<16} {'未建模(Buff)':<14} {'—':<9} {'—':<6} {flag}")
            print(f"{'':<16} {NOT_A_FLAG[e]}")
            continue
        if e in UNMODELED:
            print(f"{e:<16} {'未建模':<14} {'—':<9} {'—':<6} {flag}")
            print(f"{'':<16} {UNMODELED[e]}")
            continue
        if e not in ANCHORS:
            reds.append(f"{e}: 既不在 ANCHORS 也不在 UNMODELED —— 漏登记")
            print(f"{e:<16} {'漏登记':<14} {'?':<9} {'?':<6} {flag}")
            continue
        anchor, note = ANCHORS[e]
        ok, why = anchor_exists(anchor)
        if not ok:
            reds.append(f"{e}: 锚点失效 —— {why}")
            print(f"{e:<16} {'锚点失效':<14} {'?':<9} {'?':<6} {flag}")
            print(f"{'':<16} {why}")
            continue
        sym = anchor.split("::", 1)[1]
        callers = production_callers(sym)
        guards = guard_mentions(sym)
        call = "已接线" if callers else "零调用点"
        guard = f"{len(guards)} 处" if guards else "无"
        print(f"{e:<16} {'已建模':<14} {call:<9} {guard:<6} {flag}")
        print(f"{'':<16} 锚点 {why}" + (f"；{note}" if note else ""))
        if not callers:
            reds.append(f"{e}: 内核已建但**零生产调用点**（对拍会静默全绿）")
        if not guards:
            reds.append(f"{e}: 无守卫（没有 *_test.go 提到 {sym}）")
    n_un = sum(1 for e in ENTRIES if e in UNMODELED)
    n_buff = sum(1 for e in ENTRIES if e in NOT_A_FLAG)
    print()
    print(f"已建模 {len(ENTRIES) - n_un - n_buff} / 未建模 {n_un} / 未建模·Buff 类 {n_buff} / 共 {len(ENTRIES)} 条")
    print(f"PRTS 权威表已登记 {sum(1 for e in ENTRIES if e in PRTS_FLAG)} 条；"
          f"其中**不在异常效果表上**的 {n_buff} 条是 Buff，别去异常开关里找。")
    if reds:
        print(f"\n⚠ {len(reds)} 条欠账或红：")
        for r in reds:
            print(f"  · {r}")
    else:
        print("已建模项：锚点在、有调用点、有守卫。")
    return 1 if (check_only and reds) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true", help="列原始命中，供人工定锚点")
    ap.add_argument("--check", action="store_true", help="只报红（无红退出码 0）")
    args = ap.parse_args()
    return discover() if args.discover else report(args.check)


if __name__ == "__main__":
    sys.exit(main())
