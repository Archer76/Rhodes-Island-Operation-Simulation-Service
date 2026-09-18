"""R.I.O.S. 的终端界面：五屏向导。

    python -m ak_tactic tui

    [0] 准备 → [1] 选关卡 → [2] 选编队 → [3] 解算 → [4] 结果

## 两个刻意的设计

**一、进度反馈不动核心代码。** 规划里原本要往 `ak_tactic/search.py` 加回调，
但那会让搜索逻辑与三条基线（1-7 / SR-6 / SR-EX-8）的可比性受影响。实际不需要：
`Searcher` 本来就维护 `self.evaluated` 计数器，本模块用一个 0.25 秒的定时器读它，
就能给出**真实的**"已评估 N 个候选"。搜索本身在后台线程里跑，界面不卡。

**二、登录态不是闸门。** `[0]` 屏会显示名册从哪来、新不新，但**允许跳过**。
登录只决定"名册要不要刷新"，不决定"流程能不能走完"——名册有离线兜底
（森空岛缓存 → OperBox → 手动选择）。`--no-login` 直接跳过这一步，
用于测试全新启动的流程。
"""

from __future__ import annotations

import time
import unicodedata
from pathlib import Path

from textual import work
from textual.actions import SkipAction
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import (Button, DataTable, Footer, Header, Input, Label,
                             ProgressBar, Select, SelectionList, Static)
from textual.widgets.selection_list import Selection

from rich.cells import cell_len
from rich.text import Text

from .. import maa_export as maa
from . import data as D
from . import theme

__all__ = ["RiosApp", "run", "both_cases"]


def _full_width(key: str) -> str | None:
    """半角可打印 ASCII → 它的**全角孪生**（不可逆时返回 None）。

    中文输入法切到**全角**时，按 `l` 送过来的是 `ｌ`（U+FF4C），按 `1` 送的是
    `１`（U+FF11）——与半角是两个不同字符，按键匹配表里一个都不命中，
    界面上明明写着 `L`，按下去毫无反应。全角孪生就是 `+0xFEE0` 那一批，
    只覆盖 `!`~`~`；已经是全角、或本身就是多字符的键（`escape`）返回 None。
    """
    if len(key) != 1:
        return None
    o = ord(key)
    return chr(o + 0xFEE0) if 0x21 <= o <= 0x7E else None


def both_cases(rows: list[Binding]) -> list[Binding]:
    """把**单字符**绑定展开成若干份：大写孪生 + 全角孪生。

    ## 这一步为什么必需

    **一、大小写。** `Binding("h", "home", "主界面", key_display="H")` 里的
    `key_display` **只管显示**：Footer 上印的是 `H`，真正注册的键却只有小写 `h`。
    而 Textual 的键匹配**区分大小写**——用户照着 Footer 按 Shift+H，送过来的是
    大写 `H`，一个绑定都不匹配，**界面上明明写着 H 却按不动**。实测：
    `press("h")` 命中 1 次，`press("H")` 与 `press("shift+h")` 各命中 0 次。

    反过来把键写成 `Binding("H", …)` 也不行——那就变成"必须按住 Shift"。

    **二、全角。** 中文输入法在全角模式下，`l` 送过来是 `ｌ`、`1` 送过来是
    `１`（见 `_full_width`）。同一张表只认半角，用户按了也白按——他看不到
    "程序收不到"，只看到"这个键坏了"。所以每个单字符键都补一个全角孪生。

    这就是唯一的解法：**都收**。显示沿用 `key_display` 给的那一份（需求
    「字母改大写」说的是提示文字），其余变体一律 `show=False`，不上 Footer。
    `AskScreen` 的 `1`–`9` 也走这同一张表，所以全角数字同样能选。
    """
    out: list[Binding] = []
    seen: set[str] = set()
    for b in rows:
        out.append(b)
        seen.add(b.key)
    for b in rows:
        k = b.key
        if len(k) == 1 and k.isalpha():
            group = {k.lower(), k.upper()}
        elif len(k) == 1:
            group = {k}
        else:
            continue                       # escape / enter / ctrl+c 这类不动
        for v in list(group):
            fw = _full_width(v)
            if fw:
                group.add(fw)
        for v in sorted(group):
            if v == k or v in seen:
                continue
            seen.add(v)
            out.append(Binding(v, b.action, b.description or "",
                               show=False, priority=b.priority))
    return out


def known_accounts_safe() -> list[dict]:
    """本机登录过的账号；**取不到就当空的**。

    这是显示用的信息（主界面的账号行、登录屏的列表、退出账号的确认文案都要它），
    读失败不该拖垮一整屏。主界面与登录屏两处都要用，所以放在模块层，**只有一份**
    ——退出账号的按键从主界面搬到登录屏时，最容易出的错就是复制一份出来、
    然后两份各改一半。
    """
    try:
        from ak_tactic import skland
        return skland.known_accounts()
    except Exception:                                         # noqa: BLE001
        return []


#: `auto` 模式（「允许程序补充」）下**人选池的总大小**：勾的人先进池子，不足就从
#: 名册里按练度补到这么多。
#:
#: **这是候选池，不是出战人数**（博士 2026-09-18 追问过这件事）。它只决定"从多少人
#: 里挑组合"，与出来的编队有几个人无关；界面上因此不再写这个数，只写有几个人上场。
#: 池子越大越慢：候选数 ≈ 池子人数 × `per_op`，而每层的模拟次数 ≈ `beam` × 候选数。
AUTO_POOL = 24

#: 解算深度的**起点**：先按 4 人找（博士 2026-09-18：「默认还是 4 人」）。
DEPTH_START = 4

#: 自动加深的步长。
DEPTH_STEP = 2

#: 一支编队最多 12 人（游戏内的编队槽位）。
#:
#: 它与**关卡可部署人数**是两回事，博士 2026-09-18 说清了：两者不冲突——场上放不下
#: 的人可以撤下来换别人上，所以真正的闸门是关卡的可部署人数，12 只是封顶。
SQUAD_CAP = 12


def depth_ladder(deploy_limit: int) -> list[int]:
    """解算深度的阶梯：从 4 人起，找不到就按 `DEPTH_STEP` 加深，直到关卡可部署人数。

    「关卡可部署人数要接进来，默认还是 4 人，找不到的情况就做自动加深」——博士
    2026-09-18。所以这里不是"一上来就按上限搜"，而是：

    * 大多数关卡 4 人就够，先花最少的钱试一次；
    * 4 人以内没找到三星，才加深再试（每深一层都要重跑一遍搜索，代价是真实的，
      所以步长取 2 而不是 1）；
    * 天花板是这一关的**可部署人数**（gamedata `options.characterLimit`）；
    * 取不到这个数（库/网络都没有）时按 `SQUAD_CAP`（12）封顶，并在日志里说明
      ——悄悄按 12 搜会让人以为这一关真能上 12 个。

    末端一定落在 `cap` 上（`4、6、8` 而不是 `4、6、7` 里漏掉 8），免得"上限 8 人"
    这一档永远试不到。
    """
    cap = min(deploy_limit if deploy_limit > 0 else SQUAD_CAP, SQUAD_CAP)
    if cap <= 0:
        return [DEPTH_START]
    if cap <= DEPTH_START:
        return [cap]
    out = list(range(DEPTH_START, cap + 1, DEPTH_STEP))
    if out[-1] != cap:
        out.append(cap)
    return out


# ================================================================ 状态

class State:
    """整个向导共享的一份状态。刻意做成简单字典式，便于调试时直接看。"""

    def __init__(self) -> None:
        self.roster: D.Roster | None = None
        self.stage: dict | None = None
        self.squad: list[str] = []
        self.mode: str = "auto"          # auto = 允许程序补充；only = 只用我选的
        self.searcher = None             # 解算中用来读 evaluated
        #: 解算用的 `ak_tactic.plan.Roster`。结果屏导出时要靠它取练度与模组，
        #: 而它和 `roster`（TUI 自己的轻量名册）不是同一个类——见 `SolveScreen._run`。
        self.plan_roster = None
        self.result = None
        self.error: str = ""
        self.export_path: Path | None = None
        #: 这一轮解算的**人选池**是怎么凑出来的（如「勾的 3 人 + 名册补 24 人」）。
        #: 只在日志里用（解释"为什么这么久"）；**不进界面**——博士 2026-09-18：
        #: 编队人数部分只写有几个人上场。
        self.pool_note: str = ""
        #: 当前这一轮的**出战人数上限**（搜索深度），会随自动加深往上走。
        self.depth: int = DEPTH_START
        #: 这一关的**可部署人数**（gamedata `options.characterLimit`）；0 = 取不到。
        self.deploy_limit: int = 0


# ================================================================ 屏的基类

class RiosScreen(Screen):
    """本项目所有屏的基类：**矮窗口下装饰让路，内容优先**。

    博士 2026-09-18：「做好页面排版，保证终端窗口小的时候也要让玩家看到所有内容」。

    两层做法：

    * `compact` 类 —— `theme.py` 里 `Screen.compact .block` 那条 CSS 把块的边框、
      内边距、外边距全收掉。一个块的固定开销本来是 6 行，三块 18 行，加上顶栏、
      步骤条、底栏要 25 行才装得下，而他的终端只有 ~20 行：**内容就是这么被挤到
      窗口外面的**；
    * `_fit_extra(h)` —— 子类再收自己那些"看一次就够"的块（主界面的标题块）。

    阈值 `COMPACT_HEIGHT` 是量出来的，不是估的：`_proto/small_window_audit.py`
    逐屏逐档核对「不滚动就要看得见」，`tools/check_tui.py` 的 `check_small_window()`
    把同一套判据钉进自检。
    """

    #: 窗口矮到这个行数以下就进紧凑模式。
    COMPACT_HEIGHT = 22

    #: 再矮到这个行数以下，连**顶栏**也收掉（它印的是服务名与时钟，都是装饰；
    #: 底栏留着——那里的按键是操作）。
    TINY_HEIGHT = 16

    def _fit(self) -> None:
        try:
            h = self.size.height
        except Exception:                                     # noqa: BLE001
            return
        if h <= 0:
            return
        self.set_class(h < self.COMPACT_HEIGHT, "compact")
        try:
            self.query_one(Header).display = h >= self.TINY_HEIGHT
        except Exception:                                     # noqa: BLE001
            pass          # 有些屏（弹窗）本来就没有 Header
        self._fit_extra(h)

    def _fit_extra(self, h: int) -> None:
        """子类挂钩：按窗口高度再收点什么。默认什么都不做。"""

    def on_resize(self, event) -> None:
        self._fit()


# ================================================================ [0] 准备

class WelcomeScreen(RiosScreen):
    """[0] 准备：数据目录在哪、名册从哪来、当前登录的是哪个号。"""

    #: `key_display` 让 Footer 显示**大写字母**；而**实际能被按下的**不只小写——
    #: 每个单字母绑定都由 `both_cases()` 补了大写孪生，所以照着 Footer 按
    #: Shift+H 也能用（只写小写键、只印大写提示，是"看着有、按不动"的坑，
    #: 博士实测踩到过）。见 `both_cases()` 的说明。
    #: 提示只留 Footer 这一处：自己再画一行 `#hint` 会与它重复
    #: （截图上底部就是**两行一样的东西**）。
    BINDINGS = both_cases([
        Binding("enter", "go", "开始", key_display="Enter"),
        Binding("d", "dir", "改目录", key_display="D"),
        Binding("l", "login", "登录", key_display="L"),
        Binding("q", "quit", "退出程序", key_display="Q"),
    ])

    #: 窗口矮到这个行数以下就把**标题块**收起来（顶栏本来就印着服务名）。
    #:
    #: 博士 2026-09-18 报「主界面只看得见四行标题」、接着又报「登录账号那一栏
    #: 没有名册/干员库那句」——两件事同一个成因：这一屏的内容排在 30 行以下，
    #: 而他的终端大约只有 20 行，**值全掉在下沿之外**，只剩标题行看得见。
    #: 实测（`_proto/home_fold.py`）：80x20 时名册那句在 y=20、窗口只有 0–19。
    #: 最底下那一层成因是 Textual 的 `Vertical` 默认 `height: 1fr`：三块把剩余
    #: 空间均分，各自被撑高几行，内容于是被顶到窗口外面——`.block { height: auto }`
    #: 修掉之后，这一屏只要 **11 行**就装得下全部四行数据。
    #:
    #: 另外那三行说明被博士整个删掉了（「这一段整个删掉，不需要提示」），所以
    #: 阈值也跟着降到"只剩标题可收"的这档：**12 行起连标题一起显示**。
    SHORT_HEIGHT = 11

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(theme.step_bar(0), id="steps")
        with Vertical(classes="block", id="title-block"):
            yield Label(theme.APP_TITLE, classes="block-title")
            yield Static(theme.APP_SUBTITLE, classes="muted", id="subtitle")
        with Vertical(classes="block"):
            yield Label("数据目录", classes="block-title")
            yield Static("", id="dir-line")
        with Vertical(classes="block"):
            yield Label("登录账号", classes="block-title")
            yield Static("", id="account-line")
        yield Footer()

    def on_mount(self) -> None:
        #: 上一步动作留下的失败原因（如退出账号写盘失败）。只给下一帧看一眼。
        self._note = ""
        self._fit()
        self._refresh()

    def _fit_extra(self, h: int) -> None:
        """矮窗口下把**标题块**收起来（基类已把块的边框与内边距收掉）。

        **优先级是明写的：数据 > 标题。** 矮窗口里宁可让博士看不见那两条自己
        已经知道的服务名（顶栏也印着），也不能让他看不见数据目录与名册状态——
        后者才是他每次来这一屏要看的东西。

        | 窗口高 | 收起什么 |
        |---|---|
        | ≥ 20 | 什么都不收（30 行是常见默认） |
        | < 20 | 收起**标题块**，两栏四行数据保住 |

        阈值是量出来的：`check_welcome()` 在 80x14 到 120x44 七档上逐行核对
        「不滚动就要看得见」。
        """
        show_title = h >= self.SHORT_HEIGHT
        try:
            self.query_one("#title-block", Vertical).display = show_title
            self.query_one("#subtitle", Static).display = show_title
        except Exception:                                     # noqa: BLE001
            pass

    def _known_accounts(self) -> list[dict]:
        """本机登录过的账号（与登录屏共用模块层的 `known_accounts_safe()`）。"""
        return known_accounts_safe()

    def _account_line(self) -> str:
        uid = D.skland_uid()
        others = [a for a in self._known_accounts() if a["uid"] != uid]
        if not uid:
            tail = (f"；本机另存着 {len(others)} 个登过的账号，"
                    "按 L 进登录屏后按 S 可切回。" if others else "。按 L 扫码登录。")
            return "[warn]当前没有登录的账号[/]" + tail
        # 显示的是**游戏用户名与游戏uid**（博士 2026-09-18 口径）。
        # 原先后面还挂一个 `（登录账号 2155938927）` 的小注，博士 2026-09-18
        # 让删掉：那一层区分（登录账号 id ≠ 游戏 uid）写在文档与登录屏里就够，
        # 主界面这一行只回答"现在登的是哪个号"。
        # 名册那半句不在这里写——`_data_line()` 会单独写一句更准的（份数 + 来源
        # + 降级警告），同一栏里重复一个「有名册缓存」只会让人以为有两件事。
        head = D.describe_account(uid, current=True, roster_flag=False,
                                  login_note=False)
        if others:
            head += f"　[dim]（本机另有 {len(others)} 个登过的账号）[/]"
        return head

    def _refresh(self) -> None:
        """重画两栏。

        **逐栏兜底**（博士 2026-09-18 报过「主界面只看得见四行标题」）：任何一栏
        的取数抛了，就在那一栏写下原因，绝不留空白。空白是最坏的结果——它分不清
        是「没登录」「没有名册」还是「代码在这台机器上挂了」，而这一屏正是别人
        第一次跑起来看到的东西。
        """
        for wid, build in (("#dir-line", self._dir_line),
                           ("#account-line", self._account_block)):
            box = self.query_one(wid, Static)
            try:
                box.update(build())
            except Exception as exc:                          # noqa: BLE001
                box.update(f"[warn]这一栏取不到：{exc.__class__.__name__}: {exc}[/]")

    def _dir_line(self) -> str:
        """数据目录：**当前正在用的路径**，两行。

        博士 2026-09-18 的排版：路径独占一行，第二行写作业落点。他还把原先跟
        在路径后面的那个小注（「（默认目录…，还没改过）」／「（当前设置）」）
        删掉了——路径本身就是他要的信息，"是哪来的"他清楚（能改的地方就按 `D`）。
        """
        g = D.guides_dir()
        out = f"{g}\n[dim]MAA 作业输出到 {Path(str(g)) / '<关卡名>'}[/]"
        if not g.exists():
            out += "[dim]　（这个目录还不存在，导出时自动建）[/]"
        return out

    def _data_line(self) -> str:
        """名册与干员库的状态，收在账号这一栏里（原来的「名册」一栏已删）。

        博士 2026-09-18 的口径是**两句都要**：名册（森空岛缓存 / MAA OperBox 降级）
        与干员库（`akdb.sqlite`）各说一句「已获取没有」。没名册时把那句「是哪种
        没名册」的说明接在后面——它比一个光秃秃的「未获取」有用得多。
        """
        parts: list[str] = []
        r = getattr(self.app.state, "roster", None)
        if r is None:
            parts.append("[warn]名册：未获取[/]")
        else:
            src = "森空岛缓存" if r.source == "skland" else "MAA OperBox（降级）"
            tone = "ok" if r.complete else "warn"
            parts.append(f"[{tone}]名册：已获取[/]（{src} {len(r.operators)} 名）")
            if not r.complete:
                # 降级名册缺专精与模组等级，编队里那些「专三/模组三」的前提会算不准。
                # 这句话原来是「名册」那一栏的 `r.note`，栏删了，但**不能连警告一起删**。
                parts.append("[warn]（这份名册没有专精与模组等级）[/]")
        db = D.operator_db_status()
        if db["operators"] is not None:
            parts.append(f"[ok]干员库：已获取[/]（{Path(db['path']).name} "
                         f"{db['operators']} 名）")
        elif db["exists"]:
            parts.append(f"[warn]干员库：文件在，但读不出来[/]（{db['error']}）")
        else:
            parts.append("[warn]干员库：未获取[/]（先跑 db build）")
        line = "　".join(parts)
        if r is None:
            line += "\n" + self._no_roster_hint()
        return line

    def _account_block(self) -> str:
        note = f"[warn]{self._note}[/]\n" if self._note else ""
        self._note = ""
        return note + self._account_line() + "\n" + self._data_line()

    def _no_roster_hint(self) -> str:
        """没名册时怎么说。

        要说清是**哪一种**没名册——"这个号没拉过"、"还不知道这个账号的游戏
        uid"、"本来就没登"是三回事，混成一句「没有找到名册」会让人看着磁盘上
        明明躺着一份名册文件发愣。切换账号之后这一屏是最先看到的地方，
        所以这句话在这里最要紧。
        """
        uid = D.skland_uid()
        game = D.skland_game_uid()
        cached = D.cached_roster_uids()
        if uid and not game:
            who = "、".join(cached[:3])
            more = " 等" if len(cached) > 3 else ""
            return ("[warn]还不知道这个账号的游戏 uid[/]"
                    "（登录账号 ≠ 游戏 uid，名册按后者存）。\n"
                    f"[dim]按 U 问一次森空岛就能定下来"
                    f"{f'；本机现有缓存：{who}{more}' if who else ''}。[/]")
        if game and cached:
            who = "、".join(f"uid={u}" for u in cached[:3])
            more = " 等" if len(cached) > 3 else ""
            return (f"[warn]游戏 uid={game} 还没有名册缓存[/]，"
                    f"本机拉过的是 {who}{more}。\n"
                    "[dim]要么跑一次名册拉取，要么按 S 切回那个号（凭据还在）。[/]")
        if uid:
            return ("[dim]这个号还没有名册缓存。跑一次名册拉取即可；"
                    "在此之前编队那一步可以手动输名字。[/]")
        return ("[dim]当前没有登录的账号。可以继续，"
                "编队那一步手动输名字；或按 L 扫码登录。[/]")

    def action_go(self) -> None:
        self.app.goto_stage_pick()

    def action_dir(self) -> None:
        self.app.push_screen(GuidesDirScreen(), self._dir_done)

    def _dir_done(self, path: Path | None) -> None:
        if path:
            D.save_config(guides_dir=str(path))
        self._refresh()

    def action_login(self) -> None:
        # 登录回来要把名册行重画一遍：登录可能刚落下一份新凭据，
        # 这一行原先是按旧状态画的。登录屏还可能带回一句话（登的是新号还是老号），
        # 那句就显示在账号行上——所以回调不是个丢弃返回值的 lambda。
        self.app.push_screen(LoginScreen(), self._login_done)

    def _login_done(self, result) -> None:
        """登录屏关闭：`result` 非空时是一句要显示在账号行上的话。"""
        if isinstance(result, str) and result.strip():
            self._note = result
        self._refresh()

    # 原先这里还有两个动作，博士 2026-09-18 的界面草图把它们挪去了登录屏：
    #
    #   * `U`（取账号 uid，`skland.resolve_game_uid`）——只在**登录**时才有意义，
    #     而登录屏的 `U`（`LoginScreen.action_fill`）本来就是它的**更全版本**
    #     （一次补齐本机每个账号，不只当前这一个）。主界面不再挂它，逻辑也不留
    #     副本——留一份就是两处迟早会漂。
    #   * `O`（退出账号）——退出是为了换号，而换号是在登录屏上做的（那里才有
    #     账号列表与「按 S 切回」的上下文）。
    #
    # 两件事现在都只在登录屏上，见 `LoginScreen.BINDINGS` 与 `action_logout`。

    def action_quit(self) -> None:
        self.app.exit()


class PathInput(Input):
    """带 Tab 补全的路径输入框。

    `Input` 自己不占 Tab（默认用来移焦点），所以补全得挂在本子类上。
    **`priority=True` 是必要的**：不然 Tab 会先被屏幕的焦点切换抢走，
    按下毫无反应（这个坑与 `SquadPickScreen` 的 Enter 同源）。
    """

    BINDINGS = [Binding("tab", "complete", "补全", key_display="Tab",
                        priority=True)]

    class Completed(Message):
        """补全后把候选交回界面——**不替用户猜**，多个匹配就都列出来。"""

        def __init__(self, candidates: list[str]) -> None:
            super().__init__()
            self.candidates = candidates

    def action_complete(self) -> None:
        new, cands = D.complete_dir(self.value)
        if new != self.value:
            self.value = new
            self.cursor_position = len(new)
        self.post_message(self.Completed(cands))


class GuidesDirScreen(RiosScreen):
    """可跳过的"重设默认目录"。Esc 不改就回去。"""

    BINDINGS = both_cases([Binding("escape", "cancel", "返回", key_display="Esc")])

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="block"):
            yield Label("数据目录", classes="block-title")
            yield Static("MAA 作业的输出根目录。默认在**本工具根目录**下的 Guides/。\n"
                         "按 Tab 补全路径；留空或按 Esc 则不修改。", classes="muted")
            yield PathInput(value=str(D.guides_dir()), id="dir")
            yield Static("", id="cands", classes="muted")
        yield Footer()

    def on_path_input_completed(self, event: PathInput.Completed) -> None:
        box = self.query_one("#cands", Static)
        if not event.candidates:
            box.update("")
            return
        shown = "　".join(event.candidates[:12])
        more = f"　…（共 {len(event.candidates)} 项）" if len(event.candidates) > 12 else ""
        box.update(f"[dim]候选：{shown}{more}[/]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = (event.value or "").strip()
        self.dismiss(Path(raw).expanduser() if raw else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AskScreen(ModalScreen):
    """一个通用的一问一答屏。**只问，不做事**——按下的那一行原样回给调用方。

    为什么做成通用的：本项目有两处要问（「不登录？本次还是以后都不」、
    「确认退出账号？」），它们除了文字完全同构。各写一个屏，迟早会把
    「Esc 是什么意思」写飘一处——而"取消"的语义漂了，是要出事的那种漂。

    ## 选项画在正文里，不画在 Footer

    选项**本身就是问题的一部分**（「1　本次不登录」读起来是一句话），
    不是一个附加的动作提示；所以 Footer 只留那一行 `Esc 返回`，编号列在
    正文里。两处都印一遍，就是博士指出过的"底部两行一样的东西"。

    返回给调用方的是**行里的值**（字符串），按 Esc 时是 `None`。
    """

    BINDINGS = both_cases([
        # 1–9 是选项键，**不上 Footer**（见类文档）。走 `both_cases` 是为了拿
        # 全角孪生：中文输入法全角模式下按 1 送来的是 `１`，不补就选不动。
        *[Binding(str(i), f"pick({i})", show=False) for i in range(1, 10)],
        Binding("escape", "cancel", "返回", key_display="Esc"),
    ])

    CSS = """
    AskScreen { align: center middle; }
    #ask-box { width: 68; height: auto; border: round $primary; padding: 1 2; }
    #ask-title { text-style: bold; }
    """

    def __init__(self, title: str, body: str,
                 rows: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._rows = list(rows)

    def compose(self) -> ComposeResult:
        with Vertical(id="ask-box"):
            yield Static(self._title, id="ask-title")
            yield Static(f"\n{self._body}\n", classes="muted")
            for i, (_value, label) in enumerate(self._rows, start=1):
                yield Static(f"  [bold]{i}[/]　{label}")
        yield Footer()

    def action_pick(self, which) -> None:
        idx = int(which) - 1
        if 0 <= idx < len(self._rows):
            self.dismiss(self._rows[idx][0])

    def action_cancel(self) -> None:
        self.dismiss(None)


class QrScreen(ModalScreen):
    """扫码用的**全屏居中**二维码。

    ## 为什么单独一屏

    原先二维码是登录屏里的一块 `Static`，被上下几个 `Vertical` 挤着，高度不够
    就被裁掉一截——博士实测「显示不完整扫不了」。二维码**缺一个角就彻底作废**，
    不能靠"大概看得见"来交付。

    现在它独占一屏、由屏幕的 `align: center middle` 居中，尺寸随内容自适应。

    ## 静默区按规范给足

    二维码四周必须有**至少 4 格纯白静默区**，否则识别率骤降。终端里 2 格
    通常够用（终端本身有行距），但既然空间允许就给足 4 格；屏幕实在小的时候
    才逐级退让（见 `_pick_border`）——**宁可小一点，也不能缺角**。

    画法仍是 `▄` 上下半格，但**不在这里拼 ANSI**：Textual 会把 `\\x1b[38;5;…`
    里的方括号当标记解析，所以逐格给字符上色。
    """

    BINDINGS = both_cases([Binding("escape", "close", "返回", key_display="Esc")])

    #: 居中区里**只放二维码**：标题与状态行都 dock 到底部。
    #: 挤在同一个块里会白吃掉四五行，而那几行往往正是静默区放不下的原因。
    CSS = """
    QrScreen { align: center middle; }
    #qr-box { width: auto; height: auto; border: round $primary; padding: 0 1; }
    #qr { width: auto; height: auto; }
    #qr-note { dock: bottom; width: 100%; height: auto; text-align: center; }
    """

    _DARK = "#000000"
    _LIGHT = "#ffffff"

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content
        self.note = "等待扫码……"

    def compose(self) -> ComposeResult:
        with Vertical(id="qr-box"):
            yield Static("", id="qr")
        yield Static(self.note, id="qr-note")

    def on_mount(self) -> None:
        self._draw()

    def on_resize(self) -> None:
        # 窗口变了就按新尺寸重挑静默区，别让图被裁掉
        self._draw()

    def _pick_border(self) -> int:
        """在「放得下」的前提下取最大的静默区。

        `matrix(border=b)` 的边长是 `模块数 + 2b`，画成 `▄` 后占
        `ceil(边长/2)` 行、`边长` 列。中心区只放二维码，所以要给出去的
        只有：框的上下边框 2 行、贴底状态行 2 行、左右各留 2 列余量。

        按规范静默区**至少 4 格**，所以只有真的塞不下才退让。
        """
        from ak_tactic.qrterm import matrix

        base = len(matrix(self.content, border=0))
        avail_rows = max(1, self.size.height - 4)
        avail_cols = max(1, self.size.width - 4)
        for b in (4, 3, 2, 1, 0):
            side = base + 2 * b
            if side <= avail_cols and (side + 1) // 2 <= avail_rows:
                return b
        return 0

    def _draw(self) -> None:
        from ak_tactic.qrterm import matrix

        b = self._pick_border()
        m = matrix(self.content, border=b)
        out = Text(no_wrap=True)          # **绝不能让二维码换行**：一折就废
        h = len(m)
        for y in range(0, h, 2):
            top = m[y]
            bottom = m[y + 1] if y + 1 < h else [False] * len(top)
            for x, t in enumerate(top):
                # `▄` 画的是下半格 → 前景取下格、背景取上格
                out.append("\u2584",
                           style=f"{self._DARK if bottom[x] else self._LIGHT} "
                                 f"on {self._DARK if t else self._LIGHT}")
            out.append("\n")
        self.query_one("#qr", Static).update(out)
        # 静默区被压过就说出来：与其让人对着扫不出的码发愣，
        # 不如直接告诉他"把窗口拉大点就能扫"。
        if b < 4:
            self.set_note(self.note
                          + f"\n[warn]终端偏小，静默区已压到 {b} 格"
                            "——扫不出来的话把窗口拉大一点再按 L。[/]")
            self.note = self.note          # 保留原文，下次重画不要越接越长

    def set_note(self, text: str) -> None:
        self.note = text
        self.query_one("#qr-note", Static).update(text)

    def action_close(self) -> None:
        self.dismiss(None)


class LoginScreen(RiosScreen):
    """[0b] 登录态：**真的能扫码登录**，也允许跳过。

    ## 走的是哪条路

    `ak_tactic.skland.login_by_qr()` —— 官方 `as.hypergryph.com` 三步
    （`gen_scan/login` → `scan_status` → `token_by_scan_code`）。
    扫码换到的是**鹰角通行证 token（hgToken）**，与官网个人页那条路是同一类
    东西，过期都能用 `cred` 子命令静默重铸。所以扫码既省事又持久，
    而且完全不必让用户去官网复制那串「敏感度不亚于账号密码」的 token。

    ## 三件必须做对的事

    **一、轮询必须在后台线程。** `login_by_qr` 默认 2 秒一次、最长 180 秒，
    放在 UI 线程里界面整整三分钟不动，二维码也画不出来。

    **二、回调里不许直接碰界面。** `on_qr` / `on_status` 是在那个后台线程里
    被调的，Textual 的控件只能在 UI 线程改；所以它们只 `post_message`，
    真正动界面的是消息处理函数。

    **三、二维码不能用 ANSI 转义串画。** `ak_tactic/qrterm.py` 的
    `_render_ansi` 是给 `print()` 用的，直接塞进 `Static` 会被 Textual 当成
    标记语言解析（`\\x1b[38;5;16m` 里的方括号正好长得像标记）。这里改成
    从 `qrterm.matrix()` 取矩阵，**逐格给字符上色**，效果与终端版一致：
    用 `▄` 上下半格拼，高度减半。

    登录成功后**不自动拉名册**：拉名册要走 `skland fetch` + `roster.py`
    两个真网络步骤，那是 `[0]` 屏上另一件事。这里只负责把凭据落盘，
    顺带**重读一遍本机缓存的名册**（读盘，不联网）——因为刚落下的凭据可能
    属于另一个账号，而名册是按当前账号取的。

    ## `Esc` 在这里是「不登录」，所以要补问一句——**只在他还没登进去时**

    博士 2026-09-17 的裁定：在登录屏按 `Esc` 先问「本次不登录 / 以后都不
    登录」。差别是真的——答「以后都不」写进 `~/.rios/tui.json`，此后启动不再
    自动进这个向导；答「本次」什么都不写，下一次干净启动还会问。问屏上再按
    `Esc` 是**取消这一问**（回登录屏继续扫码），不是答"不登录"。

    博士 2026-09-18 收紧了一条：**已经登录着账号时，`Esc` 直接回主界面，
    不再问那一句**。他刚扫码登进去、按 `Esc` 想回主界面，却被问「确定不登录
    吗」——这一问在那时是荒唐的，问的是他已经做完的事。同理，**扫码登录成功
    后直接弹回主界面**（不再留在本屏等他按 `Esc`）。那一问只留给"手上确实
    还没有账号"的那一刻，也就是它当初被设计出来的那一刻。

    `S` 列出本机登过的账号并切过去。**不联网、不重扫**——退出账号不删文件，
    所以凭据与名册都还在本地，这正是"切号不必重扫"的根据。列表按博士
    2026-09-18 的口径显示**游戏用户名与游戏uid**（登录账号 id 只作附注）。

    `U` 补全本机账号的游戏用户名与游戏 uid——它**联网**，所以不是开机自动跑，
    而是按一下才去问（与 `[0]` 屏的 `U` 同一条理由）。
    """

    BINDINGS = both_cases([
        Binding("l", "login", "扫码登录", key_display="L"),
        Binding("s", "switch", "切换账号", key_display="S"),
        Binding("u", "fill", "补全账号信息", key_display="U"),
        Binding("o", "logout", "退出账号", key_display="O"),
        Binding("escape", "close", "返回", key_display="Esc"),
    ])

    #: 二维码每格用的两种颜色，与 `qrterm` 的终端版取同一组（纯黑 16 / 纯白 231）
    _DARK = "#000000"
    _LIGHT = "#ffffff"

    class QrReady(Message):
        """二维码申请到了。"""

        def __init__(self, content: str) -> None:
            super().__init__()
            self.content = content

    class QrStatus(Message):
        """一次轮询的结果。"""

        def __init__(self, status: int, text: str) -> None:
            super().__init__()
            self.status = status
            self.text = text

    class LoginDone(Message):
        """登录流程结束（成功或失败）。"""

        def __init__(self, ok: bool, text: str) -> None:
            super().__init__()
            self.ok = ok
            self.text = text

    class FillDone(Message):
        """补全账号信息（联网问绑定列表）跑完一轮。"""

        def __init__(self, lines: list[str]) -> None:
            super().__init__()
            self.lines = lines

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="block"):
            yield Label("登录态", classes="block-title")
            yield Static(self._status(), id="login-status")
        with Vertical(classes="block"):
            yield Label("本机登录过的账号", classes="block-title")
            yield Static("", id="login-accounts")
        with Vertical(classes="block"):
            yield Label("扫码登录", classes="block-title")
            yield Static("[dim]按 L 申请二维码，然后用**森空岛 APP** 扫。[/]",
                         id="login-note")
        yield Footer()

    def on_mount(self) -> None:
        self._abort = False
        self._busy = False
        #: 正在问"本次不登录还是以后都不"。问的时候再按 Esc 不该再叠一层问。
        self._asking = False
        #: 扫码**开始前**的账号快照。登录成功后要靠它分辨"登的是新号还是老号"
        #: （博士 2026-09-18：登到已有账号上要明说一句）。不快照就分不清——
        #: 登录写盘之后，那个号已经在列表里了。
        self._known_before: set[str] = set()
        self._cur_before: str | None = None
        #: 正在补全账号信息（联网）。与扫码登录互斥，两件事都会写凭据目录。
        self._filling = False
        self._refresh_accounts()

    def _refresh_accounts(self) -> None:
        """画"本机登录过的账号"那一块。**离线**——读的都是本地文件。

        退出账号不删文件，所以这里通常不止一行；"切回不必重扫"的根据就是它。
        每行显示**游戏用户名与游戏uid**（`D.describe_account`），因为博士认的
        是游戏里的那个名字与 uid，而不是凭据文件名上那串通行证账号 id。
        """
        try:
            from ak_tactic import skland
            rows = skland.known_accounts()
        except Exception as exc:                              # noqa: BLE001
            self.query_one("#login-accounts", Static).update(f"[warn]{exc}[/]")
            return
        cur = D.skland_uid()
        if not rows:
            self.query_one("#login-accounts", Static).update(
                "[dim]本机还没有登录过的账号。[/]")
            return
        lines = [D.describe_account(a["uid"], current=(a["uid"] == cur))
                 for a in rows]
        # 博士 2026-09-18：「按 O 退出账号——凭据文件保留，之后可切回，不必重扫」
        # 这一句从主界面搬到**这里**。它本来就只是在讲"退出"这件事，而退出这个
        # 动作也在这块屏上；主界面留着它要多占一行，矮窗口里正好把名册状态顶出去。
        hint = "按 O 退出账号——凭据文件保留，之后可切回，不必重扫。"
        hint += "\n按 S 切换账号（同样不必重扫）。"
        if any(not D.account_info(a["uid"])["known"] for a in rows):
            hint += "　按 U 补全游戏用户名与游戏 uid（联网，按一次问一次）。"
        self.query_one("#login-accounts", Static).update(
            "\n".join(lines) + f"\n[dim]{hint}[/]")

    @property
    def _qr_screen(self) -> QrScreen | None:
        """栈顶是不是那个二维码屏（状态更新要落到它身上）。"""
        scr = self.app.screen
        return scr if isinstance(scr, QrScreen) else None

    def _who(self, uid: str | None) -> str:
        """把"哪个账号"写成**游戏用户名 + 游戏uid**（博士 2026-09-18 口径）。

        登录账号 id 只作附注：它是凭据文件名上的东西，认不出人；而游戏用户名
        与 uid 是他在游戏里看到的那两个。还没问过森空岛时如实说"未知"并给出
        那一键（`U`）——空白会让人以为程序坏了。
        """
        uid = str(uid or "").strip()
        if not uid:
            return "（没有登录账号）"
        info = D.account_info(uid)
        nick = info["nick"] or "游戏用户名未知，按 U 问一次"
        game = info["game_uid"] or "未知，按 U 问一次"
        return f"{nick}　游戏uid={game}　[dim]（登录账号 {uid}）[/]"

    def _status(self) -> str:
        r = self.app.state.roster
        uid = D.skland_uid()
        head = ""
        try:
            from ak_tactic import skland
            st = skland.load_cred()
            who = f"当前账号：{self._who(uid)}\n" if uid else ""
            if st.get("cred"):
                head = (f"{who}已保存凭据：有效期内可直接 `status` 校验；"
                        "过期会由 hgToken 静默重铸。\n")
            elif st.get("hgToken"):
                head = f"{who}已保存 hgToken（尚未铸成 cred）。\n"
            else:
                head = f"{who}本机还没有任何森空岛凭据。\n"
        except Exception as exc:                              # noqa: BLE001
            if uid:
                head = f"[warn]读凭据失败：{exc}[/]\n"
            else:
                head = ("[warn]当前没有登录的账号。[/]\n"
                        "[dim]按 L 扫码登录；登过的号按 S 切回。[/]\n")
        if r is None:
            return head + "[warn]没有名册。[/]跳过登录不影响流程，编队那一步手动输名字即可。"
        return (head + f"名册来源：{r.source}，共 {len(r.operators)} 名。\n"
                "[dim]登录只决定名册要不要刷新，不决定流程能不能走完。[/]")

    # ---- 交互 ----

    def action_login(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._abort = False
        # 快照**扫码之前**的账号状态：登录写盘之后那个号已经在列表里了，
        # 不快照就分不清"登的是新号"还是"登回了老号"。
        try:
            from ak_tactic import skland
            self._known_before = {a["uid"] for a in skland.known_accounts()}
        except Exception:                                     # noqa: BLE001
            self._known_before = set()
        self._cur_before = D.skland_uid()
        self.query_one("#login-note", Static).update("正在申请二维码……")
        self._run_login()

    @work(thread=True, exclusive=True, group="login")
    def _run_login(self) -> None:
        """后台线程里跑完整条登录链；只回 UI 线程发消息。"""
        try:
            from ak_tactic import skland

            def on_qr(scan_id: str, content: str) -> None:
                self.post_message(self.QrReady(content))

            def on_status(status: int, text: str) -> None:
                if self._abort:
                    # 靠回调抛出来中止轮询——`login_by_qr` 没有取消参数，
                    # 而它每 2 秒一定会调一次这里。
                    raise skland.SklandError("已取消")
                self.post_message(self.QrStatus(status, text))

            skland.login_by_qr(on_qr=on_qr, on_status=on_status)
        except Exception as exc:                              # noqa: BLE001
            self.post_message(self.LoginDone(False, str(exc)))
            return
        self.post_message(self.LoginDone(True, "登录成功，凭据已保存。"))

    def on_login_screen_qr_ready(self, event: QrReady) -> None:
        # 二维码**另开一屏**全屏居中显示：嵌在本屏的块里会被挤到、裁掉一截，
        # 而二维码缺一个角就彻底作废（博士实测「显示不完整扫不了」）。
        self.query_one("#login-note", Static).update(
            "二维码已弹出（全屏居中）。\n[dim]有效期约 2 分钟；Esc 关掉它，"
            "按 L 可重新申请。[/]")
        self.app.push_screen(QrScreen(event.content))

    def on_login_screen_qr_status(self, event: QrStatus) -> None:
        scr = self._qr_screen
        if scr is not None:
            scr.set_note(f"[bold]{event.text}[/]　[dim]（Esc 关掉这张码）[/]")
        else:
            self.query_one("#login-note", Static).update(f"[bold]{event.text}[/]")

    def on_login_screen_login_done(self, event: LoginDone) -> None:
        self._busy = False
        # 结果一出来就把二维码收掉：一张已经作废的码留在屏幕上，只会诱人白扫
        if self._qr_screen is not None:
            self.app.pop_screen()
        if event.ok:
            # 他既然登了，那条「以后都不登录」就不该再拦着他
            D.save_config(login_prompt="")
            self.app.state.roster = D.load_roster()
            self._refresh_accounts()
            self.query_one("#login-note", Static).update(
                f"[bold]{event.text}[/]\n"
                "[dim]名册要另走 `skland fetch` 才会刷新（本屏只负责落凭据）。[/]")
            self.query_one("#login-status", Static).update(self._status())
            # **登录成功直接回主界面**（博士 2026-09-18 裁定）。原先留在本屏、
            # 等他按 Esc 才走，而 Esc 又弹一句「确定不登录吗」——他刚登进来。
            self._abort = True
            self.dismiss(self._back_note())
            return
        self.query_one("#login-note", Static).update(
            f"[warn]{event.text}[/]\n[dim]按 L 可以重新申请一个二维码。[/]")

    def _back_note(self) -> str:
        """登录成功后带回 `[0]` 屏、显示在账号行上的那句话。

        **登到已有账号上要明说**（博士 2026-09-18）：本机原先就登过这个号时，
        这次扫码只是刷新了凭据，账号条数没变——不提醒的话，人会以为多了一个号。
        三种情形分开说：登回当前这个号、登回本机已有的另一个号、新号。
        """
        uid = D.skland_uid()
        info = D.account_info(uid) if uid else {}
        who = info.get("nick") or "游戏用户名未知（按 U 问一次）"
        game = info.get("game_uid") or "未知（按 U 问一次）"
        msg = f"已登录：{who}　游戏uid={game}"
        if uid and uid == self._cur_before:
            msg += "；这个号**本来就登录着**，这次只刷新了凭据（账号没有变多）。"
        elif uid and uid in self._known_before:
            msg += ("；这个号**本机已经登录过**——凭据更新了，账号没有变多，"
                    "按 L 进登录屏后按 S 可以切回其他号。")
        else:
            msg += "；这是**新账号**，已加进本机账号列表（按 L 可按 S 切回旧号）。"
        return msg

    def action_switch(self) -> None:
        """切回本机登过的某个账号。**不联网、不重扫**——凭据与名册都在本地。"""
        try:
            from ak_tactic import skland
            accts = skland.known_accounts()
        except Exception as exc:                              # noqa: BLE001
            accts = []
            self.query_one("#login-note", Static).update(f"[warn]{exc}[/]")
        if not accts:
            self.query_one("#login-note", Static).update(
                "[warn]本机没有登录过的账号。[/]\n[dim]按 L 扫码登录。[/]")
            return
        cur = D.skland_uid()
        rows = []
        for a in accts:
            # 列表按**游戏用户名 + 游戏uid**排（登录账号 id 作附注），
            # 与账号列表、[0] 屏账号行同一口径。
            label = D.describe_account(a["uid"], current=(a["uid"] == cur))
            rows.append((a["uid"], label))
        self.app.push_screen(
            AskScreen("切换账号",
                      "凭据与名册都在这台机器上，切换不需要重新扫码。",
                      rows),
            self._switched)

    def _switched(self, uid: str | None) -> None:
        if not uid:
            return
        try:
            from ak_tactic import skland
            skland.activate(uid)
        except Exception as exc:                              # noqa: BLE001
            self.query_one("#login-note", Static).update(f"[warn]{exc}[/]")
            return
        # 名册必须**重读**：`load_roster()` 认的是当前账号，不重读就还是上一个号的
        self.app.state.roster = D.load_roster()
        self.query_one("#login-status", Static).update(self._status())
        self._refresh_accounts()
        self.query_one("#login-note", Static).update(
            f"[ok]已切到 {self._who(uid)}[/]\n[dim]名册已按这个账号重读。[/]")

    def action_fill(self) -> None:
        """按 `U`：把本机每个账号的**游戏用户名与游戏 uid**补全。**联网**。

        ## 为什么要有这一键

        账号列表要显示的是游戏用户名与游戏 uid（博士 2026-09-18 口径），而这两个
        量**离线推不出来**：登录账号 id 是通行证账号（13 位），游戏 uid 是 8 位，
        账号 id 不出现在任何一份森空岛数据里。唯一的来源是问一次森空岛再记住
        （`~/.skland/accounts.json`）。名册缓存里只带昵称、不带 uid，映射没建立
        的号就只能显示"未知"——所以给一个能补的键，而不是让人对着"未知"发愣。

        ## 为什么按一下才跑、为什么在后台线程

        联网动作不该在挂载时悄悄打一次（博士 2026-09-17 裁定）。而
        `resolve_game_uid_for` 要发 HTTP，在 UI 线程里做会把界面钉住。

        **一个账号失败不影响别的账号**：逐个记结果、逐个报，而不是整张列表一起
        沉掉。已经知道用户名与 uid 的号直接跳过，不白打接口。

        主界面原有一个只管**当前账号**的 `U`，博士 2026-09-18 把它撤了：
        同一件事不该有两个按钮，而这一版（本机全部账号）严格更全。
        """
        if self._busy or self._filling:
            return
        try:
            from ak_tactic import skland
            uids = [a["uid"] for a in skland.known_accounts()]
        except Exception as exc:                              # noqa: BLE001
            self.query_one("#login-note", Static).update(f"[warn]{exc}[/]")
            return
        if not uids:
            self.query_one("#login-note", Static).update(
                "[warn]本机没有登录过的账号。[/]\n[dim]按 L 扫码登录。[/]")
            return
        todo = [u for u in uids
                if not (D.account_info(u)["nick"] and D.account_info(u)["game_uid"])]
        if not todo:
            self.query_one("#login-note", Static).update(
                "[dim]账号信息本来就是全的：每个号的游戏用户名与游戏 uid 都已记下。[/]")
            return
        self._filling = True
        self.query_one("#login-note", Static).update(
            f"正在问森空岛补全 {len(todo)} 个账号的信息……")
        self._run_fill(todo)

    @work(thread=True, exclusive=True, group="fill")
    def _run_fill(self, uids: list[str]) -> None:
        """后台线程里逐个账号问绑定列表；只回 UI 线程发消息。"""
        from ak_tactic import skland
        lines: list[str] = []
        for uid in uids:
            info = D.account_info(uid)
            try:
                got = skland.resolve_game_uid_for(uid, uid=info["game_uid"] or None)
            except Exception as exc:                          # noqa: BLE001
                lines.append(f"[warn]账号 {uid} 补全失败：{exc}[/]")
                continue
            lines.append(f"[ok]{got.get('nickName') or '（森空岛没给昵称）'}[/]"
                         f"　游戏uid={got.get('gameUid')}"
                         f"　[dim]（登录账号 {uid}）[/]")
        if self.is_mounted:
            self.post_message(self.FillDone(lines))

    def on_login_screen_fill_done(self, event: FillDone) -> None:
        self._filling = False
        self._refresh_accounts()
        # 补全可能刚刚才把**游戏 uid** 定下来（原先离线推不出来），而名册是按
        # 游戏 uid 存的文件——所以顺手重读一次名册，别让主界面继续按旧状态画。
        self.app.state.roster = D.load_roster()
        if not event.lines:
            self.query_one("#login-note", Static).update(
                "[dim]没有需要补的账号。[/]")
            return
        self.query_one("#login-note", Static).update(
            "\n".join(event.lines)
            + "\n[dim]已记在 `~/.skland/accounts.json`，下次不必再问。[/]")

    def action_logout(self) -> None:
        """按 `O`：退出账号。**一个文件都不删**——只把"当前账号"这个指向清空。

        博士 2026-09-17 的裁定：退出账号是为了**换号**，所以凭据与名册全都留着，
        之后在这块屏上按 `S` 就能切回登过的号，不必重扫。

        博士 2026-09-18 把这个键从主界面搬到这里：退出是登录屏上的事（这里才有
        账号列表与「切回」的上下文），而主界面那行「按 O 退出账号……」的说明也
        一起搬了过来。
        """
        uid = D.skland_uid()
        if not uid:
            self.app.push_screen(AskScreen(
                "没有可退出的账号",
                "当前本来就没有登录的账号。\n"
                "按 L 扫码登录；登过的号按 L 再按 S 可以切回。",
                [("ok", "知道了")]))
            return
        others = [a for a in known_accounts_safe() if a["uid"] != uid]
        body = ("退出后当前账号的名册不再显示，会降级成 MAA OperBox"
                "（没有专精与模组等级）。\n"
                "**凭据与名册文件一个都不删。**")
        body += (f"\n本机另存着 {len(others)} 个登过的账号，之后按 S 可以切回。"
                 if others else "\n之后按 L 重新扫码即可登回。")
        self.app.push_screen(
            AskScreen("退出账号", body,
                      [("yes", "退出账号"), ("no", "不退出")]),
            self._logout_answered)

    def _logout_answered(self, choice: str | None) -> None:
        if choice == "yes":
            try:
                from ak_tactic import skland
                skland.logout()
            except Exception as exc:                          # noqa: BLE001
                self.query_one("#login-note", Static).update(
                    f"[warn]退出账号失败：{exc}[/]")
            else:
                # 退出账号 = 他想换号，那条「以后都不登录」就不该再拦着他
                D.save_config(login_prompt="")
                self.app.state.roster = D.load_roster()
        # 退完就地重画：登录态与账号列表（当前那只的 `←当前` 标记要落下来）
        self.query_one("#login-status", Static).update(self._status())
        self._refresh_accounts()

    def action_close(self) -> None:
        """Esc：**已经登录着就直接回主界面**，没登录才补问「不登录」那一句。

        博士 2026-09-18 收紧（原裁定是 2026-09-17 的「一律先问」）：
        「即使用户已经登录账号，现在按 Esc 返回主界面时也会弹出那个询问是否
        不登录的页面」——那一问问的是他已经做完的事。所以：

          * 手上有账号（`D.skland_uid()`）→ 直接 `dismiss` 回车，**不问**；
          * 手上确实没有账号 → 仍然问「本次 / 以后都不登录」。

        问这一次还是以后都——差别是真的：答「以后都不登录」写进
        `~/.rios/tui.json`，此后启动不再自动进登录向导；答「本次不登录」
        什么都不写，下一次全新启动还会问。
        """
        if self._asking:
            return
        if D.skland_uid():
            self._abort = True
            self.dismiss("")
            return
        self._asking = True
        self.app.push_screen(
            AskScreen(
                "不登录也可以",
                "登录只决定名册要不要刷新，不决定流程能不能走完。\n"
                "没有名册时，编队那一步可以手动输名字。",
                [("once", "本次不登录"),
                 ("never", "以后都不登录（此后启动不再问你）")]),
            self._answered)

    def _answered(self, choice: str | None) -> None:
        self._asking = False
        if choice is None:
            # Esc 回到登录屏。后台轮询**不停**——他可能只是按错了，
            # 而停掉之后二维码就废了，得重新申请一个。
            self.query_one("#login-note", Static).update("[dim]按 L 申请二维码。[/]")
            return
        if choice == "never":
            D.save_config(login_prompt="never")
        # 真正离开：走之前把后台轮询叫停，否则它会一直跑到 180 秒超时才罢休
        self._abort = True
        self.dismiss(None)


# ================================================================ [1] 选关卡
#
# 选关卡是**三层**，不是一层：
#   [1a] 章／活动   —— 114 条。「月行水上」在这一层，它含两个分部。
#   [1b] 分部／环境 —— **只在需要时才出现**：活动含多个 zone（实测 59 条），
#                      或该章有多个环境分层（第 9-14 章）。
#   [1c] 关卡       —— 「SR-EX-8　虚无之顶」，配一个难度筛选。
#
# 为什么必须有第二层：`zone_table` 的 477 条里有 103 个活动含多个 zone，而
# **「月行水上」这个名字根本不在 `zone_table` 里**——它在 `activity_table.json`
# 的 `basicInfo`，靠 `zoneToActivity` 才把 `act54side_zone1/2` 归到一起。
# 平铺成 477 行等于让用户自己认前缀。

class ChapterPickScreen(RiosScreen):
    """[1a] 选章节／活动。"""

    BINDINGS = both_cases([
        Binding("enter", "pick", "选定", key_display="Enter"),
        Binding("escape", "back", "返回", key_display="Esc"),
    ])

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(theme.step_bar(1), id="steps")
        yield Static("选章节／活动", id="title")
        yield Input(placeholder="输关键词筛：月行水上 / 第九章 / SR …（回车看全部）",
                    id="kw")
        yield DataTable(id="chapters")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#chapters", DataTable)
        t.cursor_type = "row"                     # 默认是 cell，高亮不动
        t.add_columns("章节／活动", "关卡", "分部")
        self._rows: list[dict] = D.chapter_rows()
        self._shown: list[dict] = []
        self._fill("")
        t.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._fill(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """输入框里的回车：焦点交给表格；只剩一行就直接选定。"""
        if len(self._shown) == 1:
            self.dismiss(self._shown[0])
            return
        self.query_one("#chapters", DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """**Enter 由 DataTable 自己吃掉**，Screen 上的 Binding("enter") 不会触发——
        必须挂这个事件。（踩过：binding 看着对，按下去毫无反应。）"""
        self._pick_key(str(event.row_key.value))

    def _fill(self, kw: str) -> None:
        t = self.query_one("#chapters", DataTable)
        t.clear()
        # **NFKC 归一**：中文输入法全角模式下敲进来的是 ＳＲ 而不是 SR，不归一
        # 就一条都筛不出来——“程序坏了”与“输入法开了全角”在界面上完全一样。
        k = unicodedata.normalize("NFKC", kw or "").strip().upper()
        self._shown = [
            c for c in self._rows
            if not k or k in c["title"].upper() or k in c["key"].upper()
            or any(k in p["title"].upper() for p in c["parts"])
            or any(k in p["zone_id"].upper() for p in c["parts"])
        ]
        for c in self._shown:
            t.add_row(c["title"], str(c["levels"]), self._parts_cell(c),
                      key=c["key"])

    #: 分部那一列最多写几个。剿灭作战有 15 个分部、35 个图名，全塞进一格会横到
    #: 屏幕外（实测那一格三百多字符），把「章节／活动」那列挤没了。筛选照旧
    #: 按**全部分部**匹配，这里只管显示。
    PARTS_SHOWN = 2

    @classmethod
    def _parts_cell(cls, chapter: dict) -> str:
        ps = chapter["parts"]
        if len(ps) < 2:                       # 单分部不给第二层菜单，这列留空
            return ""
        head = "、".join(p["title"] for p in ps[:cls.PARTS_SHOWN])
        rest = len(ps) - cls.PARTS_SHOWN
        return f"{head}　…（共 {len(ps)} 个分部）" if rest > 0 else head

    def _pick_key(self, key: str) -> None:
        for c in self._shown:
            if c["key"] == key:
                self.dismiss(c)
                return

    def action_pick(self) -> None:
        t = self.query_one("#chapters", DataTable)
        idx = t.cursor_row
        if 0 <= idx < len(self._shown):
            self.dismiss(self._shown[idx])

    def action_back(self) -> None:
        self.dismiss(None)


class PartPickScreen(RiosScreen):
    """[1b-1] 选哪一部分：一个活动含多个 zone 时才有这一层。"""

    BINDINGS = both_cases([
        Binding("enter", "pick", "选定", key_display="Enter"),
        Binding("escape", "back", "返回", key_display="Esc"),
    ])

    def __init__(self, chapter: dict) -> None:
        super().__init__()
        self.chapter = chapter
        self.parts = list(chapter["parts"])

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(theme.step_bar(1), id="steps")
        yield Static(f"{self.chapter['title']}　选哪一部分", id="title")
        yield DataTable(id="parts")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#parts", DataTable)
        t.cursor_type = "row"
        t.add_columns("部分", "关卡")
        for p in self.parts:
            t.add_row(p["title"], str(p["levels"]), key=p["zone_id"])
        t.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._pick(str(event.row_key.value))

    def _pick(self, zone_id: str) -> None:
        for p in self.parts:
            if p["zone_id"] == zone_id:
                self.dismiss(p)
                return

    def action_pick(self) -> None:
        t = self.query_one("#parts", DataTable)
        idx = t.cursor_row
        if 0 <= idx < len(self.parts):
            self.dismiss(self.parts[idx])

    def action_back(self) -> None:
        self.dismiss(None)


class EnvPickScreen(RiosScreen):
    """[1b-2] 选环境：主线第 9-14 章才有这一层。

    第 9 章只有剧情体验／标准实战（**没有磨难险地**），第 10-14 章三档齐全，
    而第 0-8 章与第 15-17 章全是 NONE——那些章这一层根本不出现，
    它们的「常规作战／险地作战」落在**难度**上（第 15 章 NORMAL 23 / SIX_STAR 16）。
    """

    BINDINGS = both_cases([
        Binding("enter", "pick", "选定", key_display="Enter"),
        Binding("escape", "back", "返回", key_display="Esc"),
    ])

    def __init__(self, zone_id: str, heading: str, envs: list[dict]) -> None:
        super().__init__()
        self.zone_id = zone_id
        self.heading = heading
        self.envs = list(envs)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(theme.step_bar(1), id="steps")
        yield Static(f"{self.heading}　选环境", id="title")
        yield DataTable(id="envs")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#envs", DataTable)
        t.cursor_type = "row"
        t.add_columns("环境", "关卡")
        for e in self.envs:
            t.add_row(e["label"], str(e["levels"]), key=e["env"])
        t.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._pick(str(event.row_key.value))

    def _pick(self, env: str) -> None:
        for e in self.envs:
            if e["env"] == env:
                self.dismiss(e)
                return

    def action_pick(self) -> None:
        t = self.query_one("#envs", DataTable)
        idx = t.cursor_row
        if 0 <= idx < len(self.envs):
            self.dismiss(self.envs[idx])

    def action_back(self) -> None:
        self.dismiss(None)


class StagePickScreen(RiosScreen):
    """[1c] 选关卡。

    只显示**关卡代号 + 关卡中文名**（「SR-EX-8　虚无之顶」）——博士明确要求
    **不显示 levelId、不显示区域**：前者是内部编号，后者已经在上一层选过了。

    难度是一个**筛选器**而不是常量：同一关常有普通版与 `#f#` 四星限定版并存
    （774 条），第 15-17 章则是普通与险地作战各占一半。只有一个难度档时不显示
    那一列，也不给筛选器——留着反而让人以为有得选。
    """

    BINDINGS = both_cases([
        Binding("enter", "pick", "选定", key_display="Enter"),
        Binding("escape", "back", "返回", key_display="Esc"),
    ])

    def __init__(self, *, zone_id: str = "", env: str = "",
                 heading: str = "") -> None:
        super().__init__()
        self.zone_id = zone_id
        self.env = env
        self.heading = heading or "全部关卡"
        self._diff = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(theme.step_bar(1), id="steps")
        yield Static(f"{self.heading}　选关卡", id="title")
        diffs = D.zone_diffs(self.zone_id, self.env) if self.zone_id else []
        if len(diffs) > 1:
            yield Select([(f"{d['label']}（{d['levels']} 关）", d["diff"])
                          for d in diffs], prompt="难度",
                         id="diff", allow_blank=True)
        yield Input(placeholder="输关键词筛：SR-EX / 虚无之顶 …（回车看全部）",
                    id="kw")
        yield DataTable(id="stages")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#stages", DataTable)
        t.cursor_type = "row"
        t.add_columns("关卡", "难度")
        self._rows: list[dict] = []
        self._fill()
        t.focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._diff = "" if event.value is Select.BLANK else str(event.value)
        self._fill()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._fill()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if len(self._rows) == 1:
            self.dismiss(self._rows[0])
            return
        self.query_one("#stages", DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._pick_key(str(event.row_key.value))

    def _fill(self) -> None:
        from ..db.stages import DIFFICULTY_LABELS
        t = self.query_one("#stages", DataTable)
        t.clear()
        kw = unicodedata.normalize("NFKC",          # 全角 ＳＲ → SR，见上
                                   self.query_one("#kw", Input).value or "")
        self._rows = D.stage_rows(keyword=kw, limit=400, zone_id=self.zone_id,
                                  env=self.env, difficulty=self._diff)
        one = len({r["difficulty"] for r in self._rows}) <= 1
        for r in self._rows:
            name = r.get("name") or ""
            code = r["code"] or r["level_id"]
            four = r["level_id"].endswith("#f#")
            label = f"{code}　{name}" if name else code
            if four and "突袭" not in name:
                label += "（四星）"           # 中文名一样，标出来才分得清
            diff = "" if one else DIFFICULTY_LABELS.get(
                r["difficulty"], r["difficulty"])
            t.add_row(label, diff, key=r["level_id"])

    def _pick_key(self, level_id: str) -> None:
        for r in self._rows:
            if r["level_id"] == level_id:
                self.dismiss(r)
                return

    def action_pick(self) -> None:
        t = self.query_one("#stages", DataTable)
        idx = t.cursor_row
        if 0 <= idx < len(self._rows):
            self.dismiss(self._rows[idx])

    def action_back(self) -> None:
        self.dismiss(None)


def _resolve_stage(query: str) -> dict | None:
    """把 `SR-EX-8` 这种写法解析成一条 stage 记录（供 `--stage` 用）。"""
    from ..db import DEFAULT_DB_PATH, connect
    from ..db.stages import resolve_code
    if not Path(DEFAULT_DB_PATH).exists():
        return None
    conn = connect()
    try:
        hit = resolve_code(conn, query)
    finally:
        conn.close()
    return hit


# ================================================================ [2] 选编队

class SquadList(SelectionList[str]):
    """选人用的列表框：只把「空格 勾选」露给 Footer，并把**回车让出去**。

    `SelectionList` 的 `space → select` 与父类 `OptionList` 的 `enter → select`
    都是 `show=False`（Textual 想让调用方自己写提示），于是底部只剩
    Enter / M / Esc——**用户根本看不出空格能勾人**。子类只改 `show`。

    回车这一条是**必须顶掉的**：父类 `OptionList` 的 `enter → select` 会把回车
    吃在列表里，屏上那个"开始解算"就永远等不到它（博士实测过：「回车与空格都是
    选人」）。这里改用 `skip_enter` → `SkipAction`，Textual 收到它在**不当作已处理**，
    键继续往上走，落到屏上的 `enter`。

    为什么不像以前那样在屏上用 `priority=True` 硬抢：那样连 `Select` 自己的回车
    也一起抢走了——门槛下拉框于是**打不开、也确认不了**（博士实测到的第二个 bug）。
    `priority` 是"从 App 往下查"、`skip_enter` 是"从焦点往上让"，后者只让出该让的。
    """

    BINDINGS = both_cases([
        Binding("space", "select", "勾选", key_display="空格", show=True),
        # 回车这条**要 show=True 并写上同一个说明**：Textual 的 Footer 按"键"去重，
        # 取离焦点最近的那一条——列表上挂一条 `show=False` 的 enter，就会把屏上
        # 那条「Enter 开始解算」顶掉，底部于是**看不见回车干什么**（实测如此）。
        # 说明写的是**回车真正会做的事**，不是这条绑定自己做的事。
        Binding("enter", "skip_enter", "开始解算", key_display="Enter",
                show=True),
    ])

    def action_skip_enter(self) -> None:
        """回车不吃：交给屏上的绑定（`SkipAction` = "这条我没处理"）。"""
        raise SkipAction()


class SquadAskScreen(RiosScreen):
    """[2a] 先决定**要不要手动加人**，再决定要不要进选人界面。

    不手动加人时**根本不进选人界面**：直接空手进解算，由搜索自己在名册里挑
    （模式 `auto`）。以前无论谁都要先滚一遍两百多人的列表，而「我不指定人」
    是更常见的那一种。
    """

    BINDINGS = both_cases([
        Binding("enter", "pick", "选定", key_display="Enter"),
        Binding("escape", "back", "返回", key_display="Esc"),
    ])

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(theme.step_bar(2), id="steps")
        yield Static("选编队　要不要手动加人", id="title")
        yield DataTable(id="ask")
        yield Footer()

    def on_mount(self) -> None:
        t = self.query_one("#ask", DataTable)
        t.cursor_type = "row"
        t.add_columns("做法", "说明")
        r = self.app.state.roster
        n = len(r.top()) if r is not None else 0
        self._choices = [
            {"manual": False, "label": "不用，让程序自己挑",
             "hint": "直接从名册里找组合，这一轮你不指定人"},
            {"manual": True, "label": "我自己选",
             "hint": (f"进选人界面，从名册的 {n} 人里勾"
                      if n else "进选人界面（现在没有名册，只能手输）")},
        ]
        for c in self._choices:
            t.add_row(c["label"], c["hint"], key="T" if c["manual"] else "F")
        t.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._pick(str(event.row_key.value) == "T")

    def _pick(self, manual: bool) -> None:
        for c in self._choices:
            if c["manual"] is manual:
                self.dismiss(c)
                return

    def action_pick(self) -> None:
        t = self.query_one("#ask", DataTable)
        idx = t.cursor_row
        if 0 <= idx < len(self._choices):
            self.dismiss(self._choices[idx])

    def action_back(self) -> None:
        self.dismiss(None)


class PickerRow(Static):
    """一行可选项（主职业行 / 子职业行）。

    ## 为什么不用 `Tabs`

    `Tabs` 排不下就**横向截断**，而中文是双宽字符：近卫一族 14 个子职业加上
    「全部」，光名字就是 78 列，再加每项的留白——80 列的窗口里最后 4 个直接
    看不见，**方向键也够不到**（实测见 `_proto/squad_rows_probe.py`：80x20 下
    「武者 本源近卫 佣兵 重剑手」落在行外）。分类行被截断比列表挤一点严重得多：
    截掉的那几个等于这个筛选维度不存在。

    所以这一行**自己折行**：排不下就多占一行，点得到、方向键也走得到。
    矮窗口下的让路规则见 `SquadPickScreen._fit_extra`。

    ## 布局与命中判定是同一份

    `_layout()` 既喂 `render()` 又喂点击命中，所以"看到的"和"点得到的"不会错位。
    渲染刻意不交给 Rich 的自动换行：那会多一层"实际折在哪"的推断，而命中判定
    必须与它逐格对齐。

    ## 一移动就生效

    方向键走到的同时就切筛选（不需要再按回车）。**这不是偷懒**：本屏的回车是
    `priority` 绑定（开始解算），若把"确认"也压在回车上，用户在分类行上按回车
    会直接开跑。
    """

    can_focus = True

    BINDINGS = [
        Binding("left", "move(-1)", "上一个", show=False),
        Binding("right", "move(1)", "下一个", show=False),
        Binding("home", "move(-999)", "头一个", show=False),
        Binding("end", "move(999)", "末一个", show=False),
    ]

    class Changed(Message):
        """选中项变了。`key` 为 None 时是「全部」。"""

        def __init__(self, row: "PickerRow", key: str | None) -> None:
            self.row = row
            self.key = key
            super().__init__()

    def __init__(self, *, big: bool = False, **kw) -> None:
        super().__init__("", **kw)
        self.big = big                      #: 主职业行（加粗、留白多）
        self._items: list[tuple[str, str]] = []   #: (key, 显示名)
        self._active: str | None = None
        self._boxes: list[tuple[int, int, int, str | None]] = []  # (行, x, 宽, key)

    # ---- 数据 ----

    def set_items(self, items: list[tuple[str, str]],
                  active: str | None = None) -> None:
        self._items = list(items)
        self._active = active
        self.refresh()

    @property
    def active(self) -> str | None:
        return self._active

    def set_active(self, key: str | None) -> None:
        if key == self._active:
            return
        self._active = key
        self.refresh()

    def index(self) -> int:
        for i, (k, _l) in enumerate(self._items):
            if (k or None) == (self._active or None):
                return i
        return 0

    # ---- 布局 ----

    def _layout(self, width: int) -> list[list[tuple[str, str, int, int]]]:
        """折成若干行：`[[(key, 显示名, 起始列, 占宽), …], …]`。

        每项的形式是 ` 名字 `（两侧各一格空格）：**间隔就是这两格空格**，
        所以 `gap` 是 0。这一条踩过坑：曾经 `gap=2` 只加在坐标推进里、没写进
        `render()` 的 Text，于是 `_boxes` 记的位置与画面越往右偏得越多
        （第 k 项偏 `k*gap` 列），点左边几项就选错人。**算法里算进去的列，
        必须真的写进 Text**——下面 `render()` 里那句 `" " * gap` 就是为这条留的。

        宽度用 `_cell_width`（即 Rich 的 `cell_len`），与"画出来占几列"同一把尺子。
        """
        gap = 0
        lines: list[list[tuple[str, str, int, int]]] = [[]]
        x = 0
        for key, label in self._items:
            w = _cell_width(label) + 2
            if lines[-1] and x + w > width:
                lines.append([])
                x = 0
            if not lines[-1] and w > width:
                w = width              # 窄到一项都放不下：让它占满，别消失
            lines[-1].append((key, label, x, w))
            x += w + gap
        return [ln for ln in lines if ln]

    def render(self) -> Text:
        width = max(8, self.size.width or 80)
        # 横向留白由 CSS 的 padding 负责，这里的 width 已经是内容宽度
        self._boxes = []
        gap = 0                       # 与 `_layout` 里的 gap 必须一致
        out = Text()
        for li, line in enumerate(self._layout(width)):
            if li:
                out.append("\n")
            for i, (key, label, x, w) in enumerate(line):
                if i:
                    out.append(" " * gap)
                out.append(" ")
                out.append(label, style="bold reverse" if
                           (key or None) == (self._active or None) else
                           ("bold" if self.big else ""))
                out.append(" ")
                self._boxes.append((li, x, w, key or None))
        return out

    # ---- 交互 ----

    def _keys(self) -> list[str | None]:
        return [k or None for k, _l in self._items]

    def _hit(self, line: int, x: int) -> tuple[bool, str | None]:
        """内容坐标 → 命中的项。返回 `(命中没有, 项的 key)`。

        单独抽出来是为了能**不挂载**就量折行后的命中（第二行照样点得到）：
        `on_click` 只负责把控件内坐标换算成内容坐标，判定全在这里。
        """
        for ln, bx, bw, key in self._boxes:
            if ln == line and bx <= x < bx + bw:
                return True, key
        return False, None

    def action_move(self, delta: int) -> None:
        keys = self._keys()
        if not keys:
            return
        i = max(0, min(len(keys) - 1, self.index() + delta))
        if keys[i] != (self._active or None):
            self._active = keys[i]
            self.refresh()
            self.post_message(self.Changed(self, keys[i]))

    def on_click(self, event) -> None:
        """点哪一项就选哪一项（命中判定用 `render()` 记下的格子）。

        `event.x/y` 是**控件内坐标**（含 padding），而格子记的是**内容坐标**，
        所以要减掉 `content_region` 相对控件原点的那一段。折行后第二行上的项
        同样点得到——格子带着自己的行号。
        """
        if not self._boxes:
            self.render()
        off = self.content_region.offset - self.region.offset
        hit, key = self._hit(event.y - off.y, event.x - off.x)
        if hit:
            if key != (self._active or None):
                self._active = key
                self.refresh()
                self.post_message(self.Changed(self, key))
            event.stop()


def _cell_width(s: str) -> int:
    """字符串在终端里占几列。

    直接用 Rich 的 `cell_len`，**不自己数 `east_asian_width`**：这一行最终是
    Textual/Rich 画出来的，命中判定必须跟"画出来的格子"对齐，而不是跟终端
    （或我）对东亚歧义字符的另一种理解对齐。差一格，点上去就会选错人。
    """
    return cell_len(s)


class SquadPickScreen(RiosScreen):
    """[2b] 选编队：主职业行 + 子职业行 + 练度门槛 + 两种模式。

    交互是博士定的（2026-09-17、2026-09-18 两次）：

    - **主职业行**（`#prof-row`）最左边有「全部」，**默认停在「全部」上**；
      选中某个主职业时，**子职业行**（`#sub-row`）才出现，列出这个职业的子职业；
      停在「全部」时子职业行**整行不显示**（博士 2026-09-18 的原话）。
    - 子职业行里也有「全部」＝不按子职业再筛一层——**必须有它**，否则选中一个
      主职业的瞬间就被第一个子职业筛住了，用户会以为这个职业只有那么几个人。
    - 练度门槛做成**一个三档下拉**（不限 / ≥精英二60 / 精英二90），
      而不是「精英化」「等级」两个独立下拉——独立的两个会让人去凑
      「精英 0 且 90 级」这种筛不出东西的组合；
    - `M` 仍然切「允许程序补充 / 只用我选的」。

    **`G` 键已经去掉了**（博士 2026-09-18：「选人界面可以去掉按 G 切换分类的功能了，
    与新加上的筛选重复」）。以前 `G` 在「表头按主职业」与「表头按主职业·子职业」
    之间循环；现在**子职业是靠子职业行筛的**，表头再按子职业分一次组只是把同一个
    信息说两遍——而且筛到某个子职业时，列表里那一堆表头全是同一行字。
    所以表头**固定按主职业**（`D.group_label(op)` 的默认档），
    顶上那行说明里的「分组：…」也一并去掉，剩下范围 / 练度 / 筛出 / 已勾。

    **换分类或换门槛都不能丢已勾的人**：勾选状态另存一份 `_picked`，
    列表重建后逐条选回来。否则用户勾了五个人、手一抖切了下分类，
    五个勾全没了——而列表看上去只是「重排了一下」。

    ## 终端里没有"字号"

    图上那一行是**大号字**，终端做不到变字号——能变的是**字重与留白**。
    所以这里把「大字」落实成：加粗 + 上下各留一行 + 每个项之间空两格
    （`#prof-row` 高 3、`Tabs Tab` 左右内边距 2）。矮窗口下这些留白全部让路
    （见 `_fit_extra`），一行也不多占。
    """

    #: 矮窗口（`_fit_extra` 里按高度赋值）。类属性先给个默认值：
    #: `_render_mode` 在 `on_mount` 里就会跑一次，那会儿还没有 `_fit_extra`。
    _compact = False

    BINDINGS = both_cases([
        # 回车＝开始解算。**不用 `priority=True`**：那会连 `Select` 自己的回车
        # 一起抢走（门槛下拉框打不开、确认不了）。列表那边用 `skip_enter` 把
        # 回车让出来，见 `SquadList` 的说明。
        Binding("enter", "go", "开始解算", key_display="Enter"),
        Binding("m", "toggle_mode", "切换模式", key_display="M"),
        Binding("escape", "back", "返回", key_display="Esc"),
    ])

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(theme.step_bar(2), id="steps")
        yield Static("", id="mode-line")
        # 练度门槛：**整行宽**（图上就是一行，右侧一个 ▼）。原先套在
        # `Horizontal` 里，宽度被压成内容宽，下拉框看上去像个附注。
        #
        # **`allow_blank=False` + 给初值**：`allow_blank=True` 时下拉里会多出
        # 一条空白项，标签是 `prompt`（于是博士看到选项里有一项就叫「练度门槛」），
        # 选中它给的是 `Select.NULL` ——以前拿它直接 `int()` 就崩掉整个程序。
        # 现在没有那一项，当前档位写在上面那行说明里（`练度：…`）。
        yield Select([(label, str(i))
                      for i, (label, _e, _l) in enumerate(D.TRAINED_FILTERS)],
                     allow_blank=False, value="0", id="f-trained")
        yield PickerRow(big=True, id="prof-row")
        yield PickerRow(id="sub-row")
        yield SquadList(id="squad")
        yield Footer()

    def on_mount(self) -> None:
        self._prof: str | None = None         # None = 全部
        self._sub: str | None = None          # None = 该职业下不再筛
        self._min_index = 0                   #: 门槛档位下标（写进顶上那行说明）
        self._min = (0, 1)                    # (精英段下限, 段内等级下限)
        self._picked: set[str] = set(self.app.state.squad)
        self._build_prof_row()
        self._build_sub_row()
        self._fill()
        self._render_mode()

    # ---- 两行分类 ----

    def _roster_ops(self) -> list:
        r = self.app.state.roster
        return list(r.top()) if r is not None else []

    def _build_prof_row(self) -> None:
        """主职业行：`全部` + 名册里实际有的主职业（按游戏顺序）。"""
        row = self.query_one("#prof-row", PickerRow)
        row.set_items([("", D.PROF_ALL)]
                      + [(code, D.PROFESSION_CN.get(code, code))
                         for code in D.professions_in(self._roster_ops())],
                      active="")

    def _build_sub_row(self) -> None:
        """子职业行：只在选中了某个主职业时显示（博士 2026-09-18）。

        行内首项是「全部」（＝这一职业下不再按子职业筛）。名册里取不到任何
        子职业名（老版名册、或这个职业只有一个人）时**整行不显示**——显示一行
        只有一个「全部」的按钮没有任何意义。
        """
        row = self.query_one("#sub-row", PickerRow)
        subs = (D.sub_professions_in(self._roster_ops(), self._prof)
                if self._prof else [])
        self._sub = None
        if not subs:
            row.set_items([])
            row.styles.display = "none"
            return
        row.styles.display = "block"
        row.set_items([("", D.PROF_ALL)] + [(name, name) for name in subs],
                      active="")

    def on_picker_row_changed(self, event: PickerRow.Changed) -> None:
        """两行分类各自接一次（按 `row.id` 分派）。"""
        row_id = event.row.id or ""
        if row_id == "prof-row":
            self._prof = event.key or None
            self._build_sub_row()   # 主职业变了 → 子职业行重建并回到「全部」
            self._fill()
            self._render_mode()
        elif row_id == "sub-row":
            self._sub = event.key or None
            self._fill()
            self._render_mode()

    # ---- 列表构建 ----

    def _visible(self) -> list:
        ops = self._roster_ops()
        if not ops:
            return []
        elite_min, level_min = self._min
        ops = [o for o in ops if D.meets_trained(o, elite_min, level_min)]
        if self._prof:                        # 主职业行选了某个职业
            ops = [o for o in ops if o.profession == self._prof]
        if self._prof and self._sub:          # 子职业行再筛一层
            ops = [o for o in ops
                   if (o.sub_profession or "").strip() == self._sub]
        # 先按主职业、再按子职业**稳定排序**：`sorted` 是稳定的，而 `r.top()`
        # 已经是练度降序，所以组内会自动保持「练度高的在前」。
        ops.sort(key=lambda o: (
            D.PROFESSION_ORDER.index(o.profession)
            if o.profession in D.PROFESSION_ORDER else 99,
            o.sub_profession or ""))
        return ops

    def _fill(self) -> None:
        lst = self.query_one("#squad", SelectionList)
        lst.clear_options()
        last = None
        for op in self._visible():
            head = D.group_label(op)      # 表头固定按主职业（见 `_fill` 的说明）
            if head != last:
                # 分组表头：一条**不可选**的哑行。用 `disabled` 而不是普通项，
                # 否则它会被算进 `selected`、混进最终编队里。
                lst.add_option(Selection(f"── {head} ──", f"__head__{head}",
                                         disabled=True))
                last = head
            lst.add_option(Selection(op.label(), op.name))
        for name in self._picked:                 # 把已勾的选回来
            try:
                lst.select(name)
            except Exception:                     # noqa: BLE001
                pass                              # 被门槛筛掉或名册里没这个人
        # **焦点不能被它抢走**：用户正在分类行上用方向键挑范围，每挑一次都会
        # 重建列表；这时把焦点塞回列表，下一次方向键就落到列表上——表现是
        # 「方向键只用得了一次」（自检里就是这么红的）。
        if not isinstance(self.app.focused, PickerRow):
            lst.focus()
        # **光标要有落点**：`SelectionList` 初始 `highlighted=None`，此时按空格
        # **什么都不会发生**（`action_select` 找不到落点），症状正是博士说的
        # 「空格也是选人/按了没反应」——其实一个都没勾上。重建后落点是 None，
        # 所以这里每次都补一下。
        lst.action_first()

    def on_selection_list_selected_changed(
            self, event: SelectionList.SelectedChanged) -> None:
        self._picked = set(event.selection_list.selected)
        self._render_mode()

    def on_select_changed(self, event: Select.Changed) -> None:
        """练度门槛变了。

        **任何"不是合法档位"的值都退回「不限」**，绝不做 `int()` 硬解：
        Textual 在没选值时给的是 `Select.NULL`（`str()` 出来是 `"Select.NULL"`），
        以前那一版就是这么把整个程序崩掉的（博士实测）。多一个分支不花什么，
        崩一次要重开。
        """
        if event.select.id != "f-trained":
            return
        try:
            idx = int(str(event.value))
            _label, e, lv = D.TRAINED_FILTERS[idx]
        except (TypeError, ValueError, IndexError):
            idx, (e, lv) = 0, (0, 1)
        self._min_index = idx
        self._min = (e, lv)
        self._fill()
        self._render_mode()

    # ---- 顶上的两行说明 ----

    def _render_mode(self) -> None:
        st = self.app.state
        scope = D.PROFESSION_CN.get(self._prof or "", self._prof or "") or D.PROF_ALL
        if self._prof and self._sub:
            scope = f"{scope}·{self._sub}"
        shown = len(self._visible())
        mode = ("允许程序补充" if st.mode == "auto" else "只用我选的")
        # 门槛这一档也写在这儿：下拉框本身只显示当前值（「不限」/「≥ 精英二 60 级」），
        # 而"这行是练度门槛"得有个地方说得清——写在这一行不额外占高度（矮窗口
        # 一行都不能多花）。
        train = D.TRAINED_FILTERS[self._min_index][0]
        if self._compact:
            # 矮窗口里这行**只占一行**：省下的那一行给子职业行折出来的第二行。
            # 计数与范围一个字都不少，少的是那句解释——而那句按 M 切换时本来就
            # 一眼能看出来，不必常驻。
            self.query_one("#mode-line", Static).update(
                f"范围：[bold]{scope}[/]　练度：[bold]{train}[/]　"
                f"筛出 [bold]{shown}[/] 人　"
                f"已勾 [bold]{len(self._picked)}[/] 人　"
                f"[dim]{mode}[/]")
            return
        txt = (f"范围：[bold]{scope}[/]　练度：[bold]{train}[/]　"
               f"筛出 [bold]{shown}[/] 人　"
               f"已勾 [bold]{len(self._picked)}[/] 人\n")
        if st.mode == "auto":
            # 不再写「补到 24 人」这个数（博士 2026-09-18：「编队人数部分只写
            # 使用了几人编队」）。24 是**候选池**大小，与出战人数是两件事，写在
            # 编队这一屏只会让人以为要带 24 个人上场。池子多大是程序内部的事，
            # 出来几个人的编队在结果屏上写着（「用到的干员（N 人）」）。
            txt += ("模式：[bold]允许程序补充[/]　"
                    "[dim]你勾的人优先；不够的程序从名册按练度补人来挑组合[/]")
        else:
            txt += ("模式：[bold]只用我选的[/]　"
                    "[dim]只在勾的这些人里找组合，一个都没勾就搜不出东西[/]")
        self.query_one("#mode-line", Static).update(txt)

    def action_toggle_mode(self) -> None:
        st = self.app.state
        st.mode = "only" if st.mode == "auto" else "auto"
        self._render_mode()

    # ---- 矮窗口：两行分类的留白让路，行本身留着 ----

    def _fit_extra(self, h: int) -> None:
        """分类行**一行都不许少**，让掉的只是留白。

        主职业行平时占 3 行（加粗 + 上下各留一行，这是终端里能做到的"大字"），
        矮窗口下把留白收掉。子职业行按内容折行，矮窗口下**不压**（见下）。
        两行都留着，是因为少了任何一行，用户就**没法把范围调回来**
        （只有列表可滚动、而列表里没有"全部"这一项）。
        """
        compact = h < RiosScreen.COMPACT_HEIGHT
        self._compact = compact
        self.query_one("#prof-row", PickerRow).styles.padding = (
            (0, 2) if compact else (1, 2))
        # 子职业行本就把放不下的项折到下一行（博士 2026-09-18：子职业放不下
        # 可以分两行），所以这里**不动它的高度**——压了就等于把折出来的第二行
        # 藏掉。各占几行由 `PickerRow` 按内容定（`height: auto`）。
        #
        # 矮窗口里顶上那句说明收成一行（见 `_render_mode`）：80x12 下省下的
        # 那一行正好把子职业行折出来的第二行装进去，列表还留得下 3 行。
        # **不要动 `#f-trained` 的高度**：把它压成 1 行，它内部的当前值那格就
        # 落到可见区外了（自检里 `选人屏@80x12` 报的正是这个），得不偿失。
        try:
            self._render_mode()
        except Exception:                                     # noqa: BLE001
            pass                    # 还没 mount 完时 `#mode-line` 取不到

    def action_go(self) -> None:
        self.dismiss(sorted(self._picked))

    def action_back(self) -> None:
        self.dismiss(None)


# ================================================================ [3] 解算

class SolveScreen(RiosScreen):
    """[3] 解算：进度条 + 真实计数 + 日志。

    进度条的百分比**不是编的**：搜索有上限 `max_depth`/候选规模，这里用
    `evaluated` 的增长给一个"还在动"的脉动，并把真实计数原样打出来。
    没有精确分母就不假装有分母——这比一条匀速爬到 90% 再卡住的假进度条诚实。
    """

    BINDINGS = both_cases([Binding("q", "cancel", "中止", key_display="Q")])


    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(theme.step_bar(3), id="steps")
        with Vertical(classes="block"):
            yield Label("解算中", classes="block-title")
            yield Static("", id="solve-head")
        yield ProgressBar(total=100, show_eta=False, id="prog")
        yield Static("", id="log")
        yield Footer()

    def on_mount(self) -> None:
        st = self.app.state
        squad = "、".join(st.squad) if st.squad else "（不指定，全名册）"
        mode = "允许补充" if st.mode == "auto" else "只用我选的"
        self._t0 = time.time()
        self._lines: list[str] = []
        self._aborted = False
        self.app.state.depth = DEPTH_START
        self.app.state.deploy_limit = 0
        # 开局那几行走同一个 `_head_text()`：极矮窗口下它自己会压成两行，
        # 免得"开局显示三行、第一跳变成两行"抖一下。
        self._fit()
        self.query_one("#solve-head", Static).update(self._head_text(0, 0.0))
        self._log("开始解算……")
        self.set_interval(0.25, self._tick)
        self._worker = self._run()

    def _log(self, msg: str) -> None:
        """往日志里追加一行。

        `#log` 在 CSS 里是可滚动的（`overflow-y: auto`），但这里只留**最后 14 行**
        ——这一屏的意义是"看得见它在动"，不是"留下完整档案"；真要看全，结果屏
        与 `--report` 才是那条路。
        """
        self._lines.append(f"[dim]{time.time() - self._t0:6.1f}s[/]  {msg}")
        self.query_one("#log", Static).update("\n".join(self._lines[-14:]))

    def _tick(self) -> None:
        st = self.app.state
        n = getattr(st.searcher, "evaluated", 0)
        elapsed = time.time() - self._t0
        self.query_one("#prog", ProgressBar).update(
            progress=min(95.0, 5.0 + n * 0.6))
        self.query_one("#solve-head", Static).update(self._head_text(n, elapsed))

    def _head_text(self, n: int, elapsed: float) -> str:
        """这一屏头顶那几行。

        **窗口极矮时压成两行**（博士 2026-09-18：「保证终端窗口小的时候也要让玩家
        看到所有内容」）：关卡与人数上限缩到一行、计数缩到一行，一行都不丢——
        丢的只是换行，不是内容。编队那一行在最矮这档并进第一行（"用什么编队"与
        "最多几个人"本来就是一件事的两面）。
        """
        st = self.app.state
        depth = getattr(st, "depth", DEPTH_START)
        limit = getattr(st, "deploy_limit", 0)
        squad = "、".join(st.squad) if st.squad else "（不指定，全名册）"
        mode = "允许补充" if st.mode == "auto" else "只用我选的"
        try:
            h = self.size.height
        except Exception:                                     # noqa: BLE001
            h = 0
        if h and h < self.TINY_HEIGHT:
            cap = f"（本关可部署 {limit}）" if limit else ""
            return (f"{st.stage['code']}　本轮最多 {depth} 人{cap}\n"
                    f"已评估 [bold]{n}[/] 个候选　已用 {elapsed:.0f} 秒")
        # 正常那版：`本轮最多 N 人` 是搜索的深度上限，也就是"这个方案最多用几个人"；
        # 本关的可部署上限写出来，是给他一个"还能再加深到几"的边界。
        # 候选池多大（`pool_note`）**不进这一屏**，只在日志里出现。
        cap = f"　[dim]本关最多可部署 {limit} 人[/]" if limit else ""
        out = (f"关卡：{st.stage['code']}（{st.stage['level_id']}）\n"
               f"本轮最多 {depth} 人{cap}\n")
        # 编队那一行是**上下文**，不是这一屏的主角（他在上一屏刚选过），所以
        # 矮窗口下先收它——同一条"数据 > 说明"的优先级。
        if not h or h >= self.COMPACT_HEIGHT:
            out += f"[dim]编队：{squad}　模式：{mode}[/]\n"
        return out + f"已评估 [bold]{n}[/] 个候选　已用 {elapsed:.0f} 秒"

    @work(thread=True, exclusive=True)
    def _run(self) -> None:
        """在后台线程里跑搜索。界面线程只负责读计数器。

        ## 为什么要在这个循环里做「自动加深」

        博士 2026-09-18：「关卡可部署人数要接进来，默认还是 4 人，找不到的情况就
        做自动加深」。所以先按 4 人跑一遍（大多数关卡这样就够），只有在**没找到
        三星**时才往上加，一直加到这一关的可部署人数为止（`depth_ladder()`）。

        加深的代价是真实的——每深一层都要把搜索整个重跑一遍——所以每一轮都往日志
        里写一行，让人看得见"它在加深，不是卡住了"。
        """
        st = self.app.state
        result = None
        try:
            from ..plan import Roster as PlanRoster
            from ..search import Searcher
            roster = PlanRoster.from_json(st.roster.path)
            st.plan_roster = roster
            pool, st.pool_note = self._pool(roster)
            # 候选池只在日志里说一句——博士 2026-09-18 要的是"编队部分只写出战
            # 人数"，但"这一轮为什么这么久"得有地方答，日志正是那块地方。
            # 措辞必须点明它与出战人数无关，否则又变成"要带 24 个人上场"的误会。
            if st.pool_note:
                self.app.call_from_thread(
                    self._log, f"候选池：{st.pool_note}"
                              "　[dim]（这是程序挑组合的范围，不是出战人数）[/]")
            searcher = Searcher(verbose=False)
            st.searcher = searcher
            level_id = st.stage["level_id"]
            try:
                st.deploy_limit = searcher.deploy_limit(level_id)
            except Exception as exc:                      # noqa: BLE001
                st.deploy_limit = 0
                self.app.call_from_thread(
                    self._log,
                    f"[warn]取不到本关的可部署人数（{type(exc).__name__}: {exc}），"
                    f"按编队上限 {SQUAD_CAP} 人封顶[/]")
            ladder = depth_ladder(st.deploy_limit)
            if st.deploy_limit:
                self.app.call_from_thread(
                    self._log,
                    f"本关最多可部署 {st.deploy_limit} 人；先按 {ladder[0]} 人找")
            for i, depth in enumerate(ladder):
                st.depth = depth
                if len(ladder) > 1:
                    self.app.call_from_thread(
                        self._log, f"第 {i + 1}/{len(ladder)} 轮：最多 {depth} 人")
                result = searcher.search(level_id, roster, pool, max_ops=depth)
                if result is not None and result.verdict is not None \
                        and result.verdict.stars == 3:
                    break
                if i + 1 < len(ladder):
                    self.app.call_from_thread(
                        self._log,
                        f"{depth} 人以内没找到三星，加深到 {ladder[i + 1]} 人再试一轮")
            else:
                # 跑到阶梯末端还是没有三星（`for` 的 `else`：一次都没 break）。
                # 此时 `result` 是**最深那一轮**的结果，它里面带着"最好差在哪"。
                if len(ladder) > 1:
                    self.app.call_from_thread(
                        self._log,
                        f"加深到 {ladder[-1]} 人（本关可部署上限）仍没找到三星，"
                        "把最接近的那个方案交给你")
        except Exception as exc:                          # noqa: BLE001
            st.error = f"{type(exc).__name__}: {exc}"
            self.app.call_from_thread(self._done, None)
            return
        st.result = result
        self.app.call_from_thread(self._done, result)

    def _pool(self, roster) -> tuple[list[str], str]:
        """这一轮解算的**人选池**：勾的人 + （auto 时）名册里按练度补的人。

        ## 为什么非有这一步

        原先两条路都把 `st.squad` 原样交给搜索，于是：

          * 勾了人 → 只在那几个人里找（`mode` 根本没进搜索，界面上那句
            「程序还可以再挑人补位」是句空话）；
          * **不勾人 → 空池子**。`candidates_for` 是按名单遍历的，空名单一个候选
            都不产生，搜索当场返回「几何剪枝后一个候选都不剩」——而那句话把原因
            指向了坐标口径，完全指错方向。

        `[2a]` 那一屏的**默认项**正是「不用，让程序自己挑」。所以默认这条路
        永远出不来东西，症状就是博士报的「没有可用结果」——两个关卡都一样。

        池子总大小见 `AUTO_POOL`：补人要补得动，也要跑得完。
        """
        st = self.app.state
        kept = [n for n in (st.squad or []) if roster.get(n)]
        missing = [n for n in (st.squad or []) if not roster.get(n)]
        if st.mode == "only":
            note = f"只用勾的 {len(kept)} 人"
            if missing:
                note += f"（名册里没有：{'、'.join(missing[:3])}）"
            if not kept:
                note = ("「只用我选的」但一个人都没勾——池子是空的，搜不出东西。"
                        "回去勾人，或按 M 换成「允许程序补充」。")
            return kept, note
        extra: list[str] = []
        want = max(0, AUTO_POOL - len(kept))       # 池子补到 AUTO_POOL 人为止
        tui_roster = st.roster
        if tui_roster is not None and want:
            seen = set(kept)
            for op in tui_roster.top():            # `top()` 已按练度降序
                if len(extra) >= want:
                    break
                if op.name not in seen and roster.get(op.name):
                    seen.add(op.name)
                    extra.append(op.name)
        if not kept and not extra:
            return [], "名册是空的，池子里一个人都没有。"
        note = (f"勾的 {len(kept)} 人 + 名册按练度补 {len(extra)} 人"
                f"（共 {len(kept) + len(extra)} 人）")
        if missing:
            note += f"　[d]名册里没有：{'、'.join(missing[:3])}[/]"
        return kept + extra, note

    def _done(self, result) -> None:
        # 已经中止了就别再推结果屏：后台线程拦不住（Python 杀不掉线程），
        # 它跑完照样会 `call_from_thread` 回到这里。
        if self._aborted:
            return
        self.query_one("#prog", ProgressBar).update(progress=100.0)
        self._log("完成。" if result else f"失败：{self.app.state.error}")
        self.app.push_screen(ResultScreen())

    def action_cancel(self) -> None:
        """中止这次解算，**退回上一步**（编队那一屏）。

        原先这里是 `self.app.exit()`——Footer 上写着「中止」，按下去却把
        整个程序关掉。博士 2026-09-17 裁定：「结算中止退回上一步」。

        三件事都得做：① 标已中止，挡住后台线程回来后推结果屏；
        ② `cancel()` 那个 Worker，免得它的结果回调再触发一次；
        ③ 退回上一步——走 `back_to_step()`，因为解算屏**不是** `push_step`
        推的，路径顶格就是它的上一步，不能像向导屏那样先丢掉自己。
        """
        self._aborted = True
        w = getattr(self, "_worker", None)
        if w is not None:
            w.cancel()
        self.app.back_to_step()


# ================================================================ [4] 结果

class ResultScreen(RiosScreen):
    """[4] 结果：通过的编队、模组、技能，以及导出。

    ## 这一屏**不挂 Esc**（博士 2026-09-17 裁定）

    原话：「结果屏只留退出程序和回主界面」。所以 `Esc` 不会被补上——它在这里
    能做的事与别的出口重复，而这一屏不是向导屏、没有"上一步"可退。

    出口三个（2026-09-18 加第三个）：

    * `Q` 退出程序；
    * `H` 回 [0] 准备屏（整轮重来，连关卡也忘掉）；
    * `R` **回选关页**——博士要的「算完一关，换个关卡接着算」：退到关卡列表为止，
      章/活动、分部、环境的选择都还留着，**编队也留着**（换一关通常还是同一队）。

    `E` 导出不是出口，是这一屏存在的理由（产出 MAA 作业）。
    """

    BINDINGS = both_cases([
        Binding("e", "export", "导出", key_display="E"),
        Binding("r", "stage_list", "重选关卡", key_display="R"),
        Binding("h", "home", "主界面", key_display="H"),
        Binding("q", "quit", "退出程序", key_display="Q"),
    ])

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(theme.step_bar(4), id="steps")
        yield Static(self._body(), id="result")
        yield Static("", id="msg")
        yield Footer()

    def on_mount(self) -> None:
        self._msg()

    def _msg(self) -> None:
        self.query_one("#msg", Static).update(
            "[dim]E 导出作业到 " + str(D.guides_dir()) + "/<关卡名>/[/]")

    def _body(self) -> str:
        st = self.app.state
        if st.error:
            return f"[bad]解算失败[/]\n\n{st.error}"
        r = st.result
        if r is None:
            return "[warn]没有结果。[/]"
        rows = [f"[bold]{st.stage['code']}[/]　{st.stage['level_id']}", ""]
        v = getattr(r, "verdict", None)
        if v is None:
            rows.append("[warn]这次没找到三星方案。[/]")
        else:
            stars = int(getattr(v, "stars", 0) or 0)
            rows.append(f"  评价　　　{'★' * max(0, stars)}{'☆' * max(0, 3 - stars)}"
                        f"（{'胜利' if getattr(v, 'won', False) else '失败'}）")
            for label, attr, fmt in (("时长", "elapsed", "{:.1f}s"),
                                     ("击杀", "kills", "{}"),
                                     ("漏怪", "leaks", "{}"),
                                     ("剩余生命", "life", "{}"),
                                     ("总伤害", "damage", "{:,.0f}")):
                x = getattr(v, attr, None)
                if x is not None:
                    rows.append(f"  {label}　　　{fmt.format(x)}")
        plan = getattr(r, "plan", None)
        rows.append("")
        if plan is None:
            rows.append("[warn]没有可导出的编队。[/]")
        else:
            ops = getattr(plan, "deploys", []) or []
            # 「用了哪些干员」——与写进作业 doc.details 的是**同一份取数**
            # （`maa_export.used_operators`），这里只是换了排版。
            rows.append(f"[bold]用到的干员（{len(ops)} 人，按部署顺序）[/]")
            rows.extend("  " + ln for ln in maa.operators_lines(plan, st.plan_roster))
            rows.append("")
            rows.append("[dim]编制要求取自名册（真实专精 / 模组 / 信赖）。[/]")
        rows.append("")
        rows.append(f"[dim]已评估 {getattr(r, 'evaluated', 0)} 个方案，"
                    f"最深 {getattr(r, 'depth', 0)} 人。[/]")
        # **为什么要把 `note` 摆出来**：搜索"没有三星方案"有四种完全不同的来路
        # （几何剪枝后没候选 / 没位置可加 / 全是失败 / 到了人头上限），原先这一屏
        # 只会说一句"这次没找到三星方案"，四种情况看起来一模一样——博士报的
        # "无论选什么都是 0 条结果，似乎没接上模拟器"就长这样：真因一个在**地图**
        # （`buildableType: ALL` 曾被判成"两种都不能放"，整图 0 个落位）、
        # 一个在**结算**（天桩-甲既打不死也不会离场，有它的关卡永远跑满上限、
        # 全是 0 星）。两处都在 `docs/environment.md` 第十二 / 十四节。
        # 一句话的差别决定了要不要去查模拟器。
        note = str(getattr(r, "note", "") or "").strip()
        if note:
            rows.append("")
            rows.append(f"[warn]{note}[/]")
        return "\n".join(rows)

    def action_export(self) -> None:
        """把结果编队写成 MAA 认得的作业，落到 `<Guides>/<关卡名>/<关卡名>-<序号>.json`。"""
        st = self.app.state
        plan = getattr(st.result, "plan", None) if st.result is not None else None
        if plan is None:
            self._say("[warn]没有可导出的编队。[/]")
            return
        try:
            v = getattr(st.result, "verdict", None)
            note = ""
            if v is not None:
                stars = int(getattr(v, "stars", 0) or 0)
                note = (f"模拟预测：{'胜利' if getattr(v, 'won', False) else '失败'}，"
                        f"{getattr(v, 'elapsed', 0):.1f}s，击杀 {getattr(v, 'kills', 0)}，"
                        f"漏怪 {getattr(v, 'leaks', 0)}，剩余生命 "
                        f"{getattr(v, 'life', 0)}/{getattr(v, 'max_life', 0)}，"
                        f"总伤害 {getattr(v, 'damage', 0):,.0f}。\n")
                if stars < 3:
                    note += ("**注意：这份方案不是三星**（有漏怪或掉命），"
                             "放进 MAA 之前请先自行确认。\n")
            data = maa.to_maa(
                plan, st.plan_roster,
                stage_name=st.stage["level_id"],
                difficulty=st.stage.get("difficulty"),
                title=f"{st.stage['code']} {' '.join(st.squad) or '自动编队'}",
                details=note + "由 R.I.O.S. 解算导出；编制要求取自名册，含真实专精与模组。")
            path = maa.write_job(data, D.guides_dir(), st.stage["code"])
        except Exception as exc:                          # noqa: BLE001
            self._say(f"[bad]导出失败：{type(exc).__name__}: {exc}[/]")
            return
        st.export_path = path
        self._say(f"[good]已导出[/] {path}\n"
                  f"  用了 {len(plan.deploys)} 名干员：{maa.operators_brief(plan, st.plan_roster)}")

    def _say(self, text: str) -> None:
        self.query_one("#msg", Static).update(text)

    def action_quit(self) -> None:
        """退出程序（`Q`）。结果屏的另一个出口是 `H` 回主界面。"""
        self.app.exit()

    def action_home(self) -> None:
        """回 [0] 准备屏，接着算下一关。

        算完一关还想算下一关是常态，为此退出重开一遍、再让程序重新读一次名册，
        没有道理。
        """
        self.app.goto_home()

    def action_stage_list(self) -> None:
        """回**选关页**（关卡列表），换个关卡接着算。

        与 `H` 的区别只在退到哪一层：`H` 把整轮清空、连"在哪一章哪一分部"都忘掉；
        `R` 退到关卡列表为止，章/活动、分部、环境的选择都留着——换一关只要再点
        一次关卡，不必从头点三层。
        """
        self.app.goto_stage_list()


# ================================================================ App

class RiosApp(App):
    CSS = theme.CSS
    TITLE = theme.APP_TITLE
    SUB_TITLE = theme.APP_SUBTITLE
    BINDINGS = both_cases([Binding("ctrl+c", "quit", "退出")])

    def __init__(self, *, skip_login: bool = False,
                 stage: str = "", squad: str = "") -> None:
        super().__init__()
        self.state = State()
        self.skip_login = skip_login
        self.preset_stage = stage
        self.preset_squad = [s for s in squad.replace("，", ",").split(",") if s.strip()]
        #: 向导的**路径**：从最初一屏到当前一屏。见 `push_step`。
        self._path: list[tuple] = []

    def on_mount(self) -> None:
        self.state.roster = D.load_roster()
        if self.preset_stage:
            # --stage 给了就跳过 [1]
            row = _resolve_stage(self.preset_stage)
            if row is None:
                self.state.error = f"认不出关卡「{self.preset_stage}」"
            else:
                self.state.stage = row
                if self.preset_squad:
                    # `--squad` 已经替用户决定了「要手动加人」，不必再问一遍
                    self.state.squad = self.preset_squad
                    self.push_screen(SquadPickScreen(), self._squad_picked)
                else:
                    self.push_screen(SquadAskScreen(), self._squad_asked)
                return
        if self.skip_login:
            # 测试全新启动的流程：不经过 [0]，直接进选关卡。
            self.goto_stage_pick()
        elif self._needs_login_wizard():
            # **初次干净启动先进登录向导**（博士 2026-09-17）。
            # 它不是路径上的一步：向导退出来直接落在 [0]，不构成"上一步"。
            self.push_screen(LoginScreen(), self._login_wizard_done)
        else:
            self.push_screen(WelcomeScreen())

    def _needs_login_wizard(self) -> bool:
        """是否该在启动时进登录向导：**配置里没记录过登录选择，且当前没有账号**。

        两个条件都要，缺一不可：
          * 只看"没有凭据"——凭据约 2 天过期，那会变成每次过期都拦一下；
          * 只看"配置没记录"——已经登着号的人每次启动都被拦一下。

        答过「以后都不登录」就写进 `~/.rios/tui.json`，从此不再问；
        答「本次不登录」什么都不写，下一次干净启动还会问——这正是"本次"的意思。
        """
        if D.load_config().get("login_prompt"):
            return False
        return not D.skland_uid()

    def _login_wizard_done(self, _result) -> None:
        """向导退出来了（登了、没登、或退出了账号），落到 [0]。

        名册**必须重读**：向导里可能刚落下一份新凭据（换成新账号），
        而 `state.roster` 是启动那一刻按旧账号读的。
        """
        self.state.roster = D.load_roster()
        self.push_screen(WelcomeScreen())

    # ---- 向导的推进 ----
    #
    # ## 为什么「路径」要自己记
    #
    # 各屏选完是 `dismiss(值)` 把**自己**弹掉的（弹出时触发回调，回调再推下一屏），
    # 所以屏幕栈里始终只有「当前屏」——**上一层早就不在了**。于是 `pop_screen`
    # 退不回上一层：实测在关卡层按 Esc 会一路掉回主界面。
    #
    # 博士 2026-09-17 要求「过程中按 esc 应当返回上一步」，所以来路必须自己存成
    # 一条**路径**：`push_step` 压一屏的同时把「怎么把它重建出来」追加到路径尾，
    # `step_back` 丢掉尾巴（自己）后把新的尾巴重新推出来。

    def push_step(self, make, callback=None) -> None:
        """推一屏，并把它记进路径。

        `make` 是**无参工厂**而不是现成实例：退回来时要的是一张新屏——旧的那张
        早被 `dismiss` 掉了，而 Textual 的 Screen 用过一次不能再压。
        """
        self._path.append((make, callback))
        self.push_screen(make(), callback)

    def step_back(self) -> None:
        """向导屏按 Esc：**退回上一层**。

        路径里最后一格是**自己**，所以先把自己丢掉，上一层才浮上来。
        早先写成「弹出自己那一格、再把它推回来」，结果是**按一次 Esc 什么都不变、
        要按两次才退一层**——因为弹掉的正是当前这一屏，推回来的还是它。
        已经在最初一步（路径里只剩自己）就回 [0]。
        """
        if self._path:
            self._path.pop()
        self.back_to_step()

    def back_to_step(self) -> None:
        """退回路径的最后一层。**不丢任何东西**。

        给不在路径上的屏用（解算屏不是 `push_step` 推的，所以路径顶格就是它的
        上一步）。博士 2026-09-17 裁定「结算中止退回上一步」走这里。
        """
        if not self._path:
            self.goto_home()
            return
        make, callback = self._path[-1]
        self.push_screen(make(), callback)

    def goto_stage_pick(self) -> None:
        if D.chapter_rows():
            self.push_step(ChapterPickScreen, self._chapter_picked)
            return
        if D.stage_rows(limit=1):
            # 有 stage 但归不出章（旧库没跑过带 zone 的 `db stage-fetch`）：
            # 退回平铺列表，总比甩一句「没有数据」强。
            self.push_step(
                lambda: StagePickScreen(heading="全部关卡（没有章节数据）"),
                self._stage_picked)
            return
        self.push_screen(NoStageScreen())

    # ---- [1] 的三层推进 ----

    def _chapter_picked(self, chapter: dict | None) -> None:
        if chapter is None:
            self.step_back()
            return
        if len(chapter["parts"]) > 1:
            self.push_step(lambda: PartPickScreen(chapter), self._part_picked)
            return
        self._enter_zone(chapter["parts"][0]["zone_id"], chapter["title"])

    def _part_picked(self, part: dict | None) -> None:
        if part is None:
            self.step_back()
            return
        # 分部的名字要带上活动名，否则「通学路」孤零零看不出是哪一章
        head = part["title"]
        self._enter_zone(part["zone_id"], head)

    def _enter_zone(self, zone_id: str, heading: str) -> None:
        """进关卡层之前先看这个 zone 有没有环境分层——有就先问。

        第 9-14 章有、其余章没有；判据是**数据库里真的存在几个 diff_group**，
        不是章号。硬编码「9 到 14」会在下次更新时过期。
        """
        envs = D.zone_envs(zone_id)
        if len(envs) > 1:
            self.push_step(
                lambda: EnvPickScreen(zone_id, heading, envs),
                lambda env: self._env_picked(zone_id, heading, env))
            return
        self.push_step(lambda: StagePickScreen(zone_id=zone_id, heading=heading),
                       self._stage_picked)

    def _env_picked(self, zone_id: str, heading: str, env: dict | None) -> None:
        if env is None:
            self.step_back()
            return
        label = env["label"]
        self.push_step(
            lambda: StagePickScreen(zone_id=zone_id, env=env["env"],
                                    heading=f"{heading} › {label}"),
            self._stage_picked)

    def goto_home(self) -> None:
        """回到向导的起点（[0] 准备屏），可以接着算下一关。

        向导是一层层 `push_screen` 压上来的，所以「回主界面」= 把压上去的屏
        **全部弹掉**，再放一张干净的 [0]。被弹掉的屏若带回调，会收到 `None`——
        本项目每个回调都在开头对 `None` 直接返回，所以这一趟是安全的。

        顺手清空上一轮的结果。不清的话下一轮会带着上一次的 stage/squad 从半路
        开始，而屏幕上却写着「准备」——那是假的。

        `state.roster` **留着**：它和这一轮算哪一关无关，重读一遍是白费。
        """
        while len(self.screen_stack) > 1:
            self.pop_screen()
        # 路径一并作废：下一轮是全新的向导，不该还能退回上一轮的屏
        self._path.clear()
        self._clear_round(keep_squad=False)
        self.push_screen(WelcomeScreen())

    def goto_stage_list(self) -> None:
        """回**选关页**（关卡列表），换个关卡接着算——博士 2026-09-18 要的。

        与 `goto_home` 只差退到哪一层：

        * `goto_home`：全部弹掉、路径清空，连"在哪一章哪一分部"都忘掉；
        * 这里：退到**关卡列表那一格**为止，章/活动、分部、环境的选择都留着。

        关卡列表那一格**按回调认**（`self._stage_picked`），不按工厂名：进关卡层
        有两条路，一条直接推 `StagePickScreen`，一条推的是包了一层的 `lambda`
        （环境层之后就是它），按名字认会漏掉后者。

        `state.squad` **留着**：换个关卡通常还是同一队，重勾一遍是白费。
        """
        idx = next((i for i, (_make, cb) in enumerate(self._path)
                    if cb == self._stage_picked), None)
        if idx is None:
            # 关卡层不在路径上（`--stage` 预设、或从别的入口半路进来的）：
            # 那就重新走一遍选关那三层。总比什么都不做强。
            while len(self.screen_stack) > 1:
                self.pop_screen()
            self._path.clear()
            self._clear_round(keep_squad=True)
            self.goto_stage_pick()
            return
        make, callback = self._path[idx]
        # 关卡列表之后那几格（[2a] 编队问答 / [2b] 选人）作废：编队已经交出去了
        del self._path[idx + 1:]
        while len(self.screen_stack) > 1:      # 解算屏、结果屏一并弹掉
            self.pop_screen()
        self._clear_round(keep_squad=True)
        self.push_screen(make(), callback)

    def _clear_round(self, *, keep_squad: bool) -> None:
        """清掉这一轮解算留下的东西。

        `state.roster` **不清**（与算哪一关无关）；`state.mode` 也不清——那是
        用户的偏好（"只用我选的" / "允许程序补充"），不该被一次返回重置。
        """
        st = self.state
        st.stage = None
        if not keep_squad:
            st.squad = []
        st.searcher = None
        st.plan_roster = None
        st.result = None
        st.error = ""
        st.export_path = None
        st.pool_note = ""
        st.depth = DEPTH_START
        st.deploy_limit = 0

    def _stage_picked(self, row: dict | None) -> None:
        if row is None:
            self.step_back()
            return
        self.state.stage = row
        if self.preset_squad and self.preset_stage:
            # `--squad` 已经替用户决定了「要手动加人」，不必再问一遍
            self.state.squad = self.preset_squad
            self.push_step(SquadPickScreen, self._squad_picked)
            return
        self.push_step(SquadAskScreen, self._squad_asked)

    def _squad_asked(self, answer: dict | None) -> None:
        """[2a] 的答复：要手动加人才进选人界面，否则空手进解算。"""
        if answer is None:
            self.step_back()
            return
        if answer["manual"]:
            self.push_step(SquadPickScreen, self._squad_picked)
            return
        self.state.squad = []
        self.state.mode = "auto"          # 不指定人 = 让搜索自己挑
        self.push_screen(SolveScreen())

    def _squad_picked(self, picked: list[str] | None) -> None:
        if picked is None:
            self.step_back()
            return
        self.state.squad = picked
        self.push_screen(SolveScreen())


class NoStageScreen(RiosScreen):
    """关卡表是空的。**给一句能照做的话，不是一句"没有数据"。**"""

    BINDINGS = both_cases([Binding("escape", "back", "返回", key_display="Esc"),
                           Binding("q", "quit", "退出程序", key_display="Q")])

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="block"):
            yield Label("关卡名获取失败", classes="block-title")
            yield Static(
                "本地库里的关卡表是空的，选不了关卡。\n\n"
                "取一次（要联网，约 7 MB / 十秒上下）：\n"
                "    python -m ak_tactic db stage-fetch\n\n"
                "[dim]取不到时它会明确报「关卡名获取失败」，并保留上一版表。[/]",
                id="nostage")
        yield Footer()

    def action_back(self) -> None:
        """返回 [0]。这一屏是「关卡表空」的提示，不该把人逼到只剩退出。"""
        self.app.goto_home()

    def action_quit(self) -> None:
        self.app.exit()


def run(*, skip_login: bool = False, stage: str = "",
        squad: str = "") -> int:
    """CLI 入口。`textual` 只在这里被用到，且是**惰性导入**的。"""
    RiosApp(skip_login=skip_login, stage=stage, squad=squad).run()
    return 0

