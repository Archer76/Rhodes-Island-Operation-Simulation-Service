"""干员机制体检 + 语义提议：把「每做一位干员都手工开探针」这件事脚本化。

为什么要有它
------------
做一位干员机制的流程原来是：手写一段临时探针读黑板 → 手工翻 PRTS 备注 →
手工比对审计的三道筛子 → 手工决定"这条键该落到哪"。四步里**只有最后一步
真正需要人**，前三步都是查表，却每次都重打一遍探针、重抄一遍备注——token 与
时间都花在重复劳动上。

这个脚本把前三步收成一条命令，输出固定格式的**体检简报**：欠账键、它的取值与
双写写法、它挂在哪条技能/天赋上、PRTS 备注里对应哪一句、以及**候选语义**
（落到哪个字段、谁来消费、与同名效果怎么合并）。

它**不替人做裁定**，也不为了让账目归零而硬写读点——解释不了的键进"待裁定"
队列，那一份才是交给人看的。

三个输入（全在本地，不联网）
----------------------------
① `data/akdb.sqlite`       黑板键、正文、名册
② `data/prts-notes.sqlite` PRTS 干员页备注（由 `tools/fetch_prts_notes.py` 抓）
③ `tools/audit_coverage.py` 三道筛子的判据——**直接复用**，不另写一套

用法
----
    python tools/semantics_propose.py --only 凯尔希    # 按名字子串体检
    python tools/semantics_propose.py --top 8          # 欠账最多的 8 位
    python tools/semantics_propose.py --top 8 --notes  # 附带命中的备注原文
    python tools/semantics_propose.py --queue          # 只打待裁定队列（全库）

复核同一份结论的**权威命令**仍是：

    python tools/audit_coverage.py --only <干员名> --top 20
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from ak_tactic.operator import SkillBook, TalentBook   # noqa: E402
from ak_tactic.operator.skill import _classify      # noqa: E402
import audit_coverage as A                          # noqa: E402

NOTES_DB = ROOT / "data" / "prts-notes.sqlite"

#: 声明式语义表：**键 → 这条键在这套模型里到底是什么**。
#:
#: 表里有的，提议器直接给出「落到哪个字段、谁来消费、与同名怎么合并」；
#: 表里没有的，才走备注关键词兜，再兜不住就进待裁定队列。
#:
#: **这张表是"人只裁定新语义"这句承诺的落点**：每做一次新裁定，往这里加一行。
#: 值 = (语义, 消费点, 合并规则, 判定)，判定的三种取值：
#:
#: * `可落`   —— 通道已经存在或已定型，照着接线即可（仍要写守卫）；
#: * `需裁定` —— 同名反义 / 一键多义 / 语义未定，**必须**看正文与备注再定；
#: * `空面`   —— 通道在，但现名册里没有触发对象（如实记账，不硬凑用例）。
SEMANTICS: dict[str, tuple[str, str, str, str]] = {
    # —— 第三批已落地的四家（本轮新加）——
    "block_radius_scale": ("阻挡半径倍率", "sim._update_blocking → op.block_tol2",
                           "同名**取最高**（不与技能相加）", "可落"),
    "rhodes_bonus": ("对某势力效果翻倍", "talents.RegenAura.nation_mult",
                     "乘在速率上（不是时长）", "可落"),
    "max_hp_t1": ("〈替身〉形态生命上限", "unit.enter_stand 的面板改写",
                  "形态面板，退出还原", "可落"),
    "kill_atk_scale": ("斩杀阈值（攻击力的倍数）", "sim._stand_kill_sweep",
                       "阈值 = 当前攻击力 × 本值", "可落"),
    "kill_damage": ("斩杀伤害（固定值）", "sim._stand_kill_sweep",
                    "无来源真实伤害，不过减伤", "可落"),
    "max_target_heal": ("每次治疗的目标数", "sim._stand_queue_heal",
                        "按生命比例最低取前 N", "可落"),
    "multi_attack_total_cnt": ("总攻击的叠加次数", "sim._total_attack",
                               "与 atk_scale 相乘", "可落"),
    "final_damage_different_ratio": ("伤害类型不同时的最终倍率", "sim._total_attack",
                                     "乘在最后", "可落"),
    # —— 更早批次已落地的 ——
    "hp_recovery_per_sec": ("增益治疗的每秒回血", "talents.RegenAura.hp_per_sec",
                            "同人取 max（不可叠加）", "可落"),
    "buff_duration": ("增益治疗的持续时间", "talents.RegenAura.duration",
                      "同人取 max（不可叠加）", "可落"),
    "sluggish": ("停顿秒数", "EnemyUnit.sluggish_timer",
                 "与迟钝是两个量，不可合并", "可落"),
    "barrier_decay_pct": ("屏障每秒衰减比例", "sim._barrier_decay_tick",
                          "独立于屏障量本身", "可落"),
    "shield_max_hp_ratio": ("屏障量/上限", "unit.barrier", "同名反义：须按正文判",
                            "需裁定"),
    "attack@trigger_time": ("触发式效果的间隔", "无统一消费点", "语义随技能而变",
                            "需裁定"),
    "prob": ("概率", "各机制的期望值口径", "同名反义，且晕眩不可折期望",
             "需裁定"),
    "cost": ("费用相关（**一键四义**）", "operator/skill._cost_semantics",
             "四义必须分字段", "需裁定"),
    "range_id": ("攻击范围代号", "range_provider", "恒 0 占位，与同名列重复",
                 "空面"),
}

#: 备注关键词 → 语义名。表里的键按语义名反查这一张，用来**指出出处那一句**。
_NOTE_HINTS = {
    "阻挡半径倍率": ("阻挡半径", "阻挡范围"),
    "对某势力效果翻倍": ("翻倍", "罗德岛", "拉特兰"),
    "〈替身〉形态生命上限": ("替身",),
    "斩杀阈值（攻击力的倍数）": ("斩杀", "立刻倒下"),
    "斩杀伤害（固定值）": ("斩杀",),
    "每次治疗的目标数": ("治疗", "目标"),
    "停顿秒数": ("停顿",),
    "屏障每秒衰减比例": ("衰减",),
    "增益治疗的每秒回血": ("每秒回复", "增益治疗"),
}

_WS = re.compile(r"\s+")


def _notes_of(cid: str) -> list[tuple[str, str, str]]:
    """该干员的 PRTS 备注：`(kind, anchor, text)`；没抓过就返回空。"""
    if not NOTES_DB.exists():
        return []
    con = sqlite3.connect(NOTES_DB)
    try:
        return [(r[0], r[1], _WS.sub(" ", r[2]))
                for r in con.execute(
                    "SELECT kind, anchor, text FROM note WHERE char_id=?", (cid,))]
    finally:
        con.close()


def _notes_for(key: str, notes: list[tuple[str, str, str]],
               srcs: list[str], limit: int = 3) -> list[str]:
    """给这条键找备注里相关的几句（找不到就空表）。

    两条路，**顺序不能反**：

    ① **语义表里的家族关键词**——表里有的键才走这条，命中就是最准的那一句；
    ② **挂靠物对应的备注**——按技能名/天赋名取。第二条才是主力：**新键在语义表
       里必然缺席**（表是裁定结果的沉淀），而它的语义恰恰就写在它挂靠的那条技能
       或天赋的 `※` 备注段里。所以备注按**挂靠物**兜底，而不是按键名硬猜。
    """
    if not notes:
        return []
    out: list[str] = []
    spec = SEMANTICS.get(key)
    hints = _NOTE_HINTS.get(spec[0], ()) if spec else ()
    if hints:
        for _kind, _anchor, text in notes:
            for h in hints:
                i = text.find(h)
                if i >= 0:
                    out.append(text[max(0, i - 30):i + 70].strip())
                    break
    # 挂靠物：来源写法是「技能id·技能名」或天赋名，备注的 anchor 是**名字**
    names = {s.split("·")[-1].strip() for s in srcs} | {s.split("·")[0].strip()
                                                        for s in srcs}
    for kind, anchor, text in notes:
        if anchor.strip() in names:
            out.append(f"[{kind}·{anchor}] {text[:150]}")
    seen: list[str] = []
    for line in out:
        if line not in seen:
            seen.append(line)
    return seen[:limit]


def _blackboards(cid: str) -> tuple[dict[str, float], dict[str, str]]:
    """黑板取值 + **挂靠物的正文**。

    正文是裁定一条新键语义的最后一块拼图：PRTS 备注只挑重点写（可露希尔技1 的
    备注通篇讲**回费**，而 `shield_cnt` 那层护盾只写在技能正文里）。所以取值、
    正文、备注三件一起给，人才不必再开一次探针。
    """
    vals: dict[str, float] = {}
    descs: dict[str, str] = {}

    def _rec(key: str, raw: object) -> None:
        try:
            fv = float(raw)                              # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        if fv or key not in vals:
            vals[key] = fv

    try:
        for sk in SkillBook().for_operator(cid):
            try:
                lv = sk.level(level=7, mastery=3)
            except Exception:                            # noqa: BLE001
                continue
            for k, v in (lv.blackboard or {}).items():
                _rec(k, v)
            descs[f"{sk.skill_id}·{lv.name}"] = _WS.sub(" ", lv.description or "")
        for t in TalentBook().for_operator(cid):
            for k, v in (getattr(t, "blackboard", None) or {}).items():
                _rec(k, v)
            nm = getattr(t, "name", "") or "?"
            descs[nm] = _WS.sub(" ", getattr(t, "description", "") or "")
    except Exception:                                    # noqa: BLE001
        pass
    return vals, descs


def _classify_ok(key: str) -> bool | None:
    """第一道筛子：`_classify` 认不认这条键（认不了返回 False，调用失败返回 None）。"""
    try:
        return bool(_classify(key))
    except Exception:                                   # noqa: BLE001
        return None


def brief(cid: str, name: str, lits: set[str], det: str, *,
          with_notes: bool) -> tuple[list[str], int]:
    """一位干员的体检简报。返回 `(行列表, 真欠账数)`。"""
    sk_keys, t_keys, trait_keys = A.keys_of(cid)
    allk = sk_keys + t_keys + trait_keys
    unread = [(src, k) for src, k in allk if not A.is_read(k, lits)]
    # 同一键可能出现在多处（技能 + 天赋双写），来源合并展示
    by_key: dict[str, list[str]] = {}
    for src, k in unread:
        by_key.setdefault(k, []).append(src)

    lines = [f"{name}  {cid}   真欠账 {len(by_key)} 键 / 黑键合计 {len(allk)}"]
    notes = _notes_of(cid) if with_notes else []
    vals, descs = _blackboards(cid)
    queue: list[str] = []
    for k, srcs in sorted(by_key.items()):
        # ⚠️ 备注要在**分流之前**算好：`待裁定` 那条分支原来先 `continue` 了，
        # 于是最需要看备注的键（表里没有的）反而一句备注都不打。
        note_lines = ([f"          备注：「{n}」" for n in _notes_for(k, notes, srcs)]
                      if with_notes else [])
        spec = SEMANTICS.get(k)
        # 同一件事常有两种写法（`rhodes_bonus` 与 `attack@rhodes_bonus`），
        # 指出它的"另一半"能省一次翻黑板——审计的字面量筛子按裸键判，
        # 所以只要裸键出现在源码里，两半都算有人读。
        twin = ("双写 裸键 " + k.rsplit("@", 1)[-1] if "@" in k
                else "双写 前缀 attack@" + k)
        v = vals.get(k)
        where = "、".join(dict.fromkeys(srcs))[:60]
        vtxt = f" = {v:g}" if v is not None else ""
        if spec is None:
            c1 = _classify_ok(k)
            tag = "未归类" if c1 is False else ("归类未知" if c1 is None else "归类过")
            lines.append(f"  [待裁定] {k:<30}{vtxt}  {where}   （{tag}）")
            d = next((descs[s] for s in srcs if s in descs), "")
            if d:
                lines.append(f"          正文：{d[:200]}")
            lines.extend(note_lines)
            queue.append(f"{name}: {k}")
            continue
        fam, consumer, merge, verdict = spec
        mark = {"可落": "可落", "需裁定": "需裁定", "空面": "空面"}[verdict]
        lines.append(f"  [{mark}] {k:<30}{vtxt}  {where}")
        lines.append(f"          → {fam}；消费点 {consumer}；合并 {merge}；{twin}")
        lines.extend(note_lines)

    # 第三道筛子：天赋整个没有具名检测器
    for tn in A.talent_names_of(cid):
        if tn in det:
            continue
        keys = [k for src, k in t_keys if src == tn]
        if keys and set(keys) <= A.GENERIC_TALENT_KEYS:
            continue
        lines.append(f"  [无检测器] 天赋「{tn}」——talents.py 里加 is_/find_ 具名检测器"
                     f"（键：{', '.join(keys) or '无'}）")
    return lines, len(by_key)


def all_operators(roster: list[tuple[str, str, str, str]]
                  ) -> list[tuple[str, str, str, str]]:
    """**名册在前、游戏库里其余的干员接在后面**。

    博士要的是"所有人的数据"，而 `docs/roster-*.md` 只是**练度序名册**（他实际
    练的那批，211 位）；游戏库里 `is_operator=1` 有 460 位。两者都要覆盖：名册在
    前便于按练度序读，库里的其余人补在后，谁都不漏。
    """
    out = list(roster)
    seen = {r[1] for r in out}
    ak = ROOT / "data" / "akdb.sqlite"
    if ak.exists():
        con = sqlite3.connect(ak)
        try:
            for cid, name in con.execute(
                    "SELECT char_id, name FROM operator WHERE is_operator=1"):
                if cid not in seen:
                    out.append((name, cid, "", ""))
                    seen.add(cid)
        finally:
            con.close()
    return out


def verify(roster: list[tuple[str, str, str, str]]) -> None:
    """取数完整性：名册每位干员有没有页、有没有备注、有没有正文与事实。

    「拉下来了」要能拿数字回答，而不是凭印象。判据分三层：

    * **有页且抓成功**（`page.ok=1`）——没有页 = 根本没抓；
    * **有事实行**（`fact`：天赋效果 / 技能专精3描述）——正文一个字都没有 = 页
      抓歪了（比如抓到同名的别的东西）；
    * **有备注**——**这一层允许为 0**：确实有一批干员整页没有 `※` 备注段，
      那不是漏抓。所以只报数、不报错。

    同时反向查：库里有页但**不在名册**的名字（多半是同名歧义或非干员页）。
    """
    if not NOTES_DB.exists():
        print("还没有 data/prts-notes.sqlite——先跑 tools/fetch_prts_notes.py")
        return
    con = sqlite3.connect(NOTES_DB)
    pages = {r[0]: (r[1], r[2], r[3], r[4]) for r in con.execute(
        "SELECT char_id, name, ok, n_notes, note FROM page")}
    facts = {r[0]: r[1] for r in con.execute(
        "SELECT char_id, COUNT(*) FROM fact GROUP BY char_id")}
    con.close()
    no_page, bad, no_note, no_fact = [], [], [], []
    for name, cid, _e, _l in roster:
        if cid not in pages:
            no_page.append(f"{name}({cid})")
            continue
        _nm, ok, n_notes, _txt = pages[cid]
        if not ok:
            bad.append(f"{name}({cid})")
        if not n_notes:
            no_note.append(name)
        if not facts.get(cid):
            no_fact.append(name)
    print(f"名册 {len(roster)} 位：有页 {len(roster) - len(no_page)}、"
          f"抓成功 {len(roster) - len(no_page) - len(bad)}")
    if no_page:
        print(f"  **没有页**（{len(no_page)}）：{no_page[:10]}")
    if bad:
        print(f"  **抓失败**（{len(bad)}）：{bad[:10]}")
    if no_fact:
        print(f"  **连正文都没有**（{len(no_fact)}，这才是可疑的）：{no_fact[:10]}")
    print(f"  整页没有 ※ 备注的（{len(no_note)} 位，**允许**，不是漏抓）："
          f"{no_note[:10]}")
    extra = [f"{v[0]}({k})" for k, v in pages.items()
             if k not in {r[1] for r in roster}]
    print(f"  库里有页但不在名册（{len(extra)}，非干员页/同名歧义）：{extra[:6]}")


def run(names: list[tuple[str, str, str, str]], *, with_notes: bool,
        out: str = "") -> None:
    lits = A.source_literals()
    det = A.detector_text()
    total = Counter()
    buf: list[str] = []
    # ⚠️ 名册元组的列序是 (名字, charId, 精英, 等级)——`brief` 要的是 (charId, 名字)，
    # 别照抄（这一处写反过：筛选用 r[1] 找名字，一个都匹配不上，静默打空）。
    for name, cid, _elite, _level in names:
        lines, n = brief(cid, name, lits, det, with_notes=with_notes)
        buf.extend(lines)
        total["keys"] += n
    tail = (f"\n合计真欠账 {total['keys']} 键 / {len(names)} 位干员"
            f"（复核：python tools/audit_coverage.py --top {len(names)}）")
    if out:
        Path(out).write_text("\n".join(buf) + "\n" + tail + "\n", encoding="utf-8")
        print(f"已写入 {out}（{len(names)} 位、{total['keys']} 键欠账）")
    else:
        print("\n".join(buf))
    print(tail.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description="干员机制体检 + 语义提议")
    ap.add_argument("--only", default="", help="名字含该子串的干员")
    ap.add_argument("--top", type=int, default=0, help="欠账最多的前 N 位")
    ap.add_argument("--all", action="store_true", help="**全库每位干员**都出一份简报")
    ap.add_argument("--out", default="", help="把简报写进这个文件（默认只打屏）")
    ap.add_argument("--verify", action="store_true",
                    help="只查取数完整性：名册每位有没有页、有没有备注与正文")
    ap.add_argument("--queue", action="store_true", help="只打待裁定队列（全库）")
    ap.add_argument("--notes", action="store_true", help="附带命中的 PRTS 备注原文")
    ap.add_argument("--dump", default="",
                    help="把某位干员的备注原文全打出来（排查挂靠物对不对）")
    a = ap.parse_args()

    roster = A.load_roster()
    if a.verify:
        verify(roster)
        return
    if a.dump:
        hit = [r for r in roster if a.dump in r[0]]
        if not hit:
            print(f"名册里没有含「{a.dump}」的干员——注意 `--dump` 认的是**名字**，"
                  f"不是 charId。")
            return
        for name, cid, _e, _l in hit:
            print(f"== {name} {cid}")
            for kind, anchor, text in _notes_of(cid):
                print(f"[{kind}·{anchor}] {text[:500]}")
        return
    if a.only:
        picked = [r for r in roster if a.only in r[0]]
    elif a.all:
        picked = all_operators(roster)
    elif a.top or a.queue:
        # 欠账数要用真筛子算，所以这里全量跑一遍（约一两分钟）
        lits, det = A.source_literals(), A.detector_text()
        scored = []
        for r in roster:
            _lines, n = brief(r[1], r[0], lits, det, with_notes=False)
            scored.append((n, r))
        scored.sort(key=lambda x: (-x[0], x[1][0]))
        picked = [r for n, r in scored if n > 0][: a.top or len(scored)]
    else:
        ap.error("给一个范围：--only / --top / --queue")
        return
    if not picked:
        print("没有命中的干员。")
        return
    run(picked, with_notes=a.notes, out=a.out)


if __name__ == "__main__":
    main()
