# -*- coding: utf-8 -*-
"""`difficultyMask` 的**整数形态**：单元级读数 ＋ 端到端读数（2026-09-28）。

## 为什么有这一件

「关卡静态」在全量批次上红 **163 处**，形状只有一种：

    ✗ act10d5_01/FOUR_STAR life：Go=1 Python=5
    ✗ act10d5_02/FOUR_STAR life：Go=1 Python=3
    …

原始数据（`out/acceptance/_lifepoint_runes.py` 摊开的）：

    level_act10d5_01.json  runes 3 条，其中 key=global_lifepoint
        difficultyMask=2（**整数**）  blackboard={"value": 1}
        options.maxLifePoint = 5

Go 侧 `difficultyMaskOf` 把整数 2 归一成 `FOUR_STAR`（证据在 `stageenv.go:58-67`），
于是四星档套上这条 rune ⇒ life=1；Python 侧 `mask_applies` 只认字符串，
`2 in ("ALL","",None)` 假、`2 == "FOUR_STAR"` 也假 ⇒ **整条 rune 被跳过**，
四星档的 life 被算成关卡自己的 `maxLifePoint`（3 或 5）。

⇒ 谁对：**Go 对**。旁证有两条，都不靠"哪边看着更顺眼"：
  ① 同一份对拍里 **NORMAL 档两边一致（Go=5=Python）** —— 说明 Go 只在
     `FOUR_STAR` 那一档套了这条 rune，与 `bit1=FOUR_STAR` 自洽；
  ② `stageenv.go:36` 记着"八关 EX 的四星档都改成 1"，与这批关卡的
     `value=1` 同形。

## 本脚本量什么（每条都配对照）

  · 单元：整数掩码 1/2/3/4/0 与字符串形态的 `mask_applies` 逐条对（含
    **负对照**：认不出的整数（0 与 4）**不许**变成"对所有难度都适用"）；
  · 端到端：`global_lifepoint` 在 `act10d5_01` 上 NORMAL ⇒ None（不套）、
    FOUR_STAR ⇒ 1（套上）；
  · **负对照**：一份没有 lifepoint rune 的关卡（`main_01-07`）两档都得 None
    （证明"套上了"不是无差别套）。

跑法：`python tools\\difficulty_mask_probe.py`（只读，无副作用）。rc=0 = 全过。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.frontend.blackboard import (find_rune, mask_applies,   # noqa: E402
                                          normalize_difficulty_mask)
from ak_tactic.frontend.stage_mul import global_lifepoint             # noqa: E402
from ak_tactic.gamedata.stage import load_stage                       # noqa: E402

LEVELS = ROOT / "data" / "gamedata" / "map.ark-nights.com" / "levels"
problems: list[str] = []

#: ---- 一、单元表（mask, difficulty, 期望） ----
CASES: list[tuple[object, str, bool]] = [
    #: 整数形态（本次修的）
    (2, "FOUR_STAR", True),
    (2, "NORMAL", False),
    (1, "NORMAL", True),
    (1, "FOUR_STAR", False),
    (3, "NORMAL", True),
    (3, "FOUR_STAR", True),
    #: 负对照：认不出的整数**不许**当万能
    (4, "NORMAL", False),
    (4, "FOUR_STAR", False),
    (0, "NORMAL", False),
    #: 字符串形态（不许回归）
    ("FOUR_STAR", "FOUR_STAR", True),
    ("FOUR_STAR", "NORMAL", False),
    ("ALL", "NORMAL", True),
    ("", "NORMAL", True),
    (None, "NORMAL", True),
]
print("一 · 单元：`mask_applies` 逐条")
for mask, diff, want in CASES:
    got = mask_applies(mask, diff)
    mark = "✓" if got == want else "✗"
    if got != want:
        problems.append("mask_applies(%r, %r) = %s、期望 %s" % (mask, diff, got, want))
    print("  %s mask=%-11r diff=%-10s ⇒ %-5s（归一后 %r）"
          % (mark, mask, diff, got, normalize_difficulty_mask(mask)))

#: ---- 二、端到端：真实关卡 ----
print()
print("二 · 端到端：`global_lifepoint` 在真关卡上")
raw = json.loads((LEVELS / "activities" / "act10d5"
                  / "level_act10d5_01.json").read_text(encoding="utf-8"))
st = load_stage("act10d5_01")
maxlife = (raw.get("options") or {}).get("maxLifePoint")
for diff, want in (("NORMAL", None), ("FOUR_STAR", 1)):
    got = global_lifepoint(st, diff)
    mark = "✓" if got == want else "✗"
    if got != want:
        problems.append("global_lifepoint(act10d5_01, %s) = %r、期望 %r"
                        % (diff, got, want))
    print("  %s act10d5_01 %-10s ⇒ %-6r（关卡自己的 maxLifePoint=%s）"
          % (mark, diff, got, maxlife))
#: 顺带把 find_rune 的选择印出来（"到底选中了哪一条"）
for diff in ("NORMAL", "FOUR_STAR"):
    r = find_rune(raw.get("runes") or [], "global_lifepoint", diff)
    print("     find_rune(global_lifepoint, %-10s) ⇒ %s"
          % (diff, "命中 mask=%r" % r.get("difficultyMask") if r else "None（不套）"))

#: ---- 三、对照：老键名＋字符串掩码那一支（正向），与"根本没有这条 rune"（负向） ----
print()
print("三 · 对照 A（正向）：`main_01-07` 用的是**老键名＋字符串掩码**")
print("     实测它的 runes = [('gbuff_lifepoint','FOUR_STAR'), ('ebuff_attribute','FOUR_STAR'),"
      " ('cbuff_cost_recovery','FOUR_STAR')]")
st3 = load_stage("main_01-07")
for diff, want in (("NORMAL", None), ("FOUR_STAR", 1)):
    got = global_lifepoint(st3, diff)
    mark = "✓" if got == want else "✗"
    if got != want:
        problems.append("对照A：main_01-07 的 %s 档算出 %r、期望 %r（老键名＋字符串那一支坏了）"
                        % (diff, got, want))
    print("  %s main_01-07 %-10s ⇒ %r" % (mark, diff, got))

print()
print("三 · 对照 B（负向）：根本没有 lifepoint rune 的关卡")
for lv in ("tr_01", "a001_01"):
    st2 = load_stage(lv)
    for diff in ("NORMAL", "FOUR_STAR"):
        got = global_lifepoint(st2, diff)
        if got is not None:
            problems.append("负对照失败：%s 的 %s 档算出 %r —— 这一关没有这条 rune"
                            % (lv, diff, got))
        print("  %s %-9s %-10s ⇒ %r" % ("✓" if got is None else "✗", lv, diff, got))

print()
if problems:
    print("★ %d 处不成立：" % len(problems))
    for p in problems:
        print("  · %s" % p)
    raise SystemExit(1)
print("结论：整数掩码的位义与 Go 一致，认不出的取值不假装万能，字符串形态无回归")
