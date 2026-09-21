# rios-sim 自足进度台账

> **本文性质**：**手写文档**（不是生成物）。数字是**写这一版时现跑**的读数，
> 引用时请连命令与时刻一起引——它不会自己更新。
>
> 最后核对：2026-09-20 ｜ 判据入口 `python tools\check_go_all.py --selfcheck`

---

## 〇 · 一句话

**取数三层（关卡／敌人／干员）已经搬进 Go，且每一层都有跨实现对拍判据。**
缺的是「把干员效果折成两套数值」与「规格构造」——那两段还在 Python。

---

## 一 · 判据入口：一条命令出两个结论

```
python tools\check_go_all.py --selfcheck
```

* 前半：**六套判据现在不报红**；
* 后半：**六套的反向守卫都成立**（每套人为注入一处不一致，它真会红）。

★ 两个结论缺一不可：「全绿」只证明现在不报红；**没有反向守卫的绿是零信息量的绿**。

### 当前读数

| 判据 | 取证面 | 读数 |
|---|---|---|
| 关卡 `check_stage_go.py` | 缓存可达的 55 关 | 55 / 55 关逐字段一致 |
| 敌人 `check_enemy_go.py` | 那 55 关引用的全部敌人 | 251 只敌人逐字段一致 |
| 干员 `check_operator_go.py` | fixtures 20 位深扫 ＋ **账号名册全量 211 位** | 679 次折算逐字段一致 |
| 范围 `check_range_go.py` | 全表 73 个代号 × 4 朝向 | 292 / 292 次逐格一致 |
| 技能 `check_skill_go.py` | 全表 1810 技能 × **每一级** | 11012 条逐字段一致 |
| 分类 `check_classify_go.py` | 全表黑板键并集 1056 个 | 1056 / 1056 逐字段一致 |

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

---

## 三 · 未接的部分（具名，不是"没提就是没有"）

| 缺口 | 说明 |
|---|---|
| **两套数值 profile** | 面板 ＋ 效果折成「不开启那套」与「开启期间 active」两份。Python 侧住在 `simgo/skills.py`，做法是临时把「这一帧开没开技能」的字段摆成开启态、借原版的读数函数读。 |
| **规格构造与闸门** | `simgo/spec.py`（76 KB）＋ `simgo/skills.py` 的白名单。Go 现在仍收 Python 送来的 spec。 |
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
4. **没读全的东西不许混进判据，也不许当成"拿到了一半"。** 实测：
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
