"""方向表里那些「派生 / 非量」判定的可复算谓词（**不许只写在散文里**）。

表里凡写「⊘派生」「⊘零值」的行，谓词必须能在这里跑出同一个结论；跑不出来就 rc=1，
防止把「看着像」写成判据。同时把「变体名是不是通用词」查一遍——决定某键被判
「有人读」是真消费点还是**尺子被通用词骗**（`e60262e9` 第五类成因）。

用法：`python tools/batch4_direction_checks.py`
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

from ak_tactic.operator.skill import SkillBook  # noqa: E402
from ak_tactic.operator.talent import TalentBook  # noqa: E402

PICKS = {"贝洛内": "char_4037_demetr", "耶拉": "char_4013_kjera",
         "蕾缪安": "char_4193_lemuen", "维伊": "char_4226_veen",
         "薇薇安娜": "char_4098_vvana", "淬羽赫默": "char_1031_slent2",
         "煌": "char_017_huang", "隐德来希": "char_4010_etlchi",
         "斩业星熊": "char_1044_hsgma2", "谬因": "char_4229_aphris"}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))


def skill_bb(cid: str, sid: str) -> dict:
    for sk in SkillBook().for_operator(cid):
        if sk.skill_id == sid:
            return dict(sk.level(level=7, mastery=3).blackboard or {})
    return {}


def skill_duration(cid: str, sid: str) -> float | None:
    for sk in SkillBook().for_operator(cid):
        if sk.skill_id == sid:
            lv = sk.level(level=7, mastery=3)
            return getattr(lv, "duration", None)
    return None


def talent_bb(cid: str, name: str) -> dict:
    for t in TalentBook().for_operator(cid):
        if getattr(t, "name", "") == name:
            return dict(getattr(t, "blackboard", None) or {})
    return {}


# ① prob_once + prob_twice == 1（薇薇安娜技2）⇒ prob_once 是 prob_twice 的补集
bb = skill_bb(PICKS["薇薇安娜"], "skchr_vvana_2")
s = bb.get("attack@prob_once", 0.0) + bb.get("attack@prob_twice", 0.0)
check("薇薇安娜·烛燃影息 prob_once+prob_twice==1",
      abs(s - 1.0) < 1e-12, f"{bb.get('attack@prob_once')} + {bb.get('attack@prob_twice')} = {s}")

# ② trig_cnt == aim_duration / interval（蕾缪安技2）
bb = skill_bb(PICKS["蕾缪安"], "skchr_lemuen_2")
t = bb.get("attack@trig_cnt")
q = bb.get("attack@aim_duration", 0.0) / bb.get("attack@interval", 1.0)
check("蕾缪安·归乡邀约 trig_cnt==aim_duration/interval",
      t is not None and abs(t - q) < 1e-12,
      f"trig_cnt={t}  aim_duration/interval={bb.get('attack@aim_duration')}/"
      f"{bb.get('attack@interval')}={q}")

# ③ time_stack * interval == 1 秒（贝洛内技3 的「持续1秒未攻击则重选目标」）
bb = skill_bb(PICKS["贝洛内"], "skchr_demetr_3")
p = bb.get("attack@demetr_s3[target_timer].time_stack", 0.0) * \
    bb.get("attack@demetr_s3[target_timer].interval", 0.0)
check("贝洛内·清算 time_stack*interval==1.0",
      abs(p - 1.0) < 1e-12,
      f"{bb.get('attack@demetr_s3[target_timer].time_stack')} × "
      f"{bb.get('attack@demetr_s3[target_timer].interval')} = {p}")

# ④ duration_plus **不是**「延长到 25 秒」的那一段（薇薇安娜技3）——这条谓词是**证伪**用的：
#    它成立（15+15≠25）正是 duration_plus 判「退回登记」的理由。若哪天数据改成相等，
#    本检查会转红，提示那条判读该重做（而不是让一个空的绿留在那里）。
bb = skill_bb(PICKS["薇薇安娜"], "skchr_vvana_3")
base = skill_duration(PICKS["薇薇安娜"], "skchr_vvana_3")
dp, enh = bb.get("duration_plus"), bb.get("enhance_duration")
check("薇薇安娜·明灭 duration+duration_plus ≠ enhance_duration（「延长到25秒」读法被证伪）",
      base is not None and dp is not None and enh is not None and abs(base + dp - enh) > 1e-9,
      f"duration={base} ＋ duration_plus={dp} = {(base or 0) + (dp or 0)}，"
      f"而 enhance_duration={enh} ⇒ 差值 {enh - base if base else None} 秒不是 duration_plus")

# ⑤ 街头直觉 init_prob − trig_cnt×dec_prob == 衰减下限 0.4（正文直引）
bb = talent_bb(PICKS["贝洛内"], "街头直觉")
low = bb.get("init_prob", 0.0) - bb.get("trig_cnt", 0.0) * bb.get("dec_prob", 0.0)
check("贝洛内·街头直觉 init−trig×dec==0.4（正文「衰减到40%」）",
      abs(low - 0.4) < 1e-12, f"{bb.get('init_prob')} − {bb.get('trig_cnt')}×"
                             f"{bb.get('dec_prob')} = {low}")

# ⑥ 燃烛施明的 ep_damage_ratio_m 在**全部档位**恒 0（⊘零值 的谓词）
import sqlite3  # noqa: E402
con = sqlite3.connect(f"file:{ROOT / 'data' / 'akdb.sqlite'}?mode=ro", uri=True)
vals = [json.loads(b or "{}").get("ep_damage_ratio_m")
        for (b,) in con.execute("SELECT blackboard FROM operator_talent "
                                "WHERE char_id=? AND name=?", (PICKS["薇薇安娜"], "燃烛施明"))]
check("薇薇安娜·燃烛施明 ep_damage_ratio_m 全档为 0",
      bool(vals) and all(v == 0 for v in vals), f"各档取值 = {vals}")

# ⑦ 逃犯引渡手续 ex_add_count 在全部档位恒 0
vals = [json.loads(b or "{}").get("ex_add_count")
        for (b,) in con.execute("SELECT blackboard FROM operator_talent "
                                "WHERE char_id=? AND name=?", (PICKS["蕾缪安"], "逃犯引渡手续"))]
check("蕾缪安·逃犯引渡手续 ex_add_count 全档为 0",
      bool(vals) and all(v == 0 for v in vals), f"各档取值 = {vals}")

# ⑧ 鬼之架势 的极性：max_hp_ratio 配的是**最小值**（与 家族手段 相反）
gj = talent_bb(PICKS["斩业星熊"], "鬼之架势")
jt = talent_bb(PICKS["贝洛内"], "家族手段")
check("极性相反（同名键在两处配不同端）",
      gj.get("max_hp_ratio") == 1.0 and gj.get("max_atk") == 0.0
      and jt.get("max_hp_ratio") == 0.2 and jt.get("max_add_on_scale", 0) > 0,
      f"鬼之架势 max_hp_ratio={gj.get('max_hp_ratio')} 配 max_atk={gj.get('max_atk')}；"
      f"家族手段 max_hp_ratio={jt.get('max_hp_ratio')} 配 max_add_on_scale={jt.get('max_add_on_scale')}")

# ⑨ min_hp_ratio 在三处各指不同主体（⊘主体未定 的谓词：三处取值/配对键都不同）
sub = {"家族手段(目标)": talent_bb(PICKS["贝洛内"], "家族手段").get("min_hp_ratio"),
       "无声砥柱(友军)": talent_bb(PICKS["淬羽赫默"], "无声砥柱").get("min_hp_ratio"),
       "鬼之架势(自身)": gj.get("min_hp_ratio")}
check("min_hp_ratio 三处主体不同（不是同一个量）",
      sub["家族手段(目标)"] == 1.0 and sub["无声砥柱(友军)"] == 0.3
      and sub["鬼之架势(自身)"] == 0.3, f"{sub}")

# ⑩ 变体名是不是源码里的**通用词**（决定「有人读」是真消费还是尺子被骗）
LIT = re.compile(r"""["']([A-Za-z_@$][A-Za-z0-9_@$.]*)["']""")
lits: set[str] = set()
for p in (ROOT / "ak_tactic").rglob("*.py"):
    if "__pycache__" not in p.parts:
        lits.update(LIT.findall(p.read_text(encoding="utf-8")))
for v in ("heal", "lock", "stack", "high", "bonus", "target_timer", "second"):
    where = []
    for p in (ROOT / "ak_tactic").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if f'"{v}"' in line or f"'{v}'" in line:
                where.append(f"{p.relative_to(ROOT).as_posix()}:{i}")
    print(f"变体名 {v!r}: 是源码字面量={v in lits}  出处 {len(where)} 处 {where[:3]}")

print()
bad = 0
for name, ok, detail in results:
    print(("  ✓ " if ok else "  ✗ ") + name + "  |  " + detail)
    bad += 0 if ok else 1
print(f"\n谓词 {len(results)} 条：通过 {len(results) - bad}、失败 {bad}")
Path(ROOT / "out" / "acceptance" / "batch4-direction-checks.txt").write_text(
    "\n".join(("OK  " if ok else "FAIL") + " " + n + " | " + d for n, ok, d in results) + "\n",
    encoding="utf-8")
raise SystemExit(1 if bad else 0)
