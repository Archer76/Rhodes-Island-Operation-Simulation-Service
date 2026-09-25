# 撤退机制（`e8a50a2`）独立复核

> 复核对象：提交 `e8a50a2bf3a3275deea078711745de3d09368ea9`「撤退机制 ＋ 安德切尔口径更正」
> 复核范围：**只审撤退**（`Spec.Retreats`／`RetreatSpec`／`specKeysGoOnly`／撤掉的那条拒绝理由／
> `sim.go` 帧序 1c／`operator.retreat()`／`findOpByName`／`enemy.paidCost`／`RetreatRefund`）。
> 上一份 `docs/three-star-audit.md` 里点名的 8 处不符**本轮不动**。
> 本次**只读**：未改 `rios-sim/**`、`ak_tactic/**`、`fixtures/**`、`data/**`，**未重建任何二进制**。
> 仓库内只新增本文件；**合成计划**按约定只落在 `out/audit-synth/` 下，文件名与 `title` 都带 `SYNTHETIC` 字样。

---

## 一 · 仪器身份与冻结点

| 项 | 读数 |
| --- | --- |
| `RIOS_SIM_BIN` | `out/acceptance/rios-sim-stage3.exe` |
| exe sha256 前 16 位 | **`603E656BE5C42E10`** |
| exe mtime | 2026-09-25 22:05:11（**比提交时间 22:11 早 6 分钟**） |
| exe 内嵌 VCS 戳 | `vcs.revision=8846393cc3eac73b69c304077f3094eac1ec7b37`／**`vcs.modified=true`**／`vcs.time=2026-09-25T12:54:01Z` |
| `source_sig(disk)`（74 个 `.go`，`rios-sim/**`） | **`680d793c`** |
| `source_sig(head)`（同折行规则，从 blob 算） | **`680d793c`** |
| `git status --porcelain -- rios-sim` | **空**（工作区 = HEAD = `e8a50a2`） |

★ **仪器的两句话**：

1. 这枚 exe 的 `vcs.revision` 是 `8846393`（`e8a50a2` 的**父提交**），`modified=true`
   ⇒ 它是**提交前那一刻的脏树**构建的（22:05 建、22:11 提交）。这与「提交内容 = 当时工作区内容」相容，
   但**没有可验证的等式**——`source_sig=680d793c` 量的是**此刻**的磁盘（=HEAD），不是这枚 exe 的构建源码。
2. **可用性证据**（说明它确实是这一版）：在 exe 字节里现读的符号计数——
   `RETREAT`×1、`retreats`×3、`specKeysGoOnly`×1、`paidCost`×1、`findOpByName`×1、
   `retreat_refund`×3、`RetreatSpec`×4。⇒ 本轮的运行期读数**确实**跑在含撤退实现的那一版上。

**运行期命令**（每一步都显式设了两个环境变量）：

```
$env:RIOS_DATA="data/gamedata"
$env:RIOS_SIM_BIN="out/acceptance/rios-sim-stage3.exe"
```

**合成计划清单**（全部在 `out/audit-synth/`，`title` 里写明「不是策展夹具」）：

| 文件 | 用途 |
| --- | --- |
| `SYNTHETIC-retreat-lingyu.json` | 主用例：翎羽 @[4,3] 部署@0、撤退@5 |
| `SYNTHETIC-no-retreat-lingyu.json` | 对照：同一份、**去掉 `retreats`** |
| `SYNTHETIC-retreat-melan.json` | 对照：玫兰莎（**不带**退费特性） |
| `SYNTHETIC-case-{A,B,C,D,E}.json` | 五个边界用例（下表） |
| `SYNTHETIC-redeploy-twice.json`／`SYNTHETIC-two-ops.json` | 二次部署与两人各撤一次 |

---

## 二 · Q1：撤掉拒绝理由之后，会不会走到「静默不撤退」？

**结论：端到端通了；但**有**三条静默路，其中两条**连一笔账都不记**。**

### 2.1 通了的那一半（对得上）

链路逐段现读：

| 段 | 位置 | 现读 |
| --- | --- | --- |
| 计划解析 | `plan.go:337-353` | `retreats: [{operator, time}]` → `RetreatOrder{Operator, Time}` |
| 闸门**不再**拒 | `unsupported.go:163-167` | 原 `Covered["retreat"]++` 与 `Reasons` 那句**已删**；`Scanned["retreat"]` **留着**（实测 `unsupported.retreat = 1`） |
| 规格搬运 | `buildspec.go:482-486` | `plan.Retreats` → `Spec.Retreats`（照搬，不解释） |
| 执行 | `sim.go:768-806` | 帧序 **1c**：按时刻队列出队 → `findOpByName` → `op.retreat()` → 退费 → `Event{kind:"retreat"}` ＋ `RETREAT` 痕迹 |

**实测**（`SYNTHETIC-retreat-lingyu`，路径形态走闸门）：

```
unsupported          = []                                  ← 不再拒跑
spec.retreats        = [{"time": 5, "operator": "翎羽"}]
scanned              = {"retreats": 1, "unsupported.retreat": 1, "operators.retreat_refund_true": 1}
RETREAT 痕迹         = 1   （对照局 = 0）
RETREAT t=5.0333 op=翎羽 refund=8 cost=15.0
verdict.events       = [..., {"t":5.0333, "kind":"retreat", "who":"翎羽"}]
```

⇒ **模拟器那条路真的执行撤退**，不是「静默不撤退」。这一半**对得上**。

### 2.2 三条静默路（**对不上**，具名）

`sim.go:781-792` 的两个分支：

```go
op := findOpByName(objs, r.Operator)
if op == nil {                       // ① 找不到人
    verdict.DeployRejected = append(..., "撤退请求找不到人")   // ← 记了一笔
    continue
}
if !op.alive() {                     // ② 静默：什么都不记
    continue
}
```

| 用例 | 实测 | 记账 | 判定 |
| --- | --- | --- | --- |
| A 部署@0、撤退@5 | `RETREAT=1`，事件 1 条 | 有 | 对得上 |
| B 同帧内连撤两次（@5、@5.1） | `RETREAT=1`，事件 1 条 | 有（第二条不发生，正确） | 对得上 |
| **C 撤退@0.1 / 部署@3（撤在部署之前）** | **`RETREAT=0`**，事件 0 条，`deploy_rejected=[]` | **无** | **对不上** |
| D 撤一个不在计划里的名字 | buildspec **具名拒**「撤退了没部署过的干员：不存在的人」 | 有（计划层） | 对得上 |
| **E 撤退@99999（跑不到那一刻）** | **`RETREAT=0`**，事件 0 条 | **无** | **对不上** |

**根因（C）**：`!op.alive()` 这一个判据把**三种状态压成了一种**——
`op.hp > 0 && !op.retreated`（`sim.go:450`）。而**未部署**的干员在构造时 `hp` 就是零值
（`sim.go:566` 只给了 `spec`／`leftAt: -1`／`cell`，**没给 hp**）
⇒ 未部署的人与阵亡的人、已撤退的人在这条 `if` 面前**长得一模一样**。
代码注释只点名了后两种（`sim.go:790`「已倒下/已撤退的人再撤一次」），**漏说了「还没部署」**。

**根因（E）**：跑不到那一刻的请求在循环退出时随 `retreats` 一起被丢弃（`sim.go:777` 只按 `Time <= t` 出队），
**收尾没有任何「未消化请求」的账**。

**补法（两条，各一行）**：
* C：把 `!op.alive()` 拆开——`if op.retreated || op.hp <= 0 && op.leftAt >= 0 { … }` 之外，
  「未曾部署」（`op.leftAt < 0 && op.hp <= 0`）应当**记一笔** `DeployRejected`（与 `op == nil` 同姿势），
  而不是静默 `continue`；
* E：帧循环结束后，把 `len(retreats)` 与最后一条的时刻一起写进 `verdict`（或打一行 `RETREATLEFT`），
  让「排了没用上」与「根本没排」分得开。

### 2.3 顺带：新做的撤退**没能打开它自己文案承诺的那条路**

`plan.py:271-276`（Go 是它的移植）在拒二次部署时的原话是：
「同一个干员被部署了两次：翎羽（第 1 条与第 2 条）。**要再上一次得先撤退**，本版不支持同一人的二次部署」。

实测：同一干员部署两次的计划 **buildspec 仍然拒**（`SYNTHETIC-redeploy-twice` →
`ok=False`，「同一个干员被部署了两次：翎羽」）。
⇒ 现在撤退**已经做了**，这句话就变成**误导**：读者会以为「撤了再下」可行，而校验层依旧不许
（`operators.go:1054-1062` 按 `char_id` 去重并报错）。**要么改文案，要么让二次部署真的可行**——
这是本次改动新造出来的口径落差，不是旧账。

---

## 三 · Q2：`specKeysGoOnly` 与 `specKeysAll` 真是两张表吗？往 `specKeysAll` 加行会怎样？

**结论：两张表确实是分开的（对得上）；但新键把 buildspec 那一路的跨实现键集判据**打红了**（对不上）。**

### 3.1 两张表确实是分开的（对得上）

`rios-sim/specgo.go` 现读（原文）：

```go
var specKeysAll = []string{
    "stage","fps","max_time","life","cost_init","cost_max","cost_time",
    "enemy_windup","ranged_enemies","speed_scale","highland_cells",
    "goal_cells","operators","deploys","spawns","skill_uses",
    "unsupported","mechanisms","mech_config",
}                                   // ← 19 条，一条没动

var specKeysGoOnly = []string{"retreats"}   // ← 新表，Go 单方面扩协议
```

`buildspec.go:601-616` 的 `fullSpecMissingKeys` 把两张表**并进** `known` 再做「多键」反向守卫——
所以 **Go 自己的反键守卫是满足的**（`retreats` 不再被自己判成非法多键）。这一半**对得上**。

### 3.2 往 `specKeysAll` 里加一行会怎样：**specgo 那一路会红（守卫生效）**

`tools/check_specgo_go.py:419-434` 的键集账（逐字）：

```python
produced = {k for k in got if k not in ("missing_keys", "gated_keys", "difficulty")}
missing  = set(got["missing_keys"])
if produced & missing: …        # 不相交
if produced | missing != set(all_keys): …   # == 源文件里的键集
```

而 `all_keys` 来自 `build_spec_keys()`（`check_specgo_go.py:137-148`）：
**用 `ast` 从 `ak_tactic/simgo/spec.py::build_spec` 的返回字面量里抽**——权威是**冻结的 Python**。

我按这段代码逐字复算了一次（同一套 ast 抽法，同一枚 exe）：

```
Python 权威（ast 抽出 19 个键）
Go buildspec 的 spec 键（20 个）
```

* `specgo` 命令那一侧：`produced(12) ∪ missing(7) == Python 的 19 键` ⇒ **真**
  （`SpecPart` 里**没有** `retreats`，所以这一路没被新键碰到）。
  ⇒ 若有人把 `retreats` 加进 `specKeysAll`，它会落进 `missing` 或 `produced`，两处都会让并集**多出 `retreats`** ⇒ **红**。
  **这条守卫成立**，两张表的分法在这一侧是有效的。
* ⚠ 我第一遍复算时把剔除名单写成了四项（漏 `difficulty`），得出「多 `difficulty`」的假红；
  按 `:420` 的**逐字**名单重算后归零。**记在这里，因为「查询跑成功了没有」要能被下一个人复用。**

### 3.3 但 **buildspec 那一路现在必然报「键集不同」**（**对不上**）

`tools/check_buildspec_go.py:566` 的断言是**顶层键集相等**：

```python
if sorted(py) != sorted(go):
    bad.append("%s：键集不同\n      期望 %s\n      Go   %s" …)
```

我按**它的**两侧复算（Go 侧取 `buildspec` 的 `build_spec.spec`，Python 侧取同一套 ast 抽法）：

| | 读数 |
| --- | --- |
| Python 权威 | 19 键（`…spawns, speed_scale, stage, unsupported`） |
| Go buildspec 的 `spec` | **20 键**，多出 **`retreats`** |
| `sorted(py) != sorted(go)` | **真**（多 `['retreats']`，少 `[]`） |

⇒ **`check_buildspec_go.py` 的第一道判据现在为假**。它**不认识** `specKeysGoOnly`
（全仓 grep：该标识只出现在 `rios-sim/specgo.go`、`rios-sim/buildspec.go` 两处 Go 文件里，
`tools/` 下零命中）。本次提交只动了 `tools/check_operators_go.py` 与 `tools/three_star_check.py`，
**没有动 `check_buildspec_go.py`**。

**「两张表分开」这条设计保护的是 specgo 那一路（3.2），没有保护 buildspec 这一路**——
而 buildspec 恰恰是 `build_spec` 这个契约的真正出口。

**补法**：在 `check_buildspec_go.py` 里给这一路加一条与 Go 同源的 Go-only 表
（不能把 `retreats` 塞进 Python 的期望集，那就等于把契约改了），
并把「Go-only 键必须在对拍台具名登记」做成守卫（否则下次加键再红一次）。

★ **未核**：我**没有**跑完 `check_buildspec_go.py`（后台起了 `python tools\check_buildspec_go.py`，
25 分钟只输出到第 2 行就还在跑；按约束**没有 kill 任何 python 进程**）。
上面给的是**把它的断言原样复算**的结果，不是它自己打出来的红。

---

## 四 · Q3：副作用边界（`blockedBy`／阻挡／`leftAt`／`alive()`）

**结论：Go 的两行 `retreat()` 相对参照实现**少做一件事**（清 `op.hp`），
但两处「靠别人兜」的写法都**当帧兜住了**（对得上）；另有两处**真实的边界问题**（对不上）。**

`sim.go:3242-3244`：

```go
func (o *operator) retreat() {
    o.retreated = true
    o.blocking = nil
}
```

参照实现 `ak_tactic/battle/sim.py:2624-2635`（**这是本仓里真正的撤退实现**）：

```python
op.hp = 0.0
op.retreated = True
for e in list(op.blocking):
    e.blocked_by = None
op.blocking.clear()
```

### 4.1 逐项对账

| 项 | Python 参照 | Go | 判定 |
| --- | --- | --- | --- |
| `retreated` | 置真 | 置真 | 对得上 |
| `op.blocking` | `clear()` | `= nil` | 对得上 |
| **对侧 `e.blockedBy`** | **当场逐只清** | **不清**，靠同帧稍后的 `updateBlocking` 第三段 | 对得上（**但依赖两件事**，见 4.2） |
| **`op.hp = 0`** | **清零** | **不清** | **对不上**（见 4.3） |
| `leftAt` | 帧内**统一**记（`sim.py:2660-2667`） | 帧内**统一**记（`sim.go:1133-1138`） | 对得上，**位置也同族** |
| 召唤物随主人退场 | `sim.py:2642-2656` 有 | **Go 无这一步** | 见 4.4 |

**同帧性核对（`blockedBy` 靠兜这一点站得住）**：
撤退步在**帧序 1c**（`sim.go:768`），`updateBlocking` 在 **`sim.go:1063`**，
「离场时刻」在 **`sim.go:1134`** ⇒ 三者**同一帧**、顺序递增。
`updateBlocking` 第三段（`sim.go:2012-2016`）：

```go
for _, e := range enemies {
    if b := e.blockedBy; b != nil && !b.alive() { e.blockedBy = nil }
}
```

它判的是 `alive()`，而 `alive() = hp > 0 && !retreated`（`sim.go:450`）⇒ 撤退的人当帧就被解开 ✓。

★ **但这依赖两个前提**，任一条破了就变成「撤退了还挡着」：
① `updateBlocking` **每帧无条件**被调用；② 在它跑之前**没有别的消费者**读 `e.blockedBy` 当靶子。
第②条我查了唯一的那个消费者：`enemyTarget`（`sim.go:3019-3022`）第一句就是
`if e.blockedBy != nil && e.blockedBy.alive()` ⇒ 退了的人不会被当靶子 ✓。
（其余 `ops` 循环的守卫抽查见 4.5。）

### 4.2 **`leftAt` 是一个零消费者的字段**（**对不上**）

```
sim.go:381   leftAt  float64                     声明
sim.go:566   objs[i] = &operator{…, leftAt: -1}  初始化
sim.go:641   op.leftAt = -1                      再部署时复位
sim.go:1134  if op.leftAt < 0 && (op.retreated || op.hp <= 0) { op.leftAt = t … }   写
```

**全仓没有一处把它当「再部署冷却的起点」来读**——除了 `1134` 那个 `leftAt < 0` 的**自锁**。
真正的冷却读的是**另一个量**：`lastLeft[op.spec.CharID]`（`sim.go:550` 声明、`1136` 写、`612` 读）：

```go
if last, ok := lastLeft[d.CharID]; ok && t < last+op.spec.RedeployTime { … "再部署冷却中" }
```

而 `sim.go:3236-3237` 的注释与 `1132` 的注释**都写着**「`leftAt`（再部署冷却的起点）……再部署冷却靠它」。
⇒ 这是本仓记过的那种形状：**同一件事两个量**，其中一个**只写不读**，注释指着错的那一个。

**进一步**：因为计划层**禁止同一 `char_id` 出现两次**（`operators.go:1054-1062`，实测 `SYNTHETIC-redeploy-twice` 被拒），
`lastLeft`／`RedeployTime` 这条冷却在 Go 里**结构上不可达**；`op.retreated = false`＋`op.leftAt = -1`
（`sim.go:640-641`）也因此是**死代码**。Python 侧同一条限制（`plan.py:269-276` 同一句文案）
⇒ 这不是本次改动引入的，但它让「撤退」这个动作**少了一个本该存在的下游后果**（冷却根本不生效）。

**补法**：要么删掉 `leftAt`（留 `lastLeft` 一个量），要么把冷却改成读 `leftAt` 并把 `lastLeft` 收掉——
**不许两个都留**。顺带把 `sim.go:1132`／`3236` 的注释指到真读的那个量。

### 4.3 **`op.hp` 不清零**（**对不上**，但是「窄口径的对不上」）

Go 撤退后 `hp` 保持不变（> 0）。我逐个查了两个最可能被咬到的消费者：

* `pickHeals`（`sim.go:2543`）：`if !o.alive() || o.hp >= o.spec.MaxHP { continue }` ⇒ 用 `alive()`，**排除** ✓
* `enemyTarget`（`sim.go:3020,3029`）：两处都用 `alive()` ⇒ **排除** ✓
* `updateBlocking`（`sim.go:2000`）：`if !op.alive() || !op.canBlock(e)` ⇒ **排除** ✓
* `traitDrainTick`（`sim.go:2047`）、`skillTick`（`skill.go:51`）、`blessingTick`（`sim.go:3595`）、
  `teamAuraTick` 的**目标**侧（`sim.go:2845`）：都用 `alive()` ✓

⇒ **在能想到的消费者上，`hp>0` 与 `hp=0` 的效果相同**，所以这不是判决级的偏差。
但它是**与参照实现的实质差异**，且「靠所有消费者都记得判 `alive()`」是一条**隐式约定**：
**补法**：照参照实现补一句 `o.hp = 0`，把这条差异消掉（成本一行），或把它**具名登记**成有意偏离。

### 4.4 **召唤物随主人撤退消失：Go 没有这一步**（**未核 → 附补法**）

参照实现 `sim.py:2642-2656` 在撤退之后有一整段「召唤者退场 ⇒ 召唤物一并消失」。
Go 的撤退步（`sim.go:768-806`）**只有**「标记＋清阻挡＋退费」，没有这一段。
我**没有**找到 Go 里对应的等价路径（也没找到它明确写着「召唤物不随撤退消失」）；
这是**两条路里的一条**：死亡那条有没有做，我**没核**（见 §七 未核 1）。
**补法**：`grep -n "summonOf\|SummonOf\|召唤" rios-sim/*.go`，先确认 Go 有没有召唤物这条通道；
有则把「主人退场」的判据从 `hp<=0` 扩到 `retreated`，没有则在文档里具名登记「召唤物未移植，撤退无此后果」。

### 4.5 `ops` 循环的 `alive()` 守卫抽查

`ops` 是**只增不删**的出场名单（`sim.go:721` `ops = append(ops, op)`），撤退**不把人从名单里摘掉**
⇒ 每个逐 `ops` 的循环都必须自己判 `alive()`。抽查了 9 处（`1661,1707,2072,2744,2843,3028,3376,3411,3593`）：

| 处 | 守卫 | 判定 |
| --- | --- | --- |
| `1661`／`1707`／`2072`／`3028`／`3593` | `if !op.alive() { continue }`／`op.blessingFreeze <= 0 \|\| !op.alive()` | 对得上 |
| `3376`／`3411` | `if op.alive() { … }`（只把活着的记进 allies） | 对得上 |
| `2843` | `give := owner.alive()` ＋ 目标侧 `!op.alive()` | 对得上 |
| **`2744 teamAuraTick`** | 外层循环 `for _, op := range ops`，**内层 `for _, owner := range ops` 无 `alive()` 判定** | **对不上（见下）** |

`teamAuraTick`（`sim.go:2744-2771`）内层对**每一位** `owner` 求 `TeamAura.current(owner, op)`：

```go
for _, op := range ops {
    atk, def := 0.0, 0.0
    from := make([]string, 0, len(ops))
    for _, owner := range ops {                 // ← 没有 owner.alive()
        for i := range owner.spec.TeamAuras { … atk += x; def += y … }
    }
    op.auraAtkPct = atk
    op.auraDefPct = def
```

⇒ **撤退的人会继续给全队发光环**，而且**与同族另一条路不一致**：
`sim.go:2843` 那条（治疗/回复类）明确写了 `give := owner.alive()`。
参照实现 `sim.py:3520-3527` 的 `_update_team_auras` 也是「对每位 owner 求 current」——
**两边都没过滤 `alive`**，所以「发不发」这件事**没有参照可判**（Python 也没写），
但**Go 内部两条光环路径的守卫不一致**是确凿的，且与本次「撤退」直接相关（撤退第一次让 `owner` 处于「在场但 `!alive()`」的状态）。

**补法**：先裁定「光环主人撤退后还发不发」（参照实现给不出答案，需要一句口径），再统一两条路；
在裁定前，至少把这个不一致**具名登记**（`AURA-TEAM` 痕迹里 `from=` 已经能指名主人，读数上可分辨）。

---

## 五 · Q4：「退的是**实际付出的**费用」成立吗？

**结论：成立——但成立**靠的是部署闸门，而不是 `paidCost` 这个名字**；而且这条**没有任何参照实现可对**。**

### 5.1 写入点与读取点读的是同一个量（对得上）

```go
sim.go:619   if float64(d.Cost) > cost { verdict.CostDenied = …; continue }   // ③ 付得起吗
sim.go:746   cost = math.Max(0, cost-float64(d.Cost))                        // 扣
sim.go:747   op.paidCost = d.Cost                                            // 记
…
sim.go:793   refund := 0
sim.go:794   if op.spec.RetreatRefund { refund = op.paidCost }
sim.go:799   if refund > 0 { cost += float64(refund) }
```

* **同一个量**：`paidCost` 记的就是第 746 行扣的那个 `d.Cost`，不是面板上的 `DeployCost` ✓；
* **「实付」成立的关键**在第 619 行：付不起时**根本不部署**（走 `CostDenied`），
  所以第 746 行的 `math.Max(0, …)` **永不夹断**，扣多少 == `d.Cost` == `paidCost`。
  ⇒ 这一行的 `math.Max(0,…)` 是**防御性的死代码**；它的存在本身说明「实付」不是自明的，
  而是**被上游闸门保证的**。若哪天有人把部署闸门放宽（比如按剩余费扣一部分），
  `paidCost` 会**静默变成「应付」**——而注释仍写着「实际付出的」。

### 5.2 控制实验（**只翻一个布尔**）

同一份规格、同一站位、同一出站，只翻 `operators[0].retreat_refund`：

| | `RETREAT` 行 | 差值 |
| --- | --- | --- |
| `retreat_refund = true`（原样） | `RETREAT t=5.0333 op=翎羽 refund=8 cost=15.0` | — |
| `retreat_refund = false`（控制组） | `RETREAT t=5.0333 op=翎羽 refund=0 cost=7.0` | **恰好 8** ＝ 翎羽的 `deploy_cost` |

⇒ 退费额**精确等于**实付部署费用，且**只在这一条特性为真时**发生 ✓。
另取三个不同部署/撤退时刻（@0→@5、@0→@20、@30→@40），`refund` **恒为 8**、`cost_denied=[]`、`rejected=[]` ✓。

### 5.3 两处**对不上**（具名）

1. **没有任何参照实现可对**：Python 侧的撤退（`battle/sim.py:2624-2635`）**不退款**；
   `ak_tactic` 全仓搜 `paid_cost|refund` 只有 `_refund_on_deploy`（那是**技能**的部署返还，另一回事）。
   ⇒ 这条规则是**Go 独有**，跨源对拍**结构上对不了**，只能靠上面那种自证。
   建议在 `wire.go`／`operator.go` 的注释里把它写明为「无参照、Go 先走一步」（与 `specKeysGoOnly` 同姿势），
   否则下一个人会去找一个不存在的期望值。

2. **退费是唯一一条绕过 `cost_max` 的回费路**（**对不上，已实测**）：
   * 自然回费：`sim.go:593` `cost = math.Min(spec.CostMax, cost+1.0)` —— **夹上限**
   * 技能回费：`skill.go:182` `*cost = math.Min(spec.CostMax, *cost+sk.CostGain)` —— **夹上限**
   * **撤退退费：`sim.go:799` `cost += float64(refund)` —— 不夹**

   `main_00-01` 的 `cost_max = 99`（`stageenv` 现读），自然回费封在 99。同一份规格只改撤退时刻：

   | 撤退时刻 | `RETREAT` 行 | 是否越上限 |
   | --- | --- | --- |
   | 75.0 | `RETREAT t=75.0333 op=翎羽 refund=8 cost=94.0` | 否 |
   | 80.0 | `RETREAT t=80.0333 op=翎羽 refund=8 cost=99.0` | 刚好到顶 |
   | **84.0** | **`RETREAT t=84.0333 op=翎羽 refund=8 cost=103.0`** | **是（103 > 99）** |

   ⇒ **退费真的会把费用顶到 `cost_max` 以上**，而且这是**唯一**一条能越过上限的回费路。
   参照实现也不退款 ⇒ 没有权威可判「该不该夹」。
   **补法**：要么 `cost = math.Min(spec.CostMax, cost+float64(refund))`，
   要么具名登记「退费不受上限约束」并给出依据（这句裁定权不在实现者手里）。

### 5.4 顺带：判词与实物的对读（**对不上**）

* Go 判词：`operator_traits.go:504` `retreatRefundTrait = "撤退时返还初始部署费用"`；
* 冻结参照里的规则：`ak_tactic/formula.py:758` `_r("trait_refund", r"撤退时返还(?:大量)?该次部署费用", …)`。

**实物现算**（`akdb.operator.trait_text`，全表搜「撤退时返还」）：

| 读数 | 值 |
| --- | --- |
| 含「撤退时返还」的条数 | **7**（`char_192_falco`／`290_vigna`／`261_sddrag`／`496_wildmn`／`1036_fang2`／`222_bpipe`／`220_grani`） |
| 原文（7 条逐字相同） | 「击杀敌人后获得1点部署费用，**撤退时返还初始部署费用**」 |
| Go 判词命中 | **7 / 7** ✓ |
| `formula.py::trait_refund` 正则命中 | **0 / 7**（它要的是「该次」） |

⇒ 我按「同一机制换了键名实现」这条盲区专门找了一次：**不是换键名**——
Go 侧 7/7 命中且与实物逐字一致；**冻结侧那条规则与实物不符，恒不命中**（`trait_refund` 在这 7 位上是死规则）。
注：句义上「该次部署费用」＝实付（与 Go 退 `paidCost` 的**语义**一致），
而 Go 的**判词**取「初始」——**判词与语义各取一边**，两边都没错到会改判决，但口径要写清。

---

## 六 · Q5：自造带 `retreats` 的计划跑一次

**合成计划**（`out/audit-synth/SYNTHETIC-retreat-lingyu.json`，`title` 已标 `SYNTHETIC-AUDIT`，
**不是策展夹具**）：

```json
{"title":"SYNTHETIC-AUDIT retreat probe — 不是策展夹具，只给 tools 用",
 "stage":"main_00-01",
 "deploys":[{"operator":"翎羽","position":[4,3],"direction":"Left","skill":0,
             "elite":1,"level":55,"potential":6,"module_level":0,"time":0.0}],
 "retreats":[{"operator":"翎羽","time":5.0}]}
```

对照组＝**同一份、只去掉 `retreats`**（`SYNTHETIC-no-retreat-lingyu.json`）。

**要交代的第一件事：原用例的撤退时刻挑得不好。** 该关**第一个出怪时刻恰好也是 5.0**
（`spec.spawns` 现算），而帧序里 **1c 撤退排在 2 出怪之前**（`sim.go:768` < `sim.go:808`）
⇒ 「撤@5」那一局她**在第一个敌人出场之前就离场了**，`kills=0`／`damage_dealt=0` 是**必然**的，不是她打不动。
所以我又补了**打到一半再撤**的两组（各用例只改一个撤退时刻）：

| 用例 | `RETREAT` 行 | `won` | `elapsed` | `kills` | `leaks` | `life` | `damage_dealt` | `deployed` |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **不带撤退（对照）** | — | true | 85.66666666666437 | **9** | **2** | **18** | **6205** | 1 |
| 撤@50 | `RETREAT t=50.0333 … refund=8 cost=65.0` | true | 85.66666666666437 | 5 | 6 | 14 | 3235 | 1 |
| 撤@30 | `RETREAT t=30.0000 … refund=8 cost=42.0` | true | 85.66666666666437 | 2 | 9 | 11 | 1585 | 1 |
| 撤@5（原用例） | `RETREAT t=5.0333 … refund=8 cost=15.0` | true | 85.66666666666437 | 0 | 11 | 9 | 0 | 1 |

**撤退真的发生了吗**：是，四组里带撤退的三组都各有 **1 条** `RETREAT` 痕迹，
且 `verdict.events` 里有 `{"kind":"retreat","who":"翎羽"}`（原用例：`t=5.033333333333325`）。

**退费了多少**：**恒为 8**（＝翎羽 `deploy_cost`），与撤退时刻无关；`cost` 从「自然回费到的那个数」+8。

**四数差在哪（逐条说，别只报数）**：

* **用时逐位相同（85.66666666666437）**不是没生效：这一局的收场判据是「出怪放完且场上没有可清的敌人」
  （`sim.go:1143-1145`），**撤走 1 名干员不改变**这条条件 ⇒ 四组同时收场。
  ⚠ 记住这个形状：**这里的「用时不变」是必然的，它不能当「撤退生效了」的证据**
  ——证据是 `RETREAT` 痕迹与那三条计数。
* **四个量随撤退时刻单调**：撤得越早 → 杀越少、漏越多、剩命越低、伤害越低（9→5→2→0／2→6→9→11／
  18→14→11→9／6205→3235→1585→0）。**单调且自洽**，这是「撤退真的在起作用」的正向证据。
* **剩命与漏怪的关系**（**这一条我第一遍算错了，在这里更正**）：
  `stageenv(main_00-01)` 现读 `"life": 20`；每漏一只扣 1（`LifeCost`）。
  于是 **20 − leaks = life** 在四组里都精确成立：20−2=18、20−6=14、20−9=11、20−11=9 ✓。
  我先前写的「18 − 11 = 7，与 `life=9` 对不上」是**把不带撤退那一行的 `life` 与撤退局那一行的 `leaks` 混着减**——
  跨行相减，是我的算术错，不是实现的账。**据此撤回「未核 2」**。
* `won=true` 与 `leaks=11` 并存：这一关的胜负判据不是「零漏」（`sim.go:1143` 只看出怪放完＋场上无敌人），
  三条 `life` 扣光才判负（`sim.go:1139-1142`）。⇒ 不是异常。

---

## 七 · 三态汇总

| 态 | 条数 | 具名 |
| --- | ---: | --- |
| **对得上** | **12** | ① 端到端执行（闸门不拒 → 规格搬运 → 帧序 1c → `RETREAT` 痕迹 ＋ `retreat` 事件）；② 连撤两次只发生一次；③ 计划层具名拒「撤没部署过的人」（`plan.py:284-287` 逐字同文）；④ `specKeysAll`(19) 与 `specKeysGoOnly`(`["retreats"]`) 确是两张表；⑤ `specgo` 那一路的键集并集断言**现算成立**（12 ∪ 7 == 19）；⑥ `blockedBy` 当帧被 `updateBlocking` 第三段解开（帧序 1c < 1063，判 `alive()`）；⑦ `enemyTarget` 两处都用 `alive()`，退了的人不会被当靶子；⑧ `leftAt` 的**写入**位置与参照实现同族（帧内统一记）；⑨ 退费额＝实付（控制组恰好差 8）；⑩ `retreat_refund` 的「有这条／没有这条」分得开（True vs 缺失）；⑪ 8 处 `ops` 循环带 `alive()` 守卫；⑫ Go 判词 `撤退时返还初始部署费用` 与实物 7/7 逐字一致 |
| **对不上（具名）** | **6** | **F1** 撤在部署之前 ⇒ **静默不撤退**（`RETREAT=0`、`deploy_rejected=[]`），根因是 `!op.alive()` 把「还没部署」与「已死/已撤」压成一个判据；**F2** 跑不到的撤退请求 ⇒ **静默丢弃**，收尾无「未消化请求」的账；**F3** `check_buildspec_go.py:566` 的**顶层键集相等**断言现在为假（Go 20 键 vs Python 19，多 `retreats`），而它不认识 `specKeysGoOnly`；**F4** `leftAt` 是**零消费者**的字段（真冷却读 `lastLeft`），而 `1132`／`3236` 两条注释都指出 `leftAt`；**F5** `teamAuraTick` 内层对 `owner` **不判 `alive()`**（同族另一条路 `2843` 判了）⇒ 撤退的人继续发光环；**F6** 退费是**唯一不夹 `cost_max`** 的回费路（对照 `593`／`skill.go:182` 都夹），**实测 `cost_max=99` 时退费把它顶到 103**（§5.3） |
| **对不上（具名，但非判决级）** | **3** | **F7** `retreat()` 未清 `op.hp`（参照 `sim.py:2627` 清了）；**F8** `wire.go:441` 的出处「`unit.py` 的 `_retreat(name)` 按名字找人」**不存在**——全仓只有 `battle/sim.py:636 def retreat(self, position, time)`，运行时按**格子**找人（`sim.py:2625 _alive_op_at(cell)`）；**F9** `Spec.Retreats` 的契约与实测不符：`wire.go` 注释写「没有请求时是 `[]`，不是缺键」、`buildspec.go` 注释写「有输入才有（`omitempty` 承担语义）」，而字段**无 `omitempty`** ⇒ 实测**无撤退的计划给出 `"retreats": null`**（既不是 `[]` 也不是缺键） |
| **未核（附补法）** | **3** | 见下 |

### 未核（每条附补法）

1. **「召唤物随主人撤退消失」Go 有没有对应步骤**——参照 `sim.py:2642-2656` 有，Go 的撤退步没有；
   我没确认 Go 是否有召唤物通道。补法：`grep -n "summonOf\|SummonOf\|召唤" rios-sim/*.go`，
   有则把「主人退场」判据从 `hp<=0` 扩到 `retreated`，无则具名登记。
2. **`check_buildspec_go.py` 实跑的红/绿**——我起了后台任务但 25 分钟未跑完（只输出到第 2 行），
   按约束**没有 kill 任何 python 进程**；`§3.3` 给的是**把它的断言原样复算**的结果。
   补法：`python tools\check_buildspec_go.py`（check 档，前置 `RIOS_DATA`／`RIOS_SIM_BIN`），
   看它是否打出「键集不同／多 `retreats`」。
3. **`F5` 的裁定依据（光环主人撤退后还发不发）**——参照实现 `sim.py:3520-3527` **也没过滤 `alive`**，
   所以「Go 不改」与「参照一致」并不矛盾；我只证明了 **Go 内部两条光环路径守卫不一致**，
   没证明哪一种对。补法：查「青色怒火」这类 TeamAura 在实机上的口径（或请博士裁定），
   裁定前把不一致**具名登记**。

（原「未核 2 · 剩命与漏怪对不上」**已撤回**：那是我的跨行相减错，实测 `life = 20 − leaks` 四组全中，见 §六。）

---

*本复核只读：仓库内只新增本文件；合成计划落在 `out/audit-synth/`（文件名与 `title` 均标 `SYNTHETIC`）；
未改任何 `.go`／夹具／数据，未重建二进制，未 kill 任何 python 进程。*
