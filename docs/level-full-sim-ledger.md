# 逐关「能不能完整模拟出来」台账

> 博士 2026-09-24 新目标：**从 `main_00-01` 起逐关核查，确保都可以完整模拟出来。**
> 验收线由博士裁定＝ **③ 机制行使计数全 > 0**（不是「键非空」，也不是「有读取点就算」）。

## 一 · 三层读数（缺一不算查过）

| 层 | 问题 | 怎么量 | 判红的形状 |
| --- | --- | --- | --- |
| **A 算得出** | Go 侧对它有判决吗 | `buildspec` 19 键是否造齐；`missing_keys`／`gated_keys`／`unsupported.reasons` | 缺键、或被闸门拒跑（已登记的拒跑要具名列出） |
| **B 跑得动** | 真跑一次是什么结果 | `sim` 的判决四数：`won`／`life`／`kills`／`leaks`／`elapsed` | 跑不起来、或判决四数缺 |
| **C 机制真被行使** | 这一关的机制**运行期有没有走到** | `RIOS_TRACE=1` 跑一遍，按**痕迹标签**计数（`tools/trace_kv.py` 是唯一解析入口） | 该关引用的机制**一条痕迹都没有** |

★ **C 层的判据必须与「该关引用了哪些机制」对齐**——只数痕迹不看清单，会漏掉
「清单里有、痕迹里没有」的那一类（那正是「算了但没生效」的样子）。
机制清单从**四处**来（口径不同，**分栏报，不许相加**）：
① 敌人天赋黑板 ＋ 敌方技能黑板；② 关卡机制层（田地／雪／装置）；
③ 计划里干员的技能、天赋与**特性**；④ **关卡 `options`／`runes` 那一族**
（生命点上限、初始费用、移速倍率、属性增益、功能禁用掩码…——它也是一族机制，
「算得出 ≠ 用上了」在它身上最容易发生）。
★ 第四处是**核查第 0 章时补进来的**：先前只列三处，`main_00-01` 那一关的
`options` 里有 **22 个键**，只数前三处会把它整族漏掉。

★ 第四种结局要**具名**，不许压进「通过」：**该关的机制集合为空** ⇒
「无机制可行使」是一条**读数**（要给出它为什么是空的证据），不是「行使计数 0 也算过」。

## 二 · 命令（原样，可复核）

```powershell
$env:RIOS_DATA="data/gamedata"
$env:RIOS_SIM_BIN="out/acceptance/rios-sim-stage3.exe"

# A：算得出（19 键 ＋ 闸门）
'{"id":1,"cmd":"buildspec","level":"<关卡>","spec":{"plan":"<夹具或空>","roster":"fixtures/roster_max_modelled.json"}}' |
  & $env:RIOS_SIM_BIN

# B：跑得动（把上一步的 build_spec.spec 原样喂回去）
'{"id":2,"cmd":"sim","spec":<上一步的 spec>}' | & $env:RIOS_SIM_BIN

# C：机制行使（痕迹走 stderr；只数「首列是标签」的行）
$env:RIOS_TRACE="1"
'{"id":2,"cmd":"sim","spec":<同一个 spec>}' | & $env:RIOS_SIM_BIN 2>&1 |
  Where-Object { $_ -match '^[A-Z_]+ ' } | ForEach-Object { ($_ -split ' ')[0] } |
  Group-Object | Sort-Object Count -Descending
```

⚠ 三条纪律（都是本仓踩过的）：
① `RIOS_SIM_BIN` **必须显式设**——不设就落共享 exe，量的是别处的二进制；
② 别用 PowerShell 管道的 `$LASTEXITCODE` 读判据的 rc（会被吃掉）；
③ **`0 条痕迹` 先要证明那次跑成功了**（判决四数在不在），否则「没痕迹」与「没跑成」同形。

## 三 · 逐关台账（第 0 章起）
| 关 | A 算得出 | B 跑得动（判决四数） | 引用的机制（三处分栏） | C 痕迹（实际触发的标签） | 结论 |
| --- | --- | --- | --- | --- | --- |
| `main_00-01` | ✓ 19 键齐；`missing_keys=0`／`gated_keys=0`；闸门 `reasons=0`、`spawn=7`、`spawn_skipped=0` | ✓ `won=true`／`life=20`／`kills=11`／`leaks=0`／`elapsed=76.43s`；`spawns_placed=11/11` | ① 敌人黑板键 **0**（本章 8 只敌人一个机制键都没有）② 关卡机制层 **空**（无田地／无雪／无装置）③ 干员侧：**特性「自身生命会不断流失」**（`hp_ratio=0.01`）＋ 技能 `skchr_angel2_1`（计划写 `skill:0`，按博士口径 **0 即默认技能＝技 1**）＋ 两条天赋（`火力电台`／`铳弹协约`） | `OPATK ×1769`／`ATKSCALE ×13`／`DMGENEMY ×13`／`SPEED ×11`／`DEPLOYDMG ×1` | **★ 有缺失**：特性「生命流失」**Go 未模拟**（见下）；两条天赋的触发条件取决于技 1 是不是弹药类，**待核** |

### ★ `main_00-01` 的缺失项：特性「自身生命会不断流失」

**这不是「未核」，是查实的一条缺失。** 决定性证据（全部现算，可复核）：

```powershell
# ① 这个键在 Go 全仓只出现三处：一处是 OperatorStats 的字段声明，两处是注释
git grep -n "hp_drain_per_sec" -- rios-sim/
#   operator.go:111   HPDrainPerSec float64 `json:"hp_drain_per_sec"`   ← 只算出来、只序列化
#   unsupported.go:42 / :311   两条注释（讲的是**敌人侧闸门**那条线，与干员模拟无关）

# ② 模拟器读的那个结构体**没有**这个键
git grep -n "hp_drain\|HPDrain" -- rios-sim/wire.go     # 零命中

# ③ 帧循环里没有任何「按秒扣血」的步（sim.go 里只有机制层的 DrainPollution）
git grep -n "Drain" -- rios-sim/sim.go
```

⇒ **值到不了模拟器，模拟器也没有消费点**——同一形状本仓记过：「没有消费点的字段就是假完成」
（`sim.go` 里 `freezeTimer` 那条注释就是这么写的）。
而 **Python 是有的**：`ak_tactic/battle/sim.py:1975 _trait_tick`，每帧
`op.hp = max(0, op.hp - op.max_hp * op.hp_drain_per_sec * dt)`，位置在技能 tick **之前**。

**为什么本关看得见却看不出来**：76 秒 × 1%/s ≈ 掉掉 76% 生命上限（2150 → ≈516），
**不足以致死**，判决四数因此一模一样 ⇒ **判决面上看不出这条缺失**
（这正是「不能拿判决相等当模拟得对」的现成例子）。

**补法（下一节点）**：把 `hp_drain_per_sec` 接进 Go 的 wire spec（`wire.go::OperatorSpec`
与 `operators.go` 的构造侧各加一处）＋ 在 `sim.go` 帧循环的 `skillTick` **之前**加
`traitDrainTick`；因为 Python 的 `_operator_spec` **不送**这个键（`operator_view.py:179`
把它写死 0.0，真正的值住在 `battle/unit.py`），Go 这一侧会**多一个键** ⇒ 必须按
**「Go 独有键」具名登记**进 `干员规格`（`check_operators_go.py`）与单一入口的键集账，
否则那条「键集相等」的判据会红——**红线是判据在说真话，不是判据坏了**。


## 四 · 第 0 章：机制清单（数据侧现算，不跑引擎）

做法：从关卡文件的 `enemyDbRefs` 取敌人 → 查 `enemy_database.json` 的天赋黑板键与技能
`prefabKey`；从关卡 `options`/`runes` 取选项键；从计划夹具取干员，再查 `akdb` 的
特性正文／天赋／技能。**只列清单，不下「建了没有」的结论**——那是 C 层的事。

| 关 | 敌人引用 | 敌人天赋黑板键 | 敌方技能 | 关卡选项键 | 计划夹具 |
| --- | ---: | ---: | ---: | ---: | --- |
| `main_00-01` | 2 | **0** | **0** | 22 | `plan-main-00-01.json`（1 名：新约能天使） |
| `main_00-02` | 2 | **0** | **0** | 21 | 无 |
| `main_00-03` | 3 | **0** | **0** | 21 | 无 |
| `main_00-04` | 3 | **0** | **0** | 21 | 无 |
| `main_00-05` | 4 | **0** | **0** | 21 | 无 |
| `main_00-06` | 4 | **0** | **0** | 21 | 无 |
| `main_00-07` | 3 | **0** | **0** | 21 | 无 |
| `main_00-08` | 2 | **0** | **0** | 21 | 无 |
| `main_00-09` | 3 | **0** | **0** | 21 | 无 |
| `main_00-10` | — | — | — | — | 无 |
| `main_00-11` | 6 | **0** | **0** | 22 | 无 |

★ 本章的机制面**很薄**：11 关的敌人**一个天赋黑板键、一个敌方技能都没有**；
关卡机制层（田地／雪／装置）实测为空；`options` 那一族逐关 21–22 个键，
但**值都是骨架**（`maxLifePoint` 10–20、`initialCost`、`maxCost` 99、`costIncreaseTime` 1、
`moveMultiplier` 0.5、`characterLimit` 8、`functionDisableMask: NONE`、`configBlackBoard: null`）
——`gbuff_lifepoint` / `ebuff_attribute` 那一类**第 0 章一个都没有**（它们从第 5～6 章
才出现），所以本章真正的机制对象几乎全在**干员侧**。

★ 一条**已见证**的读数：`main_00-01` 的判决 `life=20` **＝** 该关 `maxLifePoint: 20`
⇒ 「生命点上限」这一条真的被用上了（不是「算得出」，是「用上了」）。
