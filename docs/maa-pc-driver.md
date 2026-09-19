# MAA 实机线：PC 端驱动结论（A/B/C 对照组）

> 定稿时间 2026-09-20。产物（截图/轨迹/日志）留在 `..\tmp\maamcp`（**不入库**），本文档入库。

## 一句话结论

驱动《明日方舟》PC 端（Win32 窗口）**必须用 `SendMessageWithCursorPos`**：`SendMessage` 与 `PostMessage` 都能被 MAA 判定为"点过了"，但**游戏不响应**——它们的点击落在消息队列里，而游戏读的是**真实光标位置**。

## 配方（三缺一即静默失败）

| 开关 | 取值 |
|---|---|
| `ScreencapMethod` | **`PrintWindow`** |
| `MouseMethod` | **`SendMessageWithCursorPos`** |
| 会话可交互 | **`SetCursorPos` 必须可用**（RDP 断开/锁屏即失效） |

驱动路径：`AsstLoadResource` → `AsstCreate` → `AsstSetConnectionExtras("Win32Extra", extras)` → **`AsstAttachWindow`**。
（`AsstConnect` 是 ADB 专用、对本场景是死路；`config.json` 里 15 条连接配置全是 ADB。）

## 观察栏（实测）

| 组 | `mouse` | 次数 | 起点三态 | 点击后三态 | 光标轨迹 |
|---|---|---|---|---|---|
| A | `SendMessage` | 2 | PASS | **PASS（画面像素级不变）** | **1 个事件：仅 (343,1061)，不动** |
| B | `PostMessage` | 2 | PASS | **PASS（画面像素级不变）** | **1 个事件：仅 (343,1061)，不动** |
| C | `SendMessageWithCursorPos` | 2 | PASS | **RED（画面变了）** | **3 个事件：(343,1061)→(910,798)/(907,801)→(343,1061)** |

**链日志：A/B 与 C 是两种形态**

* **C**：`StageInList` OCR 命中 `HS-4`（rect `[514,451,74,24]`，score 0.981，**`exec_times=1`**）→ 点 → `ClickedCorrectStageOrSwipe` 认出「开始行动」`[1126,645,104,26]`（score 0.99999）→ `ClickedCorrectStage` 认出 `HS-4` `[922,82,88,27]` → **`TaskChainCompleted`**。
* **A/B**：`StageInList` OCR **稳定命中同一个 `HS-4`**（rect 在 `[517,451,71,24]` / `[520,451,68,24]` 之间抖，**score 0.994~0.996**），`ClickSelf` 的 **`exec_times` 一路涨到 53+ 仍在涨**，**无任何 `TaskChainCompleted`**，60 s 超时截断。

**⇒ A/B 的一行价值：「不是没点击」。** 若只看帧，"点过但没响应"与"根本没点"无法区分；`exec_times` 递增 + OCR 稳定命中正是二者的判别依据。

## 三种失败（分行，不可压成一个）

| 失败形态 | 本轮结果 |
|---|---|
| 没点击 | **无** |
| **点击了但游戏没响应** | **A（2/2）、B（2/2），共 4 次** |
| 点击了、响应了、但不是我们要的动作 | **无** |

## 推断栏（**不是**本轮实测）

本文档的因果解释是推断，与上面的观察分列：

* **推断**：游戏读**真实光标位置**，消息式点击（`lParam` 带客户区坐标）**不带位置**，因此被忽略。
* **证据强度**：观察支持该推断（A/B 光标不动 → 不响应；C 光标动了 → 响应），**但没有构造出反向情形**。
* **可选的判别实验 D**（未做）：先把光标 `SetCursorPos` 挪到**错误的**屏幕位置（如 `(100,100)`），再用 `SendMessage` 带**正确的**客户区坐标点击。
  * 点不中 ⇒ 支持"游戏读真实光标"；
  * 点中 ⇒ **A/B 的失败另有原因，上述解释错误**。

## 坐标换算

* 客户区原点 **(343,342)**，客户区 **1280×720**；屏幕 = 客户区 + (343,342)。
* `SendMessage`/`PostMessage` 的 `lParam` 用 **`MAKELPARAM(cx,cy)` 客户区坐标**；`*WithCursorPos` 先 `SetCursorPos` 到**屏幕坐标**。
* **落点带几 px 抖动**：三次实测客户区落点 `(545,452)`、`(567,456)`、`(564,459)`（OCR rect 中心均在 ±3 px 内）。
  ⇒ **"同一落点"成立；"逐像素相同"不成立。** 两件事不合并写。
* **实测 vs 推算要分列**：屏幕 `(888,794)` 是**直接观测**（`SetCursorPos` 吃屏幕坐标）；客户区 `(545,452)` 是**由它减客户区原点推算**。换算若有误，错的是后者。

## 光标轨迹是方法指纹（取坐标的副产物）

`SendMessageWithCursorPos` 会先 `SetCursorPos` 再发消息 ⇒ **光标去哪就是它点了哪**（`GetCursorPos` 只读即可取证）。
因此**预注册光标预测可以判别点击方法**，且**预测错了不许改预测**。本轮两条预测（A/B"不动"、C"走到落点"）**全部命中**。

## 仪器身份

* MaaCore **v6.17.5**（`AsstGetVersion`），base `（本机 MAA 目录）` + 增量资源 `（本机临时目录）`
* 窗口 hwnd **`0x2203b4`**，`window rect=335,311-1631,1070 size=1296x759`
* `screen=1920x1080 fullscreen_area=1872x1057`；`offscreen=0px beyond_usable_h=13px`
* `SetCursorPos` 自检 **PASS**（正例移动 / 反例不动 / 复原，exit 0）
* 光标采样：`trial.py`，8 ms 轮询 `GetCursorPos`，记录**变化点**；子进程输出**落文件、不经 PowerShell 管道**
* 读图仪器：GLM-4.6V（`seev.py`），读图前先断言像素非空白

## 产物清单（均在 `..\tmp\maamcp`，不入库）

* 六次试验 `A1 A2 B1 B2 C1 C2` × {`-start.png`, `-after.png`, `-trace.jsonl`, `-click.log`, `-summary.json`, `-rst*.png`}
* 工具：`trial.py`（采样光标 + 起子进程）、`summarize.py`（从产物复原摘要）、`gate_family.py`（三态族判据）、`cursortrace.py`、`maacore.py`
* 注册表：`stage_list_family.json`（关卡列表族的成员锚帧与两个非成员）
* 增量资源：`maares/resource/tasks/Stages/ZZ-driver-extra.json`、`ZZ-driver-enter.json`

## 踩过的坑（都与上面结论无关，但会伪装成它）

1. **A/B 组曾整轮作废**：把 python 输出接进 PowerShell 管道（含 `| Out-Null`）触发 `拒绝访问`，复位与拍帧**一条没执行**。⇒ **"我的命令坏了"≠"Send 被拒"**。
2. **增量资源顶层写了一个字符串值** ⇒ `AsstLoadResource -> False`、`append_task -> REFUSED`，**连带已有任务一起静默失效**；症状是后面每一步都照跑，只有一行 `False`。
3. **复位不是单步**：关卡列表之上还有"活动介绍页"，`Return` 只退到那一层（对族 MAD≈102 RED），需要再点「进入活动」。
4. **子进程管道 stdio 被沙箱拒绝**（`CreatePipe -> WinError 5`）⇒ 改真实文件句柄重定向。
5. **`print` 中文撞 GBK 控制台**会让脚本以 rc=1 收尾，**而产物其实已全部写好**——"产物没变"与"这轮根本没写完"要分开。
6. **判据要有灰带**：族判据 `MAD<3.0` 合格、`>20.0` 判红、**`3.0~20.0` 是灰带**（报警 + 定性 + 可登记），不压成一个红。关卡列表本身有**至少两个稳定视觉状态**，单一锚帧会假红。
