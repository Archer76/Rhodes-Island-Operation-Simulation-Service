# rios-sim 自足进度台账

> **本文性质**：**手写文档**（不是生成物）。数字是**写这一版时现跑**的读数，
> 引用时请连命令与时刻一起引——它不会自己更新。
>
> 最后核对：2026-09-22 ｜ 判据入口 `python tools\check_go_all.py --selfcheck`

---

## 〇·零 · 停在哪、为什么停、从哪接（2026-09-21 收束）

**停在哪**：目标「把 `simgo/spec.py` 的规格构造整层搬进 Go」跑完了它那一轮预算
（30 轮）。**19 个顶层键已落 14**，18 套判据全绿，本台账的收口量测一致。
规格**仍由 Python 经 `req.Spec` 送进 Go**——目标最后那半句**没有达成**。

**为什么停**：不是卡在技术上，是**那个会话的判断预算用尽**。最后几轮的形状
可以自证：写完整实现再回退（2 次）、只够做一次假设排除、只够改一段台账。
**目标本身没有变难**——它只是需要一段完整的、没被前面几十次读源码占满的上下文。

**从哪接**：见「二·补」节的三条阻点。按**真能做完**（不是「看起来快」）排序：

| 阻点 | 状态 | 下一轮的第一步 |
|---|---|---|
| **路线生产侧** | 三层**已全部落地**：`ground_path`（2594 例）、`Route.legs`（2157 段逐字段一致，`length` **逐位**）、`eta.route_plans`（1297 条路线逐字段一致） | 往上一层已不是路线：`spawns` 的 `_unit_spec`（敌人视图＋天桩链）与 `unsupported` 的敌人侧 |
| 技能效果层 | 未动 | `effects_of(sim, op)` 的白名单与 `SkillEffects` 组装 |
| 机制层 | 未动 | 每个活动一份、按需取用 |

★ **接手前请先读「二·补」节**，那里有每一条的实测证据与已经排除掉的方向——
重走一遍要花掉一整轮。

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

* 前半：**十九套判据现在不报红**；
* 后半：**十九套的反向守卫都成立**（每套人为注入一处不一致，它真会红）。

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
| 寻路 `check_stagepath_go.py` | 55 关的全部路线 × 两档斜向 ＋ **全部路线的分段计划**（另 7 条合成路线）＋ **全部路线的计划表**（`eta.route_plans`） | 2594 / 2594 逐格一致；分段 2157 / 2157 段逐字段一致（`length` **逐位**）＋ 合成 14 段；计划表 1297 / 1297 条路线 2157 段逐字段一致（`points`/`wait`/`length`/`seconds` 全精确） |
| 闸门 `check_unsupported_go.py` | 24 份夹具的生产规格 ＋ 5 例合成计划 ＋ 5 份合成关卡（另 6 条未搬线各配证人、1 处分歧） | 34 例逐条**同序**一致（其中 6 例有理由、共 9 条）＋ 已搬 7 条线的覆盖对账 |

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
| 规格·路线分段 | `rios-sim/stagelegs.go` | `Route.legs`（三种段 `walk`／`wait`／`vanish`；`WALK` 寻路／`FLY` 直线；`flush()` 里相邻两段之间 `pop()` 去重；长度走 `sum()` 的 **Neumaier** 语义） | 同上（`legs` 命令并进这一套，不单列） |
| 规格·路线计划表 | `rios-sim/etaroutes.go` | `eta.route_plans`：按路线号索引的 `{points, wait, legs}`（＝`_route_tables` 的形状，`spawns` 真正消费的那一层）＋ `leading_wait`（**只累加开头连续**的 `WAIT_FOR_SECONDS`） | 同上（`routeplans` 命令并进这一套，不单列） |
| 规格·骨架装配 | `rios-sim/specgo.go` | 已落 14 个键；`deploys`／`skill_uses` 传了计划才有（`omitempty` 在这里承担语义） | `check_specgo_go.py` |
| 规格·闸门 | `rios-sim/unsupported.go` | `unsupported_reasons` 的已搬部分：排程 3 条（召唤物／装置／撤退）＋ 技能槽号 ＋ 积雪 ×N ＋ 敌人侧 2 条（按病害值觉醒／BOSS 换弱点形态）；未搬的 6 条线具名列在 `unported` 里 | `check_unsupported_go.py` |

---

## 二·补 · 剩下 5 个键的**真实前置**（2026-09-21 量清）

19 个顶层键已落 14。剩下 5 个**各自都压着一层不在 Go 的机制**——不是「再写 100 行」那种距离。
这一节存在的意义：让下一轮不照着「看起来快」的顺序挑，而照着**真的能做完**的顺序挑。

### ★ 四轮测量的结论（重设目标后）：这一节的三处估计都要下调

重设目标后的头四轮**一行代码没写，只做测量**——因为前一个目标里「排序依据是估计
不是读数」赔掉过三整轮。量出来的结果，推翻了我自己写在这一节里的三处判断：

| 原先写的 | 实测 |
|---|---|
| 技能效果层「要技能白名单与 `SkillEffects` 组装」（当成远） | **≈480 行**：`SkillBook._parse_level` 190 ＋ `SkillLevel` 15 方法/114 ＋ `SkillEffects` 13 方法/171 ＋ `OperatorSkill` 24。入口也不是 `effects_of`（`simgo/skills.py:83`，仅 23 行的薄编排），而是 `SkillBook`。**输入侧一半已在 Go**（`effects.go` 的黑板解析、`skillmeta.go` 的状态机参数）。 |
| 机制层「远」 | 缺的只有**规格生成侧** `simgo/mech.py` **537 行**（`_pile_device_spec` 114、`farmland_spec` 79、`names_for` 15…）；**运行期 Go 早就有了一大块**——`rios-sim/mech/` ≈170 KB（`mech.go` 34 KB、`huai_shu_li.go` 57 KB、`snow.go` 35 KB、`chain.go` 6 KB）。 |
| 规格构造「要一个能起 `sim` 的 harness」 | **这个障碍不存在。** `spec.py` 用到的 `inp.<attr>` **一共 13 种**，`mech.py` 不额外加任何。 |

```
stage ×15      range_provider ×2     environment_difficulty
snow_fields    devices               deployments
goal_cells     enemy_at              species_provider
fps            speed_scale           ranged_enemies     enemy_windup
```

其中 **10 个 Go 已有**（`stageenv.go`、排程、`cells.go`、`enemy.go`、`range.go`）。
剩下三个：`snow_fields` **恒空**（`inputs.py:300` 明写「不许改成『现在有几片』」）、
`species_provider` = `lib.species_of`（**enemydb 查表，不在 gamedata 里**）、
`devices` = `frontend/devices.py` **419 行**。

⇒ **剩余工作全景（约 1600 行，全部可指名、各有 Go 侧对照物）**：

| 要搬的 | 行数 | Go 侧 |
|---|---|---|
| `Route.legs` | 67 | ✅ **已落**（第 29 轮，`stagelegs.go`；2157 段逐字段一致） |
| 技能效果组装 | ≈480 | 黑板解析、状态机参数 |
| 机制·规格侧 `mech.py` | 537 | 运行期 ≈170 KB |
| 装置层 `devices.py` | 419 | 部分在 `wire.go` |
| 三个小 provider | <100 | 两个已有 |

**这不是「76 KB 的墙」。** 前一个目标把它当成墙，是这段工作里最贵的一次误判——
它直接决定了后面许多轮的排序。

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

### 路线生产侧·另一半 `Route.legs`（2026-09-21，第 23 轮；**已落，见第 29 轮**）

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

**唯一还差的读数**：三个判定谓词的**确切写法**（`stage.py:282-302`）。已读，
并**更正本台账上一版的一处推测**：

```
is_move   = (type == "MOVE")
is_wait   = (type.startswith("WAIT"))     ← ★ 不是 == "WAIT_FOR_SECONDS"
is_appear = (type == "APPEAR_AT_POS")
```

上一版这里写的是「`is_wait` 必为 `WAIT_FOR_SECONDS`」——**那是推测，而且是错的**。
`startswith` 与 `==` 在这种地方的分叉不会有任何判据报警：遇到别的 `WAIT*`
类型时按 `==` 写会**漏判成等待**，于是那条 checkpoint 既不 flush 也不记秒数。

★ 这条更正本身就是「推测不算数，读一次再写」的实例——本目标里第四次。

### `Route.legs` 卡住的那一处：**公式已排除**（2026-09-21，第 25-26 轮；**第 29 轮已解**）

Go 版写过一次、跑通了：**55 关里 54 关全过**，`walk` / `wait` / `vanish`
三种分段与路径点集逐项相同。失配只在 `act31side_05` 的 5 条路线上，
**且只在 `length` 一个字段上**：

```
Go=24.242640687119287    原版=24.242640687119284     ← 差 3e-15
```

第 25 轮我先后归因到 `math.Hypot` 与 CPython 的 `math.dist` 缩放式，
**两次都不对**。第 26 轮把那条路径的长度用**四种算法**并排算了一遍：

```
dist / hypot / sqrt(平方和) / 按 CPython 写的缩放式   → 四种全给 …284
```

而 Go 侧先后试的三种写法**也全给 …287**。两边各自内部高度一致、彼此不同。

⇒ **差不在长度公式上**。下一轮该查的是：**Go 的 `polylineLength` 拿到的
点列与 Python 的不是同一份**——尽管打印出来看着一样。最可能的入口是
`flush()` 里那条 `pts.pop()` 接续：某个分支上少弹/多弹一次，会得到
**点数相同而累加顺序不同**的折线；累加 23 个 `1.0` 与
`1.4142135623730951` 时，顺序一换末位就变。

**判据修法**：把 `length` 的失败单独报出**两侧的点列原文**（不是截断视图），
一眼就能看出是点列不同还是累加不同。第 25 轮打印的是完整点列、看着相同——
但那是**视图**，不是逐元素比对的结果；两者不同就说明问题出在别处。

### ★ 收窄到「点列」这一步的推理（第 28 轮；**里面有一处默认是错的，见第 29 轮**）

第 28 轮查了两件事，把答案逼出来了：

1. **仪器不陈旧**：`exe` 比本树最新的 `.go` 新 ⇒ 「三个公式其实是同一个
   二进制在答」这个可能排除。
2. **单位步下三种公式逐位相同**：那条路径的每一步都是单位步
   （`dx, dy ∈ {0,1}`），而

   ```
   sqrt(1² + 1²) = hypot(1, 1) = CPython 缩放式 = 1.4142135623730951
   ```

   ⇒ Go 三种写法给出同一个值**不是错觉**，是**数学上必然**；Python 侧四种
   同理。逐项值相同 + 公式相同 + 累加顺序相同 ⇒ **和必须相同**。

   **可它不同。**

⇒ 剩下的唯一解释是**点数或点序不同**。而判据报告 `points` 字段相等
（它是第一个「不等就报出来」的字段，报的是 `length` 而不是 `points`）。

**⇒ 「点列相等」与「和不同」两条里必有一条是错的，而它们都出自同一份判据。**

**下一轮的第一步（一个探针就够）**：只挑 `act31side_05` 路线 1 的第 8 段，
把 Go 与 Python 的 `points` **逐元素**打出来（长度、每项、以及两侧的
`length`），不要用整体的 `==`。整体相等而长度不同，只可能是**序列化**
（Go 的 `[2]int` → JSON → `list(map(int, p))` 这条路上丢掉/改了东西）。
剩下的路只有一条：**重写判据（按 `(关卡, 路线号, 斜向)` 显式建键）＋ 重加
`path` 命令并回显 query，一次跑完**。那件事需要一个完整的会话余量，
不适合在推理占满上下文之后再挤。

### ★★ `Route.legs` 已落 ＋ 两个 1 ulp 的根因（2026-09-22，第 29 轮）

**落点**：`rios-sim/stagelegs.go`（`legs` 命令，`main.go` 的 `case "legs"`
＋ `response.Legs`）。判据**并进** `tools/check_stagepath_go.py`
（**不新增 SUITE 行**；`legs` 登记进 `closeout_selfsufficiency.py` 的
`EXTRA_JUDGED`，表示「判了但不单列」）。

**读数**：寻路 2594 / 2594 逐格一致；**路线分段 55 关 1297 条路线 2157 段
逐字段一致**（`kind` / `points` / `length` / `seconds`，其中 `length` 是
**逐位相等**）；另有一套 7 条路线的**合成夹具**（14 段）覆盖缓存里没有的分支。

**根因是「点列必有一错」这条推理的反面：点列一直是对的，错的是浮点语义——
而且有两处、彼此无关。**

探针（正是上一轮点名的那个：`act31side_05` 路线 1 第 8 段，24 点 23 步
**逐元素**打印）结果：两侧点列**逐元素完全相同**，`length` 的差来自求和算法：

| 算法 | 读数 |
|---|---|
| Python `sum(math.dist(...))`（权威 `_polyline_length`） | `24.242640687119284` |
| Python `math.fsum` | `24.242640687119284` |
| Python 朴素左到右累加 | `24.242640687119287` ← **旧 Go 的读数** |

★ **CPython 3.12 起，内建 `sum()` 对浮点走 Neumaier 补偿求和**
（`Objects/bltinmodule.c` 的 `builtin_sum`），给的是**正确舍入**的和；
Go 的 `total += …` 是朴素累加，20 次加法各带一次舍入 ⇒ 高 1 ulp。
⇒ 台账上一版那句「逐项值相同 ＋ 公式相同 ＋ 累加顺序相同 ⇒ 和必须相同」
**默认了累加就是朴素加法**。这条推理本身是错的，而它把两轮导向了「点列」。

**第二个 1 ulp，来源与求和无关**：修完求和之后，`act31side_09` 的 5 条路线
又差 1 ulp（`11.099019513592786` vs `…784`）。根因是每步距离的算法：
`math.dist` 是**平方和开方**，不是缩放式——**台账与代码注释里的
「CPython 缩放式」是记错的**。实测 dx, dy ∈ [0,80) 共 6400 个格点：

```
sqrt(dx² + dy²)                    与 math.dist   0 处不符
max·sqrt((dx/max)² + (dy/max)²)    与 math.dist   2062 处不符（各 1 ulp）
```

单位步下两者逐位相同 —— 这正是它又藏了一轮的原因（那个探针的段全是单位步）。
只有**跨格步**照得出来：端点不可走／不连通时 `ground_path` 退回直线，真夹具里
这样的段有 **62** 个。
（`math.hypot` 另测：6400 个格点上与 `sqrt(平方和)` **0 处不符**，
所以 `eta.py` 的 `polyline_length` 在整数点上不受这一条影响——
但那边的 `sum(hypot(...))` 同样是 **Neumaier 语义**，往上一层时不许换成朴素累加。）

**判据怎么防住它**（这一条是本轮的主要产出）：

* `length` 与 `seconds` 比的是 float **精确相等**，**没有容差**——
  加容差就再也看不见 1 ulp；
* 反向守卫四处**互相独立**、每处都要「注入过 ＋ 判红过」：
  寻路点列 / 分段点列 / **分段长度加 1 ulp** / **分段秒数加 1 ulp**；
* 缓存 55 关里 `DISAPPEAR` **一条都没有** ⇒ `vanish` 分支在真夹具上零行使，
  故判据自带一份最小合成关卡（Go 走自己的索引＋解析入口，Python 走
  `parse_stage`），并要求夹具**自证行使**：`vanish` 段 / `FLY` 路线 /
  接续去重 / 跨格步四项任一为 0 即判红。

---

### ★★ `eta.route_plans` 已落：路线生产侧三层闭合（2026-09-22，第 30 轮）

**落点**：`rios-sim/etaroutes.go`（`routeplans` 命令，`main.go` 的
`case "routeplans"` ＋ `response.RoutePlans`）。判据**并进**
`tools/check_stagepath_go.py`（**不新增 SUITE 行**，与 `legs` 同一处置；
`routeplans` 登记进 `closeout_selfsufficiency.py` 的 `EXTRA_JUDGED`）。

**读数**（`python -X utf8 tools\check_stagepath_go.py`，rc=0）：
寻路 2594 / 2594 逐格一致；路线分段 2157 / 2157 段逐字段一致；
**路线计划表 55 关 1297 条路线 2157 段逐字段一致**（`points` / `wait` /
`length` / `seconds` 四栏全部 float 精确相等）。反向守卫从四处扩到
**八处**互相独立（新增：路线点列 / 路线待命 1 ulp / 路线段数 / 路线段长度 1 ulp），
八处都做到「注入过 ＋ 判红过」。

**这一层是「组装」而不是「再算一遍」**：`route_plans` 调 `Route.legs`，
`Route.legs` 调 `ground_path`——三层同属一条链，所以判据也只有一份。

★ **量出来的三件事**（都不是估的）：

1. **`has_move` 的判据是 `MOVE` 或 `APPEAR_AT_POS`，不是「有没有 checkpoints」**
   （`eta.py:131-133`），而寻路分支的判据是 **`mode == "WALK"` 精确相等**
   （`:134`）。关卡数据里 `motionMode` 缺省解出来是**空串**（`stage.py:837`）——
   写成 `.upper() == "WALK"` 或补默认值就会让那 117 条非 WALK 路线
   **多走一次寻路**。实测分母：1297 条路线 = 有路点 989 ＋ 无路点 308；
   308 里走寻路 238、因 mode 非 WALK 而不走寻路 70。
2. **两个兜底是「结构上不可达」，不是「没测到」**：`ground_path` 的三条出口
   全部非空（同格 `[start]`／端点不可走 `[start,end]`／不连通 `[start,end]`），
   而 `Route.legs` 的 `flush()` 每次至少产出 2 个点 ⇒ `if not pts:` 与
   `wait=0.0 if legs else w` 的 `else` 支**可达性为零**。两条都**照抄**
   （照抄才叫同一个口径）但不进行使计数，改成 `STRUCTURAL_ZERO` ＋
   **每次运行现算守卫**：一旦哪天真出现，判据当场红，红的意思是
   「该补合成夹具了」。★ 顺带发现：`legs` 恒非空意味着
   **`leading_wait` 在 `spawns` 那条路上是死值**——它只在计划表里可观测。
3. **Go 自报的分支行使计数要与尺子独立数出的那一份相等**（`py_route_plan_coverage`
   vs `covered`，13 项逐项比）：计数器本身也是一个断言，它必须有两个来源。
   实测两侧逐项相同（`routes=1297, has_move=989, no_move=308, walk_mode=1180,
   non_walk_mode=117, search_used=238, search_not_used_no_move=70,
   wait_positive=26`，其余 0）。

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
