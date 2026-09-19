# kind ↔ Go 落点 映射表（C 档乙·第二版）

> **生成物，不许手改**：由 `tools/kind_mech_map.py` 生成（`--md`）。生成时所在树 HEAD=`93aab0c`。
> **表不问「该不该建模」**——它只记「谁对应谁」；判据（先写后跑）见该文件头部。
> **本版改动**（PM `msg-mu8yg0hb-f8` ＋ 验收对账）：新增第四态「待换尺子」（`regen` 改判）；M 列增「抽取方式」并加「逐格交代」节；「有落点」按 kind／distinct cand 两个口径分列；`go_index()` 剥掉**行尾注释**（词表 1508 → 1490）。

左列＝`ak_tactic/formula.py` 的 `RULES` 里 `kind` 的**确切字面值**（共 **23 种**）；M 列＝该 kind 在 Python 落点写出的**字段名**（带行号与抽取方式）；R 列＝Go 生产代码 15 个 `.go`（排除 `*_test.go`、剥掉整行与行尾注释，词表 1490 个）里的整词命中。

## 计数（**五个数各自独立，不许相加成一个数，也不许跨行并列**）

| 口径 | 数 | 说明 |
| --- | --- | --- |
| 有落点（**kind 计数**） | **3** | `damage`、`ep_damage`、`targets` |
| 有落点（**distinct cand 字段**） | **3** | `atk_scale`、`damage_type`、`max_target` —— 口径＝**所有产生命中的 cand 名去重** |
| 　└ 其中被**多个 kind 共用**的 | **1** | `damage_type` ⇒ **kind 计数 > 净字段计数** |

★ **两个口径都印出来，是因为它们曾被并列过**：验收对账时量到「净字段 2」（`damage_type`、`max_target`），而本表量到 **3**（多一个 `atk_scale`）。**不是谁错**——v1 主表每行只显前 2 处命中，把 `atk_scale`＠`rios-sim/wire.go:273`（`AtkScale float64 \`json:"atk_scale"\``）挤进了「另有 N 处」，于是「主表可见口径」＝2、「全部命中口径」＝3。**v2 已把主表改成按 cand 分组全列，两个口径同为 3**（`6dd6739c`：两套分母的数不许并列 ⇒ 要么分开写、要么把分母消掉）。
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
| `damage` | 17 | `damage_type`＠1660·out、`max_of`＠1665·out、`max_of`＠1666·note、`atk_scale`＠1669·out、`atk_scale`＠1670·out、`atk_scale`＠1671·note、`true_damage`＠1677·out | （不适用：已命中） | `damage_type`（3 处）→ `rios-sim/mech/huai_shu_li.go:369`（与 `ep_damage` 共用 ⇒ **归属未核**）<br>`atk_scale`（3 处）→ `rios-sim/wire.go:273` | **有落点** |
| `debuff` | 9 | — | — | — | **未核** |
| `dodge` | 3 | — | — | — | **未核** |
| `ep_burst` | 4 | `ep_burst`＠1705·out、`ep_burst`＠1706·note | ✓ | — | **未核** |
| `ep_damage` | 3 | `ep_damage`＠1699·out、`damage_type`＠1699·out、`ep_damage`＠1700·note | （不适用：已命中） | `damage_type`（3 处）→ `rios-sim/mech/huai_shu_li.go:369`（与 `damage` 共用 ⇒ **归属未核**） | **有落点** |
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
| `targets` | 9 | `max_target`＠1686·out、`max_target`＠1687·out、`max_target`＠1688·note | （不适用：已命中） | `max_target`（3 处）→ `rios-sim/wire.go:271` | **有落点** |
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

## 共用 cand（一个字段名被多个 kind 抽到）

| cand | 被哪些 kind 抽到 | 影响 |
| --- | --- | --- |
| `damage_type` | `damage`、`ep_damage` | 「净落点字段」口径下只算 **1** 个字段 |
| `damage_type` | `ep_damage`、`damage` | 「净落点字段」口径下只算 **1** 个字段 |
| `heal_scale` | `heal`、`regen` | 「净落点字段」口径下只算 **1** 个字段 |
| `heal_scale` | `heal`、`regen` | 「净落点字段」口径下只算 **1** 个字段 |
| `heal_scale` | `heal`、`regen` | 「净落点字段」口径下只算 **1** 个字段 |
| `heal_scale` | `regen`、`heal` | 「净落点字段」口径下只算 **1** 个字段 |
| `heal_scale` | `regen`、`heal` | 「净落点字段」口径下只算 **1** 个字段 |
| `heal_scale` | `regen`、`heal` | 「净落点字段」口径下只算 **1** 个字段 |

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
* `atk_scale` @ `rios-sim/wire.go:273`
  ```go
  AtkScale float64 `json:"atk_scale"`
  ```
* `atk_scale` @ `rios-sim/wire.go:273`
  ```go
  AtkScale float64 `json:"atk_scale"`
  ```
* `atk_scale` @ `rios-sim/wire.go:273`
  ```go
  AtkScale float64 `json:"atk_scale"`
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

### `targets`
* `max_target` @ `rios-sim/wire.go:271`
  ```go
  MaxTarget int `json:"max_target"`
  ```
* `max_target` @ `rios-sim/wire.go:271`
  ```go
  MaxTarget int `json:"max_target"`
  ```
* `max_target` @ `rios-sim/wire.go:271`
  ```go
  MaxTarget int `json:"max_target"`
  ```

## 附：反向守卫（`python tools/kind_mech_map.py --check`）

① **敏感性**：取一个已判『有落点』的 kind，把候选名人为清空 ⇒ 必须变『未核』；② **控制组**：锚从索自身取 ⇒ 必须判『有落点』；③ **两种注释口径逐行相同**；④ **新态可行使**（`regen` 必须落在『待换尺子』）。任一条不成立即 rc=1。

