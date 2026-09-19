// sim.go：最小版本的战斗主循环（常规关卡：无装置、无召唤、无手动技能、
// 无位移与硬控）。
//
// ## 它的权威性从哪来
//
// 这一份**不是**权威实现——`ak_tactic/battle/sim.py` 才是。Go 版存在的唯一理由是
// 速度（HS-EX-4 一次解算 214 秒），所以它的每一步都必须能在原版里指出出处。
// 下面每个阶段都标了原版的行号区间；改这里之前先回去读那一段。
//
// ## 帧内顺序（与 `BattleSimulator.run` 逐条对齐）
//
//  0. 费用回复          （sim.py 1689-1692）
//  1. 部署              （1694-1695）
//  2. 出怪              （1753-1760）
//  3. 推进与计时器递减  （1767-1806）
//  4. 阻挡              （1846 → _update_blocking 2289）
//  6. 我方出手          （1870 → _operators_attack 2687）
//  7. 敌方出手          （1873 → _enemies_attack 2882）
//  8. 结算：击杀奖励与漏怪（1886 → _resolve 3720）
//
// 顺序不能乱，两条最要命的：
//
//   - **推进在阻挡之前**：反过来的话敌人会"穿过"干员那一格，跑到下一格才被拦下；
//   - **费用回复在部署之前**：放帧尾的话，部署看到的是上一帧的池子，恰好差一个
//     节拍——"刚好攒够"的那一手会被冤枉地判成付不起（原版 1683-1688 的正文里
//     记的就是这一条）。
package main

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"rios-sim/mech"
)

// : 与原版同源的两个常量（`unit.py` 27-40）。攻击间隔的下限与攻速下限一起用。
const (
	positionTol  = 0.35
	positionTol2 = positionTol * positionTol
)

type enemy struct {
	spec SpawnSpec

	hp        float64
	position  [2]float64
	progress  float64
	legIndex  int
	legU      float64
	offMap    bool
	blockedBy *operator

	//: 甲的监测态无敌：挨打掉 0 血，**但照旧会被索敌**——它会白吃干员的输出，
	//: 这正是它在场上改变胜负的方式（原版 `always_invincible`，由 `spec.Invincible`
	//: 起步、激活时由机制关掉）。
	invincible bool

	attackTimer float64
	attackPause float64
	hits        int
	leaked      bool
	leakTime    float64
	deathTime   float64
	costAwarded bool

	// ---- 重生（原版 `_reborn_tick`，帧序 3.4）
	//
	// 两件事共用这套状态：BOSS 的"多一条命"（`Reborn.*`）与怀黍离
	// 「瘴 / 鄙瘴」的**重生期充能**（`Reborning.*`）。原版把它们写在同一个
	// `pending_reborn` 分支里，所以这里也放在一起。
	//
	// ⚠ 等重生的（`rebornAt >= 0`）既不算活、也不算死：它不推路（帧序 3 的
	// 条件是 `alive()`）、不出手（帧序 7 同理）、**不进击杀数**（收尾结算里
	// 由 `pendingReborn()` 排除）。少排一条，判决就会多记一次击杀。
	rebornLeft     int
	rebornAt       float64 //: >= 0 = 倒下等重生；-1 = 不在窗口里
	rebornChargeAt float64
	rebornCharge   int
	rebornDefBase  float64 //: 防御力基准：充能加成每次都按它重算，不能累乘
	//: 重生期召唤的下一拍时刻（与 `spec.RebornSummons` 一一对应，-1 = 不排了）
	rebornSummonAt []float64

	// ---- 蜕皮（原版 `Passive_Hit.*`，「祟」的混沌形态）
	//
	//: 挨打次数（每满 `PhitCnt` 就消耗掉一层；原版 `phit_hits`）
	phitHits int
	//: 已经叠到的层数（上限 `PhitMaxStack`，到顶后整段不再发生）
	phitStacks int

	// ---- 明识形态（原版 `PassiveM2.*`，「祟」重生归来后的第二形态）
	pm2Active  bool
	pm2Applied bool //: 属性改写只做一次（反复乘会让攻击力指数衰减）
	pm2Clean   bool //: 当前是否处于"清水"
	//: 无敌到什么时候（原版 `invincible_until`；`take` 里读它）
	invincibleUntil float64
	//: 被这一只**标记**过的我方单位（原版 `marked_ops`，存的是身份不是下标）
	marked map[int]bool
	//: 移速乘区（原版 `haste_multiplier`）。明识形态会把"清水"状态折进它；
	//: 推进时乘上去（`advance` 与 `EnemyMoveSpeed` 两处必须同源）。
	haste float64
	//: 上一次打进 `RIOS_TRACE` 的移速（只为"变化即记一笔"用，不参与计算）。
	traceSpeed float64
	//: 【停顿】剩余秒数（原版 `sluggish_timer`）。
	//:
	//: ⚠ 它**不是**"只是记个数"：原版 `EnemyUnit.advance` 在 `sluggish_timer > 0`
	//: 时**整帧不移动**（与晕眩/束缚/待机并列的那一串 early return）。所以每中
	//: 一次挂停顿的攻击，敌人就少走 `秒数 × 移速` 格。怒潮凛冬的天赋让每一次
	//: 高台溅射都给 0.5 秒停顿——漏掉这一路，敌人每次多吃一发就多走 0.2 格，
	//: 累积到判决层面就是"漏怪"。
	sluggishTimer float64
	//: 冻结剩余秒数（原版 `freeze_timer` / `frozen`，unit.py:1015-1023）。
	//: 冻结与停顿**不是**一回事：停顿只是走得慢，冻结是**这一帧既不走也不出手**
	//: （`advance` 与 `_enemies_attack` 两处都拦）。目前唯一的来源是圣聆初雪的
	//: 「圣山的祝福」免死那一下——她攻击范围内的敌人被冻 `c2e_freeze` 秒。
	freezeTimer float64

	//: 造它的那个模拟器——挨打效果（蜕皮加病害）要问机制层，机制层挂在
	//: 模拟器上。之所以用反向指针而不是给 `take()` 加参数：`take()` 有多个
	//: 调用点（普攻、技能、机制伤害），**加参数就会有下一次忘记的地方**，
	//: 而忘记的症状是"这一族效果静默不生效"。指针在 `newEnemy` 里一次设好。
	sim *simCtx

	index int //: 出生顺序（同分排序用，等价于原版敌人列表的顺序）
}

func (e *enemy) alive() bool { return e.hp > 0 }

// cell 是原版 `EnemyUnit.cell()`：**四舍五入**到整数格（不是截断）。
//
// ⚠ 同一段机制里两种取格口径并存，抄的时候别互换：原版 `_pollute_around`
// 选圆心时，**没被挡**那一支走 `e.cell()`（四舍五入），**被挡**那一支走
// `int(blocked_by.position)`（截断）。两者在敌人走在格子中间时给出不同的格。
func (e *enemy) cell() (int, int) {
	return int(math.RoundToEven(e.position[0])), int(math.RoundToEven(e.position[1]))
}

// pendingReborn 是原版的 `e.pending_reborn`：倒下等待重生。
func (e *enemy) pendingReborn() bool { return e.rebornAt >= 0 }

// rebornCharge 是原版的 `e.reborn_charge`——重生期吸到的病害层数。它只在
// **重生窗口里**增长（原文「重生期间每0.5s」），重生完成即定住。
func (e *enemy) rebornChargeBonus() float64 {
	if e.rebornCharge == 0 || e.spec.RebornDamageMagic == 0 {
		return 0.0
	}
	return e.spec.ATK * e.spec.RebornDamageMagic * float64(e.rebornCharge)
}

// dodgeVs 是这只敌人针对某个伤害类型的闪避比例。
//
// **恒为 0**，与原版同值：原版 `sim.py:3921` 读 `target.dodge_phys +
// target.talent_dodge_phys`，而 `EnemyUnit.dodge_phys` 是个没有任何地方写过的
// 字段、敌人侧也没有天赋抵挡那一对字段。留着这个方法是为了让"这一路上有没有闪避"
// 这件事**有名字**——写成裸 0 会让下一个人以为这里漏了。
func (e *enemy) dodgeVs(string) float64 { return 0 }

// summonFrom 是**机制造出来的敌人**（天桩链的甲/乙/天标）。
//
// 与出怪表里的敌人共用同一个 `enemy` 结构，只有两点不同：
//
//  1. **没有路线**——给一条 `kind: "static"` 的腿。自缚的甲站在装置那一格，
//     乙在扑出去之前也站着，天标钉在干员脚下。`advance` 见到这条腿一步不走，
//     `reachedEnd` 也永远是假（腿没走完），于是它们既不会移动、也不会被判成漏怪。
//  2. **不进 `verdict` 的"这一关有多少敌人"**——`spawns_placed/spawns_total`
//     只数出怪表（原版也如此：那三个数是 `_spawn_cursor` 与 `len(self._spawns)`）。
func (c *simCtx) Summon(template json.RawMessage, cell [2]float64) int {
	var spec SpawnSpec
	if err := json.Unmarshal(template, &spec); err != nil {
		// 模板是 Python 侧生成的，解不开说明两边对不上——静默造一个空单位
		// 比造不出来更糟（那会变成场上一个 0 血的幽灵）。
		panic(fmt.Sprintf("机制递来的召唤模板解不开：%v", err))
	}
	spec.Legs = []LegSpec{{Kind: "static", Points: [][2]float64{cell}}}
	e := newEnemy(spec, len(*c.enemies), cell, c)
	*c.enemies = append(*c.enemies, e)
	return e.index
}

// newEnemy 是**所有**敌人生成的唯一入口（出怪表与机制召唤共用）。
//
// 为什么必须只有一个：敌人身上有一批"初始化不变量"，它们的零值**不是**默认值——
// `rebornAt`/`rebornChargeAt` 必须是 -1（0 会被 `pendingReborn()` 读成"正在等
// 重生"，于是这一只在生成的那一帧就被按 `reborn_hp_ratio` 重置了 hp、清空了
// `blockedBy`，还多记一笔重生事件）；`deathTime` 必须是 -1（0 会被读成"在 0 秒
// 就阵亡了"）。
//
// 召唤路径曾经自己拼 `&enemy{}`，恰好漏掉这三个。判决当时没变，但那是运气：
// 甲被"复活"过一次、刚贴上来的阻挡被清掉过一次，只是那几帧里没人受影响。
// 这一类缺口不会自己报错，只会偶尔改一个判决——所以把口子合成一个。
func newEnemy(spec SpawnSpec, index int, position [2]float64, c *simCtx) *enemy {
	e := &enemy{
		spec:       spec,
		hp:         spec.HP,
		position:   position,
		index:      index,
		invincible: spec.Invincible,
		deathTime:  -1.0,
		sim:        c,
		// 重生：窗口从 -1 起步（不在窗口里）；防御力基准按原版在
		// `_build_enemy` 里取一次（`sim.py:1663`）——充能的防御加成按它重算，
		// 二次重生时不会把上次的加成再乘一遍。
		rebornLeft:      spec.RebornLeft,
		rebornAt:        -1.0,
		rebornChargeAt:  -1.0,
		rebornDefBase:   spec.DEF,
		invincibleUntil: -1.0,
		haste:           1.0,
		traceSpeed:      -1.0,
	}
	if n := len(spec.RebornSummons); n > 0 {
		// 原版 `_build_enemy` 就给每只排好这一列（-1 = 不在窗口里，不排拍）
		e.rebornSummonAt = make([]float64, n)
		for i := range e.rebornSummonAt {
			e.rebornSummonAt[i] = -1.0
		}
	}
	return e
}

func (e *enemy) reachedEnd() bool {
	return e.legIndex >= len(e.spec.Legs)
}

// legLength 是一条走段的总长（原版 `stage.map.path_length(path)`：逐段直线
// 距离之和）。召唤物要靠它把"还剩几格"换算成时间。
func legLength(pts [][2]float64) float64 {
	total := 0.0
	for i := 1; i < len(pts); i++ {
		dx := pts[i][0] - pts[i-1][0]
		dy := pts[i][1] - pts[i-1][1]
		total += math.Sqrt(dx*dx + dy*dy)
	}
	return total
}

type operator struct {
	spec OperatorSpec

	hp          float64
	cell        [2]float64
	blocking    []*enemy
	attackTimer float64
	retreated   bool
	leftAt      float64
	deathTime   float64
	damageTaken float64
	//: 造它的那个模拟器。与敌人同款的反向指针：受伤入账要写一条"阵亡"留痕
	//: （时刻＋累计承伤），而 `take()` 有五个调用点——给它加参数就迟早会漏一个。
	sim *simCtx
	//: 阵亡痕迹是否已经写过（`take` 与机制的直伤两条路都要过 `hurt`）。
	deathLogged bool
	slot        int //: 列表下标 = 部署顺序（敌人挑"最后部署的"要看它）
	//: **这一次部署**的身份号（每次部署递增）。原版每次落地都是新的
	//: `OperatorUnit` 对象，明识形态的"标记退场"记的是对象身份；Go 侧一名
	//: 干员复用同一个结构体，用这个号代替——"撤了再下同一个人"因此不算同一个。
	deploySeq int
	//: 「圣山的祝福」的免死**这一局用过没有**（原版 `blessing_used`，
	//: unit.py:492：一次部署只免一回）。
	blessingUsed bool
	//: 欠下的那次"攻击范围内全体敌人冻结"的秒数（原版 `blessing_freeze`，
	//: unit.py:495）。免死发生在掉血那一刻，而那里够不着地图，所以先记在这里、
	//: 由下一帧的 `blessingTick` 兑现——差一帧，与原版同。
	blessingFreeze float64

	// ---- 技能状态（`skill.go`；没有技能槽时这几个字段一直不动）
	//:
	//: 每次部署都**从零起**（原版每次部署都是一个全新的 `OperatorUnit` 对象，
	//: 这里复用对象，所以得自己清）：见 `runSim` 的部署那一段。
	sp          float64 //: 当前技力
	spCharges   int     //: 这一局开过几次（`once_per_battle` 与"第二次及以后"要看它）
	skillActive bool
	skillTimer  float64
	ammoLeft    int
	skillReq    bool //: 手动开技能的请求，`skillTick` 里消费
	autoSkill   bool //: 来自**这一次部署**的 `DeploySpec.AutoSkill`
}

func (o *operator) alive() bool { return o.hp > 0 && !o.retreated }

// heal 是原版 `Combatant.heal`：回复**夹在生命上限**，返回**实际回复量**
// （不是治疗量）。返回值要拿去记日志与累计，所以不能只改 hp 就完事。
//
// ⚠ 这是干员回血的**唯一入口**（与 `hurt` 对称）。受击有 `OPDMG` 痕迹而回血
// 什么都没有的时候，"Go 的人倒得更早但累计承伤反而更少"这种差异只能瞎猜：
// 承伤少而倒得早，要么是治疗没走到，要么是有一路伤害不留痕。
func (o *operator) heal(amount float64) float64 {
	before := o.hp
	o.hp = math.Min(o.maxHP(), o.hp+math.Max(0, amount))
	got := o.hp - before
	if traceOn && o.sim != nil && got > 0 {
		trace("OPHEAL t=%.4f op=%s want=%.3f got=%.3f hp=%.3f max=%.3f",
			*o.sim.time, o.spec.Name, amount, got, o.hp, o.maxHP())
	}
	return got
}

// canBlock 对应 `OperatorUnit.can_block`：飞行单位挡不住，阻挡位满也挡不住。
func (o *operator) canBlock(e *enemy) bool {
	if e.spec.IsFlying {
		return false
	}
	return o.spec.BlockCnt > 0 && len(o.blocking) < o.spec.BlockCnt
}

// runSim 把一份规格推成判决。
func runSim(spec *Spec) (*Verdict, error) {
	if len(spec.Unsupported) > 0 {
		return nil, fmt.Errorf("这一局用到了最小版本还没覆盖的机制，不跑：%v",
			spec.Unsupported)
	}
	if spec.FPS <= 0 {
		return nil, fmt.Errorf("fps 必须是正整数，收到 %d", spec.FPS)
	}
	// **关卡特有机制按需取用**（mech 包）：点名的名字取不到就整场拒跑，
	// 见 `mech.Load` 与 wire.go 里那段注释。规格按名字一起交出去。
	mechanisms, err := mech.Load(spec.MechConfig, spec.Mechanisms...)
	if err != nil {
		return nil, err
	}
	start := time.Now()

	dt := 1.0 / float64(spec.FPS)
	cost := spec.CostInit
	costTimer := 0.0
	life := spec.Life

	deploys := append([]DeploySpec(nil), spec.Deploys...)
	sort.SliceStable(deploys, func(i, j int) bool { return deploys[i].Time < deploys[j].Time })
	skillUses := append([]SkillUseSpec(nil), spec.SkillUses...)
	sort.SliceStable(skillUses, func(i, j int) bool { return skillUses[i].Time < skillUses[j].Time })

	var ops []*operator
	var enemies []*enemy
	onField := map[string]*operator{} //: char_id → 当前在场的那一个（含已阵亡的）
	lastLeft := map[string]float64{}  //: char_id → 最近一次离场时刻

	cursor := 0
	spawnsPlaced := 0
	verdict := &Verdict{
		Life:           life,
		SpawnsTotal:    len(spec.Spawns),
		LeakEvents:     [][3]any{},
		DeployRejected: [][3]any{},
		CostDenied:     [][4]any{},
		Events:         []Event{},
	}
	// 每个单位对象只建一次，重复部署时复用（血量在那一刻重置）
	objs := make([]*operator, len(spec.Operators))
	for i := range spec.Operators {
		os := spec.Operators[i]
		objs[i] = &operator{spec: os, leftAt: -1,
			cell: [2]float64{float64(os.Cell[0]), float64(os.Cell[1])}}
	}

	t := 0.0
	frameNo := 0
	// 机制看到的世界：**读**用只读视图，**写**一律走效果请求，由主循环施加
	// （帧内顺序的权威只有一处）。空机制时这一层不产生任何行为——`Empty()` 直接跳。
	ctx := &simCtx{spec: spec, objs: &objs, enemies: &enemies, mechanisms: mechanisms,
		time: &t, frame: &frameNo, verdict: verdict}
	// 干员在这里才拿得到 ctx（对象数组比 ctx 先建），所以回填一次。
	for _, o := range objs {
		if o != nil {
			o.sim = ctx
		}
	}
	if err := mechanisms.Start(ctx); err != nil {
		return nil, err
	}
	won := false
	for t < spec.MaxTime {
		// ---- 0. 费用回复（1689-1692）
		costTimer += dt
		if costTimer >= spec.CostTime && spec.CostTime > 0 {
			costTimer -= spec.CostTime
			cost = math.Min(spec.CostMax, cost+1.0)
		}

		// ---- 1. 部署（1694-1695 → _do_deploy 2117）
		for len(deploys) > 0 && deploys[0].Time <= t {
			d := deploys[0]
			deploys = deploys[1:]
			if d.Index < 0 || d.Index >= len(objs) {
				return nil, fmt.Errorf("部署时刻 %.3fs 的 index=%d 越界（共 %d 个干员）",
					d.Time, d.Index, len(objs))
			}
			op := objs[d.Index]
			// ① 同一干员不能同时在场上（`_can_deploy_again` 2096-2101）
			if cur, ok := onField[d.CharID]; ok && cur.alive() {
				verdict.DeployRejected = append(verdict.DeployRejected,
					[3]any{t, op.spec.Name, "同一干员已在场"})
				continue
			}
			// ② 再部署冷却（2102-2108）：只看**同一个 char_id**
			if last, ok := lastLeft[d.CharID]; ok &&
				t < last+op.spec.RedeployTime {
				verdict.DeployRejected = append(verdict.DeployRejected,
					[3]any{t, op.spec.Name, "再部署冷却中"})
				continue
			}
			// ③ 付得起吗（`_affordable` 2064-2077）
			if float64(d.Cost) > cost {
				verdict.CostDenied = append(verdict.CostDenied,
					[4]any{t, op.spec.Name, d.Cost, cost})
				continue
			}
			op.hp = op.spec.MaxHP
			op.blocking = nil
			op.attackTimer = 0
			op.damageTaken = 0
			op.retreated = false
			op.leftAt = -1
			// 这一次部署的**身份号**：原版每次部署都是全新的 OperatorUnit 对象，
			// 明识形态的"标记"记的是对象身份；Go 侧一名干员复用同一个结构体，
			// 于是用这个号代替对象身份——否则"撤了再下同一个人"会被误认成同一次
			// 部署，标记退场给的病害就永远算不对。
			op.deploySeq = ctx.nextDeploySeq()
			// 技能状态从零起（等价于原版"每次部署一个全新的 OperatorUnit"）：
			// 技力回到 `init_sp`，开启次数归零，上一局的持续/弹药不带到这一局。
			op.autoSkill = d.AutoSkill
			op.spCharges = 0
			op.skillReq = false
			op.ammoLeft = 0
			op.skillTimer = 0
			op.skillActive = false
			op.sp = 0
			if sk := op.spec.Skill; sk != nil && !sk.Passive {
				op.sp = sk.InitSP
			}
			ops = append(ops, op)
			onField[d.CharID] = op
			cost = math.Max(0, cost-float64(d.Cost))
			verdict.Events = append(verdict.Events,
				Event{T: t, Kind: "deploy", Who: op.spec.Name})
		}

		// ---- 1b. 手动开技能的请求（原版 2006-2009，紧随部署之后）
		//
		// 与原版同一套判据：**按格子找人**，找不到就什么也不发生。这里只记请求，
		// 真正开不开在下面的技能阶段判（那一刻的技力说了算）。
		//
		// 时间对不齐（离任何一帧都超过 dt/2）的请求**丢掉**——原版也是这么做的
		// （它每帧筛 `abs(s.time - t) < dt/2`），丢掉时要往前走，否则它会一直
		// 卡在队头把后面的请求全堵住。
		for len(skillUses) > 0 && skillUses[0].Time <= t+dt/2 {
			u := skillUses[0]
			skillUses = skillUses[1:]
			if math.Abs(u.Time-t) < dt/2 {
				useSkill(ops, u.Cell)
			}
		}

		// ---- 2. 出怪（1753-1760）
		for cursor < len(spec.Spawns) && spec.Spawns[cursor].Time <= t {
			sp := spec.Spawns[cursor]
			e := newEnemy(sp, cursor, [2]float64{}, ctx)
			e.legIndex = 0
			// 起点 = **第一段有点的腿**的第一个点。
			//
			// 原版 `_build_enemy` 给的是 `position=pts[0] if pts else (0,0)`，
			// 而 `pts` 是拼接后的整条路线——开头的待命段（`kind: wait`）**没有点**，
			// 所以原版的起点是**待命段之后那条走段的首点**，也就是出生点。
			//
			// 这里原来只看 `Legs[0].Points`，遇到"待命打头"的出怪（怀黍离 HS-EX-8
			// 的头三只就是）就取不到，位置留在 (0, 0)：那几只在待命期间**不在
			// 出生点、进不了任何人的范围**，白挨一段时间的打没了。实测差三次高台
			// 溅射、604.6 点伤害，判决从"守住"变成"漏怪"。
			for _, leg := range sp.Legs {
				if len(leg.Points) > 0 {
					e.position = leg.Points[0]
					break
				}
			}
			enemies = append(enemies, e)
			verdict.Events = append(verdict.Events,
				Event{T: t, Kind: "spawn", Who: sp.Name})
			cursor++
			spawnsPlaced++
		}

		// ---- 3. 推进与计时器递减（1767-1806）
		//
		// ⚠ **先递减、再判能不能走**，三根计时器（出手停帧 / 停顿 / 冻结）都是。
		// 原版这一段（`sim.py:2720-2761`）就是"先把所有时限状态各减一次 `dt`，
		// 然后 `e.advance(dt, ...)`"，而 `advance()` 里读到的是**减过之后**的值。
		//
		// 顺序反过来（先判后减）症状是"每段停顿/冻结都多挡一帧"：停帧设 0.5 秒
		// 本该挡 15 帧，反着写会挡到 16 帧——**不报错、只有坐标看得出**。HS-EX-8
		// 单手作业上它与原版整整差一帧的位移，就是这么来的（停帧相位差一帧，
		// 见 `docs/` 里那条对拍水位）。
		for _, e := range enemies {
			if e.attackPause > 0 {
				e.attackPause = math.Max(0.0, e.attackPause-dt)
			}
			if e.sluggishTimer > 0 {
				e.sluggishTimer = math.Max(0.0, e.sluggishTimer-dt)
			}
			if e.freezeTimer > 0 {
				e.freezeTimer = math.Max(0.0, e.freezeTimer-dt)
			}
			if e.alive() && !e.leaked && !e.offMap && e.blockedBy == nil &&
				e.attackPause <= 0 && e.sluggishTimer <= 0 && e.freezeTimer <= 0 {
				// 关卡特有机制可以改这一只的推进速度乘区（如田地/阻流阀）；
				// 没挂机制时 `speedFor` 恒为 1.0，与最小版本逐位相同。
				advance(e, dt, spec.SpeedScale*ctx.speedFor(e.index))
			}
			// 逐帧坐标（按名字门控，见 `tracePosName`）。`blocked/sluggish/freeze`
			// 一起记：坐标不动有三种截然不同的原因，不写清楚就得分不出来。
			if traceOn && tracePosName != "" && e.spec.Name == tracePosName {
				// ⚠ `x`/`legu` 打到 **7 位**：一帧的滴漏量是 3e-5 量级（帧长
				// 0.0333 与 1/30 之差），4 位精度下前半程完全看不出来，
				// 要等几百帧累积到 1e-4 才显形——那就成了"突然差一格"。
				trace("POS t=%.4f idx=%d name=%s x=%.7f y=%.7f hp=%.1f blocked=%t pause=%.2f sluggish=%.2f freeze=%.2f leg=%d legu=%.7f",
					*ctx.time, e.index, e.spec.Name, e.position[0], e.position[1], e.hp,
					e.blockedBy != nil, e.attackPause, e.sluggishTimer, e.freezeTimer,
					e.legIndex, e.legU)
			}
		}

		// ---- 3.4 重生结算（原版 2264 → `_reborn_tick`）
		//
		// 位置照原版：**推进之后、机制（3.5）之前**。怀黍离的重生期充能要读
		// 敌人所在格的病害值并从那里扣走，所以它必须排在田地那一步前面。
		//
		// 两件事共用这个窗口：BOSS 的"多一条命"，与「瘴 / 鄙瘴」的重生期充能。
		for _, e := range enemies {
			if e.leaked {
				continue
			}
			if e.pendingReborn() {
				// 重生期召唤：窗口内每 `Interval` 秒在**自己脚下**召唤 `Count` 个。
				// 排在充能之前（原版 4176-4184 在 4188 那段之前），
				// 所以同一帧既召唤又充能是可能的。
				for i := range e.rebornSummonAt {
					for e.rebornSummonAt[i] >= 0 && t >= e.rebornSummonAt[i] {
						// 间隔非正就是"没有这一拍"，先退出——否则 while 不收敛
						if e.spec.RebornSummons[i].Interval <= 0 {
							e.rebornSummonAt[i] = -1.0
							break
						}
						e.rebornSummonAt[i] += e.spec.RebornSummons[i].Interval
						ctx.summonReborn(e, i, t, verdict)
					}
				}

				// 充能：窗口内按 interval 逐个结算。用 while 而不是 if——
				// fps 高时不会漏，fps=1 的粗扫时又会一次补上欠下的所有拍。
				for e.rebornChargeAt >= 0 && t >= e.rebornChargeAt {
					// 间隔非正就是"没有充能节拍"，先退出——否则
					// `rebornChargeAt` 会原地踏步，这个 while 永不收敛。
					if e.spec.RebornInterval <= 0 {
						break
					}
					e.rebornChargeAt += e.spec.RebornInterval
					// 原文把"降低病害值"与"获得1层充能"写在同一个条件里：
					// 本格病害值 > 0 才**同时**发生两件事，否则一件都不发生。
					// `DrainPollution` 在 ≤0 时返回 0，正好当这个条件用。
					//
					// ⚠ 必须用四舍五入到整数格的坐标（原版 `e.cell()`）——病害值
					// 的键是**整数格**，传浮点进去不会报错，只是永远取不到，
					// 于是充能永远是 0 层、整条机制静默失效。
					cell := [2]int{int(math.RoundToEven(e.position[0])),
						int(math.RoundToEven(e.position[1]))}
					if moved := mechanisms.DrainPollution(cell, e.spec.RebornPollut); moved > 0 {
						e.rebornCharge++
					}
				}
				if t >= e.rebornAt {
					e.rebornAt = -1.0
					e.rebornChargeAt = -1.0
					// 召唤的排期随窗口一起清掉（原版 4214）
					for i := range e.rebornSummonAt {
						e.rebornSummonAt[i] = -1.0
					}
					e.hp = e.spec.HP * e.spec.RebornHPRatio
					// 重生后：防御力 +(def_add × 层数)%。从**基准**重算，
					// 免得二次重生时把上一次的加成再乘一遍。
					if e.rebornCharge > 0 && e.spec.RebornDefAdd != 0 {
						e.spec.DEF = e.rebornDefBase *
							(1.0 + e.spec.RebornDefAdd*float64(e.rebornCharge))
					}
					e.blockedBy = nil
					e.deathTime = -1.0
					// 归来即入明识形态（原版 4122 `_enter_pm2`）
					ctx.enterPm2(e, t)
					verdict.Events = append(verdict.Events,
						Event{T: t, Kind: "reborn", Who: e.spec.Name})
				}
			} else if e.hp <= 0 && e.rebornLeft > 0 {
				e.rebornLeft--
				e.rebornAt = t + e.spec.RebornDelay
				// 充能窗口与重生窗口同长：进来就排第一拍
				if e.spec.RebornInterval > 0 {
					e.rebornChargeAt = t + e.spec.RebornInterval
				} else {
					e.rebornChargeAt = -1.0
				}
				// 召唤窗口同样与重生窗口同长：进来给每一"拍"排上第一拍
				for i := range e.rebornSummonAt {
					if e.spec.RebornSummons[i].Interval > 0 {
						e.rebornSummonAt[i] = t + e.spec.RebornSummons[i].Interval
					}
				}
			}
		}

		// ---- 3.5 关卡特有机制：**推进之后、阻挡之前**（原版 2164）
		//
		// 位置是照原版逐行核出来的，不是随手挑的：怀黍离的田地/病害值要在这里算
		// "这一秒站在田地上的干员吃多少环境伤害、回多少血"（原版 `_environment_tick`），
		// 而原版把它排在**阻挡与出手之前**。挪到帧末会让"这一帧刚被阻挡的敌人把
		// 干员打退场"与"这一帧的环境伤害"的先后关系反过来——每一秒都差一次。
		//
		// 空机制整段跳过，通用关卡一帧都不多花。
		//
		// `blessingTick` 排在这里是照原版 3.5（`sim.py:2775`，紧跟 `_snow_tick`
		// 之后、`_qi_tick` 之前）：免死欠下的那次范围冻结要在**本帧出手之前**兑现，
		// 否则被冻的敌人还会多打一帧。
		blessingTick(ops, enemies, t, verdict)
		if !mechanisms.Empty() {
			mechanisms.EnvTick(ctx, dt)
			// ---- 3.9 天桩链（原版 3884，紧跟 `_device_tick` 之后）
			//
			// 和 3.7 同一处"推进之后、阻挡之前"。甲监测的是**这一帧已经被环境
			// 算过**的病害值，乙扑咬与天标每秒伤害又要与本帧的阻挡/出手对齐——
			// 挪到帧末会让天标的每秒伤害晚一整帧到账。
			mechanisms.PileTick(ctx, dt)
		}

		// ---- 4. 阻挡（1846 → 2289）
		updateBlocking(ops, enemies)

		// ---- 5. 技能（原版 2156，**阻挡之后、我方出手之前**）
		//
		// 位置是定的：刚攒满技力的那一帧就得算数，晚一帧会让每次开技都慢一个 dt。
		skillTick(ops, dt, t, spec, &cost, verdict)

		// ---- 6. 我方出手（1870 → 2687）
		operatorsAttack(ops, enemies, dt, t, spec, verdict)

		// ---- 7. 敌方出手（1873 → 2882）
		enemiesAttack(ops, enemies, dt, t, spec, verdict)

		// ---- 7.2 关卡特有机制：敌方**技能出手**（原版 2221 之前那一处，帧序 7.2）
		//
		// 排在普攻之后、被击倒效果之前：技能出手自己会占住敌人的动作时间，
		// 也可能正好把人打死——那个"打死"要到 7.5 才结算。
		if !mechanisms.Empty() {
			mechanisms.AttackTick(ctx, dt)
		}

		// ---- 7.5 关卡特有机制：**两次出手之后、结算之前**（原版 2221）
		//
		// 这一处专门处理"这一帧谁把谁打倒了"之后的一次性效果（怀黍离：被击倒的
		// 敌人给田地加病害 → 记入【缓存】）。排在这里而不是帧末，理由写在原版
		// 那一行上：出手之后才看得见"谁倒下了"，结算之前才不会漏掉这一次效果。
		if !mechanisms.Empty() {
			mechanisms.PostAttack(ctx, dt)
		}

		// ---- 7.6 明识形态（原版 `_enemy_mech_tick` 里紧跟机制之后那一段，4008）
		//
		// 「祟」归来的第二形态逐帧要判两件事：**清水**（站在病害值 0 的田地、
		// 或在清澈泵站范围内 → 防御与移速都要改）与**标记退场**（被它标记过的
		// 干员离场时给脚下加病害）。放在 7.5 之后、结算之前，与原版同序。
		ctx.pm2Tick(ctx, t, ops)

		// ---- 8. 结算（1886 → 3720）
		resolve(enemies, &cost, &life, t, verdict)
		// 离场时刻（1743-1750）：阵亡统一在这里记一次，再部署冷却靠它
		for _, op := range ops {
			if op.leftAt < 0 && (op.retreated || op.hp <= 0) {
				op.leftAt = t
				lastLeft[op.spec.CharID] = t
			}
		}
		if life <= 0 {
			won = false
			break
		}
		if cursor >= len(spec.Spawns) && !anyActive(enemies) {
			won = true
			break
		}
		// ---- 9. 关卡特有机制（`mech` 包）：**帧末、t += dt 之前**
		//
		// 位置是定的：机制看到的是一个已经结算完的帧（伤害、击杀、漏怪都记过了），
		// 它自己造成的影响落在下一帧。放到帧中间会让"谁先谁后"变成机制之间的事，
		// 而机制之间**不许有顺序**——它们各自只跟主循环打交道。
		//
		// 空机制（通用关卡）整段跳过，一帧都不多花。
		if !mechanisms.Empty() {
			mechanisms.Frame(ctx, dt)
		}
		frameNo++
		t += dt
	}

	verdict.Won = won
	verdict.Elapsed = t
	verdict.Life = life
	verdict.SpawnsPlaced = spawnsPlaced
	verdict.Deployed = len(ops)
	verdict.TimedOut = !won && life > 0
	for _, e := range enemies {
		// 等重生的既不算活也不算死（原版收尾结算里同样排除 `pending_reborn`）：
		// 少排这一条，一只"重生过一次"的敌人会被记成两次击杀。
		if !e.alive() && !e.leaked && !e.pendingReborn() {
			verdict.Kills++
		}
		if e.leaked {
			verdict.Leaks++
		}
	}
	for _, o := range ops {
		if !o.alive() && !o.retreated {
			verdict.OperatorDeaths++
		}
	}
	verdict.SimMS = float64(time.Since(start).Microseconds()) / 1000.0
	// 机制状态进判决，供对拍逐项比（判决本身不读它，见 `mech.Snapshotter`）。
	verdict.MechState = mechanisms.States()
	return verdict, nil
}

// ================================================================ 机制层的接口实现

// simCtx 把主循环的状态借给 `mech` 包。
//
// 指针字段是**故意的**：`ops`/`enemies` 在循环里会被 append 重新分配，视图必须
// 每次现取，不能在第一帧把切片头存下来（否则机制看到的是一个冻结的、越用越旧的
// 列表——这类错只在"敌人变多的那一刻"才现形）。
type simCtx struct {
	spec       *Spec
	objs       *[]*operator
	enemies    *[]*enemy
	mechanisms *mech.Set
	time       *float64
	frame      *int
	verdict    *Verdict
	//: 部署身份号的发号器（见 `operator.deploySeq`）
	deploySeq int

	//: 本场被请求的推进速度乘区（**出怪顺序下标** → 乘区）。机制只提请求，
	//: 主循环在推进那一步施加。没被请求过的敌人乘区是 1.0。
	//:
	//: 语义是"一直有效，直到改口"（不是"只管一帧"）：田地那种按"敌人此刻站在
	//: 哪"生效的机制每帧重报一次即可；而"脱战就恢复"的实现者也只需在自己认
	//: 为恢复时报回 1.0，不必依赖主循环替它清理。
	speedReq map[int]float64
}

func (c *simCtx) Time() float64 { return *c.time }
func (c *simCtx) Frame() int    { return *c.frame }
func (c *simCtx) DT() float64   { return 1.0 / float64(c.spec.FPS) }

// speedFor 是某一只敌人此刻的速度乘区（没请求过就是 1.0）。
func (c *simCtx) speedFor(index int) float64 {
	if c.speedReq == nil {
		return 1.0
	}
	if s, ok := c.speedReq[index]; ok {
		return s
	}
	return 1.0
}

// Operators 列的是**`Spec.Operators` 里的每一个单位对象**（不在场的也在，`Alive`
// 为 false）。用对象下标而不是"在场列表的下标"：后者随部署顺序增长，机制拿到的
// 编号会随着场上人数变化而漂。
func (c *simCtx) Operators() []mech.OpView {
	out := make([]mech.OpView, 0, len(*c.objs))
	for i, op := range *c.objs {
		out = append(out, mech.OpView{
			Index: i, CharID: op.spec.CharID, Name: op.spec.Name,
			Cell: [2]int{int(op.cell[0]), int(op.cell[1])}, HP: op.hp,
			MaxHP: op.spec.MaxHP,
			Alive: op.alive(), BlockCnt: op.spec.BlockCnt,
		})
	}
	return out
}

func (c *simCtx) Enemies() []mech.EnemyView {
	out := make([]mech.EnemyView, 0, len(*c.enemies))
	for _, e := range *c.enemies {
		ex, ey := e.cell()
		v := mech.EnemyView{
			Index: e.index, Name: e.spec.Name, Position: e.position,
			Cell: [2]int{ex, ey},
			HP:   e.hp, Alive: e.alive(), Blocked: e.blockedBy != nil,
			Leaked: e.leaked, OffMap: e.offMap, Frozen: e.freezeTimer > 0,
			PollutOnDeath: e.spec.PassivePollut, PollutRadius: e.spec.PassiveRadius,
			ATK: e.spec.ATK, AttackInterval: e.spec.Interval,
			SkillAtkScalePhys:  e.spec.SkillAtkScalePhys,
			SkillAtkScaleMagic: e.spec.SkillAtkScaleMagic,
			SkillAtkInit:       e.spec.SkillAtkInit,
			SkillAtkInterval:   e.spec.SkillAtkInterval,
			SkillAtkCross:      e.spec.SkillAtkCross,
			SkillAtkPollut:     e.spec.SkillAtkPollut,
			SkillAtkGroundOnly: e.spec.SkillAtkGroundOnly,
		}
		// 原版 `_pollute_around` 读的是 `e.blocked_by is not None and
		// e.blocked_by.alive`——**活着**的阻挡者才算数（挡它的那位这一帧刚倒，
		// 圆心就该落回敌人自己那一格）。
		if b := e.blockedBy; b != nil && b.alive() {
			v.HasBlocker = true
			v.BlockerCell = [2]int{int(b.cell[0]), int(b.cell[1])}
		}
		out = append(out, v)
	}
	return out
}

// DamageOperator 施加机制请求的伤害。
//
// **按单位对象下标**取人（与 `Operators()` 的 `Index` 同一套编号，也就是
// `DeploySpec.Index`）：同一位干员的不同次部署是不同的对象，所以"扣血"扣的一定是
// 机制想扣的那一个。
func (c *simCtx) DamageOperator(index int, raw float64, trueDamage bool) {
	objs := *c.objs
	if index < 0 || index >= len(objs) {
		return
	}
	op := objs[index]
	if !op.alive() {
		return
	}
	// 真伤不吃防御与法抗；否则按**物理**口径扣（机制自己说要哪种，这里不猜）。
	dealt := raw
	if !trueDamage {
		dealt = math.Max(raw-op.spec.DEF, raw*0.05)
	}
	op.hurt(dealt)
}

// HealOperator 施加机制请求的回血。
//
// 与"负伤害"不是一回事：回血不吃减伤、也不触发受击类效果，上限是这名干员的
// 最大生命（`unit.py:111` 的 `Combatant.heal`）。怀黍离的田地病害值为 0 时
// 每秒走的就是这一条。
func (c *simCtx) HealOperator(index int, amount float64) {
	objs := *c.objs
	if index < 0 || index >= len(objs) {
		return
	}
	op := objs[index]
	if !op.alive() || amount <= 0 {
		return
	}
	// 走唯一的回血入口（`operator.heal`），否则这条路上的回血不留痕迹、
	// 上限也读不到技能期间的那个（见 `heal` 与 `maxHP` 的说明）。
	op.heal(amount)
}

func (c *simCtx) ScaleEnemySpeed(index int, scale float64) {
	if c.speedReq == nil {
		c.speedReq = map[int]float64{}
	}
	c.speedReq[index] = scale
}

// HitOperator 施加机制发起的一次**分类型**伤害（原版 `resolve_damage` 那一路）。
//
// 与 `DamageOperator` 的分工：那个是真伤（田地每秒伤害就不吃减伤），这个要先过
// 这名干员**这一刻**的防御/法抗/闪避与 5% 保底——那些数只有主循环有，机制不该
// 自己抄一份（抄了就会随技能开关而漂）。受击回技力也在这里补上，与主循环自己
// 出手时共用 `spOnHit`。
func (c *simCtx) HitOperator(index int, raw float64, damageType string) float64 {
	objs := *c.objs
	if index < 0 || index >= len(objs) {
		return 0
	}
	op := objs[index]
	if !op.alive() {
		return 0
	}
	dealt := op.take(resolveDamage(raw, damageType, 1.0,
		op.defense(), op.res(), op.dodgeVs(damageType)))
	if traceOn {
		// 机制打干员的**唯一**入口（含怀黍离技能「污」与全场总攻击装置）。
		trace("HITOP t=%.4f op=%s raw=%.3f type=%s dealt=%.3f",
			*c.time, op.spec.Name, raw, damageType, dealt)
	}
	spOnHit(op, dealt)
	return dealt
}

// PauseEnemy 把这一只敌人的动作停顿推到一个下限（原版
// `e.attack_pause = max(e.attack_pause, self.enemy_windup)`）。
func (c *simCtx) PauseEnemy(index int, seconds float64) {
	for _, e := range *c.enemies {
		if e.index == index {
			e.attackPause = math.Max(e.attackPause, seconds)
			return
		}
	}
}

// enemyAt 按**出怪顺序下标**取对象（机制递过来的下标就是它）。
func (c *simCtx) enemyAt(index int) *enemy {
	for _, e := range *c.enemies {
		if e.index == index {
			return e
		}
	}
	return nil
}

// EnemyHP / EnemyMaxHP / SetEnemyHP —— 天桩链的**直接写血**通道。
//
// ⚠ 这里刻意**不走 `take`**：原版那三处（甲监测重设生命、激活自伤、乙/天标自毁）
// 全是 `e.hp = ...` 的直写，既不计入"我方造成的伤害"，也不该触发任何受击类效果。
// 用 `take` 会把它们记成战果——那是"看不出错"的那类差别（判决里只差一个数）。
func (c *simCtx) EnemyHP(index int) float64 {
	if e := c.enemyAt(index); e != nil {
		return e.hp
	}
	return 0
}

func (c *simCtx) EnemyMaxHP(index int) float64 {
	if e := c.enemyAt(index); e != nil {
		return e.spec.HP
	}
	return 0
}

func (c *simCtx) SetEnemyHP(index int, hp float64) {
	if e := c.enemyAt(index); e != nil {
		if hp < 0 {
			hp = 0
		}
		e.hp = hp
	}
}

func (c *simCtx) EnemyPosition(index int) [2]float64 {
	if e := c.enemyAt(index); e != nil {
		return e.position
	}
	return [2]float64{}
}

func (c *simCtx) SetEnemyPosition(index int, position [2]float64) {
	if e := c.enemyAt(index); e != nil {
		e.position = position
	}
}

// SetEnemyRoute 把一只敌人的走位换成一条新的折线（原版 `e.route = [...]` 之后
// 交给普通推进；`e.progress = 0` 重新从这条线的头开始量）。
//
// ⚠ 走完**就是漏怪**：`advance` 把腿走完 → `reachedEnd` 成立 → 第 8 步结算扣命。
// 乙的"扑向干员"用的正是这条路，所以它可以自己飞到目标格（贴到 0.5 之内时机
// 制再把它钉住），也可能扑空走完、以漏怪收场——原版两件事都会发生。
//
// **只给一个点**时＝"钉在这一格"（换成自缚腿）：原版「贴到目标」那一步就是
// `e.route = [op.position]` ＋ `e.legs = []`，一条单点路线永远走不完，于是它既不动
// 也不会漏怪。⚠ 只改位置而不换路线是个真错：旧的那条飞行路线还挂着，下一帧
// `advance` 会沿着它继续往前挪（实测 HS-S-1 就是这么让一只乙在自毁前多挨了一下）。
func (c *simCtx) SetEnemyRoute(index int, points [][2]float64) {
	e := c.enemyAt(index)
	if e == nil || len(points) == 0 {
		return
	}
	e.progress = 0
	e.legU = 0
	e.legIndex = 0
	e.offMap = false
	if len(points) == 1 {
		e.spec.Legs = []LegSpec{{Kind: "static", Points: points}}
		e.position = points[0]
		return
	}
	length := 0.0
	for i := 1; i < len(points); i++ {
		length += math.Hypot(points[i][0]-points[i-1][0], points[i][1]-points[i-1][1])
	}
	e.spec.Legs = []LegSpec{{Kind: "walk", Points: points, Length: length}}
}

// EnemyMoveSpeed 是这一只**这一刻**的推进速度：与主循环 `advance` 用的是同一个
// 算式（`spec.MoveSpeed × 自身乘区 × 关卡乘区 × 机制请求的乘区`），免得机制自己
// 抄一份。`自身乘区`就是原版 `haste_multiplier`（明识形态的清水会改它）。
func (c *simCtx) EnemyMoveSpeed(index int) float64 {
	if e := c.enemyAt(index); e != nil {
		return e.spec.MoveSpeed * e.haste * c.spec.SpeedScale * c.speedFor(index)
	}
	return 0
}

// SetEnemyInvincible 关掉/打开甲的监测态无敌（原版 `always_invincible`）。
func (c *simCtx) SetEnemyInvincible(index int, on bool) {
	if e := c.enemyAt(index); e != nil {
		e.invincible = on
	}
}

// EnemyWindup 是这一关的"出手动作时间"（原版 `self.enemy_windup`）。
func (c *simCtx) EnemyWindup() float64 { return c.spec.EnemyWindup }

func (c *simCtx) Log(format string, args ...any) {
	c.verdict.Events = append(c.verdict.Events, Event{
		T: *c.time, Kind: "mech", Who: fmt.Sprintf(format, args...)})
}

func (c *simCtx) Now() float64 { return *c.time }

// Trace 写一行痕迹：只有 `RIOS_TRACE=1` 才输出，且只走 stderr。
// 与 `Log` 分开——`Log` 会进判决的 `events`，痕迹不该改变判决的载荷。
func (c *simCtx) Trace(format string, args ...any) {
	if traceOn {
		trace(format, args...)
	}
}

// ================================================================ 推进

// advance 沿分段计划推进 dt 秒（`EnemyUnit._advance_legs`，unit.py）。
//
// 三种段共用 `legU`：走段里它是已走格数，等待/离场段里是已过秒数。
// 整个循环**以时间为预算**——按格数当预算的话，等待段会被移速缩放，
// 3 秒的待命会被拉成好几分钟。
func advance(e *enemy, dt, speedScale float64) {
	// `e.haste` 是原版 `haste_multiplier`（明识形态的清水会改它），与
	// `EnemyMoveSpeed` 必须乘同一串量——两边不一致的话，"机制看到的移速"
	// 与"实际推进的移速"会各说各话。
	speed := e.spec.MoveSpeed * e.haste * speedScale
	if speed <= 0 {
		return
	}
	// 移速**变化即记一笔**（不逐帧打，那样 72 只 × 2900 帧没法看）。
	// 原版的移速是六项连乘：`move_speed × speed_scale × speed_multiplier ×
	// haste_multiplier × (1 - slow_pct) × lock_slow`；这里只有三项，
	// 哪一项分家只能靠"同一只敌人两边速度何时开始不同"去指认。
	if traceOn && speed != e.traceSpeed {
		e.traceSpeed = speed
		trace("SPEED t=%.4f enemy=%s speed=%.6f move=%.4f haste=%.6f scale=%.6f",
			*e.sim.time, e.spec.Name, speed, e.spec.MoveSpeed, e.haste, speedScale)
	}
	left := dt
	guard := 0
	for left > 1e-12 && e.legIndex < len(e.spec.Legs) {
		guard++
		if guard > 4096 {
			break
		}
		leg := e.spec.Legs[e.legIndex]
		e.offMap = leg.Kind == "vanish"
		if leg.Kind == "static" {
			// 自缚：站在原地。这条腿**永远走不完**（`legU` 不动），所以既不会
			// 位移、也不会被 `reachedEnd` 判成走到路线终点（原版靠"单点路线 +
			// `reached_end` 要求路线长度 > 0"达到同一效果）。
			break
		}
		if leg.Kind == "walk" {
			room := leg.Length - e.legU
			if room <= 0 {
				e.nextLeg()
				continue
			}
			can := speed * left
			step := math.Min(can, room)
			e.legU += step
			e.progress += step
			e.position = pointAt(leg.Points, e.legU)
			left -= step / speed
			if step >= room-1e-9 {
				e.nextLeg()
			} else {
				break
			}
		} else {
			room := leg.Seconds - e.legU
			if room <= 0 {
				e.nextLeg()
				continue
			}
			step := math.Min(left, room)
			e.legU += step
			left -= step
			if step >= room-1e-9 {
				e.nextLeg()
			} else {
				break
			}
		}
	}
	if e.legIndex >= len(e.spec.Legs) {
		e.offMap = false
	}
}

func (e *enemy) nextLeg() {
	e.legIndex++
	e.legU = 0
}

// pointAt 沿折线走 travelled 格之后的位置（`unit.point_at`）。
func pointAt(points [][2]float64, travelled float64) [2]float64 {
	if len(points) == 0 {
		return [2]float64{0, 0}
	}
	if travelled <= 0 {
		return points[0]
	}
	acc := 0.0
	for i := 0; i+1 < len(points); i++ {
		a, b := points[i], points[i+1]
		seg := math.Hypot(b[0]-a[0], b[1]-a[1])
		if seg <= 0 {
			continue
		}
		if acc+seg >= travelled {
			k := (travelled - acc) / seg
			return [2]float64{a[0] + (b[0]-a[0])*k, a[1] + (b[1]-a[1])*k}
		}
		acc += seg
	}
	return points[len(points)-1]
}

// updateBlocking 每帧重算阻挡关系（`_update_blocking`，sim.py 2289）。
func updateBlocking(ops []*operator, enemies []*enemy) {
	for _, op := range ops {
		if len(op.blocking) == 0 {
			continue
		}
		keep := op.blocking[:0]
		for _, e := range op.blocking {
			if e.hp > 0 && e.blockedBy == op {
				keep = append(keep, e)
			}
		}
		op.blocking = keep
	}
	for _, e := range enemies {
		if e.hp <= 0 || e.leaked || e.offMap || e.blockedBy != nil || e.spec.IsFlying ||
			e.spec.Unblockable {
			continue
		}
		for _, op := range ops {
			if !op.alive() || !op.canBlock(e) {
				continue
			}
			dx := e.position[0] - op.cell[0]
			dy := e.position[1] - op.cell[1]
			if dx*dx+dy*dy <= positionTol2 {
				e.blockedBy = op
				op.blocking = append(op.blocking, e)
				break
			}
		}
	}
	for _, e := range enemies {
		if b := e.blockedBy; b != nil && !b.alive() {
			e.blockedBy = nil
		}
	}
}

// operatorsAttack 我方出手（`_operators_attack`，sim.py 2995）。
//
// 一个容易写错的细节：**没有目标时不重置攻击计时器**（原版 3026-3027 的
// `continue` 在 `attack_timer = 0` 之前）——重置的话，范围里一直没人的干员
// 会在敌人一进范围的那一帧立刻出手，比原版快半拍。
//
// 技能期间的三个数（倍率 / 连击数 / 末击倍率）都由 `Profile` 送来：
//
//   - `atk_scale` 乘在 `resolve_damage(scale=…)` 那一处（2026-09-18 博士裁定：
//     主循环**不**再自己乘一遍）；
//   - `hit_count` 是"一次出手打几下"，**每一击都各减一次防御**；
//   - `final_hit_scale` 只改最后一击的倍率。
func operatorsAttack(ops []*operator, enemies []*enemy, dt, t float64,
	spec *Spec, verdict *Verdict) {
	for _, op := range ops {
		if !op.alive() {
			continue
		}
		op.attackTimer += dt
		if op.attackTimer < op.interval() {
			continue
		}
		targets := pickTargets(op, enemies, op.maxTarget())
		// ---- 医疗：平A 是**治疗**，不是伤害（原版 3994-4019）
		//
		// 判据两段：① 这个人是医疗（`op.heals`）；② 这一击**没被技能改成伤害**
		// ——技能自己写了攻击倍率就是改成伤害了（凯尔希·思衡托技2「攻击变为射出
		// 医疗单元」）。只写 `op.heals` 不看技能，会让她的技2 变成"边打边治"。
		//
		// ⚠ 这一段的判据必须在**选完伤害目标之后、判有没有目标之前**：医疗通常
		// 范围里没有敌人，而"没有伤害目标"在原版那里就等于"没得治"——
		// 把顺序写反会让医疗一次都不出手。
		scaleNow := op.atkScale()
		deals := !op.spec.Heals || math.Abs(scaleNow-1.0) > 1e-9
		var heals []*operator
		if !deals {
			targets = nil
			heals = pickHeals(op, ops, 1)
		}
		if traceOn {
			trace("%8.4f %s 技=%v 间隔=%.4f 计时=%.4f 挡=%v 选=%v 范围里=%v 治=%v",
				t, op.spec.Name, op.skillActive, op.interval(), op.attackTimer,
				names(op.blocking), names(targets), names(inRangeOf(op, enemies)),
				namesOp(heals))
		}
		if len(targets) == 0 && len(heals) == 0 {
			continue
		}
		op.attackTimer = 0
		scale := scaleNow
		hits := op.hitCount()
		finalScale, hasFinal := op.finalHitScale()
		power := op.atk()
		dmgType := op.damageType()
		if !deals {
			// 治疗量 = 当前攻击力 × 治疗倍率（医疗干员平A 的倍率是 1）。
			// `heal` 自己夹在生命上限，返回**实际回复量**。
			for _, ally := range heals {
				got := ally.heal(power)
				if traceOn && got > 0 {
					trace("%8.4f %s 治疗 %s +%.0f（%.0f/%.0f）",
						t, op.spec.Name, ally.spec.Name, got, ally.hp, ally.spec.MaxHP)
				}
			}
			// 出手回报照算（原版把这一句放在出手之后、与打伤害同路）。
			spOnAttack(op)
			continue
		}
		for _, target := range targets {
			for i := 0; i < hits; i++ {
				if !target.alive() {
					break
				}
				hitScale := scale
				if hasFinal && i == hits-1 {
					hitScale = finalScale
				}
				// 闪避走 `target.dodgeVs`：这一路（我方打敌方）原版读的是**敌人**
				// 的 `dodge_phys + talent_dodge_phys`（`sim.py:3921`）。那个值恒为 0
				// （原因写在 `enemy.dodgeVs` 上），所以这里不是"先不管"，
				// 而是"与原版同值、并且有名字"。
				dmg := resolveDamage(power, dmgType, hitScale,
					target.spec.DEF, target.spec.RES, target.dodgeVs(dmgType))
				dealt := target.take(dmg, op)
				trace("        打 %s 攻=%.1f 类型=%s 倍率=%.3f 防=%.1f 抗=%.1f 伤害=%.3f 实扣=%.3f 剩=%.3f",
					target.spec.Name, power, dmgType, hitScale, target.spec.DEF,
					target.spec.RES, dmg, dealt, target.hp)
				if dealt <= 0 {
					continue
				}
				// 打向敌人的伤害在这里累计（原版 `_damage_enemy` 里的
				// `result.damage_dealt += dealt`）；**不是**干员承受的伤害——
				// 两者名字都叫 damage，混起来会让对拍看起来"完全对不上"。
				verdict.DamageDealt += dealt
				if !target.alive() && !target.pendingReborn() {
					target.deathTime = t
					verdict.Events = append(verdict.Events,
						Event{T: t, Kind: "kill", Who: target.spec.Name})
				}
			}
			// 特性溅射：**每个主目标各一次**（原版把调用写在主目标循环里、
			// 连击循环外面）。不判主目标死活。
			if op.spec.SplashRadius > 0 {
				traitSplash(op, spec, enemies, target, power, t, verdict)
			}
		}
		// 出手回报：攻击回复的技力与弹药消耗（原版 3187-3205，在整次出手之后）
		spOnAttack(op)
		if op.skillActive && op.spec.Skill != nil && op.spec.Skill.Ammo > 0 &&
			op.ammoLeft > 0 {
			op.ammoLeft--
		}
	}
}

// splashTiles 以 `center` 为心、`radius` 为半径的圆**盖到的地块**——**重叠判定**
// （原版 `battle/traits.py:splash_tiles`）。
//
// 地块 `(x, y)` 是以整数点为心、边长 1 的正方形；"被盖到"判的是圆心到这张
// 正方形的**最近点**距离 ≤ 半径，最近点距离按分量算（`max(|d| - 0.5, 0)` 再取
// 欧氏范数）。所以半径 1.0 时斜邻格也在内（近角距 ≈ 0.707）——**这是 3×3 九格，
// 不是十字五格**；半径 ≤ 0.707 时斜邻才掉出去。
//
// ⚠ 圆心是**连续坐标**，不是格心：圆心在格内挪半格，斜邻格的取舍就会变。
func splashTiles(center [2]float64, radius float64) [][2]int {
	if radius < 0 {
		return nil
	}
	x, y := center[0], center[1]
	baseX, baseY := int(math.Floor(x)), int(math.Floor(y))
	reach := int(math.Ceil(radius + 0.5))
	var out [][2]int
	for dx := -reach; dx <= reach; dx++ {
		for dy := -reach; dy <= reach; dy++ {
			tx, ty := baseX+dx, baseY+dy
			gx := math.Max(math.Abs(x-float64(tx))-0.5, 0)
			gy := math.Max(math.Abs(y-float64(ty))-0.5, 0)
			if math.Hypot(gx, gy) <= radius+1e-9 {
				out = append(out, [2]int{tx, ty})
			}
		}
	}
	return out
}

// crossCells 是「周围 4 格 + 本格」——**格子判定**（原版 `cross_cells`，范围码 `x-5`）。
// 高台那一半用它，与上面的半径圆不是同一套几何，不能互相顶替。
func crossCells(cell [2]int) [5][2]int {
	x, y := cell[0], cell[1]
	return [5][2]int{{x, y}, {x + 1, y}, {x - 1, y}, {x, y + 1}, {x, y - 1}}
}

// traitSplash 是职业特性溅射 + 天赋「汹涌怒火」的高台那一半
// （原版 `BattleSimulator._trait_splash`，sim.py 2931）。
//
// 三条口径：
//  1. 主目标**自己不吃这一份**（正文写的是"目标**周围的其他**敌人"），
//     天赋的增伤也只乘溅射、不乘主目标；
//  2. 高台溅射是**另一套几何**：被溅射到的每个高台，对「它自己周围四格 + 本格」
//     里的**地面**敌人再打一次（`crossCells`）；
//  3. `HighlandCells` 由 Python 随规格送来（Go 没有地图）——不在表里就当没有高台。
//
// ⚠ 已知未接：高台溅射附带的【停顿】（`highland_splash_sluggish`）与
// 「每次高台触发回 N 点技力」（`sp_per_highland`）。两者都在闸门里挡着，
// 不会静默少算。
func traitSplash(op *operator, spec *Spec, enemies []*enemy, target *enemy,
	power, t float64, verdict *Verdict) {
	cells := splashTiles(target.position, op.spec.SplashRadius)
	if len(cells) == 0 {
		return
	}
	if traceOn {
		hi := 0
		hm := map[[2]int]bool{}
		for _, c := range spec.HighlandCells {
			hm[[2]int{c[0], c[1]}] = true
		}
		for _, c := range cells {
			if hm[c] {
				hi++
			}
		}
		// 场上敌人清单也一起打：溅射的受害者是按"格"挑的，两边算出的覆盖面
		// 一模一样却少打中一次时，唯一还没比过的就是**那一刻谁站在哪一格**。
		parts := make([]string, 0, len(enemies))
		for _, e := range enemies {
			if e.hp <= 0 || e.leaked {
				continue
			}
			cx, cy := e.cell()
			parts = append(parts, fmt.Sprintf("%s@%.4f,%.4f#%d,%d/hp%.1f",
				e.spec.Name, e.position[0], e.position[1], cx, cy, e.hp))
		}
		trace("SPLASH-CENTER t=%.4f op=%s target=%s pos=%.4f,%.4f cells=%d highland=%d enemies=%s",
			t, op.spec.Name, target.spec.Name, target.position[0],
			target.position[1], len(cells), hi, strings.Join(parts, "|"))
	}
	scale := op.spec.SplashScale * op.spec.SplashDamageScale
	for _, e := range enemies {
		if e == target || e.hp <= 0 || e.leaked {
			continue
		}
		cx, cy := e.cell()
		if !hasCell(cells, cx, cy) {
			continue
		}
		splashHit(op, e, power, scale, t, verdict, "radius", target)
	}
	if op.spec.HighlandSplashScale <= 0 {
		return
	}
	highland := map[[2]int]bool{}
	for _, c := range spec.HighlandCells {
		highland[[2]int{c[0], c[1]}] = true
	}
	for _, cell := range cells {
		if !highland[cell] {
			continue
		}
		for _, victimCell := range crossCells(cell) {
			for _, e := range enemies {
				if e.hp <= 0 || e.leaked || e.spec.IsFlying {
					continue
				}
				cx, cy := e.cell()
				if cx != victimCell[0] || cy != victimCell[1] {
					continue
				}
				splashHit(op, e, power, op.spec.HighlandSplashScale, t,
					verdict, "highland", target)
			}
		}
	}
}

// splashHit 是一次溅射伤害的落地（与主目标那一路同一个伤害口径：
// `resolve_damage` → `take` → 记击杀）。
//
// `kind` 与 `from` **只为 `RIOS_TRACE` 那条可数痕迹存在**：溅射到底少算了多少点，
// 只能靠"逐次落点 + 倍率 + 实际扣血"和原版对出来；只看伤害总量，连是哪一半
// （半径圆 / 高台十字）缺的都分不出来。
func splashHit(op *operator, e *enemy, power, scale, t float64, verdict *Verdict,
	kind string, from *enemy) {
	dmg := resolveDamage(power, "PHYSICAL", scale,
		e.spec.DEF, e.spec.RES, e.dodgeVs("PHYSICAL"))
	dealt := e.take(dmg, op)
	if kind == "highland" && op.spec.HighlandSplashSluggish > 0 {
		// 原版 `sim.py:3855-3857`：高台那一半溅到谁，就给谁挂【停顿】
		// （天赋 `attack@sluggish` = 0.5 秒）。取 max 而不是覆盖，与
		// `sluggish_timer` 全仓一致的写法。
		e.sluggishTimer = math.Max(e.sluggishTimer, op.spec.HighlandSplashSluggish)
	}
	if traceOn {
		trace("SPLASH t=%.4f op=%s kind=%s from=%s victim=%s scale=%.4f dmg=%.3f dealt=%.3f hp=%.3f",
			t, op.spec.Name, kind, from.spec.Name, e.spec.Name, scale, dmg, dealt, e.hp)
	}
	if dealt <= 0 {
		return
	}
	verdict.DamageDealt += dealt
	if !e.alive() && !e.pendingReborn() {
		e.deathTime = t
		verdict.Events = append(verdict.Events,
			Event{T: t, Kind: "kill", Who: e.spec.Name})
	}
}

func hasCell(cells [][2]int, x, y int) bool {
	for _, c := range cells {
		if c[0] == x && c[1] == y {
			return true
		}
	}
	return false
}

// pickHeals 治疗目标：攻击范围内**血量比例最低**、且没满血的友方
// （原版 `_pick_heals`，sim.py 3683）。
//
// ⚠ 排序键是 **(血量比例, 血量)** 两条：比例相同时血少的先治。只比比例会让
// 同比例的两个人在排序里保持原顺序，治错人——而且这种错在计数上看不出来。
//
// 范围用**四舍五入后的格**（与索敌同一口径），不是连续坐标。
func pickHeals(op *operator, ops []*operator, n int) []*operator {
	type cand struct {
		o   *operator
		rat float64
	}
	var pool []cand
	for _, o := range ops {
		if o == op || !o.alive() || o.hp >= o.spec.MaxHP {
			continue
		}
		cell := [2]int{int(math.RoundToEven(o.cell[0])), int(math.RoundToEven(o.cell[1]))}
		if !inCells(op.spec.Range, cell) {
			continue
		}
		pool = append(pool, cand{o: o, rat: o.hp / o.spec.MaxHP})
	}
	sort.SliceStable(pool, func(i, j int) bool {
		if pool[i].rat != pool[j].rat {
			return pool[i].rat < pool[j].rat
		}
		return pool[i].o.hp < pool[j].o.hp
	})
	out := make([]*operator, 0, n)
	for _, c := range pool {
		if len(out) >= n {
			break
		}
		out = append(out, c.o)
	}
	return out
}

// pickTargets 目标选择（`_pick_targets`，sim.py 2343）。
//
// 先打**自己挡住的**，再打范围里"离防守点最近"的——用 `progress` 当"离防守点
// 多远"的代理（越大越近）。嘲讽等级高的优先，负数表示非首要目标。
func pickTargets(op *operator, enemies []*enemy, n int) []*enemy {
	out := make([]*enemy, 0, n)
	for _, e := range op.blocking {
		if e.hp > 0 && !e.leaked {
			out = append(out, e)
			if len(out) >= n {
				return out
			}
		}
	}
	inRange := make([]*enemy, 0, 8)
	for _, e := range enemies {
		if e.hp <= 0 || e.leaked || e.offMap {
			continue
		}
		cell := [2]int{int(math.RoundToEven(e.position[0])), int(math.RoundToEven(e.position[1]))}
		if !inCells(op.spec.Range, cell) {
			continue
		}
		inRange = append(inRange, e)
	}
	sort.SliceStable(inRange, func(i, j int) bool {
		if inRange[i].spec.TauntLevel != inRange[j].spec.TauntLevel {
			return inRange[i].spec.TauntLevel > inRange[j].spec.TauntLevel
		}
		return inRange[i].progress > inRange[j].progress
	})
	for _, e := range inRange {
		out = append(out, e)
		if len(out) >= n {
			break
		}
	}
	return out
}

// names / inRangeOf 只给跟踪用（`RIOS_TRACE=1`）。放在这里而不是单独文件，
// 是因为它们读的就是上面那套判据——两者必须一起改，分开写迟早会不一致。
func names(list []*enemy) []string {
	out := make([]string, 0, len(list))
	for _, e := range list {
		out = append(out, fmt.Sprintf("%s(%.0f)", e.spec.Name, e.hp))
	}
	return out
}

func namesOp(list []*operator) []string {
	out := make([]string, 0, len(list))
	for _, o := range list {
		out = append(out, fmt.Sprintf("%s(%.0f)", o.spec.Name, o.hp))
	}
	return out
}

func inRangeOf(op *operator, enemies []*enemy) []*enemy {
	out := make([]*enemy, 0, 8)
	for _, e := range enemies {
		if e.hp <= 0 || e.leaked || e.offMap {
			continue
		}
		cell := [2]int{int(math.RoundToEven(e.position[0])), int(math.RoundToEven(e.position[1]))}
		if inCells(op.spec.Range, cell) {
			out = append(out, e)
		}
	}
	return out
}

func inCells(cells [][2]int, cell [2]int) bool {
	for _, c := range cells {
		if c == cell {
			return true
		}
	}
	return false
}

// enemiesAttack 敌方出手（`_enemies_attack`，sim.py 2882）。
func enemiesAttack(ops []*operator, enemies []*enemy, dt, t float64, spec *Spec,
	verdict *Verdict) {
	for _, e := range enemies {
		if e.hp <= 0 || e.leaked || e.offMap {
			continue
		}
		// 天赋「不进行远程普通攻击」（玷 / 勿玷）：普攻这一整条路关掉，
		// 它的伤害全部走技能（原版 `_enemies_attack` 的
		// `if e.skill_atk_no_normal: continue`）。漏掉这条闸门，这只敌人会
		// **技能与普攻双份出手**——HS-EX-8 第 2 手多出的两笔 192 就是这么来的。
		if e.spec.SkillAtkNoNormal {
			continue
		}
		// 冻结：**既不走也不出手**（原版 `_enemies_attack` 的 `e.frozen` 闸门）。
		// 与「停顿」不是一回事——停顿只是移速降 80%，照样打人。
		if e.freezeTimer > 0 {
			continue
		}
		op := enemyTarget(e, ops, spec.RangedEnemies)
		if op == nil || !op.alive() {
			continue
		}
		e.attackTimer += dt
		if e.attackTimer < e.spec.Interval {
			continue
		}
		e.attackTimer = 0
		e.hits++
		// 出手占用一段动作时间，这期间它不走路（但动作一结束就继续推进）
		e.attackPause = math.Max(e.attackPause, spec.EnemyWindup)
		if traceOn {
			// 出手那一帧的**计时器与停帧值**：对拍"前摇停帧的相位差"时，
			// 光看坐标只能知道"有一帧不一样"，看不出是谁在什么时候出手的。
			// 与 POS 痕迹同一族（`RIOS_TRACE` 总开关）。
			cx, cy := e.cell()
			trace("ATK t=%.4f enemy=%s idx=%d ecell=%d,%d interval=%.4f "+
				"pause=%.4f hits=%d",
				t, e.spec.Name, e.index, cx, cy, e.spec.Interval,
				e.attackPause, e.hits)
		}
		times := e.spec.AttackTimes
		if times < 1 {
			times = 1
		}
		// 连击逐段结算：两段的防御/法抗各减一次。把 atk 乘 2 再打一次会少减
		// 一次防御，对高防目标能差出成倍的伤害（原版 2909-2920 的正文）。
		// 防御/法抗取**这一刻**的数（技能给防御的，敌人打上来时就得吃到）。
		dealt := 0.0
		for seg := 0; seg < times; seg++ {
			dmg := resolveDamage(e.spec.ATK, e.spec.DamageType, 1.0,
				op.defense(), op.res(), op.dodgeVs(e.spec.DamageType))
			dealt += op.take(dmg)
			if traceOn {
				// `ecell` 不是装饰：同一个名字的敌人有好几只（HS-EX-8 上「勿玷」
				// 一度同时有六七只），只记名字会把它们全归到同一个键上，于是
				// "某一只多打了一笔"从痕迹上根本看不出来——对拍时两边笔数不同
				// 却找不到是哪一只，只能干猜。同一族痕迹（SKILLATK）早就带了它，
				// 这里补齐。
				cx, cy := e.cell()
				trace("ENEMYATK t=%.4f enemy=%s ecell=%d,%d atk=%.1f target=%s seg=%d/%d dmg=%.3f",
					t, e.spec.Name, cx, cy, e.spec.ATK, op.spec.Name, seg+1, times, dmg)
			}
			if !op.alive() {
				op.deathTime = t
				verdict.Events = append(verdict.Events,
					Event{T: t, Kind: "death", Who: op.spec.Name})
				break
			}
		}
		// 受击回复的技力：这一下**真的掉血了**才回（原版 3301-3306）
		spOnHit(op, dealt)

		// 【怀黍离】重生后的普攻附加伤害（瘴 / 鄙瘴）：「普通攻击附加攻击力
		// (10×充能层数)%的无途径法术普通伤害」（原版 3447-3465）。
		//
		// 「无途径」= 不受攻击方式/途径影响，所以这里独立结算：攻击力 × 比例
		// × 层数，**按法术算**（吃目标法抗），并同样吃闪避期望。
		// ⚠ 它是**附加**在普攻上的，不是替代——上面那次已经结算完了。
		if bonus := e.rebornChargeBonus(); bonus > 0.0 && op.alive() {
			extra := resolveDamage(bonus, "MAGIC", 1.0, op.defense(), op.res(),
				op.dodgeVs("MAGIC"))
			dmg := op.take(extra)
			if traceOn {
				trace("ENEMYATK-BONUS t=%.4f enemy=%s target=%s bonus=%.3f dmg=%.3f",
					t, e.spec.Name, op.spec.Name, bonus, dmg)
			}
			spOnHit(op, dmg)
			if !op.alive() {
				op.deathTime = t
				verdict.Events = append(verdict.Events,
					Event{T: t, Kind: "death", Who: op.spec.Name})
			}
		}
	}
}

// enemyTarget 敌人该打谁（`_enemy_target`，sim.py 2851）。
//
// ① 挡住自己的干员最优先；② 否则射程内**最后部署**的那一个（不是最近的）。
func enemyTarget(e *enemy, ops []*operator, ranged bool) *operator {
	if e.blockedBy != nil && e.blockedBy.alive() {
		return e.blockedBy
	}
	if !ranged || e.spec.ApplyWay != "RANGED" || e.spec.AttackRange <= 0 ||
		e.spec.ATK <= 0 {
		return nil
	}
	var picked *operator
	for _, op := range ops { // 列表顺序 = 部署顺序，越靠后越晚
		if !op.alive() {
			continue
		}
		if math.Hypot(e.position[0]-op.cell[0], e.position[1]-op.cell[1]) <=
			e.spec.AttackRange {
			picked = op
		}
	}
	return picked
}

// resolve 收尾结算（`_resolve`，sim.py 3720）：击杀奖励费用与漏怪扣命。
func resolve(enemies []*enemy, cost *float64, life *int, t float64,
	verdict *Verdict) {
	for _, e := range enemies {
		if e.hp <= 0 && !e.leaked && e.spec.KillCost != 0 && !e.costAwarded {
			e.costAwarded = true
			*cost += float64(e.spec.KillCost)
		}
		if e.hp > 0 && !e.leaked && !e.offMap && e.reachedEnd() {
			e.leaked = true
			e.leakTime = t
			*life -= e.spec.LifeCost
			verdict.LeakEvents = append(verdict.LeakEvents,
				[3]any{t, e.spec.Name, e.spec.LifeCost})
			verdict.Events = append(verdict.Events,
				Event{T: t, Kind: "leak", Who: e.spec.Name})
		}
	}
}

// anyActive：场上还有"活着的、没漏的、清得掉的"敌人吗（run 1907-1912）。
func anyActive(enemies []*enemy) bool {
	for _, e := range enemies {
		if e.alive() && !e.leaked && !e.spec.CannotClear {
			return true
		}
	}
	return false
}

func (e *enemy) take(amount float64, src *operator) float64 {
	if e.invincible {
		// 监测态的甲：**挨打掉 0 血**，但目标选择照旧把它算进去（原版
		// `_damage_enemy` 里 `always_invincible` 就是返回 0）。
		return 0
	}
	// 明识形态的限时无敌窗口（原版 `_damage_enemy` 里那一支
	// `now < target.invincible_until`）。`src` 只用于记名，与伤害无关。
	if e.sim != nil && *e.sim.time < e.invincibleUntil {
		return 0
	}
	dealt := math.Min(e.hp, math.Max(0, amount))
	e.hp -= dealt
	if dealt > 0 && e.sim != nil {
		// 挨打的附加效果（原版 `_enemy_on_hit`）。放在 `take` 里而不是放在
		// 各个调用点上：普攻、技能、机制伤害都会走到这里，漏一个就是
		// "某一族效果静默不生效"。
		e.sim.onEnemyHit(e, src)
	}
	return dealt
}

// nextDeploySeq 发一个"这一次部署"的身份号（见 `operator.deploySeq`）。
func (c *simCtx) nextDeploySeq() int {
	c.deploySeq++
	return c.deploySeq
}

// onEnemyHit 是一只敌人**挨了一次伤害**之后要发生的事（原版 `_enemy_on_hit`
// 里与蜕皮有关的那一段，`sim.py:1248-1265`）。
//
// 目前只有蜕皮（`Passive_Hit.*`）与明识形态的**记名**（`PassiveM2.*`）；
// 速度提升（`SpeedUp.*`）还没接，接的时候**加在这里**，不要另开调用点。
func (c *simCtx) onEnemyHit(e *enemy, src *operator) {
	sp := &e.spec
	// 明识形态记名：形态里**被我方打中**就把那位记下来（原版
	// `marked_ops.add(id(source))`）。机制造成的伤害没有来源，不记。
	//
	// ⚠ 这一条排在"蜕皮层满就整段 return"**之前**：两者是并列的两件事，
	// 蜕皮的层满了不该连带把记名也吞掉。
	if e.pm2Active && src != nil {
		if e.marked == nil {
			e.marked = map[int]bool{}
		}
		e.marked[src.deploySeq] = true
	}
	// ⚠ 整个判据只有一层：层满了就连病害都不再加（原版把加病害写在同一个
	// `if` 里，不是并列的两件事）。
	if sp.PhitCnt <= 0 || e.phitStacks >= sp.PhitMaxStack {
		return
	}
	e.phitHits++
	for e.phitHits >= sp.PhitCnt && e.phitStacks < sp.PhitMaxStack {
		e.phitHits -= sp.PhitCnt
		e.phitStacks++
		// 黑板里 atk/def/res/move 存的都是**增量**（攻防那几项是负数）
		sp.ATK += sp.PhitAtk
		sp.DEF += sp.PhitDef
		sp.RES += sp.PhitRes
		sp.MoveSpeed += sp.PhitMove
		// 原版还按 `phit_weight_cnt` 每 N 层重量等级 −1。Go 侧没有重量字段
		// （阻挡只看 block_cnt，位移那套不在本模拟器范围内），故不减——这
		// 一条是**已知边界**，写在 `docs/uncertainties.md` 的口径里。
	}
	// 加病害：被挡用 `PhitBlockPollut`、没被挡用 `PhitPollut`。
	//
	// ⚠ 两处分寸都不一样，别照抄击倒那一路：
	//   · 选**用量**看的是 `blocked_by is not None`（挡它的那位这一帧刚倒也算）；
	//   · 选**圆心**还要求那位**活着**（`_pollute_around` 1294 行），否则退回自己脚下。
	amount := sp.PhitPollut
	if e.blockedBy != nil {
		amount = sp.PhitBlockPollut
	}
	c.polluteFromEnemy(e, amount, 1.0)
}

// enterPm2 是"归来即入明识形态"（原版 `_enter_pm2`，`sim.py:4122-4151`）。
//
// 三条容易抄错的地方：
//
//  1. **触发条件是"有没有那三个量"**，不是"有没有重生"——`pm2_atk / pm2_move /
//     pm2_invincible` 全 0 就不进形态（原版 4229）。
//  2. 面板只改**一次**（`pm2_applied`）：反复乘会让攻击力指数衰减。攻击力用
//     乘法、抗性用加法、防御也走乘法——逐个照原文，别"统一"。
//  3. `attack_times = 2` 与 `apply_way = "RANGED"` 都**只在射程大于 0 时**才改
//     出手方式：近战那只连击两次仍然按近战结算。
func (c *simCtx) enterPm2(e *enemy, t float64) {
	sp := &e.spec
	if sp.Pm2Atk == 0 && sp.Pm2Move == 0 && sp.Pm2Invincible == 0 {
		return
	}
	e.pm2Active = true
	if !e.pm2Applied {
		e.pm2Applied = true
		sp.ATK *= 1.0 + sp.Pm2Atk
		sp.DEF *= 1.0 + sp.Pm2Def
		sp.RES += sp.Pm2Res
		e.haste = 1.0 + sp.Pm2Move
		sp.AttackTimes = 2
		if sp.AttackRange > 0 {
			sp.ApplyWay = "RANGED"
		}
	}
	if sp.Pm2Invincible > 0 {
		e.invincibleUntil = t + sp.Pm2Invincible
	}
}

// pm2Tick 是明识形态的逐帧部分（原版 `_pm2_tick`，`sim.py:4044-4088`）。
//
// 两件事：**清水**开关（重新算防御与移速乘区）与**标记退场**（被记名的干员
// 离场时给脚下加病害）。
func (c *simCtx) pm2Tick(ctx mech.Ctx, t float64, ops []*operator) {
	// 场上所有活着的我方单位脚下的格子：泵站"水源地上有人"那一支要用它。
	// 每次投票现攒，不缓存——它是逐帧量（有人刚落地/刚倒下都会变）。
	allies := make([][2]int, 0, len(ops))
	for _, op := range ops {
		if op.alive() {
			allies = append(allies, [2]int{int(op.cell[0]), int(op.cell[1])})
		}
	}
	for _, e := range *c.enemies {
		if !e.pm2Active || e.hp <= 0 {
			continue
		}
		cx, cy := e.cell()
		// ---- 清水：站在病害值 0 的田地上，或在清澈泵站的射程里
		clean := false
		if ctx != nil {
			clean = c.mechanisms.IsClear(ctx, [2]int{cx, cy}, allies)
		}
		if clean != e.pm2Clean || !e.pm2Clean {
			e.pm2Clean = clean
			// 防御**从基准重算**，不是加减：清水能来回切，累乘会指数漂。
			e.spec.DEF = e.rebornDefBase *
				(1.0 + e.spec.Pm2Def + boolToFloat(clean, e.spec.Pm2CleanDef))
			// 移速乘区：清水时不加成（原版 4070）
			e.haste = 1.0 + boolToFloat(!clean, e.spec.Pm2Move)
		}
		// ---- 标记退场：被它打过的干员里，已经不在场上的那些
		if len(e.marked) == 0 || e.spec.Pm2MarkPollut <= 0 {
			continue
		}
		stillHere := map[int]bool{}
		for _, op := range ops {
			if op.alive() {
				stillHere[op.deploySeq] = true
			}
		}
		for seq := range e.marked {
			if stillHere[seq] {
				continue
			}
			delete(e.marked, seq)
			// 只在**没被阻挡**时加（原版 4085 那一支）
			if e.blockedBy == nil {
				c.polluteFromEnemy(e, e.spec.Pm2MarkPollut, 1.0)
			}
		}
	}
}

func boolToFloat(b bool, v float64) float64 {
	if b {
		return v
	}
	return 0
}

// summonReborn 是重生期召唤的一"拍"（原版 `_summon_at`，`sim.py:4176-4184` 调用）。
//
// 召唤位置是**自己脚下那一格**（原文写的"1.0 边长正方形范围内随机位置"正好覆盖
// 脚下那格，本项目按可复现收口，不做随机）。
//
// ⚠ 路线按"哪一格出发"查表：召唤那一刻站在哪一格只有跑到才知道，Python 把
// 地图每一格的路线都算好随规格发来了。查不到就**当场拒跑**——绝不"随便给条
// 路"，那会让漏怪判定悄悄偏。
func (c *simCtx) summonReborn(e *enemy, i int, t float64, verdict *Verdict) {
	rs := e.spec.RebornSummons[i]
	if rs.Template == nil || rs.Count <= 0 {
		return
	}
	cx, cy := e.cell()
	key := strconv.Itoa(cx) + "," + strconv.Itoa(cy)
	points, ok := rs.Paths[key]
	if !ok {
		panic(fmt.Sprintf(
			"重生期召唤：%s 倒在 %s，而规格里没有这一格的路线——"+
				"这一份规格不能用，拒绝跑下去（宁可拒跑也不给一条错的路）",
			e.spec.Name, key))
	}
	pts := make([][2]float64, 0, len(points))
	for _, p := range points {
		pts = append(pts, [2]float64{p[0], p[1]})
	}
	legs := []LegSpec{{Kind: "walk", Points: pts, Length: legLength(pts)}}
	for n := 0; n < rs.Count; n++ {
		tmpl := *rs.Template
		tmpl.Legs = legs
		e2 := newEnemy(tmpl, len(*c.enemies), [2]float64{float64(cx), float64(cy)}, c)
		*c.enemies = append(*c.enemies, e2)
		verdict.Events = append(verdict.Events,
			Event{T: t, Kind: "summon", Who: e2.spec.Name})
	}
}

// polluteFromEnemy 是原版 `_pollute_around`（`sim.py:1280-1303`）：在
// 「挡它的干员 / 它自己」脚下那一格半径 `radius` 内给田地加病害。
func (c *simCtx) polluteFromEnemy(e *enemy, amount float64, radius float64) float64 {
	if amount <= 0 {
		return 0
	}
	cx, cy := e.cell()
	if b := e.blockedBy; b != nil && b.alive() {
		// ⚠ 这一支原版用的是 `int(position)`（**截断**），与上面那支的
		// `e.cell()`（四舍五入）不是同一个口径——照抄，别"统一"。
		cx, cy = int(b.cell[0]), int(b.cell[1])
	}
	got := c.mechanisms.PolluteAround([2]int{cx, cy}, amount, radius)
	if got > 0 {
		c.Log("%s 蜕皮 → 田地病害 +%g 记入缓存", e.spec.Name, got)
	}
	return got
}

func (o *operator) take(amount float64) float64 {
	dealt := math.Min(o.hp, math.Max(0, amount))
	o.hurt(dealt)
	return dealt
}

// hurt 是干员**受击入账的唯一入口**：扣血、累计承伤、阵亡留痕，一次做完。
//
// 为什么必须收成一个口子：`take()`（敌方普攻/技能打的）与 `DamageOperator()`
// （机制直伤，怀黍离的田地病害走这条）是两条互不相干的路。早先只有前者留痕，
// 于是"被机制打倒"的干员在判决里只剩一个数量、没有时刻——而**时刻**才是对拍
// 要看的量：HS-EX-8 第 2 手原版机械师 56.3s 倒、怒潮凛冬 70.3s 倒，Go 只报
// "阵亡 2"，看不出是谁先塌的，也就找不到那 21% 的输出缺口。
func (o *operator) hurt(dealt float64) {
	if dealt <= 0 {
		return
	}
	o.hp = math.Max(0, o.hp-dealt)
	o.damageTaken += dealt
	if traceOn && o.sim != nil {
		// 每一笔都记：对拍要看的是**承伤曲线**，不是总量。原版那边三种来源
		// 各有明细（敌方普攻 / 敌方技能 / 田地病害）；两边总量相同而阵亡
		// 时刻差 6 秒时，只有曲线能指出是哪一路快了。
		trace("OPDMG t=%.4f op=%s dealt=%.3f cum=%.3f hp=%.3f",
			*o.sim.time, o.spec.Name, dealt, o.damageTaken, o.hp)
	}
	// 「圣山的祝福」：**受到致命伤害时不撤退**——免死一次、满血复活，并冻结
	// 自身若干秒（原版判在 `take()` 里，unit.py:643-650；分派到各调用方必然
	// 漏一处，而漏掉的那一处会让这个"免死一次"在某个伤害来源下悄悄失效——
	// 这一句是原版注释里的原话，也是它把判据放在掉血唯一入口的理由）。
	//
	// ⚠ 本条兑现的是"免死 + 满血复活 + 攻击范围内全体敌人冻结"。同一天赋里
	// **自身**冻结 N 秒（黑板 `freeze`）那半**未移植**——Go 侧还没有干员冻结/
	// 晕眩状态。所以这里**故意不写**自冻结计时器：没有消费点的字段就是假完成，
	// 它会让人以为这条天赋已经接完了。规格照送 `blessing_self_freeze`，那是
	// 给"哪天补上"留的接口，不是"已经生效"的证据。
	if o.hp <= 0 && !o.blessingUsed && o.spec.BlessingSave > 0 {
		o.blessingUsed = true
		o.hp = o.maxHP()
		// 空间查询留到**下一帧**兑现：掉血那一刻够不着地图（原版同理由，
		// sim.py:1065-1071：把空间查询塞进 `take()` 会让纯数值函数反向依赖
		// 整张地图）。差一帧，与原版同。
		o.blessingFreeze = o.spec.BlessingSave
		if traceOn && o.sim != nil {
			trace("BLESSING t=%.4f op=%s 免死→满血 %.1f（待冻结攻击范围内敌人 %.2fs；自冻结 %.2fs 未移植）",
				*o.sim.time, o.spec.Name, o.hp, o.spec.BlessingSave,
				o.spec.BlessingSelfFreeze)
		}
	}
	if o.hp <= 0 && !o.deathLogged && o.sim != nil {
		o.deathLogged = true
		// 措辞照原版日志那一行：`阵亡（承受 N 伤害）`。
		o.sim.verdict.Events = append(o.sim.verdict.Events, Event{
			T: *o.sim.time, Kind: "death",
			Who: fmt.Sprintf("%s（承受 %.0f 伤害）", o.spec.Name, o.damageTaken)})
	}
}

// blessingTick 兑现「圣山的祝福」欠下的那次"攻击范围内全体敌人冻结"
// （原版 `_blessing_tick`，sim.py:1065-1094）。
//
// 为什么欠一帧：免死发生在掉血那一刻（`hurt`），而那里够不着地图——原版的
// 理由一样（把空间查询塞进 `take()` 会让纯数值函数反向依赖整张地图）。
//
// 范围用的是**规格里那份归一化后的绝对格集合**（`spec.Range`，Python 侧
// `_range_of(op)` 同一来源），不是自己按射程重算一遍——重算就是第二套口径。
func blessingTick(ops []*operator, enemies []*enemy, t float64, verdict *Verdict) {
	for _, op := range ops {
		if op == nil || op.blessingFreeze <= 0 || !op.alive() {
			continue
		}
		secs := op.blessingFreeze
		op.blessingFreeze = 0
		cells := make(map[[2]int]bool, len(op.spec.Range))
		for _, c := range op.spec.Range {
			cells[[2]int{c[0], c[1]}] = true
		}
		hit := 0
		for _, e := range enemies {
			if !e.alive() || e.leaked || e.offMap {
				continue
			}
			cx, cy := e.cell()
			if !cells[[2]int{cx, cy}] {
				continue
			}
			// **取更大值**而不是覆盖：她已经冻着的敌人不该因为这次触发被缩短
			// （原版注释原话，与 `sluggish_timer` 的写法一致）。
			e.freezeTimer = math.Max(e.freezeTimer, secs)
			hit++
		}
		verdict.Events = append(verdict.Events, Event{T: t, Kind: "mech",
			Who: fmt.Sprintf("%s 圣山的祝福触发：生命值回满，攻击范围内 %d 名敌人冻结 %gs",
				op.spec.Name, hit, secs)})
		if traceOn {
			trace("BLESSING-TICK t=%.4f op=%s secs=%.2f hit=%d", t, op.spec.Name, secs, hit)
		}
	}
}

// resolveDamage 伤害结算（`battle/damage.py:resolve_damage` 的最小子集）。
//
// 物理 `max(atk - def, atk × 5%)`；法术 `max(atk × (1 - res/100), atk × 5%)`，
// 但 `res >= 100` 是**免疫**，保底不覆盖它；真实伤害就是 `atk`。
// 闪避在最小版本里没有（会走 `unsupported`）。
// resolveDamage 是原版 `damage.py::resolve_damage` 的那一路（`sim.py` 到处在用）。
//
// 次序照原文：先算防御/法抗，**再**按伤害类型折闪避（真实伤害两类都不吃闪避）。
// `dodge` 是受击方针对这个伤害类型的闪避比例（0.6 = 削掉 60%）——原版把它当期望值
// 线性折进去，Go 侧同样不掷骰。
//
// ⚠ 早先这个函数**没有闪避参数**，而原版的三条打人路（敌方普攻 3442、敌方技能
// 3536/3544、我方打敌方 3921）**都**在传闪避。24 例对拍语料里的干员恰好都没有
// 闪避，所以一直没暴露：那不是"两边一致"，是"这一路上两边都没走到"。
// 库里目前唯一带常驻闪避的是星熊的「战术装甲」（`DAMAGE_BLOCK_TALENTS` 只有它）。
func resolveDamage(atk float64, damageType string, scale, defense, res,
	dodge float64) float64 {
	raw := atk * scale
	floor := raw * 0.05
	var dealt float64
	switch damageType {
	case "MAGIC":
		if res >= 100.0 {
			dealt = 0
		} else {
			eff := math.Min(100.0, math.Max(-100.0, res))
			dealt = raw * (100.0 - eff) / 100.0
			if dealt < floor {
				dealt = floor
			}
		}
	case "TRUE":
		dealt = raw
	default: // PHYSICAL
		dealt = raw - math.Max(0, defense)
		if dealt < floor {
			dealt = floor
		}
	}
	if damageType != "TRUE" && dodge > 0 {
		dealt *= 1.0 - math.Min(1.0, math.Max(0.0, dodge))
	}
	return dealt
}
