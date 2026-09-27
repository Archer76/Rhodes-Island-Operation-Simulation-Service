#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：候选生成（搜索层的第一层 · 几何剪枝）。

## 它为什么存在

Go 的 `candidates` 命令（`rios-sim/candidates.go`，分发在 `rios-sim/main.go:867`）
复刻了 `ak_tactic/search.py:48-187`（`Candidate` / `candidates_for` / `_range_cells`）。
在此之前候选生成**只有「实现自洽」的判据**——Go 侧 `candidates_test.go`、
Python 侧 `tools/check_search.py`——**没有一条「与权威逐字段一致」的判据**。
两者各自都自洽，看不见分叉：这正是本仓记过的形状（两把相同的尺子互证）。

搜索层的下游（beam 搜索）吃的就是这几十条候选，**候选的顺序一错，
beam 切出来的状态就跟着错**。所以本套把「顺序」也当成被判的字段之一。

## 对的是什么（逐字段）

`rows` 的十个字段全比：`operator` / `char_id` / `position` / `direction` /
`skill` / `mastery` / `dwell` / `visits` / `value` / `cells`。

* `value = dwell × 攻击力`（面板 `total["atk"]`）——Go 侧 `atkOf()` 明写「类型不认识
  就报错，不兜底」（第一版用 `asF` 静默取 0，于是 `value` 恒 0、排序整个失效，
  而候选条数／dwell／visits 全是对的：最难发现的一类假绿）。判据把 `value`
  **按 dwell 的同一口径比**（浮点逐位相等，累加序那一处按同一个相对容差 ——
  `value` 是 `dwell` 的派生量，**容差不许只开给 dwell 一栏**），另有一条自检
  要求它确实是 `dwell ×` 权威自己拿到的那个 atk。
* `cells` 在 Python 那边是 `frozenset` ⇒ **按集合比，不逐元素比顺序**
  （Go 侧排过序只是为了输出确定）。
* `dwell` / `value` 是浮点 ⇒ 默认**精确相等**（本仓既有的口径：
  `check_stagepath_go.py` 明写「比的是 float 精确相等，加了容差就再也看不见
  那 1 ulp」；`check_stage_go.py` 的 `diff()` 也是 `!=`）。两侧都是同一个式子
  （`eta.py:379-384` 与 `arrivals.go:354-363`，都按 `enter` 稳定排序后的 visit 序
  `total += hi - lo`）⇒ 在**同一个累加序**下逐位相等是可达的，不是苛求。

  ★ **唯一的例外是「累加序」那一处已登记的分歧**（2026-09-27 博士裁定；机制与
  读数见下面 ③ 那一节与 `FLOAT_REL_TOL`）：两侧的累加序**本来就不同**（Python 按
  `frozenset` 的哈希序、Go 按 (x, y) 排序），所以那两栏**按相对容差比**。
  ⚠ 那个口子**只对这两栏**开，且容差**随 visit 条数增长**（见 `_float_tol`）——
  它不是「浮点一律放水」：超容差照旧计入 `bad` 并印出条数。

## 顺序（「稳定排序」那件事的判据）

* 每位干员内部：`local.sort(key=lambda c: -c.value)` 是**稳定**的 ⇒ 同价值保持
  插入序（插入序 = `melee_spots + ranged_spots` 的行主序 × `DIRECTIONS` 的枚举序）；
* 全体：`out.sort(key=lambda c: -c.value)` 同样稳定 ⇒ 同价值保持**干员出现序**。

Go 侧一律 `sort.SliceStable`。判据的做法是**逐索引比**（不是按集合比）：
索引 i 的十栏都必须对上，所以顺序一错、或平局取错了谁，都会当场显形；
另有一条专门的「顺序」判定，只有当两侧**多重集相同而序列不同**时才报它
（那种时候字段级比较全绿、只有顺序变了——它必须自己长一条结论出来）。

## ★ 行使计数：两个来源

`covered` 那 14 个计数是「这一层把候选从多少压到了多少」的眼睛，它是
**被测方自报**的。判据另有一份**尺子**：`py_covered()` 用 Python 自己的原语
（`stage.map.melee_spots` / `range_provider` / `index.dwell`）把同一批空间
独立走一遍数出来。两边不等 ⇒ 判红（与 `check_stagepath_go.py` 的
`py_route_plan_coverage` 同一形状：计数器本身也是一个断言）。

★ 四条**结构零**分支（**每跑一次都重新量**，不是写死一句话）：

| 分支 | 为什么在现数据上不可达 | 守卫 |
|---|---|---|
| `no_char_id` | 两个名册读取器（`plan.py:221-223` 的 `if not name or not cid: continue` 与 Go 的读名册口）都**丢掉**没有可用 id 的行 ⇒ 表里不可能有 `char_id` 为空的条目 | 合成名册里那一行必须落进 `entry_missing` 而不是 `no_char_id`；非 0 即红（红的意思是「该补样本了」） |
| `range_missing` | 每个用到的 `rangeId` 都在 `range_table.json` 里 | 全程必须为 0；非 0 即红 |
| `empty_range` | 每条范围至少含自身格 `(0,0)`（`gamedata/range.py:18-20`） | 同上 |
| `atk_missing` | 面板 `total["atk"]` 恒有值 | 同上 |

⚠ 后三条**两侧口径不同**，登记在此以免将来读错：Python 的 `_range_cells` 把
「范围代号查不到」吞成**空集合**，而 `RangeProvider.__call__` 在查不到时代码是
**退回直线四格**（`battle/range.py:135-139`）——Go 那边是 `range_missing` 直接
跳过。三者在现数据上都是 0，所以这条口径差**没有被行使**；一旦非 0，
本判据会先把它报成「结构零变成可达」而不是「判据红」，处置是补一份样本。

## `per_op <= 0`：★ 2026-09-27 已裁定 ⇒ 从「登记分歧」改成「两侧一致」的断言

**`per_op <= 0`（六个候补位）。**
历史上这里是一处**登记分歧**：引擎的契约是「0 ⇒ 缺省 6」（`candidates.go:217-220`），
而 Python 的 `candidates_for` 显式收下 0 会**每位只留 1 条**
（`if len(kept) >= per_op: break` 在 0 上立刻成立；-1 同理）。
**博士 2026-09-27 裁定：六个候补位** —— `per_op <= 0`（没给／给 0／给负数）
在**两侧一律按 6**。Python 入口已并到 `DEFAULT_PER_OP`（`ak_tactic/search.py`），
引擎侧本来就是 `defaultPerOp`。
⇒ 判据这一支现在是**断言**：`per_op=0` 与 `per_op=6` 各问一次两侧，
要求**候选条数／kept／顺序／逐字段**四个读数两两相等；并配一条**负对照**
（把 Python 的旧行为装回去，这条断言必须当场判红）。
⚠ 那一支的浮点**不吃** `FLOAT_REL_TOL`：它比的是同一位实现的两个输入，
累加序没变 ⇒ 精确相等在这里是可达的。
★ 冻结档**不必重录**：它复用的是**已经冻着**的 `per_op=6` 那一份期望值
（裁定的内容本身就是「这两个输入同解」，由断言现算，不另存答案）。

## 两条坑的处置（本仓踩过，写在这里防止再犯）

**① Python 的关卡加载器会按需从镜像下载。** `GameDataSource` 在本地缓存缺
文件时**联网补齐**并落进 `data/gamedata/map.ark-nights.com/levels/`。于是
「Go 取不到、Python 取到了」有两种**完全不同**的因：数据本来是缺的（Python
顺手补了）／代码分叉了。压成一个「判据红」＝让人去查一个不存在的分叉。
处置有三层：

* 取证范围来自 `cached_levels()`（索引里**缓存文件在场**的那些），
  `GB.level_inputs()` 还会再过一道「缓存文件不在场就大声失败」⇒ 批次里
  **不可能**有「数据缺」的关，本坑**按构造避开**；
* 仍然留了防御支：Go 失败时**也去调一次 Python**，并**在调用前后各量一次
  该关缓存文件在不在**——两边都失败记 `数据缺`（具名印出，**不算红**）、
  Python 成了而文件是**这一次**才出现的记 `Python 顺手补齐`（**不算红**）、
  文件本来就在场而只有 Go 失败 ⇒ **判红**（这才是真分叉）；
* 冻结档下跑不动 Python，那时 Go 失败直接判红（冻的那批里有关卡 ⇒ 录基线时
  数据是在的），**具名**说明「冻结档无法分辨数据缺与分叉」。

**② 引擎的 gamedata 路径是相对 cwd 拼的。** `DataRoot()`（`stage.go:167`）
在没有 `RIOS_DATA` 时返回 `filepath.Join("data", "gamedata")`。所以判据
**两件都做**：给 Go 子进程 `cwd=<本仓根>`（worktree 挂了 data junction 就行），
**并且**显式设 `RIOS_DATA=<本仓根>/data/gamedata`。少任何一件，
换一台机器或换一个 cwd 就会得到「读关卡索引失败」——而它**长得像判据红**。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 `candidates_for`，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/候选生成.json`，
  **不 import `ak_tactic`**。

★ **输入身份**：键 `("candidates", 用例名, 关卡 id, 该关缓存内容 sha16, 名册文件 sha16)`
＋ 每次跑先 `G.coverage("candidates", …)` 对账。名册那份 sha 不能省——期望值是
名册的**函数**（`potential` / `module` / `module_level` 都进攻击力），只记关卡
会在夹具被改之后拿一份旧名册的期望值去比新名册。

## 反向守卫（`--mutate`）

十二处**互相独立**的变异，各自必须「注入过 ＋ 判红过」，缺一不算成立。
★ 每处落在**不同的一条候选**上，所以**一关之内**就能全部注入完 ——
这一点是必需的：`check_go_all --selfcheck` 给「要喂清单」的套只喂 `lvls[:1]`。

| 变异 | 打在哪 | 证明什么 |
|---|---|---|
| 条数 | Go 的 rows 砍掉最后一条 | 条数比较是活的 |
| dwell 末位 | 第 i 条 `dwell` **加 1 ulp** | dwell **逐位**比（贴边界，且**没被**累加序那个容差吃掉） |
| value 末位 | 第 i 条 `value` **加 1 ulp** | value 是**比**的，不是被重算掉的（容差也没吃掉它） |
| position | 第 i 条落点 x+1 | 身份键变了 ⇒ 报「候选集合不同」 |
| direction | 第 i 条朝向换一个 | 同上，另一条键 |
| skill | 第 i 条技能槽 +1 | 技能槽那一栏是活的 |
| visits | 第 i 条 visits +1 | 进入次数那一栏是活的（整数栏**没有容差**） |
| cells 少一格 | 第 i 条 `cells` 少一个格 | **按集合比**且集合比较是活的 |
| 同价值两条的顺序 | 交换一对**同价值**的相邻候选 | 顺序那一栏是活的（字段全等、只有序变） |
| covered 计数 | Go 自报的 `visits_zero` +1 | 行使计数比较是活的（与尺子那一份独立） |
| 期望值 dwell 末位 | **Python 的**期望值 `dwell` 加 1 ulp | 「故意改一个期望值必须判红」 |
| per_op<=0 负对照 | 把 Python 的 `per_op<=0` 装回旧行为（**每位只留 1 条**） | 「`per_op=0` 与 `per_op=6` 同解」那条断言是活的（ISSUE-③ 的后半） |

## ★ 这一段对拍的实际结论（一处**已登记**分歧、一处**未裁定**）

判据跑起来会红，红的是**一处**，不是「判据自己写错」：

**① 天赋面板攻击力倍率（已登记 ⇒ 口径统一后不比红）。**
Go 把天赋的面板倍率折进了 `total`（`rios-sim/talentpanel.go`），Python 一个都不折
（2026-09-24 裁定，原文在 `tools/check_operator_go.py:788-799`）。
`value = dwell × unit.atk` ⇒ 这一处原样传到候选的价值与排序上。
实测 main_01-07：能天使 py 567 / Go 612（+8%）、焰狐龙梓兰 py 872 / Go 1003（+15%）、
赤刃明霄陈 py 698 / Go 810（+16%）；没有这类天赋的（星熊／泥岩／阿米娅）逐位相同。
处置照那一套：比例取自 Go 自己的 `opstats`，把两边统一到同一个量再比，
**除不掉仍报红**（登记不等于放水）。

**② 自身格（**仍未裁定 ⇒ 照旧判红**）。**
`excel/range_table.json` 73 个范围代号里有 **9 个**的 `grids` **不含自身格 `(0,0)`**：
`1-5`、`2-7`、`3-16`、`4-13`、`4-3`、`4-4`、`4-5`、`4-6`、`4-7`。
Python 的 `RangeProvider.__call__`（`battle/range.py:140-141`）在 `block_of(...) > 0`
时**补上 `(0,0)`**，而 `Verifier.range_provider` 传的是 `block_of=lambda c, e: 1`
（`verify.py:214-215`）⇒ **每一位干员都补**；Go 的 `candidates.go` 直接
`Footprint(base, d, x, y)`，依赖 `range.go:18-20` 那句「自身格 (0,0) 已经在
grids 里」——那句话对这 9 个代号**不成立**。
影响面：460 位干员里 **9 位**（铅踝／灰毫／火哨／熔泉／埃拉托／矩／早露／提丰／号角）。
后果**不止差一个格**：实测 `main_02-01` 上号角与火哨因此**在 `per_op` 里留下了
不同的落位**（判据报「选出来的候选集合不同」）——也就是会改变搜索的输入。
本判据把它**原样判红**（未裁定的事不许由判据自己拍板），并在读数里给出根因原文。
★ 这条**另有子代理在改**，本套这边一个字都不动它。

**③ `dwell` 的累加序（★ 2026-09-27 博士裁定：按登记走，不修产品 ⇒ 不再是判红）。**
`ArrivalIndex.dwell` 的累加序 = visit 的**拼接序**；两侧都按 `enter` **稳定**排序，
可一旦有多条 visit 的 `enter` 相等，稳定排序保留的就是拼接序，而拼接序由
**格集合的迭代序**决定：Python 的 `_range_cells` 返回 `frozenset`（哈希序），
Go 的 `candidates.go` 把格去重后**按 (x, y) 排序**。⇒ 浮点累加结果逐位不同。
实测（同一格集合、两种迭代序各累加一遍）：
`easy_10-11` 阿米娅 (6,1) Down `frozenset=434.14285714285671` / 排序 `=434.1428571428566`；
`act31side_ex08` 能天使 (7,3) Left `frozenset=854.91414134972536` / 排序 `=854.91414134972513`。
⇒ `candidates.go` 文件头那句「`frozenset` ⇒ 顺序无意义」对**浮点累加**不成立。

**处置（登记口径，逐条写死在这里）**：

* **容差用相对，不用绝对**。理由：这一处的**绝对**差随 visit 条数增长（同一个格
  上叠几千条 visit 时能累到几千 ulp 量级），而承载它的 `dwell` 本身也同尺度地
  变大 —— 换成 `abs <= 1e-9` 这种绝对口径，等于把「大 dwell 的小相对漂移」和
  「小 dwell 的大相对漂移」判成同一件事，两头都会看错。相对差是本征稳定的量；
  本次跑出来的最大相对差（读数里现印）就是这条口径的实证。
* 容差**随 visit 条数线性放大**：`FLOAT_REL_TOL × max(1, visits)`（见 `_float_tol`）。
  这不是随手乘的系数，它正是「n 项求和的累加序差」的误差量级；乘法让它对
  visit 特别多的格也留得住余量，对 visit 少的格则收得很紧。
* **开口只在「`cells` 完全相同」时成立**。登记的就是「同一个格集合、两种迭代序」
  那一条；`cells` 都不同了，浮点差就不再能用累加序解释 ⇒ 照旧判红。
  这条范围限制是**故意的**：它让「自身格」那一处仍然占着红（不会被容差收掉），
  也让「将来出现一个大的数值改动」照旧判红。
* **超容差照旧判红，并且必须印出最大相对差与超出条数** —— 登记不等于不看不报。
  读数里超容差与「收下」分开记，且超容差再按 `cells` 相同／不同拆开，
  免得「容差收不下」与「不在登记范围」被读成同一件事。
* **`value` 与 `dwell` 同一条口径**。`value = dwell × 攻击力` ⇒ dwell 的 ulp 差会
  **原样派生到 value**；只给 dwell 开口会让红从一栏挪到另一栏（假绿）。
* 两侧读数的**真值差**（`frozenset` 与排序两种累加序）已由纯 Python 复算证死，
  不依赖本判据自己：`frozenset=434.14285714285671` / `排序=434.1428571428566`。

## ★ 冻结模式的键形状（**踩过一次，写在这里**）

`freeze_baseline.Channel.coverage()` 的口径是「`key[1:]` 就是这个对象的身份」。
本套的键是 `("candidates:<用例名>", 关卡, 关卡内容 sha16, 名册内容 sha16)` ——
用例名与名册 sha **都必须落在 `key[1:]` 里**，`live` 也要给同形的四元组。
第一版把用例名放在 `key[1]`、关卡放在 `key[2]`，于是 `key[1:]`（`("main", 关卡, …)`）
与 `live`（`(关卡, sha)`）**求交出 0**，冻结档静默读到「主对拍 0 关」。
★ 它**没有静默变绿**：末端的「`visits_zero` 一例都没走到 ⇒ 判红」守卫当场拦下。

用法:
    python tools\\check_candidates_go.py                      # 缺省：main_01-07
    python tools\\check_candidates_go.py <关卡…>              # 逐关（总入口喂缓存清单）
    python tools\\check_candidates_go.py main_01-07 --mutate  # 反向守卫
    python tools\\freeze_baseline.py --record 候选生成        # 录/重录
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace",
                       line_buffering=True)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
ROSTER = ROOT / "fixtures" / "roster_max_modelled.json"
#: 名册路径不存在那一支用的**固定**路径（每次跑都一样 ⇒ 键稳定；先断言它真的不在）。
ABSENT_ROSTER = ROOT / "fixtures" / "__no_such_roster__.json"

DIRECTIONS = ("Right", "Left", "Up", "Down")

#: Go 的 `CandidateStats` 的键表（顺序照结构体）。**多一个少一个都要红**：
#: 它是判据与引擎之间的一份契约，静默少一栏就是少一栏的覆盖。
COVER_KEYS = ("operators", "entry_missing", "no_char_id", "unit_failed",
              "atk_missing", "melee_ops", "ranged_ops", "positions_tried",
              "not_in_spots", "range_missing", "empty_range", "visits_zero",
              "kept", "all_candidates")

ROW_FIELDS = ("operator", "char_id", "position", "direction", "skill",
              "mastery", "dwell", "visits", "value", "cells")

#: `rows` 里那两栏浮点。**逐位比，不加容差**（见文件头）。
FLOAT_FIELDS = ("dwell", "value")

#: 主对拍的名单。★ 最后一个名字**故意不在名册里** —— `entry_missing`
#: 这条剪枝分支在真实名册上永远走不到，而「走不到」与「没写」必须长得不一样。
MISSING_OP = "名册里没有的人"
MAIN_OPS = ["能天使", "星熊", "泥岩", "阿米娅", "焰狐龙梓兰", "赤刃明霄陈",
            MISSING_OP]

#: 合成名册：真夹具上走不到的两条「名册侧」分支。
#: `查无此人` 的 char_id 不在 character_table ⇒ 两侧的练度折算都要失败
#: （`unit_failed`）；`幽灵干员` 没有可用 id ⇒ 两个读取器都**丢掉**它
#: （⇒ 落进 `entry_missing`，且 `no_char_id` 必须仍是 0）。
SYN_ROSTER_ROWS = [
    {"id": "char_103_angel", "name": "能天使", "elite": 2, "level": 90,
     "potential": 6},
    {"id": "char_999999_nobody", "name": "查无此人", "elite": 2, "level": 90,
     "potential": 6},
    {"id": "", "name": "幽灵干员"},
]
SYN_OPS = ["能天使", "查无此人", "幽灵干员", MISSING_OP]

#: ★ **自身格分歧的取证名单**（见 `compare_case` 里那一支与文件头）。
#:
#: `excel/range_table.json` 73 个范围代号里有 **9 个**的 `grids` **不含自身格
#: `(0,0)`**：`1-5`、`2-7`、`3-16`、`4-13`、`4-3`、`4-4`、`4-5`、`4-6`、`4-7`。
#: 而 Python 的 `RangeProvider.__call__`（`battle/range.py:140-141`）在
#: `block_of(char_id, elite) > 0` 时会**补上 `(0,0)`**，`Verifier.range_provider`
#: 传的又是 `block_of=lambda c, e: 1`（`verify.py:214-215`）⇒ **每一位干员都补**。
#: Go 的 `Footprint` 不补，它依赖 `range.go:18-20` 那句「自身格 (0,0) 已经在
#: grids 里」——那句话对这 9 个代号**不成立**。
#:
#: 全表 460 位干员里命中这 9 个代号的正好 **9 位**，名单就是下面这份。
SELFCELL_OPS = [
    ("铅踝", "char_4062_totter", 70), ("灰毫", "char_431_ashlok", 80),
    ("火哨", "char_493_firwhl", 80), ("熔泉", "char_363_toddi", 80),
    ("埃拉托", "char_4043_erato", 80), ("矩", "char_4221_ju", 80),
    ("早露", "char_197_poca", 90), ("提丰", "char_2012_typhon", 90),
    ("号角", "char_4039_horn", 90),
]
#: ⚠ 每位的**精英 2 满级**（`phases[2].maxLevel`：铅踝 70、五位五星 80、其余 90）。
#: 全写 90 会让六位干员在两侧**同时**折算失败（`unit_failed`）——
#: 那不但白占分母，还会让这条分歧少覆盖 6 位（第一版就是这么写的，读数里
#: `unit_failed=14` 正是它的指纹）。
SELFCELL_LEVEL = {nm: lv for nm, _cid, lv in SELFCELL_OPS}

#: 技能槽／专精那一支（`skills` spec ⇒ Python 的 `skill_of`）。
SKILLS = {"能天使": (2, 3), "星熊": (1, 0), "泥岩": (3, 1)}

PRINT_CAP = 60

MUT_COUNT = "条数"
MUT_DWELL = "dwell 末位"
MUT_VALUE = "value 末位"
MUT_POS = "position"
MUT_DIR = "direction"
MUT_SKILL = "skill"
MUT_VISITS = "visits"
MUT_CELLS = "cells 少一格"
MUT_ORDER = "同价值两条的顺序"
MUT_COVER = "covered 计数"
MUT_WANT = "期望值 dwell 末位"
MUT_PEROP0 = "per_op<=0 负对照"
MUT_KEYS = (MUT_COUNT, MUT_DWELL, MUT_VALUE, MUT_POS, MUT_DIR, MUT_SKILL,
            MUT_VISITS, MUT_CELLS, MUT_ORDER, MUT_COVER, MUT_WANT, MUT_PEROP0)
#: 每处变异应该撞出来的**字段名**（判「这一处真的被判红」的依据）。
#: ★ `position` / `direction` 改的是**身份键**，所以它们撞出来的是
#:   「候选集合」那一栏（键对不上），不是同名的那一栏——这不是放水：
#:   身份键变了本来就该报「选出来的候选集合不同」。
#: ★ `MUT_PEROP0` 撞出来的是「per_op 两侧一致」那一栏，名字由它自己的
#:   负对照直接 `guard.caught`（见 S8 那一支），不在这里。
MUT_FIELD = {MUT_COUNT: "条数", MUT_DWELL: "dwell", MUT_VALUE: "value",
             MUT_POS: "候选集合", MUT_DIR: "候选集合", MUT_SKILL: "skill",
             MUT_VISITS: "visits", MUT_CELLS: "cells", MUT_ORDER: "顺序",
             MUT_COVER: "covered.visits_zero", MUT_WANT: "dwell"}

#: 结构零分支（见文件头）。**每跑一次都重新量**，非 0 即红。
STRUCT_ZERO = {
    "no_char_id": "名册条目没有 char_id —— 两个读取器都丢掉这种行",
    "range_missing": "范围代号不在 range_table",
    "empty_range": "范围算出来一个格都没有",
    "atk_missing": "面板里取不到攻击力",
}

#: 逐段声明本套判据的覆盖面（`freeze_baseline.Channel.sections`）。
#: 十段**全部**是「Python 期望值 ↔ Go 现读」⇒ 冻得住，没有第四态。
SECTIONS = [
    {"id": "S1", "class": "frozen",
     "why": "逐关主对拍：candidates_for 的投影 ↔ Go cmd:candidates 的 rows/covered"},
    {"id": "S2", "class": "frozen",
     "why": "per_op 变体 8/3/1：同一批样本关卡、同一份名单（逼出截断）"},
    {"id": "S3", "class": "frozen",
     "why": "大名单：名册夹具里全部 20 位干员同场（多干员）"},
    {"id": "S4", "class": "frozen",
     "why": "skills 非零：名字→[槽位,专精] 进 rows 的 skill/mastery 两栏"},
    {"id": "S5", "class": "frozen",
     "why": "directions 子集与缺省：朝向表进 direction 栏与平局插入序"},
    {"id": "S6", "class": "frozen",
     "why": "名册路径不存在：两侧都必须具名拒收（Go 拒 ∧ Python 拒）"},
    {"id": "S7", "class": "frozen",
     "why": "合成名册：entry_missing/unit_failed 两条名册侧分支"},
    {"id": "S8", "class": "frozen",
     "why": "per_op<=0 的登记分歧：Go 按缺省 6、Python 留 1 条"},
    {"id": "S9", "class": "frozen",
     "why": "行使计数两个来源：Go 自报 covered ↔ 尺子按 Python 原语独立数出的那份"},
    {"id": "S10", "class": "frozen",
     "why": "自身格：范围代号 grids 不含 (0,0) 的那 9 位干员（合成名册，"
            "cells 与 dwell/visits 都覆盖）"},
]


# --------------------------------------------------------------- Go 侧入口

def go_candidates(level, spec, data_root=None):
    """问 Go 要一份候选。子进程输出按 bytes 收、自己解码（别让 PowerShell 插手）。

    ★ 两件都做（见文件头坑②）：`cwd=<本仓根>` **且** 显式设 `RIOS_DATA`。
    """
    env = dict(os.environ)
    env["RIOS_DATA"] = str(data_root or DATA)
    req = json.dumps({"id": 1, "cmd": "candidates", "level": level,
                      "spec": spec}, ensure_ascii=False) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       env=env, cwd=str(ROOT))
    if p.returncode != 0:
        raise SystemExit("Go 进程 rc=%d：%s" % (
            p.returncode, p.stderr.decode("utf-8", "replace")[:400]))
    lines = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not lines:
        raise SystemExit("Go 没有回任何东西（stderr：%s）"
                         % p.stderr.decode("utf-8", "replace")[:400])
    resp = json.loads(lines[0])
    if not resp.get("ok"):
        return False, (resp.get("error") or "（没有 error 文字）")
    return True, resp["candidates"]


def go_spec(ops, per_op, directions, skills, roster=None, omit_dirs=False):
    """把一次用例摊成 `spec`。**省略**与「给缺省值」是两件事，分开表达。"""
    s = {"roster": str(roster or ROSTER), "operators": list(ops),
         "per_op": per_op}
    if not omit_dirs:
        s["directions"] = list(directions)
    if skills:
        s["skills"] = {k: [int(v[0]), int(v[1])] for k, v in skills.items()}
    return s


# ------------------------------------------------- 已登记分歧：天赋面板攻击力倍率

#: ★ **这是一处早就登记过的口径差，不是本判据新发现的 bug。**
#:
#: 2026-09-24 的裁定：Go 把**天赋的面板倍率**折进了 `total`
#: （`rios-sim/talentpanel.go`），Python 侧一个都不折（实测 212 / 460 位干员
#: 带这类天赋）。原文与处置写在 `tools/check_operator_go.py:788-799`。
#:
#: `candidates_for` 的 `value = dwell × float(unit.atk)`、而 `unit.atk` 就是
#: 面板的 `total["atk"]` ⇒ 这一处差**原样传到了候选的价值上**，进而传到排序上。
#: 实测（main_01-07，名册夹具）：能天使 py 567 / Go 612（+8%）、
#: 焰狐龙梓兰 py 872 / Go 1003（+15%）、赤刃明霄陈 py 698 / Go 810（+16%）；
#: 没有这类天赋的（星熊／泥岩／阿米娅）两侧逐位相同。
#:
#: 判据的处置与 `check_operator_go` **逐字相同**：不比「原始 value」，而是把两边
#: 因子统一到同一个量再比 ——
#:
#:     期望 = Python 的 atk × (1 + 比例)     比例取自 **Go 自己的 `opstats` 应答**
#:
#: 比例**不猜、也不手抄**；`opstats` 与 `candidates` 用的是同一个
#: `OperatorStatsFor`，所以这是「同一个量的两个出口」，不是把被测方的结论
#: 拿来当期望值。★ **除不掉仍按原样报红**（登记不等于放水）。

_PANEL_CACHE: dict[tuple, tuple[dict, dict]] = {}


def go_panel_fold(cfgs):
    """问 Go 要这一批练度的天赋面板攻击力倍率与折算后的面板攻击力。

    返回 `(pct_by_char, total_atk_by_char)`。不认识的 `char_id` **逐个剔除**
    （Go 对它是大声失败），被剔掉的**不在返回值里** ⇒ 调用方按 0 处理。
    """
    ck = tuple(sorted(json.dumps(c, sort_keys=True) for c in cfgs))
    if ck in _PANEL_CACHE:
        return _PANEL_CACHE[ck]
    todo, pct, tot = list(cfgs), {}, {}
    for _ in range(60):
        if not todo:
            break
        env = dict(os.environ)
        env["RIOS_DATA"] = str(DATA)
        req = json.dumps({"id": 1, "cmd": "opstats", "spec": todo},
                         ensure_ascii=False) + "\n"
        p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=env, cwd=str(ROOT))
        if p.returncode != 0:
            raise SystemExit("Go(opstats) rc=%d：%s" % (
                p.returncode, p.stderr.decode("utf-8", "replace")[:300]))
        lines = p.stdout.decode("utf-8", "replace").strip().splitlines()
        resp = json.loads(lines[0]) if lines else {}
        if resp.get("ok"):
            for row in resp.get("opstats") or []:
                cid = row.get("char_id")
                pct[cid] = float((row.get("talent_panel_mods") or {}).get("atk") or 0.0)
                tot[cid] = float((row.get("total") or {}).get("atk") or 0.0)
            break
        m = re.search(r'character_table 里没有 "([^"]+)"', resp.get("error") or "")
        if not m:
            raise SystemExit("opstats 回 error（不是可逐个剔除的那种）：%s"
                             % resp.get("error"))
        bad_id = m.group(1)
        todo = [c for c in todo if c["char_id"] != bad_id]
    _PANEL_CACHE[ck] = (pct, tot)
    return pct, tot


class AtkFoldVerifier:
    """把天赋面板攻击力倍率折进 `unit.atk` 的**代理**（见上面那张注释）。

    `candidates_for` 只从 `unit` 取一个属性（`.atk`，`search.py:173`），
    所以这里只换那一个字段：`dataclasses.replace(u, atk=折算后的值)`。
    其余属性一律转发给真的 `Verifier`（`stage` / `library` / `range_provider` /
    `is_melee` / `_by_name`）——**不重写任何一个口径**。
    """

    def __init__(self, inner, pct: dict):
        self._inner = inner
        self._pct = pct

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def unit(self, entry):
        u = self._inner.unit(entry)
        p = self._pct.get(entry.get("char_id"), 0.0)
        if not p:
            return u
        return dataclasses.replace(
            u, atk=float(round(float(u.atk) * (1.0 + p))))


# --------------------------------------------------------------- 期望值（可冻）

_VERIFIER = None


def verifier():
    """复用一份 `Verifier`：它的 init（算子表／技能书／范围表）不便宜。"""
    global _VERIFIER
    if _VERIFIER is None:
        from ak_tactic.verify import Verifier
        _VERIFIER = Verifier()
    return _VERIFIER


def py_authority() -> str:
    """那一行的文件名。冻结档下不 import，也就没有它。"""
    import ak_tactic.search as S
    return Path(S.__file__).name


def proj(c) -> dict:
    """`Candidate` → 与 Go 同形的投影。`cells` 排序只为 JSON 稳定，**比的是集合**。"""
    return {
        "operator": c.operator, "char_id": c.char_id,
        "position": [int(c.position[0]), int(c.position[1])],
        "direction": c.direction, "skill": int(c.skill),
        "mastery": int(c.mastery), "dwell": float(c.dwell),
        "visits": int(c.visits), "value": float(c.value),
        "cells": sorted([int(x), int(y)] for x, y in c.cells),
    }


def py_covered(v, st, roster, ops, idx, directions) -> dict:
    """**尺子**：用 Python 自己的原语把 `covered` 那 14 个计数独立数一遍。

    ★ 它**不是期望值**（`rows` 才是），它是「计数器本身也是一个断言」那两个
    来源里的第二个。与 Go 的 `covered` 不等 ⇒ 判红。
    ★ `kept` 由调用方填成 `len(candidates_for(...))` —— 那是**权威自己的产物**，
    比在这里重数一遍更强。
    ★ 字段名与 `COVER_KEYS` 逐个对齐；多一个少一个由 `compare_case` 报。
    """
    c = {k: 0 for k in COVER_KEYS}
    c["operators"] = len(ops)
    prov = v.range_provider(st)
    cells = list(st.map.melee_spots) + list(st.map.ranged_spots)
    for name in ops:
        entry = roster.get(name)
        if entry is None:
            c["entry_missing"] += 1
            continue
        cid = entry.get("char_id") or v._by_name(name)
        if not cid:
            c["no_char_id"] += 1
            continue
        elite = int(entry.get("elite") or 0)
        try:
            unit = v.unit({**entry, "char_id": cid})
        except Exception:                                      # noqa: BLE001
            c["unit_failed"] += 1
            continue
        try:
            float(unit.atk)
        except Exception:                                      # noqa: BLE001
            c["atk_missing"] += 1
            continue
        melee = v.is_melee(cid)
        c["melee_ops" if melee else "ranged_ops"] += 1
        spots = st.map.melee_spots if melee else st.map.ranged_spots
        if not v.range_table.exists(prov.range_id_of(cid, elite)):
            c["range_missing"] += 1
            continue
        for pos in cells:
            if pos not in spots:
                c["not_in_spots"] += 1
                continue
            c["positions_tried"] += 1
            for d in directions:
                try:
                    cs = frozenset(prov(cid, elite, d, pos))
                except Exception:                              # noqa: BLE001
                    cs = frozenset()
                if not cs:
                    c["empty_range"] += 1
                    continue
                if idx.dwell(cs) <= 0:
                    c["visits_zero"] += 1
                    continue
                c["all_candidates"] += 1
    return c


def _index_of(v, level):
    from ak_tactic.eta import ArrivalIndex, enemy_arrivals
    st = v.stage(level)
    return st, ArrivalIndex(enemy_arrivals(st, v.library(st).get))


def py_expect(level, ops, per_op, directions, skills, roster_path=None):
    """一次用例的期望值（== 权威的产物投影，不是手抄的）。

    ★ `ak_tactic` 的 import **写在函数体里**：冻结档下本函数不会被调到。
    ★ `value` 一栏走**口径统一**（天赋面板倍率，见 `AtkFoldVerifier` 上面那张
      注释）：比例取自 Go 的 `opstats` 应答，**除不掉就记进 `fold_mismatch`**，
      由调用方报红。
    """
    from ak_tactic.plan import Roster
    from ak_tactic.search import candidates_for
    v = verifier()
    st, idx = _index_of(v, level)
    roster = Roster.from_json(roster_path or ROSTER)
    #: ---- 天赋面板倍率：Python 未折算的攻击力、Go 折算后的面板、以及比例
    cfgs, base_atk = [], {}
    for name in ops:
        e = roster.get(name)
        if e is None:
            continue
        cid = e.get("char_id") or v._by_name(name)
        if not cid:
            continue
        try:
            base_atk[cid] = float(v.unit({**e, "char_id": cid}).atk)
        except Exception:                                      # noqa: BLE001
            continue
        cfgs.append({"char_id": cid, "elite": int(e.get("elite") or 0),
                     "level": int(e.get("level") or 1),
                     "potential": int(e.get("potential") or 1),
                     "module": e.get("module") or "",
                     "module_level": int(e.get("module_level") or 0)})
    pct, go_atk = go_panel_fold(cfgs)
    fold_mismatch = []
    for c in cfgs:
        cid = c["char_id"]
        if cid not in pct:
            continue
        exp = float(round(base_atk[cid] * (1.0 + pct[cid])))
        if exp != go_atk.get(cid):
            fold_mismatch.append(
                "%s：Python %.1f × (1+%.4f) 取整 = %.1f，而 Go 报的面板是 %r"
                % (cid, base_atk[cid], pct[cid], exp, go_atk.get(cid)))
    vp = AtkFoldVerifier(v, pct)
    #: ★ 缺省必须是 `(0, 0)`：`skill_of` 对**名单里每一位**都会被调到，
    #:   而 Go 那边是 `if v, ok := q.Skills[name]; ok {…} else {0, 0}`。
    sk = (lambda n: (int(skills.get(n, (0, 0))[0]),
                     int(skills.get(n, (0, 0))[1]))) if skills else None
    cands = candidates_for(vp, level, roster, list(ops), index=idx,
                           per_op=per_op, directions=tuple(directions),
                           skill_of=sk)
    rows = [proj(c) for c in cands]
    #: 尺子用**真的** Verifier（它数的是剪枝分支，与攻击力无关）。
    cov = py_covered(v, st, roster, ops, idx, directions)
    cov["kept"] = len(rows)
    #: ★ 自检（两侧都是 Python ⇒ **不**冻、也**不**算期望值）：`value` 必须真是
    #: `dwell ×` **交给 `candidates_for` 的那个** atk。它守的是「value 被人改成
    #: 别的式子」——那种改动在两侧同时发生时对拍是看不见的。
    atk_used = {}
    for name in ops:
        e = roster.get(name)
        if e is None:
            continue
        cid = e.get("char_id") or v._by_name(name)
        if not cid:
            continue
        try:
            atk_used[name] = float(vp.unit({**e, "char_id": cid}).atk)
        except Exception:                                      # noqa: BLE001
            pass
    selfcheck = [r["operator"] for r in rows
                 if r["operator"] in atk_used
                 and r["value"] != r["dwell"] * atk_used[r["operator"]]]
    return {"rows": rows, "covered": cov,
            "fold_mismatch": fold_mismatch[:8],
            "folded_rows": sum(1 for r in rows if pct.get(r["char_id"])),
            "value_selfcheck_fail": selfcheck[:8],
            "value_selfcheck_n": len(selfcheck)}


def py_rows_only(level, ops, per_op, directions, roster_path=None):
    """只取权威的 `rows`（`per_op<=0` 那一支的登记分歧用它）。"""
    from ak_tactic.plan import Roster
    from ak_tactic.search import candidates_for
    v = verifier()
    _st, idx = _index_of(v, level)
    roster = Roster.from_json(roster_path or ROSTER)
    return [proj(c) for c in candidates_for(
        v, level, roster, list(ops), index=idx, per_op=per_op,
        directions=tuple(directions))]


def py_bad_roster(path) -> dict:
    """名册路径不存在时权威的行为（两边都必须拒）。"""
    from ak_tactic.plan import Roster
    try:
        Roster.from_json(path)
    except Exception as exc:                                   # noqa: BLE001
        return {"accept": False, "why": "%s: %s" % (type(exc).__name__, exc)}
    return {"accept": True, "why": ""}


#: `per_op<=0` 那条负对照用的**旧行为**：在已经排好序的 `rows` 上按「每位只留
#: 1 条」剪一遍。它**忠于历史语义**，且**不动 `ak_tactic`**（负对照不许改被测方
#: 的源码，只许改喂进去的那一份）：
#:
#: 旧循环是「先 append 再判 `len(kept) >= per_op`」⇒ `per_op=0` 时第一次
#: append 之后 `1 >= 0` 立刻成立 ⇒ 每位只留 1 条；`per_op=1` 同解。
#: 注意**顺序**：`local` 是按 `-value` 稳定排过的，所以「前 n 条」就是它留下的
#: 那 n 条（`out.sort` 之后相对次序不变）——这就是为什么可以在这份投影上剪。
def legacy_py0_rows(rows: list) -> list:
    """把 `per_op<=0` 的旧行为（每位只留 `n=0` 条 ⇒ 实际 1 条）装回去。"""
    return _clip_first_per_operator(rows, 0)


def _clip_first_per_operator(rows: list, per_op: int) -> list:
    seen: set = set()
    kept: list = []
    for r in rows:
        key = _row_key(r)
        if key[:3] in seen:                     #: 旧代码按**落点**去重（position）
            continue
        seen.add(key[:3])
        kept.append(r)
        if len(kept) >= per_op:                 #: ★ 旧代码的 bug 就在这一行
            break
    return kept


# --------------------------------------------------------------- 变异守卫

class Guard:
    """反向守卫：每处变异都要「注入过 ＋ 判红过」，缺一不算成立。"""

    def __init__(self, on: bool):
        self.on = on
        self.applied: dict[str, str] = {}
        self.caught: dict[str, bool] = {}
        #: ★ 变异**槽位**计数：`inject()` 每见到一处变异就 +1，**不管它注在不在
        #: `applied` 里**。「行号 = 已注入的处数」这个口径要求它数的是**槽位**，
        #: 不是 `len(applied)`：有的变异（如 `per_op<=0` 的负对照）不在 Go 的应答
        #: 上注入任何东西，用 `len(applied)` 会让它**占不到行号** ⇒ 后面每一处都
        #: 往前挪一格、最后一处与别人**压在同一行**上（「各自落在不同候选」这条
        #: 前提就静默破了，而读数上看不出来）。
        self.slots = 0

    def want(self, key: str) -> bool:
        return self.on and key not in self.applied

    def put(self, key: str, where) -> str:
        self.applied[key] = str(where)
        return key

    def note(self, fields) -> None:
        """把这一轮撞出的字段名对照每一处已注入的变异，命中即记「判红」。"""
        for k, f in MUT_FIELD.items():
            if k in self.applied and f in fields:
                self.caught[k] = True


def inject(guard: Guard, got: dict, where) -> str | None:
    """在 Go 的**应答**上注入一处不一致。每次调用最多注入一处。

    ★ 每处落在**不同的一条候选**上（行号 = 已经见过的**变异槽位**数）：十二处变异
    在一关之内就能全部注入完，所以 `check_go_all --selfcheck` 只喂一关也够
    （它给「要喂清单」的套只喂 `lvls[:1]`）。
    """
    if not guard.on:
        return None
    rows = got.get("rows") or []
    cov = got.get("covered") or {}
    i = guard.slots                             #: 每条变异一个不同的行号
    guard.slots += 1

    def row():
        if not rows:
            return None
        return rows[i] if i < len(rows) else rows[0]
    if guard.want(MUT_COUNT) and len(rows) >= 13:
        del rows[-1]
        return guard.put(MUT_COUNT, where)
    if guard.want(MUT_DWELL) and row():
        r = row()
        r["dwell"] = math.nextafter(float(r["dwell"]), math.inf)
        return guard.put(MUT_DWELL, where)
    if guard.want(MUT_VALUE) and row():
        r = row()
        r["value"] = math.nextafter(float(r["value"]), math.inf)
        return guard.put(MUT_VALUE, where)
    if guard.want(MUT_POS) and row():
        r = row()
        r["position"] = [int(r["position"][0]) + 1, int(r["position"][1])]
        return guard.put(MUT_POS, where)
    if guard.want(MUT_DIR) and row():
        r = row()
        r["direction"] = "Left" if r["direction"] != "Left" else "Right"
        return guard.put(MUT_DIR, where)
    if guard.want(MUT_SKILL) and row():
        r = row()
        r["skill"] = int(r["skill"]) + 1
        return guard.put(MUT_SKILL, where)
    if guard.want(MUT_VISITS) and row():
        r = row()
        r["visits"] = int(r["visits"]) + 1
        return guard.put(MUT_VISITS, where)
    if guard.want(MUT_CELLS) and row() and len(row()["cells"]) >= 2:
        r = row()
        r["cells"] = r["cells"][:-1]
        return guard.put(MUT_CELLS, where)
    if guard.want(MUT_ORDER) and len(rows) >= 2:
        for k in range(len(rows) - 1):
            if float(rows[k]["value"]) == float(rows[k + 1]["value"]):
                rows[k], rows[k + 1] = rows[k + 1], rows[k]
                return guard.put(MUT_ORDER, where)
        return None
    if guard.want(MUT_COVER):
        cov["visits_zero"] = int(cov["visits_zero"]) + 1
        return guard.put(MUT_COVER, where)
    return None


def inject_want(guard: Guard, want: dict, where) -> str | None:
    """在**期望值**上注入一处不一致（「故意改一个期望值必须判红」）。

    ★ 改的是**副本**：`G.expect()` 在 record/frozen 两档交回的可能是**存着的
    那一份**，原地改它＝污染将要落盘的基线（本仓记过：控制组自己把读数污染了）。
    """
    if not guard.on or not guard.want(MUT_WANT):
        return None
    rows = want.get("rows") or []
    if not rows:
        return None
    rows[0]["dwell"] = math.nextafter(float(rows[0]["dwell"]), math.inf)
    return guard.put(MUT_WANT, where)


# --------------------------------------------------------------- 比较

class Printed(list):
    """带上限的失配清单。超出的**计数**（`dropped`），**不静默吞掉** ——
    「印了 40 行」与「只有 40 处失配」是两件事（本仓记过的那类假读数）。"""

    def __init__(self, cap: int = PRINT_CAP):
        super().__init__()
        self.cap = cap
        self.dropped = 0

    def append(self, line) -> None:                            # noqa: D102
        if len(self) < self.cap:
            super().append(line)
        else:
            self.dropped += 1


def _short(v) -> str:
    s = repr(v)
    return s if len(s) <= 90 else s[:87] + "..."


def _field_same(g, w, f: str) -> bool:
    """一栏比不比得上。★ 浮点**逐位**（唯一例外见 `FLOAT_REL_TOL`），`cells` **按集合**。"""
    if f == "cells":
        return ({tuple(c) for c in (g.get("cells") or [])}
                == {tuple(c) for c in (w.get("cells") or [])})
    gv, wv = g.get(f), w.get(f)
    if f in FLOAT_FIELDS:
        try:
            return float(gv) == float(wv)
        except (TypeError, ValueError):
            return False
    return gv == wv


# ------------------------------------------------ 浮点容差：只对「累加序」开口
#
#: 相对容差的**基**。只有 `dwell` / `value` 两栏用它（见文件头 ③）。
#:
#: ★ **为什么是相对、不是绝对**：这一处的**绝对**差随 visit 条数增长
#: （同一个格上叠几千条 visit 时能累到几千 ulp 量级），承载它的 `dwell` 本身
#: 也同尺度地变大 ⇒ `abs <= 1e-9` 这种绝对口径会把「大 dwell 的小相对漂移」
#: 与「小 dwell 的大相对漂移」判成同一件事，两头都看错。
#:
#: ★ **为什么乘 visits**：n 项的累加序差，误差量级就是 n 个舍入单位
#: （单次 ≈ 2.22e-16 / 单位舍入）。乘法让 visit 特别多的格留得住余量，
#: 让 visit 少的格收得很紧。挂在 `visits` 这一栏上而不是「整个应答一个系数」。
FLOAT_REL_TOL = 1e-12

#: 累计读数（`:mod:` 级，只给人读）：超出容差的条数、最大相对差、以及
#: **被容差收下**的条数（其中 `cells` 相同／不同分开数）。
FLOAT_STATS: dict = {"超容差条目": 0, "最大相对差": 0.0, "最大相对差样例": "",
                     "收下条目": 0, "收下且cells相同": 0,
                     "超容差且cells相同": 0, "超容差且cells不同": 0,
                     "收下样例": []}


def _ulps(a: float, b: float) -> int:
    """两个浮点之间隔几个 ulp（封顶 64；判据只关心量级）。"""
    lo, hi = (a, b) if a <= b else (b, a)
    n, x = 0, lo
    while x < hi and n < 64:
        x = math.nextafter(x, math.inf)
        n += 1
    return n


def _float_gap(g, w, f: str) -> tuple[float, int] | None:
    """这一栏的浮点差：`(相对差, ulp 距离)`。

    相对差 = |Go − Python| / max(|Go|, |Python|)（两侧都是 0 ⇒ 相对差记 0）。
    ★ `value` 与 `dwell` 用同一个式子 —— 不因为谁大谁小换口径。
    """
    try:
        a, b = float(g.get(f) or 0.0), float(w.get(f) or 0.0)
    except (TypeError, ValueError):
        return None
    if a == b:
        return None
    if not (math.isfinite(a) and math.isfinite(b)):
        return (math.inf, _ulps(a, b))
    den = max(abs(a), abs(b))
    return ((abs(a - b) / den) if den else math.inf, _ulps(a, b))


def _float_tol(row) -> float:
    """这一条候选的容差 = `FLOAT_REL_TOL × max(1, visits)`。"""
    try:
        n = int(row.get("visits") or 0)
    except (TypeError, ValueError):
        n = 0
    return FLOAT_REL_TOL * max(1, n)


def _rows_bit_equal(a: list, b: list) -> bool:
    """两个 `rows` 逐字段**精确**相等（浮点也精确；`cells` 按集合）。

    这一份是给「同一位实现的两个输入」用的（`per_op` 那条断言）——
    那里**不许**吃 `FLOAT_REL_TOL`：跨实现的累加序差才有容差这一说。
    """
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        for f in ROW_FIELDS:
            if not _field_same(x, y, f):
                return False
    return True


def _first_key_diff(a: list, b: list):
    """两串身份键第一个不同的下标（没有就 None）。只用于印读数。"""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


#: 前几处 1 ulp 分歧的样例（只给人读）。
DWELL_SAMPLES: list[str] = []


def _row_key(r) -> tuple:
    return (r.get("operator"), r.get("char_id"),
            tuple(r.get("position") or ()), r.get("direction"))


def compare_case(tag, level, want, got, seen, printed) -> tuple[int, set]:
    """比一次（`rows` ＋ `covered`）。返回 `(不一致处数, 撞出的字段名集合)`。

    ## 三层，顺序有讲究

    1. **条数**；
    2. **顺序**：逐索引比**身份键**序列（`(干员, char_id, 落点, 朝向)`）——
       这是「稳定排序 ＋ 平局插入序」那条的判据；
    3. **逐字段**：按**身份键对齐**比十栏，**不是按索引**。

    ★ 第 3 层为什么不能按索引：`value` 一旦分叉（本套真的分叉了两处，见文件头），
    两侧的序列就会错位，按索引比等于**拿 A 的读数去比 B 的对象**——症状是一串
    看着像字段错的失配，而真因是排序键不同。本仓记过这条同族（剔人之后仍 `zip`）。
    按身份键对齐之后，「字段错」与「顺序错」才能分开报。

    ★ 身份键唯一：每位干员对每个落点最多留一条（`per_op` 的去重就是这么做的），
    所以 `(干员, 落点, 朝向)` 在应答里不会重复。
    """
    bad = 0
    fields: set[str] = set()
    g_rows = got.get("rows") or []
    w_rows = want.get("rows") or []
    seen["候选条数"] += len(g_rows)

    if len(g_rows) != len(w_rows):
        bad += 1
        fields.add("条数")
        printed.append("✗ %s/%s 候选条数：Go=%d Python=%d"
                       % (tag, level, len(g_rows), len(w_rows)))
    gk = [_row_key(r) for r in g_rows]
    wk = [_row_key(r) for r in w_rows]
    if len(gk) == len(wk) and gk != wk:
        bad += 1
        fields.add("顺序")
        seen["顺序不一致"] += 1
        k = next(j for j in range(len(gk)) if gk[j] != wk[j])
        printed.append("✗ %s/%s 第 %d 条顺序不同：Go=%r Python=%r"
                       % (tag, level, k, gk[k], wk[k]))
    #: ---- 按身份键对齐
    gmap: dict[tuple, dict] = {}
    wmap: dict[tuple, dict] = {}
    for r in g_rows:
        gmap.setdefault(_row_key(r), []).append(r)
    for r in w_rows:
        wmap.setdefault(_row_key(r), []).append(r)
    dup = [k for k in list(gmap) + list(wmap)
           if len(gmap.get(k, [])) > 1 or len(wmap.get(k, [])) > 1]
    if dup:
        bad += 1
        fields.add("候选集合")
        printed.append("✗ %s/%s 同一个身份键出现两次（%r）—— 去重那一支坏了"
                       % (tag, level, dup[0]))
    only_g = sorted(set(gmap) - set(wmap))
    only_w = sorted(set(wmap) - set(gmap))
    if only_g or only_w:
        bad += 1
        fields.add("候选集合")
        printed.append("✗ %s/%s 选出来的候选**集合**不同：只在 Go %d 条、只在 Python %d 条"
                       "；例：Go=%r Python=%r"
                       % (tag, level, len(only_g), len(only_w),
                          only_g[:2], only_w[:2]))
    for k in sorted(set(gmap) & set(wmap), key=repr):
        g, w = gmap[k][0], wmap[k][0]
        row_diff: set[str] = set()
        cells_same = _field_same(g, w, "cells")
        for f in ROW_FIELDS:
            seen["字段比较"] += 1
            if _field_same(g, w, f):
                continue
            #: ---- ★ **已登记分歧的开口**：`dwell` / `value` 两栏，**相对容差**
            #: 随 visit 条数增长（见文件头 ③ 与 `FLOAT_REL_TOL`）。
            #: ⚠ **开口只在「`cells` 完全相同」时成立** —— 登记的就是**纯累加序**
            #:   那一条（同一个格集合、两种迭代序）；`cells` 都不同了，浮点差就
            #:   不再有「累加序」这个解释 ⇒ 照旧判红。这条范围限制是**故意的**：
            #:   它让「自身格」那处仍占红，不会因为容差被静默收掉。
            #: ⚠ 这里只决定「算不算判红」；**无论收不收下，读数都照记**
            #:   （超容差条数、最大相对差、被收下的条数与样例）——登记不等于不报。
            if f in FLOAT_FIELDS:
                gp = _float_gap(g, w, f)
                if gp is not None:
                    rel, n_ulp = gp
                    tol = _float_tol(w)
                    if cells_same and rel <= tol:
                        FLOAT_STATS["收下条目"] += 1
                        FLOAT_STATS["收下且cells相同"] += 1
                        if len(FLOAT_STATS["收下样例"]) < 6:
                            FLOAT_STATS["收下样例"].append(
                                "%s/%s %r %s：Go=%.17g Python=%.17g"
                                "（相对差 %.3g、%d ulp；容差 %.3g、visits=%r）"
                                % (tag, level, k[:3], f, float(g.get(f) or 0.0),
                                   float(w.get(f) or 0.0), rel, n_ulp, tol,
                                   w.get("visits")))
                        if f == "dwell" and len(DWELL_SAMPLES) < 4:
                            #: 纯累加序那一族的样例（只给人读）
                            DWELL_SAMPLES.append(
                                "%s/%s %r dwell：Go=%.17g Python=%.17g"
                                "（差 %d ulp、相对差 %.3g；容差 %.3g、visits=%r）"
                                % (tag, level, k[:3], float(g.get("dwell") or 0.0),
                                   float(w.get("dwell") or 0.0), n_ulp, rel, tol,
                                   w.get("visits")))
                        #: ★ 浮点两栏的「收下」**不影响** `visits` 的判红：
                        #: `visits` 是整数，它不同就是不同，没有容差这一说。
                        if f == "dwell":
                            seen["其中 cells 相同（纯累加序）"] += 1
                            if n_ulp <= 2:
                                seen["ulp 距离 <= 2"] += 1
                            seen["容差内收下"] += 1
                            seen["dwell 逐位不同的条数"] += 1
                        continue
                    #: 到这里有两种形状，**都算红的**：① 相对差超容差；② `cells`
                    #: 本来就不同（登记不覆盖它）。下列读数把两者分开记，
                    #: 免得「容差收不下」与「不在登记范围」被读成同一件事。
                    FLOAT_STATS["超容差条目"] += 1
                    if not cells_same:
                        FLOAT_STATS["超容差且cells不同"] += 1
                    elif rel > tol:
                        FLOAT_STATS["超容差且cells相同"] += 1
                    if rel > FLOAT_STATS["最大相对差"]:
                        FLOAT_STATS["最大相对差"] = rel
                        FLOAT_STATS["最大相对差样例"] = (
                            "%s/%s %r %s：Go=%.17g Python=%.17g（相对差 %.6g、"
                            "%d ulp；容差 %.3g、visits=%r；cells %s）"
                            % (tag, level, k[:3], f, float(g.get(f) or 0.0),
                               float(w.get(f) or 0.0), rel, n_ulp, tol,
                               w.get("visits"),
                               "相同" if cells_same else "不同"))
                    if f == "dwell":
                        seen["dwell 逐位不同的条数"] += 1
                        if cells_same:
                            seen["其中 cells 相同（纯累加序）"] += 1
                        else:
                            seen["其中 cells 也不同"] += 1
                        if n_ulp <= 2:
                            seen["ulp 距离 <= 2"] += 1
            bad += 1
            fields.add(f)
            row_diff.add(f)
            if f == "cells":
                gs = {tuple(c) for c in (g.get("cells") or [])}
                ws = {tuple(c) for c in (w.get("cells") or [])}
                printed.append("✗ %s/%s %r cells：只 Python 有 %r；只 Go 有 %r"
                               % (tag, level, k[:3], sorted(ws - gs)[:4],
                                  sorted(gs - ws)[:4]))
            else:
                printed.append("✗ %s/%s %r %s：Go=%r Python=%r"
                               % (tag, level, k[:3], f, _short(g.get(f)),
                                  _short(w.get(f))))
        #: ★ **自身格分歧**的定性（见文件头与 `SELFCELL_OPS`）：判它是它，
        #: 是为了把一处**未裁定**的分歧印成一句可读的话，而不是一串坐标。
        #: ⚠ 定性**不影响判红**——它照旧算在 `bad` 里（红的是事实，不是标签）。
        if "cells" in row_diff:
            gs = {tuple(c) for c in (g.get("cells") or [])}
            ws = {tuple(c) for c in (w.get("cells") or [])}
            self_cell = tuple(w.get("position") or ())
            if ws - gs == (set() if not self_cell else {self_cell}) and not gs - ws:
                seen["自身格分歧条数"] += 1
                if {"dwell", "visits", "value"} & row_diff:
                    seen["自身格分歧并带动 dwell/visits"] += 1
        #: ★ **1 ulp 分歧**的定性：`dwell` 是浮点累加，累加序 = visit 的拼接序，
        #: 而拼接序由格集合的迭代序定（Python 是 frozenset 的哈希序、Go 是按 (x,y)
        #: 排序的切片）⇒ 一旦有多条 visit 的 `enter` 相等，两侧的累加序就不同。
        #: ⚠ `row_diff` 里已经**不含**被容差收下的那一族（它们不判红）；收下那一族
        #: 的条数与样例在上面那一段里照记（`dwell 逐位不同的条数` 也照计）。
        if "dwell" in row_diff:
            seen["dwell 逐位不同的条数"] += 1
            gd = float(g.get("dwell") or 0.0)
            wd = float(w.get("dwell") or 0.0)
            n_ulp = _ulps(gd, wd)
            if n_ulp <= 2:
                seen["ulp 距离 <= 2"] += 1
            if "cells" in row_diff:
                seen["其中 cells 也不同"] += 1
            else:
                seen["其中 cells 相同（纯累加序）"] += 1
                if len(DWELL_SAMPLES) < 4:
                    DWELL_SAMPLES.append(
                        "%s/%s %r dwell：Go=%.17g Python=%.17g（差 %d ulp）"
                        % (tag, level, k[:3], gd, wd, n_ulp))
    #: ---- 两侧各自的「值降序」自洽（顺序判据的另一半：序列对了但值乱序，
    #:      说明排序键与 value 不是同一个量）
    for who, rows in (("Go", g_rows), ("Python", w_rows)):
        for a, b in zip(rows, rows[1:]):
            if float(a.get("value") or 0) < float(b.get("value") or 0):
                bad += 1
                fields.add("降序自洽")
                printed.append("✗ %s/%s %s 的 rows 不是值降序：%r(%r) → %r(%r)"
                               % (tag, level, who, a.get("operator"),
                                  a.get("value"), b.get("operator"), b.get("value")))
                break
    #: ---- covered（Go 自报 ↔ 尺子独立数出的那一份）
    g_cov = got.get("covered") or {}
    w_cov = want.get("covered") or {}
    for k in COVER_KEYS:
        seen["covered 键比较"] += 1
        if k not in g_cov:
            bad += 1
            fields.add("covered." + k)
            printed.append("✗ %s/%s covered 缺键 %s（Python 尺子=%r）"
                           % (tag, level, k, w_cov.get(k)))
            continue
        if int(g_cov[k]) != int(w_cov.get(k, -1)):
            bad += 1
            fields.add("covered." + k)
            printed.append("✗ %s/%s covered.%s：Go=%r 尺子=%r"
                           % (tag, level, k, g_cov[k], w_cov.get(k)))
    extra = sorted(set(g_cov) - set(COVER_KEYS))
    if extra:
        bad += 1
        fields.add("covered 键集")
        printed.append("✗ %s/%s covered 多出没约定的键：%s"
                       % (tag, level, "、".join(extra)))
    #: ---- 行使计数（累计；用**尺子**那一份，它不依赖 Go 自报）
    for k in seen:
        if k in COVER_KEYS:
            seen[k] += int(w_cov.get(k, 0))
    if int(w_cov.get("kept", 0)) < int(w_cov.get("all_candidates", 0)):
        seen["被 per_op 截断的关数"] += 1
    return bad, fields


# --------------------------------------------------------------- 用例表

def variant_cases():
    """S2~S5 的用例表：(用例名, 名单, per_op, directions, skills, 是否省略 directions)。

    ★ 这张表是**判据的一部分**（它决定「问哪些问题」）⇒ 表本身的变化由基线的
    `script_sha256_16` 与 `("query", "candidates_params")` 两侧看得见。
    """
    return [
        ("perop8", MAIN_OPS, 8, DIRECTIONS, {}, False),
        ("perop3", MAIN_OPS, 3, DIRECTIONS, {}, False),
        ("perop1", MAIN_OPS, 1, DIRECTIONS, {}, False),
        ("bigroster", None, 6, DIRECTIONS, {}, False),          #: None ⇒ 名册全部
        ("skills", MAIN_OPS, 6, DIRECTIONS, SKILLS, False),
        ("dironly2", MAIN_OPS, 6, ("Right", "Left"), {}, False),
        ("dirdefault", MAIN_OPS, 6, DIRECTIONS, {}, True),
    ]


def sample_levels(batch, n=5):
    """从这一批里**确定性地**摊开取 n 关（含首尾）。规则进键、不进判定。"""
    if not batch:
        return []
    if len(batch) <= n:
        return list(batch)
    return [batch[round(i * (len(batch) - 1) / (n - 1))] for i in range(n)]


def blank_seen() -> dict:
    d = {"关卡": 0, "比较次数": 0, "名单里的干员": 0, "候选条数": 0,
         "字段比较": 0, "covered 键比较": 0, "顺序不一致": 0,
         "被 per_op 截断的关数": 0, "value 自检不过": 0,
         "天赋折算的候选条数": 0, "判不了的例数": 0,
         #: ★ 自身格分歧的两栏（见 `compare_case` 里那一支）
         "自身格分歧条数": 0, "自身格分歧并带动 dwell/visits": 0,
         #: ★ 累加序那一处（见 `compare_case` 里那一支）：按**两种因**分开数。
         #: `dwell 逐位不同的条数` = **全部**浮点不同的条数（收下的 ＋ 超容差的），
         #: `容差内收下` 是其中**没**判红的那一份 ⇒ 差值就是超容差的那一份。
         "dwell 逐位不同的条数": 0, "其中 cells 也不同": 0,
         "其中 cells 相同（纯累加序）": 0, "ulp 距离 <= 2": 0,
         "容差内收下": 0,
         #: ★ per_op=0 与 per_op=6 两侧一致的断言（S8）
         "perop_zero": 0}
    for k in COVER_KEYS:
        d[k] = 0
    return d


def all_names() -> list[str]:
    """名册夹具里的全部名字（大名单那一支用）。

    ★ 读**原始 JSON**，不走 `Roster`：冻结档下不许 import `ak_tactic`，
    而这一支在冻结档也要算得出同一份名单。
    """
    rows = json.loads(ROSTER.read_text(encoding="utf-8-sig"))
    if isinstance(rows, dict):
        rows = rows.get("opers") or rows.get("chars") or []
    return [r["name"] for r in rows
            if isinstance(r, dict) and r.get("name") and r.get("own") is not False]


def level_cache_path(data_path: str) -> Path:
    return DATA / "map.ark-nights.com" / "levels" / data_path


# --------------------------------------------------------------- 主流程

#: ★ 键的**第一位**必须是覆盖面对账用的标签，而 `freeze_baseline.Channel.coverage()`
#: 的口径是「`key[1:]` 就是这个对象的身份」。本套的键还要带**名册 sha**（期望值是
#: 名册的函数）与**用例名**（同一个关卡要按 per_op／名单跑好几遍）⇒ 两者都必须
#: 落在 `key[1:]` 里，否则对账两边**永远配不上**。
#:
#: ⚠ 第一版把用例名放在 `key[1]`、关卡放在 `key[2]`，而 `coverage()` 拿 `key[1:]`
#: 去和 `[[关卡, 关卡sha]]` 求交 ⇒ 交出来是 0，冻结档读到「主对拍 0 关」。
#: 那一跑**没有静默变绿**：末端的「visits_zero 一例都没走到」守卫当场判红
#: （本仓那条「判据自己瞎也要红」的守卫真的救了一次）。
CASE_TAG = "candidates:%s"


def main() -> int:                                             # noqa: C901
    G = GB.bind("候选生成", __file__)
    G.sections(SECTIONS)

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    mutate = "--mutate" in sys.argv
    guard = Guard(mutate)
    levels = args or ["main_01-07"]

    print("Go 侧仪器：%s" % GO_BIN)
    if G.mode == GB.CHECK:
        print("Python 侧权威：ak_tactic/search.py 的 candidates_for"
              "（冻结档不 import：读的是 fixtures/golden/候选生成.json）")
    else:
        print("Python 侧权威：ak_tactic/search.py 的 candidates_for（%s）"
              % py_authority())
    print("名册夹具：%s（sha16=%s）" % (ROSTER.name, GB.file_sha16(ROSTER)))
    print()

    batch = GB.level_inputs(DATA, levels)
    roster_sha = GB.file_sha16(ROSTER)
    if G.mode == GB.RECORD:
        #: 分母也是判据的一部分（本仓：只冻答案不冻问题＝分母会静默缩水）。
        G.expect(("query", "candidates_batch"), lambda: batch)
        G.expect(("query", "candidates_sample"),
                 lambda: [r["level"] for r in sample_levels(batch)])
        G.expect(("query", "candidates_params"),
                 lambda: {"main_ops": MAIN_OPS, "syn_ops": SYN_OPS,
                          "per_ops": [8, 6, 3, 1, 0, -1],
                          "directions": list(DIRECTIONS),
                          "skills": {k: list(v) for k, v in SKILLS.items()},
                          "syn_roster_rows": SYN_ROSTER_ROWS,
                          "selfcell_ops": [list(x) for x in SELFCELL_OPS]})
    sha_of = {r["level"]: r["sha16"] for r in batch}
    path_of = {r["level"]: r["data_path"] for r in batch}
    sample = sample_levels(batch)
    sample_pairs = [(r["level"], r["sha16"]) for r in sample]
    batch_pairs = [(r["level"], r["sha16"]) for r in batch]

    printed = Printed()
    bad = 0
    seen = blank_seen()
    data_missing: list[str] = []
    py_fetched: list[str] = []
    diverged: list[str] = []
    want_cache: dict[tuple, dict] = {}
    cov_reports: list[str] = []
    #: 「断言真的活过」的留证（**不受 `printed` 的 60 行上限**，见它的使用点）。
    perop_notes: list[str] = []
    _cov: dict[tuple, set] = {}

    #: 每个用例的**对象集**（用例名 → 关卡身份列表）。判据用不到它做判定，
    #: 但覆盖面对账要用它**现读**「这一次问了哪些对象」。
    case_pairs: dict[str, list] = {"main": batch_pairs,
                                   "perop0": sample_pairs[:1],
                                   "synroster": sample_pairs[:2],
                                   "selfcell": sample_pairs[:2]}
    for (vt, _o, _p, _d, _s, _od) in variant_cases():
        case_pairs[vt] = sample_pairs

    def covered_set(tag, rsha):
        """这个用例的覆盖面（**现读**的批次 ↔ 冻的那一批）。

        ★ 键形状 `(用例名, 关卡, 关卡内容 sha16, 名册内容 sha16)`，所以这里给的
        `live` 也是同形的四元组 —— 少一位就对不上（本套第一版正是这样读到 0 关）。
        """
        ck = (tag, rsha)
        if ck not in _cov:
            t = CASE_TAG % tag
            c = G.coverage(t, [[lv, sh, rsha] for lv, sh in case_pairs.get(tag, [])])
            if G.mode == GB.CHECK and not c.ok:
                cov_reports.append(c.report(t, len(case_pairs.get(tag, []))))
            _cov[ck] = {tuple(x) for x in c.covered}
        return _cov[ck]

    def skip_in_check(tag, lv, rsha):
        if G.mode != GB.CHECK:
            return False
        return (lv, sha_of.get(lv), rsha) not in covered_set(tag, rsha)

    #: ★ 覆盖面对账**每种模式都要调**：它一身两职 ——
    #: ① RECORD 档：把「对象集是活的」这件事记进基线（`input_identity`）。
    #:    没有它，`--control` 的 **P3**（对象集变小必须报成「对象变了」）会被 ⊘ 跳过；
    #: ② CHECK 档：拿**现读**的批次 ↔ 冻的那一批对账，决定比哪些、并把
    #:    「未覆盖」具名印出来。
    #: ⚠ 第一版把这一句写进了 `if G.mode == GB.CHECK` 里 ⇒ 录出来的基线自称
    #: **「对象集写死在脚本里」**（`input_identity: False`），P3 因此被跳过。
    #: 那不是判据红、也不改判决，但它是一条**登记成了别的东西**的身份栏。
    main_covered = covered_set("main", roster_sha)
    to_cmp = batch
    if G.mode == GB.CHECK:
        #: 冻的那一批里没有的关卡**不猜**（猜＝自己写一份期望值）。
        to_cmp = [r for r in batch
                  if (r["level"], r["sha16"], roster_sha) in main_covered]
    seen["关卡"] = len(to_cmp)

    def key(tag, lv, rsha):
        return (CASE_TAG % tag, lv, sha_of.get(lv), rsha)

    def run_one(tag, lv, ops, per_op, directions, skills, spec,
                roster_path=None, rsha=None):
        """一次「取期望值 ＋ 问 Go ＋ 比」。返回 `(撞出的字段集合, 期望值)`。

        ★ `roster_path` 必须**一路传到期望值那一侧**：合成名册那一支的整个
          意义就是「换一份名册」，两边读的不是同一份的话，比出来的东西
          与它宣称的覆盖面毫无关系（第一版漏了这一路，症状是合成名册那条
          分支的期望值仍取自真夹具 ⇒ 报出 entry_missing=3/unit_failed=0）。
        """
        nonlocal bad
        rp = roster_path or ROSTER
        rs = rsha if rsha is not None else roster_sha
        try:
            want = G.expect(key(tag, lv, rs),
                            lambda: py_expect(lv, ops, per_op, directions, skills,
                                              roster_path=rp))
        except Exception as exc:                               # noqa: BLE001
            #: ⚠ `_channel_fail()` 抛的是 **SystemExit**（不是 Exception）⇒
            #: 冻结档的 rc=6 不会被这里吞掉，这一支只接「oracle 自己算不出来」。
            return handle_py_fail(tag, lv, spec, exc, (tag, lv)), None
        #: ★ 过通道之后**再复制一份**：原地改它会污染将要落盘的基线。
        want = json.loads(json.dumps(want))
        want_cache[(tag, lv)] = want
        if want.get("value_selfcheck_n"):
            seen["value 自检不过"] += int(want["value_selfcheck_n"])
        seen["天赋折算的候选条数"] += int(want.get("folded_rows") or 0)
        if want.get("fold_mismatch"):
            bad += 1
            printed.append("✗ %s/%s 天赋面板倍率**除不掉**（登记不等于放水）：%s"
                           % (tag, lv, "；".join(want["fold_mismatch"][:3])))
        inject_want(guard, want, (tag, lv))
        ok, payload = go_candidates(lv, spec)
        if not ok:
            fields = handle_go_fail(tag, lv, ops, per_op, directions, skills,
                                    payload, (tag, lv), rp)
            return fields, want
        inject(guard, payload, (tag, lv))
        b, fields = compare_case(tag, lv, want, payload, seen, printed)
        bad += b
        guard.note(fields)
        seen["比较次数"] += 1
        seen["名单里的干员"] += len(ops)
        return fields, want

    def handle_py_fail(tag, lv, spec, exc, where):
        """**oracle 自己算不出来**（例如 `enemy_arrivals` 在敌人属性库里查不到
        某只怪）⇒ 这一例**判不了**，**不是判红**。

        ★ 两个因分开报：Go 也取不到 ⇒ 数据缺（两侧同命）；Go 取得到 ⇒
        **期望值缺**——那是覆盖洞，不是分叉（判据没有资格拿一份不存在的
        期望值去判别人的对错）。两者都**不判红**，各自具名登记。
        ★ 顺带一提：这一支**每次跑都会重算**，所以哪天数据补齐了它会自己消失。
        """
        nonlocal bad
        detail = "%s: %s" % (type(exc).__name__, str(exc)[:110])
        ok, payload = go_candidates(lv, spec)
        if ok:
            data_missing.append("%s/%s **期望值缺**（Python 算不出，Go 算得出）：%s"
                                % (tag, lv, detail))
        else:
            data_missing.append("%s/%s 两侧都算不出（Go：%s；Python：%s）"
                                % (tag, lv, str(payload)[:70], detail))
        seen["判不了的例数"] += 1
        return set()

    def handle_go_fail(tag, lv, ops, per_op, directions, skills, err, where,
                       roster_path=None):
        """Go 取不到这一关：**先分清「数据缺」与「代码分叉」**（见文件头坑①）。"""
        nonlocal bad
        dp = path_of.get(lv)
        before = bool(dp) and level_cache_path(dp).is_file()
        if G.mode == GB.CHECK:
            #: 冻结档跑不动 Python（拦截器封死了）。这一支**具名**说明，
            #: 不许把它读成「数据缺」——冻的那批里有关卡，说明录基线时数据在。
            bad += 1
            printed.append(
                "✗ %s/%s Go 取不到（%s）。**冻结档下分辨不了「数据缺」与"
                "「代码分叉」**（那一支要现场调 Python），按判红报。"
                % (tag, lv, str(err)[:110]))
            return {"Go 拒绝"}
        try:
            G.expect(key(tag, lv, roster_sha),
                     lambda: py_expect(lv, ops, per_op, directions, skills,
                                       roster_path=roster_path or ROSTER))
            py_ok, py_err = True, ""
        except Exception as exc:                               # noqa: BLE001
            py_ok, py_err = False, "%s: %s" % (type(exc).__name__, exc)
        after = bool(dp) and level_cache_path(dp).is_file()
        if not py_ok:
            data_missing.append("%s/%s（Go：%s；Python：%s）"
                                % (tag, lv, str(err)[:80], py_err[:80]))
            if before != after:
                py_fetched.append("%s/%s（Python 在这一跑里新建了缓存）" % (tag, lv))
            return set()
        if after and not before:
            #: 文件是**这一次**才出现的 ⇒ 数据本来是缺的，Python 顺手补齐了。
            py_fetched.append("%s/%s（Python 顺手补齐了缓存 ⇒ 数据本来是缺的）"
                              % (tag, lv))
            return set()
        bad += 1
        printed.append("✗ %s/%s **真分叉**：Go 取不到（%s）而 Python 取到了，"
                       "且缓存文件在 Go 调用前后**都在场** ⇒ 不是数据缺"
                       % (tag, lv, str(err)[:120]))
        return {"Go 拒绝"}

    # ------------------------------------------------------ S1 主对拍（逐关）
    for n, rec in enumerate(to_cmp):
        if n and n % 25 == 0:
            #: 进度进 **stderr**：stdout 那半是要被 `结论：` 抠行的读数，
            #: 掺进进度会让「这一跑跑到哪了」与「判决是什么」互相污染。
            sys.stderr.write("  … 主对拍 %d / %d 关\n" % (n, len(to_cmp)))
            sys.stderr.flush()
        run_one("main", rec["level"], MAIN_OPS, 6, DIRECTIONS, {},
                go_spec(MAIN_OPS, 6, DIRECTIONS, {}))

    # ------------------------------------------------------ S2~S5 变体（样本关）
    names_all = all_names()
    for (tag, ops, per_op, dirs, skills, omit_dirs) in variant_cases():
        use_ops = names_all if ops is None else ops
        spec = go_spec(use_ops, per_op, dirs, skills, omit_dirs=omit_dirs)
        for rec in sample:
            lv = rec["level"]
            if skip_in_check(tag, lv, roster_sha):
                continue
            run_one(tag, lv, use_ops, per_op, dirs, skills, spec)

    # ------------------------------------------------------ S6 名册路径不存在
    if ABSENT_ROSTER.exists():
        bad += 1
        printed.append("✗ 名册缺失那一支用的路径竟然存在：%s（这一支作废）"
                       % ABSENT_ROSTER)
    else:
        want6 = G.expect(("candidates", "badroster", ABSENT_ROSTER.name),
                         lambda: py_bad_roster(ABSENT_ROSTER))
        lv_bad = sample[0]["level"] if sample else "main_01-07"
        ok, payload = go_candidates(
            lv_bad,
            go_spec(MAIN_OPS, 6, DIRECTIONS, {}, roster=ABSENT_ROSTER))
        if want6.get("accept"):
            bad += 1
            printed.append("✗ 名册缺失但 Python 收下了 —— 这一支的前提不成立")
        elif ok:
            bad += 1
            printed.append("✗ 名册缺失而 Go 收下了（空名册与「这个号一个干员都没有」"
                           "长得一模一样）")
        elif "名册" not in str(payload):
            #: ★ **拒的理由也要对**：关卡读不到也会让 Go 拒，而那种拒
            #: 与「名册读不动」长得一样（都是 ok=false）——不区分就是一处假绿。
            bad += 1
            printed.append("✗ 名册缺失那一支：Go 确实拒了，但**理由不是名册**：%s"
                           % str(payload)[:120])
        else:
            diverged.append("名册路径不存在：两侧都拒（Go：%s）" % str(payload)[:80])

    # ------------------------------------------------------ S7 合成名册
    with tempfile.TemporaryDirectory(prefix="rios-syn-roster-") as td:
        syn = Path(td) / "syn_roster.json"
        syn.write_text(json.dumps(SYN_ROSTER_ROWS, ensure_ascii=False),
                       encoding="utf-8")
        syn_sha = GB.file_sha16(syn)
        for rec in sample[:2]:
            lv = rec["level"]
            if skip_in_check("synroster", lv, syn_sha):
                continue
            _f, want = run_one(
                "synroster", lv, SYN_OPS, 6, DIRECTIONS, {},
                go_spec(SYN_OPS, 6, DIRECTIONS, {}, roster=syn),
                roster_path=syn, rsha=syn_sha)
            #: 夹具**自证行使**：这两条分支没被走到 ⇒ 夹具不再覆盖它。
            wc = (want or {}).get("covered") or {}
            if want and (int(wc.get("entry_missing", 0)) < 2
                         or int(wc.get("unit_failed", 0)) < 1):
                bad += 1
                printed.append("✗ 合成名册没走到 entry_missing/unit_failed：%r"
                               % {k: wc.get(k) for k in
                                  ("operators", "entry_missing", "unit_failed",
                                   "no_char_id")})

    # ------------------------------------------- S10 自身格（9 个缺 (0,0) 的代号）
    #: 这 9 位干员的范围代号都在「grids 不含自身格」那一组里（`SELFCELL_OPS`）。
    #: 单独摆一份名单，是为了让这条分歧**必然**被走到——真夹具的名册里只有
    #: 提丰一位命中，而且它的落位未必压在敌人的路上（`cells` 会差，`dwell` 不一定）。
    with tempfile.TemporaryDirectory(prefix="rios-selfcell-") as td:
        sc = Path(td) / "selfcell_roster.json"
        sc.write_text(json.dumps(
            [{"id": cid, "name": nm, "elite": 2, "level": lv, "potential": 6}
             for nm, cid, lv in SELFCELL_OPS], ensure_ascii=False),
            encoding="utf-8")
        sc_ops = [nm for nm, _c, _l in SELFCELL_OPS]
        sc_sha = GB.file_sha16(sc)
        for rec in sample[:2]:
            lv = rec["level"]
            if skip_in_check("selfcell", lv, sc_sha):
                continue
            run_one("selfcell", lv, sc_ops, 6, DIRECTIONS, {},
                    go_spec(sc_ops, 6, DIRECTIONS, {}, roster=sc),
                    roster_path=sc, rsha=sc_sha)

    # --------------------------------- S8 per_op<=0：两侧统一到「六个候补位」
    #: ★ **2026-09-27 博士裁定：六个候补位。** `per_op <= 0`（没给／显式给 0／
    #: 给负数）在**两侧一律按 6**，不再有第二种解释。
    #:
    #: 在此之前这里登记的是一处**分歧**：引擎的契约本来就是「0 ⇒ 缺省 6」
    #: （`candidates.go:217-220` 的 `defaultPerOp`），而 Python 的 `candidates_for`
    #: 是「先 append 再判 `len(kept) >= per_op`」⇒ 显式收下 0 时**每位只留 1 条**。
    #: 同一个输入在两边得到不同的候选数，是「两份实现」最典型的漂移形状。
    #:
    #: 现在 Python 入口也把它并到 `DEFAULT_PER_OP`（`ak_tactic/search.py`）
    #: ⇒ 这一支从「登记分歧」改成**断言**：拿 `per_op=0` 与 `per_op=6` 各问一次
    #: 两侧，要求**四个读数两两相等** ——
    #:
    #:     Go@0 的候选条数 == Go@6 的候选条数      （引擎侧真的按 6）
    #:     Go@0 的 kept     == Go@6 的 kept        （自报的行使计数也一致）
    #:     顺序（身份键序列）逐索引相同             （稳定排序那条没被搅动）
    #:     逐字段**精确**相等                       （value 也是 —— 排序键就是这个量）
    #:
    #: ⚠ 这里的浮点**不吃** `FLOAT_REL_TOL`：它比的是**同一位实现的两个输入**，
    #: 不是跨实现的累加序，所以「精确相等」在这里是可达的，加容差就是放水。
    #:
    #: ★ **冻结档不吃新键**：右侧的期望值用的是**已经冻着的那一份**（`per_op=6`
    #: 的 key），不是新造一个 `per_op=0` 的 key。理由是裁定的内容本身就是
    #: 「这两个输入同解」——它由这一条断言**现算**，不需要另存一份答案；
    #: 另存一份反而会把「同解」这个结论冻成数据，将来两侧一起漂走也看不见。
    lv0 = sample[0]["level"] if sample else None
    if lv0 is not None and not skip_in_check("perop0", lv0, roster_sha):
        zero_fields, zero_want = run_one(
            "perop0", lv0, MAIN_OPS, 6, DIRECTIONS, {},
            go_spec(MAIN_OPS, 0, DIRECTIONS, {}))
        if zero_fields:
            bad += 1
            printed.append("✗ perop0/%s `per_op=0` 与权威的**缺省口径**（六个候补位）"
                           "不一致（撞出的字段：%s）"
                           % (lv0, "、".join(sorted(zero_fields))))
        #: 期望值那一份 = **per_op=6**（同一关、同一名册 ⇒ 同一个 key，且**已冻**）。
        six_want = want_cache.get(("main", lv0)) or {}
        six_rows = six_want.get("rows") or []
        six_cov = six_want.get("covered") or {}
        ok0, res0 = go_candidates(lv0, go_spec(MAIN_OPS, 0, DIRECTIONS, {}))
        ok6, res6 = go_candidates(lv0, go_spec(MAIN_OPS, 6, DIRECTIONS, {}))
        if not (ok0 and ok6):
            bad += 1
            printed.append("✗ perop0/%s 这一支问不动引擎：per_op=0 → %r；per_op=6 → %r"
                           % (lv0, str(res0)[:90], str(res6)[:90]))
        elif not (six_rows and six_cov):
            #: 主对拍的期望值缺 ⇒ 这一条**判不了**（不是判红）。具名登记。
            data_missing.append("perop0/%s 两侧一致的断言取不到参照（per_op=6 的"
                                "期望值不在手上）" % lv0)
        else:
            r0 = res0.get("rows") or []
            r6 = res6.get("rows") or []
            c0 = res0.get("covered") or {}
            c6 = res6.get("covered") or {}
            seen["perop_zero"] += 1
            #: ---- ① 四个读数两两相等（就在这一条里现算，不写死）
            eq = [
                ("候选条数", len(r0) == len(r6), "%d vs %d" % (len(r0), len(r6))),
                ("kept", int(c0.get("kept", -1)) == int(c6.get("kept", -1)),
                 "%r vs %r" % (c0.get("kept"), c6.get("kept"))),
                ("顺序", [_row_key(r) for r in r0] == [_row_key(r) for r in r6],
                 "第 %s 条" % _first_key_diff(
                     [_row_key(r) for r in r0], [_row_key(r) for r in r6])),
                ("逐字段", _rows_bit_equal(r0, r6), ""),
            ]
            for _what, _good, _detail in eq:
                if _good:
                    continue
                bad += 1
                printed.append(
                    "✗ perop0/%s `per_op=0` 与 `per_op=6` 的**%s**不同（%s）—— "
                    "「六个候补位」这条口径在引擎自己身上就没成立"
                    % (lv0, _what, _detail))
            #: ---- ② 两侧（Go@0 ↔ Go@6 ↔ 权威@6）确实落在同一批对象上。
            #: 权威那一侧只用 `len`/键序，**不逐字段**：逐字段已经在
            #: `run_one("perop0", …)` 里比过（那次比的就是 Go@0 ↔ 权威@6）。
            wkeys = [_row_key(r) for r in six_rows]
            if len(r0) != len(six_rows) or [_row_key(r) for r in r0] != wkeys:
                bad += 1
                printed.append(
                    "✗ perop0/%s Go@0 与**权威**@6 不是同一批：%d 条 vs %d 条"
                    "（键序首个不同在第 %s 条）"
                    % (lv0, len(r0), len(six_rows),
                       _first_key_diff([_row_key(r) for r in r0], wkeys)))
            else:
                diverged.append(
                    "`per_op <= 0`（**2026-09-27 裁定：六个候补位**）：`per_op=0` 与 "
                    "`per_op=6` 在**两侧都同解** —— Go 候选 %d 条 / kept=%r、"
                    "Python 同样 %d 条（顺序逐索引相同、逐字段精确相等；"
                    "Python 入口把它并到 `DEFAULT_PER_OP`，"
                    "引擎侧本来就是 `defaultPerOp`）。"
                    "从「登记分歧」改成断言：不成立即红。"
                    % (len(r0), c0.get("kept"), len(six_rows)))
            #: ---- ③ **负对照**：把 Python 侧的老行为（0 ⇒ 每位只留 1 条）人为
            #: 装回去，上面那条断言必须当场判红。装不回来也判红——没有负对照的
            #: 「相等」证明不了任何事（本仓那条「两把相同的尺子互证」）。
            if guard.want(MUT_PEROP0):
                old_py0 = legacy_py0_rows(six_rows)
                if len(old_py0) >= len(six_rows):
                    bad += 1
                    printed.append("✗ 负对照「%s」没装成：旧行为下 %d 条、"
                                   "现口径下 %d 条（没有变短 ⇒ 这个对照作废）"
                                   % (MUT_PEROP0, len(old_py0), len(six_rows)))
                else:
                    guard.put(MUT_PEROP0, "perop0/%s" % lv0)
                    if old_py0 == six_rows:
                        bad += 1
                        printed.append("✗ 负对照「%s」装了却**判不出来**："
                                       "旧行为与现口径的 rows 完全相同"
                                       % MUT_PEROP0)
                    else:
                        guard.caught[MUT_PEROP0] = True
                        #: ⚠ 这一行走**独立通道**（直接 print，不进 `printed`）：
                        #: `printed` 有 60 行上限，负对照落在整篇的哪个位置不确定，
                        #: 被挤掉就等于「判红」这条读数没有留证。
                        perop_notes.append(
                            "负对照「%s」：把 Python 的 `per_op<=0` 装回旧行为"
                            "（每位只留 1 条）⇒ %d 条 ≠ 现口径 %d 条 ⇒ 这一条断言"
                            "当场判红 ✓" % (MUT_PEROP0, len(old_py0), len(six_rows)))

    for line in printed:
        print(line)
    if printed:
        print("（上面 %d 行是失配样例；整篇最多印 %d 行，"
              "**另 %d 处已判红但没印** —— 完整计数见下面那几行读数）"
              % (len(printed), PRINT_CAP, printed.dropped))
    #: ★ 下面这几行**不受印数上限**：它们是「断言真的活过 ＋ 真的判得红」的留证。
    for _n in perop_notes:
        print("  " + _n)
    print()

    #: ★ 天赋面板倍率那一处**已登记的口径差**：两条腿都要成立 ——
    #: ① 它真的被行使了（有候选落在这类干员上）；② 折算之后两侧逐位相等
    #: （那一条由 `compare_case` 的 `value` 栏保证，除不掉时已在上面报红）。
    if seen["天赋折算的候选条数"]:
        diverged.append(
            "**天赋面板攻击力倍率**（2026-09-24 已登记的口径差，原文在 "
            "`tools/check_operator_go.py:788-799`）：Go 把天赋的面板倍率折进了 "
            "`total`（`rios-sim/talentpanel.go`），Python 一个都不折 ⇒ "
            "`value = dwell × unit.atk` 在两侧是**两个量**。本次 %d 条候选落在"
            "这类干员上（能天使 +8%%、焰狐龙梓兰 +15%%、赤刃明霄陈 +16%%）。"
            "判据按那一套的同一处置办：把两边因子统一到同一个量再比"
            "（`期望 = Python 的 atk × (1 + 比例)`，比例取自 Go 的 `opstats`），"
            "**除不掉仍按原样报红**。" % seen["天赋折算的候选条数"])

    # ------------------------------------------------------ 读数
    print("已比：主对拍 %d 关；共 %d 次比较（%d 位干员次）；"
          "候选 %d 条；字段比较 %d 次 ＋ covered 键比较 %d 次"
          % (seen["关卡"], seen["比较次数"], seen["名单里的干员"],
             seen["候选条数"], seen["字段比较"], seen["covered 键比较"]))
    print("★ 行使计数（**尺子**那一份，与 Go 自报的 covered 逐关比过）：%s"
          % ", ".join("%s=%d" % (k, seen[k]) for k in
                      ("visits_zero", "all_candidates", "kept", "melee_ops",
                       "ranged_ops", "entry_missing", "unit_failed",
                       "not_in_spots", "positions_tried", "no_char_id",
                       "range_missing", "empty_range", "atk_missing",
                       "被 per_op 截断的关数", "顺序不一致", "value 自检不过",
                       "天赋折算的候选条数", "判不了的例数", "自身格分歧条数",
                       "自身格分歧并带动 dwell/visits", "dwell 逐位不同的条数",
                       "其中 cells 也不同", "其中 cells 相同（纯累加序）",
                       "ulp 距离 <= 2", "容差内收下", "perop_zero")))
    print()
    #: ★★ 这一处**没有裁定过**，所以它是**判红**（不是登记分歧）。
    #: 把根因、两侧的原文出处、影响面一次讲清——红要红得能直接照着改。
    if seen["自身格分歧条数"]:
        print("★ 自身格分歧（**未裁定 ⇒ 判红**）：%d 条候选的 `cells` 恰好差"
              "「干员所在的那一格」（Python 有、Go 没有），其中 %d 条的 "
              "`dwell`/`visits` 也跟着不同 ⇒ 会继续影响 `value` 与排序。"
              % (seen["自身格分歧条数"], seen["自身格分歧并带动 dwell/visits"]))
        print("  根因（两侧原文）：`excel/range_table.json` 73 个范围代号里有 9 个的"
              " `grids` **不含自身格 (0,0)**（1-5、2-7、3-16、4-13、4-3、4-4、"
              "4-5、4-6、4-7）；")
        print("    Python：`battle/range.py:140-141` 在 `block_of(...) > 0` 时"
              "**补上 (0,0)**，而 `verify.py:214-215` 传的是 "
              "`block_of=lambda c, e: 1` ⇒ **每一位干员都补**；")
        print("    Go：`candidates.go` 直接 `Footprint(base, d, x, y)`，"
              "依赖 `range.go:18-20` 那句「自身格 (0,0) 已经在 grids 里」"
              "——那句话对这 9 个代号**不成立**。")
        print("  影响面：460 位干员里 **%d 位**（%s）。"
              % (len(SELFCELL_OPS), "、".join(n for n, _c, _l in SELFCELL_OPS)))
        print()
    if data_missing:
        print("★ **判不了**（oracle 自己取不到 / Go 与 Python 都取不到 ⇒ 都不算判据红）：")
        for s in data_missing[:8]:
            print("    · %s" % s)
        if len(data_missing) > 8:
            print("    （共 %d 例，只印前 8）" % len(data_missing))
    if py_fetched:
        print("★ Python 顺手补齐（引擎的 gamedata 是按需下载的 ⇒ 不是代码分叉）：")
        for s in py_fetched[:5]:
            print("    · %s" % s)
    print()
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
    #: ★★ 累加序那一处**已登记**（2026-09-27 裁定：按登记走、不修产品）。
    #: 但**登记 ≠ 不看不报**：无论收不收下，最大相对差与超出条数都要印出来，
    #: 将来真出现一个「大的数值改动」（不是累加序那种量级）这条仍然判红。
    _over = seen["dwell 逐位不同的条数"] - seen["容差内收下"]
    if seen["dwell 逐位不同的条数"] or FLOAT_STATS["超容差条目"]:
        print("★ 累加序分歧（**已登记 ⇒ 按相对容差比**）：%d 条候选的 `dwell` "
              "**逐位**不同；其中 **%d 条连 `cells` 都完全相同**（纯累加序所致）、"
              "%d 条是自身格那一处带来的；%d 条差的 ulp 距离 ≤ 2。"
              % (seen["dwell 逐位不同的条数"],
                 seen["其中 cells 相同（纯累加序）"],
                 seen["其中 cells 也不同"],
                 seen["ulp 距离 <= 2"]))
        print("  ★ **超容差与最大相对差**（登记不等于不报）：dwell 这一族超容差 "
              "**%d** 条（dwell 共 %d 条逐位不同、其中 %d 条落在容差里）；"
              "浮点两栏（dwell ＋ value）**全部比较**里超容差 **%d** 条"
              "（其中 `cells` 相同、纯粹是差得太大 %d 条；`cells` 本来就不同、"
              "不在登记范围 %d 条）、最大相对差 **%.6g**。"
              % (_over, seen["dwell 逐位不同的条数"], seen["容差内收下"],
                 FLOAT_STATS["超容差条目"], FLOAT_STATS["超容差且cells相同"],
                 FLOAT_STATS["超容差且cells不同"], FLOAT_STATS["最大相对差"]))
        if FLOAT_STATS["最大相对差样例"]:
            print("    最大相对差那一条：%s" % FLOAT_STATS["最大相对差样例"])
        print("  容差口径（写死在这里）：`相对差 <= %g × max(1, visits)`，"
              "**两栏同一条**（`dwell` 与 `value`；`value = dwell × 攻击力`，"
              "dwell 的 ulp 差会原样派生过去 ⇒ 只给一栏开口等于把红挪到另一栏）。"
              % FLOAT_REL_TOL)
        print("    ★ 开口的**范围**：只在「`cells` **完全相同**」时成立 —— 登记的就是"
              "**纯累加序**那一条（同一个格集合、两种迭代序）。`cells` 都不同了，"
              "浮点差就不再有「累加序」这个解释 ⇒ 照旧判红（自身格那处因此仍占红）。")
        print("    为什么是**相对**不是绝对：这处的绝对差随 visit 条数增长"
              "（叠几千条 visit 能累到几千 ulp），而 dwell 本身同尺度地变大 ⇒ "
              "绝对口径会把「大 dwell 的小相对漂移」与「小 dwell 的大相对漂移」"
              "判成同一件事。相对差是本征稳定的量。")
        for _s in FLOAT_STATS["收下样例"][:3]:
            print("    例（容差内收下）：%s" % _s)
        for _s in DWELL_SAMPLES:
            print("    · %s" % _s)
        print("  根因（**已核实到机制**，不是猜）：`ArrivalIndex.dwell` 的累加序 = visit 的"
              "拼接序；两侧都按 `enter` **稳定**排序，可一旦有多条 visit 的 `enter` 相等，"
              "稳定排序保留的就是**拼接序**，而拼接序由**格集合的迭代序**决定——")
        print("    Python：`_range_cells` 返回 `frozenset`（`search.py:109`）⇒ 迭代序是"
              "**哈希序**，`dwell` 就按那个序累加；")
        print("    Go：`candidates.go` 把格去掉重复后**按 (x, y) 排序**再喂 `dwell`。")
        print("  实测（同一个格集合，两种迭代序各累加一遍；这是**纯 Python 复算**，"
              "不依赖本判据自己）：")
        print("    easy_10-11 阿米娅 (6,1) Down：frozenset=434.14285714285671 / "
              "排序=434.1428571428566（判据读到 Go=…566、Python=…567；ulp 距离 2）")
        print("    act31side_ex08 能天使 (7,3) Left：frozenset=854.91414134972536 / "
              "排序=854.91414134972513（判据读到 Go=…51、Python=…54；ulp 距离 2）")
        print("    easy_11-11 焰狐龙梓兰 (1,2)：ulp 距离 1")
        print("  ⇒ `candidates.go` 文件头那句「`frozenset` ⇒ 顺序无意义，这里排过序只是"
              "为了输出确定」对**浮点累加**不成立：`visits()` 的稳定排序只保证 `enter` "
              "不同的那些有序，`enter` 相同的那些保持拼接序。")
        print("  ⇒ 2026-09-27 裁定：**按登记走、不修产品**。那条注释仍然误导人，"
              "但它不是本次施工范围。")
        print()
    for _r in cov_reports:
        print(_r)
    if diverged:
        print("★ 已登记的分歧（要求两侧的行为**同时**成立，不算对拍失败）：")
        for d in diverged:
            print("    · %s" % d)
        print()

    # ------------------------------------------------------ 守卫与结论
    if mutate:
        for k in MUT_KEYS:
            print("  变异「%s」：注入=%s 判红=%s"
                  % (k, "是" if k in guard.applied else "否",
                     "是" if guard.caught.get(k) else "否"))
        miss = [k for k in MUT_KEYS
                if k not in guard.applied or not guard.caught.get(k)]
        if miss:
            print("反向守卫：不成立 ✗（没做到「注入过并且判红」：%s）"
                  % "、".join(miss))
            return 1
        print("反向守卫：十二处独立变异（含三处 1 ulp，其一改的是**期望值**；"
              "另一处是 `per_op<=0` 的负对照）各判红 —— 成立 ✓")
        return 0

    #: 判据自己瞎不瞎：这几条一 0，下面的「一致」就没有信息量。
    for k, why in (("visits_zero", "dwell<=0 被剪掉的落位"),
                   ("all_candidates", "剪枝之后留下的候选"),
                   ("not_in_spots", "不是这位干员能站的格"),
                   ("positions_tried", "真的试过的落位"),
                   ("melee_ops", "近战干员"),
                   ("ranged_ops", "远程干员"),
                   ("entry_missing", "名册里没有的名字"),
                   ("被 per_op 截断的关数", "per_op 截断真的发生过"),
                   ("perop_zero",
                    "`per_op=0` 与 `per_op=6` 两侧一致那条断言真的跑到了"),
                   ("天赋折算的候选条数",
                    "落在带天赋面板攻击力的干员上的候选（已登记口径差的行使）")):
        if seen.get(k, 0) == 0:
            print("结论：%s（%s）一例都没走到 —— 判红（不是实现错，是判据自己瞎）"
                  % (why, k))
            return 1
    if seen["value 自检不过"]:
        print("结论：`value` 不等于 `dwell × 攻击力`（%d 条） —— 判红："
              "两侧同源的自检，它管的正是「对拍看不见的那种同时改错」"
              % seen["value 自检不过"])
        return 1
    #: ★ 结构零分支：**每跑一次都重量一遍**（不是写死一句「不可达」）。
    #: 非 0 ⇒ 红，红的意思是「它现在有行使，必须补一份样本」。
    for k in sorted(STRUCT_ZERO):
        if seen.get(k, 0):
            print("结论：结构零分支「%s」**变成可达了**（%d 例） —— 判红："
                  "它现在有行使，必须补一份样本；不是实现错"
                  % (STRUCT_ZERO[k], seen[k]))
            return 1
    print("★ 结构零（现算，非写死）：%s（Go 自报与尺子两侧同口径）"
          % "、".join("%s=0" % k for k in sorted(STRUCT_ZERO)))
    print("结论：候选生成 %d 关逐字段一致（共 %d 次比较、候选 %d 条、"
          "字段比较 %d 次；visits_zero=%d、被 per_op 截断的关数=%d、"
          "顺序不一致=%d）"
          % (seen["关卡"], seen["比较次数"], seen["候选条数"],
             seen["字段比较"], seen["visits_zero"],
             seen["被 per_op 截断的关数"], seen["顺序不一致"]))
    if bad:
        #: ★ 累加序那一处**已登记**（2026-09-27）⇒ 只有在**超容差**时它才是红的
        #: 一因；落在容差里的那些不再进 `bad`，因此也不能在这里被念成「不成立」。
        if seen["dwell 逐位不同的条数"] - seen["容差内收下"]:
            print("结论：**不成立** —— 另有 %d 条候选的 `dwell` 逐位不同**且超出"
                  "已登记分歧的容差**（另有 %d 条落在容差里，见上面那一段的"
                  "最大相对差读数）"
                  % (seen["dwell 逐位不同的条数"] - seen["容差内收下"],
                     seen["容差内收下"]))
        if seen["自身格分歧条数"]:
            print("结论：**不成立** —— %d 条候选的 `cells` 差「干员所在的那一格」"
                  "（Python 有、Go 没有，%d 条并带动 dwell/visits）；"
                  "未裁定，按判红报（根因见上面那一段）"
                  % (seen["自身格分歧条数"],
                     seen["自身格分歧并带动 dwell/visits"]))
        #: 比过的部分**真的不一致** ⇒ 判据红，优先于「基线该重录」。
        return 1
    if G.mode == GB.CHECK and cov_reports:
        #: 比过的部分一致，但**对象集变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
