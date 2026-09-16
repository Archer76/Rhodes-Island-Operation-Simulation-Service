# -*- coding: utf-8 -*-
"""阶段六输出自检：摆位图、路线热度图、时间轴表格、完整报告。

分五节：**摆位图**（坐标口径与图例一致性）、**热度图**（两种度量）、
**时间轴**（排序、类别、那条容易误导的「预估到终点」有没有加脚注）、
**完整报告**（四段齐全且能落盘）、**CLI**。

跑法：`python tools/check_diagram.py`
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ak_tactic.cli import main as cli_main                            # noqa: E402
from ak_tactic.diagram import (battle_report, placement_diagram,      # noqa: E402
                               route_heat, timeline_table)
from ak_tactic.gamedata import load_stage                             # noqa: E402
from ak_tactic.plan import Plan, Roster                               # noqa: E402
from ak_tactic.verify import Verifier                                 # noqa: E402

from operbox_path import operbox_path                                  # noqa: E402

#: 账号名册是**外部输入**，不入库：见 tools/operbox_path.py 的两种取法。
BOX = operbox_path()
TEAM = "拉普兰德:2,3:Left; 能天使:3,5:Up"

_PASSED = 0
_FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(label)
        print(f"  [FAIL] {label}" + (f"   {detail}" if detail else ""))


def cell_at(line: str, x: int) -> str:
    """从 map.render() 的一行里取第 x 格。

    `render` 的排版是 `f"y={y}  "` 前缀 5 字符 + 每格 `rjust(2)`。
    早先我直接用 `split()` 取第几个词，结果被 row/x 差一位和 `##` 这种
    两字符符号拌倒——**排版是固定的，就按固定列宽解析**。
    """
    return line[5 + 2 * x: 7 + 2 * x].strip()


def row_of(text: str, y: int) -> str:
    """取出 `y=N` 那一行。"""
    for ln in text.splitlines():
        if ln.startswith(f"y={y}  "):
            return ln
    raise AssertionError(f"没有 y={y} 那一行")


def main() -> int:                                                    # noqa: C901
    print("检查阶段六输出（ak_tactic/diagram.py）")
    stage = load_stage("main_01-07")
    roster = Roster.from_json(BOX)
    plan = Plan.quick("main_01-07", TEAM)
    verifier = Verifier()
    verdict = verifier.run(plan, roster=roster)

    # ------------------------------------------------------------ 1 摆位图
    print("\n[1] 摆位图：坐标口径与图例")
    dia = placement_diagram(stage, plan, verdict=verdict, show_enemy=True)
    lines = dia.splitlines()
    check("画出 7 行地图（1-7 高 7）",
          sum(1 for ln in lines if ln.startswith("y=")) == 7,
          str(sum(1 for ln in lines if ln.startswith("y="))))
    check("y 从 0 到 6 依次打印（y 向下）",
          [ln[:3] for ln in lines if ln.startswith("y=")]
          == [f"y={i}" for i in range(7)],
          str([ln[:3] for ln in lines if ln.startswith("y=")]))
    check("列号 0–10 都在表头里", all(f"{x}" in lines[0] for x in range(11)))

    # MAA 口径的核心判据：出生点在右侧 (x=10)、防守点在左侧 (x=0)
    y3 = row_of(dia, 3)
    check("出生点符号出现在最右列（x=10）——MAA 原点左上",
          cell_at(row_of(dia, 1), 10) == "S" and cell_at(y3, 10) == "S",
          f"y=1 x=10 → {cell_at(row_of(dia, 1), 10)!r}")
    check("防守点符号出现在最左列（x=0）",
          cell_at(y3, 0) == "E", f"y=3 x=0 → {cell_at(y3, 0)!r}")
    check("(3,3) 是障碍（渲染成 #，不是可部署格）",
          cell_at(y3, 3) == "#" and not stage.map.tile(3, 3).deployable,
          f"y=3 x=3 → {cell_at(y3, 3)!r}")
    check("干员编号落在自己的格上",
          cell_at(y3, 2) == "1" and cell_at(row_of(dia, 5), 3) == "2",
          f"(2,3)={cell_at(y3, 2)!r} (3,5)={cell_at(row_of(dia, 5), 3)!r}")

    check("图例里两名干员都在",
          "拉普兰德" in dia and "能天使" in dia)
    check("图例写明 MAA 坐标与朝向",
          "MAA[2,3]" in dia and "朝左" in dia and "朝上" in dia)
    check("图例给出实际落地时刻（来自 verdict 而非计划）",
          "9.0s 落地" in dia and "23.0s 落地" in dia)
    check("攻击覆盖一节列出每人格数",
          "攻击覆盖" in dia and "8 格" in dia and "12 格" in dia)

    # 编号必须与图例一一对应
    check("地图上的编号与图例序号一致", "1" in dia and "2" in dia)

    # 没有 verdict 时也要能画（只有计划）
    dia2 = placement_diagram(stage, plan, show_range=False)
    check("只给计划（没跑过）也能画图",
          "MAA[2,3]" in dia2 and "未派时刻" in dia2)
    check("没有落位时给出提示而不是崩",
          "（还没有落位）" in placement_diagram(stage, None))

    # ------------------------------------------------------------ 2 热度图
    print("\n[2] 路线热度图：两种度量")
    heat = route_heat(stage, metric="dwell")
    check("dwell 版给出标题与量纲（敌人·秒）",
          "敌人·秒" in heat, heat.splitlines()[0])
    check("dwell 版画出 7 行", sum(1 for ln in heat.splitlines()
                                   if ln.startswith("y=")) == 7)
    check("不可行走的格标成 ##",
          cell_at(row_of(heat, 0), 0) == "##" and "##" in heat)
    check("咽喉 (2,3) 在热度图上是最高档 9",
          cell_at(row_of(heat, 3), 2) == "9",
          f"y=3 x=2 → {cell_at(row_of(heat, 3), 2)!r}")
    check("没有敌人经过的格标成 .",
          cell_at(row_of(heat, 1), 10) in ("1", "2") or "." in heat)

    heat2 = route_heat(stage, metric="routes")
    check("routes 版给出标题（几条路线经过）",
          "路线" in heat2.splitlines()[0], heat2.splitlines()[0])
    check("两种度量的图不一样", heat != heat2)
    check("非法度量名不崩", route_heat(stage, metric="whatever") is not None)

    # ------------------------------------------------------------ 3 时间轴
    print("\n[3] 时间轴表格")
    tl = timeline_table(stage, plan, verdict=verdict)
    tls = tl.splitlines()
    check("有表头与分隔线", "类别" in tls[0] and "---" in tls[1])
    check("含出怪行", "出怪" in tl)
    check("含落地行", "落地" in tl)
    check("含结束行", "结束" in tl)
    check("含预估到终点行", "预估到终点" in tl)
    check("预估到终点**必须带脚注**（否则会被读成真的漏了）",
          "没有任何干员拦截时" in tl and "「漏怪」行为准" in tl)
    check("脚注说明了它与模拟器同源、误差 ≤1 帧",
          "≤1 帧" in tl or "1 帧" in tl)
    check("1-7 的三名干员都出现在时间轴里（这里只有两名）",
          "拉普兰德" in tl and "能天使" in tl)
    check("没有「到终点」这种会误导的裸标签",
          "  到终点 " not in tl)

    # 时刻单调不减
    stamps = []
    for ln in tls:
        s = ln.strip().split()
        if s and s[0].endswith("s"):
            try:
                stamps.append(float(s[0][:-1]))
            except ValueError:
                pass
    check("时刻单调不减（排序正确）",
          all(stamps[i] <= stamps[i + 1] for i in range(len(stamps) - 1)),
          f"{len(stamps)} 行")
    check("时间轴行数 ≈ 出怪 + 落地 + 预估 + 结束",
          len(stamps) >= 41 + 2, f"{len(stamps)} 行")

    # 不带 verdict 的时间轴（只有关卡）
    tl2 = timeline_table(stage)
    check("只给关卡也能出时间轴（全出怪）",
          "出怪" in tl2 and "落地" not in tl2)

    # ------------------------------------------------------------ 4 报告
    print("\n[4] 完整报告：四段齐全")
    rep = battle_report(stage, plan, verdict=verdict)
    for sec in ("## 摆位", "## 路线热度", "## 时间轴"):
        check(f"报告含「{sec}」", sec in rep)
    check("报告抬头写明坐标口径", "MAA" in rep and "y 向下" in rep)
    check("报告含关卡基本信息（尺寸/生命/费用/人数上限）",
          "地面可部署" in rep and "生命" in rep and "人口上限"
          in rep.replace("人数上限", "人口上限"))
    check("报告含判定行", "★★★" in rep)
    check("报告含部署与表现", "部署与表现" in rep)
    check("报告含归因", "归因" in rep)
    check("报告长度够（不是空壳）", len(rep) > 2000, f"{len(rep)} 字符")

    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "r.md"
        p.write_text(rep, encoding="utf-8")
        back = p.read_text(encoding="utf-8")
        check("报告能落盘并原样读回", back == rep)

    # ------------------------------------------------------------ 5 CLI
    print("\n[5] CLI：--diagram / --timeline / --report")
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "rep.md"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = cli_main(["verify", "main_01-07", "--team", TEAM,
                           "--box", str(BOX), "--diagram", "--timeline",
                           "--report", str(out)])
        text = buf.getvalue()
        check("退出码 0（三星）", rc == 0, f"rc={rc}")
        check("--diagram 输出到 stdout", "图例：" in text)
        check("--timeline 输出到 stdout", "预估到终点" in text)
        check("--report 真的写了文件", out.exists() and out.stat().st_size > 2000,
              f"{out.stat().st_size if out.exists() else 0} 字节")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = cli_main(["verify", "main_01-07", "--team", TEAM, "--box", str(BOX),
                           "--report", str(out), "--heat-metric", "routes"])
        check("--heat-metric routes 可用", rc == 0 and "路线" in
              out.read_text(encoding="utf-8"))

    print()
    print("=" * 60)
    if _FAILED:
        print(f"通过 {_PASSED} 项，失败 {len(_FAILED)} 项：")
        for n in _FAILED:
            print(f"   ✗ {n}")
        return 1
    print(f"通过 {_PASSED} 项，无失败。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
