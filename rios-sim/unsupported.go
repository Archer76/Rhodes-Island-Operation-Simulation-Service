// 闸门：Python 侧 `ak_tactic/simgo/spec.py::unsupported_reasons` 的 Go 版。
//
// ## 它回答什么问题
//
// 「**这一局用到了最小版本没覆盖的机制吗**」——逐条给理由，理由为空才放行。
// 这不是可选的美化：在它出现之前，「敌人有技能出手／会重生／会换形态」这种关
// 会被原样交给 Go，而 Go 那边这些行为一行都没有，判决却照样给出来——
// **那正是「对拍通过但两边算的不是同一场战斗」**（`spec.py:456-458` 原话）。
//
// ## 输出为什么不是一个裸数组
//
// 生产规格里 `unsupported` 是一个字符串数组。但 Go 这一版**还没有**把整条闸门
// 搬完：干员侧那一圈（天赋／技能效果／光环／闪避…）要的 `operator_view` 与
// `SkillEffects` 组装不在 Go 里。裸数组只能把那几条**静默省略**——而「闸门不报、
// 规格里也没这项、Go 静默跑出另一场战斗」正是这条闸门立规矩要防的那件事。
//
// 所以应答是三个槽：
//
//	reasons   —— 与生产规格**逐条同序**的那份理由（Go 真判得出的那几条）
//	unported  —— Go **算不了**的那几条闸门线，具名列出（不是省略）
//	covered   —— 每条已搬线**产出过几条理由**（行使计数；0 的线由判据另行登记）
//	scanned   —— 每条线**被喂进去多少输入**（0 输入时的 0 不算读数）
//
// `unported` 与 `tools/check_unsupported_go.py` 的 `UNPORTED` 是同一份清单的
// 两面，两边不一致时那条判据会红（防「哪天 Go 接上了却没人回头看」）。
//
// ## 覆盖边界（2026-09-22 逐条实测，不是估的）
//
// **已搬**（这几条的输入 Go 真有）：
//
//   - `撤退 ×N`（计划）／`技能槽号 N（…）`（计划）／`召唤物部署 ×N`／
//     `装置部署 ×N`（后两条走计划，计划没有装置通道 ⇒ 恒 0）；
//   - `积雪 ×N`（`inp.snow_fields`，**运行期才 append**，规格取的是开局态 ⇒ 恒空）；
//   - `按田地病害值觉醒：X`／`BOSS 换弱点形态：X`（敌人库字段）；
//   - `mech.port_reasons` **恒为空**：它是一句常量的空表，照搬（不是漏掉）。
//
// **没搬**（见 `unportedLines`）：干员侧那一圈、积雪天赋、关卡装置、全场总攻击、
// `技能：<名字>`、`被击倒给可部署装置`。
//
// ## 两条「结构上不可达」的线（不进行使计数）
//
//   - `持续自伤`（`hp_drain_per_sec`）：它是**干员**字段（`unit.py:721`、
//     `frontend/operator_view.py:179`），`enemy_view` 从不设它 ⇒ 原版那条
//     闸门线永远取到 0。24 份夹具 1154 个出怪对象命中 0。Go 侧连字段都没有，
//     这与「两边都不报」等价，故**不算 unported**（那会谎称 Go 少了一条）。
//   - `被击倒给可部署装置`：第三个合取项是 `inp.device_deployments`，而
//     `verify.py` 从不调 `plan_device`、`Plan` 也没有装置字段 ⇒ 两个生产路径上
//     恒空。它**记在 unported** 里（Go 确实没有这条渠道），并由判据带证据登记。
package main

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

// GateQuery 是 `unsupported` 命令的 spec 体。
//
// 关卡走 `req.Level`（关卡号／levelId）或 `req.Path`（合成关卡 JSON 文件），
// 与 `stageenv` 同一口径。
//
// ⚠ `AllowDevices` / `AllowSkills` 是**原版那两个口子的形状**，它们各自只影响
// 一条线：`allow_devices` 管 `关卡装置 ×N`，`allow_skills` 管技能白名单那一圈。
// 那两条线**都在 `unported` 里**（Go 没有装置层、也没有技能效果层），所以这里
// 无分支可走——但字段**照样读**：它们会随 `Params` 原样回显，判据据此核对
// 「这一趟是按哪个口径问的」。口径只活在散文里，下一个读的人不会去看它。
type GateQuery struct {
	//: ⚠ 与 `BuildSpecQuery.Plan` **同一份两形态**（字符串＝路径／对象＝内联），
	//: 判别与解析都走 `loadPlanTwoForms`（**只此一份实现**）。闸门要读计划里的
	//: `retreats` 与每位干员的 `skill`，而 `sim` 的查询形式手上是**计划对象**、
	//: 没有路径 —— 只收路径会让查询形式那条路在这里断掉。
	Plan         json.RawMessage `json:"plan,omitempty"`
	//: ⚠⚠ **路径形态必须一起带过来**（2026-09-23 实测踩到）：`BuildSpecQuery` 的
	//: 解析器会把字符串形态的 `plan` 拆成 `(Plan=nil, PlanPath=路径)`，所以
	//: `BuildSpecFull` 只把 `Plan` 递进来的话，闸门拿到的是**空 raw** ⇒
	//: `loadPlanTwoForms(nil, "")` 返回 `nil, nil`（＝「没给计划」）⇒
	//: 计划的 `retreats`／`skill` 一条都读不到。
	//: 症状**不是**报错，而是 `unsupported` 少几条 —— `check_buildspec_go.py`
	//: 的 C 口径（合成计划，走**路径**形态）正好盯着这一处，实测红 2 例。
	//: 这也是本文件上面那句「计划少读一条部署在下游只表现为某一手没下」的又一例。
	PlanPath     string          `json:"-"`
	Difficulty   string          `json:"difficulty,omitempty"`
	AllowDevices bool            `json:"allow_devices,omitempty"`
	AllowSkills  bool            `json:"allow_skills,omitempty"`
}

// planEcho 回显这一趟的计划来源（路径原样；内联给一个读得懂的标签）。
func (q GateQuery) planEcho() string {
	if q.PlanPath != "" {
		return q.PlanPath
	}
	if len(q.Plan) == 0 {
		return ""
	}
	if _, path, err := splitPathOrInline(q.Plan, "plan"); err == nil && path != "" {
		return path
	}
	return "（内联）"
}

// GateOut 是应答体。四个槽的用途见文件头。
type GateOut struct {
	Reasons  []string       `json:"reasons"`
	Unported []string       `json:"unported"`
	Covered  map[string]int `json:"covered"`
	Scanned  map[string]int `json:"scanned"`
	//: `Params` 原样回显这一趟的**口径与对象身份**（哪一关、按哪个开关问的）。
	//: 判据拿它核对「Go 真按我要求的口径答的」，也让那两个开关有读者。
	Params map[string]any `json:"params"`
}

// unportedLines 是**具名**的未搬线。与判据脚本里的同名常量互为守卫。
//
// 每一条都对应 `spec.py` 里的一处：写了线名、不写散文，是为了让判据能集合比对。
var unportedLines = []string{
	"skill_name",    // `技能：<名字>`（计划的 skill 写成对象那一支）
	"snow_talent",   // `积雪（天赋「无垠的雪景」）：<谁>`
	"devices",       // `关卡装置 ×N`（只有 allow_devices=False 时报）
	"total_attack",  // `全场总攻击装置`
	"death_token",   // `被击倒给可部署装置：<谁>`
	"operator_side", // 干员侧那一圈：召唤物／锤击／技能效果覆盖／天赋回技力×2／
	// 高台触发回技力／强击瓶多轮／闪避×2／光环×2／免死／弱点伤害／
	// 天赋攻速×2／技能治疗倍率／翔虫机动
}

// UnsupportedGate 跑一遍闸门。
//
// ⚠ 理由的**顺序**是契约的一部分（生产规格逐条同序）：排程侧在前、敌人侧居中、
// 逐条部署在后，最后去重但保序。敌人侧内部的顺序是「按第一次出现的出怪时刻」。
func UnsupportedGate(level, path string, q GateQuery) (GateOut, error) {
	out := GateOut{
		Reasons:  []string{},
		Unported: append([]string{}, unportedLines...),
		Covered:  map[string]int{},
		Scanned:  map[string]int{},
		Params: map[string]any{
			"level": level, "path": path, "plan": q.planEcho(),
			"allow_devices": q.AllowDevices, "allow_skills": q.AllowSkills,
		},
	}
	st, err := loadGateStage(level, path, q.Difficulty)
	if err != nil {
		return out, err
	}
	//: 计划两种形态（路径／内联）共用一份解析，见 `loadPlanTwoForms`。
	//: ⚠ **两个参数都要给**：只给 raw 会让路径形态（解析器已把路径拆进
	//: `PlanPath`）静默变成「没给计划」。
	plan, err := loadPlanTwoForms(q.Plan, q.PlanPath)
	if err != nil {
		return out, err
	}

	// ---- 排程侧（`spec.py:146-151`）----
	//
	// ⚠ `召唤物部署`／`装置部署` 两条**照写**：计划里没有这两条通道，
	// 所以恒为 0。写成常量 0 而不是删掉——删掉之后这里就没有「谁该为此负责」了。
	// 三个键**一律写**（不写就与「这条检查没跑」长得一样）。
	out.Scanned["summon_deploy"] = 0
	out.Scanned["device_deploy"] = 0
	out.Scanned["retreat"] = 0
	if plan != nil {
		out.Scanned["retreat"] = len(plan.Retreats)
		if n := len(plan.Retreats); n > 0 {
			out.Covered["retreat"]++
			out.Reasons = append(out.Reasons, fmt.Sprintf("撤退 ×%d", n))
		}
	}

	// `inp.snow_fields`：**运行期才 append** 的列表，规格取的是开局态 ⇒ 恒空。
	// （这正是「积雪闸门盲区」的来源，见 `simgo/spec.py:152-161`。）
	out.Scanned["snow_fields"] = 0

	// ---- 逐条部署：技能（`spec.py:181-193`）----
	//
	// `_attach_skill_for_spec` 的判据：`skill` 是 0／None 就清空并放行；
	// 是整数（且非 0）就**报「槽号」**（调用方得先绑 SkillLevel）；
	// 是对象（已经绑好的 `SkillLevel`）才走「技能可用性」那条路 —— 那一条
	// 是 `unported`（Go 的计划读取器**故意**拒收对象形态，见 `plan.go:274`
	// 与 `tools/check_plan_go.py:131` 那条已登记的分歧）。
	out.Scanned["deploy"] = 0
	if plan != nil {
		out.Scanned["deploy"] = len(plan.Deploys)
		for _, d := range plan.Deploys {
			if d.Skill != 0 {
				out.Covered["skill_slot"]++
				out.Reasons = append(out.Reasons, fmt.Sprintf(
					"技能槽号 %d（%s）：调用方要先把 SkillLevel 绑好再生成规格",
					d.Skill, d.Operator))
			}
		}
	}

	// ---- 敌人侧（`spec.py:450-498`）----
	lib, err := LoadEnemyLibrary()
	if err != nil {
		return out, err
	}
	spawns := gateSpawns(st)
	out.Scanned["spawn"] = len(spawns)
	type bucket struct {
		who []string
		has map[string]bool
	}
	order := []string{}
	got := map[string]*bucket{}
	add := func(line, name string) {
		b := got[line]
		if b == nil {
			b = &bucket{has: map[string]bool{}}
			got[line] = b
			order = append(order, line)
		}
		if !b.has[name] {
			b.has[name] = true
			b.who = append(b.who, name)
		}
	}
	skipped := 0
	for _, sp := range spawns {
		//: ★ **走 `StatsForSpawn`，不走 `lib.At`**（2026-09-24 修）：它带「库里取不到
		//: 就查关卡本地定义」那条回退（`enemy_stats.py:34-55`），与出怪那条路同一个入口。
		//: 修之前这里直接调 `lib.At`，于是**新取进来的关卡**（第 14/16/17 章那四关）
		//: 一出怪就大声失败——下面这段注释**当初就预言了这一天**（见「一旦有哪一关的
		//: 出怪表真引用了本地定义」）。
		es, err := StatsForSpawn(lib, st, sp.EnemyID, sp.Level)
		if err != nil {
			// ⚠ **这里与 `mech._spawns_of` 的 `except: continue` 故意不同口径。**
			//
			// 原版取不到敌人时**静默跳过**那一项——那是闸门自己的盲区：跳过的敌人
			// 一条理由都不贡献，而规格里照样有它。本函数不跟那个口径：取不到就
			// **大声失败**。
			//
			// ★ **2026-09-24 这一天真的到了**（原注释在这里记过它只是「暂时点不着」）：
			// 第 14/16/17 章新取进来的 4 关（`easy_14-11`／`main_14-11`／`main_16-08`／
			// `main_17-17`）的出怪表**真的引用**了关卡本地定义（`enemy_1424_lrboom_3` 等）
			// ⇒ 这一段当场响，`单一入口` 与 `出怪规格` 一族都红在它上面。
			// 处置＝**接线，不是登记**：这一行已改走 `StatsForSpawn`（`enemy.go`），
			// 它带「库里取不到就查 `st.LocalEnemies` 再 `WithOverwrite`」那条回退，
			// 与 `enemy_stats.py:34-55` 同口径、与出怪那条路**同一个入口**。
			//
			// ⇒ 现在这一段只在**两处都没有**时才响（真的没有这份定义），
			// 那才是该大声失败的时候。
			skipped++
			return out, fmt.Errorf(
				"闸门的第 %d 个出怪项取不到敌人 %q 第 %d 档："+
					"敌人库里没有它，这一关的 `enemyDbRefs` 里也没有它"+
					"（`useDb:false` 的本地定义那条回退已经走过，见 `StatsForSpawn`）。"+
					"★ 原版在这里是**静默跳过**，本函数故意不跟——"+
					"静默跳过会让这条闸门对那只敌人永远沉默，而规格里照样有它",
				skipped, sp.EnemyID, sp.Level)
		}
		//: ⚠ **名字要补一次回退**：`enemy.py:1030-1031` 那句
		//: `if not st.name: st.name = self.name(enemy_id)` —— 名字取自「名字非空的
		//: 最高档」，或图鉴，或 id 本身。`EnemyLibrary.At()` 走的是「这一档自己那条
		//: enemyData.name」，两者**不等价**：`enemy_1589_pppdth` 第 1 档的 name 是空
		//: 而第 0 档是 `“死志的凝结”`（本判据的合成夹具就是这么照出来的——
		//: 那 251 只被现有判据覆盖的敌人**恰好**每档都有名字，所以这条一直沉默）。
		//: 闸门要的是原版那句读出来的名字，故在这里补同一条回退。
		name := es.Name
		if name == "" {
			name = lib.Name(sp.EnemyID)
		}
		//: 判据是**字段驱动**（字段非零 ⇒ 那段代码这一局会跑），不看名字、不看描述。
		if es.AwakeValue != 0 {
			add("awake", name)
		}
		if len(es.Modes) > 0 {
			add("modes", name)
		}
	}
	out.Scanned["spawn_skipped"] = skipped
	for _, line := range order {
		names := got[line].who
		sort.Strings(names)
		why, known := gateLineWhy[line]
		if !known {
			//: 新增一条敌人侧线却忘了登记文案 ⇒ 当场失败，**不许退到某条默认文案**：
			//: 退回去的症状是「理由文本写着觉醒、其实是形态」，而理由文本正是
			//: 这份应答唯一的对外契约（判据按它分类）。
			return out, fmt.Errorf(
				"闸门内部错误：敌人侧的线 %q 没有文案（新增线时忘了登记 gateLineWhy）", line)
		}
		out.Covered[line]++
		out.Reasons = append(out.Reasons,
			fmt.Sprintf("%s：%s", why, strings.Join(names, "/")))
	}

	// `mech.port_reasons` **恒为空**（`simgo/mech.py:180-202`）：田地几何、环境
	// 伤害、泵站泵水都已接线，还没接线的部分由别的闸门盖住、不在那里重复报。
	// 照搬这个常量，并记一次「这道检查跑过了」。
	out.Scanned["mech_port_reasons"] = 0

	// ---- 去重但保序（`spec.py:262-269`）----
	seen := map[string]bool{}
	uniq := []string{}
	for _, r := range out.Reasons {
		if !seen[r] {
			seen[r] = true
			uniq = append(uniq, r)
		}
	}
	out.Reasons = uniq
	return out, nil
}

// gateLineWhy 是**敌人侧**已搬线的理由文案。与 `spec.py` 里的字面量逐字相同：
//   - `awake` ← `field_why["awake_value"]`
//   - `modes` ← `mech.ENEMY_BEHAVIOR_ATTRS["modes"]`
//
// ⚠ `field_why` 里还有一条 `hp_drain_per_sec`（`持续自伤`），它**故意不在这里**：
// 那是**干员**字段（`unit.py:721`、`operator_view.py:179`），而 `enemy_view`
// 从不设它 ⇒ 原版那条线永远取到 0（24 份夹具 1154 个出怪对象命中 0）。
// 搬一条两侧都不响的线只会让覆盖表上多一个永远为 0 的行。
var gateLineWhy = map[string]string{
	"awake": "按田地病害值觉醒",
	"modes": "BOSS 换弱点形态",
}

// loadGateStage 取关卡：合成关卡走文件，真关卡走索引。
//
// ⚠ 合成关卡那一支与 `routeplans` / 出怪规格共用 `loadStageFromFile`
// （`etaroutes.go`）——「一份口径只留一处」，两处各写一遍必然走散。
func loadGateStage(level, path, difficulty string) (*Stage, error) {
	if path != "" {
		return loadStageFromFile(path, difficulty)
	}
	if level == "" {
		return nil, fmt.Errorf("unsupported 少了 level（关卡号或 levelId）或 path（合成关卡 JSON）")
	}
	return LoadStage(level)
}

// gateSpawns 把出怪表摊平成**与 `Stage.timeline()` 同序**的一串。
//
// `timeline()` 的两处语义不能漏（`gamedata/stage.py:724-728`）：
//
//   - **按数量展开**：`times = [fragment_start + pre_delay + i*interval …]`
//     ——一条 `count: 3` 的指令摊成三条不同时刻的事件；
//   - **按 (时刻, wave, fragment) 排序**，不是按它在 `waves` 里的书写顺序。
//
// 只影响**理由的顺序**，不影响集合。但顺序是契约的一部分，所以照搬。
//
// ⚠ 不必真的展开：把每条指令按「它第一次出现的时刻」排序，得到的**首次出现顺序**
// 与展开后再排**必然相同**——展开只会把同一条指令的后续时刻往后加，追不平它的首刻。
func gateSpawns(st *Stage) []EnemySpawn {
	type ev struct {
		first float64
		sp    EnemySpawn
	}
	evs := make([]ev, 0, len(st.Spawns))
	for _, sp := range st.Spawns {
		evs = append(evs, ev{first: sp.FragmentStart + sp.PreDelay, sp: sp})
	}
	sort.SliceStable(evs, func(i, j int) bool {
		if evs[i].first != evs[j].first {
			return evs[i].first < evs[j].first
		}
		if evs[i].sp.WaveIndex != evs[j].sp.WaveIndex {
			return evs[i].sp.WaveIndex < evs[j].sp.WaveIndex
		}
		return evs[i].sp.FragmentIndex < evs[j].sp.FragmentIndex
	})
	out := make([]EnemySpawn, 0, len(evs))
	for _, e := range evs {
		out = append(out, e.sp)
	}
	return out
}
