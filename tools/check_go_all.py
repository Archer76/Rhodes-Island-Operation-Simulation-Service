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

import hashlib
import os
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
    #: 本轮加的：**机制规格**（`mechanisms` ＋ `mech_config`）。★ 期望值由
    #: `build_spec` **自己**在「关卡 ＋ 空排程」这个口径上产出（不手抄组装），
    #: 并用 24 份夹具的**生产口径**（带计划）对账：田地必须逐字段相同、
    #: `mechanisms` 的差必须恰好是 `snow.field`。`groups` 的**列表次序**
    #: 复刻不了（Python 从 set 里 pop），判据按格集合口径比并把顺序差印成读数。
    ("机制规格", "tools/check_mechspec_go.py",
     "Go mechanisms/mech_config vs build_spec（空排程口径）", False),
    #: 本轮加的：**单一入口**（`buildspec`）——一次造齐 19 个顶层键。★ 三个口径：
    #: A 计划（24 份夹具的生产规格）、B 空计划（缓存 55 关）、C 计划侧合成
    #: （把真夹具零行使的 `unsupported`／`skill_uses` 两支走到）。逐**路径**比
    #: （不是整块 `!=`：那样会把一处真差异埋进 int/float 的类型噪声里）。
    ("单一入口", "tools/check_buildspec_go.py",
     "Go buildspec 一次造齐的 19 键 vs build_spec（三口径逐路径）", False),
    #: 本轮加的：**干员规格**（`operators`）。★ 顺序与 `deploys` **同一份口径**
    #: （原版这两个键是同一个循环里的两次 append），所以两者共用 `BuildDeployRows`。
    #: 期望值取 24 份夹具的**生产规格**（64 人次）；另有一条「地基」量测：
    #: Go 的 `OperatorStats.Total[...]` 与活对象 `op.current_atk()` 是不是同一个数。
    #: 产出面：**33 个键**（含条件键的存在性）—— ★ 2026-09-23（第三十八批）把
    #: `shield` 从「具名 unported」搬进了**产出面**（32 → 33）；另 2 个
    #: （`skill`／`active`）具名进 `unported`。这里的 33/2 与本行第三栏的文字
    #: 都只是给人读的标签，真正的数由判据每次**现算**（`check_operators_go.py` §7）。
    ("干员规格", "tools/check_operators_go.py",
     "Go operators vs simgo/spec.py 的 _operator_spec（产出 33 键逐位）", False),
    #: 本轮加的：**自造规格的 `sim`**——`sim` 的第二种入参形式（关卡＋名册＋计划），
    #: Go 内部调 `buildspec` 造规格再跑。★ 判据是**差分**，不是对拍 Python：
    #: 同一关同一计划下「查询形式」的判决必须与「先 buildspec 再送规格」逐路径相同，
    #: 且**两次的 `unsupported` 必须逐位相同**（Python 靠它决定退回原版；不带回
    #: 就等于把闸门静默关掉）。旧入参形式一个字没改，本行只覆盖新增的那一种。
    ("自造规格", "tools/check_sim_selfspec_go.py",
     "Go sim 自造规格 vs Python build_spec（差分：查询形式 ≡ 造好规格）", False),
    #: 本轮加的：**Python 侧那条调用链**。`sim` 收下查询形式之后（上一行），
    #: 这一行管的是**谁在用它**：`verifier._run_other_engine` 改送查询形式、
    #: `unsupported` 非空时**具名拒跑**而不再回退去跑 Python 模拟器。
    #: ★ 判据面与前一行**不重叠**：上一行量的是 Go 那两种入参形式会不会给出
    #: 不同判决（差分），这一行量的是 Python 这条路还造不造规格、还跑不跑模拟器
    #: （AST ＋ 端到端 ＋ 三态），用的是 `git show d4ddc4c:…` 的原文当「以前」。
    ("调用链", "tools/check_sim_via_python_go.py",
     "Python 侧不再造规格/不再跑模拟器（静态＋端到端＋三态分离）", False),
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
    #: ★ **前置闸门**：数据不齐就**直接拒跑**，不要把 25 套跑完再让人去发现分母缩了。
    #:
    #: 事故形状（2026-09-24 00:46）：一个会话收尾时的 `git worktree remove --force`
    #: 穿透 junction，删掉了主仓 `data/` 的内容；于是下面那行「取证范围：缓存可达的
    #: 关卡 N 个」从 **55 关掉到 2 关**，而**它不红**——一串判据在缩水的分母上照样全绿，
    #: 靠人眼看那行字才发现。这条前置检查存在的唯一理由就是把那种情形变红。
    #:
    #: ⚠ 它**不是**跨实现对拍判据，所以**不进 `SUITE` 表**：加进去会一并改掉
    #: `tools/closeout_selfsufficiency.py` 的 `DECLARED["suites"]` 与台账读数表行数
    #: 两处（两处都要重算，而它们量的本来就不是同一件事）。
    #:
    #: ⚠ **可关**：环境变量 `RIOS_SKIP_DATA_READY`。
    #:   语义：**精确等于 `1` 才跳过**这一刀；其它值（含空串、`0`、`true`）都照跑。
    #:   为什么留这个口子：将来要在一个**已知不完整**的数据集上跑单套判据做诊断，
    #:   不能被总闸一刀切死。
    #:   跳过时会显式印一行——「跳过了」不许静默（本项目记过：没有守卫的绿是零信息量）。
    if os.environ.get("RIOS_SKIP_DATA_READY") == "1":
        print("★ 已按 RIOS_SKIP_DATA_READY=1 跳过数据前置检查"
              "（本次的「全绿」不含「data/ 完整」这一层）")
    else:
        dr = subprocess.run([PY, "-X", "utf8",
                             str(ROOT / "tools" / "check_data_ready.py")],
                            cwd=str(ROOT))
        if dr.returncode != 0:
            print("★ 数据不齐：tools/check_data_ready.py rc=%d —— **拒跑**。"
                  "（不把 25 套跑完再让人去发现分母缩了）" % dr.returncode)
            print("  要在一个已知不完整的数据集上跑单套判据做诊断，"
                  "设 RIOS_SKIP_DATA_READY=1 跳过这道理。")
            #: 把它自己的两个码原样带出去：1＝数据坏了，3＝仪器缺输入；
            #: 其余（含 5＝它自己崩了）一律按「判据红」报。
            return dr.returncode if dr.returncode in (1, 3) else 1

    rows = []
    lvls = cached_levels()
    #: `--selfcheck`：**把每套判据的反向守卫也跑一遍**。
    #: ★ 「六套全绿」只证明它们现在不红；证明不了「人为破坏时会红」。
    #: 后者才是判据有分辨力的证据——本项目为此单独记过一条
    #: （没有反向守卫的绿是零信息量的绿）。
    selfcheck = "--selfcheck" in sys.argv
    guards: list[tuple[str, int]] = []
    #: ★ **仪器只解析一次，显式下传给每一套判据**（2026-09-23 修）。
    #:
    #: 为什么必须这么做：各判据的默认路径**不统一**——`check_stage_go.py` 默认
    #: `rios-sim-stage1.exe`、`check_enemy_go.py` 默认 `rios-sim-stage2.exe`，其余
    #: 默认 `rios-sim-stage3.exe`。而 `subprocess.run` 不传 `env` 时继承父环境，
    #: 于是「父环境没设 `RIOS_SIM_BIN`」＝那两套量的是**几天前的二进制**，还照样
    #: 印 ✓。实测：那样跑「关卡」全绿，而换成当天的 exe 后 **55/55 关全红**
    #: （失配键 `stage.runes`）——一道假绿盖住了一处真红，而且它骗过了两次
    #: 「全绿」结论。所以这里解析一次、下传，并把仪器身份印在表头。
    #:
    #: ⚠ 找不到仪器就**大声失败**，不退回任何默认（本仓在「默认路径最危险」上
    #: 栽过不止一次：`e7be3da5`、`5e8ca0db`）。
    exe = os.environ.get("RIOS_SIM_BIN") or str(
        ROOT / "out" / "acceptance" / "rios-sim-stage3.exe")
    if not Path(exe).is_file():
        raise SystemExit("找不到仪器 %s —— 默认路径必须大声失败" % exe)
    child_env = {**os.environ, "RIOS_SIM_BIN": exe}
    instr = hashlib.sha256(Path(exe).read_bytes()).hexdigest()[:16]
    print("仪器：%s" % exe)
    print("     sha256(16)=%s（每一套判据都用这一枚）" % instr)
    print("取证范围：缓存可达的关卡 %d 个（喂给需要清单的那两套判据）" % len(lvls))
    for name, script, what, wants_levels in SUITE:
        cmd = [PY, "-X", "utf8", str(ROOT / script)]
        if wants_levels:
            cmd += lvls
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, env=child_env)
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
            gp = subprocess.run(gc, cwd=str(ROOT), capture_output=True, env=child_env)
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
