# 元素损伤：待校正清单

这份清单是**给博士去找数据源**用的。按目标要求，数值不确定的元素损伤**先不做**，
这里把"缺什么、缺在哪一层、能不能拿到"逐条写清楚，好让拿到手就能去查。

调查日期 2026-09-18。改动相关源码前请先重跑本文里的命令核对——**数字会漂，
命令不会**。

---

## 一、先说结论：**本批的元素损伤范围是空的**

十位目标干员（电弧 / 机械师 / 望 / 赤刃明霄陈 / 圣聆初雪 / 令 / 阿米娅两形态 /
提丰 / 逻各斯 / 予愿安洁莉娜）**及其召唤物**，在**技能与天赋的正文和黑板里
一条元素损伤都没有**。

范围含召唤物：`token_10064_wang_stone1`（望）、`token_10069_mcnist_mcgraf`（机械师）。

### 这个"零"是怎么证明的（方法自检）

**先证明检索方法本身有效**：同样的检索词在全库命中**几十条**技能（`level=7`
口径下 36 条；不给死数是因为它随技能表更新会漂，命令在下面）（例如
`char_499_kaitou` 的 `attack@ep_damage_ratio`、`char_4187_graceb`、`char_4041_chnut`）。
所以十位干员那里的"零"是**结论**，不是检索写错了。

```bash
# 全库自检：应当非零
python -m ak_tactic db sql "SELECT s.skill_id, s.description FROM skill_level s WHERE s.level=7 AND (s.description LIKE '%灼燃%' OR s.description LIKE '%侵蚀%' OR s.description LIKE '%凋亡%' OR s.description LIKE '%元素损伤%')"
```

一句提醒：**先验是错的**。我原以为逻各斯是以凋亡损伤著称的，实际他的天赋是
「额外法术伤害 + 法抗 -10」、技3 是减速与清除敌方子弹——**完全没有损伤**。
所以这条结论是查出来的，不是推的。

---

## 二、模拟器侧：这套机制**根本没建**

`ak_tactic/battle/` 里没有任何元素损伤的处理。容易看错的两处**不是**它：

- `p3r.py` 的 `ELEMENT` / `"element"` 是**伤害相性槽**（0 弱点 / 1 正常 / 2 免疫），
  跟损伤条是两回事；
- `skill.py` 里提到的「损伤屏障」是**另一套**（抵挡损伤积累，不是生命屏障），
  尚未实现。

也就是说：**要接元素损伤，是从零建一套**（损伤条、积累、爆发、抗性），
不是补一个系数。

---

## 三、待校正清单

### (a) 【最关键，且**取不到**】损伤条容量

元素损伤的核心是"积累到阈值就爆发"，而**阈值这个数在两个库里都找不到**。

敌人原始属性共 **32 个键**，逐个看过，**没有任何一个是条容量**：

```bash
python -c "from ak_tactic.gamedata import EnemyLibrary, GameDataSource; print(sorted((EnemyLibrary(source=GameDataSource()).get('enemy_1007_slime').raw_attributes or {})))"
```

输出里与损伤有关的只有下面 (b) 那三个，都是**抗性/恢复**，不是**容量**。

**要问博士的**：损伤条容量是全局常量（如每类损伤固定 1000）、还是随敌人/随关卡？ 
若在客户端表里，表名是什么？（`excel/` 下哪一张？）

### (b) 【**数据可得，只是没接**】三个 ep 键被解析层丢了

原始属性里**有**这三个键，但 `ak_tactic/gamedata/enemy.py` 的字段映射**一个都没收**，
`EnemyStats` 上也没有对应字段——**它们在解析时被丢掉了**：

| 原始键 | 大概是什么 | 现状 |
|---|---|---|
| `epResistance` | 损伤抗性 | 未解析 |
| `epDamageResistance` | 损伤伤害抗性 | 未解析 |
| `epBreakRecoverSpeed` | 损伤条恢复速度 | 未解析 |

三者的值都是**嵌套结构**（不是标量），很可能按损伤类型分键
（灼燃/侵蚀/凋亡/神经各一个）——**这一点需要确认**，因为它决定字段怎么定义。

```bash
# 看原始值长什么样
python -c "from ak_tactic.gamedata import EnemyLibrary, GameDataSource; import json; ra=EnemyLibrary(source=GameDataSource()).get('enemy_1007_slime').raw_attributes; print(json.dumps({k:ra[k] for k in ra if k.lower().startswith('ep')}, ensure_ascii=False, indent=2))"
```

### (c) 【要查】爆发效果与数值

四类损伤（灼燃 / 侵蚀 / 凋亡 / 神经）爆发后各做什么，**定性**在 PRTS 有，
**数值**要查：

- 灼燃：爆发时造成法术伤害 + 降低攻击力 —— 降多少？伤多少？
- 侵蚀：降低防御 —— 降多少、持续多久？
- 凋亡：持续法术伤害 + 减速 —— 每跳多少、间隔多久？
- 神经：效果与数值？

### (d) 【要定口径】`ep_damage_ratio` 的量纲

技能黑板里只有数（如 `0.2`），**没有量纲说明**。是"攻击力的百分之多少转化为
元素损伤"，还是"直接给多少点损伤"？两者算出来的结果差一个攻击力因子。

同类还有：`ep_damage_scale`、`attack@extra_ep_damage_scale`、`ep_heal_ratio`
（损伤回复？）、`ep_damage_resistance`（技能给敌人的损伤抗性削减？）。

### (e) 【要对齐】两个库的"损伤抗性"是不是同一个量

- 敌人库 `enemy_level.element_resistance`：查值时**几乎全是 0.0**；
- gamedata 原始属性的 `epResistance` / `epDamageResistance`：**没解析**。

**要确认**：前者是不是后者的折算结果？还是一个独立的量？若两者同源，
接线时只该取一处，否则会重复扣。

```bash
python -m ak_tactic enemydb sql "SELECT element_resistance, COUNT(*) FROM enemy_level GROUP BY 1 ORDER BY 2 DESC"
```

---

## 四、如果这批要覆盖元素损伤干员

那要先改**批次范围**——现在这十位一个都没有。全库带元素损伤的是另一批人
（上面的自检命令能列出来）。这一点在动手前先跟博士确认，免得白做。

---

## 五、现在已经确定不用查的部分

- **十位干员不需要做元素损伤**（第一节，已证）。
- **不必去敌人库找条容量**（第三节 (a)，已证不在）。
- **不必去敌人库找重量**（那是位移的事，重量只在 gamedata 的 `massLevel`，
  见 `docs/uncertainties.md` 第十节）。
