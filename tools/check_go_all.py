#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Go 侧全部跨实现对拍，一次跑完，一张表。

## 为什么要有这个入口

五套判据散在五个脚本里，此前每加一块都要手动想起"还有哪几套该重跑"。
**漏跑一套的症状是「全绿」——只是那份绿少了一块。** 这个入口把它们收在一起，
谁红谁绿一目了然。

## 退出码

任一套红 → 非 0。**不把「某一套没跑」算成通过**：缺产物/异常一律计红。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

#: (名字, 脚本, 这条判据答的是什么, 要不要喂关卡清单)
#:
#: ★ 「要不要喂清单」这一栏是必需的不是装饰：关卡/敌人两套判据**带 nargs 参数**，
#: 不喂就按**缺省**跑一个样本，于是总表印出「1/1」「2/2」——**全绿里那一行
#: 的分母小得误导**。第一版就是这样，读数看着漂亮、覆盖面其实是抽样。
SUITE = [
    ("关卡", "tools/check_stage_go.py", "Go 自读关卡 vs load_stage（全格地图/路线/出怪）", True),
    ("敌人", "tools/check_enemy_go.py", "Go 自读敌人 vs EnemyLibrary（逐档合并/派生/前缀）", True),
    ("干员", "tools/check_operator_go.py", "Go 自算面板/天赋/特性 vs OperatorCalculator", False),
    ("范围", "tools/check_range_go.py", "Go 自读范围表 vs RangeTable + rotate/footprint", False),
    ("技能", "tools/check_skill_go.py", "Go 自读技能元数据/黑板/效果对象 vs SkillBook", False),
    #: ★ 这一行是第 31 轮补的：分类判据（`check_classify_go.py`）10 天前就立起来了，
    #: 但**一直没进总入口**——于是「六套里跑五套」印出来仍是「全绿」。
    #: 这正是本文件第 28-30 行那条教训的同一形状：**漏跑一套的症状是全绿，
    #: 只是那份绿少了一块**。新增判据时，别忘了往这里加一行。
    ("分类", "tools/check_classify_go.py", "Go 四张分类表/拆变体/降级 vs _classify", False),
    #: 这一行是第 34 轮加的，**就是照第 37-40 行那条教训办的**（新判据落地即登记）。
    ("生命上限", "tools/check_profile_go.py", "Go 生命上限加成一行 vs _max_hp_after_bonus", False),
    #: 第 35 轮加的，同样照第 37-40 行那条教训办。
    ("攻击间隔", "tools/check_interval_go.py", "Go 开技能间隔折算 vs SkillEffects.attack_interval", False),
    #: 第 36 轮加的。同一条教训：新判据落地即登记，漏跑的症状是全绿。
    ("面板", "tools/check_panel_go.py", "Go 同一帧七处读数 vs operator_view 的七个方法", False),
    #: 第 37 轮加的。名册原先是 Go 侧唯一零入口的输入，目标里点名的第四层。
    ("名册", "tools/check_roster_go.py", "Go 直读练度名册 vs plan.Roster.from_json", False),
    #: 第 39 轮加的：名册与计划合起来之后的练度解析（两份输入第一次被真的用上）。
    ("练度", "tools/check_loadout_go.py", "Go 练度解析 vs Verifier._entry/_by_name", False),
    #: 第 38 轮加的。目标里点名的第五层，此前同样零入口。
    ("计划", "tools/check_plan_go.py", "Go 直读打法 vs plan.Plan.from_dict/validate", False),
    #: 第 41 轮加的：「Go 自己构造规格」的第一块（build_spec 19 个顶层键里
    #: 不依赖 sim／干员／机制的那 8 个）。
    ("关卡静态", "tools/check_stageenv_go.py", "Go 关卡静态 8 项 vs stage_env", False),
    #: 第 42 轮加的：规格里的两张格表（goal_cells / highland_cells）。
    ("格表", "tools/check_cells_go.py", "Go 两张格表 vs _find_goals/_highland_cells", False),
    #: 本轮加的：把已能造出的键**装配**成一份部分规格，并对账 19 个顶层键。
    ("部分规格", "tools/check_specgo_go.py", "Go 部分规格骨架 vs build_spec 的键集与值", False),
    #: 本轮加的：初始部署费用天赋——`deploys`／`skill_uses` 排程的起始费用要用它。
    ("费用天赋", "tools/check_costbonus_go.py", "Go 初始部署费用天赋 vs squad_cost_bonus", False),
    #: 本轮加的：各自练度下的部署费用——`deploys[].cost`。
    ("部署费用", "tools/check_costof_go.py", "Go 部署费用 vs 生产规格的 deploys[].cost", False),
    #: 本轮加的：地面寻路——「路线生产侧」的一半，卡着 spawns 与 unsupported。
    ("寻路", "tools/check_stagepath_go.py", "Go 地面寻路 vs StageMap.ground_path", False),
    #: 本轮加的：规格闸门（`unsupported_reasons`）。★ 24 份夹具的期望值**全是空表**
    #: （实测合计 0 条），所以这一套的信息量全在**合成夹具**上——计划侧换 dict、
    #: 敌人侧造合成关卡；判据里印了每条线被行使几次，行使 0 次的必须登记。
    ("闸门", "tools/check_unsupported_go.py",
     "Go 闸门 vs unsupported_reasons 的理由、顺序与未搬线清单", False),
    #: 本轮加的：**出怪规格**（`spawns`）。它**不吃计划**（出怪表是关卡数据），
    #: 所以期望值直接取 24 份夹具的**生产规格**（1154 条）；两个真夹具零行使的
    #: 分支（悬空路线号 / 关卡本地定义）由合成关卡补，且夹具**自证行使**。
    ("出怪规格", "tools/check_spawns_go.py",
     "Go 出怪规格 vs simgo/spec.py 的 _spawn_spec/_view/_unit_spec", False),
]


def cached_levels() -> list[str]:
    """缓存里**取得到**的关卡 id——关卡与敌人两套判据的取证范围。

    与判据本身同一口径：权威索引给 data_path，本地缓存决定"现在跑得动哪些"。
    """
    import json
    root = ROOT / "data" / "gamedata"
    idx = json.loads((root / "_level_index.json").read_text(encoding="utf-8"))
    levels_dir = root / "map.ark-nights.com" / "levels"
    return sorted(lid for lid, e in idx.items()
                  if (levels_dir / e["data_path"]).exists())


def main() -> int:
    rows = []
    lvls = cached_levels()
    #: `--selfcheck`：**把每套判据的反向守卫也跑一遍**。
    #: ★ 「六套全绿」只证明它们现在不红；证明不了「人为破坏时会红」。
    #: 后者才是判据有分辨力的证据——本项目为此单独记过一条
    #: （没有反向守卫的绿是零信息量的绿）。
    selfcheck = "--selfcheck" in sys.argv
    guards: list[tuple[str, int]] = []
    print("取证范围：缓存可达的关卡 %d 个（喂给需要清单的那两套判据）" % len(lvls))
    for name, script, what, wants_levels in SUITE:
        cmd = [PY, "-X", "utf8", str(ROOT / script)]
        if wants_levels:
            cmd += lvls
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True)
        out = p.stdout.decode("utf-8", "replace")
        #: 从各自输出里抠出「结论：」那一行；抠不到就明说抠不到（不当成通过）。
        verdict = ""
        for line in out.splitlines():
            if line.startswith("结论："):
                verdict = line.strip()
        rows.append((name, p.returncode, verdict, what, out, p.stderr.decode("utf-8", "replace")))
        if selfcheck:
            gc = [PY, "-X", "utf8", str(ROOT / script), "--mutate"]
            if wants_levels:
                #: 守卫只需一个样本就够证明「红得起来」，喂全量太慢。
                gc += lvls[:1]
            gp = subprocess.run(gc, cwd=str(ROOT), capture_output=True)
            #: 约定：`--mutate` 下 **rc=0 = 守卫成立**（真的判红了）。
            guards.append((name, gp.returncode))

    print("=" * 92)
    print("Go 侧跨实现对拍总表（判据脚本各自独立跑；本表只汇总，不改它们的判据）")
    print("=" * 92)
    bad = 0
    for name, rc, verdict, what, _out, _err in rows:
        mark = "✓" if rc == 0 and verdict else ("✗" if rc != 0 else "?")
        if mark != "✓":
            bad += 1
        print("%s %-6s rc=%-3d %s" % (mark, name, rc, verdict or "（没抠到结论行）"))
        print("        %s" % what)
    if selfcheck:
        print()
        print("★ 反向守卫自检（每套人为注入一处不一致，**必须判红**，rc=0 即成立）：")
        gbad = 0
        for name, grc in guards:
            ok = grc == 0
            if not ok:
                gbad += 1
            print("    %s %-6s rc=%d %s" % ("✓" if ok else "✗", name, grc,
                                            "" if ok else "← 守不住：注入了改动却没红"))
        if gbad:
            print("★ %d / %d 套的守卫不成立" % (gbad, len(guards)))
            return 1
        #: ⚠ 这行**要与 SUITE 同源**：写死「六套」会在加第七套之后变成假话
        #: （实测：加了「生命上限」之后它仍印「六套守卫全部成立」，而表上是七行）。
        print("    %d 套守卫全部成立" % len(guards))
    print()
    if bad:
        print("★ %d / %d 套判据没通过 —— 下面是各自的原始输出尾部：" % (bad, len(rows)))
        for name, rc, verdict, _what, out, err in rows:
            if rc == 0 and verdict:
                continue
            print()
            print("---- %s (rc=%d) ----" % (name, rc))
            tail = out.strip().splitlines()[-12:]
            for line in tail:
                print("    " + line)
            if err.strip():
                print("    [stderr] " + err.strip().splitlines()[-1])
        return 1
    print("结论：%d / %d 套全绿" % (len(rows), len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
