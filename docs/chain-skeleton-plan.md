# `chain.*` 骨架：第一轮预注册（2026-09-20）

> 本文件是 **judge 的预注册**：**判据、方向、红条件先写死，再写代码**。
> 后续若判据要改，**改的是判据的措辞并留痕**，不是让实现去迁就（`7bd9ca65`）。
> 状态：**骨架代码尚未落**（本文件只登记「要判什么、什么情况下必须红」）。

## 一、键族身份（DB 实测，命令可复现）

`chain` 族在库里**只有 3 个键、两种写法**（带 `attack@` 前缀与裸键并存）：

| 键 | 出现处 | 值 | 正文依据 |
| --- | --- | --- | --- |
| `chain.max_target` | 特性（5 位）／技能 `skchr_halo_1` | 3.0（乌啾/明椒等）／4.0（halo 精2、halo 技1） | 「会在 **3** 个友方单位间跳跃」 |
| `chain.atk_scale` | 特性（4 位） | 0.75 | 「每次跳跃治疗量**降低 25%**」 |
| `chain.atk_scale_2` | 天赋「久病良医」×4 档（乌啾） | 1.1 / 1.15 / 1.2 / 1.25 | 「…110%/115%/120%/125%」四档 |

* 持有者（特性）：`char_135_halo`（**对敌人**，法术伤害链）、`char_4071_peper`、`char_4139_papyrs`、`char_4224_turdus`、`char_4179_monstr`（**对友方**，治疗链）。
* 持有者（天赋）：`char_4224_turdus`「久病良医」四档 → `chain.atk_scale_2`。
* 持有者（技能）：`skchr_halo_1`（同时带 `chain.max_target`=4.0 与 `max_target`=2.0 —— **两个不同的键，不许合并读**）。
* 复现：

```powershell
python -m ak_tactic db sql "SELECT char_id, group_index AS gi, cand_index AS ci, name, blackboard FROM operator_talent WHERE blackboard LIKE '%chain%'"
python -m ak_tactic db sql "SELECT char_id, cand_index AS ci, unlock_phase AS ph, blackboard FROM operator_trait WHERE blackboard LIKE '%chain%'"
python -m ak_tactic db sql "SELECT skill_id, level, blackboard FROM skill_level WHERE blackboard LIKE '%chain%' LIMIT 6"
python -m ak_tactic db sql "SELECT char_id, override_description FROM operator_trait WHERE blackboard LIKE '%chain%'"
```

**两条正文原文**（判据的地基：断言从正文写起，不从键名想当然 §`4decd843`）：

* 治疗链（`char_4071_peper`／`char_4139_papyrs`／`char_4224_turdus` 特性）：
  「恢复友方单位生命，且会在 **3** 个友方单位间跳跃，每次跳跃治疗量**降低 25%**」
* 伤害链（`char_135_halo` 特性）：
  「攻击造成法术伤害，且会在 `{attack@chain.max_target}` 个**敌人**间跳跃，每次跳跃**伤害降低 15%** 并造成短暂停顿（精英2后更新）」

⇒ **同一个键族有两种用法**（对友方＝治疗链，对敌人＝伤害链），且**衰减比例不同**（25% vs 15%）。
★ 本轮**只做治疗链这一支**（PM 裁定：第一轮不建第二族）；伤害链那支**登记不建**。

## 二、Go 侧现状（取证范围写在结论里）

* 命令：`grep -r chain rios-sim`（含 `*_test.go`）⇒ **0 命中**。
* ⇒ 「Go 侧没有 `chain` 的消费点」这句话的**取证范围＝整个 `rios-sim` 树（29 个 .go：15 生产 + 14 测试）**；
  超范围（Python 侧、其它树）**未核**（`1865d35a`：取证范围不许窄于结论范围）。

## 三、骨架形状（最小接线，先 dormant）

1. 新机制文件 `rios-sim/mech/chain.go`：实现 `mech.Mechanism`（`ID()` ＝ `chain`），
   配置经 `mech.RegisterFactory`／`wire.MechConfig` 传入（`rios-sim/wire.go:73`）。
2. **只在配置存在时动作** ⇒ 对既有基线**零影响**；自证方式＝golden 基线逐项不变 + `grep` 自证
   （`09516544`：新代码先 dormant 并 grep 自证零变化）。
3. 本轮**不做**：不改 `simgo/skills.py` 白名单，不碰任何现有机制文件。

## 四、★ 本轮只交**一条键的判据**：`chain.atk_scale`

**断言**（方向）：治疗链上，第 2 跳的治疗量 = **0.75 ×** 第 1 跳（**严格递减**，且首跳＝满量）。

**判据三件套**：

* **计数可见**：判据必须打印**逐跳治疗量序列**（不是只打印一个数）——只比总数会让「衰减发生在哪一跳」不可见。
* **合成反例（可证伪的红条件，先写死）**：
  * （a）把衰减系数当**每次乘基准**（每跳都 ×0.75）⇒ 第 3 跳 = 0.75 ≠ 预期 ⇒ **必须红**；
  * （b）把衰减**丢掉**（每跳 = 1.0）⇒ 第 2 跳 = 1.0 ⇒ **必须红**；
  * （c）把衰减方向弄反（越跳越高）⇒ **必须红**。
* **反向守卫**：把 `chain.atk_scale` 置 1.0（等价于无衰减）时判据**必须红**，且退出码非 0。

## 五、★ 明确「未定」的一项（不许拿猜测顶）

第 3 跳的治疗量是 **0.5625（等比 0.75²）** 还是 **0.5（等差 1−0.25×2）**——**语料只给了 `0.75` 一个数，两者在 n=2 完全同值、无法分辨**。

* 正文写「**每次**跳跃…降低 25%」，字面更像**逐次相对衰减（等比）**，但**不足以下结论**。
* 因此：**本轮判据只断言「方向 + 第 2 跳 = 0.75」**；第 3 跳记 **未定**，
  要判它必须另找证据（跨源对账／实战逐跳读数），**不许**由 0.75 与「25%」推出来当事实。

## 六、下一步（第一轮范围）

1. 落 `rios-sim/mech/chain.go` 骨架 + 上述判据（Go 单测）；
2. 跑 golden 基线自证「零变化」，跑新判据自证「能红」；
3. 交 PM；**骨架通过 ⇒ 再补另两个键（`chain.max_target`、`chain.atk_scale_2`）；不通过 ⇒ 早停**（PM 原话）。
