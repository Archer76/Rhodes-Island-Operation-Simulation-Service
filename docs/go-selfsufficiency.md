# rios-sim 自足进度台账

> **本文性质**：**手写文档**（不是生成物）。数字是**写这一版时现跑**的读数，
> 引用时请连命令与时刻一起引——它不会自己更新。
>
> 最后核对：2026-09-20 ｜ 判据入口 `python tools\check_go_all.py --selfcheck`

---

## 〇 · 一句话

**取数五层（关卡／敌人／干员／名册／计划）已经搬进 Go，且每一层都有跨实现
对拍判据。** 缺的是「把效果折成两套数值」的**装配**与「规格构造」——那两段
还在 Python。两套数值要的那几处读数已全部落地为纯函数（`rios-sim/profile.go`、
`panelfold.go`）；没落地的是**喂它们的实时输入**（光环／翔虫机动／替身计时／
击杀叠层／出手次数／阻挡／高台邻居这些运行态）。名册与计划**已经接上了**——
`rios-sim/loadout.go` 把两份输入合成一组面板入参（与 `Verifier._entry` 逐字段
一致）；没接上的是**把这份练度送进面板折算**的那一段接线。

---

## 一 · 判据入口：一条命令出两个结论

```
python tools\check_go_all.py --selfcheck
```

* 前半：**十八套判据现在不报红**；
* 后半：**十八套的反向守卫都成立**（每套人为注入一处不一致，它真会红）。

★ 两个结论缺一不可：「全绿」只证明现在不报红；**没有反向守卫的绿是零信息量的绿**。

### 收口量测（另一条命令，答的不是「绿不绿」）

```
python tools\closeout_selfsufficiency.py
```

它**不做跨实现对拍**（那是上面那十二套的事），只把**本文档里的每个数拿回
代码里重新数一遍**：命令 ↔ 判据 ↔ 台账 三处同屏、缺口表行数、以及
「Go 侧有没有从计划＋名册造规格的入口」。数不上就红——防的不是写错，
是**文档悄悄过期**。

★ 它自己也有反向守卫（`--mutate` 改动声明的一处数 → 必红），并且带一条
**不依赖仓库文件**的量尺自检（就地造一张带表头的表）。来历：第一版把表头
当数据行，读数表数出 13（真值 12）——那是尺子错，不是仓库错，所以尺子
也要有自己的正负对照。

### 当前读数

| 判据 | 取证面 | 读数 |
|---|---|---|
| 关卡 `check_stage_go.py` | 缓存可达的 55 关 | 55 / 55 关逐字段一致 |
| 敌人 `check_enemy_go.py` | 那 55 关引用的全部敌人 | 251 只敌人逐字段一致 |
| 干员 `check_operator_go.py` | fixtures 20 位深扫 ＋ **账号名册全量 211 位** | 679 次折算逐字段一致 |
| 范围 `check_range_go.py` | 全表 73 个代号 × 4 朝向 | 292 / 292 次逐格一致 |
| 技能 `check_skill_go.py` | 全表 1810 技能 × **每一级** | 11012 条逐字段一致 |
| 分类 `check_classify_go.py` | 全表黑板键并集 1056 个 | 1056 / 1056 逐字段一致 |
| 生命上限 `check_profile_go.py` | 网格 base 5 × cur 4 × pct 5 | 100 / 100 点逐点一致 |
| 攻击间隔 `check_interval_go.py` | 网格 base_iv 6 × base_spd 5 × 两 buff 4×5 | 600 / 600 点逐点一致 |
| 面板 `check_panel_go.py` | 有序叉乘 13848 行（另含派生边界小表） | 13848 / 13848 行逐字段一致 |
| 名册 `check_roster_go.py` | 真夹具 ＋ 11 例合成（口径各不相同） | 10 例逐字段一致 ＋ 1 例登记分歧 ＋ 1 例两边都拒 |
| 计划 `check_plan_go.py` | **`fixtures/` 下全部 24 份打法夹具**＋ 24 例合成 | 32 例逐字段一致 ＋ 1 例登记分歧 |
| 练度 `check_loadout_go.py` | 全部 24 份夹具 × 真名册 ＋ 12 例合成 | 33 例逐字段一致 ＋ 3 例两边都拒 |
| 关卡静态 `check_stageenv_go.py` | 缓存可达的 55 关 × 2 档难度 ＋ 8 例合成 | 126 例逐字段一致 |
| 格表 `check_cells_go.py` | 缓存可达的 55 关 | 55 / 55 关两张格表逐格一致 |
| 部分规格 `check_specgo_go.py` | 55 关 × 12 个值键 ＋ 键集账（ast 抽 19 键）＋ 24 份夹具 × 生产规格 ＋ **deploys 64 条** ＋ **6 份合成计划的 skill_uses 18 条**（故意乱序） | 全部一致 |
| 费用天赋 `check_costbonus_go.py` | 12 种黑板形状 × 10 种队伍组合 | 10 / 10 次求解一致 |
| 部署费用 `check_costof_go.py` | 24 份夹具 × **生产规格的 `deploys[].cost`** | 64 人次一致 |
| 寻路 `check_stagepath_go.py` | 55 关的全部路线 × 两档斜向 | 2594 / 2594 逐格一致 |

---

## 二 · 已经自足的部分（Go 直读 data/gamedata）

| 层 | Go 文件 | 读什么 | 判据 |
|---|---|---|---|
| 关卡 | `rios-sim/stage.go` | `_level_index.json` ＋ `level_*.json` | `check_stage_go.py` |
| 敌人·属性 | `rios-sim/enemy.go` | `enemy_database.json`（逐档合并、`useDb:false` 本地覆盖） | `check_enemy_go.py` |
| 敌人·派生 | `rios-sim/enemy_derive.go` | 相性／屏障／击杀费用／重生／技能攻击 | 同上 |
| 敌人·机制前缀 | `rios-sim/enemy_mech.go` | 七个前缀共 36 个字段 | 同上 |
| 干员·面板 | `rios-sim/operator.go` | `character_table.json` ｜ `char_patch_table.json` ｜ `battle_equip_table.json` | `check_operator_go.py` |
| 干员·天赋 | `rios-sim/operator_aspd.go`、`operator_traits.go` | 攻速／连击／强击瓶／特性族／文本判据／身份／翔虫 | 同上 |
| 干员·范围 | `rios-sim/range.go` | `range_table.json` ＋ 旋转/平移 | `check_range_go.py` |
| 技能·元数据 | `rios-sim/skillmeta.go` | `skill_table.json`（状态机参数／黑板／级号／正文渲染） | `check_skill_go.py` |
| 技能·分类 | `rios-sim/classify.go` | 四张分类表 ＋ 拆变体 ＋ 降级序列 | `check_classify_go.py` |
| 技能·效果 | `rios-sim/effects.go` | `_parse_effects` 全量（五个箱子 ＋ 两个计数 ＋ 演出参数） | `check_skill_go.py` |
| 数值 profile·纯函数 | `rios-sim/profile.go` | 两套快照里**不必驱动原版读数函数**的那两行：生命上限加成、开技能间隔折算 | `check_profile_go.py`、`check_interval_go.py` |
| 数值 profile·五处读数 | `rios-sim/panelfold.go` | 同一帧的 atk／def／res／攻速／间隔／目标数／伤害类型（另含 `max_target` 那条 `max(1, int(… or 1))` 派生） | `check_panel_go.py` |
| 名册·练度 | `rios-sim/roster.go` | MAA OperBox 导出与森空岛名册两种外形（`own` 恒等过滤／`or` 兜底／按名做键／插入序） | `check_roster_go.py` |
| 计划·打法 | `rios-sim/plan.go` | 部署／撤退／技能三条指令序列 ＋ `validate` 四条 ＋ `__post_init__` 三条（坐标截断、朝向表、技能槽 0–3） | `check_plan_go.py` |
| 名册＋计划·练度解析 | `rios-sim/loadout.go` | 打法覆盖名册缺省、三条 `setdefault`、`char_id` 按名字回退（走 `character_table` 的**行序**取首个匹配） | `check_loadout_go.py` |
| 规格·关卡静态 8 项 | `rios-sim/stageenv.go` | `build_spec` 19 个顶层键里不依赖 sim／干员／机制的那 8 个（`options` ＋ `runes` 的掩码消歧与两条改写） | `check_stageenv_go.py` |
| 规格·两张格表 | `rios-sim/cells.go` | `goal_cells`（防守点格，按 (x,y) 排序）与 `highland_cells`（高台格，保持行序） | `check_cells_go.py` |
| 规格·骨架装配 | `rios-sim/specgo.go` | 把已能造出的 12 个键装配成一份部分规格，并**自报还差哪 7 个**（键集拿 ast 从源文件核对） | `check_specgo_go.py` |
| 规格·起始费用天赋 | `rios-sim/costbonus.go` | `squad_cost_bonus`：滤掉 `$` 后签好只剩 `cost` 才认（`deploys`／`skill_uses` 排程的起始费用要用它） | `check_costbonus_go.py` |
| 规格·部署费用 | `rios-sim/deploycost.go` | 各自练度下的 `total["cost"]`（取数口径与干员判据同一份，不另立；这里只是把它单独取出来） | `check_costof_go.py` |
| 规格·地面寻路 | `rios-sim/stagepath.go` | `StageMap.ground_path`（Dijkstra；`"ALL"` 子串判定／`tile_hole` 不可走／不许斜穿墙角／**同距离按格坐标字典序决胜**） | `check_stagepath_go.py` |
| 规格·骨架装配 | `rios-sim/specgo.go` | 已落 14 个键；`deploys`／`skill_uses` 传了计划才有（`omitempty` 在这里承担语义） | `check_specgo_go.py` |

---

## 二·补 · 剩下 5 个键的**真实前置**（2026-09-21 量清）

19 个顶层键已落 14。剩下 5 个**各自都压着一层不在 Go 的机制**——不是「再写 100 行」那种距离。
这一节存在的意义：让下一轮不照着「看起来快」的顺序挑，而照着**真的能做完**的顺序挑。

| 键 | 真实前置 | 距离 |
|---|---|---|
| **路线生产侧**（`eta.py` 的 `route_plans` ＋ `leading_wait` ＋ `polyline_length` ＋ `_walk_visits`，以及 `route.legs(…)` 与 `map.ground_path(…)` 的来处） | **它是 `spawns` 与 `unsupported` 的共同阻点**——不是某个键各自的坑 | **真正的下一步** |
| `unsupported`（闸门） | 166 行。★ **更正**：上一版这里写「敌人库 Go 已有、最好落」，那是**估的**。量过之后：`_enemy_reasons` → `mech._spawns_of(inp)` → `_route_tables(inp.stage)` → `eta.route_plans` ⇒ **它压在路线生产侧上**，与 `spawns` 同一条 | 远（同 spawns） |
| `operators` | `_operator_spec`（162 行）→ 两套数值快照 → **技能效果层**（`effects_of(sim, op)`），而效果层要技能白名单与 `SkillEffects` 组装 | 远（同 effects 层） |
| `spawns` | `_unit_spec`（128 行）＋ 路线生产侧 | 远（同路线生产侧） |
| `mechanisms`／`mech_config` | 机制层（每个活动一份、按需取用） | 远 |

★ **`spawns` 那条要特别记**：实测 Go **只有消费侧**——`sim.go` 沿 `LegSpec` 走，
而 `Legs` 是**从规格里收来的**（Python 给的）。生产侧（`route.legs(…)` 构建器 ＋
`ground_path`）**Go 里没有**。所以在动手之前别把它当成「敌人库已有、顺手就能做」：
那会写出**第二套路线逻辑**，而两套会各自「看着对」。

### 路线生产侧·进行中的一处未解（2026-09-21）

`ground_path` 的 Go 版**已写好并跑过一次对拍**，结果是**6 处失配**，形状全是
`[0,6]→[0,6]：Go 长 1 / Python 长 12`。已经把嫌疑从三个收成一个，**留给下一轮**：

1. ~~实现错~~ —— 排除：逐行搬自 `stage.py:172-226`，含 `"ALL"` 是**子串**判定、
   `tile_hole` 不可走、**不许斜穿墙角**、以及**同距离时按格坐标字典序决胜**
   （原版的堆是 `(距离, 格)` 元组；只比距离会挑到另一条等长折线）。
2. ~~判据配对错位~~ —— 排除：对 `act31side_01` 自证 32 例，
   `PAIR-MISMATCH 0`、`SAME-CELL-MULTI 0`、`BAD 0`。
3. **只剩一个嫌疑：Go 侧收到的 query 与判据发出的不一致。**
   线索很窄——Go 答的是**长度 1**，而 `GroundPath` 里只有 `start == end`
   一个出口会这么答。

**下一轮的第一步**：重加 `path` 命令，并在应答里**回显收到的
`start` / `end` / `diagonal`**，跑第一条失配用例。收到的若真是
`[0,6]→[0,6]`，就说明解码或关卡解析把它弄成了同格，一处即可定位。

★ 两轮之间不要跳过这一步去改实现：`Route.start/end` 声明与实测都是
`tuple[int, int]`，**原版不可能对同格返回 12 点**——所以那个「Python 长 12」
本身就是待解释的现象，不是实现的靶子。

**又排除一个假设（2026-09-21，第 20 轮）**：「判据用原始端点算期望、
用 `int()` 归一化后发查询」——实测 2594 例（55 关的全部路线 × 两档斜向），
两者的路径长度**差异 0 例**。所以假信号不在这一点上。

⇒ 到这一轮为止，凡是**能在不重建 Go 的前提下测的**假设都测过了，全部为假。

### ★ 根因找到了（2026-09-21，第 21 轮）：判据里的**陈旧变量**

回看那一版判据的统计段：

```
if q["start"] == q["end"]:
    seen["退化：起终点相同"] += 1
elif not st.map.walkable(...):
    seen["退化：端点不可走"] += 1
elif len(wm := [...]) == 2 and ...:      # ← wm **只在这一支**被赋值
    seen["不连通退回直线"] += 1
else:
    seen["直行（含斜向）"] += 1
if gm != wm:                              # ← 前两支走到这里时，wm 是上一轮的值
```

`wm` 用海象运算符只在一个分支里赋值；用例落进前两支时它**留的是上一轮的
期望值**，于是拿陈旧值去比，必然不等。**证据吻合**：
`seen["退化：起终点相同"]=160`，而报出来的失配形状全是 `[0,6]→[0,6]`
这类同格用例——正是第一支。

⇒ 那不是 `ground_path` 实现错。**这一整段四轮的悬案，根因是判据自己的一个
陈旧变量**，与第 4 轮 `plan-hsex08f` 那次同族：**红的是仪器，不是对象**。

**教训（值得单独记）**：分支内的赋值语句不要在分支外使用——尤其是
海象运算符。想看「这个用例属于哪一类」可以，但**分类与期望值必须是两件事**，
期望值要在循环开头无条件算好。

### 路线生产侧·另一半 `Route.legs`（2026-09-21，第 23 轮，待落）

`ground_path` 已落（18 套判据里的「寻路」），另一半是 `Route.legs`
（`stage.py:415-481`，67 行）。**已经读透**，落它的条件齐了：

* **Go 侧字段齐备**：`Route{Index, Mode, Start, End, Checkpoints}`、
  `Checkpoint{Type, Position *[2]int, Wait}`——`Position` 还是三态指针，
  正合「`WAIT_FOR_SECONDS` 与 `DISAPPEAR` 的 position 是 `(0,0)` 占位、
  当坐标用会画出穿过地图原点的假路径」那条。
* **算法**：`WALK` 模式下相邻路点之间**沿可行走地块寻路**（调的就是刚落地的
  `ground_path`）；`FLY` 模式是直线、不寻路。输出是 `RouteLeg` 序列，
  三种 kind：`walk`（带 `points` 与折线长）、`vanish`（`DISAPPEAR` 之后、
  下一个 `APPEAR_AT_POS` 之前的所有 `WAIT_FOR_SECONDS` 之和）、
  `wait`（等待秒数）。
* **`flush()` 里那条接续**：相邻两段之间 `pts.pop()` 去掉重复顶点——
  漏了它折线会多一个重复点，长度不变而 `points` 不同。

**唯一还差的读数**：三个判定谓词的**确切写法**——`is_move` / `is_appear` /
`is_wait`（`stage.py:283-300`，共约 7 行）。已知的线索：`leading_wait` 用的是
`type != "WAIT_FOR_SECONDS"`，所以 `is_wait` 就是它；`is_move` / `is_appear`
按 `MOVE` / `APPEAR_AT_POS` 推测——**但推测不算数，读一次再写**。
剩下的路只有一条：**重写判据（按 `(关卡, 路线号, 斜向)` 显式建键）＋ 重加
`path` 命令并回显 query，一次跑完**。那件事需要一个完整的会话余量，
不适合在推理占满上下文之后再挤。

---

## 三 · 未接的部分（具名，不是「没提就是没有」）

| 缺口 | 说明 |
|---|---|
| **两套数值 profile** | **折算本身已全部落地**（`profile.go` 两行 ＋ `panelfold.go` 七处读数，合计 14548 个网格点/叉乘行）：核对下来原版那七个方法**只读实例属性**，替身对象即可当 oracle——原先以为非搭不可的 harness 省掉了。仍缺的是**喂它们的实时输入**（光环、翔虫机动、替身计时、击杀叠层、出手次数、阻挡、高台邻居、偷取攻速这些运行态），以及 `_profile` 自己「临时把开技能字段摆成开启态、读完立刻还原」的那段装配。 |
| **练度 → 面板的接线** | 练度**已经解析出来了**（`rios-sim/loadout.go`，与 `Verifier._entry` 逐字段一致），但它**还没被送去算面板**：`opstats` 目前仍由调用方逐个送练度，没人把 `loadout` 的输出接进去。 |
| **`skill` 的对象形态** | `Plan` 那一条指令的 `skill` 除整数外还可以是对象（丙方案），要 `_skill_from_json` 查技能书、按槽位/等级解成技能 id。本轮**未接**：Go 碰到对象就**具名拒收**，不假装读懂。好消息是 `fixtures/` 下 24 份打法的 `skill` 全是整数，走的是与改动前同一条路。 |
| **规格构造与闸门** | `simgo/spec.py`（76 KB）＋ `simgo/skills.py` 的白名单。Go 现在仍收 Python 送来的 spec。★ **已落地 14 个键**：不依赖 sim／干员／机制的**关卡静态 8 项**（`stageenv.go`）、**两张格表**（`cells.go`）、以及**传了计划才有的 `deploys` 与 `skill_uses`**（`specdeploys.go`）。剩下 5 个键：`operators`／`spawns`（要 `_operator_spec`／`_unit_spec`）与 `mechanisms`／`mech_config`／`unsupported`。 |
| **干员侧的其余天赋** | `advisor` 表里除已接的那几支之外的部分（`is_*` finder 一族里尚未逐条搬完的）。 |
| **干员技能的性质** | 比如「技能改写攻击范围」的消费点。 |

---

## 四 · 三十轮里最贵的四条判据纪律（都是踩出来的）

1. **判据「全绿」之前，先看它的分母是多少。** 汇总入口会缩放覆盖面，
   缩水的那一行照样打勾（实测：带 `nargs` 的判据被按缺省跑，分母从 55 掉到 1）。
2. **判据过期与对象出错长得一模一样。** 实测：Go 换了字段形状而判据仍按旧名取，
   11012 条全红——**红的是尺子**。反过来，按红去改实现会改坏一个对的东西。
3. **期望值能从被测方的权威实现取，就不要自己再写一遍。** 实测：
   我照表手写期望值，`control` 的量纲两处都写成 `secs`（真值 `sec`），
   判据全绿——它在替我自证。改成问 `_classify` 本身才第一次真取证。
4. **没读全的东西不许混进判据，也不许当成「拿到了一半」。** 实测：
   `_parse_effects` 只读前半段就做计数账，报 11002/11012；
   差异只是一个分支的 `classified` 该不该加——**回退去读尾部，差异自己现形**。

---

## 五 · 怎么加一块新的

1. 写 Go 侧取数（新文件优先，别覆盖既有同名文件）；
2. 写一条跨实现对拍：**期望值优先从 Python 的对应实现取**，不自己重写口径；
3. 覆盖面**遍历全集**、不抽样；
4. 带 `--mutate` 反向守卫；
5. 在 `tools/check_go_all.py` 的 `SUITE` 里**加一行**（不加就等于没进总表）；
6. 提交前照例四道 rc：`build` / `lint` / 本判据 / `--mutate`，
   **全绿才提交**（`build rc≠0 就停`——否则检查会跑上一版二进制，绿得没有意义）。
