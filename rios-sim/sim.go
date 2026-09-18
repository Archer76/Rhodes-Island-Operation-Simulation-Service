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
	"fmt"
	"math"
	"sort"
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

	attackTimer float64
	attackPause float64
	hits        int
	leaked      bool
	leakTime    float64
	deathTime   float64
	costAwarded bool

	index int //: 出生顺序（同分排序用，等价于原版敌人列表的顺序）
}

func (e *enemy) alive() bool { return e.hp > 0 }

func (e *enemy) reachedEnd() bool {
	return e.legIndex >= len(e.spec.Legs)
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
	slot        int //: 列表下标 = 部署顺序（敌人挑"最后部署的"要看它）

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
			e := &enemy{spec: sp, hp: sp.HP, legIndex: 0, index: cursor,
				deathTime: -1}
			// 起点 = 第一段的第一个点（`_build_enemy` 给的是 `pts[0]`）
			if len(sp.Legs) > 0 && len(sp.Legs[0].Points) > 0 {
				e.position = sp.Legs[0].Points[0]
			}
			enemies = append(enemies, e)
			verdict.Events = append(verdict.Events,
				Event{T: t, Kind: "spawn", Who: sp.Name})
			cursor++
			spawnsPlaced++
		}

		// ---- 3. 推进与计时器递减（1767-1806）
		for _, e := range enemies {
			if e.attackPause > 0 {
				e.attackPause = math.Max(0.0, e.attackPause-dt)
			}
			if e.alive() && !e.leaked && !e.offMap && e.blockedBy == nil &&
				e.attackPause <= 0 {
				// 关卡特有机制可以改这一只的推进速度乘区（如田地/阻流阀）；
				// 没挂机制时 `speedFor` 恒为 1.0，与最小版本逐位相同。
				advance(e, dt, spec.SpeedScale*ctx.speedFor(e.index))
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
		if !mechanisms.Empty() {
			mechanisms.EnvTick(ctx, dt)
		}

		// ---- 4. 阻挡（1846 → 2289）
		updateBlocking(ops, enemies)

		// ---- 5. 技能（原版 2156，**阻挡之后、我方出手之前**）
		//
		// 位置是定的：刚攒满技力的那一帧就得算数，晚一帧会让每次开技都慢一个 dt。
		skillTick(ops, dt, t, spec, &cost, verdict)

		// ---- 6. 我方出手（1870 → 2687）
		operatorsAttack(ops, enemies, dt, t, verdict)

		// ---- 7. 敌方出手（1873 → 2882）
		enemiesAttack(ops, enemies, dt, t, spec, verdict)

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
		if !e.alive() && !e.leaked {
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
	objs := *c.objs
	out := make([]mech.OpView, 0, len(objs))
	for i, o := range objs {
		out = append(out, mech.OpView{
			Index: i, CharID: o.spec.CharID, Name: o.spec.Name,
			Cell: o.spec.Cell, HP: o.hp, MaxHP: o.spec.MaxHP,
			Alive: o.alive(),
		})
	}
	return out
}

func (c *simCtx) Enemies() []mech.EnemyView {
	out := make([]mech.EnemyView, 0, len(*c.enemies))
	for _, e := range *c.enemies {
		out = append(out, mech.EnemyView{
			Index: e.index, Name: e.spec.Name, Position: e.position,
			HP: e.hp, Alive: e.alive(), Blocked: e.blockedBy != nil,
		})
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
	op.hp -= dealt
	op.damageTaken += dealt
	if op.hp < 0 {
		op.hp = 0
	}
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
	op.hp = math.Min(op.spec.MaxHP, op.hp+amount)
}

func (c *simCtx) ScaleEnemySpeed(index int, scale float64) {
	if c.speedReq == nil {
		c.speedReq = map[int]float64{}
	}
	c.speedReq[index] = scale
}

func (c *simCtx) Log(format string, args ...any) {
	c.verdict.Events = append(c.verdict.Events, Event{
		T: *c.time, Kind: "mech", Who: fmt.Sprintf(format, args...)})
}

// ================================================================ 推进

// advance 沿分段计划推进 dt 秒（`EnemyUnit._advance_legs`，unit.py）。
//
// 三种段共用 `legU`：走段里它是已走格数，等待/离场段里是已过秒数。
// 整个循环**以时间为预算**——按格数当预算的话，等待段会被移速缩放，
// 3 秒的待命会被拉成好几分钟。
func advance(e *enemy, dt, speedScale float64) {
	speed := e.spec.MoveSpeed * speedScale
	if speed <= 0 {
		return
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
	verdict *Verdict) {
	for _, op := range ops {
		if !op.alive() {
			continue
		}
		op.attackTimer += dt
		if op.attackTimer < op.interval() {
			continue
		}
		targets := pickTargets(op, enemies, op.maxTarget())
		if traceOn {
			trace("%8.4f %s 技=%v 间隔=%.4f 计时=%.4f 挡=%v 选=%v 范围里=%v",
				t, op.spec.Name, op.skillActive, op.interval(), op.attackTimer,
				names(op.blocking), names(targets), names(inRangeOf(op, enemies)))
		}
		if len(targets) == 0 {
			continue
		}
		op.attackTimer = 0
		scale := op.atkScale()
		hits := op.hitCount()
		finalScale, hasFinal := op.finalHitScale()
		power := op.atk()
		dmgType := op.damageType()
		for _, target := range targets {
			for i := 0; i < hits; i++ {
				if !target.alive() {
					break
				}
				hitScale := scale
				if hasFinal && i == hits-1 {
					hitScale = finalScale
				}
				dmg := resolveDamage(power, dmgType, hitScale,
					target.spec.DEF, target.spec.RES)
				dealt := target.take(dmg)
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
				if !target.alive() {
					target.deathTime = t
					verdict.Events = append(verdict.Events,
						Event{T: t, Kind: "kill", Who: target.spec.Name})
				}
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
		cell := [2]int{int(math.Round(e.position[0])), int(math.Round(e.position[1]))}
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

func inRangeOf(op *operator, enemies []*enemy) []*enemy {
	out := make([]*enemy, 0, 8)
	for _, e := range enemies {
		if e.hp <= 0 || e.leaked || e.offMap {
			continue
		}
		cell := [2]int{int(math.Round(e.position[0])), int(math.Round(e.position[1]))}
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
				op.defense(), op.res())
			dealt += op.take(dmg)
			if !op.alive() {
				op.deathTime = t
				verdict.Events = append(verdict.Events,
					Event{T: t, Kind: "death", Who: op.spec.Name})
				break
			}
		}
		// 受击回复的技力：这一下**真的掉血了**才回（原版 3301-3306）
		spOnHit(op, dealt)
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

func (e *enemy) take(amount float64) float64 {
	dealt := math.Min(e.hp, math.Max(0, amount))
	e.hp -= dealt
	return dealt
}

func (o *operator) take(amount float64) float64 {
	dealt := math.Min(o.hp, math.Max(0, amount))
	o.hp -= dealt
	o.damageTaken += dealt
	return dealt
}

// resolveDamage 伤害结算（`battle/damage.py:resolve_damage` 的最小子集）。
//
// 物理 `max(atk - def, atk × 5%)`；法术 `max(atk × (1 - res/100), atk × 5%)`，
// 但 `res >= 100` 是**免疫**，保底不覆盖它；真实伤害就是 `atk`。
// 闪避在最小版本里没有（会走 `unsupported`）。
func resolveDamage(atk float64, damageType string, scale float64,
	defense, res float64) float64 {
	raw := atk * scale
	floor := raw * 0.05
	switch damageType {
	case "MAGIC":
		if res >= 100.0 {
			return 0
		}
		eff := math.Min(100.0, math.Max(-100.0, res))
		dealt := raw * (100.0 - eff) / 100.0
		if dealt < floor {
			return floor
		}
		return dealt
	case "TRUE":
		return raw
	default: // PHYSICAL
		dealt := raw - math.Max(0, defense)
		if dealt < floor {
			return floor
		}
		return dealt
	}
}
