# kind ↔ Go 落点 映射表（C 档乙·第二版）

> **生成物，不许手改**：由 `tools/kind_mech_map.py` 生成（`--md`）。生成时所在树 HEAD=`5dae546`。
> **表不问「该不该建模」**——它只记「谁对应谁」；判据（先写后跑）见该文件头部。
> **本版改动**（PM `msg-mu8yg0hb-f8` ＋ 验收对账）：新增第四态「待换尺子」（`regen` 改判）；M 列增「抽取方式」并加「逐格交代」节；「有落点」按 kind／distinct cand 两个口径分列；`go_index()` 剥掉**行尾注释**（词表 1508 → 1490）。

左列＝`ak_tactic/formula.py` 的 `RULES` 里 `kind` 的**确切字面值**（共 **23 种**）；M 列＝该 kind 在 Python 落点写出的**字段名**（带行号与抽取方式）；R 列＝Go 生产代码 16 个 `.go`（排除 `*_test.go`、剥掉整行与行尾注释，词表 1505 个）里的整词命中。

## 计数（**五个数各自独立，不许相加成一个数，也不许跨行并列**）

| 口径 | 数 | 说明 |
| --- | --- | --- |
| 有落点（**kind 计数**） | **3** | `damage`、`ep_damage`、`targets` |
| 有落点（**distinct cand 字段**） | **3** | `atk_scale`、`damage_type`、`max_target` —— 口径＝**所有产生命中的 cand 名去重** |
| 去重后**命中处数**（按 `文件:行` 去重） | **12** | `atk_scale` 3 处、`damage_type` 4 处、`max_target` 5 处 —— ★ 与上面两行**不是同一口径**：这行数的是 Go 侧的**行** |
| 　└ **不含本轮新增文件**（＝**下面「本轮新增文件清单」里的那些**） | **6** | `atk_scale` 1 处、`damage_type` 4 处、`max_target` 1 处 —— ★ **这一行才与验收那一版可比**（它量时那种文件还不存在）；**「排除清单」在下面单独一节，连首次入库 sha 与时间一起印** |
| 共用字段（**只在「有落点」范围内**） | **1** | `damage_type` |
| 共用字段（**全表范围**） | **2** | `damage_type`、`heal_scale` —— ★ 多出的 `heal_scale`（`heal`／`regen`）不在有落点范围内，**而它正是 `regen` 那格缺陷的本体** |

### 本轮新增文件清单（**「不含本轮新增」那一列的口径来源**）

划界规则：**手工枚举的路径集合（不是 tag、不是起点 sha）：本轮新增且会被同一把尺子算成落点的文件**。★ 为什么必须印这一节（PM `msg-mu8zychr-fp` 把验收的建议升格为硬要求）：**「本轮」是随时间漂移的词**——同一个 `6`，在这一轮与下一轮的意思不同（下一轮若又新增了带 `json:"atk_scale"` 的文件，`6` 就变了）。**只印 `6`，读者无法判断它是否可比；印出清单，`6` 才有身份**（同族 `515530a8`：表的身份先于数值）。

| 路径 | 首次入库 sha | 入库时间 |
| --- | --- | --- |
| `rios-sim/mech/chain.go` | `136e617` | 2026-09-20 06:32:18 |

★ **被排除的命中处**（现算，故行号会随该文件改动而漂移——**这正是不能写死行号的理由**；验收 07:05 独立算的是 `atk_scale` ← `chain.go:34,70`、`max_target` ← `:33,67,111,114`，**本轮重生成后行号已经变了**，因为我随后又改过那个文件）：

| cand | 被排除的 `文件:行` |
| --- | --- |
| `atk_scale` | `rios-sim/mech/chain.go:35`、`rios-sim/mech/chain.go:81` |
| `max_target` | `rios-sim/mech/chain.go:34`、`rios-sim/mech/chain.go:78`、`rios-sim/mech/chain.go:124`、`rios-sim/mech/chain.go:127` |

★ **四个量分开写，因为它们回答的是四个不同的问题**（`6dd6739c`／`fd544d68`）：kind 计数（几个**机制种类**有落点）／distinct 字段（几个**字段名**命中）／共用字段（一个字段名被几个 kind 抽到）／命中处数（Go 侧几个**行**命中）。**跨行不可比、不许相加。**

★ **「净字段 2 vs 3」这一场争议的结论是两边各错一半——并且它的署名要写三方槽**（对账 `msg-mu8xg2iz-f4`／`msg-mu8ymgmc-ff`／署名更正 `msg-mu8zychr-fp`）：**① 归因源头＝PM 的广播推断**（它从我的汇报里推出「v1 主表把 `atk_scale` 藏了」，**且当时没标『这是我推的』**）；**② 写入产物＝我**（把这句推断当结论写进了 v2 表）；**③ 引用方＝验收**（它按产物署名归给了我，并在对账里查明源头另有其人）。★ 通则：**「产物里写着」与「这是谁说的」是两个槽**。**另外两边各错一半**：验收量到 2，是它自己打印时 `hits[:3]` 截掉了排第 4 的 `atk_scale`（**与我的主表显示无关**——这一点是它自己查出来并自纠的）；而我的**命中处数**把同一个 Go 行数了三遍（按**抽取次数**计数，不是按**对象**计数，**与幽灵 kind 同源**）。**现在的口径**：处数按 `文件:行` 去重，`atk_scale` **1 处**／`max_target` **1 处**／`damage_type` **4 处**。
| 待换尺子 | **1** | cand 与 kind 名不同源 ⇒ 先换尺子 |
| 未核·**Python 侧无可抽字段名** | **15** | 这把尺子量不到，不是「Go 侧没有」 |
| 未核·**同源 cand 但 Go 0 命中** | **4** | 要读 Go 确认 |
| 无落点 | **0** | **本轮一格不填**：要逐条读 Go ＋ 写明取证范围 |

## 主表

| kind（确切名字） | 规则条数 | Python 落点 cand（名字＠行·抽取方式） | 同源? | Go 侧机制标识 | 态 |
| --- | --- | --- | --- | --- | --- |
| `buff` | 26 | — | — | — | **未核** |
| `control` | 10 | `self_control`＠1718·out、`enemy_control`＠1718·out、`control`＠1720·note | ✓ | — | **未核** |
| `cost` | 3 | — | — | — | **未核** |
| `count` | 6 | — | — | — | **未核** |
| `damage` | 17 | `damage_type`＠1660·out、`max_of`＠1665·out、`max_of`＠1666·note、`atk_scale`＠1669·out、`atk_scale`＠1670·out、`atk_scale`＠1671·note、`true_damage`＠1677·out | （不适用：已命中） | `damage_type`（4 处）→ `rios-sim/mech/huai_shu_li.go:369`、`rios-sim/wire.go:165`（与 `ep_damage` 共用 ⇒ **归属未核**）<br>`atk_scale`（3 处）→ `rios-sim/wire.go:273`、`rios-sim/mech/chain.go:35`（**本轮新增**） | **有落点** |
| `debuff` | 9 | — | — | — | **未核** |
| `dodge` | 3 | — | — | — | **未核** |
| `ep_burst` | 4 | `ep_burst`＠1705·out、`ep_burst`＠1706·note | ✓ | — | **未核** |
| `ep_damage` | 3 | `ep_damage`＠1699·out、`damage_type`＠1699·out、`ep_damage`＠1700·note | （不适用：已命中） | `damage_type`（4 处）→ `rios-sim/mech/huai_shu_li.go:369`、`rios-sim/wire.go:165`（与 `damage` 共用 ⇒ **归属未核**） | **有落点** |
| `ep_fragile` | 1 | — | — | — | **未核** |
| `ep_heal` | 5 | `ep_heal`＠1710·out、`ep_heal`＠1711·out、`ep_heal`＠1712·note | ✓ | — | **未核** |
| `ep_resist` | 1 | — | — | — | **未核** |
| `flag` | 5 | — | — | — | **未核** |
| `heal` | 8 | `heal_scale`＠1692·out、`heal_scale`＠1693·out、`heal_scale`＠1694·note | ✓ | — | **未核** |
| `pen` | 2 | — | — | — | **未核** |
| `prob` | 1 | — | — | — | **未核** |
| `range` | 4 | — | — | — | **未核** |
| `regen` | 4 | `heal_scale`＠1692·out、`heal_scale`＠1693·out、`heal_scale`＠1694·note | **✗** | — | **待换尺子** |
| `shield` | 3 | — | — | — | **未核** |
| `sp` | 3 | — | — | — | **未核** |
| `summon` | 2 | — | — | — | **未核** |
| `targets` | 9 | `max_target`＠1686·out、`max_target`＠1687·out、`max_target`＠1688·note | （不适用：已命中） | `max_target`（5 处）→ `rios-sim/wire.go:271`、`rios-sim/mech/chain.go:34`（**本轮新增**） | **有落点** |
| `trait` | 8 | — | — | — | **未核** |

## 逐格交代：20 格「未核／待换尺子」的 cand 给的是什么、凭什么

| kind | cand | 凭什么（`formula.py` 行·抽取方式） | 同源? | 与谁共用 | 态 |
| --- | --- | --- | --- | --- | --- |
| `buff` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `control` | `self_control` | `formula.py:1718`·`out` | ✓ | — | **未核** |
| `control` | `enemy_control` | `formula.py:1718`·`out` | ✓ | — | **未核** |
| `control` | `control` | `formula.py:1720`·`note` | ✓ | — | **未核** |
| `cost` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `count` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `debuff` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `dodge` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `ep_burst` | `ep_burst` | `formula.py:1705`·`out` | ✓ | — | **未核** |
| `ep_burst` | `ep_burst` | `formula.py:1706`·`note` | ✓ | — | **未核** |
| `ep_fragile` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `ep_heal` | `ep_heal` | `formula.py:1710`·`out` | ✓ | — | **未核** |
| `ep_heal` | `ep_heal` | `formula.py:1711`·`out` | ✓ | — | **未核** |
| `ep_heal` | `ep_heal` | `formula.py:1712`·`note` | ✓ | — | **未核** |
| `ep_resist` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `flag` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `heal` | `heal_scale` | `formula.py:1692`·`out` | ✓ | `regen` | **未核** |
| `heal` | `heal_scale` | `formula.py:1693`·`out` | ✓ | `regen` | **未核** |
| `heal` | `heal_scale` | `formula.py:1694`·`note` | ✓ | `regen` | **未核** |
| `pen` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `prob` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `range` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `regen` | `heal_scale` | `formula.py:1692`·`out` | **✗** | `heal` | **待换尺子** |
| `regen` | `heal_scale` | `formula.py:1693`·`out` | **✗** | `heal` | **待换尺子** |
| `regen` | `heal_scale` | `formula.py:1694`·`note` | **✗** | `heal` | **待换尺子** |
| `shield` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `sp` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `summon` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |
| `trait` | **—（抽不到）** | 该 kind 的分支块里 `note()`／`out.` 都没出现 | — | — | **未核** |

★ 每格都能**报出自己来自哪一块、哪一行**（PM 对「串块」那条的判据）——报不出来就是解析器串了块。

## 共用 cand（一个字段名被多个 kind 抽到）——**这类缺陷的探测器**

★ 验收对账的原话：**「共用表不是附注，是这类缺陷的探测器」**——若共用表一开始就列 `heal_scale`，`regen → heal_scale` 那格**当场显形**。所以本节**按 cand 去重、每行一个 cand**（v2 曾把 `damage_type` 印两遍、且漏了 `heal_scale`）。

| cand | 被哪些 kind 抽到 | 其中有落点? | 与「待换尺子」的关系 |
| --- | --- | --- | --- |
| `damage_type` | `damage`、`ep_damage` | `damage`、`ep_damage` | — |
| `heal_scale` | `heal`、`regen` | 都不是 | ★ **就是 `regen` 那格的 cand**：它抽到这个名字，而 Go 侧落点叫别的名字 |

★ **归属未核**：`ep_damage` 现在这一态是**靠共用 cand `damage_type` 撑起来的**——「一个字段名同时清两个键」是 `180eab0c` 的同族问题，**`damage_type` 是不是 ep 的落点，本表不当既成事实**：要么补证据，要么标未核。**本轮标未核。**

## 脚注：四态各是怎么定出来的

* **有落点（机械命中）**＝cand 在 Go 生产代码里整词命中。**命中数会被通用词骗**，所以带 ⚠ 标记**并把原文行一并交出**——判读材料与数字同权。
* **待换尺子**＝0 命中 且 **cand 与 kind 名不同源**。理由写死：**cand 与 kind 名不同源** ⇒ 先回答「这个 kind 该抽哪个字段名」，不是去 Go 里找（换错名字 = 0 命中）
* **未核②**＝0 命中 且 cand 与 kind 名同源。理由写死：同源 cand、Go 生产代码 0 命中 ⇒ 要读 Go 确认（grep 0 命中 ≠ 无落点）
* **未核①**＝Python 侧抽不到字段名。理由写死：formula.py 里该 kind 没有可抽的落点字段名（`note()`／`out.` 都没出现）⇒ **这把尺子量不到**，不是「Go 侧没有」
* **无落点：本轮一个都不填。** 它要「逐条读过 Go 侧＋写明取证范围」才算（`fac4b7de`）；**不许由 0 命中推出**——Go 里换个名字就 grep 不到（`7f782586`、`1865d35a`）。

### 两处软处（写在表里，不许只写在脑子里）

1. **通用词命中**：cand 若是不含 `_` 的短英文名（`damage`／`control`／`heal`…），命中**可能来自别处的同名词**。
2. **大小写尺子**：本表按**整词、大小写敏感**匹配，而 Go 标识符是驼峰、Python 落点字段名是全小写 ⇒ **大小写差异会把「有」读成「未核」**。这类行在右列写 `⚠ 同词不同大小写命中（诊断，不计入态）`。
3. **注释口径（v2 修）**：只跳整行注释会让**行尾注释里的词**混进词表（实测差 18 个词，如 `STUN`／`UNABLE_ACTION`／`vs`）。v2 剥掉行尾注释（引号内的 `//` 不算注释），并在守卫里断言**两种口径下 23 行态逐行相同**。

## 附：有落点各条的原文行（判读材料）

### `damage`
* `damage_type` @ `rios-sim/mech/huai_shu_li.go:369`
  ```go
  DamageType string          `json:"damage_type"`
  ```
* `damage_type` @ `rios-sim/wire.go:165`
  ```go
  DamageType     string      `json:"damage_type"`
  ```
* `damage_type` @ `rios-sim/wire.go:268`
  ```go
  DamageType string  `json:"damage_type"`
  ```
* `damage_type` @ `rios-sim/wire.go:432`
  ```go
  DamageType string  `json:"damage_type"`
  ```
* `atk_scale` @ `rios-sim/mech/chain.go:35`
  ```go
  AtkScale  float64 `json:"atk_scale"`
  ```
* `atk_scale` @ `rios-sim/mech/chain.go:81`
  ```go
  return nil, fmt.Errorf("chain: atk_scale 必须 >0，收到 %v", s.AtkScale)
  ```

### `ep_damage`
* `damage_type` @ `rios-sim/mech/huai_shu_li.go:369`
  ```go
  DamageType string          `json:"damage_type"`
  ```
* `damage_type` @ `rios-sim/wire.go:165`
  ```go
  DamageType     string      `json:"damage_type"`
  ```
* `damage_type` @ `rios-sim/wire.go:268`
  ```go
  DamageType string  `json:"damage_type"`
  ```
* `damage_type` @ `rios-sim/wire.go:432`
  ```go
  DamageType string  `json:"damage_type"`
  ```

### `targets`
* `max_target` @ `rios-sim/mech/chain.go:34`
  ```go
  MaxTarget int     `json:"max_target"`
  ```
* `max_target` @ `rios-sim/mech/chain.go:78`
  ```go
  return nil, fmt.Errorf("chain: max_target 必须 ≥1，收到 %d", s.MaxTarget)
  ```
* `max_target` @ `rios-sim/mech/chain.go:124`
  ```go
  return nil, fmt.Errorf("chain: max_target 必须 ≥1，收到 %d", maxTarget)
  ```
* `max_target` @ `rios-sim/mech/chain.go:127`
  ```go
  return nil, fmt.Errorf("chain: max_target=%d：%w", maxTarget, ErrJumpUndetermined)
  ```
* `max_target` @ `rios-sim/wire.go:271`
  ```go
  MaxTarget int `json:"max_target"`
  ```

## 附：反向守卫（`python tools/kind_mech_map.py --check`）

① **敏感性**：取一个已判『有落点』的 kind，把候选名人为清空 ⇒ 必须变『未核』；② **控制组**：锚从索自身取 ⇒ 必须判『有落点』；③ **两种注释口径逐行相同**；④ **新态可行使**（`regen` 必须落在『待换尺子』）。任一条不成立即 rc=1。

