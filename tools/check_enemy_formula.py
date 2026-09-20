# -*- coding: utf-8 -*-
"""敌人公式项自检。

分六节：**清洗**（wiki 模板 → 纯文本）、**语料**（五类来源与条数）、
**锚点**（真实句子 → 期望的规则与 kind）、**量纲与表达式**、
**精度守卫**（每条都对应一次真实的过度匹配）、**覆盖率下限**。

跑法：`python tools/check_enemy_formula.py`
"""
from __future__ import annotations

import collections
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ak_tactic import enemy_formula                                 # noqa: E402
from ak_tactic import formula                                       # noqa: E402
from ak_tactic.db import DEFAULT_ENEMY_DB_PATH                      # noqa: E402
from ak_tactic.enemy_formula import (ENEMY_RULES, RULES_ENEMY,       # noqa: E402
                                     detemplate, enemy_scan,
                                     load_enemy_corpus, parse_enemy)

_PASSED = 0
_FAILED: list[str] = []

#: 抓一个完整的 `{{特殊机制|…}}`（参数里不含花括号——引用都是浅层的，够用）。
#: 用它做"有没有被洗成空串"的扫描，比在语料里数正文更可靠。
_MECH_CALL = re.compile(r"\{\{\s*特殊机制\s*\|[^|{}]*(?:\|[^|{}]*)*\}\}")


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(label)
        print(f"  [FAIL] {label}" + (f"   {detail}" if detail else ""))


def close(a, b, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def rules_of(text: str) -> list[str]:
    return [t.source for t in parse_enemy(detemplate(text))]


def kinds_of(text: str) -> set[str]:
    return {t.kind for t in parse_enemy(detemplate(text))}


# ---------------------------------------------------------------- 1 清洗

def check_detemplate() -> None:
    print("\n[1] 清洗：prts.wiki wikitext → 纯文本")
    check("`{{术语|ba.stun|晕眩}}` 取位置参数 1（丢掉内部术语 id）",
          detemplate("免疫{{术语|ba.stun|晕眩}}") == "免疫晕眩",
          repr(detemplate("免疫{{术语|ba.stun|晕眩}}")))
    check("`{{color|#FF4F0B|第一形态}}` 取位置参数 1",
          detemplate("{{color|#FF4F0B|第一形态}}") == "第一形态")
    check("`{{异常效果|失衡|免疫}}` 两个位置参数**拼成一个词**",
          detemplate("{{异常效果|失衡|免疫}}") == "失衡免疫",
          repr(detemplate("{{异常效果|失衡|免疫}}")))
    check("`{{修正lite|新|原文=旧|原因=6}}` 取勘误后文本",
          detemplate("{{修正lite|并不会失效|原文=并使失效|原因=6}}") == "并不会失效")
    check("嵌套模板从最内层展开（顶层剥不了嵌套）",
          detemplate("{{color|#FFF|{{术语|ba.stun|晕眩}}}}") == "晕眩",
          repr(detemplate("{{color|#FFF|{{术语|ba.stun|晕眩}}}}")))
    check("不认识的模板取最后一个非空位置参数（宁可留词）",
          detemplate("持有{{例外|无敌}}") == "持有无敌",
          repr(detemplate("持有{{例外|无敌}}")))

    # 单位引用必须活到 normalize 之后，否则"召唤了什么"就没了
    check("`<无谓>` 单位引用换成「无谓」，不被当富文本标签剥掉",
          detemplate("召唤1个<无谓>") == "召唤1个「无谓」",
          repr(detemplate("召唤1个<无谓>")))
    check("真富文本标签原样留着交给 normalize 处理",
          detemplate("<$ba.stun>眩晕</>") == "<$ba.stun>眩晕</>"
          and detemplate("普通攻击<br>造成伤害") == "普通攻击，造成伤害")
    check("内链 `[[页名|文字]]` 摊平成文字",
          detemplate("见[[解构畸变体|畸变体]]") == "见畸变体")

    corpus = load_enemy_corpus(DEFAULT_ENEMY_DB_PATH)
    left = [r for r in corpus if "{{" in detemplate(r["text"])
            or "}}" in detemplate(r["text"])]
    check("全量语料洗完零残留花括号", not left, f"残留 {len(left)} 条")

    # ★ `{{特殊机制|…}}` 是**唯一**会把整段引用洗成空串的形态：它的正文取第 0 个
    #   位置参数，而页面上存在把机制名写成命名参数的写法
    #   （`{{特殊机制|名称=病害|病害值|color=yellowgreen}}`，怀黍离活动页原文）。
    #   一旦出现**只有**命名参数的调用，`detemplate` 会静默返回空串——
    #   整句话的宾语凭空消失且不报错。这条守卫盯着它。
    calls = [c for r in corpus for c in _MECH_CALL.findall(r["text"])]
    empties = [c for c in calls if not detemplate(c).strip()]
    check("★ 语料里没有「展开成空串」的 {{特殊机制|…}} 调用",
          not empties,
          f"空了 {len(empties)} 处" + (f"，例：{empties[0]}" if empties else ""))
    named = [c for c in calls
             if any("=" in a for a in c.split("|")[1:])]
    print(f"       语料里 {{特殊机制}} 调用共 {len(calls)} 处，"
          f"其中带命名参数的 {len(named)} 处"
          + (f"（例：{named[0]}）" if named else ""))


# ---------------------------------------------------------------- 2 语料

def check_corpus() -> None:
    print("\n[2] 语料")
    corpus = load_enemy_corpus(DEFAULT_ENEMY_DB_PATH)
    got = {}
    for r in corpus:
        got[r["source"]] = got.get(r["source"], 0) + 1
    check(f"共 {len(corpus)} 条", len(corpus) > 6000, str(got))
    for src, want in (("ability", 1574), ("ability_fixed", 114),
                      ("talent", 1870), ("desc", 2025), ("skill", 1352)):
        check(f"来源 {src} = {want}", got.get(src) == want, f"实得 {got.get(src)}")
    withbb = sum(1 for r in corpus if r["blackboard"])
    check("有黑板的语料 > 3000 条（黑板按同档取）", withbb > 3000, f"实得 {withbb}")


# ---------------------------------------------------------------- 3 锚点

ANCHORS: tuple[tuple[str, str, str], ...] = (
    # (句子, 期望规则, 期望 kind)
    ("·无法被阻挡", "e_unblockable", "block"),
    ("无敌、自缚，无法攻击/被阻挡", "e_invincible", "invincible"),
    ("自缚、失衡免疫，无法攻击/被阻挡", "e_self_bind", "block"),
    ("获得200s无敌", "e_invincible_dur", "invincible"),
    ("免疫失衡", "e_immune_prefix", "immune"),
    ("失衡免疫", "e_immune_suffix", "immune"),
    ("弱点：物理；免疫：元素", "e_weakness", "trait"),
    ("位于结晶所在地块时，移动速度+90%", "e_movespeed_up", "movespeed"),
    ("每损失20%生命值，移动速度大幅提升", "e_movespeed_word_up", "movespeed"),
    ("失衡移动后，移动速度提升并变为不可阻挡", "e_unblockable", "block"),
    ("自身每秒受到330无来源真实伤害", "e_self_dot", "selfharm"),
    ("首次倒下后重生为<大君之触>", "e_revive_after", "revive"),
    ("进入持续20s的重生", "e_revive_dur", "revive"),
    ("切换至第二形态", "e_form_switch", "form"),
    ("远程攻击未命中后变为近战", "e_form_become", "form"),
    ("获得隐匿", "e_stealth", "stealth"),
    ("获得可吸收相当于当前最大生命值50%的全伤害屏障", "e_shield_maxhp", "shield"),
    ("未被阻挡时获得40%庇护", "e_unblocked_shelter", "buff"),
    ("未被阻挡时有几率闪避物理攻击", "e_unblocked_dodge", "dodge"),
    ("伤害倍率降低35%", "e_damage_reduce_pct", "buff"),
    ("以预设路径召唤巫术石球", "e_summon", "summon"),
    ("被击倒后生成1个<饮啄>", "e_summon", "summon"),
    ("放下结晶", "e_place", "flag"),
    ("飞行单位", "e_fly", "fly"),
    ("不进行普通攻击，无法被阻挡", "e_no_attack", "flag"),
    ("蓄力5s，期间倒地时蓄力与技能强制终止", "e_channel", "channel"),
    ("反弹部分本应受到的伤害", "e_reflect", "reflect"),
    ("嘲讽等级+1", "e_taunt_level", "taunt"),
    ("元素脆弱", "e_fragile", "fragile"),
    ("生命值首次低于25%时，获得屏障", "e_hp_trigger", "flag"),
    ("技能结束时自身强制退场", "e_retreat_forced", "flag"),
    ("攻击数次，偷取我方3费用，并回复5%生命值", "e_steal_cost", "cost"),
    # 干员的 `buff_*` 只认游戏内 `+N` 记法，prts.wiki 手写正文用的是「提升N」
    ("攻击力提升50", "e_attr_up", "buff"),
    ("防御力降低30%", "e_attr_down", "debuff"),
    ("被阻挡时立即变为随机敌人", "e_form_become", "form"),
    # —— 干员规则仍要照常命中（证明两套规则合起来用）——
    ("造成相当于攻击力210%的法术伤害", "damage_atk", "damage"),
    ("攻击速度+50", "buff_aspd", "buff"),
)


def check_anchors() -> None:
    print("\n[3] 锚点：真实句子 → 期望规则")
    for text, rule, kind in ANCHORS:
        got = rules_of(text)
        ok = rule in got
        detail = f"实得 {got}" if not ok else ""
        check(f"「{text[:26]}」命中 {rule}", ok, detail)
        if ok:
            ks = kinds_of(text)
            check(f"  同上 kind = {kind}", kind in ks, f"实得 {sorted(ks)}")


# ---------------------------------------------------------------- 4 量与式

def check_values() -> None:
    print("\n[4] 数值与表达式")
    t = parse_enemy(detemplate("自身每秒受到330无来源真实伤害"))[0]
    check("自身每秒受到 330 → amount=330、dtype=TRUE",
          close(t.amount.value, 330) and t.dtype == "TRUE",
          f"amount={t.amount.value} dtype={t.dtype}")
    t = parse_enemy(detemplate("获得200s无敌"))[0]
    check("获得200s无敌 → duration=200",
          close(t.duration.value, 200), f"实得 {t.duration.value}")
    t = parse_enemy(detemplate("位于结晶所在地块时，移动速度+90%"))[0]
    check("移动速度+90% → 带正号、单位是百分数",
          close(t.amount.value, 90) and t.expr.startswith("+"),
          f"expr={t.expr!r}")
    t = parse_enemy(detemplate("伤害倍率降低35%"))[0]
    check("伤害倍率降低35% → 带负号（减伤不是增益）",
          t.expr.startswith("-"), f"expr={t.expr!r}")
    t = parse_enemy(detemplate("进入持续20s的重生"))[0]
    check("进入持续20s的重生 → duration=20", close(t.duration.value, 20))
    t = parse_enemy(detemplate("被击倒后生成1个<饮啄>"))[0]
    check("生成1个 → count=1", close(t.count.value, 1), f"实得 {t.count.value}")

    # 无数值形状：expr 必须留空，好让 flag 填进去
    t = parse_enemy(detemplate("无法被阻挡"))[0]
    check("不可阻挡 → expr 为空、flag 落在 expr 上",
          t.expr == "不可阻挡", f"expr={t.expr!r}")

    # 干员侧的量纲机器必须仍然生效
    t = parse_enemy(detemplate("造成相当于攻击力210%的法术伤害"))[0]
    check("攻击力210% 不被再乘 100（量纲 PCT 不重复换算）",
          close(t.amount.value, 210) and t.amount.pct,
          f"amount={t.amount.value} pct={t.amount.pct}")


# ---------------------------------------------------------------- 5 精度守卫

def check_precision() -> None:
    print("\n[5] 精度守卫（每条对应一次真实的过度匹配）")
    check("「释放源石技艺」**不算召唤**",
          "e_summon" not in rules_of("释放源石技艺"),
          f"实得 {rules_of('释放源石技艺')}")
    check("「释放当前波次」不算召唤",
          "e_summon" not in rules_of("释放当前波次"))
    check("「放下结晶」走放置、不当召唤",
          rules_of("放下结晶") == ["e_place"],
          f"实得 {rules_of('放下结晶')}")
    check("「被阻挡时立即变为随机敌人」走形态、不当属性增益",
          "e_form_become" in rules_of("被阻挡时立即变为随机敌人"),
          f"实得 {rules_of('被阻挡时立即变为随机敌人')}")
    check("「未被阻挡时获得40%庇护」是减伤，**不当闪避**",
          "e_unblocked_shelter" in rules_of("未被阻挡时获得40%庇护")
          and "e_unblocked_dodge" not in rules_of("未被阻挡时获得40%庇护"),
          f"实得 {rules_of('未被阻挡时获得40%庇护')}")
    check("「获得200s无敌」整段被吃掉，不会再多出一个裸无敌项",
          rules_of("获得200s无敌") == ["e_invincible_dur"],
          f"实得 {rules_of('获得200s无敌')}")
    check("规则名唯一（重名会让溯源指向两条规则）",
          len({r.name for r in ENEMY_RULES}) == len(ENEMY_RULES))
    check("敌人规则表里没有与干员规则重名的",
          not ({r.name for r in ENEMY_RULES} & {r.name for r in formula.RULES}))

    # —— 中文数字：量词里是习语，序数里是真数 ——
    got = [t for t in parse_enemy(detemplate("【最后的奖赏】蓄力一段时间后"))
           if t.source == "e_channel"]
    check("「蓄力**一**段时间」不得算出「持续 1 秒」（量词里的中文数字不是数值）",
          got and got[0].duration is None,
          f"实得 duration={got[0].duration.value if got and got[0].duration else None}")
    check("「切换至第**二**形态」照常命中（序数里的中文数字是真数值）",
          "e_form_switch" in rules_of("切换至第二形态"),
          f"实得 {rules_of('切换至第二形态')}")
    got = [t for t in parse_enemy(detemplate("攻击速度提升，")) 
           if t.source.startswith("e_attr")]
    check("「攻击速度提升」（无数值）走 word 档、且不带编造的数值",
          got and got[0].amount is None and got[0].source == "e_attr_word_up",
          f"实得 {[(t.source, t.amount) for t in got]}")
    check("「免疫法术伤害」被认作免疫伤害类型",
          "e_immune_damage" in rules_of("免疫法术伤害"),
          f"实得 {rules_of('免疫法术伤害')}")


# ---------------------------------------------------------------- 6 覆盖率

FLOOR_TOTAL = 0.65
FLOOR_BY_SOURCE = {"talent": 0.85, "skill": 0.70, "ability": 0.65}


def check_coverage() -> None:
    print("\n[6] 覆盖率下限")
    base = enemy_scan(DEFAULT_ENEMY_DB_PATH, rules=formula.RULES)
    full = enemy_scan(DEFAULT_ENEMY_DB_PATH)
    bt, ft = base["hit_rows"], full["hit_rows"]
    print(f"  仅干员规则 {bt}/{base['rows']} = {bt / base['rows'] * 100:.1f}%"
          f"  →  加敌人规则 {ft}/{full['rows']} = {ft / full['rows'] * 100:.1f}%")
    check(f"总覆盖率 ≥ {FLOOR_TOTAL:.0%}", ft / full["rows"] >= FLOOR_TOTAL,
          f"实得 {ft / full['rows'] * 100:.1f}%")
    check("敌人规则确实补了至少 40 个百分点", ft - bt >= 0.40 * full["rows"],
          f"补了 {(ft - bt) / full['rows'] * 100:.1f} 个点")
    for src, floor in FLOOR_BY_SOURCE.items():
        v = full["by_source"][src]
        check(f"{src} 覆盖率 ≥ {floor:.0%}", v["hit"] / v["total"] >= floor,
              f"实得 {v['hit'] / v['total'] * 100:.1f}%")
    # desc 里大量是剧情/风味描述，**不该**被解析；只保证没有离奇倒退
    d = full["by_source"]["desc"]
    check("desc 覆盖率不高于 55%（其中多是风味文本，过高的解析率说明规则过宽）",
          d["hit"] / d["total"] <= 0.55, f"实得 {d['hit'] / d['total'] * 100:.1f}%")
    check("命中的语料条数 > 未命中（基本盘已过半数）",
          full["hit_rows"] > full["rows"] - full["hit_rows"])

    # 统计函数必须与真编译器**逐行同口径**：`enemy_scan` 早先漏挂了算式钩子
    # （`expr_terms`），报 68.4% 而 `parse_enemy` 实为 69.3%——差的 63 行全是
    # "只被算式救回"的行。CLI 照它打印，等于把编译器的成绩报低。谁再把钩子摘掉，
    # 这一条就红。
    recount = sum(1 for row in load_enemy_corpus(DEFAULT_ENEMY_DB_PATH)
                  if parse_enemy(detemplate(row["text"]), row["blackboard"]))
    check("enemy_scan 与 parse_enemy 逐行同口径（统计不许漏挂钩子）",
          recount == ft, f"scan {ft} / 逐行 {recount}")


def check_second_wave() -> None:                                      # noqa: C901
    """第二轮补的家族规则 + 两条本轮真踩到的坑。"""
    print("\n[7] 第二轮家族规则（长尾里成簇的那几类）")

    # —— 「分条目切分」为什么被删掉了 ——
    # 这一节守的是删除所依赖的**结构前提**，不是某个行为。
    long_text = ("·只能被阻挡数大于等于3的单位阻挡，·每隔一段时间，"
                 "优先以高台干员为目标放出一个「甜蜜派送机」")
    check("长清单文本靠**子串匹配**就能收走（与切分无关）",
          len(parse_enemy(detemplate(long_text))) >= 1,
          f"实得 {rules_of(long_text)}")
    _unanchored = all(not r.pattern.startswith("^") and not r.pattern.endswith("$")
                      for r in tuple(ENEMY_RULES) + tuple(formula.RULES))
    check("规则表全是**无锚定**的（切分对召回是恒等变换，前提即此）",
          _unanchored,
          "" if _unanchored else
          "有规则被锚定了——「整句为空则逐条重试」不再是恒等变换，"
          "需要把删掉的切分器拿回来（见 enemy_formula 里那段注释）")
    check("模块里不再留 split_clauses（死代码比不留更坏）",
          not hasattr(enemy_formula, "split_clauses"))

    # —— 阻挡门槛 ——
    t = parse_enemy("只能被阻挡数大于等于3的单位阻挡", None)[0]
    check("阻挡门槛读出门槛值 3，且是门槛不是自己的阻挡数",
          t.source == "e_block_threshold" and t.attr == "阻挡数门槛"
          and t.expr == "3", f"{t.source} {t.attr} {t.expr}")
    check("「不小于」与「大于等于」同解",
          parse_enemy("只能被守门员或阻挡数不小于4的单位阻挡", None)[0].expr == "4")
    check("「占用N个阻挡数」与门槛区分开（两条语义不同的规则）",
          parse_enemy("占用3个阻挡数", None)[0].attr == "占用阻挡数")

    # —— 否定式属性 ——
    check("「无法被攻击」= 不可被选中，**不是**「它不攻击」（主语不能反）",
          parse_enemy("无法被攻击", None)[0].kind == "invincible",
          f"实得 {rules_of('无法被攻击')}")
    check("「无法攻击」才是它不攻击",
          parse_enemy("无法攻击", None)[0].kind == "flag")
    check("「不可沉默」记成免疫沉默", 
          parse_enemy("不可沉默", None)[0].attr == "沉默")
    check("「不可对空」是索敌限制", parse_enemy("不可对空", None)[0].kind
          == "targets")
    check("「索敌不受阻挡影响」可查（这是已确认的敌人硬规则之一）",
          parse_enemy("索敌不受阻挡影响", None)[0].kind == "targets")

    # —— 元素损伤：正文只给种类，数值在同档黑板 ——
    t = parse_enemy("每次攻击造成一定侵蚀损伤", None)[0]
    check("「造成一定侵蚀损伤」认出种类、且量纲记 word（数值不编）",
          t.kind == "ep_damage" and t.attr == "侵蚀" and t.amount is None,
          f"{t.kind} {t.attr} amount={t.amount}")

    # —— 生死语义：word 形态的值落在 `expr` 上（Term 没有 flag 字段） ——
    check("「消失时不会扣除目标生命」可查（与 target_value 相反的口径，影响三星判定）",
          parse_enemy("消失时不会扣除目标生命", None)[0].expr == "漏掉不扣生命")
    check("「不计入歼灭数」同解",
          parse_enemy("不计入歼灭数", None)[0].expr == "漏掉不扣生命")

    # —— 本轮真踩到的静默算错 ——
    to = parse_enemy("移动速度最终提升至500%", None)[0]
    up = parse_enemy("移动速度最终提升50%", None)[0]
    check("「提升**至**N%」= 设为目标值，**不是** +N%（差 6 倍且看着都对）",
          to.source == "e_movespeed_to" and to.expr == "500%",
          f"{to.source} {to.expr}")
    check("「提升N%」仍是增量 +N%",
          up.source == "e_movespeed_up" and up.expr == "+50%",
          f"{up.source} {up.expr}")
    check("「移动速度变为2倍」「移动速度降低50%」不回归",
          parse_enemy("移动速度变为2倍", None)[0].expr == "2"
          and parse_enemy("移动速度降低50%", None)[0].expr == "-50%")

    # —— 溅射：类型不明就不要替它填 ——
    sp = parse_enemy("攻击造成法术溅射伤害", None)[0]
    check("「法术溅射伤害」带上伤害类型 ARTS",
          sp.kind == "damage" and sp.dtype == "ARTS", f"{sp.dtype}")
    bare = parse_enemy("对周围我方单位造成物理伤害", None)[0]
    check("「对周围…造成物理伤害」= PHYSICAL",
          bare.kind == "damage" and bare.dtype == "PHYSICAL", f"{bare.dtype}")

    # —— 新规则不得与旧规则抢文字 ——
    check("新补 15 条规则名互不重复",
          len({r.name for r in ENEMY_RULES[53:]}) == len(ENEMY_RULES) - 53)
    check("新规则名与旧 53 条无重名",
          not ({r.name for r in ENEMY_RULES[53:]} & {r.name for r in ENEMY_RULES[:53]}))


def check_expressions() -> None:                                       # noqa: C901
    """带变量的算式接进 `parse_enemy` 之后的行为与精度守卫。

    这一节的立场：**算式项是「结构」，不是「数值」**——`amount` 一律为空，
    `expr` 保留算式本身，`vars` 列出依赖。任何"顺手求个值"的实现都该在这里红。
    """
    print("\n[8] 带变量的算式（接入与精度守卫）")

    def one(text: str) -> Any:
        got = [t for t in parse_enemy(text, None) if t.source == "expr_var"]
        return got[0] if got else None

    # —— 属性与作用对象 ——
    t = one("自身移动速度+(50%×加速层数)（增益数值仅于特定时机更新），每0.5s检测一次")
    check("认到移速、值就是算式本身、变量列出来",
          t is not None and t.kind == "movespeed" and t.attr == "移动速度"
          and t.expr == "(50%×加速层数)" and t.vars == ["加速层数"],
          f"实得 {t.line() if t else None}")
    check("**不编数值**：amount 必须为空（算式编译期求不出值）",
          t is not None and t.amount is None)

    t = one("②攻击命中部署于重力感应机关所在地块的我方单位时，使其阻挡数×0，持续3s")
    check("「使其阻挡数×0」= 阻挡数归零，且作用对象是**我方**",
          t is not None and t.kind == "block" and t.attr == "阻挡数"
          and t.op == "enemy" and t.expr == "0", f"实得 {t.line() if t else None}")

    t = one("每秒受到(层数×300)无来源真实伤害，最多叠加10层")
    check("`每秒受到(算式)` 认成持续伤害", t is not None and t.kind == "dot")

    t = one("攻击力+（场上的啸叫音响数量×25%）")
    check("全角括号也要认，属性取 `攻击力`",
          t is not None and t.attr == "攻击力" and t.expr == "(场上的啸叫音响数量×25%)",
          f"实得 {t.line() if t else None}")

    t = one("自身防御力+(30×充能层数)%，普通攻击附加")
    check("`(30×充能层数)%` 的整体百分比记在 note 里，不改表达式",
          t is not None and "整体为百分比" in t.note and t.expr == "(30×充能层数)")

    t = one("自身移动速度最终提升至(100%+增益层数×25%)")
    check("算式被「提升至」和属性隔开时，仍能往回找到属性",
          t is not None and t.kind == "movespeed" and t.attr == "移动速度",
          f"实得 {t.line() if t else None}")

    t = one("成功造成伤害后再造成当前移动速度×800的预计算近战途径物理伤害")
    check("`当前移动速度×800` **不是**「改移速」——是拿移速当系数算伤害",
          t is None or t.attr != "移动速度",
          f"实得 {t.line() if t else None}")
    check("但那个量也不能丢，留在 vars 里",
          t is not None and "当前移动速度" in t.vars,
          f"实得 {t.vars if t else None}")

    # —— 不重复：规则咬走的片段算式不再出一项 ——
    got = parse_enemy("出场后进入持续4s的【潜行】状态：移动速度+110%", None)
    check("已被规则收走的片段不再出算式项（否则同一件事记两遍）",
          sum(1 for x in got if x.source == "expr_var") == 0,
          f"实得 {[(x.source, x.expr) for x in got]}")
    check("而且那条规则本身照常命中",
          any(x.source == "e_movespeed_up" for x in got))

    # —— 纯追加：算式只可能让结果变多 ——
    corpus = load_enemy_corpus(DEFAULT_ENEMY_DB_PATH)
    def sig(ts):
        return set((x.kind, x.expr, x.attr, x.dtype, x.op, x.source) for x in ts)
    lost = notpure = with_expr = rows_expr = 0
    for c in corpus[:1500]:
        flat = detemplate(c["text"])
        o = sig(formula.parse(flat, c["blackboard"], rules=RULES_ENEMY))
        n = sig(parse_enemy(flat, c["blackboard"]))
        ex = [x for x in parse_enemy(flat, c["blackboard"])
              if x.source == "expr_var"]
        if ex:
            rows_expr += 1
            with_expr += len(ex)
        if not n and o:
            lost += 1
        elif not (o <= n):
            notpure += 1
    check("算式 pass 不丢项（抽样 1500 条）", lost == 0, f"实得丢 {lost}")
    check("算式 pass 不动已匹配的旧项（纯追加）", notpure == 0, f"实得动 {notpure}")
    check("抽样里确实收到了算式项（不是空转）", with_expr > 0,
          f"实得 {with_expr} 项 / {rows_expr} 条")

    # —— 精度：全语料不许出现这几类 ——
    bad: list[str] = []
    for c in corpus:
        flat = detemplate(c["text"])
        for x in parse_enemy(flat, c["blackboard"]):
            if x.source != "expr_var":
                continue
            f_ = x.formula
            if re.search(r"(?<!\d)1×1|3×3|2×2", f_):
                bad.append(f"尺寸标注被当算式：{f_}")
            elif re.search(r"[物理法术真实元素神经]/[物理法术真实元素神经]", f_):
                bad.append(f"斜杠并列被当除法：{f_}")
            elif x.amount is not None:
                bad.append(f"算式项竟然带了数值：{f_}")
            elif any(ch.isdigit() for ch in "".join(x.vars)):
                bad.append(f"变量名里带数字（散文碎片）：{f_} {x.vars}")
    check("全语料：没有尺寸标注 / 斜杠并列 / 编造数值 / 散文碎片变量",
          not bad, "\n        ".join(bad[:5]) if bad else "")

    # —— 算式项只能来自本 pass，规则表里不许混进算式规则 ——
    check("规则表里没有叫 expr_var 的规则（算式只能从 pass 出来）",
          all(r.name != "expr_var" for r in RULES_ENEMY))


def check_attr_table() -> None:
    """属性表的**收录口径**守卫（博士 2026-09-16 裁定 + 回填的排除名单）。

    裁定是「只留战斗结算真正用得到的」，未填的部分按我的建议走，而那 93 条
    建议几乎全是**排除**——它们是散文碎片，不是属性名。

    这里钉的不是「哪些词没收」（逐词列一遍会随语料腐烂），而是**词条的形状**：
    属性名必须是短词、不含动词。这条守得住，散文碎片就进不来。
    反面例子（都曾在候选里出现过）：`范围内的田地地块病害值`、
    `每次普通攻击使自身攻击间隔`、`被该效果击倒的干员再部署时间`。

    长度上限取 12 而不是 8：`可抵抗状态生效时间倍率` 有 11 字，但它是**真属性名**
    （敌人正文写「【明力】可抵抗状态生效时间倍率」），不是碎片。这条阈值是我
    先定 10 后被它顶红才改的——**阈值要按真实反例校正，不能凭手感**。
    """
    from ak_tactic.enemy_formula import _EXPR_ATTR
    check("[属性表] 条目数已按裁定扩到 30 以上", len(_EXPR_ATTR) >= 30,
          f"实得 {len(_EXPR_ATTR)}")
    long_words = [w for w, _, _ in _EXPR_ATTR if len(w) > 12]
    check("[属性表] 没有长句词条（散文碎片不得当属性名）", not long_words,
          f"实得 {long_words}")
    verb_words = [w for w, _, _ in _EXPR_ATTR
                  if re.search(r"使|被|位于|判定|拥有|获得|造成", w)]
    check("[属性表] 词条里没有动词（有动词的就是句子不是属性）", not verb_words,
          f"实得 {verb_words}")
    dupes = [a for a, n in collections.Counter(
        w for w, _, _ in _EXPR_ATTR).items() if n > 1]
    check("[属性表] 没有重复词条（重复会让表序变得不可推理）", not dupes,
          f"实得 {dupes}")
    # 裁定明确要保留的两处（怀黍离 / 红丝绒），钉住免得日后被"清理"掉
    words = [w for w, _, _ in _EXPR_ATTR]
    check("[属性表] 怀黍离的田地病害值保留", "田地地块病害值" in words)
    check("[属性表] 红丝绒的飞行速度保留", "飞行速度" in words)
    check("[属性表] 裸「速度」按移速收", "速度" in words)


def main() -> int:
    print(f"检查敌人公式项：{DEFAULT_ENEMY_DB_PATH}")
    print(f"规则：干员 {len(formula.RULES)} 条 + 敌人 {len(ENEMY_RULES)} 条 "
          f"= {len(RULES_ENEMY)} 条")
    check_detemplate()
    check_corpus()
    check_anchors()
    check_values()
    check_precision()
    check_coverage()
    check_second_wave()
    check_expressions()
    check_attr_table()
    print()
    print("=" * 60)
    if _FAILED:
        print(f"通过 {_PASSED} 项，失败 {len(_FAILED)} 项：")
        for name in _FAILED:
            print(f"   ✗ {name}")
        return 1
    print(f"通过 {_PASSED} 项，无失败。")
    return 0


if __name__ == "__main__":
    #: ★ 判据的输出不许依赖终端编码（2026-09-20 修，PM 裁定 msg-mu9cwt89-ll 第二节）。
    #: 本机 `sys.stdout.encoding` **默认就是 gbk**（PYTHONIOENCODING 未设），而本文件的输出里
    #: 含 ✓／✗／⇒／− 等 GBK **编不出**的字符 ⇒ **印总结行时**抛 UnicodeEncodeError
    #: ⇒ 退出码由崩溃给出：实测改前**恒 rc=1**，与它要判的东西毫无关系
    #: （＝一个从不发光的守卫；PM 每次 push 前的「tools/check_*.py 全绿」判据因此失去分辨力）。
    #: 只放宽错误处理器、**不改编码**：编不出的字符退化成转义文本，信息不丢，既有输出形状一字未动。
    #: ★ 全部写在 `__main__` 里：作为模块被 import 时行为**一字不变**。
    import sys as _sys
    try:
        _sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:  # noqa: BLE001 - 不支持 reconfigure 的流 ⇒ 不适用，继续
        pass
    try:
        _rc = main()
    except BaseException as _e:  # noqa: BLE001 - 崩了必须是**与业务态不重叠**的一个值
        print(f"VERDICT=SELFCHECK_CRASH EXC={type(_e).__name__}: {_e}")
        _rc = 5
    #: ASCII 机读判定行：rc 从此是它自己的结论（0 无失败／1 有失败／5 没能判定）。
    print(f"VERDICT={'PASS' if _rc == 0 else 'FAIL'} rc={_rc}")
    raise SystemExit(_rc)
