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
    ("技能", "tools/check_skill_go.py", "Go 自读技能元数据/黑板 vs SkillBook", False),
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
