#!/usr/bin/env python3
"""
Audit repository files for unofficial or fabricated Arknights terminology.
Ensures subprofessions, operator talents, and skills follow official game data.
Exit code: 0 if clean, 1 if any violation found.
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent

# Comprehensive dictionary of (unofficial_term, official_term, category)
TERMS = [
    # 1. Subprofession unofficial names
    ("原质近卫", "本源近卫", "子职业 (primguard)"),
    ("原初近卫", "本源近卫", "子职业 (primguard)"),
    ("元素近卫", "本源近卫", "子职业 (primguard)"),
    ("协同支援", "游击手", "子职业 (supportiveranger)"),
    ("支援射手", "游击手", "子职业 (supportiveranger)"),
    ("游击狙", "游击手", "子职业 (supportiveranger)"),
    ("攻城狙击手", "攻城手", "子职业 (siegesniper)"),
    ("攻城狙", "攻城手", "子职业 (siegesniper)"),
    ("重炮狙", "攻城手", "子职业 (siegesniper)"),
    ("特种地刺", "伏击客", "子职业 (stalker)"),
    ("伏击者", "伏击客", "子职业 (stalker)"),
    ("重剑近卫", "重剑手", "子职业 (crusher)"),
    ("震地者", "撼地者", "子职业 (hammer)"),
    ("破空炮手", "裂空炮手", "子职业 (skybreaker)"),
    ("滑翔者", "巡空者", "子职业 (skywalker)"),
    ("附灵术师", "塑灵术师", "子职业 (soulcaster)"),
    ("灵能术师", "塑灵术师", "子职业 (soulcaster)"),
    ("原质术师", "本源术师", "子职业 (primcaster)"),
    ("元素术师", "本源术师", "子职业 (primcaster)"),
    ("原质铁卫", "本源铁卫", "子职业 (primprotector)"),
    ("元素铁卫", "本源铁卫", "子职业 (primprotector)"),
    ("炼金术士", "炼金师", "子职业 (alchemist)"),
    ("调度官", "调度者", "子职业 (dispatcher)"),
    ("调配者", "调度者", "子职业 (dispatcher)"),
    ("戒备者", "守望者", "子职业 (watchman)"),
    ("快活特种", "处决者", "子职业 (executor)"),
    ("快速复活特种", "处决者", "子职业 (executor)"),
    ("推推特种", "推击手", "子职业 (pusher)"),
    ("拉人特种", "钩索师", "子职业 (hookmaster)"),
    ("自伤特种", "怪杰", "子职业 (geek)"),
    ("扣费特种", "行商", "子职业 (merchant)"),
    ("替身特种", "傀儡师", "子职业 (dollkeeper)"),
    ("减速辅助", "凝滞师", "子职业 (slower)"),
    ("削弱辅助", "削弱者", "子职业 (underminer)"),
    ("减防辅助", "削弱者", "子职业 (underminer)"),
    ("庇护辅助", "护佑者", "子职业 (blessing)"),
    ("装置辅助", "工匠", "子职业 (craftsman)"),
    ("仪式辅助", "巫役", "子职业 (ritualist)"),
    ("死魂辅助", "巫役", "子职业 (ritualist)"),
    ("投降先锋", "执旗手", "子职业 (bearer)"),
    ("杀回先锋", "冲锋手", "子职业 (charger)"),
    ("高台先锋", "战术家", "子职业 (tactician)"),
    ("速活先锋", "情报官", "子职业 (agent)"),
    ("群攻近卫", "强攻手", "子职业 (centurion)"),
    ("远攻近卫", "领主", "子职业 (lord)"),
    ("连击近卫", "剑豪", "子职业 (sword)"),
    ("绝食近卫", "武者", "子职业 (musha)"),
    ("收割近卫", "收割者", "子职业 (reaper)"),
    ("蓄力近卫", "解放者", "子职业 (librator)"),
    ("法伤近卫", "术战者", "子职业 (artsfghter)"),
    ("快拳近卫", "斗士", "子职业 (fighter)"),
    ("单体狙", "速射手", "子职业 (fastshot)"),
    ("快狙", "速射手", "子职业 (fastshot)"),
    ("轻狙", "速射手", "子职业 (fastshot)"),
    ("霰弹狙", "重射手", "子职业 (closerange)"),
    ("散弹狙", "散射手", "子职业 (reaperrange)"),
    ("高台重装", "阵法术师", "子职业 (phalanx)"),
    ("绝食重装", "不屈者", "子职业 (unyield)"),
    ("绝食盾", "不屈者", "子职业 (unyield)"),
    ("法抗重装", "驭法铁卫", "子职业 (artsprotector)"),
    ("法抗盾", "驭法铁卫", "子职业 (artsprotector)"),
    ("奶重装", "守护者", "子职业 (guardian)"),
    ("奶盾", "守护者", "子职业 (guardian)"),
    ("炮盾", "要塞", "子职业 (fortress)"),
    ("决斗盾", "决战者", "子职业 (duelist)"),
    ("单奶", "医师", "子职业 (physician)"),
    ("群奶", "群愈师", "子职业 (ringhealer)"),
    ("广域奶", "疗养师", "子职业 (healer)"),
    ("元素奶", "行医", "子职业 (wandermedic)"),
    ("输出奶", "咒愈师", "子职业 (incantationmedic)"),
    ("链奶", "链愈师", "子职业 (chainhealer)"),

    # 2. Operator talents & skills unofficial names
    # Ascalon
    ("密林低语", "死亡拘审", "阿斯卡纶第一天赋"),
    ("暗影遮蔽", "噬光残影", "阿斯卡纶第二天赋"),
    ("无声收割", "追袭", "阿斯卡纶技能一"),
    ("荆棘束缚", "恩赐", "阿斯卡纶技能二"),
    ("尽头余烬", "降临", "阿斯卡纶技能三"),

    # Typhon
    ("碎石破阵", "锐如兽牙", "提丰第一天赋"),
    ("沉着巡弋", "重如沼泥", "提丰第二天赋"),
    ("冰原馈赠", "冰原秩序", "提丰技能二"),

    # Talulah
    ("照霁白夜", "照霎白夜", "塔露拉技能一"),
    ("阻断骤雪", "阂断骤雪", "塔露拉技能二"),
    ("不息之火", "绝不妥协", "塔露拉第一天赋(草案)"),
    ("原初烈焰力场", "我即火焰", "塔露拉第二天赋(草案)"),
    ("熔火恐惧", "照霎白夜", "塔露拉技能一(草案)"),
    ("天火焚原", "日冕重烈", "塔露拉技能三(草案)"),
]

TERMS.sort(key=lambda x: len(x[0]), reverse=True)

EXTS = {".md", ".go", ".py", ".json", ".txt"}
EXCLUDE_DIRS = {".git", ".agents", "node_modules", "data"}
EXCLUDE_FILES = {
    "docs/official-terminology-audit-report.md",
    "dispatch/2026-11-03-official-terminology-audit.md",
    "tools/audit_official_terminology.py",
}

def main():
    violations = []
    for p in REPO_ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel in EXCLUDE_FILES:
            continue
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        if p.suffix not in EXTS:
            continue

        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue

        for line_idx, line in enumerate(lines, 1):
            for bad, good, cat in TERMS:
                if bad in line:
                    violations.append({
                        "file": rel,
                        "line": line_idx,
                        "bad": bad,
                        "good": good,
                        "category": cat,
                        "text": line.strip()
                    })

    if violations:
        print(f"FAILED: Found {len(violations)} terminology violations:")
        for v in violations:
            print(f"  {v['file']}:{v['line']} [{v['bad']} -> {v['good']}] ({v['category']})")
            print(f"    {v['text']}")
        sys.exit(1)
    else:
        print("OK: All official terminology checks passed (0 violations).")
        sys.exit(0)

if __name__ == "__main__":
    main()
