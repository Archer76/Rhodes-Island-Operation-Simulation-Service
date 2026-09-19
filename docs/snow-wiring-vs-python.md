# snow 接线 vs 权威实现 Python：逐子行为对照表

> 交件人：RIOS后端2（session-37b2c3e2-6993-4a98-a7d2-5f09d62088a2）。
> 依据 PM 2026-09-20 派活（事实比较，非观点）。
> **边界**：①「哪一侧才是对的」**不在这里判**——归博士裁定；②本文件**不含任何引擎改动**（只读诊断）；
> ③19:08 那版 exe 的源码**已不存在**，故本文件**不**主张"它当时有没有接线"。
> 被测对象：`c2ed574` 那一版接线（PM 指定），对照基准：`ak_tactic/battle/` 的 Python 实现。

## 0 · 一句话结论（事实，不含判断）

逐子行为比过：**积层／首敌清雪／减速／满层冻结／踏入伤害五条一致**（差异仅在实现路径，语义等价，见 §2）
；**两条真差异同源**——**「技能2 期间」的两个数**（`spread_cap` 扩散上限、`dot_scale` 每秒伤害倍率）：

* **规格侧根本不送**：`ak_tactic/simgo/spec.py:349-358` 的 `snow_spec` 只送
  `owner/char_id/cell/direction/interval/max_layers/slow_per_layer/magic_scale` **七个键**，**没有**技能期那两个键；
* **Go 侧硬写 0**：`rios-sim/mech/snow.go:331-332` 每帧 `f.spreadCap = 0; f.dotScale = 0.0`
  （文件里自己写明「Go 侧没有送，所以恒为 0 —— 也就是"技能关闭"的形态」）；
* **Python 侧是现读技能黑板**：`ak_tactic/battle/sim.py:1134-1137`
  （`if op.skill_active and sk is not None:` → `spread_cap = int(other.get("talent@max_cast_tile_count") or 0)`、
  `dot_scale = float(other.get("talent@s2_magic_scale") or 0.0)`）。

⇒ **差异成立的前提是"那一局技能2 开着"**。**这一点我没有实测**（见 §4 的可判读数设计），
所以本文件把它写成**条件性差异**，不写成"本关一定有差"。

## 1 · 逐子行为对照表

| # | 子行为 | Python（权威） | Go（`c2ed574`） | 判定 |
| --- | --- | --- | --- | --- |
| 1 | **积层**（计时/施放） | `battle/talents.py:884-894`（`tick`：`timer += dt`；**`while`** `timer >= interval` ⇒ 一帧可多次施放）；调用点 `battle/sim.py:1125-1141`（`ground = [c for c in self._range_of(op) if m.walkable(*c)]`） | `mech/snow.go:342`（`f.tick(dt)`）＋ `:595-598`（`cast`：对 `spec.Ground` 每格 `add`）；`tick` 本体 `:527+`，注释 `:503-526` 逐行抄了原版并注明「`while` 不是 `if`」 | **一致**（Go 的 `spec.Ground`＝原版那串 `ground`，由 Python 侧算好送进来） |
| 2 | **扩散**（射程满层后向外） | `talents.py:896-907`（`_cast`：`spread_cap > 0` **且射程内全满**才扩散，`len(layers) >= spread_cap` 时停）＋ `:909-918`（`_spread_frontier`）＋ `:920-928`（`_add`：新格受上限管、老格照加） | `snow.go:599-618`（`cast`：同两段条件＋`>=` 看**总格数**）＋ `:631-653`（`spreadFrontier`，注释 `:621-630` 说明"不去重"是照抄原版）＋ `:668-678`（`add`，注释 `:665-667` 说明上限只管**新格**） | **条件性差异**：公式一致，但 **Go 的 `spreadCap` 恒 0** ⇒ 原版在技能期**会**扩散、Go **不会** |
| 3 | **减速** | `talents.py:932-937`（`slow_at = max(0.05, 1 - slow_per_layer×n)`）；`battle/sim.py:1153-1160`（`speed_multiplier` 每帧先置 1.0 再乘，`:1141/:1143`）；消费 `battle/unit.py:1540-1542`（连乘） | `snow.go:682-688`（`slowAt`，同式含 `0.05` 底）；`:417-419`（逐片乘进 `mult`）；`:442` `ctx.ScaleEnemySpeed(...)` **无条件上报**（注释 `:429-441` 记了两条坑） | **一致**（Go 的通道语义是"直到改口"，靠无条件上报复现原版"每帧重算"） |
| 4 | **满层冻结** | `battle/sim.py:1164-1166`（`snow_freeze and layers >= max_layers > 0 and not self._is_goal(cell)` ⇒ `e.frozen = True`）；每帧先 `:1149 e.frozen = e.freeze_timer > 0` | `snow.go:420-423`（同三条件，`!s.goals[cell]`）→ `:452-454 ctx.SetEnemyFrozen(idx, true)`；每帧 `:355` 先置 false，主循环锁存 `sim.go:732 frozenLatched = freezeTimer > 0 || frozenSnow` | **一致**（写入路径不同：Go 走 `SetEnemyFrozen`＋主循环锁存，等价） |
| 5 | **踏入伤害** | `talents.py:939-957`（`enter` 六步）→ `battle/sim.py:1169`（`sf.enter(key, cell, atk, cb)`）→ `:1184-1190 _snow_hit`（`resolve_damage(MAGIC, defense, res)`，**不吃物理 5% 保底**） | `snow.go:705-741`（同六步，注释 `:690-704` 逐行列了原版）；伤害 `:740 ctx.HitEnemy(idx, raw, "MAGIC", -1)`；`raw = f.spec.MagicScale × v.ATK`（`:469`） | **一致**（`atk` 两侧都是**每帧现读**：原版 `op.current_atk()` `sim.py:1167`；Go `OpView.ATK`，`mech/mech.go:362-365` 注明"随技能开关变，必须每帧现读"） |
| 6 | **技能2 每秒伤害（DOT）** | `sim.py:1132/1137` 取 `talent@s2_magic_scale` → `:1178-1179` `self._snow_hit(e, sf.dot_scale * atk * dt)` | 通道在：`snow.go:424-427`（`f.dotScale > 0` 才累加）＋ `:497-499`（`ctx.HitEnemy(idx, dotTotal, "MAGIC", -1)`）；但 `:332` 硬写 `dotScale = 0.0` | **条件性差异**：通道写法与原版一致，**输入恒 0** ⇒ Go 恒不施加 |
| 7 | **首敌清雪／离场摘记账** | `talents.py:950-956`（`enter` 内）、`:959-964`（`leave_all`）；离场清雪在 `sim.py:1117-1122`，**位置在积层之前** | `snow.go:301-324`（离场清雪，注释 `:303` 明确"位置照原版"）、`enter :711-732`、`leaveAll :748-767`（注释 `:713-716` 记了"键不存在给 0"的坑） | **一致** |

## 2 · 路径不同但语义等价的三处（同一张表的脚注，免得被读成差异）

1. **"不可行走格整段跳过"**：原版 `sim.py:1150-1152` 用 `m.walkable(cell)` 跳过；Go 没有可行走格表，
   用「这一格有没有雪」等价替代，并把**减速/冻结**（按有雪判）与**踏入结算**（按原版"不可行走才跳"判）**分开**——
   分开这件事写在 `snow.go:394-404`。
2. **`SetEnemyFrozen` 每帧先置 false**（`snow.go:355`）对应原版 `sim.py:1149` 的每帧重算；
   Go 用主循环锁存 `frozenLatched`（`sim.go:732`）保住 `freezeTimer` 那一半，故不会把技能冻结清掉。
3. **施放者阵亡后雪失效**：原版靠 `sim.py:1146` 的 `continue`；Go 靠 `snow.go:385-392` 先滤 `!v.Alive`
   （注释 `:373-384` 记了漏它的后果：HS-EX-8 第 3 手多 1.167 秒）。

## 3 · 差异方向（只写机制方向，不判对错）

两条差异的机制方向**相同**：**Go 侧雪的作用面比原版小**（不扩散 ⇒ 覆盖格数少；无 DOT ⇒ 雪格上敌人少受伤）。
⇒ 相对原版，**Go 里敌人更少被减速、更少吃伤害 ⇒ 推进更快 ⇒ 更容易漏**。
PM 给的观测读数（Go 3 漏／原版 1 漏）与该方向**一致**——但**"一致"不等于"已证因果"**：
该关的最终读数由多条机制共同决定，本文件不主张这两条是全部原因。

## 4 · 可判读数（设计已给；"跑"这一手按分工交验收）

**观测量与取法**（跑同一夹具、同名册、同计划，唯一变量是引擎）：

* **Python 侧**：在 `_snow_tick` 之后读 `sim.snow_fields[0]` 的 `spread_cap` / `dot_scale`，以及 `op.skill_active`。
  * 若 `skill_active == False` 或两值皆为 0 ⇒ **这两条差异在本关不可观测**（漂移另有原因）；
  * 若两值非 0（文档推演：专精三 `talent@max_cast_tile_count 20`、`talent@s2_magic_scale 0.2`，见
    `battle/talents.py:16-17`）⇒ 差异可观测。
* **Go 侧**：`SNOWTICKT` 痕迹里的**格数**（`mech/snow.go:279-281`）与 `SNOWENTRY` 痕迹的**笔数/总额**（`:478-479`）——
  两边逐笔比，而不是拿总数猜。
* **我手上已有的一条事实**（跑现成探针 `tools/probe_snow_inputs.py`，只读、rc=0）：
  HS-EX-8 该局 Go 规格里 `mechanisms = ['huai_shu_li.farmland', 'snow.field']`，
  雪片 1 片、`interval=5.5 max_layers=5 slow=0.12 magic=0.8`、`ground` **8 格**、终点格 `[[12,1]]`；
  探针同时把 8 个部署的 `skill` 都打印成 **`skill=0`**。
  ⚠ **这一条只登记、不作推断**：`skill=0` 是探针对部署对象的读数，**不等于**"技能那一局没开"，
  也不等于"技能期两个数一定是 0"——真值要用 §4 第一条在 Python 侧现读。

## 4b · 同窗痕迹（验收 2026-09-20 提供，把"条件性差异"钉成"本窗内没触发"）

来源：验收 `msg-mu8lehod-54`（A＝19:08 留证副本 `b3e4d6b1`，B＝`c2ed574` 构建；同规格 `spec_sha=464a9dc2…`）；
同窗 W=221.6667s（B 全程，A 只统计 `t<=W`）：

| 键 | A(19:08) | B(`c2ed574`) | 读法 |
| --- | --- | --- | --- |
| `SNOWTICKT` | 6650 | 6651 | Δ=+1 ⇒ **雪节拍两边一样**（⚠ 全程 24422 vs 6651 是时长差，不能用全程数下结论） |
| `SNOWENTRY` | 94 | 96 | 踏入结算笔数几乎相同 ⇒ §1 第 5 行的"踏入伤害一致"在**实测**上也成立 |

⇒ 与 §0 的两条**条件性差异**合起来读：**这两条在本窗内没有产生可观测差**（若扩散/DOT 真的生效，
`SNOWENTRY` 与会造成的伤害笔数/雪格数应当出现量级差）。**本窗内的实质差是另外两处**
（`SNOWSKIP` 1531↔1775、`OPHEAL` 2629↔2494，以及 B 侧独有的 `HITENEMY.frozen/.res/.resbase/.resdown` 两组列）
——按 PM 划的边界，**"差在哪"归验收**，本文件只登记它给出的数。

## 5 · 本文件**不能**证的事（缺口，与结论分开写）

* **不能证**「19:08 那版 exe 有没有 snow 接线」——那份源码是未提交的混合态、**已不存在**（PM 明确要求不得当既成事实）。
* **不能证**「这两条差异就是 `hsex8_max` 读数漂移的原因」——本文件只证"当前接线与原版在这两条上不同"。
* **未实测**「技能2 在那一局是否开启」——见 §4。
* **本地查不到技能期那两个键的权威值**（这是**仪器缺口**，不是"键不存在"）：
  ① 全盘（`<工作区上级>` 递归）**没有任何 `*.sqlite`** ⇒ 干员库/敌人库都没建，`python -m ak_tactic db …` 走不通；
  ② `data/gamedata/raw.githubusercontent.com/excel/` 只缓存了 `char_patch_table.json`、`character_table.json`、
  `range_table.json` —— **`skill_table.json` 不在缓存里**（技能黑板住在那张表）。
  ⇒ 现有缓存**只能核天赋侧四个数**（`character_table.json` 里 `max_cast_cnt` / `talent_magic_scale` 各命中 6 行），
  **核不了** `talent@max_cast_tile_count` / `talent@s2_magic_scale`（在 `character_table.json` 里命中 **0** 行，
  但这**不构成"键不存在"的证据**——它们本就该住在 `skill_table.json`）。
  **要补这一格**：建库（需 `skill_table.json` 源）或在 Python 侧现读 `skill.effects.other`（§4 第一条）。
