#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：Go 自算的干员面板 vs Python 的 `OperatorCalculator.stats()`。

## 比什么

四份来源**逐份比**（只比 `total` 会让「base 错、抵消后 total 对」溜过去）：
`base` / `trust_bonus` / `potential_bonus` / `total`。

## 覆盖面（★ 不许窄于结论）

名册 20 位 × 每位的 `(精英, 等级)` × 信赖 {0, 50, 100} × 潜能 {1, 6}
——**信赖与潜能要真的扫**，否则那两条支路等于没测。
等级取「底、顶、中间」三档（`interpolate_keyframes` 的夹取/插值/多帧三种情形）。

## 本轮的**具名缺口**

模组那一支（`module_levels`，读 `battle_equip_table.json`）**未接入 Go**——
那份表不在本机 `excel/` 缓存里。工具会把「名册里带模组的干员」逐个列出来，
不静默略过。

## 两份输入：一份在库、一份**刻意不入库**（缺了必须大声失败）

| 输入 | 入库？ | 缺了会怎样 |
|---|---|---|
| `fixtures/roster_max_modelled.json`（20 位，深扫） | **在库** | 崩（rc=1） |
| `docs/roster-<uid>.md`（账号名册 211 位，拉宽） | **不入库**（`.gitignore:32`：uid／昵称／完整练度＝个人数据） | **具名失败**（rc=3） |

## 退出码三态（**判据红**与**仪器缺输入**不共用一个码）

    0 ＝ 判据全绿（两份输入都在，且都被真的行走到）
    1 ＝ **判据红**：Go 与 Python 有逐字段不一致
    3 ＝ **仪器缺输入**：名册不在，或它在却一行都解析不出来

rc=3 时印一条**机读行**（纯 ASCII，便于机器消费）：

    SUITE_INPUT_MISSING docs/roster-<uid>.md python tools/skland.py fetch && python tools/roster.py
    SUITE_INPUT_UNUSABLE docs/roster-<uid>.md python tools/skland.py fetch && python tools/roster.py

## 怎么再生这份名册（要登录态，**不能**离线重建）

    python tools/skland.py fetch      # 拉本账号森空岛名册 → data/skland/opers_<uid>.json（不入库）
    python tools/roster.py            # 翻成算符口径 + 导出 docs/roster-<uid>.md（不入库）

★ 为什么是 rc=3 而不是「跳过并登记为绿」：2026-09-23 实测两件事，**形状不同**——
  · 名册**不在**：`read_text` 抛 `FileNotFoundError` ⇒ rc=1。这是崩，不是静默。
  · 名册**在、却被解析成 0 行**（只留表头的空壳）：这一段静默不跑，脚本照旧
    **rc=0**，仍印「结论：468 / 468 次折算逐字段一致」——**覆盖面的塌缩长得与全绿一样**。
    这一条才是假绿，本条 rc=3 与上面那条 `SUITE_INPUT_UNUSABLE` 就是堵它的。
  ⇒ 纪律：**宁可假红，也不许静默变绿**；「没跑」不许长成「通过」。

用法:
    python tools\\check_operator_go.py
    python tools\\check_operator_go.py --mutate
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
ROSTER = ROOT / "fixtures" / "roster_max_modelled.json"

#: ★ **判据红**与**仪器缺输入**不许共用一个退出码（见文件头「退出码三态」）。
EXIT_JUDGE_RED = 1
EXIT_INPUT_MISSING = 3

#: 账号名册（个人数据、**刻意不入库** ⇒ `.gitignore:32`）。
#: ⚠ 它是**唯一**带真实练度三元组（精英／等级／潜能）的输入，且**不能离线重建**：
#: 它由 `tools/skland.py fetch`（要登录态）＋ `tools/roster.py` 两步产出。
ROSTER_DOC = ROOT / "docs" / "roster-<uid>.md"
ROSTER_REGEN = "python tools/skland.py fetch && python tools/roster.py"

TRUSTS = [0.0, 50.0, 100.0]
POTENTIALS = [1, 6]


def go_opstats(configs: list[dict]) -> tuple[list[dict], list[str]]:
    """问 Go 要一批面板。

    ★ **逐个剔除**：Go 对不认识的 char_id 是**大声失败**（不静默给 0），
    所以遇到它就回 error。这里把这个 id 剔出去重试，并把它们**具名收在
    第二个返回值里**——「这一批没跑」与「跑过没问题」必须分开报
    （第一版直接抛，整批一次都没跑成，却看着像判据红了）。
    """
    dropped: list[str] = []
    while True:
        env = dict(os.environ)
        env["RIOS_DATA"] = str(DATA)
        req = json.dumps({"id": 1, "cmd": "opstats", "spec": configs}) + "\n"
        p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        if p.returncode != 0:
            raise SystemExit("Go rc=%d：%s"
                             % (p.returncode, p.stderr.decode("utf-8", "replace")[:400]))
        line = p.stdout.decode("utf-8", "replace").strip().splitlines()
        if not line:
            raise SystemExit("Go 没有回任何东西")
        resp = json.loads(line[0])
        if resp.get("ok"):
            #: ★ 回来的是**剔除之后**的那一批——必须把它一并返回，
            #: 否则外层 `zip(configs, got)` 会错位（看起来全一致，其实比错了对象）。
            return resp["opstats"], configs, dropped
        err = resp.get("error") or ""
        m = re.search(r'character_table 里没有 "([^"]+)"', err)
        if not m or len(dropped) > 50:
            raise SystemExit("Go 回 error（不是可逐个剔除的那种）：%s" % err)
        bad_id = m.group(1)
        dropped.append(bad_id)
        configs = [c for c in configs if c["char_id"] != bad_id]


def norm(v):
    """dict 里 int/float 互通：`0` 与 `0.0` 是同一个读数，别当成不一致。"""
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def main() -> int:
    from ak_tactic.operator import OperatorCalculator, TalentBook
    from ak_tactic.operator.attack_speed import attack_speed_bonus
    from ak_tactic.battle.traits import (read_combo_attack, read_trait_splash,
                                         apply_splash_talent, read_hp_drain)
    from ak_tactic.battle.talents import find_power_attack, find_glider_mobility
    calc = OperatorCalculator()
    tbook = TalentBook()
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    configs: list[dict] = []
    for e in roster:
        cid, elite, level = e["id"], int(e["elite"]), int(e["level"])
        #: 等级的底/顶/中间三档：分别走夹取、夹取、插值（多帧阶段还会走中间帧）
        cap = calc.max_level(cid, elite)
        if not cap:
            continue
        lvls = sorted({1, int(cap), (1 + int(cap)) // 2})
        for lv in lvls:
            for tr in TRUSTS:
                for pot in POTENTIALS:
                    configs.append({
                        "char_id": cid, "elite": elite, "level": lv,
                        "trust": tr, "potential": pot,
                        "module": "", "module_level": 0,
                    })
    #: 模组一支：每位带数值模组的干员、每个等级都扫一遍。
    #: ★ 不扫模组＝那 18/20 位干员的面板**根本没被这条判据覆盖**。
    mod_cfg = 0
    mod_ops: list[str] = []
    for e in roster:
        cid = e["id"]
        try:
            mods = [m for m in calc.modules(cid) if m.get("has_stats")]
        except Exception:                                        # noqa: BLE001
            mods = []
        if not mods:
            continue
        mid = mods[0]["id"]
        try:
            levels = sorted(calc.module_levels(mid))
        except Exception:                                        # noqa: BLE001
            continue
        mod_ops.append("%s(%s:%s)" % (e["name"], mid, levels))
        for mlv in levels:
            for tr in (0.0, 100.0):
                configs.append({
                    "char_id": cid, "elite": int(e["elite"]),
                    "level": int(e["level"]), "trust": tr,
                    "potential": int(e["potential"]),
                    "module": mid, "module_level": mlv,
                })
                mod_cfg += 1

    #: ---- 覆盖面拉宽：账号名册全量 ----
    #: ★ 现有的深扫只覆盖 fixtures 那 20 位；而账号名册有 211 位。
    #: 「取证范围不许窄于结论范围」——只测 20 位就宣布面板层没问题，是不成立的。
    #: 这里每位只取**它自己的**精英/等级/潜能、信赖取 0：
    #: 信赖的标度（显示% ÷ 2）在两种名册里口径不同，**不猜**，留给上面的深扫。
    #:
    #: ⚠⚠ 这一段的输入**不在库里**（`.gitignore:32`：名册含 uid／昵称／完整练度）。
    #: 所以它必须**自己证明输入在、且真的解析出了行**——两条都印机读行并给独立退出码。
    #: 实测教训（2026-09-23）：只把「文件不在」当异常是不够的——**文件在、格式变了、
    #: 解析出 0 行**时这一段静默不跑，而整脚本照旧 rc=0 并印「468 / 468 逐字段一致」。
    import re as _re
    ROW = _re.compile(
        r"^\|\s*([^|]+?)\s*\|\s*`(char_[^`]+)`\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*"
        r"\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|")
    #: 表头对账：下面的正则按**序**取第 2/4/5/6 列，必须与表头声明的一致。
    #: ★ 为什么这一条不能省：列一错位（如 `等级` 与 `潜能` 互换），
    #: Go 与 Python 吃的是**同一份错 configs** ⇒ 逐字段比对照样全绿。
    #: 这个错**只有输入身份这一层看得见**，比对层永远看不见它（同族：本项目
    #: 「名字不是身份」那一条）。两列都是数字时更隐蔽——它连「解析失败」都不会发生。
    HEAD_WANT = ("charId", "精英", "等级", "潜能")

    def _head_ok(cells: list[str]) -> bool:
        return (len(cells) >= 6 and cells[1] == HEAD_WANT[0] and cells[3] == HEAD_WANT[1]
                and cells[4] == HEAD_WANT[2] and cells[5] == HEAD_WANT[3])

    wide = 0
    skipped: list[str] = []
    #: 名册文件的形态读数：像表行的行数（含表头与分隔行）。窄太多＝格式变了。
    n_table_lines = 0
    #: "" ＝ 这一段被真的行使了；否则 MISSING（文件不在）／UNUSABLE（在但解析 0 行）。
    input_state = ""
    if not ROSTER_DOC.is_file():
        input_state = "MISSING"
        print("SUITE_INPUT_MISSING %s %s"
              % (ROSTER_DOC.relative_to(ROOT).as_posix(), ROSTER_REGEN))
        print("        账号名册不在 ⇒ 「覆盖面拉宽」这一段本轮**没跑**。"
              "它不入库是刻意的（个人数据），再生要登录态，见文件头。")
    else:
        _lines = ROSTER_DOC.read_text(encoding="utf-8").splitlines()
        n_table_lines = sum(1 for ln in _lines if ln.lstrip().startswith("|"))
        _head: list[str] = []
        for _ln in _lines:
            if _ln.lstrip().startswith("|"):
                _head = [c.strip() for c in _ln.strip().strip("|").split("|")]
                break
        if not _head_ok(_head):
            input_state = "UNUSABLE"
            print("SUITE_INPUT_UNUSABLE %s %s"
                  % (ROSTER_DOC.relative_to(ROOT).as_posix(), ROSTER_REGEN))
            print("        ⚠ 名册表头与判据按序取的列对不上（实得 %r；"
                  "期望第 2/4/5/6 列 ＝ %r）。列错位时两边吃的是**同一份错 configs**，"
                  "逐字段比对照样全绿。" % (_head[:6], list(HEAD_WANT)))
        else:
            for line in _lines:
                m = ROW.match(line)
                if not m:
                    continue
                cid = m.group(2)
                if not calc.exists(cid):
                    skipped.append(cid)
                    continue
                try:
                    elite = int(m.group(4).lstrip("Ee") or 0)
                    level = int(m.group(5) or 1)
                    pot = int(m.group(6) or 1)
                except ValueError:
                    skipped.append(cid)
                    continue
                if not (1 <= level <= int(calc.max_level(cid, elite) or 1)):
                    skipped.append("%s(E%d L%d 越界)" % (cid, elite, level))
                    continue
                configs.append({"char_id": cid, "elite": elite, "level": level,
                                "trust": 0.0, "potential": pot,
                                "module": "", "module_level": 0})
                wide += 1
        #: ⚠ 表头已判不合格时不再叠一条「0 行」的同一结论（两句话说同一件事会让人以为是两个错）。
        if not input_state and wide == 0:
            input_state = "UNUSABLE"
            print("SUITE_INPUT_UNUSABLE %s %s"
                  % (ROSTER_DOC.relative_to(ROOT).as_posix(), ROSTER_REGEN))
            print("        ⚠ 名册在，却一行都没解析出来（文件里 %d 行像表行）："
                  "格式变了／换账号导出了／文件被截断。这一段等于没跑，"
                  "**不许**把它当绿。" % n_table_lines)
        elif not input_state:
            print("        名册形态读数：文件里 %d 行像表行（含表头与分隔行），"
                  "本段解析出 %d 位可折算、跳过 %d 位。"
                  % (n_table_lines, wide, len(skipped)))

    got, configs, dropped = go_opstats(configs)

    mutate = "--mutate" in sys.argv
    if mutate:
        #: ★ **合成一处不一致**：不改任何东西就宣称「守卫成立」是假守卫
        #: （本项目记过：反向守卫必须真换策略/真注入）。
        #: 这里把第一次折算的 `total` 改掉一个键，判据**必须**红。
        k0 = sorted(got[0]["total"])[0]
        got[0]["total"][k0] = got[0]["total"][k0] + 1

    bad = 0
    compared = 0
    #: ★ 行使计数：三个 aspd 字段**各有几次非零**。全零的绿是零信息量的绿——
    #: 若三条都是 0，这条判据什么也没证明（本项目记过「必然绿」这一类）。
    aspd_hits = {"aspd_flat": 0, "aspd_when_free": 0, "aspd_high_ground": 0}
    #: 连击三字段的行使计数：这三条「没有这条」是 1/1.0/1.0，
    #: 所以要数的是**非 1** 的次数（非零判据在这里会数成「全员命中」）。
    combo_hits = {"combo_hits": 0, "combo_hit_scale": 0, "combo_damage_scale": 0}
    #: 这条连击天赋**命中**的次数与它实际的 hit_scale 取值。
    #: ⚠ 不能靠「字段值 ≠ 默认值」来数命中：`combo_hit_scale` 的**真值就是 1.0**，
    #: 与「没有这条」的默认值相同 ⇒ 按值判会永远数成 0（那是尺子的毛病）。
    combo_seen = [0, 0.0]
    #: 「强击瓶专家」的行使计数（`count` 非 0、`scale` 非 1.0）。
    pa_hits = {"power_attack_count": 0, "power_attack_scale": 0}
    #: 特性的行使计数（三项各自非零次数）。「没有这条」都是 0，所以非零即命中。
    tr_hits = {"splash_radius": 0, "splash_scale": 0, "splash_damage_scale": 0,
               "highland_splash_scale": 0, "highland_splash_sluggish": 0,
               "hp_drain_per_sec": 0}
    #: 三个纯文本判据的行使计数（布尔真 / 非法术类型 各计一次）。
    tx_hits = {"damage_type_text": 0, "heals": 0, "weakness_damage": 0}
    #: 身份两字段的行使计数（非空次数）。
    id_hits = {"nation_id": 0, "profession": 0}
    #: 「翔虫机动」七字段的行使计数（非零/非空/为真）。
    gl_hits = {"mobility_atk_bonus": 0, "mobility_atk_duration": 0,
               "mobility_leftover": 0, "mobility_deploy_range": 0,
               "mobility_melee_deploy": 0, "mobility_ignore_dir": 0,
               "no_respawn_cost_add": 0}
    for cfg, g in zip(configs, got):
        py = calc.stats(cfg["char_id"], elite=cfg["elite"], level=cfg["level"],
                        trust=cfg["trust"], potential=cfg["potential"],
                        module=cfg.get("module") or None,
                        module_level=cfg.get("module_level") or 0)
        compared += 1
        out = []
        for part in ("base", "trust_bonus", "potential_bonus", "total"):
            a = norm(g.get(part) or {})
            b = norm(getattr(py, part, None) or {})
            if a != b:
                for k in sorted(set(a) | set(b)):
                    if a.get(k) != b.get(k):
                        out.append("%s.%s：Go=%r Python=%r"
                                   % (part, k, a.get(k), b.get(k)))
        #: 攻速加成那一支（天赋常驻/高台条件 ＋ 模组特性改写/未阻挡条件）。
        #: 模组那一项**只有在这次折算带了模组时**才可能非零。
        aspd = attack_speed_bonus(
            calc, cfg["char_id"], elite=cfg["elite"], level=cfg["level"],
            potential=cfg["potential"],
            module=cfg.get("module") or None,
            module_level=cfg.get("module_level") or 0)
        for gk, pk in (("aspd_flat", "flat"), ("aspd_when_free", "when_free"),
                       ("aspd_high_ground", "when_high_ground")):
            a, b = norm(g.get(gk)), norm(getattr(aspd, pk, 0.0))
            if b:
                aspd_hits[gk] += 1
            if a != b:
                out.append("%s：Go=%r Python=%r" % (gk, a, b))
        #: 普攻连击（隐藏天赋的键组合）。Python 侧 `verify.py:342-344` 的三行
        #: 是「没有这条 1 / 1.0 / 1.0」，Go 侧同口径。
        combo = read_combo_attack(calc.character(cfg["char_id"]))
        if combo is not None:
            combo_seen[0] += 1
            combo_seen[1] = combo.hit_scale
        py_combo = {"combo_hits": combo.hits if combo else 1,
                    "combo_hit_scale": combo.hit_scale if combo else 1.0,
                    "combo_damage_scale": combo.damage_scale if combo else 1.0}
        for k, b in py_combo.items():
            if b != 1 and b != 1.0:
                combo_hits[k] += 1
            a = norm(g.get(k))
            if a != norm(b):
                out.append("%s：Go=%r Python=%r" % (k, a, b))
        #: 「强击瓶专家」。★ `scale` 的「没有这条」是 **1.0**，`count` 是 0。
        pa = find_power_attack(tbook.for_operator(
            cfg["char_id"], elite=cfg["elite"], level=cfg["level"],
            potential=cfg["potential"]))
        py_pa = {"power_attack_count": pa.count if pa else 0,
                 "power_attack_scale": pa.scale if pa else 1.0}
        for k, b in py_pa.items():
            if (k == "power_attack_count" and b) or (k == "power_attack_scale" and b != 1.0):
                pa_hits[k] += 1
            if norm(g.get(k)) != norm(b):
                out.append("%s：Go=%r Python=%r" % (k, norm(g.get(k)), b))
        #: 特性那两支：溅射（几何 ＋ 天赋「汹涌怒火」叠三项）与生命流失速率。
        #: ★ 有天赋叠层时 `damage_scale` 的「没有这条」是 **1.0**（它是乘数），
        #: 两个 highland 是 0.0——不能一律按 0 判。
        ch = calc.character(cfg["char_id"])
        sp = apply_splash_talent(
            read_trait_splash(ch),
            tbook.for_operator(cfg["char_id"], elite=cfg["elite"],
                               level=cfg["level"], potential=cfg["potential"]))
        py_tr = {"splash_radius": sp.radius if sp else 0.0,
                 "splash_scale": sp.scale if sp else 0.0,
                 "splash_damage_scale": sp.damage_scale if sp else 1.0,
                 "highland_splash_scale": sp.highland_scale if sp else 0.0,
                 "highland_splash_sluggish": sp.highland_sluggish if sp else 0.0,
                 "hp_drain_per_sec": read_hp_drain(ch)}
        for k, b in py_tr.items():
            if (k == "splash_damage_scale" and b != 1.0) or (k != "splash_damage_scale" and b):
                tr_hits[k] += 1
            if norm(g.get(k)) != norm(b):
                out.append("%s：Go=%r Python=%r" % (k, norm(g.get(k)), b))
        #: 三个纯文本判据（verify.py:305-308 与 :329-331）。
        #: ⚠ `weakness_damage` 的判据文本是**所有候选**的描述拼接，
        #: 不是「这个练度下生效的那几条」——照解析后的天赋判会漏。
        trait = ch.get("description") or ""
        tal_text = " ".join(
            (cand.get("description") or "")
            for t_ in (ch.get("talents") or [])
            for cand in (t_.get("candidates") or []))
        py_tx = {"damage_type_text": "MAGIC" if "法术伤害" in trait else "PHYSICAL",
                 "heals": "恢复友方单位生命" in trait,
                 "weakness_damage": "弱点伤害" in tal_text}
        for k, b in py_tx.items():
            #: ⚠ `damage_type_text` 是**字符串**（恒真），按真值计数会数出
            #: 「468 次全被行使」——那是假计数。它要数的是 **MAGIC 的条数**。
            if k == "damage_type_text":
                if b == "MAGIC":
                    tx_hits[k] += 1
            elif b:
                tx_hits[k] += 1
            if norm(g.get(k)) != norm(b):
                out.append("%s：Go=%r Python=%r" % (k, g.get(k), b))
        #: 身份两字段（直接取自 character_table，不做推断）。
        py_id = {"nation_id": ch.get("nationId") or "",
                 "profession": ch.get("profession") or ""}
        for k, b in py_id.items():
            if b:
                id_hits[k] += 1
            if (g.get(k) or "") != b:
                out.append("%s：Go=%r Python=%r" % (k, g.get(k), b))
        #: 天赋「翔虫机动」：**一个天赋两个平面**（落位放宽 ＋ 限时攻击力加成）。
        #: 没有这条时 verify.py:348-354 给的是零值 0.0/False/""。
        gl = find_glider_mobility(tbook.for_operator(
            cfg["char_id"], elite=cfg["elite"], level=cfg["level"],
            potential=cfg["potential"]))
        py_gl = {"mobility_atk_bonus": gl.atk_bonus if gl else 0.0,
                 "mobility_atk_duration": gl.atk_duration if gl else 0.0,
                 "mobility_leftover": gl.projectile if gl else "",
                 "mobility_deploy_range": gl.deploy_range if gl else "",
                 "mobility_melee_deploy": gl.ignore_build_type if gl else False,
                 "mobility_ignore_dir": gl.ignore_dir if gl else 0.0,
                 "no_respawn_cost_add": gl.no_respawn_cost_add if gl else False}
        for k, b in py_gl.items():
            if b:
                gl_hits[k] += 1
            if norm(g.get(k)) != norm(b):
                out.append("%s：Go=%r Python=%r" % (k, norm(g.get(k)), b))
        if out:
            bad += 1
            print("✗ %s E%d L%d trust=%g pot=%d mod=%s —— %d 处不一致"
                  % (cfg["char_id"], cfg["elite"], cfg["level"],
                     cfg["trust"], cfg["potential"], cfg.get("module") or "-", len(out)))
            for line in out[:10]:
                print("    " + line)
    print()
    print("已比：base / trust_bonus / potential_bonus / module_bonus / total 五份逐字段，"
          "另加**攻速**三字段（aspd_flat / aspd_when_free / aspd_high_ground）；"
          "共 %d 次折算" % compared)
    print("覆盖面：名册 %d 位 × (底/顶/中 三档等级) × 信赖 %s × 潜能 %s，"
          "另加**模组** %d 次（%d 位带数值模组的干员）"
          % (len(roster), TRUSTS, POTENTIALS, mod_cfg, len(mod_ops)))
    print("        另加**账号名册全量** %d 位（`docs/roster-<uid>.md`，各取自己的"
          "精英/等级/潜能、信赖 0）" % wide)
    if skipped:
        print("        名册里跳过 %d 位（表里没有 / 等级越界）：%s"
              % (len(skipped), "、".join(skipped[:8])))
    if dropped:
        print("★ Go 侧**没有覆盖**的 char_id %d 个（它大声失败，由判据逐个剔除）：%s"
              % (len(dropped), "、".join(dropped)))
        print("  ⇒ 这些干员**不在本轮覆盖面内**，不是「比过了没问题」。")
    print("★ 攻速三字段的**行使计数**（Python 侧非零次数／共 %d 次折算）：" % compared)
    for k, n in aspd_hits.items():
        flag = "" if n else "   ← 零信息量的绿：这一档本轮没被行使到"
        print("    %-18s %d%s" % (k, n, flag))
    print("★「翔虫机动」七字段行使计数（非零/非空/为真）：")
    for k, n in gl_hits.items():
        flag = "" if n else "   ← 这一档本轮没被行使到"
        print("    %-22s %d%s" % (k, n, flag))
    print()
    print("★ 身份两字段行使计数（非空次数）：")
    for k, n in id_hits.items():
        flag = "" if n else "   ← 这一档本轮全是空值"
        print("    %-18s %d%s" % (k, n, flag))
    print()
    print("★ 三个纯文本判据行使计数（MAGIC 条数 / 治疗为真 / 弱点伤害为真）：")
    for k, n in tx_hits.items():
        flag = "" if n else "   ← 这一档本轮没被行使到"
        print("    %-18s %d%s" % (k, n, flag))
    print()
    print("★ 特性三字段行使计数（非零／共 %d 次）：" % compared)
    for k, n in tr_hits.items():
        flag = "" if n else "   ← 这一档本轮没被行使到"
        print("    %-18s %d%s" % (k, n, flag))
    print()
    print("★「强击瓶专家」行使计数（count 非 0 / scale 非 1.0）：")
    for k, n in pa_hits.items():
        flag = "" if n else "   ← 这一档本轮没被行使到"
        print("    %-20s %d%s" % (k, n, flag))
    print()
    print("★ 连击三字段的行使计数（**非 1** 的次数；这三条的「没有这条」就是 1）：")
    for k, n in combo_hits.items():
        flag = "" if n else "   ← 该字段的值与默认值相同（见下）"
        print("    %-18s %d%s" % (k, n, flag))
    print("    连击天赋命中 %d 次，其 hit_scale 实测 = %g" % (combo_seen[0], combo_seen[1]))
    print("    ⚠ hit_scale 的**真值就是 1.0**，与默认值无法按值区分 ⇒ 上面那一行 0")
    print("      是尺子的口径所限，不是「没被走到」；命中次数看这两行。")
    print()
    if mod_ops:
        print("    模组清单（取每位的第一个带数值模组，全等级扫）：")
        for line in mod_ops:
            print("        " + line)
    else:
        print("★ 名册里**没有**带数值模组的干员 —— 模组那一支这一轮没被行走到")
    print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗（注入了改动却没红，判据没有分辨力）")
        return 1
    if input_state:
        #: ★ 缺输入**优先于**判据绿：宁可假红，也不许覆盖面静默塌缩成绿（见文件头）。
        print("结论：**输入%s，本轮不给判决**——上面那 %d / %d 次折算只盖到深扫那一段，"
              "名册那一尺本轮没量到（机读行见上）。"
              % (input_state, compared - bad, compared))
        return EXIT_INPUT_MISSING
    print("结论：%d / %d 次折算逐字段一致" % (compared - bad, compared))
    return EXIT_JUDGE_RED if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
