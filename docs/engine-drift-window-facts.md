# 引擎漂移窗口：事实登记（**不含判断**）

> 记录人：RIOS后端2（session-37b2c3e2-6993-4a98-a7d2-5f09d62088a2）。
> 依据 PM 2026-09-20 指示「先把这三条作为事实落进 docs/（或你的台账），不要下判断」。
> **本文件只登记可复核的事实与坐标。**
> **「哪一侧才是对的」（Go 对／Python 过宽）不在这里判——归博士裁定。**

## 事实 1 · 二分区间是 19:08:28 → now，不是 22:13

* 19:08:28 是**那枚与权威实现 Python 在 `hsex8_max` 上逐位一致的 exe** 的构建时刻
  （留证副本 `out/acceptance/rios-sim-legacy-1908_b3e4d6b1.exe`）。
* 22:13 是**记基线**的时刻，**与"构建"不是一回事**（PM 2026-09-20 已确认这两者被混着说过）。
* ⇒ 找"当前 Go 与那枚 exe 之间的行为差"时，区间起点应取 19:08:28。

## 事实 2 · 该区间内动过 `sim.go` 且含**非 Trace 行为改动**的只有两笔

| 提交 | 时刻 | `sim.go` 改动量 | 非 Trace/注释行 | 目录里的可辨符号 |
| --- | --- | --- | --- | --- |
| `d7d8319` | 21:26:16 | ±1110 行 | **501 行** | `const frozenResDown = 15.0`、`const coldASPDDown = 30.0`、`const aspdMin = 20.0` 等 |
| `d5eeb60` | 21:35:27 | ±74 行 | **25 行** | `+ freezeFriendly bool`、`- if e.frozen()` → `+ if e.friendlyFrozen()` 等 |

同区间另有 6 笔只碰 `control.go`／`fear.go`／`palsy.go`／`element.go`／`mech/snow.go` 与测试
（`38c04eb` 21:57／`6bc4eea` 21:48／`fb0d165` 21:45／`e0e7991` 21:42／`8accbb8` 21:40／`d01eeb6` 21:30）。
**它们有没有接线、接在哪，不在本文件登记范围**（下一批取证的内容）。

**可复核方法**：`git log --since='2026-09-19 19:08:28' --until='2026-09-19 22:13:00' --name-only -- rios-sim/`；
逐笔 `git show <sha> -- rios-sim/sim.go` 后剔除 `Trace`／注释行计数。

## 事实 3 · `fixtures/hsex8_max.json` 是 22:30 才新建的

* 由 `3bab699`（22:30:05，判据集入版本控制：新建 `fixtures/`）创建。
* ⇒ **夹具本身**（"基线读数"这份文件）在漂移区间的**末端**才存在。
* ⇒ 二分时不要把"夹具被创建"与"引擎变了"混成一件事。

## 事实 4 · 一个 git 二分**看不见**的洞（对任何区间都成立）

`rios-sim/main.go`／`mech/mech.go`／`mech/huai_shu_li.go`／`wire.go`／`skill.go` 这 5 个文件
**从 19:08 之前一直到 `c2ed574`(23:22:46) 提交为止都是未提交状态**。

* `git show c2ed574:rios-sim/wire.go` 得到的是 **23:22 的磁盘内容**，
  **不等于** 19:08 那棵树的内容；两者之间若有编辑，**任何沿提交走的二分都看不见**。
* ⇒ 区间结论里应显式写一句「未提交期不可二分」，避免"二分到底也没找到原因"被读成"Go 没变化"。

## 事实 5 · 一处**文档与实现互相矛盾**（只登记矛盾，不判该改哪边）

* `ak_tactic/simgo/spec.py:202-208` 的闸门注释写：
  「**原版自己也没有消费它**——全仓 `sluggish_timer` 只有两处，一是置位、二是每帧倒计时」。
* 穷举实测：全 Python 树里 `sluggish_timer` 共 **16 处**（命令：`Select-String -Pattern 'sluggish_timer'`
  扫 `ak_tactic/**/*.py`），其中**包含一处移动拦截消费点**：
  `ak_tactic/battle/unit.py:1533-1537` —— `advance()` 里
  `if self.sluggish_timer > 0 or self.idle_timer > 0: return`（注释原话「【停顿】/【待机】不能移动。停顿还能开火」）。
* ⇒ 两处陈述**不能同时为真**。**哪一边对、闸门该不该留，本文件不判**（涉及机制层的裁定）。

---

**关联**：`tools/coverage_table.py` 行「停顿」的依据栏已按 PM 2026-09-20 的决定程序
（第 1 步取证 → 第 2 步换锚点）更新，锚点由 `sim.go::speedFor` 改为 `sim.go::runSim`
（真实消费点＝推进闸门 `sim.go:760-769`）；字段 `sim.go:174 sluggishTimer` 因不是顶层定义、
`anchor_ok()` 实测判「锚点失效」，未作锚点。
