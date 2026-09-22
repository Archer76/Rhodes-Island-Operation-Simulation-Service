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

* 前半：**十四套判据现在不报红**；
* 后半：**十四套的反向守卫都成立**（每套人为注入一处不一致，它真会红）。

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

---

## 三 · 未接的部分（具名，不是「没提就是没有」）

| 缺口 | 说明 |
|---|---|
| **两套数值 profile** | **折算本身已全部落地**（`profile.go` 两行 ＋ `panelfold.go` 七处读数，合计 14548 个网格点/叉乘行）：核对下来原版那七个方法**只读实例属性**，替身对象即可当 oracle——原先以为非搭不可的 harness 省掉了。仍缺的是**喂它们的实时输入**（光环、翔虫机动、替身计时、击杀叠层、出手次数、阻挡、高台邻居、偷取攻速这些运行态），以及 `_profile` 自己「临时把开技能字段摆成开启态、读完立刻还原」的那段装配。 |
| **练度 → 面板的接线** | 练度**已经解析出来了**（`rios-sim/loadout.go`，与 `Verifier._entry` 逐字段一致），但它**还没被送去算面板**：`opstats` 目前仍由调用方逐个送练度，没人把 `loadout` 的输出接进去。 |
| **`skill` 的对象形态** | `Plan` 那一条指令的 `skill` 除整数外还可以是对象（丙方案），要 `_skill_from_json` 查技能书、按槽位/等级解成技能 id。本轮**未接**：Go 碰到对象就**具名拒收**，不假装读懂。好消息是 `fixtures/` 下 24 份打法的 `skill` 全是整数，走的是与改动前同一条路。 |
| **规格构造与闸门** | `simgo/spec.py`（76 KB）＋ `simgo/skills.py` 的白名单。Go 现在仍收 Python 送来的 spec。★ **已落地**：19 个顶层键里不依赖 sim／干员／机制的**关卡静态 8 项**（`rios-sim/stageenv.go`，126 例对拍）与**两张格表** `goal_cells`／`highland_cells`（`rios-sim/cells.go`，55 关逐格）。剩下 9 个键：`operators`／`deploys`／`spawns`／`skill_uses`（要 `_operator_spec`／`_unit_spec`，128–162 行起）与 `stage`／`max_time`／`mechanisms`／`mech_config`／`unsupported`。 |
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
