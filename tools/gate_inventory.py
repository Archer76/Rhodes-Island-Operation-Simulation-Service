#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸门条目 × Go 侧落地状态 的静态盘点（**不需要作业**）。

## 为什么要有它

`tools/sweep_hsl_parity.py` 那条路（逐关搜索作业 → 对拍）需要作业才能跑，
而且它依赖的 `parity_plan` 模块已从仓库中消失。但要回答"8 关到底卡在什么上"，
其实不必跑战斗：**闸门条目本身是静态可穷举的**——它们就是
`ak_tactic/simgo/spec.py::unsupported_reasons` 里那些 `bad.append(...)`。

## 三态判据（这是本工具的重点）

一个字段**在 `wire.go` 里存在，不等于有人在 `sim.go` 里读它**。
本项目已经栽过这个跟头（`Farmland.DeployDamage` 有实现有测试、零调用点）。
所以每个条目分三态报：

    未送        wire.go 与消费树里都找不到该字段名
    送了没消费  wire.go 里有，消费树里一处都没有   ← **最危险的一态**
    已消费      消费树里至少有一处

⚠ 本工具是**静态**的：找到名字不等于语义正确，也不等于闸门该放行。
它只回答"这一条在 Go 侧有没有落脚点"，放行与否仍要逐条读代码。

用法：
    python tools\\gate_inventory.py            # 打印表
    python tools\\gate_inventory.py --md       # 输出 markdown 表（写文档用）
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parents[1]
SIMDIR = ROOT / "rios-sim"

#: 送数文件：规格字段定义在这里（`json:"snake_case"` + Go 字段名两种写法都可能被搜）
WIRE = SIMDIR / "wire.go"

#: 消费树：真正**读**这些字段的地方。排除 wire.go 自己，避免"只定义就算落地"。
CONSUMERS = sorted(
    p for p in list(SIMDIR.glob("*.go")) + list((SIMDIR / "mech").glob("*.go"))
    if p.name != "wire.go"
)

#: 闸门条目表。来源 = `spec.py::unsupported_reasons` 的 `bad.append`，
#: 逐条抄下来并标注那一行（`why`），免得日后与闸门脱钩。
#: `tokens` = 该条目在 Go 侧可能的写法（snake_case 的 JSON 名 / CamelCase 的字段名）。
GATES: list[tuple[str, str, tuple[str, ...]]] = [
    # ---- 排程层（整关拒跑）----
    ("召唤物部署", "sch.summon_deployments", ("summon_of", "SummonOf", "SummonSpec", "Summon")),
    ("装置部署", "sch.device_deployments", ("device_deployments", "DeviceDeployments", "DeviceSpec")),
    ("撤退", "sch.retreats", ("retreats", "Retreats", "retreat", "Retreat")),
    ("关卡装置", "sim._devices", ("_devices", "DeviceSpec", "devices")),
    ("全场总攻击装置", "sim.total_attack", ("total_attack", "TotalAttack")),
    # ---- 活动机制层（田地／积雪…）----
    ("积雪", "sim.snow_fields", ("snow_fields", "SnowFieldSpec", "SnowFields")),
    ("田地", "sim.farmland", ("farmland", "Farmland")),
    # ---- 技能层 ----
    ("技能（未放行时整条拒跑）", "op.skill", ("Skill", "skill")),
    ("技能效果覆盖", "op.effects_override", ("effects_override", "EffectsOverride")),
    ("技能治疗倍率 heal_scale", "op.heals + eff.heal_scale", ("heal_scale", "HealScale")),
    ("高台触发回技力 sp_per_highland", "skill.blackboard", ("sp_per_highland", "SpPerHighland")),
    # ---- 干员字段层 ----
    ("锤击", "op.hammer", ("hammer", "Hammer")),
    ("天赋回技力（出手）", "op.sp_per_attack_talent", ("sp_per_attack_talent", "SpPerAttack")),
    ("天赋回技力（击杀）", "op.sp_per_kill_talent", ("sp_per_kill_talent", "SpPerKill")),
    ("物理闪避", "op.dodge_phys", ("dodge_phys", "DodgePhys")),
    ("法术闪避", "op.dodge_arts", ("dodge_arts", "DodgeArts")),
    ("攻击力光环", "op.aura_atk_pct", ("aura_atk_pct", "AuraAtkPct", "TeamAura")),
    ("防御光环", "op.aura_def_pct", ("aura_def_pct", "AuraDefPct", "TeamAura")),
    ("免死", "op.blessing_save", ("blessing_save", "BlessingSave")),
    ("弱点伤害", "op.weakness_damage", ("weakness_damage", "WeaknessDamage")),
    ("天赋攻速（空闲时）", "op.aspd_when_free", ("aspd_when_free", "AspdWhenFree")),
    ("天赋攻速（高台）", "op.aspd_high_ground", ("aspd_high_ground", "AspdHighGround")),
    ("天赋回技力 find_sp_on_action", "天赋表", ("find_sp_on_action", "FindSPOnAction", "SpOnAction")),
    ("翔虫机动 find_glider_mobility", "天赋表", ("find_glider_mobility", "GliderMobility", "Glider")),
    # ---- 强击瓶专家：`rounds == 1` 已放行，多轮仍挡 ----
    ("强击瓶专家·多轮 volley_arrows", "eff.volley_arrows", ("volley_arrows", "VolleyArrows", "Volley")),
    ("强击瓶专家·多轮 landing_scale", "eff.landing_scale", ("landing_scale", "LandingScale", "Landing")),
    ("强击瓶专家·多轮 charge_arrows", "eff.charge_arrows", ("charge_arrows", "ChargeArrows", "ChargeArrows")),
]


def _grep(paths: list[pathlib.Path], tokens: tuple[str, ...]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """在这些文件里找这些 token，返回 (定义处, 读取处)。

    ⚠ **注释行必须排除**。本工具第一版把注释也算命中，于是
    `sim.go:1918` 那句"那三样（`volley_arrows`/`landing_scale`/`charge_arrows`）
    **还没进** Go 的 `Profile`"、`sim.go:2041` 那句"已知未接：`sp_per_highland`"
    都被读成了"**已消费**"——结论正好反了。凡是"注释里提过"就当落地的判据，
    在这棵树上会给出与事实相反的答案。

    "定义" = 结构体字段声明或 json tag；"读取" = 字段访问（`.Name`）。
    两者分开数，才能区分"送了"与"有人用"。
    """
    defs: list[tuple[str, str]] = []
    reads: list[tuple[str, str]] = []
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            if s.startswith("//") or s.startswith("*"):
                continue                      # 注释：不算证据
            for t in tokens:
                if t not in line:
                    continue
                tag = f'{p.name}:{i}'
                # 定义：json tag、结构体字段声明、**类型声明**、切片元素类型
                # （只认字段会漏掉整族机制——积雪/田地在 Go 里是 `type Xxx struct`
                #  与 `[]Xxx`，第一版因此把它们误报成"未送"）
                if (f'json:"{t}' in line
                        or re.match(rf"^{re.escape(t)}\s+[\w\[\]\*\.]+", s)
                        or re.match(rf"^type\s+{re.escape(t)}\b", s)
                        or f"[]{t}" in line.replace(" ", "")
                        or f"[]{t} " in line):
                    defs.append((tag, s[:110]))
                if f".{t}" in line:
                    reads.append((tag, s[:110]))
                break
    return defs, reads


def main() -> int:
    wire_defs: dict[str, list[tuple[str, str]]] = {}
    con_defs: dict[str, list[tuple[str, str]]] = {}
    con_reads: dict[str, list[tuple[str, str]]] = {}
    for name, _why, tokens in GATES:
        _wd, _wr = _grep([WIRE], tokens)
        cd, cr = _grep(CONSUMERS, tokens)
        wire_defs[name] = _wd
        con_defs[name] = cd
        con_reads[name] = cr

    md = "--md" in sys.argv
    if md:
        print("| 闸门条目 | 规格判据 | Go 侧状态 | 证据 |")
        print("|---|---|---|---|")
    else:
        print(f"闸门条目 × Go 落地状态（静态盘点，消费树 {len(CONSUMERS)} 个文件，注释已排除）")
        print("=" * 96)

    tally = {"未送": 0, "已定义未读": 0, "已读取": 0}
    for name, why, _tokens in GATES:
        wd, cd, cr = wire_defs[name], con_defs[name], con_reads[name]
        if cr:
            state = "已读取"
        elif cd or wd:
            state = "**已定义未读**"
        else:
            state = "未送"
        tally[state.replace("*", "")] += 1
        ev = ""
        if cr:
            ev = "、".join(h[0] for h in cr[:3]) + (f" 等 {len(cr)} 处" if len(cr) > 3 else "")
        elif cd:
            ev = "仅定义：" + "、".join(h[0] for h in cd[:3])
        elif wd:
            ev = "仅 wire 定义：" + "、".join(h[0] for h in wd[:2])
        if md:
            print(f"| {name} | `{why}` | {state} | {ev} |")
        else:
            print(f"  [{state:>8}] {name:<34} 判据 {why:<28} 送={len(wd)+len(cd)} 读={len(cr)}  {ev}")

    print()
    print(f"  合计：已读取 {tally['已读取']} / 已定义未读 {tally['已定义未读']} / 未送 {tally['未送']}")
    print()
    print("  ⚠ 静态判据：命中名字 ≠ 语义正确、≠ 闸门该放行；放行仍须逐条读代码。")
    print("  ⚠ 「已定义未读」是最危险的一态：字段有、没人读，闸门却以为落地了。")
    print("  ⚠ 注释已排除（第一版没排除，把「还没进 Go」读成了「已消费」，结论正好反了）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
