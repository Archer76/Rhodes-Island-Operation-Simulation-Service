# 第三方来源、许可与合规说明

> 本文回答两个问题：**这个仓库用了别人的什么**、**有没有违反他们的规则**。
> 结论先给：**没有违规**。判据是两条——本仓库**不重新分发任何第三方内容**，
> 且**没有复制任何受传染性许可约束的代码**。
>
> 核验日期 2026-09-17；核验方式见文末「怎么重新核」。

---

## 一、一句话结论

| 问题 | 答案 |
| --- | --- |
| 仓库里有没有别人的代码？ | **没有。** 被跟踪的只有原创的 67 个 `.py`、19 个 `.md`、`LICENSE`、`.gitignore` |
| 仓库里有没有别人的数据？ | **没有。** 任何 `.json` / `.sqlite` 都不入库；数据在建库时从上游取回，落在 `.gitignore` 目录里 |
| 有传染性许可（AGPL/GPL）的代码被拿进来过吗？ | **没有。** 唯一 AGPL 的上游只被「读了公式、作了对照」，实现是独立写的 |
| 那本仓库的 MIT 成立吗？ | **成立。** MIT 只覆盖本仓库的原创代码与文档，不覆盖运行时取回的数据 |

---

## 二、第三方依赖（三个）

| 包 | 协议 | 用在哪 | 说明 |
| --- | --- | --- | --- |
| `textual`（含 `rich`） | **MIT** | `ak_tactic/tui/`，仅 `python -m ak_tactic tui` | **惰性导入**——建 CLI parser、跑其他任何子命令都不导入它，守卫在 `tools/check_tui.py` 第 [1] 节 |
| `qrcode` | **BSD**（PyPI 分类器原文） | `ak_tactic/qrterm.py`，仅 `ak_tactic/skland.py qr`（`tools/skland.py` 是同一份的兼容入口）与 TUI 的登录屏 | **惰性导入**；终端渲染只用它的矩阵，**不需要 Pillow** |
| `pycryptodome` | **BSD-2-Clause / Public Domain**（PyPI 分类器原文） | 仅 `ak_tactic/skland_did.py`（`tools/skland_did.py` 是兼容入口） | **惰性导入**，没装也能用其余全部功能；缺了会打印一条能照做的提示 |

三条都是宽松许可，与 MIT 相容，**无附加义务**。清单见 `requirements.txt`（2026-09-17 起）。
（`tools/` 里的 `import squad`、`import run_srx8`、`import operbox_path` 是同目录模块，不是外部包。）

**注意别把上表读成"项目很重"**：`ak_tactic/` 包与大多数 `tools/` 脚本仍是**纯标准库**，
上面三个都只在特定子命令上用到——不装 `textual` 与 `qrcode` 照样能跑模拟与全部自检。

---

## 三、参考过的代码项目

这些项目**只被阅读与对照**，没有任何一行代码进入本仓库。

| 上游 | 协议 | 本仓库用了它的什么 | 复制代码？ | 义务 |
| --- | --- | --- | --- | --- |
| [xulai1001/akdata](https://github.com/xulai1001/akdata) | **MIT** | 伤害/攻速/SP 回转/技能攻击次数的**公式口径**，用于对照与验证（见 `docs/formula-sources.md`） | **否**（Python 重写） | 无。已在文档中标注来源 |
| [wxhwwla/calc-framework](https://github.com/wxhwwla/calc-framework) | ⚠️ **AGPL-3.0 或商业授权（双许可，须择一）** | 仅在「法术是否 5% 保底、攻速下限取 20 还是 10、攻击力是否取整」三处分歧上作为**反面对照** | **否** | **无**——但见下方警告 |
| [arkntools/arknights-toolbox](https://github.com/arkntools/arknights-toolbox) | **MIT** | 查证「它的 `Level.vue` 只算经验与龙门币、不含属性」，以确定属性必须自算 | 否 | 无。其 `level.json`（经验/龙门币）**尚未接入** |
| [MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights) | ⚠️ **AGPL-3.0** | 只按它**公开的 copilot JSON 格式**导出作业文件（`tools/export_srx8.py`） | **否** | 无——数据格式互通不构成衍生作品 |
| [Arknights-yituliu/BackEndV3](https://github.com/Arknights-yituliu/BackEndV3) | ⚠️ **未声明许可**（见下） | 森空岛**扫码登录**的接口与流程：`gen_scan/login` → `scan_status` → `token_by_scan_code` 三步，以及 status `100/101/102/0` 的语义。据此在 `ak_tactic/skland.py` **自行实现** | **否** | 无——但见下方警告 |
| [Arknights-yituliu/frontend-v2-plus](https://github.com/Arknights-yituliu/frontend-v2-plus) | ⚠️ **`LICENSE` 文件不是许可证**（见下） | 只用于确认扫码的 UI 行为（**2 秒**轮询一次、二维码内容用 deep link 渲染）与三种导入方式的划分 | **否** | 无——但见下方警告 |

### ⚠️ 关于 calc-framework，必须说清楚

它的许可文件写明：**未签商业协议时适用 AGPL-3.0，且第 13 条要求网络服务提供者向用户开放源码**。
本项目**刻意只读它的公式结论，不取任何实现**——`ak_tactic/` 里没有它的代码，
只有 `battle/damage.py` 与 `docs/formula-sources.md` 里**引用其结论并标明出处**的注释。

**给后来者的红线：不要把 calc-framework 的代码复制进本仓库。** 一旦复制，
AGPL-3.0 的传染性会覆盖整个仓库，MIT 就不再成立（除非另行取得它的商业授权）。
要用它的东西，只有两条路：**只读公式、自己实现**，或**单独取得商业许可**。

同理，MAA 是 AGPL-3.0：本项目只**生成**符合其格式的 JSON 文件，**不链接、不复制、不修改**它的代码。
如果你将来要把 MAA 的代码并入本仓库，同样会触发 AGPL。

### ⚠️ 关于一图流的两个仓库：它们根本没有授权

与 calc-framework 那条的性质不同——那条是"有许可，但传染"，**这条是"没有许可"**。

- 前端 `frontend-v2-plus` 的仓库根确实有一个叫 `LICENSE` 的文件。但打开看，它是一段
  「本项目缺少开源许可证声明，建议添加一个」的说明文字，后面附了 MIT / GPL 的简介——
  **那不是许可证，是模板生成的占位内容。**
- 后端 `BackEndV3` **没有任何许可文件**。

按著作权默认规则，两边都是**保留全部权利**。

**红线：不要把一图流的任何代码复制进本仓库。** 要用只有一条路：**只读思路，自己实现。**

本仓库确实采用了它透露的**事实性信息**——`as.hypergryph.com` 的三个官方端点、
status `100/101/102/0` 的语义、deep link 前缀 `hypergryph://scan_login?scanId=`。
这些是**鹰角网络公开服务的事实**，不在一图流的著作权范围内，可以照用；
`ak_tactic/skland.py` 与 `ak_tactic/qrterm.py` 里的实现代码**一行未抄**（请求层、签名、
渲染、轮询都是本项目自己原有的或新写的）。

另有一点值得记下：一图流是在**它自己的服务器**上调这三个接口（请求 IP 是它的），
本项目是在**用户自己的机器**上调（IP 是用户的）——后者更接近真实官方客户端的行为。

---

## 四、数据来源

**关键事实：本仓库不分发数据。** 下表每一行的数据都是**运行时取回**、写进 `.gitignore` 目录的
本地缓存或本地库；克隆仓库得到的是一个**空壳工具**，不是数据副本。

| 来源 | 协议 @ 核验 | 取什么 | 落在哪 | 是否入库 |
| --- | --- | --- | --- | --- |
| 游戏本体 gamedata / [Kengxxiao 镜像](https://github.com/Kengxxiao/ArknightsGameData) | **仓库未声明许可**（默认保留全部权利）；游戏内容版权属鹰角 | 关卡地图、出怪路线、敌人数值、攻击范围、属性表 | `data/gamedata/`、`data/akdb.sqlite` | **否** |
| [map.ark-nights.com](https://map.ark-nights.com)（PRTS.Map 部署） | 站点未找到许可声明 | 同上（首选镜像，更精简） | 同上（按域名分目录缓存） | **否** |
| [prts.wiki](https://prts.wiki) | **CC BY-NC-SA 4.0**（`siteinfo.rightsinfo` 原文：知识共享署名-非商业性使用-相同方式共享） | 敌人页正文与模板 → 本地敌人库 | `data/cache/prts/`、`data/enemydb.sqlite` | **否** |
| [theresa.wiki](https://theresa.wiki) | **CC BY-NC-SA 4.0**（首页页脚原文：本站采用 署名-非商业性使用-相同方式共享 4.0 国际协议进行许可） | 地块字典 95 条（gamedata 没有这张表） | `data/cache/theresa/`、`data/akdb.sqlite` 的 `tile` 表 | **否** |
| [arknights.wiki.gg](https://arknights.wiki.gg) | 以其站点声明为准（本项目未复制其内容） | 文档中引用其 Damage 页的结论用于口径对照 | — | **否** |

游戏内容（干员名、技能文本、数值、地图、图鉴）版权归 **上海鹰角网络科技有限公司** 所有。
本项目**与鹰角网络无隶属关系、未获其授权**，也**不提供任何游戏资源下载**——
只提供把公开数据取回来自己算的脚本。

### ⚠️ 非商业（NC）这一条要单独记住

两个主要数据源（prts.wiki、theresa.wiki）都是 **BY-NC-SA 4.0**，带**非商业性使用**限制。
于是：

* **本仓库的代码**是 MIT，**允许商业使用**——因为它只是工具。
* **由这两个源派生的数据**（敌人库、地块表、敌人正文）**不是** MIT，也**不是**可商用的。
  它们随 CC BY-NC-SA 4.0 走：署名、非商业、相同方式共享。

本仓库的应对是**干脆不分发**：`data/` 与 `out/` 全部 gitignore，克隆后自行建库。
**如果你要把建好的库随成品分发、或用于商业用途，需要自行评估并取得相应授权。**

---

## 五、文档里的引文

`docs/` 与 `README.md` 里出现的技能/天赋正文片段（例如「造成 3 次攻击力 210% 的法术伤害」），
是**为说明解析规则而作的简短引用与举例**，不是数据再分发。同理，文档里的数值基线
（137.0s / 41 杀 / 60,750 等）是本项目自己跑出来的结果。

---

## 六、如果要再分发数据：自查清单

1. 你分发的对象是否包含 `data/*.sqlite`、`data/gamedata/`、`data/cache/`？→ 那就是在分发数据，不是分发工具。
2. 其中是否含 prts.wiki / theresa.wiki 派生内容？→ 适用 CC BY-NC-SA 4.0：**署名 + 非商业 + 相同方式共享**。
3. 你的用途是否商业？→ NC 条款下**不可以**，除非另行取得授权。
4. 是否含游戏本体数据？→ 版权属鹰角，未经授权不宜再分发。
5. 有没有复制 calc-framework 或 MAA 的代码？→ 有则整个项目转为 AGPL-3.0 义务。

---

## 七、怎么重新核（命令）

```powershell
# 上游协议：GitHub API 的 license 字段
curl.exe -s -H "User-Agent: audit" https://api.github.com/repos/wxhwwla/calc-framework
curl.exe -s -H "User-Agent: audit" https://api.github.com/repos/xulai1001/akdata
curl.exe -s -H "User-Agent: audit" https://api.github.com/repos/MaaAssistantArknights/MaaAssistantArknights

# prts.wiki 的站点协议（走本项目的客户端，它带得出 WAF 的请求头）
python -c "from ak_tactic.prts.client import default_client as d; print(d().get_json({'action':'query','meta':'siteinfo','siprop':'rightsinfo'}))"

# theresa.wiki：首页页脚（curl.exe -x <proxy> -A <browser-ua> https://theresa.wiki/）

# 本仓库有没有夹带第三方代码或数据
git ls-files | Select-String -Pattern 'json|sqlite|csv|html'      # 应为空
git grep -n -i "calc-framework" ; git grep -n -i "akdata"        # 应只有注释与文档
```

---

*本文随 `LICENSE`（MIT）一同构成本仓库的许可声明。若文中的协议信息与上游最新声明不符，以上游为准——并请顺手改这里。*
