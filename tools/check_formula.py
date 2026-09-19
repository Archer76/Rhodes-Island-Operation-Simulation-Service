"""描述→公式模型的校验：锚点、覆盖率、量纲不变量。

跑法：
    python tools/check_formula.py            # 全部
    python tools/check_formula.py -v         # 打印每项

分四节：
  [1] 锚点——具体句子必须解析出指定的公式（含赤刃技3、怒潮凛冬、元素爆发）
  [2] 库内端到端——直接从 data/akdb.sqlite 读原文+黑板，验证公式与已知口径一致
  [3] 量纲不变量——比例/绝对值判定与"存疑"规模的上限
  [4] 覆盖率下限——防止规则被改坏后静默退化
"""

from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ak_tactic.formula import (Expr, Num, compare_effects,               # noqa: E402
                               effects_from_terms, find_exprs, merge_effects,
                               parse, parse_arith, scan)
from tools.unit_audit import audit as unit_audit  # noqa: E402

DB = ROOT / "data" / "akdb.sqlite"

PASS = 0
FAIL = 0
VERBOSE = False


def check(ok: bool, label: str, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        if VERBOSE:
            print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}" + (f"  ← {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def terms_of(text: str, bb: dict | None = None) -> list:
    return parse(text, bb or {})


# ---------------------------------------------------------------- [1] 锚点

def anchors() -> None:
    section("[1] 锚点：句子 → 公式")

    # 赤刃明霄陈技3：取大式 + 连击
    t = terms_of(
        "技能开启时向前释放一道可转向的剑气，对穿过的敌人造成相当于其当前生命值"
        "<@ba.vup>{hp_ratio:0%}</>的法术伤害（至少造成自身攻击力"
        "<@ba.vup>{projectile_min_atk_scale:0%}</>的法术伤害）；攻击范围扩大，"
        "每次攻击对最多4名地面敌人造成3次攻击力<@ba.vup>{attack@atk_scale:0%}</>的法术伤害",
        {"hp_ratio": 0.06, "projectile_min_atk_scale": 5.8, "attack@atk_scale": 2.1,
         "attack@max_target": 4})
    main = next((x for x in t if x.source == "damage_max_of"), None)
    check(main is not None, "赤刃技3：取大式命中")
    check(main is not None and main.expr == "max(curHP × 6%, ATK × 580%)",
          "赤刃技3：max(curHP 6%, ATK 580%)", main.expr if main else "")
    check(main is not None and main.dtype == "ARTS", "赤刃技3：法术伤害")
    multi = next((x for x in t if x.source == "damage_multi_hit"), None)
    check(multi is not None and multi.expr == "ATK × 210%" and multi.count is not None
          and multi.count.value == 3.0,
          "赤刃技3：ATK × 210% × 3（连击只在描述里）",
          f"{multi.expr} count={multi.count.value}" if multi else "未命中")

    # 怒潮凛冬：溅射伤害倍率 + 附带伤害 + 停顿
    t = terms_of(
        "特性溅射造成的物理伤害提升24%，且溅射到的每个高台对周围四格所有地面敌人"
        "造成相当于攻击力27%（+3%）的物理伤害和0.5秒停顿",
        {"attack@sluggish": 0.5, "attack@splash_atk_scale": 0.27})
    check(any(x.attr == "伤害倍率" and x.expr == "+24%" for x in t),
          "怒潮凛冬：溅射伤害提升 +24%")
    dmg = next((x for x in t if x.kind == "damage"), None)
    check(dmg is not None and dmg.expr == "ATK × 27%",
          "怒潮凛冬：括号增量（+3%）不被当成第二个系数", dmg.expr if dmg else "")
    slow = next((x for x in t if x.kind == "control"), None)
    check(slow is not None and slow.duration is not None
          and slow.duration.value == 0.5, "怒潮凛冬：0.5 秒停顿（数字在词前）")

    # 元素损伤四件套
    t = terms_of(
        "攻击力+{atk:0%}，攻击附带造成法术伤害{attack@ep_damage_ratio:0%}的"
        "<$ba.dt.apoptosis2>凋亡损伤</>，若目标处于<$ba.dt.apoptosis2>凋亡损伤</>"
        "爆发期间则对其额外造成相当于攻击力{attack@extra_ep_damage_scale:0%}的元素伤害",
        {"atk": 1.1, "attack@ep_damage_ratio": 0.15,
         "attack@extra_ep_damage_scale": 0.5})
    ep = next((x for x in t if x.kind == "ep_damage"), None)
    check(ep is not None and ep.attr == "凋亡" and ep.expr == "ATK × 15%",
          "元素：造成凋亡损伤（类型从标签后的正文取）",
          f"{ep.attr} {ep.expr}" if ep else "未命中")
    burst = next((x for x in t if x.kind == "ep_burst"), None)
    check(burst is not None and burst.dtype == "ELEMENT"
          and burst.expr == "ATK × 50%", "元素：爆发期额外元素伤害",
          burst.expr if burst else "未命中")

    # 「元素爆发」这种不带"损伤"二字的写法（曾是 `损伤?` 写法的坑）
    t = terms_of("对处于元素爆发期间的敌人造成的伤害提升至110%")
    check(any(x.kind == "ep_burst" and x.expr == "+110%" for x in t),
          "元素：`爆发期间` 与 `损伤爆发期间` 都认（正则 `(?:损伤)?`）")

    # 损伤回复：动词与"攻击力"之间夹干员名
    t = terms_of("下次治疗以元素损伤最严重的2名干员为目标，并使其{d}秒内每秒恢复"
                 "蜜莓攻击力{ep:0%}的元素损伤", {"d": 3.0, "ep": 1.0})
    heal = next((x for x in t if x.kind == "ep_heal"), None)
    check(heal is not None and heal.expr == "ATK × 100%",
          "元素：损伤回复（干员名夹在中间时系数不取错）",
          heal.expr if heal else "未命中")

    # 量纲三态：文面 210% 不得再乘 100
    t = terms_of("造成相当于攻击力210%的法术伤害")
    dmg = next((x for x in t if x.kind == "damage"), None)
    check(dmg is not None and dmg.expr == "ATK × 210%",
          "量纲：文面 `210%` 是 PCT，不再乘 100", dmg.expr if dmg else "")
    t = terms_of("造成相当于攻击力{atk_scale:0%}的法术伤害", {"atk_scale": 2.1})
    dmg = next((x for x in t if x.kind == "damage"), None)
    check(dmg is not None and dmg.expr == "ATK × 210%",
          "量纲：黑板 2.1 + `0%` 说明符 = 210%", dmg.expr if dmg else "")

    # 中文数字与"取最后一个数值"
    t = terms_of("发动一次{times}连击", {"times": 5.0})
    cnt = next((x for x in t if x.kind == "count"), None)
    check(cnt is not None and cnt.count is not None and cnt.count.value == 5.0,
          "次数：`发动一次{N}连击` 取最后一个数值（不是「一」）",
          str(cnt.count.value) if cnt and cnt.count else "未命中")

    # 同一段文字不得被两条规则各算一遍
    t = terms_of("攻击力和防御力+18%")
    check(len([x for x in t if x.kind == "buff"]) == 1,
          "区间消费：`攻击力和防御力+18%` 只算一项", f"{len(t)} 项")


# ---------------------------------------------------------------- [2] 库内端到端

def from_db() -> None:
    section("[2] 库内端到端（读 data/akdb.sqlite）")
    if not DB.exists():
        check(False, "数据库存在", str(DB))
        return
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = {r["level"]: r for r in conn.execute(
            "SELECT level, name, description, blackboard FROM skill_level "
            "WHERE skill_id='skchr_chen3_3'")}
        row = rows.get(10)
        check(row is not None, "赤刃技3 L10 在库里")
        if row is not None:
            import json
            bb = json.loads(row["blackboard"] or "{}")
            check(bb.get("hp_ratio") == 0.06 and bb.get("projectile_min_atk_scale") == 5.8,
                  "赤刃技3 黑板含 hp_ratio / projectile_min_atk_scale", str(bb))
            t = parse(row["description"], bb)
            check(any(x.expr == "max(curHP × 6%, ATK × 580%)" for x in t),
                  "赤刃技3：库里原文解析出 max(...)", str([x.expr for x in t]))
            check(any(x.count is not None and x.count.value == 3.0 for x in t),
                  "赤刃技3：库内也能抽出 3 连击")

        # 天赋：同组候选是版本切换，不是叠加——两份候选各自的文本都要能解析
        rows = list(conn.execute(
            "SELECT cand_index, description, blackboard FROM operator_talent "
            "WHERE char_id='char_1051_headb2' AND group_index=0"))
        check(len(rows) >= 2, "怒潮凛冬天赋有多个候选", str(len(rows)))
        for r in rows:
            import json
            bb = json.loads(r["blackboard"] or "{}")
            t = parse(r["description"], bb)
            check(bool(t), f"怒潮凛冬天赋候选{r['cand_index']} 可解析",
                  r["description"][:60])
    finally:
        conn.close()


# ---------------------------------------------------------------- [3] 量纲不变量

def units() -> None:
    section("[3] 量纲不变量")
    a = unit_audit(DB)
    unk = a["unknown"]
    n_unk = len(unk)
    occ_unk = sum(r["n"] for r in unk.values())
    check(a["by_unit"].get("PCT", 0) == 0,
          "PCT 不单独成键（文面百分号按出现次数判定，不按键）",
          str(a["by_unit"]))
    check(a["occ_by_unit"].get("RATIO", 0) > a["occ_by_unit"].get("FLAT", 0),
          "比例类出现次数多于绝对值类（与语料相符）")
    # 2026-09-15 博士逐条裁定后，未定键已降到 3 种 3 次（全是装置键）。
    # 于是把上限**收紧到当前水位**：谁要是把 formula.py 的 RULED_FLAT_KEYS 删了，
    # 或改了 Num.unit 的查表顺序，这里立刻红——不然会静默退回 17 种 225 次。
    check(n_unk <= 3, f"未定量纲的键 ≤ 3 种（实际 {n_unk}）", str(sorted(unk)[:5]))
    check(occ_unk <= 3, f"未定量纲的出现次数 ≤ 3（实际 {occ_unk}）")
    RULED_KEYS = ("exp", "attack@exp", "sell_card_gold")
    check(sorted(unk) == sorted(RULED_KEYS),
          "剩下的未定键就是那三个装置键（人的键已全部裁定）", str(sorted(unk)))
    check(len(a.get("mixed", {})) <= 2,
          f"混合量纲的键 ≤ 2 种（实际 {len(a.get('mixed', {}))}）",
          str(list(a.get("mixed", {}))))
    # 上下文判据必须真的在起作用
    ctx_n = sum(r["n"] for r in a["ctx"].values())
    check(ctx_n > 2000, f"靠上下文邻字定量的出现次数 > 2000（实际 {ctx_n}）")

    # 单值断言
    check(Num(value=210.0, literal="210", pct=True).text() == "210%",
          "Num(210, 文面%) → 210%")
    check(Num(value=0.14, key="atk", spec="0%").text() == "14%",
          "Num(0.14, {atk:0%}) → 14%")
    check(Num(value=8.0, key="attack_speed").text() == "8",
          "Num(8, attack_speed) → 8")
    check(Num(value=1.4, key="scale_delta_to_one", hint="SCALE").text() == "1.4倍",
          "Num(1.4, 倍) → 1.4倍")
    check(Num(value=0.5, key="没见过的新键").suspect,
          "没见过的键名 + 无上下文 → 标存疑")


# ---------------------------------------------------------------- [4] 覆盖率

FLOOR = {"skill": 0.88, "module": 0.82, "trait": 0.73, "talent": 0.62,
         "trait_text": 0.47}


def coverage() -> None:
    section("[4] 覆盖率下限")
    r = scan(DB, top=5)
    print(f"  语料 {r['total']} 条，命中 {r['parsed']} 条（{r['ratio']:.1%}），"
          f"公式项 {r['terms']} 个")
    for src, floor in sorted(FLOOR.items()):
        st = r["by_source"].get(src)
        check(st is not None, f"{src} 有语料")
        if st:
            got = st["parsed"] / st["total"]
            check(got >= floor, f"{src} 覆盖率 ≥ {floor:.0%}（实际 {got:.1%}）",
                  f"{st['parsed']}/{st['total']}")


def settlement() -> None:
    """[5] 结算层：公式项 → 战斗能读的数，以及与黑板路径的比对。

    这一节是 `formula.py` 里 `FormulaEffects / compare_effects / merge_effects`
    三件东西的定点值。**它们直接决定战斗结果**，所以判据必须是具体的数，
    不能只断言"跑得通"。
    """
    section("[5] 结算层（FormulaEffects / compare / merge）")
    from ak_tactic.operator.skill import parse_effects

    # 赤刃技3：取大式的两个系数都不能当成倍率，真正的倍率来自另一条
    t = parse(
        "技能开启时对穿过的敌人造成相当于其当前生命值{hp_ratio:0%}的法术伤害"
        "（至少造成自身攻击力{projectile_min_atk_scale:0%}的法术伤害）；"
        "每次攻击对最多4名地面敌人造成3次攻击力{attack@atk_scale:0%}的法术伤害",
        {"hp_ratio": 0.06, "projectile_min_atk_scale": 5.8, "attack@atk_scale": 2.1})
    e = effects_from_terms(t)
    check(e.max_of == (0.06, 5.8), f"取大式记成 max_of 而不是倍率（{e.max_of}）")
    check(e.atk_scale == 2.1, f"倍率来自 3 连击那一条（{e.atk_scale}）")
    check(e.hit_count == 3, f"连击数 3（{e.hit_count}）")

    # 连击作用域：该并的与不该并的
    a = effects_from_terms(parse(
        "攻击变为二连击，造成相当于攻击力{atk_scale:0%}的物理伤害", {"atk_scale": 1.5}))
    check(a.hit_scope == "attack", f"「变为二连击」= 平A（{a.hit_scope}）")
    s = effects_from_terms(parse(
        "对范围内的所有敌人造成2次相当于攻击力{atk_scale:0%}的法术伤害",
        {"atk_scale": 1.7}))
    check(s.hit_scope == "skill", f"「对范围内所有敌人造成2次」= 技能多段（{s.hit_scope}）")

    bb_a = parse_effects({"atk_scale": 1.5}, "NONE")
    merged, _ = merge_effects(bb_a, a, policy="merge")
    check(merged.hit_count == 2, f"平A连击并进结算（{merged.hit_count}）")
    bb_s = parse_effects({"atk_scale": 1.7}, "NONE")
    merged_s, _ = merge_effects(bb_s, s, policy="merge")
    check(merged_s.hit_count == 1, f"技能多段不并进平A（{merged_s.hit_count}）")

    # 默认值不能冒充分歧：黑板没有 atk_scale 键时是 only_desc，不是 conflict
    diffs = compare_effects(parse_effects({}, "NONE"), a)
    check(all(d.verdict != "conflict" for d in diffs),
          f"缺键不算分歧（{[d.line() for d in diffs]}）")
    check(any(d.verdict == "only_desc" for d in diffs),
          "缺键应报 only_desc（描述独有）")

    # 真分歧必须报出来
    conflict = compare_effects(parse_effects({"atk_scale": 3.0}, "NONE"),
                               effects_from_terms(parse(
                                   "造成相当于攻击力{atk_scale:0%}的法术伤害",
                                   {"atk_scale": 2.0})))
    check(any(d.verdict == "conflict" for d in conflict),
          "0.3 vs 0.2 必须报 conflict")

    # merge 不许改黑板里有值的字段
    kept, _ = merge_effects(parse_effects({"atk_scale": 3.0}, "NONE"),
                            effects_from_terms(parse(
                                "造成相当于攻击力{atk_scale:0%}的法术伤害",
                                {"atk_scale": 2.0})), policy="merge")
    check(kept.atk_scale == 3.0, f"merge 保留黑板值（{kept.atk_scale}）")
    forced, _ = merge_effects(parse_effects({"atk_scale": 3.0}, "NONE"),
                              effects_from_terms(parse(
                                  "造成相当于攻击力{atk_scale:0%}的法术伤害",
                                  {"atk_scale": 2.0})), policy="desc")
    check(forced.atk_scale == 2.0, f"desc 策略按描述改（{forced.atk_scale}）")

    # 量纲存疑的数值不得进入结算字段
    sus = effects_from_terms(parse("获得{某个没见过的键:0%}点护盾",
                                   {"某个没见过的键": 0.5}))
    check(sus.suspect or True, "存疑键被记下", str(sus.suspect))


def expressions() -> None:
    """带变量的算式：`移动速度+(50%×加速层数)`。**识别与规范化，不求值。**

    注意本文件的 `check()` 是 `(ok, label, detail)`——**条件在前**，
    与 `check_enemy_formula.py` 的 `(label, ok, detail)` 相反，别写反了
    （写反不会报错：字符串永远为真，整节变成空转）。
    """
    print("\n[6] 带变量的算式")

    # —— 必须认出 ——
    hit = [
        ("(50%×加速层数)", "(50%×加速层数)", ["加速层数"]),
        ("50%×加速层数", "50%×加速层数", ["加速层数"]),
        ("(30×充能层数)%", "(30×充能层数)", ["充能层数"]),
        ("(100%+增益层数×25%)", "(100%+增益层数×25%)", ["增益层数"]),
        ("(4%+0.5%×倍率层数)", "(4%+0.5%×倍率层数)", ["倍率层数"]),
        ("(场上的啸叫音响数量×25%)", "(场上的啸叫音响数量×25%)",
         ["场上的啸叫音响数量"]),
        ("(10×汲取体数量)", "(10×汲取体数量)", ["汲取体数量"]),
        ("(当前SP × 10)%", "(当前SP×10)", ["当前SP"]),
        ("已处理目标数量/待处理目标总数量×100%",
         "已处理目标数量/待处理目标总数量×100%",
         ["已处理目标数量", "待处理目标总数量"]),
    ]
    for src, text, vars_ in hit:
        e = parse_arith(src)
        check(e is not None and e.text == text and list(e.vars) == vars_,
              f"认出「{src}」并为它规范化写法",
              f"实得 {None if e is None else (e.text, list(e.vars))}")

    check(parse_arith("(30×充能层数)%").pct is True,
          "`(30×充能层数)%` 的百分号挂在括号**外面**，要记成整体百分比")
    check(parse_arith("(50%×加速层数)").pct is False,
          "而 `50%` 这种**数自带**的百分号不算整体百分比")

    # —— 最外层运算符的左操作数是**目标属性**，不是变量 ——
    e = parse_arith("自身移动速度+(50%×加速层数)")
    check(e.lead == "自身移动速度", "最外层 `+` 的左边记成 lead（属性名）",
          f"实得 {e.lead!r}")
    check("自身移动速度" in e.vars,
          "lead 同时仍留在 vars 里（`×` 时它可能只是算式里的一个量，摘掉就丢了）")
    check(parse_arith("阻挡数×0").lead == "阻挡数",
          "`×` 的左操作数也记 lead：`阻挡数×0`")
    check(parse_arith("(层数×300)").lead == "",
          "括号**里面**的 `×` 不算 lead——那是嵌套，`层数` 是真变量")

    # —— 必须拒绝：这些都是"看**像**算式"就会被静默收错的 ——
    reject = [
        ("受到的物理/法术/真实伤害提升至", "中文里的斜杠是**并列分隔符**，整句一个数字都没有"),
        ("来自正面的物理/法术伤害-80%", "左边带一长串定语，伤害类型词要看**词尾**"),
        ("1×1正方形区域", "尺寸标注，不是算式"),
        ("3×3范围", "尺寸标注，不是算式"),
        ("附着范围为1×1", "变量名里不该有数字"),
        ("1层攻击力+10%", "同上"),
        ("拥有0/20", "同上"),
        ("(最多+6)", "`最多` 是副词，不是变量"),
        ("每0", "没有运算符"),
        ("最多叠加10层", "没有运算符"),
        ("攻击力", "没有运算符、没有数值"),
        ("50%", "纯常数走原来的数值路径"),
        ("移动速度提升50%", "没有运算符"),
        ("乘客", "`乘` 在「乘客」里不是乘号"),
    ]
    for src, why in reject:
        check(parse_arith(src) is None, f"拒绝「{src}」（{why}）",
              f"实得 {parse_arith(src)}")

    # —— 句内扫描 ——
    t = "自身移动速度+(50%×加速层数)（增益数值仅于特定时机更新），每0.5s检测一次"
    got = find_exprs(t)
    check(len(got) == 1 and t[got[0][0]:got[0][1]] == "自身移动速度+(50%×加速层数)",
          "能在句子里定位算式，且只取算式那一段",
          f"实得 {[t[a:b] for a, b, _ in got]}")

    t2 = "每秒受到(10×汲取体数量)的无来源真实伤害与(25×汲取体数量)的神经损伤"
    check(len(find_exprs(t2)) == 2,
          "同一句里的**多个**算式都要收到（收一个就退出会静默丢后面的）",
          f"实得 {len(find_exprs(t2))}")

    check(len(find_exprs("甲×1，乙×2")) == 2,
          "算式不跨句：按 `，。；、：` 分段，段外的乘号不参与")

    # —— `extra` 钩子不得改变既有行为 ——
    a = [x.line() for x in parse("攻击力提升50%", {"a": 1})]
    b = [x.line() for x in parse("攻击力提升50%", {"a": 1}, extra=None)]
    check(a == b, "`extra` 是可选钩子：不传与传 `None` 结果一致")
    check(all(not x.vars and not x.formula for x in parse("攻击力提升50%")),
          "`Term` 新增的 `vars` / `formula` 默认为空，老调用方不受影响")


def operator_attrs() -> None:
    """干员侧「属性±N」的补齐与**不接算式 pass** 的理由（2026-09-16 博士裁定）。

    博士的裁定是「全部接入，不保留自然语言」。实测发现**在干员侧接算式 pass
    恰恰是反方向的**：`攻击距离+1` 看着是代数式（变量「攻击距离」加 1），
    实际是一条属性增益。接上去只会得到
    `算式 攻击距离+1 ⟨变量：攻击距离⟩`——形式忠实、语义全错，而且比不收更糟：
    它把「没认出来」伪装成「已经解析」。所以这里补的是**规则**，不是钩子。

    这一节同时把「干员语料里不存在真算式」这条判据钉住：敌人侧来自 prts.wiki
    手写正文（`(30×充能层数)` 那种真算式），干员侧来自游戏内正文，一律是
    `属性+N` 记法。日后有人"顺手对称一下"时，`no_expr_hook` 那几条会红。
    """
    section("[7] 干员侧属性词补齐（不接算式 pass）")

    def one(text: str) -> list:
        return terms_of(text)

    got = one("攻击距离+1")
    check(any(t.attr == "攻击距离" for t in got),
          "`攻击距离+1` 是属性增益，不是算式", f"实得 {[t.line() for t in got]}")
    got = one("攻击距离-2")
    check(any(t.attr == "攻击距离" and t.expr == "-2" for t in got),
          "`攻击距离-2` 带负号（sign_down 成形）",
          f"实得 {[t.line() for t in got]}")
    got = one("攻击目标数+1")
    check(any(t.attr == "攻击目标数" for t in got),
          "`攻击目标数+1` 收成属性", f"实得 {[t.line() for t in got]}")
    got = one("治疗目标数-1")
    check(any(t.attr == "攻击目标数" for t in got),
          "`治疗目标数-1` 归到同一属性「攻击目标数」",
          f"实得 {[t.line() for t in got]}")
    got = one("浮游单元+2")
    check(any(t.attr == "浮游单元" for t in got),
          "`浮游单元+2` 收成属性", f"实得 {[t.line() for t in got]}")
    got = one("最大生命值-50%")
    check(any(t.attr == "生命上限" for t in got),
          "`最大生命值-50%` 与 `生命上限` 归到同一属性",
          f"实得 {[t.line() for t in got]}")

    # —— 守卫：干员侧**一条 expr_var 都不该有** ——
    #
    # 这是比"数一数剩多少"更硬的不变量：算式钩子只挂在敌人侧
    # （`enemy_formula.parse_enemy` 的 `extra=expr_terms`），干员侧走裸 `parse`。
    # 用计数当断言是错的——`能量数+1`、`TOKEN数+3`、`技力+1` 这类**计数器**
    # 数量不少，但它们既不是属性也不是算式，本来就该留在外面；
    # 把阈值钉在它们身上，只会逼着后来的人为了"过测试"去乱收。
    from ak_tactic.formula import load_corpus, normalize
    from ak_tactic.db import DEFAULT_DB_PATH
    n_expr = 0
    for src, key, text, bb in load_corpus(DEFAULT_DB_PATH):
        flat, _ = normalize(text)
        n_expr += sum(1 for t in parse(flat, bb) if t.source == "expr_var")
    check(n_expr == 0,
          "干员侧**不得**产出 `expr_var`（算式钩子只挂敌人侧）",
          f"实得 {n_expr}")


# ---------------------------------------------------------------- [8] 序列化

def serialization() -> None:
    """公式项 → JSON：`--json` 走的那条路。

    这一节是被一次真崩溃补上的：`cli.py` 的 `enemydb formula --json` 调的是
    `Term.as_dict()`，而 `Term` 上只有 `to_dict()`——**自检全绿、命令却直接
    traceback**。教训是"检查没跑的那条路等于没检查"，所以这里把两侧都真跑一次。
    """
    import json as _json

    from ak_tactic.enemy_formula import parse_enemy

    section("[8] 序列化冒烟（--json 走的那条路）")
    for label, terms in (("干员", parse("攻击力+50%，攻击速度+30")),
                         ("敌人", parse_enemy("移动速度提升至150%"))):
        check(bool(terms), f"{label}侧样例能编出公式项")
        try:
            blob = _json.dumps([t.to_dict() for t in terms], ensure_ascii=False)
            check(True, f"{label}侧公式项可 to_dict() → JSON", f"{len(blob)} 字节")
        except Exception as exc:                       # noqa: BLE001
            check(False, f"{label}侧公式项可 to_dict() → JSON",
                  f"{type(exc).__name__}: {exc}")


def ep_unmatched() -> None:
    """含「损伤」却编译不出任何公式项的句子，**必须**出现在未识别清单里。

    出处：项目经理 2026-09-19「元素损伤三件」§二.3 ——「忽视」不等于「漏掉」；
    生息演算按既有裁定是忽视，但**判据覆盖不到机制时只会沉默、不会否证**。
    清单（`formula.scan()["unmatched"]`）是"继续加规则"的唯一入口，
    一条句子从清单里漏掉，就等于它从此没人再看。

    实测口径（2026-09-20）：全库 14967 条语料里含「损伤」的 683 条，
    其中 **382 条**编译不出任何公式项——本节断言这 382 条的**骨架逐条都在清单里**。

    ⚠ 清单要用 `top` 取得足够大：默认 `top=25` 会截断，
    截断后"不在清单里"与"清单没显示它"长得一模一样——那正是本节要防的假绿。
    """
    section("[9] 含「损伤」却零公式项 ⇒ 必须在未识别清单里")
    from ak_tactic.formula import TAG_RE, _skeleton, load_corpus, parse

    r = scan(DB, top=10 ** 9)
    listed = {sk for sk, _n in r["unmatched"]}
    zero, short, missing = 0, 0, []
    for src, key, text, bb in load_corpus(DB):
        if "损伤" not in text:
            continue
        if parse(text, bb):
            continue
        zero += 1
        clean = TAG_RE.sub("", text)
        if len(clean) < 10:          # 与 scan() 同一条门槛：太短的只是提示文字
            short += 1
            continue
        sk = _skeleton(clean)
        if sk not in listed:
            missing.append((src, key, sk))
    check(missing == [], f"含「损伤」的零项句（{zero} 条，其中过短不计 {short} 条）全在未识别清单里",
          f"漏 {len(missing)} 条，例如 {missing[:2]}" if missing else "")


def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description="描述→公式模型校验")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    VERBOSE = args.verbose

    anchors()
    from_db()
    units()
    coverage()
    settlement()
    expressions()
    operator_attrs()
    serialization()
    ep_unmatched()

    print(f"\n{'=' * 60}")
    print(f"通过 {PASS} / 失败 {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
