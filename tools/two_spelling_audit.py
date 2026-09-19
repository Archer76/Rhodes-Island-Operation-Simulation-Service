#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「双写法且有信息」全库清单 —— 给第四批选人用的**实操可做性**证据。

判据（PM 2026-09-20 裁定）：同一概念出现两种写法（`$X` 与 `X`，或 `attack@X` 与 `X`），
**且至少一条带真值**。

## 键空间不另立一套（这是本工具的第一条纪律）
判「这个键有没有人读」的尺子在 `tools/audit_coverage.py`：`is_read()`（`:50-69`）依次试
① 整键字面量 ② 方括号变体里的条件名 ③ **`key.rsplit("@", 1)[-1]`**。第 ③ 条意味着源码里写一个
`"attack_range_id"` 字面量会**同时**让 `attack@attack_range_id` 与 `$attack@attack_range_id`
判成「有人读」——**一个键族共用一把尺子**。
而审计收的键来自**模型层的黑板字典**（`keys_of():149-180` 迭代 `lv.blackboard` / `t.blackboard`），
那份字典由 `operator/talent._blackboard:139-147` 把 DB 行摊平而来：数值键直放，
**带 `valueStr` 的另存一份 `$键名`**（技能那边同理）。本工具照同一条规则合成 `$` 侧，
并用 `--check` 拿审计自己的 `keys_of()` 逐键对拍（键集不等就 rc≠0）。

## 三档
* **A 干净可做**：这个概念**已经有消费点**（`core` 或某个成员的字面量在源码里出现）
  ＋ 有成员欠账 ＋ 有成员带真值 ⇒ 接线＝**扩一处已存在的查表**；
* **B 假欠账**：同上但没有一侧带真值（两侧都是 0／空）⇒ 接上去不改行为，属审计口径问题；
* **C 无消费点**：这个概念在本树源码里**一次都没出现** ⇒ 要新机制，**不是干净件**。

用法：
    python tools/two_spelling_audit.py --check 予愿安洁莉娜      # 先对拍键空间
    python tools/two_spelling_audit.py                          # 出清单
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import re
import sqlite3
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "akdb.sqlite"
RANGES = ROOT / "data" / "ranges.json"

#: 概念 → （可见量落点，接线后往哪边动）。落点都是本树读过的：
#: 规格字段在 `ak_tactic/simgo/spec.py` 的 `_operator_spec`（`:702-716`）与 `simgo/skills._profile`；
#: 状态/位移类在 `rios-sim/control.go` 等机制层。
#: 标「须对照实验」的＝落点已知但方向要靠一次判据③ 定（**不许猜**）。
OBSERVABLE: dict[str, tuple[str, str]] = {
    "atk_scale": ("active.atk_scale（伤害倍率）", "伤害读数按倍率变"),
    "atk_scale_2": ("active.atk_scale_2（第二倍率槽）", "第二段伤害"),
    "atk_scale_other": ("active.atk_scale_other", "另一套数值的伤害"),
    "final_hit_scale": ("末段倍率", "最后一击伤害"),
    "landing_scale": ("落地那一击倍率", "落地伤害"),
    "heal_scale": ("治疗倍率", "回血读数"),
    "atk": ("active.atk（面板）", "攻击力"),
    "def": ("active.def（面板）", "防御力"),
    "res": ("active.res（面板）", "法抗"),
    "attack_speed": ("active.interval（攻击间隔）", "攻速↑ ⇒ 间隔↓ ⇒ 出手次数"),
    "base_attack_time": ("active.interval", "基础间隔"),
    "attack_interval": ("active.interval", "攻击间隔"),
    "max_target": ("active.max_target", "一次出手命中数"),
    "max_target_heal": ("active.max_target（治疗）", "一次治疗覆盖人数"),
    "trigger_time": ("active.ammo（弹药）", "技能可打几发"),
    "ammo": ("active.ammo", "弹药数"),
    "range_id": ("规格 range 格表", "范围格数（扩大/缩小，须与正文比对）"),
    "attack_range_id": ("规格 range 格表", "范围格数（扩大/缩小，须与正文比对）"),
    "duration": ("技能/状态时长", "持续秒数"),
    "move_speed": ("敌人移速（POS 轨迹）", "推进快慢 ⇒ 到终点时刻"),
    "damage_resistance": ("承伤（减伤）", "受到的伤害"),
    "mass_level": ("重量（位移/失重判定）", "位移等级与按重量分支"),
    "sp_cost": ("开技时刻", "技能何时开启"),
    "init_sp": ("开技时刻", "初动"),
    "increment": ("SP 增速", "开技时刻"),
    "max_charge": ("充能层数", "技能层数"),
    "times": ("段数", "一次出手的伤害笔数"),
    "multi_hit": ("段数", "同上"),
    "repeat_hits": ("段数", "同上"),
    "volley_arrows": ("箭数", "一次出手的箭数"),
    "true_damage": ("伤害类型", "物理/法术/真实"),
    "cost": ("费用", "部署费用"),
    "max_hp": ("active.max_hp", "血量"),
    "height_offset": ("**待取证**", "**量纲未知，先别接**"),
}

#: 这些 `core` 的「另一侧」是**字符串**（范围代号、标记），不是能相减的数。
STRINGY = {"range_id", "attack_range_id", "ignore_build_type_target_range", "projectile",
           "tile_key", "buff_id", "token_key"}

#: 逐族裁定表 —— **由人读过证据后写死**，不由机械规则猜。
#: 键＝`core`；值＝(档, 为什么)。五档含义见 `write_md` 的报告头。
VERDICT: dict[str, tuple[str, str]] = {
    # ── A 档机械结果里的 7 个：逐条看原文行后**全部判成假欠账 / 非干员行** ──
    "prob": ("B", "`$prob` 与裸 `attack@prob`/`prob` **同值**（实测 4 处同值、0 处不同值）；"
                   "而且 `$prob` 只出现在**装置**行，干员侧（Misery）根本没有 `$` 侧 ⇒ 假欠账"),
    "token_key": ("E", "裸 `talent@token_key` 的数字是 0、真值在 `valueStr`（真 token id），"
                       "`$` 侧与它**同值** ⇒ 同一量的两种写法；且 `ak_tactic/gamedata/enemy.py:481` "
                       "用 `k.endswith(\"token_key\")` **后缀匹配**读它 ⇒ 审计的字面量尺子看不见这种读法"),
    "branch_id": ("D", "43 行**全是装置**（唤血祭坛／天桩／核心增幅器…），零干员行；`$` 侧与裸侧同值。"
                       "`frontend/devices.py:189` 那句 `kb.get(\"key\") == \"branch_id\"` 是**真读点**"
                       "（读裸键），与 `$` 侧无关"),
    "enemy_key": ("D", "38 行全是装置；同值；`gamedata/enemy.py:466` 另有 `k.endswith(\"enemy_key\")` 后缀读法"),
    "equip": ("D", "1 行装置；同值；命中处是 `ak_tactic/skland.py` 取数层的字段名（**同名不同义**）"),
    "key": ("D", "1 行装置；同值；78 处命中是解析黑板条目时的 `item.get(\"key\")`（**同名不同义**）"),
    "unlock": ("D", "5 行装置；同值；命中处是 `ak_tactic/prts/operator.py` 取数层字段名（**同名不同义**）"),
    # ── C 档里**有干员行**的那 7 个（第四批真正会碰到的） ──
    "projectile_range": ("C", "4 位干员（引星棘刺／机械师／艾拉…）、50 行；本树**没有任何** "
                              "`projectile_range` 读点 ⇒ 要新读点；弹道机制在 `rios-sim/` 侧（机制层）"),
    "atk_magic": ("C", "雷狼龙S空爆 1 位、10 行；无读点 ⇒ 要新读点（法术附加伤害那一族）"),
    "attack_range_id": ("C", "予愿安洁莉娜 1 位、10 行；**已按判据③判红**：`x-4` ＝ 周围 8 格、"
                             "接进 `_range_override` 会让范围 19 格 → 9 格，与正文「扩大」**方向相反** ⇒ "
                             "**不许接**（`docs/uncertainties.md` 第三十节）"),
    "burn.atk_scale": ("C", "火哨 1 位、10 行；无读点 ⇒ 要新读点"),
    "chain.atk_scale": ("C", "乌啾；无读点 ⇒ 要新读点（链式那一家族）"),
    "chain.atk_scale_2": ("C", "乌啾；无读点 ⇒ 要新读点"),
    "chain.max_target": ("C", "乌啾；无读点 ⇒ 要新读点"),
    "damage_addition": ("C", "戴菲恩 1 位、10 行；无读点 ⇒ 要新读点"),
    "take_extra_enemy_key": ("C", "隐德来希 1 位；无读点 ⇒ 要新读点"),
}

#: `k.endswith("X")` 这类**后缀匹配读法**：审计的 `is_read` 只认整键／去前缀／方括号条件
#: 三种字面量，**看不见后缀匹配** ⇒ 这类"无人读"可能是尺子的问题，不是真没人读。
_SUFFIX_RE = re.compile(r"""endswith\(\s*["']([^"']+)["']""")

_RANGE_CODE = re.compile(r"^[0-9a-zA-Z]+-[0-9]+$")


def load_audit():
    spec = importlib.util.spec_from_file_location(
        "audit_coverage", ROOT / "tools" / "audit_coverage.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)              # type: ignore[union-attr]
    return mod


def literal_locations(audit) -> tuple[dict[str, list[str]], dict[str, str]]:
    """字面量 → 出现位置（`ak_tactic/**/*.py`，与 `source_literals()` 同一批文件）。

    同时返回 `{位置: 该行原文}`：**只看命中数会骗人**——通用词（`key`/`unlock`/`equip`）
    的字面量到处都是（解析黑板时的 `it.get("key")` 就是一例），必须能把原文行摆出来逐条看。
    """
    out: dict[str, list[str]] = defaultdict(list)
    texts: dict[str, str] = {}
    for p in (ROOT / "ak_tactic").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(ROOT).as_posix()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            for lit in audit._LITERAL.findall(line):        # noqa: SLF001
                out[lit].append(f"{rel}:{i}")
                texts.setdefault(f"{rel}:{i}", line.strip()[:110])
    return out, texts



def suffix_reads() -> dict[str, list[str]]:
    """`endswith("X")` 的后缀匹配读法 → {后缀字面量: 位置}（同一批源文件）。"""
    out: dict[str, list[str]] = defaultdict(list)
    for p in (ROOT / "ak_tactic").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(ROOT).as_posix()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            for suf in _SUFFIX_RE.findall(line):
                out[suf].append(f"{rel}:{i}")
    return out


def core(key: str) -> str:
    """与 `is_read` 第 ③ 条同源：去 `$` 前缀，再取最后一个 `@` 之后。"""
    return key.lstrip("$").rsplit("@", 1)[-1]


def parse_blackboard(raw: str | None) -> dict[str, tuple[object, object]]:
    """黑板 → {键: (数值, valueStr)}，**照 `operator/talent._blackboard:139-147` 的规则摊平**。

    * 数组形式（技能/天赋）：`[{"key":..,"value":..,"valueStr":..}, ...]`；
    * 对象形式（有的特性就是这种）：`{"height_offset": 0.8}` —— 只按数组解析会**静默读成空**
      （2026-09-20 实测踩过：读不出来与本来就是空被压成一个显示）；
    * 带 `valueStr` 的键**另存一份 `$键名`**（判据尺子认这个写法）。
    """
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except Exception:                                          # noqa: BLE001
        return {}
    out: dict[str, tuple[object, object]] = {}
    for it in (obj if isinstance(obj, list) else [obj]):
        if not isinstance(it, dict):
            continue
        pairs = ([(str(it.get("key") or ""), it.get("value"), it.get("valueStr"))]
                 if "key" in it else [(str(k), v, None) for k, v in it.items()])
        for k, v, vs in pairs:
            if not k:
                continue
            out[k] = (v, vs)
            if vs is not None:
                out[f"${k}"] = (None, vs)
    return out


def has_info(val: object, vs: object) -> bool:
    if vs is not None and str(vs).strip() not in ("", "0"):
        return True
    try:
        return float(val or 0.0) != 0.0
    except (TypeError, ValueError):
        return bool(val)


def _cols(con: sqlite3.Connection, t: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({t})")]


def db_rows(con: sqlite3.Connection, char_id: str | None = None) -> list[dict]:
    """全库黑板行：技能（按 char 归属）/ 天赋 / 特性。`char_id` 给了就只取那一位。"""
    out: list[dict] = []
    where = "WHERE os.char_id = ?" if char_id else ""
    args = (char_id,) if char_id else ()
    bb = "blackboard_raw" if "blackboard_raw" in _cols(con, "skill_level") else "blackboard"
    for r in con.execute(
            f"SELECT os.char_id, sl.skill_id, sl.level, sl.name, sl.{bb} "
            f"FROM skill_level sl JOIN operator_skill os ON os.skill_id = sl.skill_id {where}",
            args):
        out.append({"char_id": r[0], "kind": "技能", "owner": r[1], "level": r[2],
                    "row_name": r[3], "bb": parse_blackboard(r[4])})
    where = "WHERE char_id = ?" if char_id else ""
    tb = "blackboard_raw" if "blackboard_raw" in _cols(con, "operator_talent") \
        else "blackboard"
    for r in con.execute(
            f"SELECT char_id, group_index, cand_index, name, {tb} FROM operator_talent {where}",
            args):
        out.append({"char_id": r[0], "kind": "天赋", "owner": f"天赋{r[1]}-{r[2]}",
                    "level": None, "row_name": r[3], "bb": parse_blackboard(r[4])})
    for r in con.execute(
            f"SELECT char_id, cand_index, unlock_phase, override_description, blackboard "
            f"FROM operator_trait {where}", args):
        out.append({"char_id": r[0], "kind": "特性", "owner": f"特性{r[1]}", "level": r[2],
                    "row_name": (r[3] or "")[:30], "bb": parse_blackboard(r[4])})
    return out


def real_operators(con: sqlite3.Connection) -> set[str]:
    """真干员（`operator` 表）。`operator_skill` 里还混着**召唤物/装置**（`token_*`），
    它们的 `SkillBook` 会直接抛错，统计时必须与干员分开。"""
    try:
        return {r[0] for r in con.execute("SELECT char_id FROM operator")}
    except Exception:                                          # noqa: BLE001
        return set()


def operator_names(con: sqlite3.Connection) -> dict[str, str]:
    out: dict[str, str] = {}
    for t, a, b in (("operator", "char_id", "name"), ("operator_phase", "char_id", "name")):
        try:
            for cid, nm in con.execute(f"SELECT {a}, {b} FROM {t}"):
                out.setdefault(cid, nm)
        except Exception:                                      # noqa: BLE001
            pass
    return out


def my_keys(con: sqlite3.Connection, char_id: str) -> set[str]:
    """本工具摊出来的键集（用来与审计的 `keys_of()` 对拍）。"""
    return {k for r in db_rows(con, char_id) for k in r["bb"]}


def check_space(cid: str) -> int:
    """对拍键空间：本工具 vs 审计 `keys_of()`。

    `keys_of(cid)` 返回 `(技能键, 天赋键, 特性键)`，元素是 **`(来源说明, 键名)`**（`:152`），
    且**每个技能只取最高等级**（`sk.level(level=7, mastery=3)`，`:156`）。本工具取**全等级**，
    因此正确关系是「**本工具 ⊇ 审计**」：
      * 硬判据：**审计看得见的键，本工具一个都不许漏**（漏了就 rc≠0）；
      * 超集部分逐条归因（低等级 / 其他天赋候选），打印出来给人看，而不是当成「一致」。
    """
    audit = load_audit()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    mine = my_keys(con, cid)
    rows = db_rows(con, cid)
    con.close()

    sk, tal, tr = audit.keys_of(cid)
    theirs = {k for _, k in [*sk, *tal, *tr]}
    print(f"  键空间对拍 {cid}：本工具(全等级) {len(mine)} 键 / "
          f"审计(最高等级) {len(theirs)} 键")
    missing = sorted(theirs - mine)
    extra = sorted(mine - theirs)
    if missing:
        print(f"    ❌ 审计看得见而我漏了 {len(missing)} 个：{missing[:8]}")
    #: 超集归因：看这个键是从哪几行来的（等级 < 最高 就是可解释的）
    explain: dict[str, list[str]] = {}
    for k in extra:
        explain[k] = sorted({f"{r['kind']}·{r['owner']}·lv{r['level']}"
                             for r in rows if k in r["bb"]})
    if extra:
        print(f"    超集 {len(extra)} 个（审计只取最高等级 ⇒ 应为低等级/其他候选），例：")
        for k in extra[:6]:
            print(f"      {k}  来自 {explain[k][:3]}")
    ok = not missing
    print(f"  ⇒ {'✅ 审计键集被完整覆盖' if ok else '❌ 有漏项，不许出清单'}"
          f"（超集 {len(extra)} 个已归因）")
    return 0 if ok else 1


def build(con: sqlite3.Connection, lits: set[str], locs: dict[str, list[str]],
          texts: dict[str, str], SUFFIX: dict[str, list[str]]) -> list[dict]:
    nm = operator_names(con)
    real = real_operators(con)
    ranges = json.loads(RANGES.read_text(encoding="utf-8")) if RANGES.exists() else {}
    fams: dict[str, dict] = defaultdict(
        lambda: {"members": set(), "rows": [], "info": set()})
    for r in db_rows(con):
        by_core: dict[str, list[str]] = defaultdict(list)
        for k in r["bb"]:
            by_core[core(k)].append(k)
        for c, ks in by_core.items():
            if len(set(ks)) < 2:                       # 只有一种写法 ⇒ 不是「双写法」
                continue
            f = fams[c]
            f["members"].update(ks)
            for k in ks:
                if has_info(*r["bb"][k]):
                    f["info"].add(k)
            f["rows"].append({
                "char_id": r["char_id"], "name": nm.get(r["char_id"], r["char_id"]),
                "is_op": r["char_id"] in real and not r["char_id"].startswith(("token_", "trap_")),
                "kind": r["kind"], "owner": r["owner"], "row_name": r["row_name"],
                "keys": {k: {"value": r["bb"][k][0], "valueStr": r["bb"][k][1]} for k in ks},
                "unread": [k for k in ks if not audit_is_read(k, lits)],
                "range_codes": sorted({str(r["bb"][k][1]) for k in ks
                                       if r["bb"][k][1] and _RANGE_CODE.match(str(r["bb"][k][1]))}),
            })

    out = []
    for c, f in fams.items():
        members = sorted(f["members"])
        unread = sorted({k for row in f["rows"] for k in row["unread"]})
        if not unread:
            continue                                   # 没欠账 ⇒ 不进清单
        info = sorted(f["info"])
        where = sorted({*(locs.get(c) or []),
                        *[x for m in members for x in (locs.get(m) or [])]})
        consumed = bool(locs.get(c)) or any(locs.get(m) for m in members)
        obs, how = OBSERVABLE.get(c, ("**待取证**（按正文追这个概念在本树的落点）",
                                      "**须先取证**"))
        #: 方向：两侧都是数就相减；一侧是字符串就按「这是另一个量」处理，不许猜数值方向。
        nums = []
        for row in f["rows"]:
            vals = {k: row["keys"][k] for k in row["unread"]}
            if all(isinstance(v.get("value"), (int, float)) for v in vals.values()):
                nums.append(vals)
        direction = how
        if c in STRINGY or any(k.startswith("$") for k in unread):
            direction = f"该概念的**字符串侧**（`$` 写法）没人读；接上后 {obs} 由正文决定要不要变"
        elif nums:
            direction = how
        miss = sorted({code for row in f["rows"] for code in row["range_codes"]
                       if code not in ranges or not ranges.get(code)})
        #: `$` 侧与裸侧是不是同一个值：同值 ⇒ 只清账、不改行为（假欠账的判据）
        same_v = diff_v = 0
        for row in f["rows"]:
            bare = {k: v for k, v in row["keys"].items() if not k.startswith("$")}
            strs: set[str] = set()
            for v in bare.values():
                if isinstance(v["value"], (int, float)) and v["value"] is not None:
                    fv = float(v["value"])
                    strs.add(str(int(fv)) if fv == int(fv) else str(fv))
                if v["valueStr"]:
                    strs.add(str(v["valueStr"]))
            for k, v in row["keys"].items():
                if k.startswith("$") and v["valueStr"] is not None:
                    if str(v["valueStr"]) in strs:
                        same_v += 1
                    else:
                        diff_v += 1
        has_op = any(r["is_op"] for r in f["rows"])
        suf = sorted(set(SUFFIX.get(c, [])) | {x for m in members for x in SUFFIX.get(m, [])})
        mech = ("D" if not has_op else
                "A" if (consumed and info and diff_v) else
                "B" if consumed else "C")
        v = VERDICT.get(c)
        out.append({
            "core": c, "tier": (v[0] if v else mech),
            "tier_mech": mech, "verdict_why": (v[1] if v else "（未逐条取证）"),
            "same_value": same_v, "diff_value": diff_v, "suffix_reads": suf, "has_op": has_op,
            "members": members, "unread": unread, "truth_side": info,
            "consumption_points": where[:5], "consumption_hits": len(where),
            "consumption_lines": [f"{w} ｜ {texts.get(w, '')}" for w in where[:8]],
            "observable": obs, "direction": direction,
            "n_rows": len(f["rows"]),
            "chars": sorted({f"{r['name']}｜{r['char_id']}" for r in f["rows"] if r["is_op"]}),
            "chars_other": sorted({f"{r['name']}｜{r['char_id']}"
                                   for r in f["rows"] if not r["is_op"]}),
            "kind_mix": sorted({r["kind"] for r in f["rows"]}),
            "range_codes_missing": miss, "rows": f["rows"],
        })
    out.sort(key=lambda d: ({"A": 0, "B": 1, "E": 2, "C": 3, "D": 4}.get(d["tier"], 9),
                            -len(d["chars"]), d["core"]))
    return out


_AUDIT_IS_READ = None


def audit_is_read(key: str, lits: set[str]) -> bool:
    global _AUDIT_IS_READ
    if _AUDIT_IS_READ is None:
        _AUDIT_IS_READ = load_audit().is_read
    return _AUDIT_IS_READ(key, lits)


def _git(*args: str) -> str:
    import subprocess
    try:
        p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
        return p.stdout.decode("utf-8", "replace").strip()      # CP936 错解的解药
    except Exception:                                          # noqa: BLE001
        return "?"


def write_md(rep: list[dict], lits: set[str], out: pathlib.Path, by: str,
             checks: list[str]) -> None:
    a = [d for d in rep if d["tier"] == "A"]
    b = [d for d in rep if d["tier"] == "B"]
    e = [d for d in rep if d["tier"] == "E"]
    cc = [d for d in rep if d["tier"] == "C"]
    dd = [d for d in rep if d["tier"] == "D"]
    per_op: dict[str, list[dict]] = defaultdict(list)
    for d in rep:
        if d["tier"] not in ("A", "B", "C", "E"):
            continue
        for c in d["chars"]:
            per_op[c].append(d)

    L: list[str] = []
    L.append("# 双写法且有信息 —— 全库清单（第四批选人的「实操可做性」证据）\n")
    L.append("> **本文件由脚本生成，不要手改**：`python tools/two_spelling_audit.py`。"
             "改口径请改脚本（或改题源），改完重生成。\n")
    L.append("## 生成方式（元数据，便于复核）\n")
    L.append(f"* 工具：`tools/two_spelling_audit.py`；运行者：**{by}**")
    L.append(f"* 所属树 HEAD：`{_git('rev-parse', '--short', 'HEAD')}`；"
             f"工作区（`ak_tactic/`＋`tools/`）"
             f"{'**dirty**' if _git('status', '--porcelain', '--', 'ak_tactic/', 'tools/') else '干净'}")
    L.append(f"* 键空间对拍（vs 审计 `keys_of()`）：{'；'.join(checks) or '未跑'}")
    L.append("* **判据来源**：`tools/audit_coverage.py:50-69` 的 `is_read()`"
             "（整键 → 方括号条件名 → `key.rsplit('@', 1)[-1]`）；"
             "键空间＝DB 黑板行摊平后**另存 `$键名`**（`ak_tactic/operator/talent.py:139-147`）。\n")
    L.append("## 口径（五档，先说清「这一列数的是什么」）\n")
    L.append("| 档 | 家族数 | 其中有干员行 | 含义 |")
    L.append("|---|---|---|---|")
    L.append(f"| **A 干净可做** | {len(a)} | {sum(1 for d in a if d['has_op'])} | "
             "有干员行 ＋ 有现成消费点 ＋ `$` 侧与裸侧**不同值** ⇒ 接线＝扩一处已存在的查表，"
             "**且会改行为** |")
    L.append(f"| **B 假欠账（同值）** | {len(b)} | {sum(1 for d in b if d['has_op'])} | "
             "有消费点，但 `$` 侧与裸侧**同值** ⇒ 接上**不改行为** |")
    L.append(f"| **E 口径·后缀读法** | {len(e)} | {sum(1 for d in e if d['has_op'])} | "
             "源码用 `k.endswith(…)` 读它，`is_read` 的字面量尺子**看不见**这种读法 |")
    L.append(f"| **C 要新读点** | {len(cc)} | {sum(1 for d in cc if d['has_op'])} | "
             "本树**没有任何**读点 ⇒ 要新机制／新分支，不是干净件 |")
    L.append(f"| **D 装置·召唤物** | {len(dd)} | 0 | 行都在装置／召唤物上（**无干员行**）⇒ "
             "不属于第四批选人范围 |")
    L.append("\n**读法**：一个「家族」＝ 同一个 `core` 下的多种写法。"
             "`core(X)` ＝ 去 `$` 前缀、取最后一个 `@` 之后——**与 `is_read` 第 ③ 条同一把尺子**，"
             "所以在源码里写一个 `core` 字面量会**同时**把这族的成员都判成「有人读」。\n")

    L.append("## 一、结论先说（三句）\n")
    L.append(f"1. **A 档 ＝ {len(a)}**：全库（{len(rep)} 族）扫下来，**没有一族**满足"
             "「有干员行 ＋ 有现成消费点 ＋ 两侧值不同」。")
    L.append("2. 机械规则本来报了 7 个 A，**逐条看消费点原文行后全部推翻**：5 个根本没有干员行"
             "（是装置／召唤物），`key`／`equip`／`unlock` 的命中是解析黑板或取数层的**同名不同义**，"
             "`prob`／`token_key` 是**同值**。")
    L.append(f"3. ⇒ 按「双写法且有信息」这条判据选人：**它不产出干净可做的人**。"
             f"有干员行的家族只有 {sum(1 for d in rep if d['has_op'])} 个，其中 A 档 0 个，"
             "其余是 C（要新读点）或口径问题。\n")

    L.append("## 二、A 档逐条（7 条全部判成假欠账／非干员行，证据在此）\n")
    if not a:
        L.append("（空）\n")
    for d in a:
        ops = d["chars"]
        L.append(f"### `{d['core']}`　干员行 {len(ops)} 位 / 总 {d['n_rows']} 行"
                 f"　**裁定：{d['tier']}**\n")
        L.append(f"* **裁定理由**：{d['verdict_why']}")
        L.append(f"* **两种写法**：欠账侧 `{'`、`'.join(d['unread'])}`"
                 f"；真值侧 `{'`、`'.join(d['truth_side']) or '（无）'}`")
        L.append(f"* **`$` 侧 vs 裸侧**：同值 **{d['same_value']}** 处／不同值 **{d['diff_value']}** 处"
                 f"（同值＝只清账不改行为）")
        L.append(f"* **消费点**（{d['consumption_hits']} 处；原文行摆出来，便于判断是不是黑板读点）：")
        for ln in d.get("consumption_lines", [])[:8]:
            L.append(f"    * `{ln}`")
        L.append(f"* **可见量与方向**：{d['observable']}　——　{d['direction']}")
        L.append(f"* **样例值**：" + "；".join(
            f"{r['name']}·{r['kind']}·{r['owner']} → " +
            ", ".join(f"`{k}`={v['value'] if v['value'] is not None else repr(v['valueStr'])}"
                      for k, v in list(r["keys"].items())[:4])
            for r in d["rows"][:3]))
        if ops:
            L.append(f"* **干员**（前 8）：{'、'.join(ops[:8])}{'…' if len(ops) > 8 else ''}")
        else:
            L.append("* **干员**：**无**（全是装置／召唤物行）")
        L.append("")

    L.append("## 三、B 档：假欠账（有消费点，但两侧同值）\n")
    L.append("| core | 欠账侧 | 同值/不同值 | 干员行 | 裁定理由 |")
    L.append("|---|---|---|---|---|")
    for d in b:
        L.append(f"| `{d['core']}` | `{'`、`'.join(d['unread'])}` | "
                 f"{d['same_value']}/{d['diff_value']} | {len(d['chars'])} | {d['verdict_why']} |")

    L.append("\n## 四、E 档：口径·后缀匹配读法（`is_read` 看不见的那一类）\n")
    L.append("审计的 `is_read()`（`tools/audit_coverage.py:50-69`）只试三种字面量：整键、"
             "方括号里的条件名、`key.rsplit('@',1)[-1]`。**后缀匹配读法不在其中**——"
             "下面这些键的「没人读」是**尺子的问题**，不是真没人读。\n")
    if not e:
        L.append("（空）\n")
    for d in e:
        L.append(f"### `{d['core']}`　干员行 {len(d['chars'])} 位 / 总 {d['n_rows']} 行\n")
        L.append(f"* **裁定理由**：{d['verdict_why']}")
        L.append(f"* **后缀读法命中**：" + "、".join(f"`{x}`" for x in d["suffix_reads"][:6]) +
                 ("（无）" if not d["suffix_reads"] else ""))
        L.append(f"* **`$` 侧 vs 裸侧**：同值 {d['same_value']} / 不同值 {d['diff_value']}")
        L.append(f"* **样例**：" + "；".join(
            f"{r['name']}·{r['owner']} → " + ", ".join(
                f"`{k}`={v['value'] if v['value'] is not None else repr(v['valueStr'])}"
                for k, v in list(r["keys"].items())[:3])
            for r in d["rows"][:2]))
        L.append("")

    L.append("## 五、C 档：要新读点（**有干员行的排前面**——这是第四批会碰到的）\n")
    L.append("| core | 干员行 | 欠账侧 | 总行数 | 样例干员 | 裁定理由 |")
    L.append("|---|---|---|---|---|---|")
    for d in sorted(cc, key=lambda x: (not x["has_op"], -len(x["chars"]), x["core"]))[:70]:
        L.append(f"| `{d['core']}` | {'**有**' if d['has_op'] else '无'} | "
                 f"`{'`、`'.join(d['unread'][:3])}` | {d['n_rows']} | "
                 f"{'、'.join(d['chars'][:3]) or '（无）'} | {d['verdict_why']} |")
    if len(cc) > 70:
        L.append(f"| … | | 其余 {len(cc) - 70} 个见 JSON | | | |")

    L.append("\n## 六、D 档：装置·召唤物行（非干员，供引擎侧参考）\n")
    L.append("| core | 总行数 | 欠账侧 | 同值/不同值 | 样例 |")
    L.append("|---|---|---|---|---|")
    for d in dd:
        L.append(f"| `{d['core']}` | {d['n_rows']} | `{'`、`'.join(d['unread'][:2])}` | "
                 f"{d['same_value']}/{d['diff_value']} | "
                 f"{'、'.join(r['name'] for r in d['rows'][:3])} |")

    miss = [d for d in rep if d["range_codes_missing"]]
    L.append("\n## 七、★ 第四类「读写不到」（单独标出来对账）\n")
    L.append("`head核查` 报的那一类：范围代号在 `data/ranges.json` 里**没有或为空** —— "
             "那不是「没人读」，是「读了也读不到」。它修完 `grid.py` 后这类应自己消失一批。\n")
    if miss:
        L.append("| core | 缺的代号 | 干员 |")
        L.append("|---|---|---|")
        for d in miss:
            L.append(f"| `{d['core']}` | `{'`、`'.join(d['range_codes_missing'])}` | "
                     f"{'、'.join(d['chars'][:4])} |")
    else:
        L.append("（本次扫描没命中）\n")

    L.append("\n## 八、按干员聚合（给第四批选人用）\n")
    L.append("| 干员 | 欠账家族数 | 家族（带档） |")
    L.append("|---|---|---|")
    for c, ds in sorted(per_op.items(), key=lambda kv: -len(kv[1])):
        L.append(f"| {c} | {len(ds)} | "
                 f"{'、'.join('`' + d['core'] + '`(' + d['tier'] + ')' for d in ds)} |")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", metavar="干员名或char_id", default=None)
    ap.add_argument("--sample-check", type=int, default=0,
                    help="在 N 位干员上抽验键空间（写成「抽 N 位逐位相同」，不写成全称）")
    ap.add_argument("--by", default="未署名", help="运行者署名（生成物元数据不许写死）")
    ap.add_argument("--out", default="out/backend2-b1/two-spelling.json")
    ap.add_argument("--md", default="docs/two-spelling-audit.md")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    if args.check:
        nm = operator_names(con)
        cid = args.check if args.check.startswith("char_") else \
            next((c for c, n in nm.items() if n == args.check), args.check)
        con.close()
        return check_space(cid)

    audit = load_audit()
    lits = audit.source_literals()
    locs, texts = literal_locations(audit)

    checks: list[str] = []
    if args.sample_check:
        real = real_operators(con)
        #: `operator` 表里有 703 个 `token_*`/`trap_*`（召唤物/装置也住这张表），
        #: 抽验要只看真干员——否则会抽到 `SkillBook` 必然抛错的对象（那不是"不一致"）。
        cids = sorted({c for (c,) in con.execute(
            "SELECT DISTINCT char_id FROM operator_skill")
            if c in real and not c.startswith(("token_", "trap_"))})
        step = max(1, len(cids) // args.sample_check)
        sample = cids[::step][:args.sample_check]
        n_same = n_all = 0
        worst = ""
        for c in sample:
            mine = my_keys(con, c)
            try:
                sk, tal, tr = audit.keys_of(c)
            except Exception as exc:                           # noqa: BLE001
                print(f"  ⚠ keys_of({c}) 抛 {exc.__class__.__name__}，跳过（不当成一致）")
                continue
            theirs = {k for _, k in [*sk, *tal, *tr]}
            n_all += 1
            if mine == theirs:
                n_same += 1
            elif not worst:
                worst = (f"{c}：本工具 {len(mine)} / 审计 {len(theirs)}，"
                         f"仅在本地 {sorted(mine - theirs)[:3]}，"
                         f"仅在审计 {sorted(theirs - mine)[:3]}")
        checks.append(f"抽 {n_all} 位（等距）逐位相同的 {n_same} 位"
                      + (f"；首个不同：{worst}" if worst else ""))
        print(f"  抽样键空间：{n_same}/{n_all} 逐位相同" + (f"；首个不同 {worst}" if worst else ""))
    con.close()

    con2 = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rep = build(con2, lits, locs, texts, suffix_reads())
    con2.close()

    a = [d for d in rep if d["tier"] == "A"]
    b = [d for d in rep if d["tier"] == "B"]
    e = [d for d in rep if d["tier"] == "E"]
    cc = [d for d in rep if d["tier"] == "C"]
    dd = [d for d in rep if d["tier"] == "D"]
    chars_a = sorted({c for d in a for c in d["chars"]})
    print(f"有欠账的双写法家族 {len(rep)} 个 —— 五档（与文档同一口径）：")
    for tag, name, ds in (("A", "干净可做（会改行为）", a), ("B", "假欠账（两侧同值）", b),
                          ("E", "口径·后缀读法", e), ("C", "要新读点", cc),
                          ("D", "装置·召唤物（非干员）", dd)):
        print(f"  {tag} {name:22s} {len(ds):3d} 族，其中有干员行的 "
              f"{sum(1 for d in ds if d['has_op'])} 族")
    print(f"  ⇒ A 档涉及干员 {len(chars_a)} 位；有干员行的家族合计 "
          f"{sum(1 for d in rep if d['has_op'])} 族")
    if a:
        print("\n  ── A 档全部 ──")
        for d in a:
            print(f"  {d['core']:32s} 欠账侧 {d['unread']} 干员 {len(d['chars'])} "
                  f"落点 {d['consumption_hits']}")
    print(f"\n  ── B／E／C 里有干员行的（第四批会碰到的，共 "
          f"{sum(1 for d in b + e + cc if d['has_op'])} 族）──")
    for d in sorted(b + e + cc, key=lambda x: (not x["has_op"], -len(x["chars"]))):
        if not d["has_op"]:
            continue
        print(f"  [{d['tier']}] {d['core']:32s} 干员 {len(d['chars']):2d} 行 {d['n_rows']:3d} "
              f"欠账侧 {d['unread'][:2]}"
              + (f"  例：{'、'.join(d['chars'][:3])}" if d['chars'] else ""))

    outp = ROOT / args.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    mdp = ROOT / args.md
    write_md(rep, lits, mdp, args.by, checks)
    print(f"\n⇒ 完整清单 JSON：{outp.relative_to(ROOT)}")
    print(f"⇒ 清单文档：{mdp.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
