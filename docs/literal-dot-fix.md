# 尺子修复：`_LITERAL` 补点号（第六类「无人读」的前后对照留痕）

**手写文档**（不是生成物）。写它的会话：RIOS后端2（`session-37b2c3e2-6993-4a98-a7d2-5f09d62088a2`）。
依据：PM 裁定 `msg-mu8ur4g8-dq`（①先修尺子并重跑 ②再按乙做 `chain.*` 骨架 ③甲押后）。

**身份（缺一即「身份未知」）**

| 项 | 改前 | 改后 |
| --- | --- | --- |
| 尺子 `tools/audit_coverage.py` | git blob `43637d52d016`（当时 HEAD blob `f210a4a3e37e`） | git blob `2f1835073377`（HEAD blob `f857bcff642d`） |
| 所属树 HEAD | `6fd4693` | `9273e1d` |
| 输入库 | `data/akdb.sqlite` `30e08f0da83b2ca9`（与验收 §头 ident 一致） | 同左 |
| 范围表 | `data/ranges.json` `63ea8a90a89ce24c` | 同左 |

> 旧读数**原样留在验收的产物里**（`out/acceptance/batch4-scan2.json` 04:31:56、`batch4-onlyport.json` 04:32:19，旧尺子），本文**没有覆盖**它们；新读数落在 `out/backend2-b1/*-after-dot.*`。

---

## 一、修的是什么（一行字符类）

```python
# 旧
_LITERAL = re.compile(r"""["']([A-Za-z_@$][A-Za-z0-9_@$]*)["']""")
# 新（只加了 `.`）
_LITERAL = re.compile(r"""["']([A-Za-z_@$][A-Za-z0-9_@$.]*)["']""")
```

原注释块按本仓习惯**在行内续写**了理由与两个读数（含「仍未收 `[`/`]`」的边界），见 `tools/audit_coverage.py:41-60`。

**修前先说清它为什么是尺子的毛病**（两个读数合起来才叫证明，PM 确认过这个写法）：

1. 旧尺子从 `ak_tactic/**` 全部文本提出 **2396 个字面量，含点的 0 个** ⇒ 它**必然**看不见任何含点键；
2. 补点号后 **2474 个（+78）**，**丢失 0**，且**新增的 78 个全部含点**（不变式，程序断言「新增的必须全部含点」成立）。

**合成反例（敏感性）**：`"attack@chain.max_target"` —— 旧尺子提出 `[]`，新尺子提出 `['attack@chain.max_target']`。
**真跑过**（不是只 py_compile）：加载改后的模块，`source_literals()` 实测 2474、其中含点 78。

---

## 二、重跑读数（同口径四格，**不许跨行并列**）

| 口径 | 旧尺子 | 新尺子 | 差 |
| --- | --- | --- | --- |
| 全库行空间（**431 位**）类 1 键 | 599 | **594** | −5 |
| 全库类 1 需求对 | 773 | **761** | −12 |
| 过闸行空间（**169 位**）类 1 键 | 213 | **211** | −2 |
| 过闸类 1 需求对 | 253 | **251** | −2 |
| A 名单（10 位） | `demetr,kjera,lemuen,veen,vvana,slent2,huang,etlchi,hsgma2,aphris` | **同 10 位、逐位相同** | 0 |
| A 名单类 1 键并集 | 84 | **84** | **0（逐键相同）** |

两处独立复算对上了同一个差：我在改文件**之前**用两把正则对同一份文本预量，得「翻转 5 键 / 12 需求对」；改完后工具自己的重跑给出全库 599→594、773→761（**−5 键 / −12 对**），逐位一致。

**命令（可复现，四条）**

```powershell
python tools/audit_coverage.py --select --batch 10 --cache out/backend2-b1/scan-after-dot.json --json out/backend2-b1/select-after-dot.json
python tools/audit_coverage.py --select --batch 10 --only-port --from-cache out/backend2-b1/scan-after-dot.json --json out/backend2-b1/select-onlyport-after-dot.json
python tools/audit_coverage.py --select --batch 10 --only-port --cross --from-cache out/backend2-b1/scan-after-dot.json > out/backend2-b1/select-onlyport-cross-after-dot.log
python tools/coverage_table.py --plane 干员 > out/backend2-b1/coverage-干员-after-dot.txt
```

---

## 三、翻转的 5 键 / 12 对，分成**几类**：一类

| 键 | 需要它的干员数（全库） | 唯一的字面量出现处 | 性质 |
| --- | --- | --- | --- |
| `attack@chain.extra_value` | 3 | `ak_tactic/formula.py:123` | 键名表成员 |
| `attack@chain.max_target` | 6 | `ak_tactic/formula.py:142` | 键名表成员 |
| `blkngt_s_2.duration` | 1 | `ak_tactic/formula.py:140` | 键名表成员 |
| `failure.stun` | 1 | `ak_tactic/formula.py:132` | 键名表成员 |
| `success.silence` | 1 | `ak_tactic/formula.py:132` | 键名表成员 |

五处**全部**落在同一张表：`ak_tactic/formula.py:119-145` 的 `RULED_FLAT_KEYS`（`frozenset[str]`）——公式编译器用来做「量纲判不出、由裁定定案」的**键名表**，注释自己写着「正因如此才要按**原键**比对」。**它不读值**，是名字表，**不是消费者**。

过闸行空间里那 −2 对来自 **`char_4071_peper`（明椒）** 的 `attack@chain.extra_value` + `attack@chain.max_target`（两处都在名字表里）。

---

## 四、结论三句（与 PM 的预期不同，要点在这里）

1. **修尺子没有多出任何真消费点**：5 处全是名字表，没有一处是真读值。
2. ★ 它反而把这 5 键从「无人读」栏里**划掉了** ⇒ 这是**假清账**（过闸 2 对、全库 12 对）。**「出现过」不等于「被消费」**（关键记忆 `1bd38acb`：注释／名字表被当证据）。
3. 修尺子的**正面价值**是去掉**结构性盲区**：改之前，**任何**含点键都不可能被判「有人读」——哪怕将来真有人读它，也永远看不见。这一点与「这 5 键有没有人读」是两件事。

**⇒ 待裁定（选项 + 代价）**

* **甲「加排除」**：在 `source_literals()` 里把「只出现在集合/字典字面量里的键名」排除（判别式：该字面量所在行没有任何调用或属性访问）。5 键退回「无人读」，读数不掺假。代价：≈10 行 + 重跑一次（≈6 min）。
* **乙「不加」**：接受这 5 键被算作「有人读」。代价 0，但「无人读」这一列从此少 5 键/12 对，引用它时必须同时带这个例外。
* **丙「只改报表」**：`source_literals()` 不动，在表里加一列「**仅名字表提到**」把 5 键显式标出。代价：≈10 行（报表侧），读数三态可分。

---

## 五、未修的（不许读宽）

`[` / `]` **仍不在字符类** ⇒ 含方括号的键**依旧提不出来**。已知例子（仅列出，**未量、未修**）：`blackd_s_2[period].trig_cnt`、`peacok_s_1[crit].atk_scale`、`chen3_s2[respawn_buff].prob`。它们是**第七类的候选**，不是结论；本轮没做逐键判定。

---

## 六、下游连带（我自己的清单）

`docs/two-spelling-audit.md`（我那份生成物）用同一把尺子 ⇒ 已按原样重生成（`--by RIOS后端2 --sample-check 16`），与入库版本的差**只有 3 行**：

* 2 行元数据（HEAD 与尺子 blob 变了，属正常）；
* 1 行 `chain.max_target` 族：**族的欠账侧写法从 2 种变 1 种**——`attack@chain.max_target` 被名字表清掉，只剩 `chain.max_target`；裁定文字改为「**零消费者**——但有一处字面量（`formula.py:142` 的名字表）」，与小节的其余「无读点」C 档家族**区分开**（那几家真的一处字面量都没有）。档位仍是 **C**（判据不是「有没有字面量」，而是「有没有人读值」）。

---

## 七、本轮踩到的三个坑（都留在这儿，省下一个人踩）

1. ★ **`| Select-Object -First N` 会掐断上游进程**：我用它截 python 的输出，进程被杀 ⇒ **JSON 根本没写盘**，而屏幕上照样有半截正常输出。信号是 `rc=`（空）。⇒ 要落盘的命令，一律 `> file 2>&1` 再读文件。
2. **`--cross` 与 `--json` 不能同时要**：`tools/audit_coverage.py:883-884` 在 `a.cross` 时 `return cross_mode(a)`，**提前返回**，走不到 `:815` 的写盘。⇒ 分成两次跑。
3. **`keys1` 是「筛后」集合**：拿**新**扫描的 `keys1` 去问「谁需要这个键」，答案必然是 0（那些键已经被清出去了）。要问「谁需要」得用**未筛的 need 集合**或旧扫描。我第一版探针正是这么读错的（读成「全库 0 位」，与上一轮实测的 3/6 位矛盾，才发现）。

---

## 八、丙落地：报表加第二态 `name_table_only`（提交 `96a4e1c`）

**裁定**（PM `msg-mu8v78xa-e3`）：走**丙**——「仅名字表提到」是**独立第三态**，不许并进「有人读」、也不许并进「无人读」；**不动 `source_literals()`**；新列要写明**是判据不是事实**并在脚注写出判别式原文；三态计数**分别打印**。

**判据（启发式，原文）**：该字面量**所在行去掉字符串与注释后只剩分隔符**（无调用 `(`、无属性访问 `.`、无下标 `[`）。
`name_table_only(key)` 三条件**同时**成立才算：`is_read` 全量认它 ／ 名字表那一份也认它 ／ **去掉名字表就不认**。第三条是关键——同时有真消费点的键**不算**这一态。

**读数（同一提交、同一把尺子、同一份源码；四行各有各的分母，不许跨行并列）**

| 口径 | 第一道（分类器认不了） | 第二道（真没人读） | **第二态（仅名字表提到）** |
| --- | --- | --- | --- |
| 普查（全体名册） | 412 种键、842 次 | 228 种键、270 次 | **116 种键、1153 位次** |
| `--select` 全库（**431 位**） | — | — | **185 种键、2210 位次** |
| `--select` 过闸（**169 位**） | — | — | **95 种键、802 位次** |

* **不变量（加列不改数）**：加这一列前后，第一道/第二道的数**逐位不变**（412/842、228/270）——因为 `source_literals()` 与 `is_read()` 一字未动。
* 我第一版把「全库」印成了过闸数（工具里 `data` 在算行空间时已被收窄）⇒ 独立复算当场对不上（185/2210 对印出的 95/802），已修：收窄**前**留 `data_all` 快照，两档分报。
* select 的 JSON 增字段 `name_table_only`：`keys` / `pairs` / `gate_keys` / `gate_pairs` / `判据`。

**这个判据的假阳面（实测，不是猜）**：让它合格的那些行，最内层括号分布＝`[` 537 处、`{` 146 处、`(` 52 处、顶层 78 处。
其中 **52 处落在 `(` 组里**——形态是「调用实参一行一个字面量」，与「多行集合的成员行」在**行**这一层长得一样 ⇒ **这一类会被误判成名字表**。另有已知窄口：**单行**写的集合/字典（键名与赋值同行）**不会**被判为名字表，会落回「真有人读」。两条都写进了报表输出与源码注释。

**两个自伤（都当场红，记下来省下一个人踩）**

1. **`d["keys"]` 是筛后集合**：拿它数第二态恒得 **0**（被名字表清掉的键早已不在里面）。要用摊平键集 `kv`。
2. **复用了别人的 `k`**：`select_mode` 里 `k = a.batch` 是切片上界，我的 `for k in ...` 把它覆盖成字符串 ⇒ 崩在 `[:k]`（`TypeError: slice indices must be integers`）。改名 `_key`。

**复现**

```powershell
python tools/audit_coverage.py --select --batch 10 --only-port --from-cache out/backend2-b1/scan-after-dot.json --json out/backend2-b1/select-3state.json
python tools/audit_coverage.py --all --top 3
```

**★ 两条不变量，缺一不可（PM 补强 `msg-mu8x41vn-et`）**

1. **值的不变量**：加列**只该加列**——第一道/第二道逐位不变（412/842、228/270）。
2. **档的不变量**：**加了开关之后，每一档都要真跑一次**，**默认档（不带开关）最危险**。
   ⇒ 这条不是假设：`data_all` 只绑在 `--only-port` 分支里 ⇒ **默认档 `UnboundLocalError`**，而我两轮自测**全绕开了默认档**（一次带开关、一次跑 `--all` 走的是普查路径），由验收抓到（`af1e8a6`）。
   ⇒ **「值不变」这条即使全绿也拦不住这次的崩：它查的是数，崩的是路。**

**档矩阵（五档，2026-09-20 修后逐档真跑，逐档看 rc）**

| 档 | rc | 第一道 | 第二道 | 第二态 |
| --- | --- | --- | --- | --- |
| 普查·默认（**E2 名册**） | **0** | 175 种键/266 次 | 49 种键/52 次 | 68 种键/289 位次 |
| 普查·`--all` | **0** | 412 种键/842 次 | 228 种键/270 次 | 116 种键/1153 位次 |
| `--select`·默认（无开关） | **0** | — | — | 全库 **185**/2210；过闸 **95**/802 |
| `--select --only-port` | **0** | — | — | 全库 **185**/2210；过闸 **95**/802 |
| `--select --no-port` | **0** | — | — | 全库 **185**/2210；过闸 **95**/802 |

* 普查那两行**不是同一个分母**（默认档只数 E2 名册、`--all` 数全体名册）⇒ **不许并列比较**；select 三档的第二态读数**逐位一致**，说明这一列**不随覆盖行空间漂移**（这与设计一致：第二态按收窄前的全库快照算）。
* 命令矩阵（可复制执行，逐条看 rc）：

```powershell
python tools/audit_coverage.py                      # 普查·默认
python tools/audit_coverage.py --all                # 普查·全体
python tools/audit_coverage.py --select --batch 10 --from-cache <cache>              # 默认档
python tools/audit_coverage.py --select --batch 10 --only-port --from-cache <cache>  # 过闸档
python tools/audit_coverage.py --select --batch 10 --no-port   --from-cache <cache>  # 关闸档
```

**协作留痕**：`96a4e1c` 这一笔**同时带上了验收**在同一文件里的未提交补丁（`ident_of()` 加 `head` + `src_dirty`、`import subprocess`）——正是「来源三件套缺树身份」的补法，属他同意下的合并；提交后该文件工作区干净。验收 05:02 报我「文件 RC=1、`:719 IndentationError`」**属实**，那是我改到一半的中间态（已修），他的文档重生成用的是坏之前的落盘产物，读数不受影响。
