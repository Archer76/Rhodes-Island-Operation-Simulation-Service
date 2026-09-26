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

    ping                      握手：协议号 ＋ 解释器版本 ＋ 当前账号
    accounts                  本机登过的账号（含当前标记）＋ 游戏 uid
    login_start [timeout=180] 起扫码登录（**后台线程**跑 login_by_qr），返回二维码
    login_poll                取扫码进度／结果（waiting / done / failed）
    activate {uid}            切到某个已登账号
    logout                    退出账号

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
            self.qr_lines: list[str] = []
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
                "qr_lines": list(self.qr_lines),
                "status": self.status,
                "text": self.text,
                "error": self.error,
                "result": self.result,
            }

    def start(self, timeout: float) -> None:
        from ak_tactic import skland

        self.reset()

        def on_qr(_scan_id: str, content: str) -> None:
            try:
                #: 用 skland 自己的终端渲染（`_render_terminal_qr`）—— 与 CLI 出的
                #: 二维码字形一致；换一套渲染就是"同一个码两种样子"。
                lines = skland._render_terminal_qr(content).splitlines()
            except Exception:                                    # noqa: BLE001
                lines = []
            with self.lock:
                self.url = content
                self.qr_lines = [_plain(x) for x in lines]
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

    return {
        "proto": PROTO,
        "python": platform.python_version(),
        "impl": sys.implementation.name,
        "uid": skland.current_uid(),
    }


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
            "qr_lines": snap["qr_lines"], "text": snap["text"],
            "error": snap["error"]}


def cmd_login_poll(req: dict) -> dict:
    snap = SESSION.snapshot()
    #: ⚠ **不重发二维码**：那 43 行带 ANSI，单次应答约 90 KB，而登录屏每秒轮询一次
    #: —— 重发等于每秒搬 90 KB 过管道。二维码只在 `login_start` 给一次。
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


HANDLERS = {
    "ping": cmd_ping,
    "accounts": cmd_accounts,
    "login_start": cmd_login_start,
    "login_poll": cmd_login_poll,
    "activate": cmd_activate,
    "logout": cmd_logout,
}


def main() -> int:
    #: stdout 必须**只**有协议行：任何第三方库的 print 都会污染它。所以协议行走
    #: 一条自己打开的管道，而把 stdout 换成一个吞掉一切的对象。
    out = sys.stdout
    sys.stdout = open(__import__("os").devnull, "w", encoding="utf-8")

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
