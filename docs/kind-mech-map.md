# kind ↔ Go 落点 映射表（C 档乙·第一版）

> **生成物，不许手改**：由 `tools/kind_mech_map.py` 生成（`--md`）。生成时所在树 HEAD=`cefa1b7`。
> **表不问「该不该建模」**——它只记「谁对应谁」；判据（先写后跑）见该文件头部与下表脚注。

左列＝`ak_tactic/formula.py` 的 `RULES` 里 `kind` 的**确切字面值**；共 **23 种 kind**。中列＝该 kind 在 Python 落点里写出的**字段名**（带行号，可复核到原文行）。右列＝Go 侧机制标识，三态。Go 侧索＝`rios-sim/**/*.go` 生产文件 **15** 个（排除 `*_test.go`、跳过整行注释），词表 1508 个。

**计数（四种来源各自独立，不许相加成一个数）**：有落点 **3** 种 ／ 未核·**Python 侧无可抽字段名** **15** 种 ／ 未核·**有字段名但 Go 0 命中** **5** 种 ／ 无落点 **0** 种（本轮**不填**，见脚注）。

| kind（确切名字） | 规则条数 | Python 落点字段名（行号） | Go 侧机制标识 | 态 |
| --- | --- | --- | --- | --- |
| `buff` | 26 | — | — | **未核** |
| `control` | 10 | `self_control`(1718)、`enemy_control`(1718)、`control`(1720) | — | **未核** |
| `cost` | 3 | — | — | **未核** |
| `count` | 6 | — | — | **未核** |
| `damage` | 17 | `damage_type`(1660)、`max_of`(1665)、`max_of`(1666)、`atk_scale`(1669)、`atk_scale`(1670)、`atk_scale`(1671)、`true_damage`(1677) | `damage_type` → `rios-sim/mech/huai_shu_li.go:369`<br>`damage_type` → `rios-sim/wire.go:165`（另有 2 处） | **有落点** |
| `debuff` | 9 | — | — | **未核** |
| `dodge` | 3 | — | — | **未核** |
| `ep_burst` | 4 | `ep_burst`(1705)、`ep_burst`(1706) | — | **未核** |
| `ep_damage` | 3 | `ep_damage`(1699)、`damage_type`(1699)、`ep_damage`(1700) | `damage_type` → `rios-sim/mech/huai_shu_li.go:369`<br>`damage_type` → `rios-sim/wire.go:165`（另有 1 处） | **有落点** |
| `ep_fragile` | 1 | — | — | **未核** |
| `ep_heal` | 5 | `ep_heal`(1710)、`ep_heal`(1711)、`ep_heal`(1712) | — | **未核** |
| `ep_resist` | 1 | — | — | **未核** |
| `flag` | 5 | — | — | **未核** |
| `heal` | 8 | `heal_scale`(1692)、`heal_scale`(1693)、`heal_scale`(1694) | — | **未核** |
| `pen` | 2 | — | — | **未核** |
| `prob` | 1 | — | — | **未核** |
| `range` | 4 | — | — | **未核** |
| `regen` | 4 | `heal_scale`(1692)、`heal_scale`(1693)、`heal_scale`(1694) | — | **未核** |
| `shield` | 3 | — | — | **未核** |
| `sp` | 3 | — | — | **未核** |
| `summon` | 2 | — | — | **未核** |
| `targets` | 9 | `max_target`(1686)、`max_target`(1687)、`max_target`(1688) | `max_target` → `rios-sim/wire.go:271` | **有落点** |
| `trait` | 8 | — | — | **未核** |

## 脚注：三态各是怎么定出来的

* **有落点（机械命中）**＝中列任一字段名在 `rios-sim/**/*.go`（**排除 `*_test.go`**、跳过整行注释）里以整词命中。**命中数会被通用词骗**，所以下表把**原文行**一并交出，判读材料与数字同权。
* **未核**＝0 命中。理由写死：Go 生产代码里未命中；未逐条读语义（grep 0 命中 ≠ 无落点，同族 7f782586／1865d35a）
* **两处软处（写在表里，不许只写在脑子里）**：
  1. **通用词命中**：候选名若是不含 `_` 的短英文名（`damage`／`control`／`heal`…），命中**可能来自别处的同名词**。表里带 ⚠ 标记，**并且把原文行一并交出**，判读材料与数字同权。
  2. **大小写尺子**：本表按**整词、大小写敏感**匹配，而 Go 侧标识符是驼峰（`Heal`）、Python 落点字段名是全小写（`heal_scale`）⇒ **大小写差异会把「有」读成「未核」**。有这类情况的行在右列写 `⚠ 同词不同大小写命中（诊断，不计入态）`——**它不改变态**，只是防止下一个人把『未核』读成『Go 侧没有』。
* **无落点：本轮一个都不填。** 它要「逐条读过 Go 侧＋写明取证范围」才算（`fac4b7de`）；**不许由 0 命中推出**——Go 里换个名字就 grep 不到（`7f782586`、`1865d35a`）。

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

## 附：反向守卫（`python tools/kind_mech_map.py --check`）

① **敏感性**：取一个已判『有落点』的 kind，把候选名人为清空 ⇒ 必须变成『未核』；② **控制组**：合成候选名 `TakeDamage` ⇒ 必须判『有落点』。两条任一不成立即 rc=1。（这不是形式——它证明「状态真的会翻」，否则整张表的『未核』可能只是尺子坏了。）

