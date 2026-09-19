// skill.go：技能的**状态机**（攒技力 / 能不能开 / 开多久 / 结束）。
//
// ## 为什么状态机在 Go、数值在 Python
//
// 原版把技能拆成两件事，这两件事的归属**不一样**：
//
//   - **数值**（开着的时候攻击力/攻速/伤害类型是多少）——由 Python 侧用原版
//     自己的读数函数算好，两套一起送过来（`OperatorSpec` 顶层那套 = 没开技能，
//     `Active` 那套 = 技能期间）。Go 一个数都不算。
//   - **状态机**（这一帧攒了多少技力、够不够开、还剩几秒）——**只能在 Go 跑**：
//     "够不够开"取决于战斗中发生的事（出手回复、受击回复、手动请求落在哪一帧），
//     事前算不出来。
//
// ## 与 `sim._skill_tick` 逐条对齐
//
// 帧内位置：**阻挡之后、我方出手之前**（`sim.py` 的 5. 技能）。排在这里是因为
// "刚攒满技力的那一帧就得算数"——晚一帧会让每一次开技都慢一个 dt，
// 而 dt=1/30 时一整局下来能差出好几次出手。
//
// 顺序与判据都照抄原版，包括两处**看起来不一致、但必须照抄**的上限：
//
//   - 攒技力（未开启）时上限是 `sp_cost × max(1, max_charge)`——可充能 N 次的
//     技能允许把 N 次的使用额度攒起来；
//   - 出手回复（`sp_per_attack` / `sp_per_hit`）时上限却是 `sp_cost`。
//
// 两处不一样是真的（`sim.py` 就是这么写的），"顺手统一"会让可充能技能的
// 技力条与手感同时变样。
package main

import (
	"fmt"
	"math"
	"os"
)

// 技力回复方式（与 `ak_tactic/operator/skill.py` 的 SP_* 同源）
const (
	spNone   = "PASSIVE"
	spAuto   = "INCREASE_WITH_TIME"
	spAttack = "INCREASE_WHEN_ATTACK"
	spHit    = "INCREASE_WHEN_TAKEN_DAMAGE"
)

// skillTick 每帧的技能结算（`BattleSimulator._skill_tick`，sim.py）。
//
// `cost` 是指针：回费类技能在**开启那一刻**直接给费用（原版 `_activate` 里
// `self.cost = min(self.max_cost, self.cost + gain)`）。
func skillTick(ops []*operator, dt, t float64, spec *Spec, cost *float64,
	verdict *Verdict) {
	for _, op := range ops {
		if !op.alive() {
			continue
		}
		// 【冻结】按帧递减（原版 `sim.py:2038-2041`）。干员侧的冻结 = **缴械**、
		// **不动阻挡**，所以它有自己的字段，不能并进别的计时器。
		//
		// ⚠ 必须放在下面 `if sk == nil { continue }` **之前**：原版就在
		// `op.skill is None` 那道 continue 之前递减。放后面的话，**没带技能的
		// 干员被冻住就永远解不开**——而这类偏差在判决上完全看不出来。
		if op.freezeTimer > 0 {
			op.freezeTimer = math.Max(0.0, op.freezeTimer-dt)
		}
		// 「每 N 秒获得 1 层护盾」（泥岩「沃土予身」）**与技能无关**，所以必须
		// 放在下面 `if sk == nil { continue }` **之前**——原版就是这么排的
		// （`sim.py:2042-2045`，注释里写明"放后面会让没带技能的泥岩整场不长护盾，
		// 而且是静默的"）。
		//
		// 满层时这一次"获得"**作废、计时照走不攒着**：正文只说"每 9 秒获得 1 层
		// （最多 3 层）"，没说满层挂起（原版 `_shield_tick` 的 while 循环同义）。
		if op.shieldInterval > 0 && op.shieldMaxLayers > 0 {
			op.shieldTimer += dt
			for op.shieldTimer >= op.shieldInterval {
				op.shieldTimer -= op.shieldInterval
				if op.shieldLayers < op.shieldMaxLayers {
					op.shieldLayers++
					if traceOn && op.sim != nil {
						trace("SHIELD t=%.4f op=%s grant %d/%d", t, op.spec.Name,
							op.shieldLayers, op.shieldMaxLayers)
					}
				}
			}
		}
		sk := op.spec.Skill
		if sk == nil {
			continue
		}
		// 被动技能：部署即生效、不耗技力、永不关闭
		if sk.Passive {
			if !op.skillActive {
				activate(op, t, spec, cost, verdict, true)
			}
			continue
		}
		if op.skillActive {
			// 持续时间倒计时（无限持续减不完）
			if !sk.Infinite {
				op.skillTimer -= dt
				if op.skillTimer <= 0 {
					deactivate(op)
					continue
				}
			}
			// 弹药类：打光就结束
			if sk.Ammo > 0 && op.ammoLeft <= 0 {
				deactivate(op)
				continue
			}
			// 只有多充能技能在**开启期间**还继续攒技力
			if sk.MaxCharge > 1 && sk.SPType == spAuto {
				op.sp = math.Min(sk.SPCost*float64(sk.MaxCharge),
					op.sp+sk.Increment*dt)
			}
			op.skillReq = false
			continue
		}
		// 未开启：按回复方式攒技力（上限见文件头那两条）
		if sk.SPType == spAuto {
			cap := sk.SPCost * math.Max(1, float64(sk.MaxCharge))
			op.sp = math.Min(cap, op.sp+sk.Increment*dt)
		}
		ready := op.sp >= sk.SPCost
		want := op.skillReq || sk.AutoTrigger || op.autoSkill
		if sk.OncePerBattle && op.spCharges >= 1 {
			want = false
		}
		if ready && want {
			activate(op, t, spec, cost, verdict, false)
		}
		op.skillReq = false
	}
}

// activate 开技能（`sim._activate` 的**已移植子集**）。
//
// 原版在这里还顺手做了几件事（剑气、推击、锤击时刻表、屏障、闪避、生命上限
// 加成、击杀叠层、刚连射、换变体）——那些技能在规格生成时就被白名单挡住了
// （见 `ak_tactic/simgo/skills.py`），所以这里只做状态机那几件：
// 扣技力、记次数、定持续、装弹、回费。
func activate(op *operator, t float64, spec *Spec, cost *float64,
	verdict *Verdict, passive bool) {
	sk := op.spec.Skill
	if sk == nil {
		return
	}
	if !passive {
		op.sp = math.Max(0, op.sp-sk.SPCost)
	}
	op.skillActive = true
	if sk.Infinite {
		op.skillTimer = math.Inf(1)
	} else {
		op.skillTimer = sk.Duration
	}
	op.ammoLeft = sk.Ammo
	// 天赋「强击瓶专家」：**部署后首次开启技能时**，接下来 N 轮攻击的攻击力
	// 倍率提升。判据是"本局的第几次开技"，而 `spCharges` 在**下一行**才自增，
	// 所以这里读到的 0 就是首次（原版 `sim.py:2448` 同一位置、同一写法）。
	//
	// 每次开技都重置一遍也无妨——它只在 `== 0` 时触发，之后的技能不动它，
	// 剩余层数照常往下走（这正是原版的行为：层数是**跨技能**消耗的）。
	if op.spCharges == 0 && op.spec.PowerAttackCount > 0 {
		op.powerAttackLeft = float64(op.spec.PowerAttackCount)
	}
	op.spCharges++
	// 技能给的生命上限（原版 `sim.py:2498` → `unit.py:947`）：
	// 「上限和当前血量一起涨」——`hp += 基准 × pct`，这里用绝对值反推：
	// `pct × 基准 = 新上限 − 基准`。少了这一句，"开技能翻倍生命上限"的干员
	// 会少一半血（HS-EX-8 第 3 手圣聆初雪：2058 就倒，原版到 4116）。
	if p := op.profile(); p != nil && p.MaxHP != nil {
		base := op.spec.MaxHP
		op.hp = math.Min(*p.MaxHP, op.hp+(*p.MaxHP-base))
	}
	if sk.CostGain != 0 {
		*cost = math.Min(spec.CostMax, *cost+sk.CostGain)
	}
	verdict.Events = append(verdict.Events,
		Event{T: t, Kind: "skill", Who: op.spec.Name})
}

// deactivate 关技能（`sim._deactivate` 的已移植子集）：技力清零、状态归位。
//
// 原版还会清击杀叠层、闪避、屏障——那些都不在白名单里（拒跑），所以这里不写；
// 写了反而是给"以后接了它们"埋一个假的已完成状态。
func deactivate(op *operator) {
	op.skillActive = false
	op.skillTimer = 0
	op.ammoLeft = 0
	op.sp = 0
	// 生命上限还原（原版 `revert_max_hp_bonus`，unit.py:956）：上限回到基准，
	// 当前血量按新上限夹一次——**不是**把涨上去那部分再扣掉。
	op.hp = math.Min(op.hp, op.spec.MaxHP)
}

// maxHP 这一刻的生命上限：技能开着且有值就用技能给的，否则用规格里的基准值。
//
// 凡是"夹血量 / 算血量比例"的地方都该走这里，而不是直接读 `spec.MaxHP`：
// 直接读会在技能期间把上限算小（回血夹在旧上限、血量比例偏高）。
func (o *operator) maxHP() float64 {
	if p := o.profile(); p != nil && p.MaxHP != nil {
		return *p.MaxHP
	}
	return o.spec.MaxHP
}

// spOnAttack 出手回复的技力（`_operators_attack` 尾部）。
//
// **只在技能没开着的时候回**，且上限是 `sp_cost`（不是 `× max_charge`——
// 见文件头）。按"出手"算，不按打中几个目标算。
func spOnAttack(op *operator) {
	sk := op.spec.Skill
	if sk == nil || sk.Passive || op.skillActive {
		return
	}
	if sk.SPType != spAttack || sk.Increment == 0 {
		return
	}
	op.sp = math.Min(sk.SPCost, op.sp+sk.Increment)
}

// spOnHit 受击回复的技力（`_enemies_attack` 尾部）：这一下**真的掉血了**才回。
func spOnHit(op *operator, dealt float64) {
	sk := op.spec.Skill
	if dealt <= 0 || sk == nil || sk.Passive || op.skillActive {
		return
	}
	if sk.SPType != spHit || sk.Increment == 0 {
		return
	}
	op.sp = math.Min(sk.SPCost, op.sp+sk.Increment)
}

// useSkill 手动开技能的一次请求：时刻到了，找**站在这一格上的、活着的**干员
// 记一笔请求（`sim.use_skill` → `_alive_op_at(position)`）。
//
// 找不到人（已阵亡 / 没部署 / 那格上站的不是它）就什么也不发生——
// 请求不是命令，能不能开还要看那一刻的技力（在 `skillTick` 里判）。
func useSkill(ops []*operator, cell [2]int) {
	for _, op := range ops {
		if !op.alive() {
			continue
		}
		if int(op.cell[0]) == cell[0] && int(op.cell[1]) == cell[1] {
			op.skillReq = true
		}
	}
}

// ---------------------------------------------------------------- 跟踪

// traceOn 打开逐帧跟踪（`RIOS_TRACE=1`）。
//
// 对拍分叉时唯一能定量的手段：判决只说"两边不一样"，而**哪一帧开始不一样**
// 得从逐帧读数里看。默认关，且只写 stderr——stdout 是协议通道，一个字都不能多。
//
// 为什么不做成协议里的一条命令：协议是给调用方用的，跟踪是给查错的人用的，
// 两者的生命周期不一样（这条查完就没人再跑，也没有版本兼容的负担）。
var traceOn = os.Getenv("RIOS_TRACE") == "1"

// tracePosName 只对**这一只敌人**逐帧打坐标（空 = 不打）。
//
// 为什么要单独一个开关：坐标是每帧每只一行，全开就是几万行，捞不出东西；
// 而"某只敌人推进得不一样"这类差异，**逐帧坐标比出手笔数早暴露得多**
// （出手是位置的结果，位置是第一手）。按名字筛而不是按下标：下标在排查时
// 要先反查名单，名字直接对应到看得见的那一只。
var tracePosName = os.Getenv("RIOS_TRACE_POS")

func trace(format string, args ...any) {
	if traceOn {
		fmt.Fprintf(os.Stderr, format+"\n", args...)
	}
}

// ---------------------------------------------------------------- 数值读数

// profile 是这一刻生效的那套数值：技能开着就是 `Active`，否则是顶层那套。
//
// 返回 nil = 用顶层字段（`spec.ATK` 那一族）。这样调用方写成
// `if p := op.profile(); p != nil { … } else { … }` 就能一眼看出
// "技能开着没有"，不需要另立一个布尔量（两个状态源必然有一天不一致）。
func (o *operator) profile() *Profile {
	if o.skillActive && o.spec.Active != nil {
		return o.spec.Active
	}
	return nil
}

// atk 是这名干员**这一刻**的攻击力面板（原版 `OperatorUnit.current_atk()`）。
//
// 全场光环那一段**必须加成、不能在技能面板上连乘**：原版写的是
// `self.atk * (1 + 技能增益 + … + aura_atk_pct)`——光环的贡献是
// `self.atk × aura_atk_pct`，底子是**不含技能增益**的那个数。
// 写成 `p.ATK * (1 + aura)` 会多出一项 `p.ATK × 技能增益 × aura`，
// 技能一开就对不上（本次的关卡里技能恒关，所以那个错会**一直藏着**）。
func (o *operator) atk() float64 {
	base := o.spec.ATK
	if p := o.profile(); p != nil {
		base = p.ATK
	}
	return base + o.spec.ATK*o.auraAtkPct
}

func (o *operator) defense() float64 {
	base := o.spec.DEF
	if p := o.profile(); p != nil {
		base = p.DEF
	}
	// 同 `atk()`：光环的底子是 `spec.DEF`，不是技能面板。
	return base + o.spec.DEF*o.auraDefPct
}

func (o *operator) res() float64 {
	if p := o.profile(); p != nil {
		return p.RES
	}
	return o.spec.RES
}

// dodgeVs 是这名干员针对某个伤害类型的闪避比例（原版
// `op.dodge_phys + op.talent_dodge_phys` 那一族）。
//
// 两项来源不同、生命周期也不同，所以规格里分开送：
//
//   - **技能给的**（`dodge_phys/arts`）只在技能开启期间有效，随 `Active` 那套走；
//   - **天赋给的常驻抵挡**（星熊「战术装甲」）跟着人走，整场不变。
//
// 真实伤害两类都不吃闪避（原版 `damage.py:144`）。
func (o *operator) dodgeVs(damageType string) float64 {
	skillDodge := 0.0
	if p := o.profile(); p != nil {
		if damageType == "MAGIC" {
			skillDodge = p.DodgeArts
		} else {
			skillDodge = p.DodgePhys
		}
	}
	talent := o.spec.TalentDodgePhys
	if damageType == "MAGIC" {
		talent = o.spec.TalentDodgeArts
	}
	return skillDodge + talent
}

func (o *operator) interval() float64 {
	if p := o.profile(); p != nil {
		return p.Interval
	}
	return o.spec.AttackInterval
}

func (o *operator) damageType() string {
	if p := o.profile(); p != nil {
		return p.DamageType
	}
	return o.spec.DamageType
}

func (o *operator) maxTarget() int {
	if p := o.profile(); p != nil {
		return p.MaxTarget
	}
	return 1
}

// atkScale / hitCount / finalHitScale 是"这一击怎么打"的三个数；
// 没有技能（或没开）时是 1 / 1 / 无。
func (o *operator) atkScale() float64 {
	if p := o.profile(); p != nil {
		return p.AtkScale
	}
	return 1.0
}

func (o *operator) hitCount() int {
	if p := o.profile(); p != nil && p.HitCount > 0 {
		return p.HitCount
	}
	return 1
}

// finalHitScale 的"有没有"看**指针是不是 nil**，不看数值——理由见 `Profile`
// 里那个字段的注释（`null` 会变成 0，而 0 倍率是一记 0 伤害）。
func (o *operator) finalHitScale() (float64, bool) {
	if p := o.profile(); p != nil && p.FinalHitScale != nil {
		return *p.FinalHitScale, true
	}
	return 0, false
}
