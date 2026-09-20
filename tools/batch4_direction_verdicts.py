"""第四批方向表·**逐键判读表**（作者：RIOS 第四批建模 / session-dee51d3a）。

这是本任务的人工判读数据，不是生成物：每行是「这一条键，改完之后哪个可观测的数往
哪边动」。渲染与计数走 `tools/batch4_direction_table.py`（它会先与探针算出的 84 键
清单**核对集合相等**，对不上就 rc=1，防止表与名单分叉）。

字段
    state : 可接线 | 退回登记 | 不适用     ← 本任务判据的三态，判据是**方向**问题
    sub   : 退回登记/不适用的子因（三态不许压成一个，子因要写清试过哪几种读法）
    src   : 来源（技能·第几槽 / 天赋 / 特性）——决定落点走哪条闸
    dir   : 答句本体：量 → 方向 → 可观测量。**退回登记的行也要写清试过哪几种读法**
    basis : 正文（描述里直引）| 推断（键名＋上下文）| 谓词（`batch4_direction_checks.py` 可复算）
    note  : 落点与风险

★ 已知的**同名不同义**风险：`min_hp_ratio`/`max_hp_ratio` 在三个天赋里各指**不同主体的
生命比例**，且 `max_` 的极性在两处相反（详见 note）。

★ 落点（第二道闸）**不是**三态之一，单列成一栏（`src` 决定），因为实测：47 条技能键
被挡的理由里都含「技能效果 other」——**挡因就是这些键没被解释**，把它们归进
「不适用」会把本批该做的活划到范围外。此口径与任务原文的差别已在文档里声明并给出
两套读数的条数。
"""
from __future__ import annotations

#: 落点判据：来源技能被 `simgo/skills.py` 白名单挡住时，`dir` 仍答得出方向，
#: 但**当前没有落点**。逐技能原文见 `out/acceptance/batch4-port-per-skill.txt`。
VERDICTS: list[dict[str, str]] = [
    # ── 蕾缪安 ─────────────────────────────────────────────────────────
    dict(key="atk_to_hp_recovery_ratio", state="可接线", sub="", src="天赋·丰润羽翼",
         dir="量＝每秒回复量＝自身攻击力×5%；↑ ⇒ 攻击范围内低血友军的 HP 每秒抬升更多 ⇒ "
             "存活帧数上升；观测＝友军 HP 轨迹的斜率",
         basis="正文", note="落点＝天赋通道；受益面 2 位（淬羽赫默、调香师）"),
    dict(key="add_count", state="可接线", sub="", src="天赋·逃犯引渡手续",
         dir="量＝弹药上限增量（+1）；↑ ⇒ 技能期间能多打一发 ⇒ 出手笔数与总伤害上升",
         basis="正文", note="落点＝天赋通道（需新 spec 字段）"),
    dict(key="attack@aim_duration", state="可接线", sub="", src="技能·归乡邀约(s2)",
         dir="量＝瞄准上限秒数；↑ ⇒ 瞄准期更长 ⇒ 倍率能爬到更高（受 fin 封顶）⇒ 那一枪伤害上升",
         basis="正文", note="落点＝被挡（技能效果 other；挡因即本键族未被解释）"),
    dict(key="attack@aim_interval", state="可接线", sub="", src="技能·礼炮·强制追思(s3)",
         dir="量＝锁定间隔秒数；↓ ⇒ 同一次技能内锁定的目标数上升 ⇒ 轰炸目标数上升 ⇒ 总伤害上升",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@atk_scale_twice", state="可接线", sub="", src="技能·烛燃影息(s2)",
         dir="量＝二连击每击倍率（150%）；↑ ⇒ 期望伤害上升",
         basis="正文", note="落点＝被挡（面板增益 block_cnt；技能效果 other）"),
    dict(key="attack@base_atk_scale", state="退回登记", sub="两读法",
         src="技能·用赤铁铭记(s3)",
         dir="试过两种读法：①正常攻击那一段的倍率（值 1.0 ⇒ 实现后是恒等变换）"
             "②技能的 baseline 倍率。正文里没有对应句子，两读法动的是不同的量 ⇒ 不许接线",
         basis="推断", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@bounce_atk_scale", state="可接线", sub="", src="技能·用赤铁铭记(s3)",
         dir="量＝跳跃那一段的伤害倍率；↑ ⇒ 每笔跳跃伤害上升",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@def_dec_duration", state="可接线", sub="", src="天赋·家族手段",
         dir="量＝减防 debuff 的持续秒数；↑ ⇒ 目标 DEF 被压低的时间更长 ⇒ 后续每笔物理伤害上升；"
             "观测＝同一目标 PHITRES 的 delta 随时间",
         basis="正文", note="落点＝天赋通道"),
    dict(key="attack@def_scale", state="可接线", sub="", src="技能·灵与欲的惜别(s3)",
         dir="量＝心烛继承原敌人防御的比例；↑ ⇒ 心烛每次挨的伤害下降 ⇒ 传递发生得更慢；"
             "观测＝原敌人掉血的时刻序列",
         basis="推断", note="落点＝被挡（技能改写攻击范围；技能效果 other）；心烛机制两棵树零实现"),
    dict(key="attack@delay", state="可接线", sub="", src="技能·用赤铁铭记(s3)",
         dir="量＝跳跃之间的间隔秒数；↑ ⇒ 跳跃段更慢 ⇒ 技能期内段数下降；观测＝命中时刻序列",
         basis="推断", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@demetr_s3[bonus].atk", state="可接线", sub="", src="技能·清算(s3)",
         dir="量＝技能期间攻击力加成（1.7＝+170%）；↑ ⇒ 他每次出手的物理伤害上升；"
             "观测＝PHITRES 的 delta",
         basis="正文", note="落点＝被挡（技能改写攻击范围；技能变体；技能效果 other）"),
    dict(key="attack@demetr_s3[bonus].attack_speed", state="可接线", sub="", src="技能·清算(s3)",
         dir="量＝技能期间攻速加成（+50）；↑ ⇒ 攻击间隔＝基础×100/(100+攻速) 缩短 ⇒ "
             "单位时间出手数上升 ⇒ 总伤害上升",
         basis="正文", note="落点＝被挡（技能改写攻击范围；技能变体；技能效果 other）"),
    dict(key="attack@demetr_s3[bonus].prob", state="可接线", sub="", src="技能·清算(s3)",
         dir="量＝附加那一段的触发概率；↑ ⇒ 期望伤害上升",
         basis="正文", note="落点＝被挡（同族）"),
    dict(key="attack@demetr_s3[bonus].prob_atk_scale", state="可接线", sub="", src="技能·清算(s3)",
         dir="量＝附加那一段的倍率（185%）；↑ ⇒ 期望伤害上升",
         basis="正文", note="落点＝被挡（同族）"),
    dict(key="attack@demetr_s3[target_timer].interval", state="可接线", sub="",
         src="技能·清算(s3)",
         dir="量＝重选目标的计时间隔；↓ ⇒ 更快重选 ⇒ 目标切换更频繁；观测＝出手目标 idx 序列",
         basis="正文", note="落点＝被挡（同族）"),
    dict(key="attack@demetr_s3[target_timer].time_stack", state="可接线", sub="",
         src="技能·清算(s3)",
         dir="量＝重选阈值（与 interval 相乘）；谓词 time_stack×interval＝1.0 逐位成立，"
             "与正文的「持续 1 秒未攻击则重选目标」相符；↓ ⇒ 更早重选目标",
         basis="谓词", note="落点＝被挡（同族）"),
    dict(key="attack@dist_1", state="可接线", sub="", src="技能·礼炮·强制追思(s3)",
         dir="量＝中心判定的半径（配 proj_atk_scale_1＝450%）；↑ ⇒ 更多目标吃到中心倍率 ⇒ "
             "总伤害上升",
         basis="推断", note="落点＝被挡（技能效果 other）；中心/外圈的配对是推断，接线前须按实战读数核"),
    dict(key="attack@dist_2", state="可接线", sub="", src="技能·礼炮·强制追思(s3)",
         dir="量＝范围判定的半径（配 proj_atk_scale_2＝300%）；↑ ⇒ 覆盖更多目标 ⇒ 总伤害上升",
         basis="推断", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@emit_offset", state="退回登记", sub="两读法",
         src="技能·礼炮·强制追思(s3)",
         dir="试过两种读法：①落点相对锁定点的偏移（↑ ⇒ 打偏 ⇒ 命中数下降）"
             "②发射点相对自身的偏移（↑ ⇒ 不影响命中数）。两读法方向相反 ⇒ 不许接线",
         basis="推断", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@ex_atk_scale", state="可接线", sub="", src="技能·归乡邀约(s2)",
         dir="量＝每个 interval 的倍率增量；谓词 0.175/0.25＝0.7/s 与 (4.25−1.8)/3.5＝0.7/s "
             "相符 ⇒ 量纲是「每秒倍率增量×interval」；↑ ⇒ 倍率爬得更快 ⇒ 伤害上升",
         basis="谓词", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@extra_atk_scale", state="可接线", sub="", src="技能·混沌的本质(s3)",
         dir="量＝攻击经过中继器时额外那一段的法术伤害倍率；↑ ⇒ 每笔经过中继器的攻击伤害上升",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@extra_sluggish", state="可接线", sub="", src="技能·混沌的本质(s3)",
         dir="量＝停顿延长的秒数；↑ ⇒ 目标被拦推进的帧数上升；观测＝目标推进距离/位置轨迹",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@fin_atk_scale", state="可接线", sub="", src="技能·归乡邀约(s2)",
         dir="量＝瞄准终止时的倍率（封顶 425%）；↑ ⇒ 上限更高 ⇒ 那一枪伤害上升",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@finish_listener_duration", state="退回登记", sub="两读法",
         src="技能·清算(s3)",
         dir="试过两种读法：①技能结束后返回初始位置的时长（动的是位移轨迹）"
             "②监听「目标被击倒/自身受致命伤」这类结束事件的窗口（动的是技能结束时刻）。"
             "两读法动的是不同的量 ⇒ 不许接线",
         basis="推断", note="落点＝被挡（同族）"),
    dict(key="attack@limited_hit_time", state="可接线", sub="", src="技能·礼炮·强制追思(s3)",
         dir="量＝每处轰炸的判定窗口秒数；↑ ⇒ 移动中的敌人更可能被判中 ⇒ 命中数上升",
         basis="推断", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@limited_stack_cnt", state="可接线", sub="", src="天赋·家族手段",
         dir="量＝减防的叠加上限（层数）；↑ ⇒ 目标 DEF 最多降得更多 ⇒ 每笔物理伤害上升",
         basis="正文", note="落点＝天赋通道"),
    dict(key="attack@magic_resistance_scale", state="可接线", sub="", src="技能·灵与欲的惜别(s3)",
         dir="量＝心烛继承原敌人法抗的比例；↑ ⇒ 法术打心烛的每笔伤害下降 ⇒ 传递更慢",
         basis="推断", note="落点＝被挡（技能改写攻击范围；技能效果 other）"),
    dict(key="attack@main_atk_scale", state="可接线", sub="", src="技能·归乡邀约(s2)",
         dir="量＝瞄准起始的倍率（180%）；↑ ⇒ 每一枪的伤害上升",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@max_hp_scale", state="可接线", sub="", src="技能·灵与欲的惜别(s3)",
         dir="量＝心烛继承原敌人当前 HP 的比例；↑ ⇒ 心烛更耐打 ⇒ 能被攻击更多次 ⇒ "
             "传递回原敌人的累计伤害上升；观测＝原敌人 HP 轨迹",
         basis="推断", note="落点＝被挡（技能改写攻击范围；技能效果 other）"),
    dict(key="attack@origin_sluggish", state="可接线", sub="", src="技能·混沌的本质(s3)",
         dir="量＝基础停顿秒数；↑ ⇒ 目标被拦推进的帧数上升（推进距离下降）",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@prob_once", state="不适用", sub="派生",
         src="技能·烛燃影息(s2)",
         dir="谓词：prob_once＋prob_twice＝0.8＋0.2＝1.0 逐位成立 ⇒ 它是 prob_twice 的补集，"
             "接线会与 prob_twice 重复计数",
         basis="谓词", note="落点＝被挡（面板增益 block_cnt；技能效果 other）"),
    dict(key="attack@prob_twice", state="可接线", sub="", src="技能·烛燃影息(s2)",
         dir="量＝变成二连击的概率；↑ ⇒ 期望伤害上升",
         basis="正文", note="落点＝被挡（同族）"),
    dict(key="attack@proj_atk_scale_1", state="可接线", sub="", src="技能·礼炮·强制追思(s3)",
         dir="量＝中心那一档的伤害倍率（450%）；↑ ⇒ 吃到中心的目标那一笔伤害上升",
         basis="推断", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@proj_atk_scale_2", state="可接线", sub="", src="技能·礼炮·强制追思(s3)",
         dir="量＝外圈那一档的伤害倍率（300%）；↑ ⇒ 外围每笔伤害上升",
         basis="推断", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@projectile_range", state="可接线", sub="", src="技能·礼炮·强制追思(s3)",
         dir="量＝轰炸范围半径；↑ ⇒ 每次轰炸覆盖的敌人更多 ⇒ 总伤害上升",
         basis="推断", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@s2_limited_stack_cnt", state="可接线", sub="", src="天赋·家族手段",
         dir="量＝「军师的手段」期间的减防叠加上限（8）；↑ ⇒ 技能期间目标 DEF 降得更多 ⇒ "
             "技能期间伤害上升",
         basis="推断", note="★落点双重受阻：它只在 s2 期间生效，而 g(军师的手段) 被挡"
                            "（技能改写攻击范围）；接线本键前必须先让 s2 进 Go"),
    dict(key="attack@steal_hp", state="可接线", sub="", src="天赋·萃血",
         dir="量＝每次攻击偷取的目标生命上限；↑ ⇒ 目标 max HP 与当前 HP 下降更多 ⇒ 更早被击杀；"
             "观测＝目标 HP 轨迹",
         basis="正文", note="落点＝天赋通道；正文只说偷取目标，未写自身获得 ⇒ 自身侧不改"),
    dict(key="attack@steal_hp_max", state="可接线", sub="", src="天赋·萃血",
         dir="量＝偷取累计上限；↑ ⇒ 目标 max HP 可被压到更低 ⇒ 更早死亡",
         basis="正文", note="落点＝天赋通道"),
    dict(key="attack@trig_cnt", state="退回登记", sub="两读法", src="技能·归乡邀约(s2)",
         dir="试过两种读法：①瞄准的 tick 上限（谓词 trig_cnt＝aim_duration/interval＝"
             "3.5/0.25＝14.0 逐位成立）②弹药/触发次数上限（与同黑板 trigger_time＝7 不符）。"
             "两读法导致「这个量该与 aim_duration 去重还是与 trigger_time 相加」不同 ⇒ 不许接线",
         basis="谓词", note="落点＝被挡（技能效果 other）"),
    dict(key="attack@veen_s_2_buff[stack].atk", state="可接线", sub="",
         src="技能·以鲜血洗去(s2)",
         dir="量＝每层攻击力加成（15%）；↑ ⇒ 层数堆起来后攻击力更高 ⇒ 每笔伤害上升",
         basis="正文", note="★键名含 [stack]，而 stack 在源码里是通用局部变量名"
                            "（Go `stack := []Cell`、Python `stack = [seed]`）⇒ 按变体名 grep 会假命中；"
                            "落点＝被挡（技能变体；技能效果 other）"),
    dict(key="attack@veen_s_2_buff[stack].attack_speed", state="可接线", sub="",
         src="技能·以鲜血洗去(s2)",
         dir="量＝每层攻速加成（+8）；↑ ⇒ 攻击间隔缩短 ⇒ 出手数上升",
         basis="正文", note="落点＝被挡（技能变体；技能效果 other）"),
    dict(key="attack@veen_s_2_buff[stack].max_stack_cnt", state="可接线", sub="",
         src="技能·以鲜血洗去(s2)",
         dir="量＝层数上限（9）；↑ ⇒ 攻速与攻击力的上限更高 ⇒ 总伤害上升",
         basis="正文", note="落点＝被挡（技能变体；技能效果 other）"),
    dict(key="charge_time", state="可接线", sub="", src="技能·混沌的本质(s3)",
         dir="量＝技能开启后停止攻击的秒数；↑ ⇒ 技能前段不出手 ⇒ 技能期内出手数下降；"
             "观测＝技能期内首次出手时刻",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="damage_by_atk_scale", state="可接线", sub="", src="技能·沸腾爆裂(s3)",
         dir="量＝技能结束时那一下的范围伤害倍率（400%）；↑ ⇒ 那一笔伤害上升",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="damage_resistance_base", state="可接线", sub="", src="天赋·无声砥柱",
         dir="量＝庇护的基础值；↑ ⇒ 攻击范围内友军受到的伤害下降；观测＝友军 PHITRES 的 delta",
         basis="正文", note="落点＝天赋通道（Go 侧无庇护通道，需新开字段）"),
    dict(key="damage_resistance_pm", state="可接线", sub="", src="天赋·燃烛施明",
         dir="量＝自身受到的物理/法术伤害减免（8%）；↑ ⇒ 她承伤下降",
         basis="正文", note="落点＝天赋通道（Go 侧无庇护通道，需新开字段）"),
    dict(key="damage_resistance_scale", state="可接线", sub="", src="技能·俯瞰视界(s2)",
         dir="量＝第一天赋效果的倍数（×3）；↑ ⇒ 庇护更强 ⇒ 友军承伤下降",
         basis="推断", note="落点＝被挡（技能效果 other）；且它乘的是「无声砥柱」，须与该天赋同接"),
    dict(key="damage_scale_m", state="可接线", sub="", src="天赋·燃烛施明",
         dir="量＝造成的法术伤害加成（8%）；↑ ⇒ 她打出的法术伤害上升",
         basis="正文", note="落点＝天赋通道"),
    dict(key="dec_prob", state="可接线", sub="", src="天赋·街头直觉",
         dir="量＝闪避每秒衰减量；↑ ⇒ 闪避更快回落到下限 ⇒ 后期承伤上升",
         basis="正文", note="落点＝天赋通道（Go 已有 TalentDodgePhys/Arts 常量，需改成时变）"),
    dict(key="delta_atk_scale", state="可接线", sub="", src="特性·浮游单元",
         dir="量＝连续攻击同一敌人时每层伤害倍率的增量；↑ ⇒ 倍率爬得更快 ⇒ 对同一目标的伤害上升",
         basis="推断", note="落点＝特性通道；受益面 5 位（卡达、耶拉、洛洛、至简、时隙），"
                            "两棵树对 浮游/drone 只有 formula.py 的描述层命中、无实现"),
    dict(key="dot_duration", state="可接线", sub="", src="天赋·萃血",
         dir="量＝持续法术伤害的秒数；↑ ⇒ 总法术伤害上升 ⇒ 目标 HP 更低",
         basis="正文", note="落点＝天赋通道"),
    dict(key="duration_plus", state="退回登记", sub="两读法（谓词证伪）",
         src="技能·明灭(s3)",
         dir="试过两种读法：①「延长至 25 秒」的那一段＝10 秒——谓词证伪："
             "duration(15)＋duration_plus(15)＝30 ≠ enhance_duration(25)；"
             "②另一段效果的持续秒数。量未定 ⇒ 不许接线",
         basis="谓词", note="落点＝被挡（技能改写攻击范围；技能效果 other）"),
    dict(key="ep_damage_ratio_m", state="不适用", sub="零值",
         src="天赋·燃烛施明",
         dir="谓词：该键在 operator_talent 的**全部 4 档**取值均为 0.0 ⇒ 元素损伤占比恒 0，"
             "实现后没有任何可观测量会动",
         basis="谓词", note="落点＝天赋通道（但零收益）"),
    dict(key="ex_add_count", state="不适用", sub="零值", src="天赋·逃犯引渡手续",
         dir="谓词：该键在全部档位取值恒 0.0 ⇒ 实现后是恒等变换，无方向可言",
         basis="谓词", note="落点＝天赋通道（但零收益）"),
    dict(key="grave_duration", state="可接线", sub="", src="技能·无畏者协议(s3)",
         dir="量＝免死窗口秒数；↑ ⇒ 被保护干员「生命值不低于 1」的帧区间更长 ⇒ 存活上升",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="heal_ratio", state="可接线", sub="", src="技能·无始无明(s2)",
         dir="量＝回复量＝盾牌造成伤害的比例（15%）；↑ ⇒ 自身回血上升 ⇒ 存活上升",
         basis="正文", note="落点＝被挡（技能效果 control；技能效果 other）"),
    dict(key="huang_t_1[lock].duration", state="可接线", sub="", src="天赋·紧急除颤",
         dir="量＝锁血持续秒数；↑ ⇒ 生命值不低于 50% 的帧数上升 ⇒ 存活上升；"
             "观测＝煌 HP 轨迹里 ≥0.5×maxHP 的帧数（应等于 duration×30）",
         basis="正文", note="落点＝天赋通道；★同天赋的 huang_t_1[heal].hp_ratio 不在 keys1 里，"
                            "因变体名 heal 是源码通用字面量（13 处）⇒ 该分支被尺子**假清账**"),
    dict(key="huang_t_1[lock].min_hp_ratio", state="可接线", sub="", src="天赋·紧急除颤",
         dir="量＝锁血下限（生命值不低于该比例）；↑ ⇒ 更难被击杀",
         basis="正文", note="落点＝天赋通道"),
    dict(key="init_atk_scale", state="可接线", sub="", src="特性·浮游单元",
         dir="量＝首层伤害倍率（相对干员攻击力）；↑ ⇒ 起手那几笔伤害上升",
         basis="推断", note="落点＝特性通道；受益面 5 位"),
    dict(key="init_prob", state="可接线", sub="", src="天赋·街头直觉",
         dir="量＝部署瞬间的闪避率（80%）；↑ ⇒ 物理/法术承伤下降（闪避按期望折减）",
         basis="正文", note="落点＝天赋通道（需时变字段）"),
    dict(key="kjera_t_1[high].atk", state="可接线", sub="", src="天赋·低眉（条件分支）",
         dir="量＝满足「攻击范围内存在 ≥2 格地面地形」时的攻击力加成（16%）；↑ ⇒ 面板攻击力上升 ⇒ "
             "每笔伤害上升",
         basis="正文", note="落点＝天赋通道；需新增地形格数判据（同黑板 cnt＝2.0）"),
    dict(key="magic_value", state="可接线", sub="", src="天赋·萃血",
         dir="量＝每秒法术伤害；↑ ⇒ 目标 HP 下降更快",
         basis="正文", note="落点＝天赋通道"),
    dict(key="max_add_on_scale", state="可接线", sub="", src="天赋·家族手段",
         dir="量＝插值上端点（目标生命比例 ≤20% 端）的伤害加成（28%）；↑ ⇒ 低血目标挨的伤害上升",
         basis="正文", note="落点＝天赋通道；必须与 max_hp_ratio 配对接线"),
    dict(key="max_atk", state="可接线", sub="", src="天赋·鬼之架势",
         dir="量＝插值上端点（生命比例＝1.0 端）的攻击力加成，现值 0.0；↑ ⇒ 满血时也有加成 ⇒ "
             "每笔伤害上升。★0 是合法的插值端点，不是空值",
         basis="正文", note="落点＝天赋通道；必须与 max_hp_ratio 配对接线"),
    dict(key="max_atk_scale", state="可接线", sub="", src="特性·浮游单元",
         dir="量＝伤害倍率的封顶（110%）；↑ ⇒ 封顶更高 ⇒ 长连击的总伤害上升",
         basis="推断", note="落点＝特性通道；受益面 5 位"),
    dict(key="max_hp_ratio", state="退回登记", sub="主体未定", src="天赋·家族手段／鬼之架势",
         dir="同名两处指**不同主体**的生命比例（家族手段＝目标、鬼之架势＝自身），且 max_ 的极性相反："
             "家族手段 max_hp_ratio＝0.2 配的是**效果最大**端，鬼之架势 max_hp_ratio＝1.0 配的是"
             "**效果最小**端（max_atk＝0.0）。键名不含主体也不含极性 ⇒ 单键方向不可答",
         basis="谓词", note="处置：接线必须写成（来源天赋 × 本键）对，禁止按键名全局接"),
    dict(key="max_magic_resistance", state="可接线", sub="", src="天赋·鬼之架势",
         dir="量＝插值上端点（生命比例＝1.0 端）的法抗加成，现值 0.0；↑ ⇒ 满血时也有法抗 ⇒ "
             "受到的法术伤害下降。★0 是插值端点",
         basis="正文", note="落点＝天赋通道；必须与 max_hp_ratio 配对接线"),
    dict(key="max_minus_hp_ratio", state="可接线", sub="", src="天赋·业火",
         dir="量＝我执期间可累积的伤害上限（×max HP）；↑ ⇒ 更晚被击倒；"
             "观测＝进入我执→被击倒之间的帧数",
         basis="正文", note="落点＝天赋通道"),
    dict(key="merge_cnt", state="可接线", sub="", src="特性·储能",
         dir="量＝储能上限（最多存 3 个）；↑ ⇒ 一次齐射的能量数上升 ⇒ 总伤害上升",
         basis="推断", note="落点＝特性通道"),
    dict(key="merge_hit_cnt", state="可接线", sub="", src="技能·用赤铁铭记(s3)",
         dir="量＝转置能量的跳跃次数；↑ ⇒ 命中次数上升 ⇒ 总伤害上升",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="min_add_on_scale", state="可接线", sub="", src="天赋·家族手段",
         dir="量＝插值下端点（目标生命比例＝1.0 端）的伤害加成，现值 0.0；↑ ⇒ 满血目标挨的伤害上升。"
             "★0 是插值端点（另一端是 0.28），不是零值键",
         basis="正文", note="落点＝天赋通道；必须与 min_hp_ratio 配对接线"),
    dict(key="min_atk", state="可接线", sub="", src="天赋·鬼之架势",
         dir="量＝生命比例 ≤0.3 时的攻击力加成（35%）；↑ ⇒ 她每笔伤害上升",
         basis="正文", note="落点＝天赋通道；必须与 min_hp_ratio 配对接线"),
    dict(key="min_hp_ratio", state="退回登记", sub="主体未定",
         src="天赋·家族手段／无声砥柱／鬼之架势",
         dir="同名三处指**三个不同主体**的生命比例阈值（家族手段＝目标的、无声砥柱＝友军的、"
             "鬼之架势＝自身的），三处配对的效果键也各不相同（伤害加成／庇护／攻击力与法抗）⇒ "
             "单键方向不可答",
         basis="谓词", note="处置：与 max_hp_ratio 同——必须按（来源天赋 × 本键）对写，"
                            "并给这个槽加一个「主体」位"),
    dict(key="min_magic_resistance", state="可接线", sub="", src="天赋·鬼之架势",
         dir="量＝生命比例 ≤0.3 时的法抗加成（+50）；↑ ⇒ 她受到的法术伤害下降",
         basis="正文", note="落点＝天赋通道；必须与 min_hp_ratio 配对接线"),
    dict(key="mode_default", state="退回登记", sub="两读法", src="技能·混沌的本质(s3)",
         dir="试过两种读法：①中继器两种姿态各自的伤害倍率 ②攻击间隔的模式代号。正文里没有对应句子，"
             "且同值不同键（atk_scale＝2.0 是另一条）⇒ 量未定 ⇒ 不许接线",
         basis="推断", note="落点＝被挡（技能效果 other）"),
    dict(key="mode_down", state="退回登记", sub="两读法", src="技能·混沌的本质(s3)",
         dir="同上（试过的两种读法都说得通，动的是不同的量）",
         basis="推断", note="落点＝被挡（技能效果 other）"),
    dict(key="one_minus_status_resistance", state="可接线", sub="", src="天赋·严酷训练",
         dir="量＝1 − 可抵抗状态的生效时间倍率 ⇒ 倍率＝1＋(−0.5)＝0.5；值越负 ⇒ 状态计时器流逝越快 ⇒ "
             "冻结/眩晕类状态的剩余帧数下降、其定时触发效果间隔减半（总伤害翻倍）；"
             "观测＝被抵抗状态的剩余帧数、以及每 5 秒类效果的触发次数",
         basis="正文", note="落点＝天赋通道；★Go 侧 resist.go 有 resistHalf＝0.5 与守卫，但 "
                            "advanceStatus/resistFactor 在生产代码里**零调用点**（只出现在定义与测试）；"
                            "受益面 6 位（微风、寒檀、诺威尔、灵知、年、煌）＝本批最大杠杆"),
    dict(key="resistance_scale", state="可接线", sub="", src="天赋·无声砥柱",
         dir="量＝庇护随友军缺血程度的增长斜率；↑ ⇒ 低血友军的庇护更强 ⇒ 承伤更低。"
             "★斜率的分母（hp_ratio＝0.01 是什么单位）与「8%→15%」对不上，接线前须先定公式",
         basis="推断", note="落点＝天赋通道（Go 侧无庇护通道，需新开字段）"),
    dict(key="shield_atk_scale", state="可接线", sub="", src="技能·无始无明(s2)",
         dir="量＝盾牌每段法术伤害的倍率（130%）；↑ ⇒ 每笔盾牌伤害上升",
         basis="正文", note="落点＝被挡（技能效果 control；技能效果 other）"),
    dict(key="skill_index", state="不适用", sub="非量", src="天赋·（未命名）",
         dir="量＝选择器（该天赋作用于第 2 个技能）；它本身不动任何可观测量，"
             "同黑板另有 take_extra_enemy_key 才是该天赋的实质",
         basis="推断", note="落点＝天赋通道（接线无意义）"),
    dict(key="skill_max_trigger_time", state="可接线", sub="", src="技能·无畏者协议(s3)",
         dir="量＝一场作战内的最多次数；↑ ⇒ 能覆盖更多次致命伤 ⇒ 存活上升",
         basis="正文", note="落点＝被挡（技能效果 other）"),
    dict(key="super_scale", state="可接线", sub="", src="天赋·燃烛施明",
         dir="量＝攻击范围内存在精英/领袖时的效果倍数（×2）；↑ ⇒ 上面两条效果被放大 ⇒ "
             "法术伤害更高、承伤更低",
         basis="正文", note="落点＝天赋通道"),
    dict(key="token_recharge_cnt", state="可接线", sub="", src="技能·混沌的本质(s3)",
         dir="量＝技能期间可额外部署的中继器数；↑ ⇒ 攻击经过中继器的次数上升 ⇒ 额外伤害与停顿更多",
         basis="正文", note="落点＝被挡（技能效果 other）；且需装置（中继器）通道"),
    dict(key="trig_cnt", state="可接线", sub="", src="天赋·街头直觉",
         dir="量＝闪避衰减窗口的秒数；谓词 init_prob − trig_cnt×dec_prob＝0.8−0.4＝0.4，"
             "与正文的「衰减到 40%」相符；↑ ⇒ 高闪避维持更久 ⇒ 承伤下降",
         basis="谓词", note="落点＝天赋通道（需时变字段）"),
]


#: 落点**可算字段**：来源是技能 ⇒ 走 `simgo/skills.py` 白名单那条闸（逐技能原文见
#: `out/acceptance/batch4-port-per-skill.txt`）；天赋/特性走另一条通道（spec 字段＋检测器）。
#: 不许从 note 的散文里猜（第一版就是拿子串数出来的，把天赋键也数进去了）。
def land_of(src: str) -> str:
    return "挡" if src.startswith("技能") else "通"


#: 例外必须显式登记，不许藏在散文里。
LAND_OVERRIDE: dict[str, str] = {
    # 它本身是天赋键，但只在「军师的手段」期间生效，而那个技能被挡 ⇒ 同样没有落点。
    "attack@s2_limited_stack_cnt": "挡",
}
