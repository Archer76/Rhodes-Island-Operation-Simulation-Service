# ak-tactic 验收报告

- 生成时间：2026-09-19 21:57:15
- 执行者：验收与守卫会话 `session-1a45cfee-9a65-4830-a327-03ac84285bfb`（命令：`python tools/acceptance.py`）
- 判定：**通过 7 / 失败 0 / 未跑 1**，退出码 **0**，总耗时 2.7 分钟
- 测量对象：HEAD `38c04eb4f768`，脏文件 46 条

> ⚠ **测量期间工作树被改动**：HEAD 9b18763093bd → 38c04eb4f768；脏文件清单变化（48 → 46 条） ⇒ 本轮数字不对应单一版本，跨轮次比数量之前必须重跑。

## 一、逐项实测

| # | 项 | 状态 | 本轮实测 | 上次基线 | 判据 |
|---|---|---|---|---|---|
| 1 | 仪器自检（Go 二进制） | 通过 | 私有构建 `rios-sim-2c68f2c6.exe`（`b88b28ce6d0ca14f`）；共享 exe 落后源码=True | — | 当前源码能构建出 Go 引擎二进制（-buildvcs=false） |
| 2 | 金标准（规格哈希 + 判决四数） | 通过 | 一致 17/17 份（spec_sha 含在内） | 17 | 与 out/golden_go.json 逐项一致（含 spec_sha），且基线文件未被改写 |
| 3 | 闸门放行抽查（go_fallbacks） | 通过 | 17 份 go_fallbacks=0，spec_error 0，与基线有差 0 | — | 每份计划 go_runs≥1、go_fallbacks==0、spec_error 为空、与基线四数一致 |
| 4 | 自检 check_battle（战斗与技能回归） | 通过 | 通过 816 项，失败 0 | 816 | 套件全过（无失败项），且项数不低于基线 |
| 5 | 自检 check_verify（验证器） | 通过 | 通过 71 项，失败 0 | 71 | 套件全过（无失败项），且项数不低于基线 |
| 6 | 闸门盲区审计 | 通过 | 登记 9 条（本轮扫出 2），未登记 0，守卫失效 0，自检过 | 未登记 0 | 未登记=0 且 守卫失效=0，且 --selftest 反向守卫成立 |
| 7 | 闸门能力清单（static） | 通过 | 已读取 10 / 已定义未读 1 / 未送 16（未读：积雪） | 未送 16 / 未读 1 | 未送/已定义未读的条目数进水位；「已定义未读」每条须能对上登记理由 |
| 8 | 对拍入口（已退役·仅登记） | 未跑 | 退役（仅登记） | — | 不作为验收手段（通告 #2 裁定；博士 2026-09-19 19:56 弃用 Python 模拟器） |

## 二、仪器身份（先验仪器，再谈结论）

- 私有构建（本门使用）：`rios-sim-2c68f2c6.exe` sha256 `b88b28ce6d0ca14f`，3,597,312 字节
- 共享二进制：sha256 `b3e4d6b1565d63b4`，构建于 09-19 19:08:28，落后于源码：**True**
- 规则：本门一律用私有构建（`RIOS_SIM_BIN` 指过去），**绝不覆盖共享二进制**——回写共享树会造成假红。

## 三、版本指纹（本轮数字属于哪一版）

| 文件 | sha256 前 16 位 |
|---|---|
| `ak_tactic/simgo/spec.py` | `7bc40802f71b8baa` |
| `ak_tactic/simgo/skills.py` | `af49d9c6cb17fb91` |
| `ak_tactic/simgo/verifier.py` | `804b892767d2e9b3` |
| `ak_tactic/verify.py` | `172b0315c6e99247` |
| `ak_tactic/battle/sim.py` | `d41e8fe6d4dbb040` |
| `ak_tactic/battle/unit.py` | `e2d3a15298db9e6b` |
| `rios-sim/sim.go` | `d7ff1d58b644e426` |
| `rios-sim/wire.go` | `739dd0a0af3fd48c` |
| `rios-sim/skill.go` | `37ad6dfc28a6417d` |
| `rios-sim/mech/mech.go` | `73cc56f641228181` |
| `rios-sim/mech/huai_shu_li.go` | `c70b943ac98d7ff8` |

## 四、水位比对（与上一次报告比）

- 无下降、无变化。

## 五、未跑项与原因（未跑 ≠ 通过）

- **对拍入口（已退役·仅登记）**（已登记，默认不参与判定）：对拍项退役：不作验收手段、不修 `sweep_hsl_parity` 那条路、不为它写新仪器。「8 关闸门拦下 / 3 关真差」改读**能力清单**（见上一项）。历史水位（不可复算）：怀黍离 20 关 = 9 关四项归零、8 关被闸门拦下、3 关真差根因未定

## 六、独立复核台账（「它说的」vs「我测的」）

## 独立复核台账（「它说的」vs「我测的」）

> 维护者：验收与守卫会话 `session-1a45cfee-9a65-4830-a327-03ac84285bfb`
> 规则：**不复核就不得替它背书**。每当有会话广播「某阶段完成」，独立复跑与该阶段相关的
> 验收项，把「它说的」与「我测的」并列写在这里；不符就点名会话、文件与数字。
> 本文件被 `tools/acceptance.py` 原样嵌进每轮的 `docs/acceptance-report.md`（标题降一级）。

### 格式

```
#### <日期> <会话> <阶段名>
- 它说的：<原话或摘要>（出处：会话广播 / 提交正文 / 进度文件第 N 节）
- 我测的：<命令 + 实测数字>
- 判定：一致 / 不符 / 部分覆盖（写明缺什么）
- 附录：<最小复现或反证>
```

---

#### 2026-09-19 首轮基线（**自测，不是替谁背书**）

- 它说的：无（首轮只建立基线，未替任何会话的阶段结论背书）
- 我测的：金标准 `--check` 17/17 一致（两台仪器：共享 exe `B3E4D6B1…`（19:08 构建）
  与当前源码私有构建 `18D68C1D…`）；`check_battle` 通过 816 项无失败；
  `check_verify` 通过 71 项无失败；闸门盲区审计未登记 0 / 守卫失效 0（登记表 9 条，
  本轮扫出 7 条）；审计反向守卫 `--selftest` 通过；闸门放行抽查 17 份
  `go_fallbacks=0`、`spec_error` 0 条。
- 判定：不适用（基线）
- ⚠ 未验证项：① 共享 `rios-sim.exe` 落后源码（19:08 vs 源码 21:33），本轮 17 份上
  两台仪器结论相同，故未造成假绿，但这条陈旧已在门里做成固定项；② 逐关对拍已退役
  （通告 #2），本门不复算；③ 测量期间工作树被其他会话改动（进度文件、`rios-sim/sim.go`
  等在测量窗口内仍有写入），报告头部会打出指纹差异。

#### 2026-09-19 RIOS后端 提交 `e0e7991`：控制类清单与战栗/沉睡/浮空

- 它说的（提交正文，逐条抄下）：① `gofmt -l control.go control_test.go` → 无输出；
  ② `go vet ./...` → 干净；③ `go test ./...` → `rios-sim` ok、`rios-sim/mech` ok 全绿；
  ④ 8 条守卫全 PASS（`TestAbnormalFlagListsAreExact` 等）；
  ⑤ 「本批全部**未接线**（无调用点）」；⑥ 新增 `rios-sim/control.go` 164 行、
  `control_test.go` 172 行、`docs/mechanics-dictionary.md` +20 行。
- 我测的（全部本轮亲手复算）：
  - `git diff --stat HEAD -- rios-sim/control.go rios-sim/control_test.go` → 空
    ⇒ 我测的文件与那个提交**逐字节同一份**，下面的数字才对得上它。
  - `gofmt -l control.go control_test.go` → **无输出** ✅ 与①一致
  - `go vet ./...` → **退出码 0** ✅ 与②一致
  - `go test ./...` → `ok rios-sim (cached)`、`ok rios-sim/mech (cached)` ——
    ⚠ **是缓存结果**。缓存只在输入未变时命中，所以不算错；但"复核"要的是**重跑**，
    故我用 `-count=1` 强制重跑（见下条）。
  - `go test -count=1 -v -run '<8 条>' .` → **8/8 PASS，`ok rios-sim 0.420s`** ✅ 与④一致
  - 未接线：`control.go` 里的 8 个函数（`blocksAttack` / `blocksAbility` / `blocksMove` /
    `trembleBlocksAttack` / `canDamageSleepingTarget` / `damageVsInvincible` /
    `levitateApplies` / `levitateDuration`）在 `rios-sim/*.go` 与 `rios-sim/mech/*.go`
    中**除 `control*.go` 外零调用点**（机械 grep）✅ 与⑤一致
- 判定：**一致**（五项自述逐项复核通过；唯一修正是"缓存"那一处口径，已用重跑覆盖）
- ⚠ 我**没有**复核的部分（别读成"整条提交都过了"）：判据本身的正确性——即
  `control.go` 里的三张清单是否与 PRTS `异常效果` 页原文逐字相符。我这轮只核了
  "它说的守卫都过、且确实没接线"，没核"守卫的判据抄得对不对"。要核需要原文比对，
  留待该阶段接线时一并做。

#### 2026-09-19 `tools/parity_plan.py`（`4fe187b` 重建入库）——**跑不起来**（最小复现）

- 它说的（通告 #2 第一节）："已从 RIOS终端UI_2 的会话日志按序重放 2 次 write + 3 次
  edit 重建终版（6025 字符、py_compile 通过），入库为 4fe187b"。
- 我测的：
  ```
  python tools\parity_plan.py plan-hsex08 --deploys 4
  → TypeError: GoCapture._run_other_engine() got an unexpected keyword argument 'schedule'
     （tools/parity_plan.py:116 → ak_tactic/verify.py:485）
  ```
  根因：`verify.py:485` 现在传 `schedule=sched, env=env`（round 9/10 加的），
  而重建版的 `GoCapture._run_other_engine(*, sim, plan, stage, deployed, title)`
  是**旧签名**。`import parity_plan` 本身没问题（`compare()` 存在），**一跑就断**。
  ⚠ 这正是进度 3.39 记过的那类："工具的红被读成代码的红"。`golden_go.py` 的
  `SpecCapture` 当时就是因为同一件事改成收 `**kw`（它的注释里写着理由）。
- 判定：**与"可复现证据"的用途不符**——文件在、`py_compile` 过，但**复现不了任何结论**。
  按通告 #2 第二节第 3 条，对拍项已退役、`sweep_hsl_parity` 那条路不修，
  所以这里**只登记不修**。
- ⚠ 提醒（写给出结论的人）：谁要拿 `4fe187b` 当"切换前 17 份四项全归零"的证据，
  得先把上面这个 `TypeError` 修掉、再跑通一次——**否则那段结论目前没有可复现的仪器**。
  我作为只读验收方不动这个文件。

#### 2026-09-19 项目经理通告 #2 落地检查

- 它说的：① 门的判定项改为 golden / check_battle / audit / 20 关 unsupported 能力清单；
  ② 共享 `rios-sim.exe` 任何人不得写回，一律私有构建 + `RIOS_SIM_BIN`；
  ③ `docs/` 与 `out/` 落点批准；④ 验收工件当轮入库。
- 我测的：① 已落地——第四项换成 `tools/gate_inventory.py` 的能力清单（本轮实测
  **已读取 10 / 已定义未读 1（积雪，已登记理由）/ 未送 16**，合计 27 条）；
  `check_verify` **保留**（博士原始交办的第二条自检水位，通告未提，若要去掉是一行改动）；
  ② 已落地——门第 0 项就是私有构建 + `RIOS_SIM_BIN`，共享 exe 只读不写（本轮实测共享
  exe 仍停在 19:08 构建，未被本会话触碰）；③、④ 见本文件同轮的提交。
- 判定：一致。

## 七、水位历史

- 2026-09-19 21:45:51 `fb0d1658cc7d` session-1a45cfee-9a65-4830-a327-03ac84285bfb（验收与守卫）：首轮实测建立基线：金标准17/17、check_battle 816、check_verify 71、审计9登记(扫出7)/0未登记、selftest通过
- 2026-09-19 21:50:41 `b05fee48d328` session-1a45cfee-9a65-4830-a327-03ac84285bfb（验收与守卫）：按项目经理通告#2 落地：第四项换为闸门能力清单（gate_inventory 三态）、对拍项退役仅登记；并记入 e0e7991 独立复核与 parity_plan 跑不起来的发现
- 2026-09-19 21:57:15 `38c04eb4f768` session-1a45cfee-9a65-4830-a327-03ac84285bfb（验收与守卫）：重建基线：上一轮被在途重构的瞬时断裂污染（金标准报 AttributeError、审计撞 activity.py 写锁），两处均为仪器问题；本轮已加「同种异常→重跑一次再定性」与「红轮不许改基线」两条修正

## 八、本门**不覆盖**什么（别把绿读成全绿）

- **逐关对拍**：已按项目经理通告 #2 **退役**（博士 2026-09-19 19:56 弃用Python 模拟器），本门不再把它当验收手段、不为它写新仪器；「8 关闸门拦下 / 3 关真差」改读**闸门能力清单**（第六项）。⚠ 已入库的 `tools/parity_plan.py`（4fe187b）实测**跑不起来**（`GoCapture._run_other_engine` 不接受 `schedule`，见台账）——谁要引它当证据，先自己跑通。
- **17 份计划没走到的路径**：金标准只覆盖这些计划上真跑出来的路径；没被走到的分支，它不说话——**覆盖不到机制的判据只会沉默，不会否证**。所以金标准绿 ≠ 所有机制都对。
- **保真**（两台引擎一起错）：本门问的是「Go 与基线一致」，**不问**「像不像真游戏」。`UNMODELLED_ENEMY_ABILITIES` 那 5 条属保真课题，不在本门判定内（裁定 `77fce667` 设的门槛只在一致性这一层）。
- **未跑到的自检分支**：`check_battle` / `check_verify` 报的是它们自己声明的项数；项数没降只说明「没变少」，不等于「新加的路径被考到了」。

## 九、怎么用这条门

```
python tools\acceptance.py            # 全套（金标准两趟 + 自检两项 + 审计 + 能力清单）
python tools\acceptance.py --quick    # 省掉「闸门放行抽查」那一趟（退出码记 2）
python tools\acceptance.py --update-baseline --by <会话> --why "<为什么>"
```

⚠ 三条铁律：① 未跑不许写成通过；② 水位降了就是红；③ 比数量前先确认工作树没被别人动过——报告头部的指纹差异段就是干这个的。

