# 第四批·方向表（A 名单 84 键逐条核方向）

作者会话：RIOS 第四批建模 `session-dee51d3a-0816-4065-bf51-16fe66ee793b`（本文件手写；明细是生成物，
见下「三处同口径」）。

**判据（任务原文）**：改完之后，**哪个可观测的数往哪边动？** 答得出 ⇒ 可接线；答不出 ⇒ 退回登记
（不许接线）；本批不可做 ⇒ 不适用（须给可复算谓词）。**三个态不许压成一个。**

## 一、汇总

**84 键逐条判读完成**：可接线 71 条、退回登记 9 条、不适用 4 条；其中**落点被挡 48 条**
（技能来源的键，方向答得出但当前接不上）。依据分级：正文直引 51 条、推断 23 条、谓词 10 条。

本任务**不写产品代码**：以下全部是判读，没有接线、没有改任何产品文件。

## 二、口径

### 1. 三态怎么判

- **可接线**＝能写出（量 → 方向 → 可观测量）三件齐。**注意它不等于「已核对过公式」**：
  依据＝推断的 23 条，接线前必须按实战读数复核；依据＝正文的 51 条也仍是「方向」结论，
  不含公式细节。
- **退回登记**＝方向答不出，且必须写清**试过哪几种读法**（第四列）。正确产出，不是失败。
- **不适用**＝本批不可做，各带一条**可复算谓词**（零值／派生／非量），脚本
  `tools/batch4_direction_checks.py` 能跑出同一个结论。

### 2. 落点为什么单列一栏（与任务原文的一处口径差别，请 PM 过目）

任务原文把「第二道闸结构上挡住」列为**不适用**的一种。实测：48 条被挡的技能键里，
挡因**都含「技能效果 other」**——`other` 就是「黑板里有键但没被解释」的那个箱子，
**挡因正是这些键没被解释**。把它们归进不适用，等于把本批该做的活划到范围外，所以我把
「落点」单列成一栏，并给出两套读数的条数：

- 口径甲（本表用的）：可接线 71／退回登记 9／不适用 4
- 口径乙（把「来源技能被挡」也算不适用）：可接线 23／退回登记 9／不适用 52

两套都对得上同一份明细，PM 若要按口径乙走，不必重跑，只需在渲染器里换判词。

### 3. 三处同口径

| 处 | 位置 | 形态 |
| --- | --- | --- |
| 明细 | `out/acceptance/batch4-direction-table.md`（84 行，逐键） | 生成物 |
| 括注 | 本文件第四、五节（退回登记 9 条、不适用 4 条**逐条重列**） | 手写 |
| 汇总 | 本文件第一节的四个数 | 手写，但**被脚本核** |

汇总不是手抄的自证：`python tools/batch4_direction_table.py --check-doc docs/batch4-direction-table.md`
会现算三态与落点的条数，与本节逐位比，不一致即 rc=1。

## 三、三条新事实（值得拍板）

### 事实 1：A 名单的「19/19 全部能进 Go」**不保证本批选出的键有落点**

A 名单的入选判据是「**至少一个**技能能进 Go」（`audit_coverage.port_reasons_best` 取理由最少的那次）。
逐技能实测（`out/acceptance/batch4-port-per-skill.txt`，39 行）：**10 位里每位恰好只有 1 个技能能进**，
且都是第 1 槽或通用技能（如耶拉只有 `skcom_atk_up[3]`）：

- 能进的 10 个技能的黑板键**全是已建模的**（`atk`、`atk_scale`、`attack_speed` 一类）——
  一条都不在本批 84 键里；
- 本批 84 键的来源**全部**是被挡的第 2/3 槽技能，或没有任何检测器的天赋/特性。

⇒ 结论：本批 48 条技能键的落点是**空的**，且空的理由就是它们自己没被解释。接它们＝先把机制建出来。

### 事实 2：「抵抗」在 Go 侧有实现有守卫，但**生产零调用点**

受益面最大的一条（权重 6：微风、寒檀、诺威尔、灵知、年、煌）是 `one_minus_status_resistance`。
`rios-sim/resist.go` 已经有 `resistHalf = 0.5`、`resistFactor`、`advanceStatus`（加速流逝，
不是砍半时长）、`palsyDecayInterval`，`resist_test.go` 有守卫。但 grep 全文：

- `advanceStatus(`／`resistFactor(` 的调用点只出现在**定义**与**测试**里；
- `palsyState.tick` 只在 `palsy_test.go` 里被调用。

⇒ 接这一条键，才是这条实现第一次进生产路径。**「有实现」与「有落点」是两个槽**。

### 事实 3：变体名撞通用词 ⇒ 同一天赋的两个分支被尺子分到两栏

`huang_t_1[lock].duration`／`[lock].min_hp_ratio` 在 keys1（本批），而同天赋的
`huang_t_1[heal].hp_ratio` **不在**——它被判「有人读」。实测 `"heal"` 是 `ak_tactic/` 里的
源码字面量（13 处，`ak_tactic/formula.py:261` 等描述编译层），所以那是**变体名撞通用词**造成的
**假清账**（与键名表 `RULED_FLAT_KEYS` 假清账同族，落在 `[xxx]` 形式上）。

对照：`lock`／`stack`／`high`／`bonus`／`target_timer` 都**不是**源码字面量，故本批这些变体键
没有被误清账（它们是真欠账）。这条可作为后端2 那条尺子改动的又一个判据实例。

### 附：同名不同义（接线方式的一条硬约束）

`min_hp_ratio`／`max_hp_ratio` 落在**三个不同天赋**里，指的是**三个不同主体的生命比例**
（家族手段＝目标、无声砥柱＝友军、鬼之架势＝自身），而且 `max_` 的极性**相反**：
家族手段 `max_hp_ratio = 0.2` 配的是**效果最大**端（`max_add_on_scale = 0.28`），
鬼之架势 `max_hp_ratio = 1.0` 配的是**效果最小**端（`max_atk = 0.0`）。

⇒ 这两条键**不能按键名全局接**，必须写成（来源天赋 × 键）对，并给这个槽补一个「主体」位。
两条键因此判**退回登记**。

## 四、退回登记 9 条（括注：试过哪几种读法）

| 键 | 试过的读法 | 为什么答不出 |
| --- | --- | --- |
| `min_hp_ratio` | 家族手段／无声砥柱／鬼之架势 三处 | 三处各指**不同主体**的生命比例，配对的效果键也不同 |
| `max_hp_ratio` | 家族手段／鬼之架势 两处 | 同上，且 `max_` 极性在两处相反 |
| `attack@trig_cnt`（蕾缪安） | ①瞄准 tick 上限 ②弹药/触发次数上限 | ①谓词成立（＝aim_duration/interval＝3.5/0.25＝14.0）；②与同黑板 `trigger_time＝7` 不符。两读法决定「与谁去重」不同 |
| `attack@finish_listener_duration` | ①技能结束后返回初始位置的时长 ②监听结束事件的窗口 | 动的是不同的量（位移轨迹 vs 技能结束时刻） |
| `attack@emit_offset` | ①落点相对锁定点的偏移 ②发射点相对自身的偏移 | 两读法**方向相反**（打偏致命中数下降 vs 不影响命中） |
| `duration_plus` | ①「延长至 25 秒」的那一段＝10 秒 ②另一段效果的持续秒数 | ①被谓词证伪：duration 15＋duration_plus 15＝30 ≠ enhance_duration 25 |
| `attack@base_atk_scale` | ①正常攻击段的倍率 ②技能 baseline 倍率 | 正文无对应句子；①下值 1.0 是恒等变换 |
| `mode_default` | ①中继器两种姿态的伤害倍率 ②攻击间隔模式代号 | 正文无对应句子，且同值不同键（`atk_scale`＝2.0 是另一条） |
| `mode_down` | 同上 | 同上 |

## 五、不适用 4 条（谓词）

| 键 | 子因 | 可复算谓词 |
| --- | --- | --- |
| `attack@prob_once` | 派生 | `prob_once＋prob_twice ＝ 0.8＋0.2 ＝ 1.0` 逐位成立 ⇒ 接线会与 `prob_twice` 重复计数 |
| `ep_damage_ratio_m` | 零值 | 该键在 `operator_talent` 的**全部 4 档**取值均为 0.0 |
| `ex_add_count` | 零值 | 该键在全部档位取值恒 0.0 |
| `skill_index` | 非量 | 值是选择器（该天赋作用于第 2 技能），本身不动任何可观测量 |

★ 注意两条**不是**零值键：`min_add_on_scale＝0.0`（另一端 0.28）、`max_atk`／
`max_magic_resistance＝0.0`（插值端点）——接线它们会改可观测量（满血端的加成从 0 变成非 0）。

## 六、未核（明确没查过的，不与「答不出」合并）

1. **公式细节**：所有「可接线」只答方向，不含公式。已知两处对不上，接线前必须先定：
   - `resistance_scale＝0.02`：`hp_ratio＝0.01` 的单位与「8%→15%」对不上；
   - `attack@ex_atk_scale`：量纲（每秒增量 vs 每 interval 增量）靠数值自洽推的。
2. **接线后的实战读数**：本表没有任何模拟器读数（未跑引擎），故不涉及 `RIOS_SIM_BIN`；
   依据＝推断的 23 条要用实战读数复核。
3. **未查别的干员**：同名键在**非 A 名单**干员上的读数没查（如 `min_hp_ratio` 第 5 位受益者
   赤冬/赫拉格的天赋），本表的「主体」结论只在 A 名单＋受益面范围内取证。
4. **`--cross` 与 `--json` 不能同时给**（`tools/audit_coverage.py:883` 提前 return），
   本表的键清单与权重取自 `--json out/acceptance/batch4-select3.json` 一族缓存，
   没有独立跑一遍 `--cross` 对账。

## 七、复算命令与身份

来源身份（跑这次读数时的实测值）：

| 件 | 身份 |
| --- | --- |
| 库 | `data/akdb.sqlite` sha16 `30e08f0da83b2ca9` |
| 范围表 | `data/ranges.json` sha16 `63ea8a90a89ce24c` |
| 扫描缓存 | `out/acceptance/batch4-scan3.json` sha16 `628c53ca369722de`（**HEAD 不可得**：扫描当时未记录） |
| 过闸缓存 | `out/acceptance/batch4-onlyport2.json` sha16 `b0e5fbcc88b5d71a`（原记录 head `8c0e039`） |
| 尺子 | `tools/audit_coverage.py` sha16 `467ca70b4e18e6aa`（后端2 在办，读数随其改动而变） |
| 树 | HEAD `6f6cfa0039bc7b800fa54c0b434460aeb9234fba`；`git status --porcelain --untracked-files=no` **空** ⇒ source_dirty＝无 |

```
# ① 复现 A 名单与 84 键（复用工具自己的 greedy_pick，不另写实现）
python tools\batch4_direction_probe.py --keys

# ② 落点（逐技能第二道闸）＋天赋逐档黑板与特性正文
python tools\batch4_direction_probe.py --ports
python tools\batch4_direction_probe.py --phases

# ③ 谓词（零值／派生／极性／变体名是否通用词）
python tools\batch4_direction_checks.py

# ④ 渲染方向表并核四个数
python tools\batch4_direction_table.py --check-doc docs\batch4-direction-table.md

# ⑤ 反向守卫：四个变异必须各自让对应守卫变红（控制组原样必须绿）
python tools\batch4_direction_table.py --selftest
```

上面前三条来自缓存，第 ④⑤ 条每次现算；`--check-doc`／`--selftest` 不通过即 rc=1。
`out/` 在 `.gitignore` 里（第 39 行），故**明细本身不入库**，靠命令 ④ 重生成；
入库的是本文件与 `tools/batch4_direction_*.py` 四个文件。

守卫清单（每条都配了会红的变异，实测 5/5）：

| 守卫 | 判什么 | 变异实测 |
| --- | --- | --- |
| ① | 判读表的键集合与探针算出的 84 键逐位相等 | 删一行 ⇒ rc=1 |
| ② | 三态自洽（且非法态要被报出来，不许把守卫变成崩溃） | 造一个非法态 ⇒ rc=1 |
| ③ | 文档汇总＝现算值 | 改文档里的数 ⇒ rc=1 |
| ④ | 技能来源的行必须判「挡」（落点不许从散文里猜） | 判成「通」⇒ rc=1 |

## 八、我做的与没做的

- 做了：84 键逐条判读（量／方向／可观测量／依据分级）、落点逐技能表、9 条谓词的可执行化、
  渲染器、四条守卫（键集合逐位相等／三态自洽／文档汇总＝现算／落点可算）与反向守卫自测（5/5）。
- 没做：**没写任何产品代码**、没接线、没动 `tools/audit_coverage.py`（后端2 在办）、
  没动 `rios-sim/mech/`（怀黍离补齐在办）。
- 待 PM 裁：落点单列（口径甲/乙）；`attack@s2_limited_stack_cnt` 这类**条件依赖被挡技能**的键
  算不算「无落点」；`huang_t_1[heal]` 那类变体名假清账要不要进后端2 的报表列。
