# -*- coding: utf-8 -*-
"""Go 界面 ↔ Python 侧的**一行协议桥**（登录／名册那两条必须走 Python 的路）。

形状照 `ak_tactic/simgo/client.py`（那条是 Python→Go 的引擎协议）：**一行一个 JSON
对象进、一行一个 JSON 对象出**；没有应答就带着 stderr 摘要报错。**不发明第二套 IPC。**

为什么要有它：博士 2026-09-26 裁定「登录／名册走 Python 子进程」（Go 侧不重写森空岛
那条链）。所以这座桥只做**翻译**——把 `ak_tactic.skland` 与 `ak_tactic.tui.data`
**已有的**函数按命令名暴露出去，**不重新实现任何一步**。尤其 `login_by_qr` 那条
「申请 → 轮询 → 换 hgToken → 换 cred」的流程**原样调用**：拆开重写就是第二份实现，
而两份实现迟早会漂。

命令（请求 `{"id":N,"cmd":"..."}`；应答 `{"id":N,"ok":true,...}` 或
`{"id":N,"ok":false,"error":"..."}`）：

    ping                      握手：协议号 ＋ 解释器版本 ＋ 当前账号 ＋ 凭据状态
    accounts                  本机登过的账号（含当前标记）＋ 游戏 uid
    fill_accounts             补全各账号的游戏用户名与游戏 uid（**联网**，按一次问一次）
    login_start [timeout=180] 起扫码登录（**后台线程**跑 login_by_qr），返回二维码矩阵
    login_poll                取扫码进度／结果（waiting / done / failed）
    activate {uid}            切到某个已登账号
    logout                    退出账号
    roster                    名册：来源（skland / operbox）、是否完整、干员练度列表

★ 二维码为什么给**矩阵**而不是画好的字符：编码（文本 → 模块）由 Python 的
  `ak_tactic.qrterm.matrix` 走 `qrcode` 库做，**画法**（静默区、半格、颜色）是界面的
  事、留在 Go 侧。早先这条给的是 43 行带 ANSI 的成品（单次约 90 KB），而登录屏每秒
  轮询一次；现在的 `qr_matrix` 是每行一串 `0`/`1`（约 3 KB），且**两端不会各有一套
  二维码编码器** —— 两份编码器迟早会漂，而二维码画错是"扫不出来"，最难查的那类症状。

★ 三条纪律：

  · **具名失败**：任何异常都变成 `ok:false` ＋ `error` 全文（带异常类名），
    绝不静默返回一个空列表 —— 空名册与「这个号没干员」长得一模一样。
  · **剥掉 rich 标记**：Python 那边给人看的字符串带 `[dim]…[/]` 这类标记，桥上统一
    剥掉（Go 侧不做富文本）。**登记为分歧**：文字内容相同、样式不同。
  · **不 import textual**：只碰 `ak_tactic.tui.data`（`ak_tactic/tui/__init__.py`
    写明包本身不导入 textual），所以没装 textual 的机器上登录这条也走得了。
"""
from __future__ import annotations

import json
import re
import sys
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROTO = 1

_MARKUP = re.compile(r"\[/\]|\[/?[a-zA-Z][^\[\]]*\]")


def _plain(s: str) -> str:
    """剥掉 rich 标记（`[dim]` / `[/]` / `[bold reverse]` …）。"""
    return _MARKUP.sub("", s or "")


# ---------------------------------------------------------------- 扫码会话


class LoginSession:
    """把 `login_by_qr` 放后台线程跑，把它的两个回调收成可轮询的状态。

    ⚠ 这里**没有**重写登录流程：线程体就是一次 `skland.login_by_qr(...)`。
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.phase = "idle"      # idle → waiting → done / failed
            self.url = ""
            self.qr_matrix: list[str] = []
            self.qr_note = ""
            self.status = None
            self.text = ""
            self.result: dict | None = None
            self.error = ""
            self.thread: threading.Thread | None = None
            self.qr_ready = threading.Event()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "phase": self.phase,
                "url": self.url,
                "qr_matrix": list(self.qr_matrix),
                "qr_note": self.qr_note,
                "status": self.status,
                "text": self.text,
                "error": self.error,
                "result": self.result,
            }

    def start(self, timeout: float) -> None:
        from ak_tactic import skland

        self.reset()

        def on_qr(_scan_id: str, content: str) -> None:
            matrix: list[str] = []
            note = ""
            try:
                #: 只要**矩阵**（border=0）：静默区与配色是界面的事，Go 侧自己挑。
                #: 用 `qrcode` 库（`qrterm.matrix`）而不是自己编码 —— 与 Python 界面
                #: 用的是同一个编码器。
                from ak_tactic.qrterm import matrix as qr_matrix
                matrix = ["".join("1" if c else "0" for c in row)
                          for row in qr_matrix(content, border=0)]
            except Exception as exc:                             # noqa: BLE001
                #: 编不出来就把**原因**带回去（`qr_note`），别给一张空图：
                #: 空矩阵与「码还没到」在界面上长得一样，而这两件事的处置完全不同。
                note = "%s: %s" % (exc.__class__.__name__, exc)
            with self.lock:
                self.url = content
                self.qr_matrix = matrix
                self.qr_note = note
                self.phase = "waiting"
            self.qr_ready.set()

        def on_status(status: int, text: str) -> None:
            with self.lock:
                self.status = status
                self.text = _plain(text)

        def body() -> None:
            try:
                result = skland.login_by_qr(timeout=timeout, on_qr=on_qr,
                                            on_status=on_status)
                with self.lock:
                    self.result = result
                    self.phase = "done"
            except Exception as exc:                             # noqa: BLE001
                with self.lock:
                    self.error = "%s: %s" % (exc.__class__.__name__, exc)
                    self.phase = "failed"
            finally:
                self.qr_ready.set()   # 失败也要放行，别让 start 白等

        self.thread = threading.Thread(target=body, daemon=True)
        self.thread.start()


SESSION = LoginSession()


# ---------------------------------------------------------------- 命令


def cmd_ping(req: dict) -> dict:
    import platform

    from ak_tactic import skland

    #: 凭据状态：`cred`（有效期内）／`hgtoken`（还没铸成 cred）／`none`。
    #: ★ 登录屏那句话就是照这三态说的（「已保存凭据：有效期内可直接 status 校验；
    #: 过期会由 hgToken 静默重铸」／「已保存 hgToken（尚未铸成 cred）」／「本机还没有
    #: 任何森空岛凭据」）—— 不给这一栏，界面只能干说一句"已登录"。
    try:
        st = skland.load_cred()
        if st.get("cred"):
            cred_state = "cred"
        elif st.get("hgToken"):
            cred_state = "hgtoken"
        else:
            cred_state = "none"
    except Exception:                                        # noqa: BLE001
        cred_state = "none"

    return {
        "proto": PROTO,
        "python": platform.python_version(),
        "impl": sys.implementation.name,
        "uid": skland.current_uid(),
        "cred_state": cred_state,
    }


def cmd_fill_accounts(req: dict) -> dict:
    """补全本机每个账号的**游戏用户名与游戏 uid**（**联网**，按一次问一次）。

    为什么非有这一条：账号列表要显示的是游戏用户名与游戏 uid，而这两个量**离线推不
    出来** —— 登录账号 id 是通行证账号（13 位），游戏 uid 是另一个号（8 位），账号 id
    不出现在任何一份森空岛数据里。唯一的来源是问一次再记住
    （`~/.skland/accounts.json`）。

    照 `LoginScreen.action_fill` 的口径，三条：
      · **已经知道的直接跳过**（不白打接口）；
      · **一个账号失败不影响别的账号**（逐个记结果、逐个报，不是整张列表一起沉掉）；
      · 补全可能刚把**游戏 uid** 定下来，而名册是按游戏 uid 存的文件 ⇒ 界面拿到应答
        后应当重读一次名册（这一条在界面侧做，桥上只如实回报）。
    """
    from ak_tactic import skland
    from ak_tactic.tui import data as D

    uids = [a.get("uid") or "" for a in skland.known_accounts()]
    uids = [u for u in uids if u]
    todo = [u for u in uids
            if not (D.account_info(u).get("nick") and D.account_info(u).get("game_uid"))]
    filled: list[str] = []
    lines: list[str] = []
    for uid in todo:
        info = D.account_info(uid)
        try:
            got = skland.resolve_game_uid_for(uid, uid=info.get("game_uid") or None)
        except Exception as exc:                             # noqa: BLE001
            lines.append("账号 %s 补全失败：%s: %s"
                         % (uid, exc.__class__.__name__, exc))
            continue
        filled.append(uid)
        lines.append("%s　游戏uid=%s　（登录账号 %s）"
                     % (_plain(str(got.get("nickName") or "（森空岛没给昵称）")),
                        got.get("gameUid"), uid))
    return {"total": len(uids), "todo": len(todo), "filled": len(filled),
            "skipped": len(uids) - len(todo), "lines": lines}


def cmd_accounts(req: dict) -> dict:
    from ak_tactic import skland
    from ak_tactic.tui import data as D

    cur = D.skland_uid()
    rows = []
    for a in skland.known_accounts():
        uid = a.get("uid") or ""
        #: ⚠ 游戏用户名与游戏 uid 要问 `D.account_info`（Python 的 `_refresh_accounts`
        #: 与 `describe_account` 都走它）—— `known_accounts()` 的行里**没有**这两个字段，
        #: 从那里取只会得到空串，而空串与「还没问过森空岛」是两回事。
        info = D.account_info(uid)
        rows.append({
            "uid": uid,
            "game_uid": info.get("game_uid") or "",
            "nick": info.get("nick") or "",
            "known": bool(info.get("known")),
            "current": bool(uid) and uid == cur,
            #: 照 Python 的排版（它自己带标记，这里剥成纯文本）
            "line": _plain(D.describe_account(uid, current=(uid == cur))),
        })
    return {"current": cur or "", "game_uid": D.skland_game_uid() or "",
            "accounts": rows}


def cmd_login_start(req: dict) -> dict:
    timeout = float(req.get("timeout") or 180.0)
    SESSION.start(timeout)
    #: 等二维码出来（或线程直接失败）再回 —— 界面拿到应答就能画码。
    SESSION.qr_ready.wait(timeout=10.0)
    snap = SESSION.snapshot()
    return {"phase": snap["phase"], "url": snap["url"],
            "qr_matrix": snap["qr_matrix"], "qr_size": len(snap["qr_matrix"]),
            "qr_note": snap["qr_note"], "text": snap["text"],
            "error": snap["error"]}


def cmd_login_poll(req: dict) -> dict:
    snap = SESSION.snapshot()
    #: ⚠ **不重发二维码**：登录屏每秒轮询一次，而矩阵虽然比原先的 ANSI 小得多，
    #: 也没有每秒搬一遍的必要。二维码只在 `login_start` 给一次。
    return {"phase": snap["phase"], "status": snap["status"], "text": snap["text"],
            "url": snap["url"], "error": snap["error"], "result": snap["result"]}


def cmd_activate(req: dict) -> dict:
    from ak_tactic import skland
    from ak_tactic.tui import data as D

    uid = str(req.get("uid") or "")
    if not uid:
        raise ValueError("activate 要带 uid")
    res = skland.activate(uid)
    return {"uid": uid, "game_uid": D.skland_game_uid() or "", "result": {
        k: v for k, v in (res or {}).items() if isinstance(v, (str, int, float, bool))
    }}


def cmd_logout(req: dict) -> dict:
    from ak_tactic import skland

    res = skland.logout()
    return {"result": bool(res)}


#: 一个进程里只试一次"直接去森空岛取名册"（界面会反复问；每问一次打一趟网是浪费）。
_ROSTER_FETCH_TRIED = False


def _try_fetch_roster_from_skland() -> tuple[object | None, str]:
    """名册缓存不在时**直接去森空岛取一份**（博士 2026-09-28 裁）。

    链路就是现成的那两条（**不重写**）：`skland.fetch_all()` 拉全量落 `opers_<uid>.json`，
    再用 `tools/roster.py` 的 `build()` ＋ `write_json()` 翻成 `roster_<uid>.json`
    —— 之后 `load_roster()` 自己就找得到（口径仍在它手里，桥上只负责"缺了就去取"）。

    返回 `(名册 or None, 说明)`：说明在成功时是"取到并落盘"，失败时是**具名原因**
    （要一起写进上层那句失败提示里 —— 玩家得知道是"没登录"还是"网/证书"）。
    """
    global _ROSTER_FETCH_TRIED
    if _ROSTER_FETCH_TRIED:
        return None, "（这一步本次已经试过，不重复打网）"
    _ROSTER_FETCH_TRIED = True
    try:
        from ak_tactic import skland
        from ak_tactic.tui import data as D

        uid = skland.current_uid()
        if not uid:
            return None, "本机没有森空岛登录凭据（~/.skland/cred.json）"
        #: ★ 要的是**游戏 uid**，不是登录账号 id —— 两者通常不相等（前者 13 位、
        #: 后者 8 位），而 `fetch_all()` 只认前者。实测（2026-09-28）：直接拿
        #: `current_uid()` 去取会报「uid 1352155938927 不在绑定列表里」。
        game_uid = ""
        try:
            game_uid = str(skland.game_uid() or "")
        except Exception:                                    # noqa: BLE001
            game_uid = ""
        if not game_uid:
            try:
                got = skland.resolve_game_uid_for(uid)
                game_uid = str(got.get("gameUid") or "")
            except Exception:                                # noqa: BLE001
                game_uid = ""
        res = skland.fetch_all(uid=game_uid or uid)
        real = str(res.get("uid") or uid)
        import roster as _roster          #: `tools/roster.py`（桥的 cwd 就在 tools/）
        data = _roster.build(real)
        path = _roster.write_json(data)
        got = D.load_roster()
        if got is None:
            return None, "从森空岛取回来了、但 load_roster() 仍认不出（%s）" % path
        return got, "已从森空岛取到并落盘：%s" % path
    except Exception as exc:                                 # noqa: BLE001
        return None, "%s: %s" % (exc.__class__.__name__, exc)


def cmd_roster(req: dict) -> dict:
    """名册：把 `ak_tactic.tui.data.load_roster()` 的产出翻成一行 JSON。

    ★ 桥上**只翻译，不重新实现**：名册有三个来源（森空岛缓存 → MAA 的 OperBox
    导出 → 都没有），该按哪个 uid 去找（**游戏 uid ≠ 登录账号 id**，两者通常不相等）
    全是 `load_roster()` 已经定好的口径。这里自己再走一遍那条链，就是第二份实现，
    两份迟早会漂。

    `load_roster()` 返回 `None` **不是**「这个号没干员」，而是「一份名册都找不到」。
    按桥的纪律必须**具名失败**：静默回一个空列表，界面就会显示成「这个号一个干员
    都没有」——那是最坏的一类错，看着正常、内容是假的。

    字段只给界面要用的那几个（`char_id` / `name` / `profession` / `sub_profession` /
    `elite` / `level`）；潜能、信赖、专精、模组等级这次没带（选人屏用不到，且
    OperBox 那条来源本来就没有）。

    ★ 2026-09-27 补 `sub_profession`：参照实现的选人屏有**子职业行**
    （`app.py:1838` 的 `PickerRow #sub-row`，只列出当前职业下真有的子职业），
    没有这个字段那排就只能是空的 —— 而 Go 侧此前连字段都没有。
    ⚠ 两条来源的完整度不同：skland 那份名册带 `subProfession`，MAA 的 OperBox
    导出未必有 ⇒ 拿不到时这里是空串，界面按参照的口径**整行隐藏**
    （`app.py:1878-1881`：取不到任何子职业名就 `display="none"`），
    而不是显示一排空白项。
    """
    from ak_tactic.tui import data as D

    r = D.load_roster()
    fetch_note = ""
    if r is None:
        #: ★ 2026-09-28 博士裁：名册**直接去森空岛取**，取不到才明确提示手动导入。
        r, fetch_note = _try_fetch_roster_from_skland()
    if r is None:
        raise LookupError(
            "RosterUnavailable: 名册取不到 —— 本机既没有当前账号的 "
            "data/skland/roster_<游戏uid>.json，也没有**解析得动**的 OperBox 导出；"
            "并且**已经试过直接去森空岛取**：%s。\n"
            "  手动导入（两条路任选）：\n"
            "    ① MAA 的 OperBox 导出放到 `tools/operbox_path.py` 指的位置；\n"
            "    ② `python tools/skland.py fetch`（拉全量）再 `python tools/roster.py`"
            "（翻成 roster_<uid>.json）。" % (fetch_note or "未试"))
    operators = [{"char_id": op.char_id, "name": op.name,
                  "profession": op.profession or "",
                  "sub_profession": getattr(op, "sub_profession", "") or "",
                  "elite": int(op.elite), "level": int(op.level)}
                 for op in r.operators]
    return {"source": r.source,
            "complete": bool(r.complete),
            "uid": r.uid,
            "nick": r.nick,
            "path": r.path,
            "note": _plain(r.note),
            "count": len(operators),
            "operators": operators}


def cmd_ensure_level(req: dict) -> dict:
    """**确保某一关的关卡 JSON 在本地**（不在就取一个）。

    博士 2026-09-27 裁：关卡数据**随用随取** —— 首次运行不再一次下 1765 个文件，
    改到玩家真正选定那一关时再取一个（约 60 KB）。界面在问引擎 `load` 之前调它。

    取不到就把原因抛出去（协议会把它包成具名错误），**不许**静默退化成"这关没地图"。
    """
    level = str(req.get("level") or "").strip()
    if not level:
        raise ValueError("ensure_level 少了 level（给 levelId，如 main_09-12）")
    from ak_tactic.gamedata.levels import ensure_level_file

    r = ensure_level_file(level)
    return {"level": r["level"], "data_path": r["data_path"],
            "cached": bool(r["cached"]), "bytes": int(r["bytes"])}


def cmd_check_updates(req: dict) -> dict:
    """检查「上游数据有没有更新」与「我们的数据包有没有新版」。

    博士 2026-09-27：「让用户打开本工具的时候程序自动请求数据文件」。
    这里只**报结论**，不动手 —— 动手的是 rebuild_data 那条既有流程
    （只加不删、缺件具名、每项任务一条进度条）与 `datapack --fetch-latest`。

    取不到不算"有新版"（`checked=False` 如实带出来）：把断网说成有更新，
    会让人白下几十 MB。
    """
    from ak_tactic.updates import check_updates

    return check_updates()


HANDLERS = {
    "ping": cmd_ping,
    "accounts": cmd_accounts,
    "fill_accounts": cmd_fill_accounts,
    "login_start": cmd_login_start,
    "login_poll": cmd_login_poll,
    "activate": cmd_activate,
    "logout": cmd_logout,
    "roster": cmd_roster,
    "ensure_level": cmd_ensure_level,
    "check_updates": cmd_check_updates,
}


def main() -> int:
    #: stdout 必须**只**有协议行：任何第三方库的 print 都会污染它。所以协议行走
    #: 一条自己打开的管道，而把 stdout 换成一个吞掉一切的对象。
    out = sys.stdout
    sys.stdout = open(__import__("os").devnull, "w", encoding="utf-8")
    #: ★ 协议行**一律 UTF-8**，不跟着控制台代码页走。
    #: 这条是 `roster` 逼出来的：`ensure_ascii=False` 的应答里带干员名，而中文
    #: Windows 的 stdout 默认是 GBK——名册里只要有一个 GBK 编不出的字符
    #: （实测：昵称里的 `²`，`UnicodeEncodeError: 'gbk' codec can't encode
    #: character '\xb2'`），整条应答就写不出去，回给 Go 的是**一个空管道**，
    #: 而空管道与「桥死了」长得一模一样。协议是字节流，编码得由协议自己定。
    try:
        out.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):     # 不是 TextIOWrapper（如被判据套了壳）
        pass

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        req = {}
        try:
            req = json.loads(raw)
            name = req.get("cmd") or ""
            fn = HANDLERS.get(name)
            if fn is None:
                raise ValueError("不认识的命令：%r（可用：%s）"
                                 % (name, "、".join(sorted(HANDLERS))))
            body = fn(req)
            resp = {"id": req.get("id"), "ok": True}
            resp.update(body)
        except Exception as exc:                                 # noqa: BLE001
            resp = {"id": (req or {}).get("id"), "ok": False,
                    "error": "%s: %s" % (exc.__class__.__name__, exc),
                    "trace": traceback.format_exc()[-600:]}
        out.write(json.dumps(resp, ensure_ascii=False, separators=(",", ":")) + "\n")
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
