# 正文 → 公式项：维护者手册

> 面向**接手这套解析器的人**。这里只讲两件事：**要改该怎么下手**、**改完怎么证明没改坏**。
> 逐条调研结论与踩坑的来龙去脉不在本文，见第九节的分工表。
>
> 写这份文档时的实测值（会漂，别抄）：`RULES` **137** 条、`ENEMY_RULES` **71** 条、
> `RULES_ENEMY` 合计 **208** 条。想拿当前值：

```powershell
python -c "from ak_tactic import formula as F, enemy_formula as E; print(len(F.RULES), len(E.ENEMY_RULES), len(E.RULES_ENEMY))"
```

---

## 一、这台机器是干什么的

把游戏里**人写的正文**，翻译成**机器能结算的结构**。

输入两路，输出同一种东西（`Term` 列表）：

| 来源 | 文本长什么样 | 入口 |
| --- | --- | --- |
| 干员 | gamedata 的游戏内正文，只有 `<$ba.xxx>` 标签与 `{key:spec}` 占位符 | `formula.parse` |
| 敌人 | prts.wiki 的 wikitext，外面还包着一层 wiki 模板 | `enemy_formula.parse_enemy` |

**两条铁律，先记住再动代码：**

1. **只翻译，不算数。** 编译期绝不求值。`移动速度+(50%×加速层数)` 这类带变量的算式，
   只保留**结构**——`formula` 存完整算式、`vars` 存它依赖哪些变量，而 `amount`
   **一律为空**。变量的值运行时才知道，编译期编不出来。任何"顺手求个值"的实现
   都会被自检打红。
2. **少算可以，算错不行。** 判不出来就标 `UNKNOWN` 或留空，**不要猜**。下游看到
   `suspect` 会走保守分支；猜错则会静默给出一个**看起来完全合理**的错数——
   这一类最难发现，见第七节的「伪装成已解析」。

---

## 二、数据流

```
干员：  gamedata 正文 ──► normalize ──┐
                                      ├─► 规则按序消费区间 ─► 量纲判定 ─► 成形 ─► Term
敌人：  prts.wiki wikitext ──► detemplate ──► （单位引用已先抢救）──┘
                                                          └─► expr_terms（算式 pass）─► 追加 Term
```

| 步骤 | 干什么 | 在哪 |
| --- | --- | --- |
| `detemplate` | 展开 wiki 模板、摊平 `[[页名\|文字]]`、`<br>`→逗号、去粗斜体与注释 | `enemy_formula.py` |
| `normalize` | 剥富文本标签、把 `{key:spec}` 换成私有区哨兵并记槽位、剔掉 `27%（+3%）` 这类潜能展示值 | `formula.py` |
| 规则扫描 | **按表内顺序**逐条在扁平文本上找；命中即**消费该区间**，后来的规则不得重叠 | `formula.parse` |
| 量纲判定 | 给每个数值定 `PCT`/`RATIO`/`FLAT`/`SCALE`（见 5.2） | `Num.unit` |
| 成形 | 按规则的 `form` 把系数拼成 `expr` | `_expr` |
| 算式 pass | 规则跑完后，在**与已消费区间不相交**的文字上找带变量的算式 | `extra` 回调 |
| 输出 | `Term` 列表 → `render`（人读）/ `formulas`（机器用） | `formula.py` |

`extra` 回调的约定（**新增 pass 必须遵守**）：签名 `f(flat, used) -> list[Term]`，
只处理与 `used` 不相交的片段，因此**只可能让结果变多，不可能改坏已匹配的项**。
自检里有一条「纯追加」的断言盯着它。

---

## 三、要认识的接口

### 数据类

| 名字 | 职责 |
| --- | --- |
| `Num` | 一个数值 + 它的**量纲与出处**。字段：`value` / `key` / `spec` / `literal` / `pct` / `hint` |
| `Term` | 一条公式项。17 个字段，主干是 `kind` / `expr` / `op` / `dtype` / `attr` / `duration` / `count` / `amount` / `amount2` |
| `Rule` | 一条声明式短语规则。`_r(name, pattern, kind, **kw)` 是构造糖 |

`Term` 的溯源字段别忽略：`source`（命中哪条规则）、`evidence`（原文片段）、
`context`（命中位置**之前**的一小段，用来判作用域，例如连击属于平A还是技能）、
`keys`（用到的黑板键）、`pos`（只用于按原文顺序排列，不参与判定）、
`vars`/`formula`（算式专用）。

### 函数

| 名字 | 位置 | 用途 |
| --- | --- | --- |
| `parse(text, blackboard=None, *, rules=None, extra=None)` | `formula.py` | 主入口 |
| `parse_enemy(text, blackboard=None)` | `enemy_formula.py` | 敌人入口＝`parse(rules=RULES_ENEMY, extra=expr_terms)` |
| `render(terms)` / `formulas(terms, name="")` | `formula.py` | 人读行 / `{公式名: 表达式}` |
| `load_corpus(db)` / `scan(db, top=25)` | `formula.py` | 全库语料 / 覆盖率统计 |
| `describe_row(db, key)` | `formula.py` | 单条正文的编译报告 |
| `detemplate(text)` | `enemy_formula.py` | wikitext → 纯文本 |
| `formulas_enemy(text, *, name="")` | `enemy_formula.py` | 敌人侧的 `formulas` |
| `enemy_scan(db, ...)` / `enemy_formulas(db, key)` | `enemy_formula.py` | 全库统计 / **单页报告**（最好用的入口） |
| `FormulaEffects` / `effects_from_terms` | `formula.py` | 编译结果 → 战斗层 |
| `compare_effects` / `merge_effects(bb, desc, policy="merge")` | `formula.py` | 黑板 vs 描述对账 / 合并策略 |
| `Expr` / `parse_arith` / `find_exprs` | `formula.py` | 算式解析器，**两支语料共用** |

规则表：`RULES`（干员）、`ENEMY_RULES`（敌人独有）、`RULES_ENEMY = RULES + ENEMY_RULES`。
`FormulaEffects` 的字段即战斗层能看到的全部效果：
`atk_scale` / `max_of` / `hit_count` / `hit_scope` / `max_target` / `heal_scale` /
`true_damage` / `damage_type` / `ep_damage` / `ep_burst` / `ep_heal` /
`self_control` / `enemy_control` / `sources` / `suspect` / `terms`。

### 命令行（两侧对称，2026-09-17 起）

| 命令 | 用途 |
| --- | --- |
| `python -m ak_tactic formula "<文本>"` | **干员侧**：编译任意文本，**不查库** |
| `python -m ak_tactic formula --char <干员>` | 库里一个干员的全部天赋（名字或 `char_id`） |
| `python -m ak_tactic formula --skill <技能>` | 一个技能的全部等级（技能名或 `skill_id`；撞名时报错列候选） |
| `python -m ak_tactic formula --scan` | 干员全库覆盖率 + 未命中的高频残句 |
| `python -m ak_tactic formula --enemy "<文本>"` | 临时改用敌人规则（含 detemplate 与算式钩子） |
| `python -m ak_tactic formula --scan --enemy` | 敌人全库覆盖率 |
| `python -m ak_tactic enemydb formula <敌人>` | 敌人单页报告（每节的原文、洗净文本、公式项） |

两侧都认 `--bb "k=v,k=v"`（黑板系数，也接受 JSON 对象）与 `--json`。
**统计命令必须与编译器同口径**：`scan` / `enemy_scan` 报的数就是 CLI 打印给用户的数，
它们一旦漏挂某个钩子，等于把编译器的成绩报低——已由自检逐行钉死（见第六节）。

---

## 四、加一条规则：六步

1. **先看它现在被编译成什么。** 别凭正文想象。
   敌人侧：`python -m ak_tactic enemydb formula <名字>`（单页报告）。
   干员侧：`python -m ak_tactic formula --char <干员>` 或 `--skill <技能>`；
   手头只有一句话时直接 `python -m ak_tactic formula "<那句话>"`，不必先入库。
   **先跑一遍自检确认基线是绿的**，否则你分不清红是你造成的还是原来就红。
2. **决定落在哪张表。** 干员语料的概念进 `RULES`；敌人独有概念进 `ENEMY_RULES`。
   **不要把敌人规则写进 `RULES`**——它是干员侧自检的基线，混进去会把干员的期望值一起带偏。
3. **决定插在哪一段。** 顺序即优先级（见 5.1）。`_r` 附近已按概念分了段
   （相性 / 阻挡 / 光环 / 位移 / 多形态……），跟着走。
4. **声明规则。** 占位符三个：`{N}` 数值、`{INC}` 数值后可能跟的括号增量、`{PCT}` 百分号。
   `scale`/`scale2`/`dur`/`count` 指向**命中片段内第几个数值**；`form` 决定右式形状；
   片段里夹带无关数字时用 `pick="last"`。
5. **加锚点。** 在 `tools/check_formula.py` 或 `tools/check_enemy_formula.py` 里写一条
   **真实句子 → 期望的 kind/表达式**。锚点从语料里抄，**不要自己编句子**——编出来的句子
   恰好符合你的正则，证明不了任何事。
6. **跑全套，看三件事**：① 精度守卫（有没有把无关句子咬走）；② 覆盖率守卫
   （总 ≥65%，`talent` ≥85% / `skill` ≥70% / `ability` ≥65%，`desc` **≤55%**）；
   ③ 三条战斗基线（1-7、SR-6、SR-EX-8）**逐字不变**。

---

## 五、五个必须懂的概念

### 5.1 顺序即优先级，命中即消费

规则**按表内顺序**扫描，命中一段就"吃掉"这段文字，后面的规则不得与它重叠。
所以：**更具体的规则必须写在更一般的前面**。

反面实例：`damage_atk` 会把「处于 X 爆发期间则额外造成攻击力 N% 的元素伤害」
当成普通伤害收走——**条件性丢失，而表达式看起来完全正确**，只有断言 `dtype` 才会暴露。
四条 `ep_burst_*` 因此被提到伤害表之前。

### 5.2 量纲四态与判定顺序

`Num.unit` 的判定顺序**不能调换**：

```
文面百分号 → 格式说明符 endswith % → 键名白名单（RATIO / FLAT / 人裁定） → 上下文 hint → UNKNOWN
```

* `PCT` —— 文面就写了 `%`，值**已经是百分数**（210 就是 210%）。再乘 100 会得到 21000%，真发生过。
* `RATIO` —— 黑板里的比例（0.14 → 14%、2.1 → 210%）。
* `FLAT` —— 绝对值（8 就是 8 秒/点/个）。
* `SCALE` —— 倍率。
* `UNKNOWN` —— 判不出来，**标存疑不猜**。

白名单规模：`RATIO_KEYS` 13、`FLAT_KEYS` 22、`RULED_FLAT_KEYS` 73（后者是**人裁定**的，
出处见 `docs/formula-units.md`）。键名比对是**原键与剥前缀后各一次、且忽略大小写**：
`{ABILITY_RANGE_FORWARD_EXTEND}` 全大写、`attack@silence` 要剥 `attack@`。

上下文判据（键名毫无线索时看数值后面紧跟的字）**必须排在白名单之后**：白名单是从实测语料
核出来的，比字面邻字可信；但它必须存在，否则 `{sleep}秒` 这类一律落进"存疑"。

### 5.3 带变量的算式只保留结构

`移动速度+(50%×加速层数)` 按常数提取不是"漏了"，而是**会算错**——它会得到
`ATK × 50%`，看起来合理，实际意思是「**每层** 50%」。

约定：`amount` 一律为空，`expr` 是值算式，`formula` 是完整算式，`vars` 是依赖的变量。
自检里有守卫，任何求值实现都会红。

### 5.4 `op` 的基准在两套语料里是**相反**的

| 值 | 干员侧含义 | 敌人侧含义 |
| --- | --- | --- |
| `self` | 该干员自己 | **该敌人自己** |
| `ally` | 我方阵营 | **敌方阵营**（召唤物、光环） |
| `enemy` | 敌方 | **我方干员与召唤物** |

写敌人规则时想「这条效果落在谁身上」，答案是**文本的主语**。搞反了不会报错。

### 5.5 中文数字有真数值也有习语

占位符分两个：`_DNUM`（只要阿拉伯数字）用于**量词**，`_DORD`（含中文数字）用于**序数**。

PRTS 的正文是人写的散文，中文数字几乎只出现在习语里——实测「蓄力**一**段时间」
曾被算成「持续 1s」，**看起来完全合理、实际是编的**。反过来「切换至第**二**形态」
的「二」是真数值。

### 5.6 单位引用必须在 `normalize` 之前抢救

PRTS 用尖括号表示单位引用（`<无谓>`、`<R系列动力装甲>`），而 `normalize` 的标签正则会把
`<...>` 当富文本标签**整段剥掉**：`召唤1个<无谓>` 变成 `召唤1个`，**召唤的是什么就没了**，
而那正是这条语料唯一的语义。

判据是"像不像真标签"（真标签以 `$`/`@`/`/` 开头，或 `br`/`color=`）而不是"有没有尖括号"。

---

## 六、不变量与守卫

改完这些必须**仍然成立**（自检里大多有对应断言）：

| 不变量 | 为什么 |
| --- | --- |
| 算式项 `amount` 必须为空 | 见 5.3；求值即错 |
| `RULES_ENEMY` 的前 N 条**逐条等于** `RULES` | 干员规则必须在前，否则粗粒度规则先咬走带系数的句子 |
| `detemplate` 后全语料**零残留花括号** | 残留说明有模板没展开，规则会匹配到模板名 |
| 规则名唯一 | 自检项；重名会让溯源失效 |
| 干员侧**不接**算式 pass | 实测纯常数片段 561 处、真变量仅 8 处且全是 `/秒` 被当除号：零收益、只增误读 |
| 覆盖率下限（总 65%，分来源）+ `desc` 上限 55% | 下限防退化；上限防"把剧情文本也算进来刷数" |
| 三条战斗基线逐字不变 | 这一层是给战斗层供数的，改了不该改的会静默改变战斗结果 |
| 统计函数与真编译器**逐行同口径** | `enemy_scan` 曾漏挂算式钩子，把编译器的成绩报低；CLI 照它打印 |
| `--json` 走的那条序列化路径**真能跑** | `Term` 只有 `to_dict`，写成 `as_dict` 时自检全绿、命令直接崩 |
| 自检**不是空转** | 见第七节最后一条 |

---

## 七、坑清单（每条都真踩过）

| 现象 | 根因 | 防线 |
| --- | --- | --- |
| 「元素爆发期间」永不命中，18 条静默漏掉 | 正则 `损伤?` 是「损」必选、「伤」可选 | 可选两字要写 `(?:损伤)?` |
| 条件性伤害被当普通伤害，表达式却看着对 | 规则顺序：一般规则排在具体规则之前 | 断言 `dtype`；`ep_burst_*` 提前 |
| 含 `%` 的算式全判非法 | 用 `m.lastgroup` 判 token 类型（它返回最后一个**子组**） | 按固定优先级逐个查组是否非 None |
| 「蓄力一段时间」变成「持续 1s」 | 量词里的中文数字被当数值 | 量词用 `_DNUM`，序数才用 `_DORD` |
| `召唤1个<无谓>` 丢了召唤物名 | 单位引用被 normalize 当标签剥掉 | `_UNIT_REF` 抢在 normalize 之前 |
| `物理/法术伤害-80%` 算成除法 | 中文的 `/` 极少是除法 | 左看词尾、右看词头都是伤害类型词即判并列 |
| **`受到的物理伤害-80%` 被算式 pass 兜成一条看着对的错项** | 规则只认「降低80%」，不认 `-80%`；算式把它当变量名 | **最危险的一类：伪装成已解析**。见下 |
| 覆盖率涨了 0.9%，但那一涨是错的 | 把「释放」「放下」也算进召唤 | 逐条看证据；总覆盖不是正确率 |
| 长度上限 8 字把真属性名顶红 | `可抵抗状态生效时间倍率` 是 11 字的真属性名 | 阈值按**真实反例**校正，不凭手感 |
| 自检整节静默变成空转 | `check` 的参数顺序写反（见第八节） | 新加自检前先看该文件的签名 |
| `enemydb formula --json` 直接崩，自检却全绿 | CLI 调 `Term.as_dict()`，真名是 `to_dict()` | `check_formula` 的「序列化冒烟」节 |
| 敌人覆盖率统计比编译器低 0.9 个点 | `enemy_scan` 漏挂 `expr_terms` 钩子 | `check_enemy_formula` 覆盖率节里的逐行对拍 |

**「伪装成已解析」要单独记一笔**：判据是"规则表完全不匹配、随后被兜底 pass 收走"。
它比"漏了"更危险——漏了看得出来，错了看不出来。加新规则时，**先确认它确实被某条规则命中**
（看 `Term.source`），而不是被兜底逻辑收走的。

---

## 八、日常工作流

```powershell
python -m ak_tactic db build                 # 干员库（3.4 秒，不联网）
python -m ak_tactic enemydb build            # 敌人库（联网，首次约 53 秒）

python -m ak_tactic enemydb formula 死志的凝结   # 敌人单页报告：最好用的调试入口
python -m ak_tactic formula --char 望        # 干员侧：一个干员的全部天赋
python -m ak_tactic formula "攻击力+50%"     # 干员侧：随手验一句话，不查库
python -m ak_tactic formula --scan           # 干员全库覆盖率 + 未命中残句
python tools/check_formula.py                # 干员侧自检
python tools/check_enemy_formula.py          # 敌人侧自检
python tools/unit_audit.py                   # 重刷 docs/formula-units.md（已填的裁定会续用）
python tools/uncertainty_audit.py            # 重刷 docs/uncertainties.md（同上）
python tools/check_battle.py                 # 战斗基线（三条）
```

**两个 `check` 的签名顺序是反的**——写反**不会报错**，字符串永远为真，整节静默空转
（真踩过：93 项里 34 项是空的）：

| 文件 | 签名 |
| --- | --- |
| `tools/check_formula.py` | `check(ok, label, detail)` —— **条件在前** |
| `tools/check_enemy_formula.py` | `check(label, ok, detail)` |

**量纲裁定的两条表**都由生成器维护、**最后一栏由人填**，且重新生成时会
**读回续用**已填内容。填法：只动 `裁定` 栏；表格**第一列必须是键**（不是编号 `#`），
否则读回来的键对不上，裁定会静默丢失。

---

## 九、文档分工

| 文档 | 讲什么 | 什么时候看 |
| --- | --- | --- |
| **本文** | 怎么下手、怎么验证 | 要改代码时 |
| `docs/formula-model.md` | 干员侧的调研结论：为什么做、管线、量纲、规则语法、覆盖率水位、驱动战斗结算 | 想知道"当初为什么这么定" |
| `docs/enemy-formula.md` | 敌人侧的全部细节：detemplate 五要点、15 个新 kind、语料特性、算式 pass、逐条坑 | 改敌人规则时**必读** |
| `docs/formula-units.md` | 量纲裁定台账（人填）+ 未定量纲的键 | 碰到 `UNKNOWN` 时 |
| `docs/formula-sources.md` | 外部公式取源调研（AKData / calc-framework / wiki 口径与三处分歧） | 要核对结算公式本身时 |
| `docs/uncertainties.md` | 待博士裁定的清单（项目级问题、误读复查、数据缺口） | 拿不准要不要猜时——**先查这里，别自己定** |

**水位会漂，别在文档里写死。** 覆盖率的当前值以 `scan` / `enemy_scan` 的输出为准；
规则条数以 `len(RULES)` / `len(ENEMY_RULES)` 为准。
