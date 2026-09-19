package main

// 脆弱（fragile）：使目标**受到的伤害提升相应比例**。
//
// ── 取证（2026-09-19）──
//   - **它不是异常效果**。PRTS `异常效果` 权威表（`?action=raw`，客户端 2.7.61）逐行核对，
//     43 个异常效果 + 2 占位里**没有**脆弱。它是 Buff / 伤判效果。
//     ⇒ 别去 `abnormalFlag` 里找它——那里没有，硬找只会误抓别的开关。
//   - 词典原文：「受到的物理、法术、真实伤害提升相应比例（**同名效果取最高**）」。
//   - 公式层**已经认得它**：`formula.py` 的 `fragile`（`attr="脆弱"`）与 `fragile_effect`、
//     `enemy_formula.py` 的 `e_fragile`（`attr="=a"`）与 `e_damage_amp`（`attr="受到伤害"`）；
//     **引擎侧零消费**——本文件补的就是被消费的那一段。
//
// ── ⚠ 一处未取证：**不同名**的脆弱之间怎么合 ──
// 词典只写了「同名取最高」，**没有**写异名之间是相加还是相乘。
// 本实现取**异名相加**（依据是 `作战机制` 页战斗 Buff 的通用模型那一栏
// 「直接乘算 Y₂=Y₁(1+b₁%+b₂%)」），但**没有针对脆弱的权威原句**，所以：
//   ① `ratioFor` 把这个选择写死，并用守卫钉住（`TestFragileDistinctNamesAdd`）；
//   ② 取到权威原句后要改它，**守卫会先红**——不许静默改口径；
//   ③ 这一条与元素损伤口径那一条同性质，属于「要先取证再定」的，不靠猜。
//
// ── ⚠ 另一处刻意不做的：**元素脆弱是另一条** ──
// 「元素脆弱」（`ep_fragile`）只提升**元素损伤**，与「脆弱」只提升**物理/法术/真实伤害**
// 是两条不同的轴。本实现**不**把元素损伤算进来，并有守卫钉住这一点
// （`TestFragileDoesNotAmplifyElementDamage`）——混轴会让两边都错。

// fragileBuff 是一条脆弱效果：**每条各自计时**，不合并。
//
// 为什么不合并成"每个名字一条"：同名效果取最高，但**各自的时间是独立的**——
// 合并会把"短的那条到期了、长的还在"这种情形算错（比例会跟着短的那条一起消失）。
// 所以这里保留每一条，取值时再按名字分组取最大。
type fragileBuff struct {
	Name   string  //: 效果名——「同名取最高」就按它分组
	Ratio  float64 //: 提升比例：0.3 表示受到伤害 +30%
	Remain float64 //: 剩余秒数
}

// fragileState 是单位身上的一整套脆弱。
type fragileState struct {
	Buffs []fragileBuff
}

// Add 施加一条脆弱。比例或时长非正的一律不记（数据里 0 值很常见，记下来会变成"永久的 +0%"）。
func (f *fragileState) Add(name string, ratio, secs float64) {
	if name == "" || ratio <= 0 || secs <= 0 {
		return
	}
	f.Buffs = append(f.Buffs, fragileBuff{Name: name, Ratio: ratio, Remain: secs})
}

// Tick 推进计时并丢弃到期的。返回是否发生了变化（供痕迹/快照判断用）。
func (f *fragileState) Tick(dt float64) bool {
	if len(f.Buffs) == 0 {
		return false
	}
	live := f.Buffs[:0]
	for _, b := range f.Buffs {
		b.Remain -= dt
		if b.Remain > 0 {
			live = append(live, b)
		}
	}
	f.Buffs = live
	return true
}

// Ratio 返回当前的伤害提升比例。
//
// 规则（两条，分别是取证过的与未取证的）：
//   - **同名取最高**（词典原文）：同名效果只算比例最大的那一条，**不相加**；
//   - **异名相加**（未取证，见文件头）：不同名的各自相加。
func (f *fragileState) Ratio() float64 {
	if len(f.Buffs) == 0 {
		return 0
	}
	byName := make(map[string]float64, len(f.Buffs))
	var order []string
	for _, b := range f.Buffs {
		if cur, ok := byName[b.Name]; ok {
			if b.Ratio > cur {
				byName[b.Name] = b.Ratio
			}
			continue
		}
		byName[b.Name] = b.Ratio
		order = append(order, b.Name)
	}
	var sum float64
	for _, n := range order {
		sum += byName[n]
	}
	return sum
}

// Apply 把脆弱作用在**一次已经算好的伤害**上。
//
// ⚠ 输入是伤害、**不是攻击力**：脆弱提升的是「受到的伤害」。
// 这正是元素损伤那条口径歧义的反面——这里原文写的就是伤害，不含糊。
// 元素损伤**不**走这里（见文件头最后一段）。
func (f *fragileState) Apply(dmg float64) float64 {
	if dmg <= 0 {
		return dmg
	}
	return dmg * (1 + f.Ratio())
}

// Active 报告当前是否有效，供调用方决定要不要打痕迹。
func (f *fragileState) Active() bool { return len(f.Buffs) > 0 }

// Names 返回当前生效的效果名（去重、稳定顺序），供痕迹用。
func (f *fragileState) Names() []string {
	var out []string
	seen := make(map[string]bool, len(f.Buffs))
	for _, b := range f.Buffs {
		if seen[b.Name] {
			continue
		}
		seen[b.Name] = true
		out = append(out, b.Name)
	}
	return out
}

// TraceFragile 打一行 `FRAGILE` 痕迹。
//
// 键值形状与 `ELEM`/`HITOP` 一致（`<TAG> t=%.4f k=v …`），`tools/trace_kv.py` 是唯一解析入口。
// 刻意打出 `ratio` 与 `names`：脆弱是**乘在伤害上**的效果，不把乘出来的结果打出来，
// 事后就无法回答"这一笔伤害为什么比面板高"（记忆 62 5ec7b4：机制直伤要共用扣血入口，
// 而增伤类效果必须在**伤害发生的那一刻**留下值，事后无法反推）。
func TraceFragile(t float64, who string, ratio, before, after float64, names []string) {
	if ratio <= 0 {
		return
	}
	joined := ""
	for i, n := range names {
		if i > 0 {
			joined += ","
		}
		joined += n
	}
	trace("FRAGILE t=%.4f who=%s ratio=%.4f before=%.3f after=%.3f names=%s",
		t, who, ratio, before, after, joined)
}
