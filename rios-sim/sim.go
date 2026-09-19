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

// : 攻速下限（`间隔 = 基础间隔 × 100 / max(攻速下限, 总攻速)`）。
// : 与原版同一口径：`unit.py` / `operator/skill.py` 的 `ASPD_MIN = 20`
// : （2026-09-16 博士裁定：wiki 写 20、akdata 写 10，取 20）。
const aspdMin = 20.0

// : 【寒冷】的攻击速度折减。出处：PRTS《敌人一览/数据》tooltip 词典——
// : 「寒冷：攻击速度下降 30，如果在持续时间内再次受到寒冷效果则会变为冻结」。
// : 这是项目此前**明确记为"拿不到"**的那个数（`异常效果`页不给数、
// : `excel/buff_table.json` 两个公开镜像都 404），2026-09-19 由博士提供该页解开。
const coldASPDDown = 30.0

// : 【冻结】期间敌方法术抗性的降低值。与 `coldASPDDown` 同一条 tooltip：
// : 「冻结：……敌方被冻结时，法术抗性-15」。**动态**生效（冻结一结束就恢复），
// : 所以读法走 `enemy.res()` 而不是把 −15 写进 `spec.RES`。
// : ⚠ 判据来源订正（2026-09-19）：上面那句 tooltip 读起来像"看**目标阵营**"，
// : 但 PRTS `可抵抗状态` 页写明「**仅友方冻结**会令目标法术抗性-15（直接加算），
// : **与被冻结的是否是敌方单位无关**……敌人施加的均为敌方冻结」——**看的是施加方**。
// : 权威页更具体、且明确排除了目标阵营这条读法，故以它为准（见 `freezeFriendly`）。
const frozenResDown = 15.0

type enemy struct {
	spec SpawnSpec

	hp        float64
	position  [2]float64
	progress  float64
	legIndex  int
	legU      float64
	offMap    bool
	blockedBy *operator

	//: ---- 天桩-乙（`spec.Diver`；原版 `_pile_diver_tick`，帧序 3.9）
	//:
	//: 三件状态缺一不可，少哪个都会让乙"已经贴上去了还在扑"或者"扑不完就自毁"：
	//: `diverIdle`（登场自缚，剩余秒数；出怪表刷的乙是 0）、
	//: `diverBitten`（已咬过一口，原版 `attacked_once`）、
	//: `diverBoomAt`（自毁时刻，-1 = 还没排）。
	diverIdle   float64
	diverBitten bool
	diverBoomAt float64

	//: ---- 身上的天标（原版 `_pile_attach_mark` / `_pile_mark_tick`）
	//:
	//: 它**同时是两样东西**，缺哪一样都会差一次：① 每秒对附着对象结算一次
	//: `attachDamage`（定额、不吃防御也不吃法抗）；② 它自己是一个 `hp=1.0`
	//: 的**普通敌人**，会被我方索敌——`act31side_09` 的出手账里原版就有一笔
	//: `t=47.1000 → 身上的天标 1.00`。所以它是**造一个敌人**，不是给干员挂 buff。
	//:
	//: `attached` 是**登场那一刻的快照**（原版 `mark.attached`），不是每帧现算：
	//: 附着范围内的单位是"那一刻站在这一格的人"。
	attachDamage float64
	attachRadius float64
	attachTimer  float64
	attached     []*operator

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

	//: 积雪写的那一半冻结（原版 `sim.py:1156` 由 `_snow_tick` 置位；
	//: 每帧先被重置成 false）。与 `freezeTimer` 合成原版的 `frozen`——
	//: 读写都走 `frozen()` 这一个入口，见 `simCtx.SetEnemyFrozen`。
	frozenSnow bool

	//: **推进门控专用的锁存值**，每帧在递减计时器**之前**算一次
	//: （`= freezeTimer > 0 || frozenSnow`）。
	//:
	//: ⚠ 它存在的唯一理由是原版的 `e.frozen` 是个**锁存字段**而非现算判据：
	//: 它由上一帧的 `_snow_tick`（`sim.py:1139`）写，而 `advance()` 在本帧
	//: 递减 `freeze_timer` **之后**才读它 → 读到的是**减之前**的值。
	//: 详见主循环 3 那一段的长注释。除推进门控外一律用 `frozen()`（现算），
	//: 因为 `_enemies_attack`（原版 :2851）跑在 `_snow_tick`（:2773）**之后**。
	frozenLatched bool

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
	//: 上面这段冻结是**友方冻结**还是**敌方冻结**。
	//:
	//: 判据出处（2026-09-19 抓到，PRTS `可抵抗状态` 页原文）：
	//: 「游戏中存在两类冻结：敌方冻结与友方冻结（颜色偏绿）。**仅友方冻结**会令目标
	//:   法术抗性-15（直接加算），**与被冻结的是否是敌方单位无关**。站内没有明确
	//:   注明的情况下，干员与我方召唤物直接施加的均为友方冻结，敌人施加的均为敌方冻结。」
	//:
	//: ⚠ 这一条**推翻**了本文件 2026-09-19 早些时候按 tooltip 词典写的判据
	//: （「敌方被冻结时，法术抗性-15」）。词典那句话读起来像"看目标是不是敌人"，
	//: 而权威页明说"**与被冻结的是否是敌方单位无关**"——看的是**施加方**。
	//: 本项目目前唯一的冻结来源（圣山的祝福、积雪）都是干员给的，所以既有行为不变；
	//: 但这个字段必须在，否则哪天敌人之间互相冻结就会凭空多出 −15。
	freezeFriendly bool
	//: 【寒冷】剩余秒数（原版 `cold_timer`）。
	//:
	//: 数值效果出自 **PRTS《敌人一览/数据》** 的 tooltip 词典（2026-09-19 博士提供）：
	//: 「寒冷：**攻击速度下降 30**，如果在持续时间内**再次**受到寒冷效果则会变为冻结」。
	//: 折减落在 `interval()`（与干员侧同一条攻速公式），"再次中招转冻结"落在
	//: `applyCold()`。此前这条数两台引擎都拿不到——见 `docs/mechanics-dictionary.md`。
	coldTimer float64

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
	e := newEnemy(spec, c.nextEnemyIndex, cell, c)
	c.nextEnemyIndex++
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
		//: 天桩-乙的自毁时刻从 -1 起步（0 会被读成"开局就该自毁"）。
		diverBoomAt: -1.0,
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
	//: 【冻结】剩余秒数（原版 `OperatorUnit.freeze_timer`，`unit.py` 的
	//: `Combatant` 字段）。干员侧的冻结 = **缴械**：`_operators_attack` 开头
	//: 有一道 `if op.freeze_timer > 0: continue`（`sim.py:3978`），
	//: **连出手计时器都不走**；但它**不动阻挡**（这是它与晕眩的区别，
	//: 所以不能拿晕眩的字段顶替）。
	//:
	//: ⚠ 这个字段的消费点曾经**整条缺失**：`hurt` 里早就送了
	//: `spec.BlessingSelfFreeze`，但没有任何地方读它——"没有消费点的字段
	//: 就是假完成"，判决上只表现为"某一门干员比原版多出手几次"。
	//: 来源：`hurt`（圣山祝福的自冻结）；递减：`skillTick`。
	freezeTimer float64
	//: 【增益治疗】（天赋「医者丰碑」）剩余秒数。**从吃到那一刻起算**，
	//: 与光环主人是否还活着**无关**——原版把这句话写在 `RegenAura.tick` 里：
	//: 「增益已经挂在身上了，就算光环本人倒掉也照样跳完」（`talents.py:811`）。
	regenLeft float64
	//: 这份增益的**每秒回复量**（已按势力翻过倍）。与 `regenLeft` 成对：
	//: 归零时两个一起清。
	regenPerSec float64
	//: 已经吃过哪些光环主人的增益（按**光环主人在 `ops` 里的下标**）。
	//: 「不可叠加」= 同一个人只触发一次；按主人分账是因为场上可能不止一位
	//: 带这条天赋的干员，各自独立计数（原版 `granted` 是挂在 aura 上的集合）。
	regenGrantedBy []int
	//: 【全场光环】当前对这**一位**干员生效的攻击力 / 防御力比例（原版
	//: `op.aura_atk_pct` / `op.aura_def_pct`，由 `_refresh_auras` 每帧刷）。
	//:
	//: 为什么每帧刷而不是部署时一次定死：「光环主人开技能期间效果加倍」是
	//: 随时间变的。多条光环**相加**（不是连乘）。
	//:
	//: 怎么折进面板：原版是 `self.atk * (1 + … + aura_atk_pct)`，也就是光环
	//: 的贡献 = `self.atk × aura_atk_pct`，其中 `self.atk` 是**底子**（不含技能
	//: 增益）。Go 侧 `spec.ATK` 正是那个底子——所以加成是**加上去**、
	//: 不是在技能面板上**乘上去**（两者在有技能时不等价）。
	auraAtkPct  float64
	auraDefPct  float64
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

	// ---- 层数护盾（原版 `OperatorUnit.shield_*`，`unit.py:412-421`）
	//:
	//: 语义是**次数制抵挡**、不是一条可以吸的血条：`interval` 秒加一层、上限
	//: `maxLayers` 层、部署时给 `layers` 层，**任何一次受伤消耗一层并把这一下
	//: 整笔归零**（`unit.py:613-620`）。破裂时按 `breakHeal` 回血、按 `breakSP`
	//: 给技力——位置在屏障分支**之前**（伤判顺序：先裂、先回血，再把伤害归零）。
	//:
	//: 为什么单列一段而不是蹭 `blessingUsed` 之类的现成字段：它是**唯一会
	//: 把伤害整笔吃掉**的干员侧机制，而这一族在 Go 里长期**一个字都没有**。
	//: 代价实测（`tr02`，单人泥岩）：原版她前三下**一下都没挨**（`take(0)`），
	//: Go 每下按 5% 保底扣 14.5 ⇒ 她在 Go 里提前阵亡、187.33s 三漏判负，
	//: 而原版打到 430.13s、零漏。判决四项里**只看得到这个结果，看不到原因**。
	shieldLayers    int     //: 当前层数
	shieldMaxLayers int     //: 上限
	shieldBreaks    int     //: 累计破裂几层（层数会被补回来，看它看不出发生过几次）
	shieldTimer     float64 //: 「每 N 秒加一层」的计时
	shieldInterval  float64
	shieldBreakHeal float64 //: 破裂回血（原版是 `ratio × max_hp`，部署时算死）
	shieldBreakSP   float64 //: 破裂给技力

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

	//: 天赋「强击瓶专家」的剩余轮数。**部署后首次开技**时置为 `spec.PowerAttackCount`
	//: （原版 `sim.py:2448` 读 `sp_charges == 0`，位置在它自增**之前**），
	//: 之后每出一轮扣一层。每次部署都从 0 起——所以它和技能状态一起清。
	powerAttackLeft float64
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
		time: &t, frame: &frameNo, verdict: verdict,
		//: 召唤物的下标发号从**出怪表之后**开始。见 `simCtx.nextEnemyIndex`。
		nextEnemyIndex: len(spec.Spawns)}
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
			// 「医者丰碑」的增益是**跟着这一次部署**的：撤了再下等于换了一个人，
			// 上一局吃到的那份不跟过来（原版每次部署都是全新的 OperatorUnit，
			// 那几个字段自然从零起）。
			//
			// ⚠ `regenGrantedBy` **不在这里清**：原版那个"吃过没有"的集合是挂在
			// **光环主人**身上的（`aura.granted`），友方重新部署**不会**把它抹掉
			// （它按名字记）。Go 侧改用主人的 `deploySeq` 作键，语义等价：
			// 主人每次部署都是新的一份光环、历史为空。
			op.regenLeft = 0
			op.regenPerSec = 0
			op.auraAtkPct = 0
			op.auraDefPct = 0
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
			// 「强击瓶专家」的剩余层数也从零起：它由**本局的首次开技**点亮，
			// 上一局的余量带过来会让这一局开场就多打几十轮加成。
			op.powerAttackLeft = 0
			if sk := op.spec.Skill; sk != nil && !sk.Passive {
				op.sp = sk.InitSP
			}
			// ---- 层数护盾（原版 `_attach_talent_shield`，`sim.py:3157-3182`，
			// 在 `_do_deploy` 里、紧随部署时技能/天赋效果之后）
			//
			// ⚠ 破裂回血是**在这里定死的**：原版写的是
			// `op.shield_break_heal = ratio × op.max_hp`，用的是**部署那一刻**的
			// 生命上限。规格只送比例，正是为了让两边都用"此刻"的上限——
			// 送绝对值就把那个时刻固化了，日后任何改上限的机制都会让两边对不上。
			op.shieldLayers = 0
			op.shieldMaxLayers = 0
			op.shieldBreaks = 0
			op.shieldTimer = 0
			op.shieldInterval = 0
			op.shieldBreakHeal = 0
			op.shieldBreakSP = 0
			if sh := op.spec.Shield; sh != nil && sh.MaxLayers > 0 {
				op.shieldMaxLayers = sh.MaxLayers
				op.shieldInterval = sh.Interval
				op.shieldBreakHeal = sh.BreakHealRatio * op.maxHP()
				op.shieldBreakSP = sh.BreakSP
				//: 部署时那几层：原版是一层层调 `_grant_shield_layer`，
				//: 到上限即作废——所以这里也夹一次，别直接赋 `sh.Layers`。
				for i := 0; i < sh.Layers; i++ {
					if op.shieldLayers >= op.shieldMaxLayers {
						break
					}
					op.shieldLayers++
				}
				if traceOn {
					ctx.Trace("SHIELD t=%.4f op=%s 部署授予 %d/%d interval=%.3f "+
						"breakHeal=%.3f", t, op.spec.Name, op.shieldLayers,
						op.shieldMaxLayers, op.shieldInterval, op.shieldBreakHeal)
				}
			}
			ops = append(ops, op)
			onField[d.CharID] = op
			// 部署瞬间的**一次性**环境伤害（原版 `sim.py:3383-3394`，在 `_do_deploy`
			// 里：技能/天赋的部署时效果之后，扣费用与建积雪之前）。
			//
			// ⚠ 这一下**额外于**每秒结算，不是它的第一次——原文是两句分开的话
			//（「部署时立刻受到 …」与「每秒受到 …」），加起来才是落地那一秒的总量。
			// 并进 `EnvTick` 会让"落地那一拍不整秒"的干员少挨一整下。
			//
			// 本来这条在机制层是**实现了、也有黄金测试、却一个调用点都没有**的：
			// 规格在、算术在、单测绿，模拟里一次都没跑过。实测代价见 `DeployDamager`。
			dmg := mechanisms.DeployDamage(op.spec.Cell)
			// 打痕迹而不是只改数字：这一下没有别的可观测量，事后只能从承伤账
			// 反推"是不是少挨了一整下"，而从下游猜是猜不是测。
			// **无条件打**（含 dmg=0 的情形）：为 0 才是最需要看见的那种情况——
			// 分不清"这一下不适用"与"落位格读错了"。
			ctx.Trace("DEPLOYDMG t=%.4f name=%s cell=%d,%d dmg=%.3f",
				t, op.spec.Name, op.spec.Cell[0], op.spec.Cell[1], dmg)
			if dmg > 0 {
				dealt := op.take(dmg)
				ctx.Trace("DEPLOYDMG t=%.4f name=%s 扣血 dealt=%.3f 余=%.3f",
					t, op.spec.Name, dealt, op.hp)
				verdict.Events = append(verdict.Events, Event{
					T: t, Kind: "env", Who: op.spec.Name})
			}
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
			// ⚠⚠ **必须先锁存 `frozen`，再递减计时器**——本文件里最容易写错的一处。
			//
			// 原版的 `e.frozen` **不是**一个现算的复合判据，而是一个**锁存字段**：
			// 它只在两处被写——`_snow_tick` 的 `sim.py:1139`
			// （`e.frozen = e.freeze_timer > 0.0`）和圣山祝福的 `:1088`。
			// 而 `advance()` 读的就是这个字段。帧序于是是：
			//
			//	本帧 :2755  减 `freeze_timer`
			//	本帧 :2761  `advance()` 读 `e.frozen` ← **上一帧锁的值**
			//	本帧 :2773  `_snow_tick` 重新锁一次
			//
			// 所以推进门控用的是**减之前**的 `freeze_timer`：冻结在最后一帧仍然
			// 生效，要再等一帧才动。
			//
			// Go 原来写成 `!e.frozen()`（现算、且在递减之后）＝把冻结算**晚**了一帧，
			// 于是敌人**早一帧**解冻。HS-EX-8 第 3 手实测：厌肮@12.5 在 Go 侧
			// t=71.3333 就开始走，原版要到 t=71.3667，差值恰好一帧位移（0.0064 格），
			// 一路累出判决上的 −0.5 秒。
			//
			// 注意 `attackPause` / `sluggishTimer` **不是**这样：那两个是 `advance()`
			// 现读的，所以它们"先减再判"才是对的（见下面那段注释）。别把三者一起改。
			e.frozenLatched = e.freezeTimer > 0 || e.frozenSnow
			if e.attackPause > 0 {
				e.attackPause = math.Max(0.0, e.attackPause-dt)
			}
			if e.sluggishTimer > 0 {
				e.sluggishTimer = math.Max(0.0, e.sluggishTimer-dt)
			}
			if e.freezeTimer > 0 {
				e.freezeTimer = math.Max(0.0, e.freezeTimer-dt)
				// 冻完了就把来源形别一起清掉：留着它，下一段"敌方冻结"会继承上一段的
				// 友方形别，凭空多出 −15（这正是"改写类机制要单一入口"的那类坑）。
				if e.freezeTimer == 0 {
					e.freezeFriendly = false
				}
			}
			// 【寒冷】与它们同一类：`interval()` 是**现读** coldTimer 的，
			// 所以"先减再判"才是对的（别和 `frozenLatched` 那个锁存值混）。
			if e.coldTimer > 0 {
				e.coldTimer = math.Max(0.0, e.coldTimer-dt)
			}
			// 积雪写的那一半冻结**每帧在这里重置**（原版 `sim.py:1139`
			// `e.frozen = e.freeze_timer > 0`，写在推进那一段里）。本帧稍后的
			// 帧序 3.5 由积雪重新置位。
			//
			// ⚠ 这一句**必须由主循环做**，不能只放在积雪那一层里：没有积雪的
			// 关卡上"上一帧留下的 true"就永远没人清，而它会同时挡住推进与出手
			// ——症状是"敌人莫名停住"，且只在挂过雪的那一局里出现。
			e.frozenSnow = false
			if e.alive() && !e.leaked && !e.offMap && e.blockedBy == nil &&
				e.attackPause <= 0 && e.sluggishTimer <= 0 && !e.frozenLatched {
				// 关卡特有机制可以改这一只的推进速度乘区（如田地/阻流阀）；
				// 没挂机制时 `speedFor` 恒为 1.0，与最小版本逐位相同。
				//
				//: ⚠ 两个乘区**分开传**，不要在调用点先乘起来——原版是
				//: `move_speed * speed_scale * speed_multiplier * …` 逐项连乘，
				//: 提前合并会改末位，见 `advance` 的注释。
				advance(e, dt, spec.SpeedScale, ctx.speedFor(e.index))
			}
			// 逐帧坐标（按名字门控，见 `tracePosName`）。`blocked/sluggish/freeze`
			// 一起记：坐标不动有三种截然不同的原因，不写清楚就得分不出来。
			if traceOn && tracePosName != "" && e.spec.Name == tracePosName {
				// ⚠ `x`/`y`/`legu` 打到 **17 位有效数字**（`%.17g`，双精度的往返精度）。
				// 4 位精度下前半程完全看不出滴漏；**7 位同样不够**——`hsex07`
				// 那只除秽的 x 原版是 `7.4999999999999885`、Go 是 `7.5`，
				// 差 1.15e-14，`%.7f` 两边都显示 `7.5000000`，等于没有痕迹。
				// 而这一点点差正好把落格从 7 翻到 8、把主目标翻成溅射受害者
				// （见 `AK-TACTIC-进度.md` §3.15）。
				// `cell` 单列一项：判决只认落格，坐标只是通往落格的中间量。
				// 冻结那一列**必须两半都打**：`freeze` 是计时器那一半，`snow` 是
				// 积雪那一半，`latch` 才是推进门控真正读的值。
				//
				// ⚠ 更隐蔽的一点：痕迹跑在**本帧 `frozenSnow` 已被重置之后**，
				// 所以"敌人明明被雪冻住"的那一刻，`snow=` 恰好显示 `false`、
				// 而 `latch=true`。**这不是矛盾，是顺序**——只看 `freeze`/`snow`
				// 会得出"没有原因却不动"，我为此白追了一轮。
				trace("POS t=%.4f idx=%d name=%s x=%.17g y=%.17g cell=%d,%d hp=%.1f blocked=%t pause=%.2f sluggish=%.2f freeze=%.4f snow=%t latch=%t leg=%d legu=%.17g",
					*ctx.time, e.index, e.spec.Name, e.position[0], e.position[1],
					int(math.RoundToEven(e.position[0])), int(math.RoundToEven(e.position[1])),
					e.hp,
					e.blockedBy != nil, e.attackPause, e.sluggishTimer, e.freezeTimer,
					e.frozenSnow, e.frozenLatched,
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
		//
		// ⚠ **积雪排在 `blessingTick` 之前**（原版 `sim.py:2773` 在 2775 之前），
		// 而且必须排在**这一帧的推进之后**：它要判"敌人这一帧踏进了哪一格"，
		// 写下的减速给**下一帧**的 `advance` 用（见 `mech.SnowTicker`）。
		// 挪到推进之前，踏入判定会晚一帧、减速也晚一帧生效。
		if !mechanisms.Empty() {
			mechanisms.SnowTick(ctx, dt)
		}
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

		// 出怪表刷出来的天桩-乙**不在** `mechanisms` 的记账里（那边只管装置
		// 召唤的甲/乙/天标），但它们照样要跑 `_pile_diver_tick`——原版
		// `_pile_tick` 的第 ② 段是**遍历全体敌人**按类型分派（`sim.py:4651`）。
		pileDiverTick(enemies, ops, t, ctx)
		// 天标的每秒结算。⚠ 与 `pileDiverTick` 的**帧内交错**同样没有对齐：
		// 原版三种单位在同一次遍历里按敌人列表顺序分派（`sim.py:4651`），
		// 这里是"甲/乙跑完再跑天标"。本关没有装置召唤的甲，所以先按这个顺序落。
		pileMarkTick(enemies, t, dt)

		// ---- 4. 阻挡（1846 → 2289）
		updateBlocking(ops, enemies)

		// ---- 5. 技能（原版 2156，**阻挡之后、我方出手之前**）
		//
		// 位置是定的：刚攒满技力的那一帧就得算数，晚一帧会让每次开技都慢一个 dt。
		skillTick(ops, dt, t, spec, &cost, verdict)

		// ---- 5.4 全场光环（原版 2831-2832）
		//
		// 位置是定的：排在**技能之后**——「光环主人开技能期间效果加倍」是随
		// 技能状态变的，本帧刚开的技能必须本帧就吃到加倍，不然会晚一帧。
		if len(ops) > 0 {
			teamAuraTick(ops)
		}

		// ---- 5.5 天赋「医者丰碑」的增益治疗（原版 2834-2840）
		//
		// 位置是定的：排在**技能之后**（本帧刚上场的干员当帧就能吃到），
		// 又在**我方出手之前**（这一帧治回来的血，出手前就已经在身上）。
		regenAuraTick(ops, dt)

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
		//: **跑满上限时还剩谁**（原版 `BattleResult.leftover_units`，sim.py:2899）。
		//: 判据与原版收尾那一段逐字一致：活着且没漏的。
		//: 「清不掉」那一项就是结束判据里被忽略的那一类——它非空时这一局
		//: **永远收不了场**，而杀/漏/伤害可以全对。
		if e.alive() && !e.leaked {
			verdict.Remnants = append(verdict.Remnants,
				[2]any{e.spec.Name, e.cannotClear()})
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

	//: **召唤物的下标发号器**（见 `Summon`）。
	//:
	//: ⚠ 出怪表的敌人下标是它的**排期位置**（`0 … len(Spawns)-1`，主循环里就是
	//: `cursor`），而召唤物曾经用 `len(*c.enemies)` 发号——那只是"**此刻已经上场
	//: 几只**"，在出怪表跑完之前**恒小于** `len(Spawns)`。于是任何一次召唤都会
	//: 与**还没出场的某只表内敌人**撞下标。
	//:
	//: 下标不是"编号"而是**身份**：`lastCell`/`firstOn`（积雪）、`speedReq`、
	//: `frozenSnow`、天桩链的写血通道全按它记账。撞号之后两个实体轮流写同一个
	//: 槽位，症状是"某格的首敌归属永远清不掉"——判决上看不出，机制上全错。
	//:
	//: 实测（HS-EX-8，k=3）：`idx=5` 同一帧同时属于「失控天桩-甲」与「除秽」。
	nextEnemyIndex int
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
			// `atk()` 而不是 `op.spec.ATK`：后者是"无技能帧的定值"，
			// 而积雪的踏入伤害读的是**当前**攻击力（会随技能开关变）。
			ATK: op.atk(),
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
			Leaked: e.leaked, OffMap: e.offMap, Frozen: e.frozen(),
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
		// `op.defense()` 而不是 `op.spec.DEF`：原版走的是 `current_defense()`，
		// 含技能增益、固值加成与**全场光环**（`unit.py:851`）。读规格那个定值
		// 会把光环给的防御整个漏掉，而且**不报错**。
		dealt = math.Max(raw-op.defense(), raw*0.05)
	}
	// ⚠ **必须走 `take`，不能直接 `hurt`。** 原版的机制直伤与敌方普攻是**同一个**
	// 入口（`op.take(...)`，`sim.py` 的 `_environment_tick` 就是这么写的），
	// 而「层数护盾」那道闸门就在 `take` 里（`unit.py:612-622`）：
	// 有一层就把这一下**整笔吃掉**，并按 `shield_break_heal` 回血。
	//
	// 这里曾经写 `op.hurt(dealt)`，于是**机制直伤无视层数护盾**——
	// `hsex07` 的泥岩上暴发成：t=81.0333 补的那一层没被 t=82.0 的田地病害
	// （430）吃掉，一直留到 86.3333 才破，导致它在 t=82.0 白掉 430 血、
	// 比原版早**一帧**阵亡（89.3333 vs 89.3667）。一帧之差让天桩甲改扑凯尔希，
	// 4 枚天标的归属整体挪位，可露希尔少打 4 手——判决差出 伤害 −1,100.8。
	//
	// 层数护盾的**次数制**在这里特别容易漏：它不是"少减一点伤害"，
	// 而是"这一笔完全不进血"，且会**回血**。走 `take` 才有这两件事。
	op.take(dealt)
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

// HitEnemy 施加机制发起的一次**分类型**伤害（原版 `_damage_enemy` 那一路）。
//
// 与 `HitOperator` 对称，方向相反：倍率由机制算好（`raw` = 攻击力 × 倍率），
// 防御/法抗/闪避与 5% 保底由主循环按这一只**这一刻**的数值结算；
// 无敌窗口、蜕皮叠层、加速、明识形态记名也一并走主循环那唯一的出口
// （`enemy.take` → `simCtx.onEnemyHit`）。
//
// 第一个使用者是**积雪的踏入伤害**（原版 `_snow_hit`）：`magic_scale ×
// 干员当前攻击力`，**走正规法抗结算、不吃物理的 5% 保底**——所以这里必须
// 分类型，不能复用 `DamageEnemy(trueDamage)` 那种真伤通道。
//
// `src` 是伤害来源的干员下标；机制造成的伤害通常没有明确来源，传 -1
// （原版 `_damage_enemy(..., source=None)`：明识形态的记名会因此跳过，
// 而那正是原版的写法）。
func (c *simCtx) HitEnemy(index int, raw float64, damageType string, src int) float64 {
	e := c.enemyAt(index)
	if e == nil || raw <= 0 {
		return 0
	}
	var source *operator
	if src >= 0 {
		objs := *c.objs
		if src < len(objs) {
			source = objs[src]
		}
	}
	dealt := e.take(resolveDamage(raw, damageType, 1.0,
		e.spec.DEF, e.res(), e.dodgeVs(damageType)), source)
	if dealt > 0 {
		// 打向敌人的伤害在这里累计（原版 `_damage_enemy` 里的
		// `result.damage_dealt += dealt`）。与 `splashHit` 同一口径。
		c.verdict.DamageDealt += dealt
		if !e.alive() && !e.pendingReborn() {
			e.deathTime = *c.time
			c.verdict.Events = append(c.verdict.Events,
				Event{T: *c.time, Kind: "kill", Who: e.spec.Name})
		}
	}
	if traceOn {
		trace("HITENEMY t=%.4f enemy=%s raw=%.3f type=%s dealt=%.3f hp=%.3f",
			*c.time, e.spec.Name, raw, damageType, dealt, e.hp)
	}
	return dealt
}

// IsGoalCell 回答"这一格是不是防守点"（原版 `_is_goal`：`tile_end`）。
//
// Go 没有地图（`wire.go` 文件头那条原则），所以这份几何由 Python 随规格送来
// （`snow.go` 规格里的 `goal_cells`）。积雪的满层冻结要用它：**终点格豁免**——
// 把已经踏到终点的敌人冻在离终点半格处，它永远到不了终点，等于白送一条命。
//
// ⚠ 与 `spec.HighlandCells` 同一个口径：**不在表里就当没有**。所以 Python 侧
// 漏送 `goal_cells` 的症状是"终点格也被冻"——那会让漏怪数**变少**，
// 是一眼能看出的那种偏差；反过来漏送高台格是"溅射少一段"，两者都不许静默。
func (c *simCtx) IsGoalCell(cell [2]int) bool {
	for _, g := range c.spec.GoalCells {
		if g == cell {
			return true
		}
	}
	return false
}

// SetEnemyFrozen 把一只敌人标记为**被冻住**（原版 `e.frozen`）。
//
// ⚠ 原版的 `frozen` 是**复合判据**（`sim.py:1139`）：每帧重置成
// `freeze_timer > 0`，然后由积雪在 1156 那一行补上"所站格满层"。守这个字段的
// 是"不推进、不出手"两处闸门，所以少写一半的后果是**冻结静默失效**——
// 敌人照走照打，而判决上看不出"是冻结没生效"还是"本来就没人冻它"。
//
// 于是实现上分成两个字段：`frozenSnow` 是机制写的那一半（本方法），
// `freezeTimer` 是计时器那一半。读的地方一律用 `e.frozen()`（复合）。
func (c *simCtx) SetEnemyFrozen(index int, on bool) {
	if e := c.enemyAt(index); e != nil {
		e.frozenSnow = on
	}
}

// HitOperator 施加机制发起的一次**分类型**伤害（原版 `resolve_damage` 那一路）。
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
// `e.route = [op.cell]` ＋ `e.legs = []`，一条单点路线永远走不完，于是它既不动
// 也不会漏怪。⚠ 只改位置而不换路线是个真错：旧的那条飞行路线还挂着，下一帧
// `advance` 会沿着它继续往前挪（实测 HS-S-1 就是这么让一只乙在自毁前多挨了一下）。
func (c *simCtx) SetEnemyRoute(index int, points [][2]float64) {
	e := c.enemyAt(index)
	if e == nil || len(points) == 0 {
		return
	}
	setRoute(e, points)
}

// setRoute 把一名敌人的路线**整个换掉**（原版就是直接写 `e.route` / `e.legs`）。
//
// 天桩-乙每帧都会调它（`_pile_diver_tick` 的两支：扑向目标 / 贴上去后钉住），
// 所以它与 `SetEnemyRoute` 必须是**同一段实现**——两份的话，"钉住"那一支
// 迟早只在一边改对。单点路线给 `static`（不动，也不会被判成走到终点）。
func setRoute(e *enemy, points [][2]float64) {
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

// pileDiverTick 是**出怪表刷出来的**天桩-乙的行为（原版 `_pile_diver_tick`，
// `sim.py:4734-4785`，帧位 3.9）。
//
// 为什么它不在机制层：原版跑这段的 `_pile_tick` 第 ② 段是**遍历全体敌人**
// 按类型分派（`sim.py:4651-4659`），`_pile_mark_key` 认的是**所有**乙，
// 不区分"装置召唤的"还是"出怪表刷的"。机制层的 `PileTick` 只管它自己的
// `m.units`（`huai_shu_li.go:192`）——本关一个天桩装置都没有，那边的记账是空的，
// 于是这些乙在 Go 里**没人推**，只会沿出怪表的腿一路走出图外漏掉。
//
// ⚠ 与机制层的**帧内交错**没有对齐：原版三种单位在同一次遍历里按敌人列表顺序
// 分派，这里是"机制层跑完再跑这一段"。本关（无天桩装置）两者不可能同时非空，
// 所以先按这个顺序落；将来遇到"既有装置召唤的乙、又有出怪表刷的乙"的关卡，
// 要回来把两者合进同一次遍历。
func pileDiverTick(enemies []*enemy, ops []*operator, t float64, c *simCtx) {
	for _, e := range enemies {
		if !e.spec.Diver {
			continue
		}
		//: 原版 `_pile_tick` 第 ② 段的四道闸门（`sim.py:4652`）
		if e.hp <= 0 || e.leaked || e.offMap || e.rebornAt >= 0 {
			continue
		}
		// ① 「攻击结束时强制击杀自身」。走**直接写血**（原版 `e.hp = 0.0`）：
		//    按原版注释，"这不是我方击杀，也不该触发任何『被击倒』类效果"。
		//    Go 的击杀数在挨打那条路上记账，直接写 hp 不会进 `verdict.Kills`；
		//    而乙的 `kill_cost` 本来就是 0，结算里那条奖励也不会触发。
		if e.diverBoomAt >= 0 && t >= e.diverBoomAt {
			e.hp = 0
			e.deathTime = t
			if traceOn {
				trace("PILEBOOM t=%.4f enemy=%s idx=%d", t, e.spec.Name, e.index)
			}
			continue
		}
		// ② 登场自缚没走完，或已经咬过一口了 → 什么都不做
		if e.diverIdle > 0 || e.diverBitten {
			continue
		}
		// ③ 最近的**存活**干员。原版不设距离上限：正文写的是「扑到…身上」，
		//    而数据里 `rangeRadius = −1`，加一个上限就是凭空造数
		//    （两种读法都登记在 `docs/verdicts-pending.md`）。
		target := nearestAliveOperator(ops, e.position)
		if target == nil {
			continue
		}
		dx := target.cell[0] - e.position[0]
		dy := target.cell[1] - e.position[1]
		if math.Hypot(dx, dy) <= 0.5 {
			// 已经贴到目标格：钉住——换成单点路线，免得"走到路线终点"被判成漏怪
			setRoute(e, [][2]float64{target.cell})
			dmg := resolveDamage(e.spec.ATK, e.spec.DamageType, 1.0,
				target.defense(), target.res(), target.dodgeVs(e.spec.DamageType))
			dealt := target.take(dmg)
			spOnHit(target, dealt)
			e.diverBitten = true
			e.diverBoomAt = t + c.EnemyWindup()
			attachMark(e, target, ops, t, c)
			if traceOn {
				trace("PILEBITE t=%.4f enemy=%s idx=%d target=%s dealt=%.3f boom=%.4f",
					t, e.spec.Name, e.index, target.spec.Name, dealt, e.diverBoomAt)
			}
			continue
		}
		// ④ 还没到 → 朝目标扑。**每帧都指一遍**：目标换人、或目标刚登场时，
		//    路线都要重设（原版 4781-4785 的注释就是这么写的）。
		setRoute(e, [][2]float64{e.position, target.cell})
	}
}

// nearestAliveOperator 是离 `from` 最近的**存活且未撤退**的干员。
// 原版用 `math.dist` 比欧氏距离、并列取先遇到的（`<` 不是 `<=`）。
func nearestAliveOperator(ops []*operator, from [2]float64) *operator {
	var best *operator
	bestD := math.Inf(1)
	for _, op := range ops {
		if !op.alive() {
			continue
		}
		d := math.Hypot(op.cell[0]-from[0], op.cell[1]-from[1])
		if d < bestD {
			bestD = d
			best = op
		}
	}
	return best
}

// attachMark 是乙咬中之后挂天标那一步（原版 `_pile_attach_mark`，
// `sim.py:4787-4807`）。
//
// 在**目标所在地块中心**造一个天标敌人。⚠ 三个容易漏的点：
//
//  1. 它是**敌人**，不是 buff——要进 `*c.enemies`，否则我方索敌看不见它
//     （原版的出手账里确实有一笔打在它身上）。
//  2. 路线必须是**单点**（`static`）：原版 `reached_end` 要求路线长度 > 0，
//     单点路线长度为 0，所以它既不动、也不会被判成走到终点而漏怪。
//     主循环的 `SpawnSpec.Static` **没有被消费**（只有机制层那份模板认它），
//     所以这里直接改腿，别指望那个字段。
//  3. `attached` 是**登场那一刻的快照**：半径 0.3 从格心量出去够不到别格
//     （干员都在格心、相邻 1.0 格），所以快照就是这一格的人。
func attachMark(diver *enemy, target *operator, ops []*operator,
	t float64, c *simCtx) {
	if diver.spec.Mark == nil {
		return
	}
	cell := target.cell
	spec := *diver.spec.Mark
	spec.Legs = []LegSpec{{Kind: "static", Points: [][2]float64{cell}}}
	m := newEnemy(spec, c.nextEnemyIndex, cell, c)
	c.nextEnemyIndex++
	//: ⚠ 不可阻挡读的是 `spec.Unblockable`（`sim.go:1686`），敌人身上**没有**
	//: 单独的 `unblockable` 位——写成 `m.unblockable = true` 编译不过，
	//: 而如果哪天有人"顺手加一个字段"，它会静默不生效。改规格这一份才对。
	m.spec.Unblockable = true
	m.attachDamage = spec.AttachDamage
	m.attachRadius = spec.AttachRadius
	radius := spec.AttachRadius
	if radius <= 0 {
		radius = 0.3
	}
	for _, op := range ops {
		if !op.alive() {
			continue
		}
		if math.Hypot(op.cell[0]-cell[0], op.cell[1]-cell[1]) <= radius {
			m.attached = append(m.attached, op)
		}
	}
	*c.enemies = append(*c.enemies, m)
	if traceOn {
		trace("PILEMARK t=%.4f enemy=%s idx=%d cell=%.4f,%.4f attached=%d dmg=%.3f",
			t, m.spec.Name, m.index, cell[0], cell[1], len(m.attached), m.attachDamage)
	}
}

// pileMarkTick 是身上的天标的每秒结算（原版 `_pile_mark_tick`，`sim.py:4809-4824`）。
//
// 附着对象**全部退场就自毁**（直接写血，不是我方击杀）。
// 伤害是「预计算无途径物理伤害」= 定额，**不走 `resolveDamage`**（不吃防御、
// 不吃法抗），所以这里直接 `take`。
//
// ⚠ 原版这一行还套了一层 `_species_resist(op, e, ...)`（泥岩「手足相惜」一类
// 的按物种减伤），**Go 侧还没有这个机制**。差在哪只能靠对拍发现——写在这里
// 免得下一次又要从头找。
func pileMarkTick(enemies []*enemy, t float64, dt float64) {
	for _, e := range enemies {
		if e.attachDamage <= 0 {
			continue
		}
		if e.hp <= 0 || e.leaked || e.offMap || e.rebornAt >= 0 {
			continue
		}
		//: 快照里还有谁是活的（原版 `[op for op in e.attached if ...]`）
		alive := e.attached[:0:0]
		for _, op := range e.attached {
			if op.alive() {
				alive = append(alive, op)
			}
		}
		if len(alive) == 0 {
			e.hp = 0
			e.deathTime = t
			if traceOn {
				trace("PILEMARKGONE t=%.4f enemy=%s idx=%d", t, e.spec.Name, e.index)
			}
			continue
		}
		e.attachTimer += dt
		for e.attachTimer >= 1.0 {
			e.attachTimer -= 1.0
			for _, op := range alive {
				dealt := op.take(e.attachDamage)
				if traceOn {
					trace("PILEMARKDMG t=%.4f enemy=%s idx=%d target=%s dealt=%.3f",
						t, e.spec.Name, e.index, op.spec.Name, dealt)
				}
			}
		}
	}
}

// EnemyMoveSpeed 是这一只**这一刻**的推进速度：与主循环 `advance` 用的是同一个
// 算式（`spec.MoveSpeed × 自身乘区 × 关卡乘区 × 机制请求的乘区`），免得机制自己
// 抄一份。`自身乘区`就是原版 `haste_multiplier`（明识形态的清水会改它）。
func (c *simCtx) EnemyMoveSpeed(index int) float64 {
	if e := c.enemyAt(index); e != nil {
		//: 与 `advance` 同一口径、同一顺序（原版六项连乘，见那里的注释）：
		//: 机制看到的移速与真正推进用的移速必须**逐位**相同，否则
		//: "机制按 A 减速、主循环按 B 推进"会在末位长期分家。
		return e.spec.MoveSpeed * c.spec.SpeedScale * c.speedFor(index) * e.haste
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

// initMechTrace 把主包的痕迹通道交给机制层（`mech.Trace`）。
//
// 机制内部那些拿不到 `Ctx` 的小方法（`tick`/`cast`/`add`）要靠它才能打痕迹，
// 而"计时器为什么不动、施放为什么没发生"只能在这些地方问。
// 未调用时 `mech.Trace` 是 no-op——单测里不需要任何桩。
func initMechTrace() {
	if traceOn {
		mech.Trace = trace
	}
}

// ================================================================ 推进

// advance 沿分段计划推进 dt 秒（`EnemyUnit._advance_legs`，unit.py）。
//
// 三种段共用 `legU`：走段里它是已走格数，等待/离场段里是已过秒数。
// 整个循环**以时间为预算**——按格数当预算的话，等待段会被移速缩放，
// 3 秒的待命会被拉成好几分钟。
func advance(e *enemy, dt, speedScale, speedMult float64) {
	// `e.haste` 是原版 `haste_multiplier`（明识形态的清水会改它）。
	//
	//: ⚠⚠ **四项必须逐项、按原版的顺序左到右连乘，不许提前合并任何两项。**
	//: 原版（`unit.py:1493-1496`）是**六项**连乘：
	//:     move_speed * speed_scale * speed_multiplier * haste_multiplier
	//:                * (1 - slow_pct) * lock_slow
	//: （后两项在本关恒为 1.0，乘 1.0 是精确的，省略无害。）
	//:
	//: 这里曾经写成 `MoveSpeed * haste * (SpeedScale * speedFor(idx))`——
	//: 把 `speed_scale * speed_multiplier` **先乘成一个数**再参与。
	//: 浮点乘法**不满足结合律**，`(mv*h)*(ss*sm)` 与 `((mv*ss)*sm)*h`
	//: 在末位就分了家。每帧差 ~1e-16，累加 500 帧就是 1e-14 量级，
	//: 足以让**卡在半整数坐标上**的敌人翻格——`hsex07` 里那只除秽的
	//: x 原版算成 `7.4999999999999885`（落格 7、在凛冬范围内、当主目标），
	//: Go 算成 `7.5000000`（落格 8、不在范围、只能当溅射受害者），
	//: 判决因此差出 杀 +1 / 用时 +12.7s。排查全过程见
	//: `AK-TACTIC-进度.md` §3.12–§3.15。
	speed := e.spec.MoveSpeed * speedScale * speedMult * e.haste
	if speed <= 0 {
		return
	}
	// 移速**变化即记一笔**（不逐帧打，那样 72 只 × 2900 帧没法看）。
	//
	// ⚠ 只看"整速变化"不够：机制自己算的那一段（如积雪的 `speed_multiplier`）
	// 是**每帧重算**的，整速不变不代表它没变。要盯那一段得看机制的痕迹
	// （`SNOWSLOW`），两者并排才是完整的现场。
	if traceOn && speed != e.traceSpeed {
		e.traceSpeed = speed
		trace("SPEED t=%.4f enemy=%s speed=%.6f move=%.4f haste=%.6f scale=%.6f mult=%.6f",
			*e.sim.time, e.spec.Name, speed, e.spec.MoveSpeed, e.haste, speedScale, speedMult)
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
			// 自缚：**站位不动，但 `progress` 照涨**。
			//
			// 原版对"没有分段计划"的敌人走的是（`unit.py:1504-1505`）
			//     self.progress += speed * dt
			//     self.position = point_at(self.route, self.progress)
			// 而自缚者的 `route` 只有**一个点**，`point_at` 对单点折线
			// 循环体一次都不进、直接 `return points[-1]` —— 也就是
			// **位置钉死、`progress` 一直在涨**。
			//
			// ⚠ 这不是无关紧要的记账：索敌排序键是 `(嘲讽等级, progress)`
			// （`_pick_targets`，sim.py:3649），**progress 大的先挨打**。
			// 这里曾经直接 `break`、把 `progress` 冻在 0，于是"自缚的甲"
			// 永远输给任何走上来的敌人——`hsex07` t=17.0 凛冬因此把主目标
			// 从甲换成了除秽（原版甲的 progress 已涨到 4.9，除秽才 0.98），
			// 溅射落点整体位移，判决差出 杀 +1 / 用时 +12.7s。
			//
			// `legU` **不涨**：它只喂 `pointAt`，涨了会被 `reachedEnd` 当成
			// 走到终点（原版靠"路线长度 > 0 才算走到终点"达到同一效果）。
			e.progress += speed * left
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
		// ⚠ **干员【冻结】= 缴械，冻结期间不出手**（原版 `_operators_attack`
		// 的开头，`sim.py:3978`：`if op.freeze_timer > 0: continue`）。
		//
		// 位置是定的：这道闸门在 `op.attack_timer += dt` **之前**，所以冻结
		// 的那几秒**连出手计时器都不走**——解冻后不是"立刻补一发"，而是接着
		// 之前攒到的地方继续。把它写在 `attack_timer += dt` 之后，出手节奏
		// 会整体提前，症状与"没有这道闸门"完全不同。
		//
		// 目前唯一的来源是「圣山的祝福」的自冻结（`spec.BlessingSelfFreeze`）；
		// 晕眩 `stun_timer` 与闭锁 `locked_timer` 仍未移植，理由见 `hurt`。
		if op.freezeTimer > 0 {
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
			//: ⚠ 这一行**必须是自描述的 `key=value`**：它是"这次出手计时到了，
			//: 我选到了谁"的**唯一**记录，而"某位干员一次都没出力"只有它看得见。
			//: 第一版写成 `OPATK  8.0333 怒潮凛冬 …`（前两个字段没有键名），
			//: 结果 `trace_kv` 一行都解析不出来——探针报"0 笔"，
			//: 与"她真的没出手"**长得一模一样**。列表用 `|` 连接，
			//: 空格会破坏 `key=value` 的切分。
			trace("OPATK t=%.4f op=%s skill=%v interval=%.4f timer=%.4f "+
				"block=%s pick=%s inrange=%s heals=%s",
				t, op.spec.Name, op.skillActive, op.interval(), op.attackTimer,
				strings.Join(names(op.blocking), "|"),
				strings.Join(names(targets), "|"),
				strings.Join(names(inRangeOf(op, enemies)), "|"),
				strings.Join(namesOp(heals), "|"))
		}
		if len(targets) == 0 && len(heals) == 0 {
			continue
		}
		op.attackTimer = 0
		scale := scaleNow
		hits := op.hitCount()
		finalScale, hasFinal := op.finalHitScale()
		// 普攻连击（焰狐龙梓兰的**隐藏天赋**）：普通攻击为三连击、每击 100%，
		// **计算防御/法抗之后**再 ×33.3%（原版 `sim.py:4049-4062` + 4135）。
		//
		// 「是不是普攻」的判据与上面 `deals` 同一套写法：**看技能有没有改写这一击
		// 的攻击倍率**，不看技能开没开——她的技2 是 +buff 型、技1 是改攻击型，
		// 两者在这一点上不同。`scaleNow` 就是 `effects.atk_scale`。
		//
		// ⚠ 三连击是**覆盖** `hits` 与 `scale`，不是相加：技能自己写了
		// `hit_count`（她的技2 是 13 笔）时那条判据已经把它排除在外了。
		comboDmgScale := 1.0
		if op.spec.ComboHits > 1 && math.Abs(scaleNow-1.0) < 1e-9 {
			hits = op.spec.ComboHits
			scale = op.spec.ComboHitScale
			comboDmgScale = op.spec.ComboDamageScale
		}
		power := op.atk()
		// 天赋「强击瓶专家」：接下来 N **轮**攻击的攻击力倍率提升。备注写明
		// "于弹道脱手前对当次连击的所有弹道生效" ⇒ 乘在这一轮的全部箭矢上，
		// 整轮只扣一层（原版 `sim.py:4088-4101`）。
		//
		// ⚠ 原版的 `rounds` 会因"技2 三轮齐射 ＋ 落地点射""技1 刚连射"而大于 1；
		// 那三样（`volley_arrows` / `landing_scale` / `charge_arrows`）**还没进
		// Go 的 `Profile`**。所以这里只兑现 `rounds = 1` 这一种，闸门负责把
		// 剩下的挡在门外——两边都不许猜。
		if op.powerAttackLeft > 0 {
			power *= op.spec.PowerAttackScale
			op.powerAttackLeft = math.Max(0, op.powerAttackLeft-1)
		}
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
					target.spec.DEF, target.res(), target.dodgeVs(dmgType))
				// 连击的 `ComboDamageScale` **乘在这里**：原版是
				// `self._damage_enemy(target, dmg.final * combo_dmg_scale, ...)`
				// （`sim.py:4135`），也就是**算完防御/法抗之后**再整笔缩放。
				// 乘进 `hitScale`（结算之前）会得到完全不同的数——那是法抗/
				// 防御也一起被缩放，症状是"伤害偏低且随目标防御变化"。
				dmg *= comboDmgScale
				dealt := target.take(dmg, op)
				trace("        打 %s 攻=%.1f 类型=%s 倍率=%.3f 防=%.1f 抗=%.1f 伤害=%.3f 实扣=%.3f 剩=%.3f",
					target.spec.Name, power, dmgType, hitScale, target.spec.DEF,
					target.res(), dmg, dealt, target.hp)
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
		e.spec.DEF, e.res(), e.dodgeVs("PHYSICAL"))
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
		// ⚠ **不能排除自己**：原版 `_pick_heals` 的候选池是
		// `[o for o in self.operators if o.alive and o.hp < o.max_hp]`
		// （`sim.py:3691`）——**没有 `o is not op` 这一条**，
		// 所以医疗可以把自己的平A治在自己身上。
		//
		// 多写一个 `o == op` 的症状极具误导性：她**照常出手、照常有治疗痕迹**，
		// 只是永远治不到自己；于是"医疗是全场唯一没人治的人"，她会比原版
		// 早 107 秒倒下（k=4：84.3667 vs 191.2000），而她的治疗量看起来
		// 完全正常——顺着治疗量查一辈子也查不到。
		if !o.alive() || o.hp >= o.spec.MaxHP {
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

// teamAuraTick 把全场光环的当前数值刷到每个干员身上（原版 `_refresh_auras`，
// `sim.py:3547`；帧位 5.4，`sim.py:2831-2832`）。
//
// 三条口径：
//  1. **按目标逐个算**，不能先算一份再刷给所有人——「万众巨潮」对
//     【乌萨斯学生自治团】翻倍、对别人不翻，取值因人而异。
//  2. 多条光环**相加**，不是连乘。
//  3. 光环一旦建立就**不随主人阵亡而消失**（原版 `self.team_auras` 只 append、
//     没有删除点）。主人倒了之后只有「技能期间才生效」那类会自然变 0
//     （技能状态没了），常驻那类照旧——所以这里不判 `owner.alive()`。
func teamAuraTick(ops []*operator) {
	for _, op := range ops {
		atk, def := 0.0, 0.0
		for _, owner := range ops {
			for i := range owner.spec.TeamAuras {
				x, y := owner.spec.TeamAuras[i].current(owner, op)
				atk += x
				def += y
			}
		}
		op.auraAtkPct = atk
		op.auraDefPct = def
	}
}

// current 是原版 `TeamAura.current(target)`（`talents.py:702`）——
// **唯一的判定函数**。`owner` 是光环主人（判它开没开技能），`target` 是吃光环的人。
//
// 分支顺序照抄原版：`self_only` → `ammo_skill_only` → `faction_only`
// → `profession` → 最后才是"常驻 / 技能期间"那条。
// **顺序有意义**：某条光环可能同时带着筛选与倍率，先命中的分支说了算。
func (a *TeamAuraSpec) current(owner, target *operator) (float64, float64) {
	if a.SelfOnly && target != owner {
		return 0.0, 0.0
	}
	if a.AmmoSkillOnly {
		sk := target.spec.Skill
		if sk == nil || sk.DurationType != "AMMO" {
			return 0.0, 0.0
		}
		k := 1.0
		if a.NationDouble != "" && target.spec.NationID == a.NationDouble {
			k = a.DoubleScale
		}
		return a.AtkPct * k, a.DefPct * k
	}
	if a.FactionOnly != "" {
		if target.spec.NationID != a.FactionOnly {
			return 0.0, 0.0
		}
		return a.AtkPct, a.DefPct
	}
	if a.Profession != "" {
		if target.spec.Profession != a.Profession {
			return 0.0, 0.0
		}
		return a.AtkPct, a.DefPct
	}
	active := owner.skillActive
	if a.SkillOnly {
		if !active {
			return 0.0, 0.0
		}
		k := 1.0
		for _, id := range a.Faction {
			if id == target.spec.CharID {
				k = a.FactionScale
				break
			}
		}
		return a.AtkPct * k, a.DefPct * k
	}
	k := 1.0
	if active {
		k = a.DoubleScale
	}
	return a.AtkPct * k, a.DefPct * k
}

// regenAuraTick 兑现天赋「医者丰碑」的增益治疗光环（原版 `RegenAura.tick`，
// `talents.py:772`；帧位 5.5，`sim.py:2834-2840`）。
//
// 三件事按顺序：① 判"谁**进入**了光环主人的攻击范围"（每人只触发一次）；
// ② 给吃到的人挂上剩余时长与每秒回复量；③ **所有**身上还挂着增益的人跳一次回血
// ——注意 ③ 与 ① 是分开的：光环主人倒下之后不再发新的，**但已经发出去的照跳完**。
//
// ⚠ 部署进射程**也算"进入"**：游戏里干员落地那一刻就是在范围里，天赋照样触发。
// 所以这里在部署当帧就判一次，不等它"走进来"。
func regenAuraTick(ops []*operator, dt float64) {
	for _, owner := range ops {
		au := owner.spec.RegenAura
		if au == nil {
			continue
		}
		//: 每一份光环的身份 = 主人的 `deploySeq`（原版每次部署 append 一个新的
		//: `RegenAura` 对象，那个对象就是身份）。
		auraID := owner.deploySeq
		give := owner.alive()
		for _, op := range ops {
			if op == owner || !op.alive() {
				continue
			}
			cell := [2]int{int(math.RoundToEven(op.cell[0])),
				int(math.RoundToEven(op.cell[1]))}
			// 严格读法只认**光环之后**才进场的人（原版按 `operators` 里的先后）。
			eligible := !au.Strict || indexOfOp(ops, op) > indexOfOp(ops, owner)
			if give && eligible && !op.hasRegenGrant(auraID) &&
				inCells(owner.spec.Range, cell) {
				op.markRegenGranted(auraID)
				op.regenLeft = math.Max(op.regenLeft, au.Duration)
				// 【罗德岛】翻的是**速率**，不是持续时间（原文那句话紧跟在
				// "每秒回复 N 点"后面）。倍率取黑板，不写死 2.0。
				rate := au.HPPerSec
				if au.Nation != "" && op.spec.NationID == au.Nation {
					rate *= au.NationMult
				}
				op.regenPerSec = math.Max(op.regenPerSec, rate)
			}
			if op.regenLeft > 0 {
				// `step` 夹在剩余时长上：最后一帧只跳剩下的那点，不能多跳一帧的整量。
				step := math.Min(dt, op.regenLeft)
				op.heal(op.regenPerSec * step)
				op.regenLeft = math.Max(0.0, op.regenLeft-dt)
				if op.regenLeft <= 0 {
					op.regenPerSec = 0
				}
			}
		}
	}
}

// indexOfOp 是 `ops` 里的位置（找不到给 -1）。
func indexOfOp(ops []*operator, want *operator) int {
	for i, o := range ops {
		if o == want {
			return i
		}
	}
	return -1
}

// hasRegenGrant 问"这一份光环（按主人的部署序号认）发的那份增益，我吃过没有"。
func (o *operator) hasRegenGrant(auraID int) bool {
	for _, v := range o.regenGrantedBy {
		if v == auraID {
			return true
		}
	}
	return false
}

// markRegenGranted 记下"吃过了"。
func (o *operator) markRegenGranted(auraID int) {
	o.regenGrantedBy = append(o.regenGrantedBy, auraID)
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
		//
		// ⚠ 读的是**复合**的 `frozen()`：原版的 `frozen` 是
		// `freeze_timer > 0` **或**"所站格满层"（积雪），只读计时器会让
		// 积雪那一半静默失效（敌人照打）。
		if e.frozen() {
			continue
		}
		op := enemyTarget(e, ops, spec.RangedEnemies)
		if op == nil || !op.alive() {
			continue
		}
		e.attackTimer += dt
		if e.attackTimer < e.interval() {
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
		if e.alive() && !e.leaked && !e.cannotClear() {
			return true
		}
	}
	return false
}

// cannotClear 是原版的 `Sim._cannot_clear`（`sim.py:2596`）——这个单位
// **有没有可能被清掉**：要么被打死，要么走到目标点。两个条件**同时**成立才算。
//
//   - **打不死** → `always_invincible`。⚠ 这是**运行期**字段：天桩-甲的监测形态
//     常驻无敌，激活时机制会把它摘掉（改成每秒自损 1%），那时它就打得死了。
//   - **不会离场** → 单点路线。原版判 `route_length == 0`；Go 侧"自缚"落地成的
//     是一条 `static` 腿（见 `advance` 里那句"这条腿永远走不完"），口径等价。
//
// ⚠ **不能读 `spec.CannotClear`**：那是规格在**开局**算好的定值，而
// `always_invincible` 要到这只怪**出场那一刻**才被机制写上——于是它恒为 false，
// 天桩-甲永远被算成"能清掉"。症状极具迷惑性：**杀、漏、伤害全对，
// 只有用时等于时间上限**（这一局根本收不了场），而 Go 的判决里此前
// 连"场上还剩谁"都不报，只能看到一个 +80 秒然后去猜。
func (e *enemy) cannotClear() bool {
	if !e.invincible {
		return false
	}
	for _, leg := range e.spec.Legs {
		if leg.Kind != "static" {
			return false
		}
	}
	return true
}

// frozen 是原版的 `EnemyUnit.frozen`——**复合判据**（`sim.py:1139` 每帧重置成
// `freeze_timer > 0`，再由积雪在 1156 那一行补上"所站格满层"）。
//
// 为什么合成一个方法而不是散着判：读它的地方有两处（推进闸门、出手闸门），
// 而"两处都记得读两个字段"这种约定迟早会破——漏一处就是**冻结静默失效**，
// 判决上看不出"是冻结没生效"还是"本来就没人冻它"。写成方法，漏读会编译不过。
func (e *enemy) frozen() bool { return e.freezeTimer > 0 || e.frozenSnow }

// interval 是这一只**这一刻**的出手间隔：`基础间隔 × 100 / max(20, 总攻速)`。
//
// 与干员侧同一条公式（原版 `SkillEffects.attack_interval`）。这条攻速轴上目前
// 唯一的修正是【寒冷】−30；**没有寒冷时 `× 100/100` 恒等于 `spec.Interval`**，
// 所以既有的对拍基线一位都不动——这条是刻意的，别在这里顺手加别的因子。
func (e *enemy) interval() float64 {
	aspd := 100.0
	if e.coldTimer > 0 {
		aspd -= coldASPDDown
	}
	return e.spec.Interval * 100.0 / math.Max(aspdMin, aspd)
}

// res 是这一只**这一刻**的法术抗性：冻结期间 −15（PRTS《敌人一览/数据》tooltip）。
//
// ⚠ 必须是**动态**判据而不是写进 `spec.RES`：冻结解除后抗性要回来，而
// `spec.RES` 是整局的静态规格（改写它会让同一只敌人"冻过一次就永久变脆"）。
// 所有"敌人作为受击方"的结算都要走这里读，直接读 `spec.RES` 就是漏这条。
func (e *enemy) res() float64 {
	if e.friendlyFrozen() {
		return e.spec.RES - frozenResDown
	}
	return e.spec.RES
}

// friendlyFrozen 报告这一只**这一刻**是否处于【友方冻结】。
//
// 法抗 −15 只看这个，**不看目标是不是敌人**（见 `freezeFriendly` 与 `frozenResDown`
// 的出处）。积雪那一半（`frozenSnow`）恒定是干员造成的，所以无条件算友方。
func (e *enemy) friendlyFrozen() bool {
	return (e.freezeTimer > 0 && e.freezeFriendly) || e.frozenSnow
}

// applyCold 施加【寒冷】秒数；**已在寒冷中则转为【冻结】**。
//
// 来源是 PRTS《敌人一览/数据》tooltip：「寒冷：攻击速度下降 30，如果在持续时间
// 内再次受到寒冷效果则会变为冻结」。
//
// ⚠ 转冻结之后的**时长**，tooltip 没有给数。本函数按"触发那一次的秒数"取——
// 这是一条**假设**，不是查到的定论，已登记进 `docs/uncertainties.md`
// （键：`寒冷转冻结后的时长`）。要改成别的口径，只改这一处。
func (e *enemy) applyCold(secs float64, friendly bool) {
	if secs <= 0 {
		return
	}
	if e.coldTimer > 0 {
		// 转为冻结时，冻结的来源形别跟着这次寒冷的来源走。
		e.applyFreeze(secs, friendly)
		return
	}
	e.coldTimer = math.Max(e.coldTimer, secs)
}

// applyFreeze 施加【冻结】秒数。取较大值与既有那条来源（圣山的祝福 `blessingTick`）
// 同款，免得"后到的短冻结把先到的长冻结顶掉"。
func (e *enemy) applyFreeze(secs float64, friendly bool) {
	if secs <= 0 {
		return
	}
	// 生效的是"剩得更久的那一笔"，所以来源形别也跟着那一笔走：
	// 先挨一发 2 秒敌方冻结、再挨一发 5 秒友方冻结，这 5 秒里算友方冻结（吃 −15）。
	// 这是**近似**：真正精确要按来源各记一份计时器，混合来源时 −15 应当随友方那一份
	// 到期而结束。当前项目里没有混合来源的用法，先按"较长者定形别"实现并登记。
	if secs >= e.freezeTimer {
		e.freezeFriendly = friendly
	}
	e.freezeTimer = math.Max(e.freezeTimer, secs)
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
	//: 敌人**受伤的唯一汇点**留痕（原版对应 `Combatant.take`，`unit.py:104`）。
	//:
	//: 为什么要有这一条：`HITENEMY`（机制直伤）、`SPLASH`（溅射）、普攻各有各的
	//: 痕迹，**总伤害对不上时无从下手**——三路加起来差 1,392 点，是"某一路多打了"
	//: 还是"同一个敌人被多打了一次"，只能靠一个**统一的**账本回答。
	//: 原版侧用同样的钩子（钩 `Combatant.take`）就能逐笔对。
	if traceOn && e.sim != nil && dealt > 0 {
		//: `src` 就是出手的干员（没有来源的机制伤害是 nil）。**必须带上**：
		//: 只记"这只敌人挨了多少"能定位到"哪一只不对"，记不到"谁打的那一下"——
		//: 而多出来的那一笔往往正是某一门干员**多出手了一次**。
		who := "(机制)"
		if src != nil {
			who = src.spec.Name
		}
		trace("DMGENEMY t=%.4f enemy=%s idx=%d src=%s amount=%.3f dealt=%.3f hp=%.3f",
			*e.sim.time, e.spec.Name, e.index, who, amount, dealt, e.hp)
	}
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
		//: 改写类机制**没有可观测量**（记忆 e681022e）：RES 被改了多少，下游只能看到
		//: "伤害被顶到 5% 保底"这种间接信号，从下游反推必偏。
		//: 所以在这里把**改写前后**直接打出来——"RES 变负"这类事应该在这里就能看见。
		beforeRES := sp.RES
		sp.RES += sp.PhitRes
		c.Trace("PHITRES t=%.4f enemy=%s idx=%d stack=%d/%d before=%.2f delta=%.2f after=%.2f",
			c.Now(), sp.Name, e.index, e.phitStacks, sp.PhitMaxStack,
			beforeRES, sp.PhitRes, sp.RES)
		sp.MoveSpeed += sp.PhitMove
		c.Trace("PHIT t=%.4f name=%s 层=%d/%d atk=%.2f def=%.2f res=%.2f",
			c.Now(), sp.Name, e.phitStacks, sp.PhitMaxStack,
			sp.ATK, sp.DEF, sp.RES)
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
	//: ⚠ 这两套改写（`phit_*` 蜕皮、`pm2_*` 归来）改的是**普通字段**，原版与 Go
	//: 都不产生任何可观测量，下游只能看到"伤害被顶到 5% 保底"这种间接信号。
	//: 拿间接信号反推"防御被改成了多少"是猜；所以在这里把**改写前后**直接打出来。
	c.Trace("PM2 t=%.4f name=%s 前 层=%d atk=%.2f def=%.2f res=%.2f",
		t, sp.Name, e.phitStacks, sp.ATK, sp.DEF, sp.RES)
	if !e.pm2Applied {
		e.pm2Applied = true
		beforeRES := sp.RES
		sp.ATK *= 1.0 + sp.Pm2Atk
		sp.DEF *= 1.0 + sp.Pm2Def
		sp.RES += sp.Pm2Res
		//: 与 `PM2 前/后` 同族，但**只有这一行**能回答"这次真的改了没有、改了多少"：
		//: 那两行在重复进入时照样打（`applied` 已是 true），于是"前后有差"
		//: 与"这一次改的"是两件事，混在一起就会把重复改写读成正常。
		c.Trace("PM2RES t=%.4f enemy=%s idx=%d applied_before=%t before=%.2f delta=%.2f after=%.2f",
			t, sp.Name, e.index, false, beforeRES, sp.Pm2Res, sp.RES)
		e.haste = 1.0 + sp.Pm2Move
		sp.AttackTimes = 2
		if sp.AttackRange > 0 {
			sp.ApplyWay = "RANGED"
		}
	}
	c.Trace("PM2 t=%.4f name=%s 后 层=%d atk=%.2f def=%.2f res=%.2f applied=%t",
		t, sp.Name, e.phitStacks, sp.ATK, sp.DEF, sp.RES, e.pm2Applied)
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
		//: ⚠ 判据**只有"切换"这一支**（原版 `if clean != e.pm2_clean:`）。
		//: 曾经多写了一个 `|| !e.pm2Clean`，本意是"进去时先算一次"，实际效果是
		//: **只要不在清水里就每帧重算** —— 而重算是"从 `rebornDefBase` 覆盖"，
		//: 于是「蜕皮」每帧攒下的 `−50/层` 被逐帧冲掉（80 层本该 `350→−245`，
		//: 实测停在 `4000×0.3 − 50 = 1150`）。症状是**物理伤害被顶到 5% 保底**
		//: （`525.20 × 5% = 26.26`），一只 BOSS 因此整场打不死。
		//: 进去那一次不需要这里补：`enterPm2` 已经乘过 `(1 + Pm2Def)` 了。
		if clean != e.pm2Clean {
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
		e2 := newEnemy(tmpl, c.nextEnemyIndex, [2]float64{float64(cx), float64(cy)}, c)
		c.nextEnemyIndex++
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
	amount = math.Max(0, amount)
	// 「层数护盾」：**次数制抵挡**，一层把这一下**整笔**吃掉（原版
	// `unit.py:613-620`，位置在屏障分支之前）。顺序是原版定的：先裂、先回血，
	// 再把这一下归零——所以"回血之后血量更高"是原版的语义，不是笔误。
	//
	// ⚠ 判据是 `amount > 0`：伤害本来就是 0 的那一下**不消耗层数**
	// （原版同一句）。漏掉这个条件会让护盾被"0 伤害"白白吃掉。
	if o.shieldLayers > 0 && amount > 0 {
		o.shieldLayers--
		o.shieldBreaks++
		amount = 0
		if o.shieldBreakHeal > 0 {
			o.hp = math.Min(o.maxHP(), o.hp+o.shieldBreakHeal)
		}
		if o.shieldBreakSP > 0 {
			o.sp += o.shieldBreakSP
		}
		if traceOn && o.sim != nil {
			//: 这一族**没有别可观测量**：它把伤害变成 0，判决里只剩"谁活到最后"。
			//: 所以破裂点必须打痕迹——`tr02` 就是靠它认出"原版前三下没挨"的。
			trace("SHIELD t=%.4f op=%s break %d/%d heal=%.3f hp=%.3f",
				*o.sim.time, o.spec.Name, o.shieldLayers, o.shieldMaxLayers,
				o.shieldBreakHeal, o.hp)
		}
	}
	dealt := math.Min(o.hp, amount)
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
	// ⚠ 本条兑现的是"免死 + 满血复活 + 攻击范围内全体敌人冻结 + **自身冻结
	// N 秒**"。自身冻结（黑板 `freeze` → `blessing_self_freeze`）**是缴械**：
	// 原版 `_operators_attack` 的开头就有 `if op.freeze_timer > 0: continue`
	// （`sim.py:3978`），冻结期间**不出手**（但不动阻挡）。
	//
	// 漏掉它的症状**在 Go 的痕迹里完全看不见**——它不是"算错了一个数"，
	// 是"少了一道闸门"，所以只会表现为"某一门干员比原版多打了几次"。
	// HS-EX-8 第 3 手实测：圣聆初雪在 t=63.3 免死并自冻 4 秒，正好吃掉
	// 65.0 / 67.0 两次出手；Go 多打 2 笔 696 = 1,392 点，正好是总伤害残差。
	if o.hp <= 0 && !o.blessingUsed && o.spec.BlessingSave > 0 {
		o.blessingUsed = true
		o.hp = o.maxHP()
		// 空间查询留到**下一帧**兑现：掉血那一刻够不着地图（原版同理由，
		// sim.py:1065-1071：把空间查询塞进 `take()` 会让纯数值函数反向依赖
		// 整张地图）。差一帧，与原版同。
		o.blessingFreeze = o.spec.BlessingSave
		// 自冻结：取 `max`（原版 `unit.py:646` 就是 `max`），递减在 `skillTick`。
		if o.spec.BlessingSelfFreeze > 0 {
			o.freezeTimer = math.Max(o.freezeTimer, o.spec.BlessingSelfFreeze)
		}
		if traceOn && o.sim != nil {
			trace("BLESSING t=%.4f op=%s 免死→满血 %.1f（待冻结攻击范围内敌人 %.2fs；自冻结 %.2fs）",
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
			// 来源形别 = **友方**：这是干员天赋直接施加的冻结（见 `freezeFriendly`）。
			e.applyFreeze(secs, true)
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
