# -*- coding: utf-8 -*-
"""命令面判据：**缺值输入下命令行不许崩**。

## 它是为哪一件事写的

2026-09-24 实测：`python -m ak_tactic stage main_02-07` 把地图、路线、出怪全印完，
**末尾**抛 `TypeError: unsupported format string passed to NoneType.__format__`
（`ak_tactic/cli.py` 的敌人数值那一行对 `s.weight` 用了 `{...:g}`），rc=1。

崩的根因是**取数口径**，不是把关卡坏了：游戏本体用 `massLevel` 表达重量等级，
「没覆写」的那些是 `m_defined=false`；取数层按「只认 `m_defined: true`」合并逐档数据，
于是这一项没进合并结果，读出来是 `None`。2154 个敌人里有 **73** 个如此，
几乎全是**飞行单位与装置**。

⚠ **这个 bug 的形状是骗人的**：数据全印出来了、末尾才崩、rc=1 ——
很容易被读成「这一关的数据有缺失」。做第二章核查时就差点这么记。

## 判据怎么算（全部**现算**，不写死关卡名）

1. 从 `enemy_database.json` 现算「重量等级没覆写」的敌人键集合；
2. 从**缓存可达的关卡**里现算哪些关引用了它们 ⇒ 取字典序第一关当**正例**；
3. 另取一关**不引用**它们的当**对照**（它必须印得出数字）；
4. 正例的输出里，「重量 —」的**条数**必须等于那一关引用的缺值敌人数；
5. `--mutate`：把 `cli._num` 换回旧写法再跑同一条命令，**必须崩** ——
   没有这一条，「修好了」只证明现在没红，证明不了这一条判据红得起来。

## 退出码

    0 ＝ 全绿   1 ＝ 判据红   3 ＝ 仪器缺输入（缓存里找不到可用关卡 / 缺数据文件）

用法：
    python tools\\check_cli_go.py
    python tools\\check_cli_go.py --mutate
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
GAMEDATA = ROOT / "data" / "gamedata"
RAW = GAMEDATA / "map.ark-nights.com" / "levels" / "enemydata" / "enemy_database.json"


def cached_levels() -> list[str]:
    """缓存里取得到的关卡 id（与总闸同一口径：索引给 data_path，本地缓存决定跑得动哪些）。"""
    idx_p = GAMEDATA / "_level_index.json"
    if not idx_p.is_file():
        return []
    idx = json.loads(idx_p.read_text(encoding="utf-8"))
    levels_dir = GAMEDATA / "map.ark-nights.com" / "levels"
    return sorted(lid for lid, e in idx.items()
                  if (levels_dir / e["data_path"]).is_file())


def missing_weight_keys() -> set[str]:
    """游戏本体里**没覆写** `massLevel` 的敌人键（`m_defined != true`）。"""
    d = json.loads(RAW.read_text(encoding="utf-8"))
    out: set[str] = set()
    for e in d["enemies"]:
        defined = False
        for lvl in e["Value"]:
            ml = (lvl["enemyData"].get("attributes") or {}).get("massLevel")
            if isinstance(ml, dict) and ml.get("m_defined"):
                defined = True
                break
        if not defined:
            out.add(e["Key"])
    return out


def level_enemy_keys(level_id: str) -> set[str]:
    """某一关引用到的敌人键（从关卡 JSON 的 `enemy_*` 串里现取）。"""
    idx = json.loads((GAMEDATA / "_level_index.json").read_text(encoding="utf-8"))
    p = GAMEDATA / "map.ark-nights.com" / "levels" / idx[level_id]["data_path"]
    txt = p.read_text(encoding="utf-8")
    keys: set[str] = set()
    i = 0
    while True:
        i = txt.find('"enemy_', i)
        if i < 0:
            break
        j = txt.find('"', i + 1)
        keys.add(txt[i + 1:j])
        i = j
    return keys


def run_cli(level_id: str, patch_old: bool = False) -> subprocess.CompletedProcess:
    """跑 `python -m ak_tactic stage <关卡>`；`patch_old` 时把 `_num` 换回旧写法。"""
    if patch_old:
        code = (
            "import sys, ak_tactic.cli as c\n"
            "c._num = lambda v, s='': f'{v:g}{s}'\n"
            "sys.exit(c.main(['stage', %r]))\n" % level_id
        )
        cmd = [PY, "-X", "utf8", "-c", code]
    else:
        cmd = [PY, "-X", "utf8", "-m", "ak_tactic", "stage", level_id]
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def main() -> int:
    mutate = "--mutate" in sys.argv
    problems: list[str] = []

    if not RAW.is_file():
        print("SUITE_INPUT_MISSING %s" % RAW.relative_to(ROOT))
        return 3
    lvls = cached_levels()
    if not lvls:
        print("SUITE_INPUT_MISSING 缓存可达的关卡为 0（%s）" % GAMEDATA.relative_to(ROOT))
        return 3

    miss = missing_weight_keys()
    print("现算：重量等级**没覆写**的敌人 %d 个（取证范围＝ %s）"
          % (len(miss), RAW.relative_to(ROOT)))

    pos = con = None
    pos_hit: set[str] = set()
    for lid in lvls:
        ks = level_enemy_keys(lid)
        hit = ks & miss
        if hit and pos is None:
            pos, pos_hit = lid, hit
        elif not hit and con is None:
            con = lid
        if pos and con:
            break
    if pos is None or con is None:
        print("SUITE_INPUT_MISSING 缓存里找不出「有缺值敌人」与「没有缺值敌人」的一对关卡"
              "（正例=%r 对照=%r）" % (pos, con))
        return 3

    #: ---- 正例：引用缺值敌人的那一关，必须 rc=0 且把缺值印成「—」----
    r = run_cli(pos)
    dashes = sum(1 for ln in r.stdout.splitlines() if "重量 —" in ln)
    print("正例 %-14s rc=%d  「重量 —」%d 条 / 引用缺值敌人 %d 个"
          % (pos, r.returncode, dashes, len(pos_hit)))
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or [""]
        problems.append("正例 %s rc=%d —— 命令面在缺值输入上崩了：%s"
                        % (pos, r.returncode, tail[0][:100]))
    if dashes != len(pos_hit):
        problems.append("正例 %s 印出的「重量 —」%d 条，而这一关引用的缺值敌人是 %d 个"
                        "（两处必须相等，否则是印少了或印多了）"
                        % (pos, dashes, len(pos_hit)))

    #: ---- 对照：不引用缺值敌人的那一关，必须一个「—」都不印，且印得出数字 ----
    r2 = run_cli(con)
    d2 = sum(1 for ln in r2.stdout.splitlines() if "重量 —" in ln)
    nums = sum(1 for ln in r2.stdout.splitlines() if "重量 " in ln and "—" not in ln)
    print("对照 %-14s rc=%d  「重量 —」%d 条 / 有数字的 %d 行"
          % (con, r2.returncode, d2, nums))
    if r2.returncode != 0:
        problems.append("对照 %s rc=%d —— 正常关卡也崩了" % (con, r2.returncode))
    if d2 != 0:
        problems.append("对照 %s 印出了 %d 条「重量 —」，而它不引用缺值敌人" % (con, d2))
    if nums == 0:
        problems.append("对照 %s 一行数字都没印 —— 这条对照没有行使过" % con)

    #: ---- 反向守卫：把 `_num` 换回旧写法，同一条命令必须崩 ----
    if mutate:
        r3 = run_cli(pos, patch_old=True)
        crashed = r3.returncode != 0 and "NoneType" in (r3.stderr or "") + (r3.stdout or "")
        print("注入：把 `_num` 换回 `{%s:g}` 再跑 %s ⇒ rc=%d，崩在 NoneType=%s"
              % ("v", pos, r3.returncode, crashed))
        if not crashed:
            problems.append("注入「换回旧写法」后 **没有崩**（rc=%d）—— 这条判据红不起来，"
                            "它的绿是零信息量的绿" % r3.returncode)

    print()
    if problems:
        print("结论：**未通过**（%d 处）" % len(problems))
        for p in problems:
            print("  ✗ %s" % p)
        return 1
    print("结论：命令面在缺值输入下不崩（正例 %s ／ 对照 %s）%s"
          % (pos, con, "；反向守卫成立" if mutate else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
