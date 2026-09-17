# -*- coding: utf-8 -*-
"""地图机制自检。

分八节：**解析**（嵌套模板与花括号配平）、**术语表**（条数与分节）、
**锚点**（真实正文 → 期望的规则与 kind）、**关卡页字段**、
**精度守卫**（每条都对应一次真实的静默错误）、**不该编译的条目与已知误读**、
**覆盖率下限**。

绝大多数检查是**离线**的：用的正文是逐字抄自 prts.wiki 的字面量。
只有 [2] 的"活页面"以及 [6][7] 要联网，取不到就跳过并说明，不算失败。

跑法：`python tools/check_mechanics.py`
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ak_tactic import mechanics as M                                  # noqa: E402

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


# ---------------------------------------------------------------- 字面量
#
# 下面两段是**逐字**抄自 prts.wiki 的原始 wikitext（不是转写、不是记忆）。
# 它们同时充当"解析器能不能吃下真语料"的证据。

TIAN_RAW = (
    "田地|仅适用于'''地形标记'''为'''默认'''的地面地块（传送门出入口/地穴除外）。"
    "|※“地形标记”详见：[[作战机制#扩展阅读：地块]]。|[[文件:头像 敌人 秽.png|50px|link=秽]]"
)

BINGHAI_RAW = (
    "病害值|范围0～100。田地拥有【实际病害值】，未被隔断的连片田地拥有共同的【最大病害值】。"
    "<br>未被污染（病害值{{=}}0）时：其中的我方单位每秒回复50点生命值。"
    "<br>受到污染（病害值&gt;0）时：【缓存】获得的病害，每0.2s释放1点病害值累加至当前的"
    "【最大病害值】上；每1秒更新自身的【实际病害值】直到达到【最大病害值】"
    "（与最大值的差值每25点+1实际病害值，小数部分上入）。"
    "<br>位于其中的我方单位受影响时立刻受到 基础伤害+实际病害值×一定比例 的环境法术伤害；"
    "每秒受到 基础伤害+实际病害值×一定比例 的环境法术伤害。"
    "||[[文件:头像 敌人 秽.png|50px|link=秽]]"
)

#: 带**嵌套同层模板**的正文——解析器最容易在这里静默截断。
NESTED_RAW = (
    "洋红蒸汽|生成时，对范围内我方单位造成250点无来源法术伤害+350点"
    "{{术语|ba.dt.burning|灼燃损伤}}。<br>位于洋红蒸汽范围内的地面敌方单位"
    "受到的物理/法术伤害降低75%。|{{特殊机制|伤害相性（P3R）}}|[[文件:头像 敌人 秽.png]]"
)

GLOSSARY_PAGE = (
    "== 常用的基础机制 ==\n"
    "=== 战场效果 ===\n"
    "{{特殊机制表格|" + TIAN_RAW + "}}\n"
    "{{特殊机制表格|" + BINGHAI_RAW + "}}\n"
    "{{特殊机制表格|" + NESTED_RAW + "}}\n"
    "=== 伤害机制 ===\n"
    "{{特殊机制表格|生命流失|指一类带有“跳过各种伤害处理事件”标签的伤害。||}}\n"
)

# 逐字取自 HS-8「特殊地形效果」与 HS-EX-8 的关卡页。
# **提成模块级常量**：死规则守卫与锚点节都要用，两处各写一份迟早会漂。
HS8_TEXT = ("'''田地'''<br/>位于病害值=0低地的我方单位，每秒恢复50生命值；"
            "位于病害值>0低地的我方单位，每秒受到20+病害值×3法术环境伤害；"
            "我方单位部署于位于病害值>0的低地时，立刻受到100+病害值×9的法术环境伤害")
HEX8_TEXT = ("'''田地'''<br/>位于病害值=0低地的我方单位，每秒恢复50生命值；"
             "位于病害值>0低地的我方单位，每秒受到30+病害值×4法术环境伤害；"
             "我方单位部署于位于病害值>0的低地时，立刻受到200+病害值×14的法术环境伤害")


def _sec(report: dict, name: str) -> dict:
    """按**末段**取节——节名带 `常用的基础机制/` 前缀，直接 `.get("阵营")` 取不到，
    会退化成 `0 <= 0` 的恒真空转（这正是"空转守卫"的经典形态）。"""
    for k, v in report["sections"].items():
        if k.split("/")[-1] == name:
            return v
    return {}


# ---------------------------------------------------------------- 1 解析

def check_parsing() -> None:
    print("\n[1] wikitext 解析：嵌套、配平与分节")

    args = M.split_args("田地|说明里有{{术语|ba.x|晕眩}}|备注")
    check("split_args 按嵌套深度切分，内层 `|` 不算分隔符",
          len(args) == 3 and args[1] == "说明里有{{术语|ba.x|晕眩}}",
          f"得到 {len(args)} 段")

    args2 = M.split_args("a|b{{x|y|z}}c|d")
    check("split_args 对多层嵌套同样成立",
          len(args2) == 3 and args2[1] == "b{{x|y|z}}c", str(args2))

    # 非贪婪正则会在嵌套模板的 }} 处提前截断，把后半句丢掉——
    # 这是**静默**错误：截出来的前半句看着完全正常。
    body = dict((n, b) for _p, n, b in
                ((p, M.split_args(i)[0], M.split_args(i)[1])
                 for p, i in M._iter_templates(GLOSSARY_PAGE, "特殊机制表格")))
    check("配平：嵌套同层模板不会被提前截断（后半句仍在）",
          "伤害降低75%" in body.get("洋红蒸汽", ""),
          "洋红蒸汽的正文应保留到句末")

    ms = M.parse_glossary(GLOSSARY_PAGE)
    check("parse_glossary 收齐 4 条", len(ms) == 4, f"实得 {len(ms)}")

    by = {m.name: m for m in ms}
    check("分节：`|` 之后小节切换被正确回溯（战场效果 ≠ 伤害机制）",
          by["田地"].section == "战场效果" and by["生命流失"].section == "伤害机制",
          f"{by['田地'].section} / {by['生命流失'].section}")

    check("备注栏独立取出，不混进正文",
          by["田地"].note.startswith("※“地形标记”")
          and "地形标记" in by["田地"].text,
          by["田地"].note[:20])

    check("图标栏不进正文",
          by["田地"].icons and "文件" not in by["田地"].text,
          f"{len(by['田地'].icons)} 个图标")

    check("{{=}} 这类转义模板被展开（不残留花括号）",
          "{{" not in by["病害值"].text and "}}" not in by["病害值"].text,
          by["病害值"].text[:24])


# ---------------------------------------------------------------- 2 术语表

def check_glossary() -> None:
    print("\n[2] 术语表：条数、分节、活页面")

    ms = M.parse_glossary(GLOSSARY_PAGE)
    check("离线样本的节名都落在 SECTIONS 里",
          all(any(m.section.endswith(s) for s in M.SECTIONS)
              for m in ms if m.section),
          "、".join(sorted({m.section for m in ms})))

    try:
        live = M.fetch_glossary()
    except Exception as exc:                                   # noqa: BLE001
        print(f"  [skip] 活页面取不到（跳过联网节）：{type(exc).__name__}: {exc}")
        return

    check("「特殊机制」页解析出 87 条", len(live) == 87, f"实得 {len(live)}")

    secs = {}
    for m in live:
        secs[m.section] = secs.get(m.section, 0) + 1
    check("九节齐全（节名按页面顺序）",
          all(any(s in k for k in secs) for s in M.SECTIONS),
          "、".join(f"{k}:{v}" for k, v in secs.items()))

    names = {m.name for m in live}
    for must in ("田地", "病害值", "洋红蒸汽", "兔子洞", "稳固锁链", "盲区"):
        check(f"点名机制在表内：{must}", must in names)

    check("每条都有正文（不存在只有名字的条目）",
          all(m.body.strip() for m in live),
          f"最短 {min(len(m.body) for m in live)} 字符")


# ---------------------------------------------------------------- 3 锚点

def check_anchors() -> None:
    print("\n[3] 锚点：真实正文 → 期望的规则与 kind")

    # 逐字取自 HS-8「特殊地形效果」与 HS-EX-8 的关卡页。
    for tag, text in (("HS-8", HS8_TEXT), ("HS-EX-8", HEX8_TEXT)):
        terms = M.parse_mechanic(text)
        kinds = [t.kind for t in terms]
        check(f"{tag}：编译出公式项", bool(terms), f"{len(terms)} 项 {kinds}")
        check(f"{tag}：认出了环境伤害（dtype=法术）",
              any(t.kind == "damage" and t.dtype == "ARTS" for t in terms),
              str([(t.kind, t.dtype, t.source) for t in terms]))
        check(f"{tag}：认出了清水田地的回复（HEAL）",
              any(t.kind == "heal" and t.dtype == "HEAL" for t in terms),
              str([(t.kind, t.dtype) for t in terms]))

    t = [x for x in M.parse_mechanic(HS8_TEXT) if x.kind == "heal"]
    check("回复项的基数是 50（写在正文里的那个数）",
          bool(t) and t[0].expr == "50", t[0].expr if t else "(无)")

    env = [x for x in M.parse_mechanic(HS8_TEXT) if x.source.startswith("mech_env_damage")]
    check("环境伤害由机制规则认领（不是被通用伤害规则咬走）",
          bool(env), str([x.source for x in env]))

    # ⚠ 词序：**关卡页与术语表不一致**，两条规则各服务一边。
    #   关卡页「法术环境伤害」/ 术语表「环境法术伤害」。
    alt = [x for x in M.parse_mechanic("受到 基础伤害+实际病害值×一定比例 的环境法术伤害。")
           if x.source == "mech_env_damage_alt"]
    check("术语表词序（环境法术伤害）另有一条规则接住",
          bool(alt), str([(x.source, x.dtype) for x in
                          M.parse_mechanic("受到环境法术伤害")]))


# ---------------------------------------------------------------- 4 关卡页字段

def check_stage_fields() -> None:
    print("\n[4] 关卡页字段（离线字面量）")

    page = (
        "{{关卡信息\n"
        "|关卡代号=HS-8\n"
        "|初始COST=10\n"
        "|关卡描述=一位农人挥动农具。<br/>{{color|#FFFFFF|<田地>}}根据病害程度"
        "使部署其上的干员恢复生命/受到伤害\n"
        "|情报=场地左上角田地区域的初始病害值+100\n"
        "|特殊地形效果='''活性源石'''<hr>'''田地'''<br/>每秒恢复50生命值\n"
        "|无关字段=不该被取到\n"
        "}}\n"
    )
    f = M.parse_stage_fields(page)
    check("取到三个机制字段", set(f) == {"关卡描述", "情报", "特殊地形效果"},
          "、".join(f))
    check("与机制无关的字段不进结果", "无关字段" not in f)
    check("字段值里的嵌套模板被展开成纯文本",
          "田地" in M.detemplate(f["关卡描述"])
          and "color" not in M.detemplate(f["关卡描述"]))

    sm = M.parse_stage_mechanics("HS-8 种因", page)
    check("parse_stage_mechanics 带上标题", sm.title == "HS-8 种因")
    check("plain() 串起全部字段文本", "初始病害值+100" in sm.plain())

    ref_page = "{{关卡信息|关卡描述=见{{特殊机制|病害值}}与{{特殊机制|田地}}}}\n"
    sm2 = M.parse_stage_mechanics("X", ref_page)
    check("引用到的机制名被抽出、且去重",
          sm2.refs == ("病害值", "田地"), str(sm2.refs))


# ---------------------------------------------------------------- 5 精度守卫

def check_precision() -> None:
    print("\n[5] 精度守卫（每条都对应一次真实的静默错误）")

    # 守卫①：`_iter_templates` 若改用非贪婪正则，嵌套模板会在内层 `}}` 处截断。
    # 症状是"后半句消失而前半句看着正常"，不会报错。
    inner = list(M._iter_templates(GLOSSARY_PAGE, "特殊机制表格"))
    nested = [i for _p, i in inner if "洋红蒸汽" in i]
    check("守卫①：嵌套模板不截断（后半句在）",
          nested and "降低75%" in nested[0])

    # 守卫②：split_args 若裸切 `|`，说明栏会被切碎、备注栏整体错位。
    naive = len(NESTED_RAW.split("|"))
    real = len(M.split_args(NESTED_RAW))
    check("守卫②：裸切 `|` 会多出字段，嵌套切分不会",
          naive > real, f"裸切 {naive} 段 vs 嵌套切分 {real} 段")

    # 守卫③：环境伤害是「基础值 + 系数×变量」的加法。若被当常数提取，
    # 会得到 `20+病害值×3` 里的 20 当系数这类"看着对、其实错"的结果。
    terms = M.parse_mechanic("位于病害值>0低地的我方单位，每秒受到20+病害值×3法术环境伤害。")
    env = [t for t in terms if t.kind == "damage" and t.dtype == "ARTS"]
    check("守卫③：环境伤害不被当成常数系数（amount 留白）",
          bool(env) and all(t.amount is None for t in env),
          str([(t.source, t.expr, t.amount) for t in env]))

    # 守卫④：机制规则必须排在干员/敌人规则**之前**——「环境伤害」锚点独特，
    # 排在后面会被通用伤害规则先咬走（顺序即优先级）。
    order = [type(r).__name__ for r in M.RULES_MECHANIC[:len(M.MECHANIC_RULES)]]
    check("守卫④：机制规则排在规则表最前",
          tuple(M.RULES_MECHANIC[:len(M.MECHANIC_RULES)]) == tuple(M.MECHANIC_RULES),
          f"前 {len(order)} 条是机制规则")

    # 守卫⑤：分节回溯。`==` 是 h2 不是 h1，层级偏移会算出 `A/B/C` 这种错路径。
    ms = M.parse_glossary(GLOSSARY_PAGE)
    by = {m.name: m for m in ms}
    check("守卫⑤：小节层级回溯正确（不残留上层路径）",
          "/" not in by["生命流失"].section, by["生命流失"].section)


# ---------------------------------------------------------------- 6 覆盖率

def check_non_effect() -> None:
    print("\n[7] 不该编译的条目与已知误读")

    try:
        live = M.fetch_glossary()
    except Exception as exc:                                   # noqa: BLE001
        print(f"  [skip] 活页面取不到，跳过：{type(exc).__name__}")
        return

    names = {m.name for m in live}

    # 名单里的名字必须真的在表内——写错一个字，下面那条断言会因为
    # "根本没这条"而**静默通过**，整节变成空转。
    missing = sorted(M.NON_EFFECT_NAMES - names)
    check("NON_EFFECT 名单里的名字全都在表内（防写错字导致空转）",
          not missing, f"表里找不到：{missing}")

    compiled = [m.name for m in live
                if m.name in M.NON_EFFECT_NAMES and M.parse_mechanic(m.text)]
    check("名单里的条目确实都编不出公式项（定义 ≠ 效果）",
          not compiled, f"编出来了：{compiled}")

    # 已知误读：断言它们**仍在**被误读。修好了这条会红，红了就移进 NON_EFFECT。
    still = {m.name: [t.source for t in M.parse_mechanic(m.text)]
             for m in live if m.name in M.KNOWN_MISPARSE}
    check("已知误读条目仍在表内",
          set(still) == set(M.KNOWN_MISPARSE), str(sorted(set(M.KNOWN_MISPARSE) - set(still))))
    check("已知误读**仍在**被误读（修好后请把它们移进 NON_EFFECT_NAMES）",
          all(v for v in still.values()),
          "、".join(f"{k}←{'/'.join(v)}" for k, v in still.items()))


# ---------------------------------------------------------------- 8 覆盖率

def check_coverage() -> None:
    print("\n[6] 覆盖率下限（判据，不是水位）")

    try:
        live = M.fetch_glossary()
    except Exception as exc:                                   # noqa: BLE001
        print(f"  [skip] 活页面取不到，跳过覆盖率：{type(exc).__name__}")
        return

    r = M.scan_glossary(live)
    # 下限是**判据**：低于它说明规则表被改坏了，不是"水位漂了"。
    check("术语表覆盖率 ≥ 50%", r["rate"] >= 0.50,
          f"{r['hit']}/{r['total']} = {r['rate'] * 100:.1f}%")

    war = _sec(r, "战场效果")
    check("「战场效果」一节覆盖率 ≥ 70%（地图机制的主战场）",
          bool(war) and war["hit"] / war["total"] >= 0.70,
          f"{war.get('hit')}/{war.get('total')}")

    dmg = _sec(r, "伤害机制")
    check("「伤害机制」一节覆盖率 ≥ 70%",
          bool(dmg) and dmg["hit"] / dmg["total"] >= 0.70,
          f"{dmg.get('hit')}/{dmg.get('total')}")

    # 「阵营」「职业」「特殊计算方式」三节**故意**接近 0 —— 它们是定义。
    # 这里写成上限守卫：哪天它们被"顺手"补上，说明有人把定义当效果收了。
    # ⚠ 必须先断言节**取到了**——取不到时 `0 <= 0` 恒真，守卫会空转。
    for sec in ("阵营", "职业", "特殊计算方式"):
        v = _sec(r, sec)
        check(f"「{sec}」一节取得到（否则下面那条是空转）", bool(v),
              f"{v.get('hit')}/{v.get('total')}")
        check(f"「{sec}」一节覆盖率 ≤ 34%（定义性散文，不该被收）",
              bool(v) and v["hit"] <= v["total"] * 0.34,
              f"{v.get('hit')}/{v.get('total')}")

    # 死规则守卫：一条永不命中的规则看着毫无问题，只有点名才找得出来。
    # ⚠ 语料必须是**术语表 + 关卡页锚点**：`mech_env_damage` 锚的是关卡页词序
    #   （「法术环境伤害」），只扫术语表会把它误判成死规则——反过来，
    #   只扫锚点会漏掉术语表那边的。两边都要喂。
    corpus = [m.text for m in live] + [HS8_TEXT, HEX8_TEXT]
    hits: dict[str, int] = {}
    for text in corpus:
        for t in M.parse_mechanic(text):
            hits[t.source] = hits.get(t.source, 0) + 1
    dead = sorted({r_.name for r_ in M.MECHANIC_RULES} - set(hits))
    check("机制规则没有一条是死的（术语表 + 关卡页锚点都喂）",
          not dead, f"死规则：{dead}")

    # 统计函数必须与真编译器**逐行同口径**。本项目踩过：敌人侧的统计函数
    # 漏挂 expr 通道，报 68.4% 而真编译为 69.3%，CLI 照它打印等于把成绩报低。
    mismatch = [
        m.name for m in live
        if bool(M.parse_mechanic(m.text)) != bool(
            M._formula.parse(M.detemplate(m.body), None,
                             rules=M.RULES_MECHANIC, extra=M.expr_terms))
    ]
    check("统计口径与真编译器逐行同口径（无一行不一致）",
          not mismatch, f"不一致 {len(mismatch)} 条 {mismatch[:3]}")


def main() -> int:
    print("=" * 68)
    print("地图机制自检（ak_tactic/mechanics.py）")
    print("=" * 68)
    check_parsing()
    check_glossary()
    check_anchors()
    check_stage_fields()
    check_precision()
    check_non_effect()
    check_coverage()
    total = _PASSED + len(_FAILED)
    print("\n" + "=" * 68)
    print(f"通过 {_PASSED} 项，失败 {len(_FAILED)} 项：")
    for name in _FAILED:
        print(f"  - {name}")
    print("=" * 68)
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
