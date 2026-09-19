#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 `docs/uncertainties.md` —— 给博士**逐项回填**的待裁定清单。

跑法：`python tools/uncertainty_audit.py`

## 为什么要生成而不是手写

清单里的数据（哪些算式认不出属性、各占多少、原文长什么样）会随语料与规则变，
手写必然过期。但**裁定是人写的**，重新生成时绝不能冲掉——所以每张表都留一栏
`裁定`，生成前先把上一版已填的读回来续用（与 `tools/unit_audit.py` 同一套做法）。

## 填完之后怎么落地

裁定不会自动生效。填好后我来读 `docs/uncertainties.md`，把裁定接进：
- **属性词表** → `ak_tactic/enemy_formula.py` 的 `_EXPR_ATTR`
- **误读复查** → 对应的规则或守卫（可能同时改 `ak_tactic/formula.py`）
- **项目级** → 一处一处改代码，改完跑全套自检

## 行是怎么排序的

按频次降序——**频次高的先裁**，收益最大。低频长尾一律列在后面，
可以整段跳过，也可以一条条来。
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ak_tactic import formula                                      # noqa: E402
from ak_tactic.db import DEFAULT_ENEMY_DB_PATH                     # noqa: E402
from ak_tactic.enemy_formula import (RULES_ENEMY, detemplate,      # noqa: E402
                                     expr_terms, load_enemy_corpus)

OUT = ROOT / "docs" / "uncertainties.md"

_RULING = "裁定"


# ------------------------------------------------------------ 裁定栏的续用

#: 从这一节起，正文**不生成**，是手写补上去的；重生成时必须原样搬过来。
#:
#: 2026-09-18 踩过这个坑：第七节（怀黍离敌人侧机制的存疑读法）是生成之后手写
#: 上去的，而生成器只会回读「裁定」栏、并不知道正文还有别的节——一次重生成
#: 就把 4 条裁定行与两条只登记项**整节冲掉了**，只在第六节的索引里留下一条
#: 半截记录。生成物里手写补节这件事本身没错，错在生成器不认它。
_PRESERVE_FROM = "## 七、"


def split_preserved(path: pathlib.Path) -> str:
    """取出上一版里「手写补上去」的那几节，原样返回（含末尾换行）。

    找不到就返回空串——第一次生成时本来就没有。
    """
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    i = text.find(_PRESERVE_FROM)
    return "" if i < 0 else text[i:]


def load_rulings(path: pathlib.Path) -> dict[tuple[str, str], str]:
    """把上一版已填的 `裁定` 读回来，按 (节名, 首列) 索引。

    只认**带 `裁定` 列**的表：旧版或别处的表最后一栏是建议，不能被当答案读进来。
    人若在 markdown 里直接敲了裸 `|`，表格会多切出几栏，把尾部并回最后一栏
    ——不并回去，裁定值会被悄悄截断成半截，比报错更难发现。

    **手写补上去的那几节（见 `_PRESERVE_FROM`）不参与回读**：它们的表也有
    「裁定」列，读进来会把行号之类的首列当成"键"塞进第六节的索引，
    而那些行本来就由 `split_preserved` 原样搬过去，不需要也不该被索引一次。
    """
    if not path.exists():
        return {}
    out: dict[tuple[str, str], str] = {}
    section, has_col, ncol, pending_header = "", False, 0, False
    raw = path.read_text(encoding="utf-8")
    i = raw.find(_PRESERVE_FROM)
    if i >= 0:
        raw = raw[:i]
    for line in raw.splitlines():
        if line.startswith("## "):
            section, has_col, ncol, pending_header = (
                line[3:].strip(), False, 0, False)
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        if not cells:
            continue
        if set("".join(cells)) <= set("-: "):
            continue                      # 分隔行
        if pending_header:
            # 第六节的行：节 / 键 / 您填的裁定 / 状态
            if len(cells) >= 4 and cells[0] not in ("节", "—"):
                key, val = _unkey(cells[1]), cells[-2].replace("\\|", "|")
                if key and val:
                    out[(cells[0].strip(), key)] = val
            continue
        # 第六节「填了但还没落地的裁定」的**表头**。判据必须是"首两列正好是
        # 节/键"这种**结构**判据：一开始写的是「某栏里含"裁定"二字」，结果
        # 第一节的数据行里就有「**请博士裁定**：…」「原裁定「维持不变」…」，
        # 于是数据行被当成表头、**此后整表列错位**——读回来的键变成了"分歧在哪"
        # 那一栏的正文，第五列的值也串位。这种错不报错，只是把裁定接到别的键上。
        if len(cells) >= 2 and cells[0] == "节" and cells[1] == "键":
            pending_header, has_col, ncol = True, False, len(cells)
            continue
        if _RULING in cells or any(c.startswith(_RULING) for c in cells):
            has_col, ncol = True, len(cells)
            continue
        if not has_col:
            continue
        if len(cells) > ncol:
            cells = cells[:ncol - 1] + ["|".join(cells[ncol - 1:])]
        key, val = _unkey(cells[0]), cells[-1].replace("\\|", "|")
        if key and val:
            out[(section, key)] = val
    return out


def _unkey(cell: str) -> str:
    """把「键」栏的单元格还原成生成时用的键。

    **只削成对的外层反引号，键内部的反引号原样保留。** 这里曾经写的是
    `cell.strip("`")`，它把**开头**的反引号一律削掉——于是
    `` `tile_forbidden` 与 `tile_empty` … `` 读回来变成
    `` tile_forbidden` 与 `tile_empty` … ``，和生成时的键**不再相等**。
    后果是静默的、而且很像"博士没填"：`_answered` 判 False → 那一行照旧
    列在表里；`LANDED` 里登记的同一个键也匹配不上。凡是键里带反引号的
    （第二节整张词表都是）都中这一枪。2026-09-19 博士反馈"我记得我都填过"，
    查到的第二个成因就是它。
    """
    s = (cell or "").strip()
    # 渲染时键栏**总会**再包一层反引号，所以这里只削最外那一对；键内部原有的
    # 反引号必须原样留下（`` `tile_forbidden` 与 `tile_empty` … `` 在文档里
    # 是四个反引号，削一对才回到原键）。判据必须是"首尾都是反引号"——只削开头
    # 正是老实现（`strip("`")`）的错处。
    if len(s) >= 2 and s.startswith("`") and s.endswith("`"):
        return s[1:-1]
    return s


def _cell(text: str, keep_tick: bool = False) -> str:
    """markdown 单元格转义：`|` 切断表格，换行切断行。

    **不要动反引号**——正文里的 `battle/damage.py` 这类代码路径就靠它可读；
    键栏的反引号由 `_unkey` 还原（只削成对的外层），与这里无关。
    """
    return re.sub(r"\s+", " ", (text or "").replace("|", "\\|")).strip()


def _key_roundtrip_bad() -> list[str]:
    """键栏往返自检：写进表格、再读回来，键必须**一字不差**。

    2026-09-19 加的守卫。当时 `_unkey` 的前身是 `strip("`")`，键里带反引号的
    会被削变形（见 `_unkey` 的说明），后果是"博士填了也不生效"且完全静默。
    守卫拿本工具真会写进「键」栏的两批键来走 `_cell` → `_unkey` 往返：
    `LANDED` 的键（其中就有含两个反引号的）与第一节的模板键。
    """
    keys = list(dict.fromkeys(list(LANDED) + [q[0] for q in _Q]))
    return [k for k in keys if _unkey("`" + _cell(k) + "`") != k or _unkey(k) != k]


def _rb(rules: dict, section: str, key: str) -> str:
    return _cell(rules.get((section, key), ""))


def _answered(rules: dict, section: str, key: str) -> bool:
    """这一条**已经裁过了**吗？裁过的行不再出现在问答表里。

    2026-09-18 博士：「检查 uncertainties.md，把已确认的条目删掉」。
    「已确认」= `裁定` 栏有内容——它们不再是一道**待**裁定的题。落地过的
    （在 `LANDED` 表里）就此从这份文件消失；填了但还没落地的仍由第六节
    「填了但还没落地的裁定」原样兜着，**不会丢**。

    ⚠️ 为什么在生成器里判、而不是手工去 md 里删行：这份文件是**生成物**，
    `load_rulings` 会把 `裁定` 栏读回来续用——手工删掉的行下次生成会**带着
    裁定原样回来**（删了等于没删，而且看上去像删过了）。要让它不再出现，
    只能在生成这一侧判。

    ⚠️ 判据必须**两条都算**：只看 `rules`（文件里的裁定栏）会自反弹——行一删，
    裁定栏也跟着没了，下一次生成 `_answered` 判 False，那一行**又长回来**
    （真踩过：第一次生成删掉 11 行，第二次原样回来）。所以还要认 `LANDED`
    这份**代码侧**的台账：它独立于文件，删不掉。
    """
    return key in LANDED or bool(rules.get((section, key)))


def _keep(rules: dict, section: str, rows, key_of=lambda r: r[0]):
    """过滤掉已裁的行；顺手把"这一节还剩几条"的计数给出去。"""
    return [r for r in rows if not _answered(rules, section, key_of(r))]


# ------------------------------------------------------------ 语料抽取

#: 「左词」里出现这些就是散文碎片，不是属性名。判据同 `formula._VERB` 的思路：
#: 属性名是名词短语，含动词或含数量词的都是从正文里切歪的。
_PROSE = re.compile(
    r"^(·|※|\d)"                      # 前导项目符号 / 数字
    r"|^[sS]后|^秒生效|^清空|^切换|^随后|^则|^否则|^使其$|^然后|^并在|^每次|^每次普通"
    r"|^短暂使|^携带此技能|^攻击范围内所有|^阻挡的敌人|^与活性源石风暴"
    r"|x$|[xX]-|范围x|视野x|半径x"
)
#: 与位移/角度/记法有关的，一律不是属性增减。
_MISREAD = re.compile(r"发射|角度|°|^[sS]$|^x$|^Lv$|百分比|^则|^否则")

#: 已知该认成什么的词。**这是建议不是结论**——最终由博士裁定。
_SUGGEST: dict[str, str] = {
    # —— 伤害减免（A1：规则漏了「-N%」写法，见第三节）——
    "法术伤害": "认成 减伤（buff/减伤）",
    "物理和法术伤害": "认成 减伤",
    "物理与法术伤害": "认成 减伤",
    "来源于正面的物理和法术伤害": "认成 减伤",
    "来源于正面的物理/法术伤害": "认成 减伤",
    "来自正面的物理/法术伤害": "认成 减伤",
    "来自背面的物理/法术伤害": "认成 减伤",
    "伤害来源位于自身左侧的物理/法术伤害": "认成 减伤",
    "伤害来源位于自身右侧的物理/法术伤害": "认成 减伤",
    "非来源于自身的物理/法术伤害": "认成 减伤",
    "无来源或来源非矿工游击队的物理/法术伤害": "认成 减伤",
    "伤害": "认成 减伤",
    # —— 真属性，加进 `_EXPR_ATTR` 即可 ——
    "技能优先级": "认成 buff/技能优先级",
    "优先级": "认成 buff/技能优先级",
    "嘲讽等级": "认成 buff/嘲讽等级",
    "阻挡数": "认成 buff/阻挡数",
    "短暂使我方干员阻挡": "认成 debuff/阻挡数（作用于我方，op=enemy）",
    "攻击间隔": "认成 buff/攻击间隔",
    "攻击速度": "认成 buff/攻击速度",
    "攻击距离": "认成 buff/攻击距离",
    "攻击半径": "认成 buff/攻击半径",
    "攻击范围半径": "认成 buff/攻击半径",
    "目标影响半径": "认成 buff/攻击半径",
    "速度倍率": "认成 buff/速度倍率",
    "可抵抗状态生效时间倍率": "认成 buff/状态生效时间倍率",
    "退场时本次再部署时间": "认成 buff/再部署时间",
    "部署费用": "认成 buff/部署费用",
    "我方费用上限": "认成 buff/费用上限",
    "SP再": "认成 buff/SP（敌我双方都吃技力）",
    "当前移动速度": "留空（它是**系数**，不是被改的属性——见第一节算式口径）",
    "摩擦力": "留空（物理引擎参数，非战斗属性）",
    "累计伤害阈值": "留空（阈值，不是被改的属性）",
    # —— 生息演算 / 足球：按既定口径不收 ——
    "范围内的田地地块病害值": "排除（生息演算，按既定口径不收）",
    "场上球员类敌人总数": "排除（足球模式，按既定口径不收）",
    "待处理目标计数": "留空（计数，非属性）",
    # —— 位移/角度/记法：收进来是噪声 ——
    "发射": "排除（发射角度，不是属性增减）",
    "然后发射": "排除（同上）",
    "范围x": "排除（范围记法）",
    "对大范围x": "排除（同上）",
    "对更大范围x": "排除（同上）",
    "对十字范围x": "排除（同上）",
    "强制撤退范围x": "排除（同上）",
    "光弹对范围x": "排除（同上）",
    "自身所在地块周围的视野x": "排除（视野记法）",
    "对目标所在地块及周围四格x": "排除（同上）",
    "对目标所在地块及周围八格x": "排除（同上）",
    "对目标周围四格x": "排除（同上）",
    "并在影响范围x": "排除（散文碎片）",
    "每次普通攻击以攻击主目标位置": "排除（散文碎片）",
    "清空范围内L": "排除（散文碎片）",
    "与活性源石风暴之间距离不超过": "排除（散文碎片）",
    # —— 公式系数：不是一个属性，留空本就对 ——
    "Lv": "留空（等级系数，不是一个属性）",
    "百分比": "留空（占位符）",
    "s": "留空（秒数记法）",
    "场上结晶数量": "留空（分子，非属性）",
    "场上球员类敌人总数": "排除（足球模式，按既定口径不收）",
    "待处理目标计数": "留空（计数，非属性）",
    "随后自身拾取数": "排除（散文碎片）",
    "随后自身储存数": "排除（散文碎片）",
    "自身退场并令拾取计数": "排除（散文碎片）",
    "则计数": "排除（散文碎片）",
    "否则": "排除（散文碎片）",
    "切换目标": "排除（散文碎片）",
    "让其": "排除（散文碎片）",
    "使其": "排除（散文碎片）",
    "短暂使我方干员阻挡": "排除（散文碎片）",
    "每次普通攻击使自身攻击间隔": "排除（散文碎片）",
}


# ------------------------------------------------------------ 抽取

def collect() -> tuple[collections.Counter, collections.Counter, dict, dict]:
    """返回 (左词频次, 左词种类数, 例句, 该词下最常见的算式)。"""
    corpus = load_enemy_corpus(DEFAULT_ENEMY_DB_PATH)
    freq: collections.Counter = collections.Counter()
    forms: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    sample: dict[str, str] = {}
    for c in corpus:
        flat = detemplate(c["text"])
        for t in formula.parse(flat, c["blackboard"], rules=RULES_ENEMY,
                               extra=expr_terms):
            if t.source != "expr_var" or t.attr:
                continue
            body = t.formula.lstrip("(（")
            m = re.match(r"^([^\d\s（()）+\-×/]+)", body)
            word = (m.group(1) if m else body)[:18] or body[:18]
            freq[word] += 1
            forms[word][t.formula[:40]] += 1
            sample.setdefault(word, flat[:120])
    return freq, forms, sample


def suggest(word: str) -> str:
    """给一个左词的建议。**是建议不是结论**——最终由博士裁定后写回。

    先剥掉前导的项目符号再查表：`※技能优先级` 是**真属性**，不剥的话会被
    下面的散文启发式当成碎片排除，把一条该收的判成不该收。
    """
    w = word.lstrip("※·＊*☆")
    if w in _SUGGEST:
        return _SUGGEST[w]
    if word in _SUGGEST:
        return _SUGGEST[word]
    if _MISREAD.search(w) or _PROSE.search(word) or len(w) > 10:
        return "排除（疑似散文碎片/记法，待博士确认）"
    return "**待定**"


# ------------------------------------------------------------ 各节

_Q: list[tuple[str, str, str, str]] = [
    ("元素损伤的比例式乘的是「伤害」还是「攻击力」",
     "技能正文有两种写法：「攻击附带造成法术伤害{attack@ep_damage_ratio:0%}的」与"
     "「攻击力{ep_damage_ratio:0%}的…损伤」。前者字面是**伤害**、后者字面是**攻击力**，"
     "而技能带倍率时两者不是同一个数（本仓既有裁定：技能倍率只在 "
     "`damage.resolve_damage(scale=)` 乘一次，见 target=key 的伤害口径条）。"
     "**取证结论（2026-09-19，全树检索）**：原版根本没有元素损伤的**结算层**——"
     "`ak_tactic/battle/` 里 `ep_damage` 与「损伤」零命中；元素损伤只存在于两处："
     "① 公式**编译**层（`ak_tactic/formula.py` / `enemy_formula.py` / `operator/skill.py`，"
     "只编译成公式项、不求值）；② Go 内核 `rios-sim/element.go`，"
     "**调用点只有 `element_test.go`、零生产调用点**。"
     "唯一沾边的 `p3r.py::TotalAttack.ELEMENT` 是**敌方元素相性**那条轴，公式层自己写明两条轴别混。",
     "`ak_tactic/formula.py:464-474` 现把三种写法**都**记成 "
     "`source=ATK` + `form=atk_scale`（即**口径合并**）。因为没有原版结算可对照，"
     "「与原版逐位一致」这条判据**对本案不适用**；口径合并是否成立**无法由取证原版回答**。"
     "对拍影响：若真有两种口径，带倍率技能的元素损伤量会静默给错（差值＝倍率因子）。",
     "**待裁——本项不预设处理方式**。可裁的选项："
     "① 维持合并（三种写法同义）；② 拆成两条规则并配一条守卫（让合并写法变红）；"
     "③ 先去权威页／实机取证「伤害X%」那一种写法的实际结算再定。"),

    ("法术伤害有没有 5% 保底",
     "wiki.gg 的 Damage 页原文说「不论伤害类型，最终伤害至少为攻击力的 5%」；"
     "xulai1001/akdata 也实现了；但 wxhwwla/calc-framework 只对物理保底",
     "本项目 `battle/damage.py` 现在**无保底**（法术 = ATK×scale×(1−RES/100)）。"
     "影响 SR-EX-8 的吓人路灯（RES 99）：有保底是 5%，无保底是 1%",
     "维持无保底（跟随 calc-framework）／改为有保底（跟随 wiki 与 akdata）"),
    ("攻速下限取多少",
     "wiki 写 20，akdata 写 10",
     "现无夹取。攻速只影响攻击间隔换算，下限越低越容易打出高频",
     "取 10 或 20，或明确「不夹取」"),
    ("攻击力取整方式",
     "面板取整与伤害结算取整是两回事，原先混在一行问。wiki 明确的是**伤害**里的 FLOOR",
     "**2026-09-17 分两处定案**：面板 = 四舍五入（`operator/stats.py` 默认已由 floor "
     "改为 round）；伤害结算 = floor（`battle/damage.py`，不动）。判据见 `check_db` "
     "的 [4b] 节（红豆 1185/510、怒潮凛冬 2981/1307/473 命中 round；攻击 1307 一栏 "
     "floor 给 1306，直接排除），旁证是 prts.wiki 干员页计算器亦用 `Math.round`",
     "面板 round、伤害 floor，两者各自成立"),
    ("`tile_forbidden` 与 `tile_empty` 哪个对应哪种不可部署地块",
     "两者 `(heightType, buildableType, passableMask)` 完全一致，都是 NONE/FLY_ONLY，"
     "**字段分不出来**",
     "现按「不可部署地块」统一处理，不区分。若要区分只能靠名字猜",
     "维持不区分"),
    ("算式认领：属性表扩到哪一层",
     "第二节列了全部 169 个候选词。扩得越宽，认错的机会越多",
     "当前 `_EXPR_ATTR` 只有 11 项",
     "**只收战斗结算真正用到的**（阻挡/移速/攻防/攻速/重量/再部署），其余留空"),
    ("干员侧要不要也接算式 pass",
     "实测干员侧 10392 条技能描述里，纯常数片段 561 处、**真变量只有 8 处**，"
     "且 8 处**全部**是 `速度+0.25/秒` 的 `/秒` 被当除号",
     "目前只有敌人侧接了",
     "**不接**——零收益，只多出 7 种误读。此口径须写进文档，"
     "免得日后有人「顺手对称一下」"),
    ("`防御力/法术抗性最终×0` 怎么读",
     "斜杠是**并列**（「防御力和法术抗性都归零」），不是除法。两侧不是伤害类型词，"
     "现有判据拦不住",
     "共 4 处。现产出 `算式 法术抗性最终×0 ⟨变量：法术抗性最终⟩`："
     "字符串忠实、语义读错",
     "补判据（如「最终」+乘 0 视为并列）／接受现状"),
    ("规则抢先导致算式不出一项，是否可接受",
     "规则已咬走的区间，算式不再重复出项（这是「不可能重复计数」的保证）",
     "代价：`攻击力/防御力降低至已处理目标数量/待处理目标总数量×100%` 只留下"
     "「降低（幅度未写明）」，而正文其实写了幅度。1 类",
     "接受（保证不重复计数）／改成「算式优先于规则」"),
    ("阿米娅技2「影霄·绝影」的『接下来的伤害类型变为真实』管到哪一段",
     "描述是「进行 10 次攻击力 220% 的法术斩击（**最后一击**系数加倍且为真实"
     "伤害）；……**并且接下来的伤害类型变为真实**」。10 次里只有末击明写"
     "「为真实伤害」，那『接下来』究竟指技能剩余时间她自己的**普通攻击**，"
     "还是**斩击序列的后几段**",
     "现按 `_wants_true_damage`（描述含「伤害类型变为真实」）判为**整条技能**"
     "的真实——对这条技能**偏强**：会把 10 次斩击全按真实算，"
     "而原文只保证末击与『接下来』的那些。真数值差可达数倍",
     "**请博士裁定**：① 只末击为真实；② 末击起往后全为真实（含技能期普攻）；"
     "③ 整条技能全为真实（维持现状）"),
    ("阿米娅(术战者)天赋「青色怒火」的『技能开启期间效果加倍』是谁开技能",
     "描述：「在场时所有友方单位的攻击力和防御力+7%，**技能开启期间效果加倍**」。"
     "加倍的主语没写明",
     "现**未建模**（该天赋整条还没接）——它在场时是全场光环，"
     "承接它要新开一条光环路径（现有 `RegenAura` 只做治疗）",
     "**请博士裁定**：① **阿米娅自己**开技能时翻倍（+14%）；"
     "② **受益的友方单位**各自开技能时翻倍。两者结果不同且都要写进实现"),
    ("天赋「情绪吸收」在技能开启期间是否照常回 SP",
     "正文只写「攻击敌人时额外回复 3 点技力，消灭敌人后额外获得 10 点技力」，"
     "**没有**『非技能期间』的限定",
     "现按游戏常规实现：**技能开启期间不回**（与既有 `sp_per_attack` 口径一致）。"
     "但这一条是**未证实假设**，天赋正文没写。若实际照常回，"
     "阿米娅的技力循环会明显更快（技能衔接变紧）",
     "**请博士裁定**：① 技能期间不回（维持现状）；② 技能期间照常回"),
    ("概率类效果（闪避/暴击）怎么进确定性模拟",
     "阿米娅技1「获得 60% 的法术闪避」、赤刃明霄陈天赋2「闪避下一次攻击」"
     "都是**概率**效果，而本项目模拟器是**确定性**的（无随机数）",
     "现**未建模**，闪避率与触发次数都无处安放。"
     "同一段文本还出现在「有 X% 概率晕眩敌人」这类控制上",
     "**请博士裁定**建模口径：① **期望值法**（伤害 ×(1−闪避率)，可复现、"
     "但单次交战的波峰波谷被抹平）；② **确定性触发**（每 N 次命中固定闪 1 次）；"
     "③ **不建模**并如实标注。我倾向 ①，但这是口径问题不是技术问题"),
    ("阿米娅技2「影霄·绝影」的击杀叠层：『斩击期间』指多长、结束后留不留",
     "黑板 `amiya2_s_2[kill].atk 0.4` / `[kill].magic_resistance 20` / "
     "`[kill].max_stack_cnt 3`，描述写「**斩击期间**每击败一个敌人获得"
     "攻击力+40%和法术抗性+20（最多叠加 3 次）」",
     "现**未建模**。歧义有二：① 该技能 `duration=35s` 但效果是「**立即**进行"
     "10 次斩击」，「斩击期间」是指那 10 次斩击的一瞬，还是整个 35 秒？"
     "② 叠满的 +120% 攻 / +60 法抗在**技能结束后是否保留**（描述没说）",
     "**请博士裁定**：① 「斩击期间」的范围；② 技能结束后是否清零。"
     "两者都影响伤害量级，我不猜"),
    ("召唤物的「同时部署上限」以哪个数为准",
     "同一个召唤者身上有**三个**不同的数，且互相不等：① 天赋黑板的 `cnt`——"
     "它是描述里的「可以使用 N 个」（可动用总量，**随精英阶段变**：电弧/令 "
     "E0=3→E1=4→E2=5，望 4→5→6）；② 描述文字里的第二个数——电弧/令写"
     "「最多同时部署 3 个」（**恒为 3**，不随精英变），望写「最多拥有 5/6/7 枚」；"
     "③ token 自己的 `maxDeployCount`——电弧是 3、望是 4/5/6，但在**令/深池/梅尔 "
     "身上是 1**（它们明明能同时放 3-5 个，所以这个字段并不总是上限）",
     "**2026-09-18 已按 ② 落地**（`battle/talents.py` 的 `find_summon_allowance`）："
     "优先取「最多同时部署」→ 退而取「最多拥有」→ 文字没写时才回落到 `cnt`，"
     "并在返回值里用 `source` 标明出处。**明确不用** `maxDeployCount`——"
     "取它会把令错压成只能放 1 个。影响：召唤师同时能站几个（电弧/令现在取 3）",
     "维持现读法（文字优先、`source` 留痕）／并请顺带定一下："
     "**望该取 6（「可以使用」）还是 7（「最多拥有」）**——现取 7"),
]


def render(rules: dict, out: pathlib.Path = OUT) -> str:
    freq, forms, sample = collect()
    L: list[str] = []
    add = L.append

    add("# 待裁定清单")
    add("")
    add("> 这份文件由 `python tools/uncertainty_audit.py` 生成。")
    add("> **每一张表的最后一栏 `裁定` 是给人填的**，重新生成时会被读回续用，不会冲掉。")
    add("> 表中其余各栏都是实测数据，请不要改（改了下次生成就没了）。")
    add("")
    add("## 怎么填")
    add("")
    add("1. 在 `裁定` 栏写结论。词表那一节可以直接写 `认成 buff/减伤`、`排除`、`留空`。")
    add("2. 写 `|` 会切断表格——要写字面竖线请写成 `\\|`。")
    add("3. **表格里行序按频次降序**，从高到低裁收益最大；低频长尾可以整段跳过。")
    add("4. 一节里若想批量同意，可以在该节第一行写 `以下全部同意建议`，我会按建议逐条落地。")
    add("5. 填完告诉我，我读回裁定并接进代码，然后跑全套自检。")
    add("6. **裁过的行不会再出现**在下面这些表里（2026-09-18 起）——落地过的直接"
        "消失，填了但还没落地的移到第六节，所以这张清单只会越读越短。")
    add("")

    # ---------------- 一、项目级 ----------------
    # **第一列必须是键**：`load_rulings` 按第一列取值，若把编号放第一列，
    # 读回来的键是 `1` 而渲染时按问题名查，裁定会静默丢失（真踩过）。
    sec = "一、项目级问题（答一句即可）"
    add(f"## {sec}")
    add("")
    add("| 问题（键） | 分歧在哪 | 现状与影响 | 我的建议 | 裁定 |")
    add("|---|---|---|---|---|")
    for q, why, now, sug in _keep(rules, sec, _Q):
        add(f"| {_cell(q)} | {_cell(why)} | {_cell(now)} | {_cell(sug)} "
            f"| {_rb(rules, sec, q)} |")
    add("")

    # ---------------- 二、属性词表 ----------------
    sec = "二、算式认领：属性词表"
    add(f"## {sec}")
    add("")
    hi = [w for w, n in freq.items() if n >= 2]
    lo = [w for w, n in freq.items() if n == 1]
    ntot = sum(freq.values())
    add(f"算式认出来、但**认不出作用在哪个属性**的共 **{ntot} 项**，"
        f"归到 **{len(freq)} 个不同的左词**。当前 `_EXPR_ATTR` 只有 11 项，"
        f"这张表就是它的候选扩展。")
    add("")
    add(f"**高频词（出现 ≥2 次，共 {sum(freq[w] for w in hi)} 项 / {len(hi)} 词）**"
        "——建议优先裁这一张。")
    add("")
    add("| 左词（键） | 频次 | 最常见形态 | 我的建议 | 裁定 |")
    add("|---|---|---|---|---|")
    for w in sorted(hi, key=lambda x: (-freq[x], x)):
        if _answered(rules, sec, w):
            continue
        form = forms[w].most_common(1)[0][0]
        add(f"| `{_cell(w, True)}` | {freq[w]} | {_cell(form)} | {_cell(suggest(w))} "
            f"| {_rb(rules, sec, w)} |")
    add("")
    add(f"**低频长尾（出现 1 次，共 {len(lo)} 词）**——可整段跳过；"
        "想逐条来也留了裁定栏。")
    add("")
    add("| 左词（键） | 频次 | 最常见形态 | 我的建议 | 裁定 |")
    add("|---|---|---|---|---|")
    for w in sorted(lo):
        if _answered(rules, sec, w):
            continue
        form = forms[w].most_common(1)[0][0]
        add(f"| `{_cell(w, True)}` | 1 | {_cell(form)} | {_cell(suggest(w))} "
            f"| {_rb(rules, sec, w)} |")
    add("")

    # ---------------- 三、误读复查 ----------------
    sec = "三、算式误读：具体句子复查"
    add(f"## {sec}")
    add("")
    add("下面是**具体句子**层面的复查，每条都附原文与当前读法。"
        "与第二节不同：第二节裁「词归哪一类」，这里裁「这句话有没有被读错」。")
    add("")
    add("| 原文（节选） | 当前读法 | 问题 | 我的建议 | 裁定 |")
    add("|---|---|---|---|---|")
    cases = [
        ("受到的物理/法术伤害-80%", "算式 pass → `法术伤害-80%`（无属性）",
         "**规则表完全没匹配**——写成「降低80%」能认，写成「-80%」不认。"
         "91 处同类，是唯一会**伪装成已解析**的一类",
         "补规则字形 `受到…伤害-N%` → 减伤"),
        ("受到的物理/法术伤害降低80%", "`e_damage_reduce_pct 减伤 -80% (物理/法术)`",
         "这条是对的", "保持"),
        ("受到的物理和法术伤害-60%", "同上（无匹配）",
         "「和」「与」写法的 `-N%` 也漏", "与第一条一并补"),
        ("防御力/法术抗性最终×0", "`算式 法术抗性最终×0 ⟨变量：法术抗性最终⟩`",
         "斜杠是并列不是除法；现状字符串忠实、语义错",
         "4 处；已按并列读法落地（见 `LANDED`）"),
        ("发射-20°、±0°、+20°", "`算式 发射-20`（无属性）",
         "发射角度，不是属性增减——9 处噪声", "排除"),
        ("Lv×0 / (百分比)+0.1", "`算式 Lv×0`（无属性）",
         "公式系数，本来就不是一个属性", "留空（现状即可）"),
        ("(场上球员类敌人总数+1)", "`算式 …`（无属性）",
         "足球模式", "排除（既定口径不收）"),
    ]
    for src, cur, prob, sug in cases:
        if _answered(rules, sec, src):
            continue
        add(f"| {_cell(src)} | {_cell(cur)} | {_cell(prob)} | {_cell(sug)} "
            f"| {_rb(rules, sec, src)} |")
    add("")

    # ---------------- 四、需要我拿不到的数据 ----------------
    sec = "四、要实机数据、我取不到的"
    add(f"## {sec}")
    add("")
    add("这些不是口径分歧，是**数据缺口**——只能靠实机录像或您告知。")
    add("")
    add("| 事项 | 为什么取不到 | 现状 | 我的建议 | 裁定 |")
    add("|---|---|---|---|---|")
    gaps = [
        ("赤刃明霄陈技3 的剑气速度",
         "技能原文没写速度；gamedata 黑板里也没有",
         "2026-09-16 由攻略录像实测为 **1.2 格/秒**，已写成默认值（构造参数，可调）",
         "**已定案**，不需要裁定。细扫显示 1.2–1.25 会漏 1 只，而旧默认 4.0 恰好不漏——"
         "编出来的数不一定偏保守"),
        ("敌人攻击动作时长",
         "gamedata 里没有该字段", "模拟器假设 0.5s（`enemy_windup`）",
         "已做敏感性：0–1.0s 结论全同，60s 复现 37 杀 4 漏"),
        ("干员抬手 prepDuration 与动画帧补正",
         "gamedata 无对应数据；prts.wiki 的 Module 命名空间持续 403",
         "**攻击间隔已定案否**（2026-09-16 实机：1.25×100/124 的预测 15.12 帧"
         "与实测 15.11 帧吻合到 0.07%）；仍缺的只有**首刀时机**（抬手本身）",
         "周期不必再接数据；抬手要拿只能实机逐帧"),
    ]
    for a, b, c, d in gaps:
        if _answered(rules, sec, a):
            continue
        add(f"| {_cell(a)} | {_cell(b)} | {_cell(c)} | {_cell(d)} "
            f"| {_rb(rules, sec, a)} |")
    add("")

    # ---------------- 五、数据缺口 ----------------
    sec = "五、数据缺口（量小，可缓）"
    add(f"## {sec}")
    add("")
    add("| 事项 | 缺什么 | 现状 | 我的建议 | 裁定 |")
    add("|---|---|---|---|---|")
    for a, b, c, d in [
        ("量纲未定的 3 个键", "`exp` / `attack@exp` / `sell_card_gold`",
         "都是装置键、来历未定，`check_formula` 已把上限锁在 3",
         "按「只补战斗相关」豁免；删表即红，不会悄悄变多"),
        ("元素损伤的结算", "数据侧已认得种类与算式，战斗侧没有模型",
         "未建模", "工程量，非不确定；排在 A1 之后"),
        ("SR-EX-8 的敌人技能 / 飞行不可阻挡 / 反射 / BOSS 双形态重生",
         "4 件都未建模", "四人剑气方案已在现有模型下取胜（38 杀 1 漏，非三星）",
         "只有要打更难的关才需要"),
    ]:
        if _answered(rules, sec, a):
            continue
        add(f"| {_cell(a)} | {_cell(b)} | {_cell(c)} | {_cell(d)} "
            f"| {_rb(rules, sec, a)} |")
    add("")

    # ---------------- 六、已填未采纳 ----------------
    add("## 六、填了但还没落地的裁定")
    add("")
    add("生成时有内容、但代码里还没生效的裁定会列在这里（我落地后自动消失）。")
    add("")
    add("「已落地」由 `uncertainty_audit.py` 的 `LANDED` 表判定（人工维护，")
    add("记的是这条裁定进了哪段代码）——它不能自动判，但也正因如此，")
    add("某条裁定日后被改动悄悄回退时，这里会重新把它标回待落地。")
    add("")
    add("| 节 | 键 | 您填的裁定 | 状态 |")
    add("|---|---|---|---|")
    pend = _pending(rules)
    if pend:
        for s, k, v in pend:
            add(f"| {_cell(s)} | `{_cell(k, True)}` | {_cell(v)} | 待落地 |")
    else:
        add("| — | — | — | 暂无 |")
    add("")
    # ---------------- 七、手写补的节（原样搬过来）----------------
    # 放在最后：它们是手写的，不属于生成流程，搬过来即可。
    kept = split_preserved(out)
    if kept:
        if not kept.startswith("\n"):
            add("")
        add(kept.rstrip("\n"))
    return "\n".join(L) + "\n"


def _pending(rules: dict) -> list[tuple[str, str, str]]:
    """已填但代码尚未采纳的。落地后由 `LANDED` 消去。

    `LANDED` 是「键 → 落地凭证」的表：值是**说明这条裁定进了哪段代码**的一句话。
    它不能自动判定——「20 是不是真成了攻速下限」不是语料能回答的问题，
    只有读过 `skill.py` 的人知道。所以这里是人工维护的，而**这正是它有用的原因**：
    某条裁定被后来的改动悄悄回退时，这份台账会重新把它标成待落地。

    为什么不自作聪明去正则扫源码：那会把「注释里提了一句」当成「已实现」，
    比不判还坏。
    """
    return sorted((s, k, v) for (s, k), v in rules.items()
                  if v and k not in LANDED)


# —— 已落地的裁定（键 → 落地位置），2026-09-16 本轮 ——
LANDED: dict[str, str] = {
    "法术伤害有没有 5% 保底": "battle/damage.py DAMAGE_FLOOR=0.05（法抗≥100 仍免疫）",
    "攻速下限取多少": "operator/skill.py ASPD_MIN=20.0",
    "攻击力取整方式": "维持 floor，未改动（结论即现状）",
    "算式认领：属性表扩到哪一层": "enemy_formula.py _EXPR_ATTR 11→31 项",
    "防御力/法术抗性最终×0 怎么说": "enemy_formula.py _expr_kind 并列分支",
    "受到的物理/法术伤害-80%": "enemy_formula.py 规则 e_damage_reduce_sign",
    "规则抢先导致算式不出一项，是否可接受":
        "enemy_formula.py expr_terms 切段重试",
    "干员侧要不要也接算式 pass":
        "结论=只补规则不挂钩子；check_formula 第 [7] 节钉「干员侧不得出 expr_var」",
    "10×充能层数)": "已查清出处：瘴/鄙瘴（怀黍离），非缺口",
    "2+Lv×2)": "已查清出处：信使安洁莉娜技1/3，Lv=敌人档位",
    "【绒毛屏障】的屏障值": "已查清出处：BOSS 多利「羊之主」天赋，非缺口",
    "额外对以取消伤害的对象为中心周围四格":
        "整节按建议落地：93 词排除，未收进 _EXPR_ATTR",
    # —— 2026-09-19 补登 ——
    # 以下几条都是**博士已裁定且已落地**，只是落地当时没登记进本表，
    # 于是每次生成都被当成新题重新打印（博士反馈「我记得我都填过」的真因）。
    # 凭证是提交正文里逐字引用的裁定原话，补登后它们不再出现在清单里。
    "`防御力/法术抗性最终×0` 怎么读":
        "同一件事已在上表「…怎么说」登记过；这条是模板换了措辞导致键对不上，"
        "落地处同 `enemy_formula.py _expr_kind` 并列分支",
    "阿米娅技2「影霄·绝影」的『接下来的伤害类型变为真实』管到哪一段":
        "博士裁定②：末击起往后全为真实 → `operator/skill.py` `true_from_final_hit`"
        "（要求「最后一击」+「真实伤害」+「伤害类型变为真实」三者齐备），提交 764293b",
    "阿米娅(术战者)天赋「青色怒火」的『技能开启期间效果加倍』是谁开技能":
        "博士裁定①：光环主人（阿米娅自己）开技能时翻倍 → `battle/talents.py` TeamAura"
        " 全场光环 + `_refresh_auras` 在部署后与技能拍各刷一次，提交 764293b",
    "概率类效果（闪避/暴击）怎么进确定性模拟":
        "博士裁定④：期望值法（伤害 ×(1−闪避率)）→ 提交 4d8716c/f59c2a5 闪避全链路接通，"
        "`tools/dodge_check.py` 头注释同口径（编译层与战斗层同一期望）",
    "阿米娅技2「影霄·绝影」的击杀叠层：『斩击期间』指多长、结束后留不留":
        "裁定：整个技能持续期累积、结束时清零 → `OperatorUnit.kill_stacks` +"
        " `kill_max_stack`，逐帧计入 `current_atk()` 与 `current_res()`，提交 764293b",
    "召唤物的「同时部署上限」以哪个数为准":
        "取天赋描述**括号里**那个数（即上限），与 PRTS 备注一致 → "
        "`battle/talents.py find_summon_allowance`（文字优先、`source` 留痕）。"
        "证据：令/电弧「可以使用 3/4/5 个（最多同时部署 3 个）」→ 3；"
        "望「可以使用 4/5/6 枚（最多拥有 5/6/7 枚）」→ 7（前者是库存总量，不是上限）；"
        "PRTS 备注（多萝西/钼铅/艾拉）「陷阱部署上限与最多拥有数量相同」",
    # —— 2026-09-19 博士本轮填的裁定（读回后逐条核实现状）——
    "`tile_forbidden` 与 `tile_empty` 哪个对应哪种不可部署地块":
        "博士裁定：**empty 那个来自生息演算，无视**。与现状一致 → `db/tiles.py`："
        "`tile_forbidden`=禁入区、`tile_empty`=空（说明明写「游戏本体未包含该内容」）；"
        "`tools/check_db.py:675-678` 已把这条悬案销案并留守卫",
    "天赋「情绪吸收」在技能开启期间是否照常回 SP":
        "博士裁定：**技能期间不回复 sp**。即现状 → `battle/sim.py:4170-4175`"
        "（`if op.sp_per_attack_talent and not op.skill_active`）才额外回一份，"
        "与 `sp_per_attack` 口径一致",
    "受到的物理/法术伤害降低80%":
        "博士裁定：**保持**（现状即结论）。落地处同 LANDED 里「受到的物理/法术伤害-80%」"
        "→ `enemy_formula.py` 规则 `e_damage_reduce_sign`",
    "防御力/法术抗性最终×0":
        "同一件事已由上面两条「…怎么读／怎么说」的键登记过：斜杠是**并列**不是除法 → "
        "`enemy_formula.py _expr_kind` 并列分支。2026-09-19 博士要求把已落地的裁定"
        "从清单里删掉，故补上这个**第三节用的键形**（键不同曾使它一直长回来）",
    "(场上球员类敌人总数+1)":
        "博士裁定：**足球模式、生息演算等子玩法一律不收**（2026-09-16，"
        "见 `docs/enemy-formula.md:345-347` 的不收名单），本行即名单内 → 无需处理",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="生成待裁定清单")
    ap.add_argument("-o", "--out", type=pathlib.Path, default=OUT)
    args = ap.parse_args()
    bad = _key_roundtrip_bad()
    if bad:
        print(f"[!] 键往返自检失败 {len(bad)} 项——这些键写进表格后读回来会变形，"
              f"博士填了也不生效：")
        for k in bad[:5]:
            print(f"    {k!r}")
        return 1
    rules = load_rulings(args.out)
    text = render(rules, args.out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    freq, _, _ = collect()
    print(f"续用上一版已填的裁定 {len(rules)} 条")
    print(f"待裁左词 {len(freq)} 个 / 无属性算式 {sum(freq.values())} 项")
    print(f"已写 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
