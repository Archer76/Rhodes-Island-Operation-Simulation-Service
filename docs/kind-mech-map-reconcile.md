# kind ↔ Go 落点表 · **对账**（验收方，独立复算）

> 对账对象：`docs/kind-mech-map.md`（**生成物**）＋ 生成器 `tools/kind_mech_map.py`，提交 **`83a11a4`**（后端2 出表）。
> 本文是**手写**的对账报告（不是生成物，不会被重生成冲掉）。
> 纪律：**出表方不自证，对账方不看它的数**——下面每个数都是我在本树重跑/重算得到的。
> **分工**：表由后端2 出（能改表的一方），对账由验收出（不改表的一方，`83825a62`）。

## 一、可复现性（先行，不然后面全是转述）

| 检查 | 我跑的 | 结果 |
|---|---|---|
| 反向守卫 | `python tools/kind_mech_map.py --check` | **rc=0**（控制组锚从索自身取、命中最多词 `omitempty` 107 处）✓ |
| 生成 | `python tools/kind_mech_map.py --md … --json …` | **rc=0** ✓ |
| 与它交的产物比 | 我重生成 vs `docs/kind-mech-map.md` | **逐字只差一行**——生成时树 HEAD（它 `83a11a4`／我 `cefa1b7`）⇒ 同口径可复现 ✓ |

尺子自检：`rios-sim` 下 29 个 `.go` = **15 生产 + 14 测试**，与它的读数一致；生产整词表我独立取到 **1490** 个（它报 1508，差 18 ⇒ 见 §四未核）。

## 二、列的独立复算（口径：**cands＝Python 落点字段名**，不是 kind 名）

★ 我第一遍按 **kind 名**在 Go 里整词匹配，得「有落点 10」，与它的 3 对不上。**不是它错，是我换了键空间**（`5383209a`）。按它的口径（`cands` 字段名）复算 ⇒ **一致**：

| 态 | 我的复算 | 它的读数 | 判 |
|---|---|---|---|
| 有落点 | **3**（`damage`、`ep_damage`、`targets`） | 3 | **一致** ✓ |
| 未核 | **20** | 20 | **一致** ✓ |
| 无落点 | **0**（未填） | 0 | **一致** ✓ |

kind 种数：我从 `ak_tactic/formula.py` 的 `RULES[*].kind` 独立取到 **23** 种，逐名与它相同 ✓。

## 三、★ 顶回去的两处（这是本次对账的产出）

### 3.1 「有落点 3」是 **kind 计数**，不同字段只有 **2** 个

`damage` 与 `ep_damage` **共用同一个 cand `damage_type`**，hit 明细（三条）**逐条相同**：

```
rios-sim/mech/huai_shu_li.go:369  DamageType string          `json:"damage_type"`
rios-sim/wire.go:165               DamageType     string      `json:"damage_type"`
rios-sim/wire.go:268               DamageType string  `json:"damage_type"`
```

⇒ 表里应显式标注「共用同一 cand」，或加一列 `distinct_cand`；否则读者会把 3 读成「三个独立落点」。
另外：**`damage_type` 是否同时也是 `ep_damage`（元素损伤）的落点，未核**——两把机制共用一个字段名不等于共用一个语义（同族 `180eab0c`：**一个字面量同时清两个键**）。
净结论：**distinct 字段 = 2**（`damage_type`、`max_target`）。

### 3.2 ★ `regen` 那一格**不是「未核」，是「cand 名错」**

它把 `regen` 放进「未核②（有字段名但 Go 0 命中）」，cand 是 **`heal_scale`**（与 `heal` 共用）。而 Go 生产侧**有真落点**，只是**名字不同**：

```
rios-sim/wire.go:206     RegenAura *RegenAuraSpec `json:"regen_aura,omitempty"`
rios-sim/wire.go:80      type RegenAuraSpec struct {
rios-sim/sim.go:2377     func regenAuraTick(ops []*operator, dt float64) {
rios-sim/sim.go:347      regenPerSec float64
rios-sim/mech/huai_shu_li.go:1169  func (fs *Farmland) RegenPerSecond(x, y int) float64 {
```

取证范围：`rios-sim/**/*.go` **排除 `_test.go`**（15 个生产文件），读法：**整词大小写敏感 + 全小写化两种**。
⇒ 处置：这一格的 `reason` 应从「Go 0 命中」改为「**cand 名与 Go 落点名不一致**」（已见一例）。**零命中是尺子的读数，不是机制的事实**——否则读者会把 0 读成「没有落点」。

## 四、它点名要我顶的三处 · 判决

1. **通用词命中** ⇒ **这一栏是干净的**：三处命中全部是**真字段**（struct 字段 + `json:` tag，`wire.go:165/268/271`、`mech/huai_shu_li.go:369`），没有取到注释或无关同名词。
2. **大小写/驼峰尺子** ⇒ **诊断列本身有洞**：`regen` 的同族词在 Go 里是 `Regen*`/`regen*`（§3.2 五行），而它按 `heal_scale` 派生的驼峰候选自然命中不到 ⇒ **诊断"该命中却没命中"这一自检成立**。判别式：**靠名字匹配永远抓不到"换了名字的落点"**（与上一轮「名字命中≠语义等价」是对偶面）。
3. **「未核」≠「无落点」** ⇒ **同意，并守住**：本轮「无落点」我**一个都没填**。我给的范围只能证明「**没有同名字段**」，证明不了「**没有机制**」（§3.2 就是反例：机制在，名字不在）。要判「无落点」，必须逐条读机制并把取证范围写上。

## 五、本对账**未覆盖**的部分（不许读宽）

* 15 个「Python 侧无可抽字段名」的 kind：我**未逐条核**其落点假设，只核了 kind 计数与态分布；
* 表内 `rules` 列与 `formula.py` 的对应关系：**未逐条核**；
* 我的生产整词表 **1490** vs 它报 **1508**（差 18）：**未定位**（可能是注释剥离/语言特性差异，也可能是它的词表含非生产文件）；
* 第②桶里除 `regen` 外的 4 格（`control`、`ep_burst`、`ep_heal`、`heal`）：我只验了它们的 cand **整词 0、子串 0**（即"连子串都不存在"），**未**逐条读机制判「有/无落点」。

—— 验收会话（RIOS验收与守卫 / session-1a45cfee-9a65-4830-a327-03ac84285bfb）
