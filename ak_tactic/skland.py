# -*- coding: utf-8 -*-
"""森空岛（skland.com）取数：拿账号内干员的**专精等级与模组等级**。

为什么必须走这里
----------------
本地 MAA 导出的 `Arknights_OperBox_Export.json` 只有
`{id,name,elite,level,own,potential,rarity}` —— **没有专精，没有模组**。
而森空岛的 `data.chars` 两项都有（`skills[].specializeLevel` 与 `equip[].level`），
所以干员算符要用它当权威口径。

登录态
------
zonai.skland.com 的接口一律要 `cred`，无 cred 时统一返回
`{"code":10002,"message":"用户未登录"}`。cred 由鹰角通行证 token 换取：

    手机号 --(短信验证码)--> as.hypergryph token
    token --(oauth2/v2/grant, appCode 4ca99fa6b56cc2ba)--> code
    code  --(zonai /web/v1/user/auth/generate_cred_by_code, kind=1)--> cred + token

签名（每个 zonai 请求都要）
---------------------------
    sign = md5( HMAC_SHA256(key=token, msg=path + query_or_body + timestamp
                            + json.dumps(sign_headers, separators=(",",":"))) )

`sign_headers` 的键序固定为 platform / timestamp / dId / vName，
`sign` 与这三项一起作为请求头返回。**键序或分隔符错了签名就错。**

凭据只落盘在 `~/.skland/cred.json`（主目录下，`SKLAND_HOME` 可换），
不进仓库、不打印明文。

用法
----
    python tools/skland.py status                     # 校验 cred + 列出绑定账号
    python tools/skland.py qr                         # 扫码登录（终端里画二维码）
    python tools/skland.py send-code <手机号>          # 发短信验证码
    python tools/skland.py login <手机号> <验证码>      # 换取并保存 cred
    python tools/skland.py fetch [--uid U]            # 拉全量数据，落 data/skland/
    python tools/skland.py opers [--uid U]            # 只导出干员名册（含专精/模组）
    python tools/skland.py selftest                   # 不联网：校验签名拼装

三条补登录的路子，按持久性排
----------------------------
1. **扫码**（`qr`）——森空岛 APP 扫，最终换到的是**鹰角通行证 token（hgToken）**，
   与第 2 条同一个东西，过期能静默重铸。最省事，且**不必碰官网 Token**。
2. **官网 Token**——用户自己从 `account/info/hg` 取 `data.content` 粘进来，
   同样是 hgToken。但要提醒用户：那串东西的敏感度不亚于账号密码。
3. **手机号 + 验证码**（`send-code` + `login`）——验证码一次性，换到 hgToken 后
   也一样持久，但多一步短信。

扫码走的是**官方** `as.hypergryph.com` 的三个接口（gen_scan/login、scan_status、
token_by_scan_code），请求头照官方账号站 user.hypergryph.com 的样子设。
**这三步都不需要 dId**；dId 只到最后一跳 generate_cred_by_code 才用得上，
而那一步本项目用数美换真 dId 解决（见 `skland_did.py`），不吃占位值。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- 常量

APP_CODE = "4ca99fa6b56cc2ba"

AS_BASE = "https://as.hypergryph.com"
ZONAI_BASE = "https://zonai.skland.com"

URL_SEND_CODE = f"{AS_BASE}/general/v1/send_phone_code"
URL_TOKEN_BY_CODE = f"{AS_BASE}/user/auth/v2/token_by_phone_code"
URL_GRANT = f"{AS_BASE}/user/oauth2/v2/grant"
URL_CRED = f"{ZONAI_BASE}/web/v1/user/auth/generate_cred_by_code"
URL_CHECK = f"{ZONAI_BASE}/api/v1/user/check"
URL_BINDING = f"{ZONAI_BASE}/api/v1/game/player/binding"
URL_PLAYER_INFO = f"{ZONAI_BASE}/api/v1/game/player/info"

# ---- 扫码登录（官方 as.hypergryph.com 的三个接口，不经过 zonai）----
URL_QR_CREATE = f"{AS_BASE}/general/v1/gen_scan/login"
URL_QR_STATUS = f"{AS_BASE}/general/v1/scan_status"
URL_TOKEN_BY_SCAN = f"{AS_BASE}/user/auth/v1/token_by_scan_code"

#: 扫码这三步只带这三个头——照官方账号站 user.hypergryph.com 自己发请求的样子。
#: **这三步都不需要 dId**；dId 要到最后一跳 generate_cred_by_code 才用得上，
#: 而那一步本项目已经用数美换真 dId 解决了（见 skland_did.py）。
QR_HEADERS: dict[str, str] = {
    "Content-Type": "application/json",
    "Origin": "https://user.hypergryph.com",
    "Referer": "https://user.hypergryph.com/",
}

#: 二维码内容是 deep link，森空岛 APP 认这个 scheme。
DEEP_LINK_PREFIX = "hypergryph://scan_login?scanId="

#: 上游 status 的语义（100/101/102 要继续轮询，0 是完成）。
QR_STATUS_TEXT: dict[int, str] = {
    100: "等待扫码",
    101: "已扫码，请在手机上确认",
    102: "二维码已过期",
    0: "已确认",
}

#: 签名头，**键序不可改**（platform / timestamp / dId / vName）。
SIGN_HEADERS_BASE: dict[str, str] = {
    "platform": "1",
    "timestamp": "",
    "dId": "de9759a5afaa634f",
    "vName": "1.45.1",
}

REQUEST_HEADERS_BASE: dict[str, str] = {
    "User-Agent": ("Skland/1.45.1 (com.hypergryph.skland; build:104501004; "
                   "Android 34; ) Okhttp/4.11.0"),
    "Accept-Encoding": "gzip",
    "Connection": "close",
    "Origin": "https://www.skland.com",
    "Referer": "https://www.skland.com/",
    "Content-Type": "application/json; charset=UTF-8",
    "manufacturer": "Xiaomi",
    "os": "34",
    "vname": "1.45.1",
    "vcode": "104501004",
    "platform": "1",
    "nid": "1",
    "channel": "OF",
    "language": "zh_CN",
    "dId": SIGN_HEADERS_BASE["dId"],
}

#: dId 现在是**真的设备指纹**，服务端会校验。社区通用的占位值
#: `de9759a5afaa634f` 会被回 `10001 设备信息无效`（已实测）。
#: 真值由 tools/skland_did.py 向数美换取，缓存在 ~/.skland/did.txt。
_DID_CACHE: str | None = None


def current_did(*, fresh: bool = False) -> str:
    """取真实 dId；没有就现生成并缓存。"""
    global _DID_CACHE
    if _DID_CACHE and not fresh:
        return _DID_CACHE
    # 与 skland 同包，直接相对导入——不再靠 sys.path 插 tools/
    from ak_tactic import skland_did
    _DID_CACHE = skland_did.get_did(fresh=fresh)
    return _DID_CACHE


def request_headers() -> dict[str, str]:
    """带真实 dId 的通用请求头。"""
    h = dict(REQUEST_HEADERS_BASE)
    h["dId"] = current_did()
    return h

DEFAULT_HOME = Path(os.environ.get("SKLAND_HOME") or Path.home() / ".skland")
DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data" / "skland"


class SklandError(RuntimeError):
    """凭证、签名或接口层面出错。"""


# ---------------------------------------------------------------- 签名


def sign_string(path: str, body_or_query: str, timestamp: str,
                did: str | None = None) -> str:
    """待加密串：path + query/body + timestamp + 签名头 JSON。"""
    headers = dict(SIGN_HEADERS_BASE)
    headers["timestamp"] = timestamp
    if did is not None:
        headers["dId"] = did
    return path + body_or_query + timestamp + json.dumps(headers, separators=(",", ":"))


def generate_signature(token: str, path: str, body_or_query: str,
                       timestamp: str, did: str | None = None
                       ) -> tuple[str, dict[str, str]]:
    """返回 (sign, 签名头)。算法见模块 docstring。"""
    s = sign_string(path, body_or_query, timestamp, did)
    hex_s = hmac.new(token.encode("utf-8"), s.encode("utf-8"),
                     hashlib.sha256).hexdigest()
    sign = hashlib.md5(hex_s.encode("utf-8")).hexdigest()
    headers = dict(SIGN_HEADERS_BASE)
    headers["timestamp"] = timestamp
    if did is not None:
        headers["dId"] = did
    return sign, headers


def signed_headers(cred: str, token: str, url: str, method: str,
                   body: Any = None, timestamp: str | None = None) -> dict[str, str]:
    """拼出一次 zonai 请求的完整请求头。"""
    ts = timestamp or server_timestamp()
    did = current_did()
    parsed = urllib.parse.urlparse(url)
    if method.lower() == "get":
        payload = parsed.query
    else:
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    sign, sign_hdr = generate_signature(token, parsed.path, payload, ts, did)
    headers = request_headers()
    headers["cred"] = cred
    headers["sign"] = sign
    headers.update(sign_hdr)
    return headers


def server_timestamp() -> str:
    """用不带签名的 binding 请求取服务器时间，避开本机时钟偏差。"""
    try:
        req = urllib.request.Request(URL_BINDING, headers=request_headers())
        data = _read_json(req, timeout=15)
        ts = data.get("timestamp")
        if ts:
            return str(ts)
    except Exception:
        pass
    import time
    return str(int(time.time()))


# ---------------------------------------------------------------- HTTP


def _read_json(req: urllib.request.Request, *, timeout: float = 30.0) -> Any:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        if e.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            raise SklandError(f"HTTP {e.code}：{raw[:300]!r}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SklandError(f"连不上：{e}") from None
    return json.loads(raw.decode("utf-8"))


def _post_json(url: str, payload: Any, headers: dict[str, str],
               *, timeout: float = 30.0) -> Any:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    return _read_json(req, timeout=timeout)


def _get_json(url: str, headers: dict[str, str], *, timeout: float = 60.0) -> Any:
    req = urllib.request.Request(url, headers=headers, method="GET")
    return _read_json(req, timeout=timeout)


# ---------------------------------------------------------------- 登录


def send_phone_code(phone: str) -> dict[str, Any]:
    """给手机号发短信验证码（type=2 即森空岛登录用）。"""
    return _post_json(URL_SEND_CODE, {"phone": phone, "type": 2},
                      request_headers())


def obtain_hg_token(phone: str, code: str) -> str:
    """手机号 + 验证码 → 鹰角通行证 token。**验证码只在这一步用掉。**"""
    r = _post_json(URL_TOKEN_BY_CODE, {"phone": phone, "code": code},
                   request_headers())
    if r.get("status") != 0:
        raise SklandError(f"验证码换取 token 失败：{r}")
    return r["data"]["token"]


def create_qr_login() -> tuple[str, str]:
    """申请扫码二维码。返回 `(scanId, 二维码内容)`。

    内容是 deep link（`hypergryph://scan_login?scanId=…`）；上游偶尔也回一个
    `scanUrl`，有就用它，没有就自己按 scheme 拼——两条路等价。
    """
    r = _post_json(URL_QR_CREATE, {"appCode": APP_CODE}, dict(QR_HEADERS))
    if r.get("status") != 0 or not r.get("data"):
        raise SklandError(f"申请二维码失败：{r}")
    d = r["data"]
    scan_id = d["scanId"]
    return scan_id, (d.get("scanUrl") or DEEP_LINK_PREFIX + scan_id)


def qr_status(scan_id: str) -> dict[str, Any]:
    """查一次扫码状态。`status == 0` 时 `data.scanCode` 才可用。"""
    url = f"{URL_QR_STATUS}?scanId={urllib.parse.quote(scan_id)}"
    return _get_json(url, dict(QR_HEADERS))


def token_by_scan_code(scan_code: str) -> str:
    """一次性 scanCode → 鹰角通行证 token（hgToken）。

    **这个 token 与官网 `account/info/hg` 给的是同一类东西**，拿到它就等于
    拿到了「过期能静默重铸」的那一份，所以调用方必须立刻落盘。
    """
    r = _post_json(URL_TOKEN_BY_SCAN, {"scanCode": scan_code}, dict(QR_HEADERS))
    if r.get("status") != 0 or not r.get("data"):
        raise SklandError(f"scanCode 换 hgToken 失败：{r}")
    return r["data"]["token"]


def login_by_qr(*, home: Path | None = None, interval: float = 2.0,
                timeout: float = 180.0,
                on_qr: Any = None, on_status: Any = None) -> dict[str, Any]:
    """扫码登录的完整流程（申请 → 轮询 → 换 hgToken → 换 cred）。

    两个回调都可不给（给 CLI 与 TUI 各自接管展示）：
    - `on_qr(scan_id, content)`：二维码申请到时调一次；
    - `on_status(status, text)`：每次轮询后调一次。

    **拿到 hgToken 立刻落盘**——与手机号那条同一纪律：scanCode 是一次性的。
    2 秒一次、默认 180 秒超时；上游 102 就是过期，直接抛，让调用方重新申请。
    """
    import time

    scan_id, content = create_qr_login()
    if on_qr is not None:
        on_qr(scan_id, content)

    deadline = time.monotonic() + timeout
    while True:
        r = qr_status(scan_id)
        status = r.get("status", -1)
        if on_status is not None:
            on_status(status, QR_STATUS_TEXT.get(status, r.get("msg") or "?"))
        if status == 0:
            data = r.get("data") or {}
            scan_code = data.get("scanCode")
            if not scan_code:
                raise SklandError(f"上游说已确认但没给 scanCode：{r}")
            break
        if status == 102:
            raise SklandError("二维码已过期，请重新申请。")
        if time.monotonic() >= deadline:
            raise SklandError(f"等待扫码超时（{timeout:.0f} 秒）——重新申请一个二维码。")
        time.sleep(interval)

    hg_token = token_by_scan_code(scan_code)
    save_cred({"hgToken": hg_token, "cred": None, "token": None,
               "userId": None, "stage": "hg_token"}, home)
    return finish_login(home)


def hg_token_to_cred(hg_token: str) -> dict[str, Any]:
    """鹰角通行证 token → (grant code) → cred。返回 {cred, token, userId}。"""
    g = _post_json(URL_GRANT,
                   {"appCode": APP_CODE, "token": hg_token, "type": 0},
                   request_headers())
    if g.get("status") != 0:
        raise SklandError(f"换授权码失败：{g}")
    grant_code = g["data"]["code"]

    c = _post_json(URL_CRED, {"code": grant_code, "kind": 1},
                   request_headers())
    if c.get("code") != 0:
        raise SklandError(f"换 cred 失败：{c}")
    return c["data"]


def login_by_phone_code(phone: str, code: str,
                        home: Path | None = None) -> dict[str, Any]:
    """完整登录。**拿到 hgToken 就先落盘**，这样后面任何一步失败都不必再要验证码。"""
    hg_token = obtain_hg_token(phone, code)
    save_cred({"hgToken": hg_token, "cred": None, "token": None,
               "userId": None, "stage": "hg_token"}, home)
    return finish_login(home)


def finish_login(home: Path | None = None) -> dict[str, Any]:
    """用已保存的 hgToken 走完 grant + cred。可反复重试，不再消耗验证码。

    **先读在途票据**：刚拿到 hgToken 时 `userId` 还不知道，它只能落在
    `pending.json`；这时若本机已经登着别的账号，`load_cred()` 读到的是**那一个**
    的凭据，于是这次登录会拿旧账号的 hgToken 去换 cred——静默换错号，不报错。
    """
    st = load_pending(home) or load_cred(home)
    hg_token = st.get("hgToken")
    if not hg_token:
        raise SklandError("没有缓存的 hgToken，需要重新 `login <手机号> <验证码>`。")
    d = hg_token_to_cred(hg_token)
    save_cred({"hgToken": hg_token, "cred": d["cred"], "token": d["token"],
               "userId": d.get("userId"), "stage": "ready"}, home)
    return d


def check_cred(cred: str, token: str) -> dict[str, Any]:
    return _get_json(URL_CHECK, signed_headers(cred, token, URL_CHECK, "get"))


def binding_list(cred: str, token: str) -> list[dict[str, Any]]:
    data = _get_json(URL_BINDING, signed_headers(cred, token, URL_BINDING, "get"))
    if data.get("code") != 0:
        raise SklandError(f"取绑定列表失败（sign 若错也会报同码）：{data}")
    for app in data["data"]["list"]:
        if app.get("appCode") == "arknights":
            return app["bindingList"]
    raise SklandError("该账号未绑定明日方舟")


def player_info(cred: str, token: str, uid: str) -> dict[str, Any]:
    url = f"{URL_PLAYER_INFO}?uid={urllib.parse.quote(str(uid))}"
    data = _get_json(url, signed_headers(cred, token, url, "get"), timeout=120.0)
    if data.get("code") != 0:
        raise SklandError(f"取玩家数据失败（sign 若错也会报同码）：{data}")
    return data["data"]


# ---------------------------------------------------------------- 凭据落盘


# ---- 凭据按账号分开存 ----------------------------------------------------
#
# 旧版把所有凭据写在单个 `cred.json` 里，换一个账号就把它覆盖掉。现在一个
# 账号一份 `cred_<uid>.json`，另用 `current` 记住"当前用哪一份"。于是：
#
#   * 退出账号只把 `current` 清空，**一个文件都不删**——登过的号都还在，
#     可以直接切回来，不必重新扫码（博士 2026-09-17 裁定）。
#   * 名册缓存早就按 uid 分文件了（`roster_<uid>.json`）。两边口径现在一致，
#     "拿当前账号去取那一份"这件事才有意义。
#
# `current` 有三种状态，别只看"文件在不在"：
#   * 存在且非空 -> 那个 uid
#   * 存在且为空 -> **已退出账号**（文件都保留着，只是当前没有账号）
#   * 不存在     -> 旧版单文件时代；有 `cred.json` 就认它（老用户不丢登录态）

#: 旧版单文件凭据的文件名。**保留**：老用户的登录态在这里，读得到就别动它。
LEGACY_CRED = "cred.json"

#: 当前账号指向。内容是 uid，空文件表示"已退出账号"。
CURRENT_FILE = "current"

#: 登录在途的票据。拿到 hgToken 时 `userId` 还不知道，只能先放这儿；
#: `finish_login()` 换到 cred 后写进 `cred_<uid>.json` 并把它清掉。
#: 名字**故意不带 `cred_` 前缀**，免得被 `known_accounts()` 当成一个账号扫出来。
PENDING_CRED = "pending.json"


def cred_dir(home: Path | None = None) -> Path:
    return home or DEFAULT_HOME


def _legacy_path(home: Path | None = None) -> Path:
    return cred_dir(home) / LEGACY_CRED


def _pending_path(home: Path | None = None) -> Path:
    return cred_dir(home) / PENDING_CRED


def _current_file(home: Path | None = None) -> Path:
    return cred_dir(home) / CURRENT_FILE


def cred_path_for(uid: str, home: Path | None = None) -> Path:
    """某个账号的凭据文件。"""
    return cred_dir(home) / f"cred_{uid}.json"


def read_json(path: Path) -> dict[str, Any] | None:
    """读一个 JSON 文件；读不动（不存在/坏掉）返回 None，不抛。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def current_uid(home: Path | None = None) -> str | None:
    """当前账号的 uid。**没有登录态返回 None**（没登过、或已退出账号）。"""
    cf = _current_file(home)
    if cf.exists():
        try:
            raw = cf.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return raw or None
    legacy = read_json(_legacy_path(home))
    if legacy:
        return str(legacy.get("userId") or "").strip() or None
    return None


def set_current_uid(uid: str, home: Path | None = None) -> Path:
    """写当前账号指向。`uid` 传空串即"已退出账号"。"""
    cf = _current_file(home)
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(uid or "", encoding="utf-8")
    return cf


def cred_path(home: Path | None = None) -> Path:
    """**当前账号**的凭据文件路径（`status` / `cred` 两个子命令打印的就是它）。

    当前没有账号时退回旧单文件路径——只为让打印出来的路径不至于是个幻觉，
    不代表那里真有东西。
    """
    uid = current_uid(home)
    if uid:
        p = cred_path_for(uid, home)
        if p.exists():
            return p
        if _legacy_path(home).exists():
            return _legacy_path(home)
    return _legacy_path(home)


def load_pending(home: Path | None = None) -> dict[str, Any] | None:
    return read_json(_pending_path(home))


def save_cred(payload: dict[str, Any], home: Path | None = None) -> Path:
    """写凭据。**有 uid 就按 uid 分文件并把当前账号指过去**。

    `userId` 还是 `None` 的那种（刚拿到 hgToken、还没换 cred）落到在途票据里，
    不动当前账号指向——这时它还不属于任何一个账号。
    """
    uid = str(payload.get("userId") or "").strip()
    if not uid:
        p = _pending_path(home)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        return p

    p = cred_path_for(uid, home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    set_current_uid(uid, home)
    # 票据已经兑现，清掉——留着它下次 `finish_login()` 会拿一个过期的 hgToken 重试。
    # 清的是**在途票据**（转瞬即逝的中间态），不是账号数据：账号与名册一个都不删。
    try:
        _pending_path(home).unlink()
    except OSError:
        pass
    return p


def load_cred(home: Path | None = None) -> dict[str, Any]:
    """读**当前账号**的凭据。

    找不到时报出来的话要说清是哪一种"找不到"——"没登录过"与"登录过但这个
    账号的凭据文件没了"是两回事，混成一句会让人查错方向。
    """
    uid = current_uid(home)
    for p in ([cred_path_for(uid, home)] if uid else []) + [_legacy_path(home)]:
        if p.exists():
            data = read_json(p)
            if data is None:
                raise SklandError(f"凭据文件读不动（不是合法 JSON）：{p}")
            return data
    if uid:
        raise SklandError(f"当前账号 {uid} 的凭据文件不见了，请重新扫码登录。")
    raise SklandError("当前没有登录的账号。跑 `login` 或 `qr` 登录，"
                      "或在 TUI 的 [0] 屏按 L 扫码。")


def known_accounts(home: Path | None = None) -> list[dict[str, Any]]:
    """本机登录过的账号，**当前账号排第一**，其余按最近使用排。

    退出账号不删文件，所以这里通常不止一个——这正是"切回旧号不必重扫"的根据。
    """
    d = cred_dir(home)
    if not d.exists():
        return []
    files = sorted(d.glob("cred_*.json"))
    legacy = _legacy_path(home)
    if legacy.exists():
        files.append(legacy)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for f in files:
        st = read_json(f)
        if not st:
            continue
        uid = str(st.get("userId") or "").strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        try:
            mtime = f.stat().st_mtime
        except OSError:
            mtime = 0.0
        out.append({"uid": uid, "path": str(f), "stage": st.get("stage") or "",
                    "mtime": mtime, "has_cred": bool(st.get("cred"))})
    cur = current_uid(home)
    out.sort(key=lambda a: (a["uid"] != cur, -a["mtime"]))
    return out


def logout(home: Path | None = None) -> dict[str, Any]:
    """退出当前账号。**一个文件都不删**，只把当前账号指向清空。"""
    uid = current_uid(home)
    set_current_uid("", home)
    return {"uid": uid}


# ------------------------------------------------- 登录账号 uid → 游戏 uid
#
# **这是两个量，别混。**
#
# `cred.json` / `cred_<uid>.json` 里的 `userId` 是**通行证账号 id**；森空岛数据
# 里的 `uid`（`opers_*.json` 顶层那个）是**游戏 uid**。名册按后者存。
#
# 实测（一条真凭据）：通行证账号 id 是 13 位、游戏 uid 是 8 位，**两者不相等**，
# 而且**账号 id 不出现在任何一份森空岛数据里**——player_info / opers / roster
# 三份全查过，一个字符都没有。所以这个映射**离线推不出来**，只能问森空岛
# 要一次，然后记住（博士 2026-09-17 的裁定：识别要用森空岛给的 uid）。
#
# 记住的地方是 `accounts.json`，键 = 通行证账号 id。放这个文件而不是塞回凭据里，
# 是因为凭据在老机器上还是单文件 `cred.json`（那是只读的老格式，不该回写）。

ACCOUNTS = "accounts.json"


def _accounts_path(home: Path | None = None) -> Path:
    return cred_dir(home) / ACCOUNTS


def accounts_map(home: Path | None = None) -> dict[str, Any]:
    """通行证账号 id → {gameUid, nickName, channelName}。读不动就当空的。"""
    d = read_json(_accounts_path(home))
    return d if isinstance(d, dict) else {}


def set_game_uid(login_uid: str, game_uid: str, *, nick: str | None = None,
                 channel: str | None = None,
                 home: Path | None = None) -> dict[str, Any]:
    """记下"这个通行证账号对应哪个游戏 uid"。

    只在**真的问过森空岛**之后调用——它是学到了一个事实，不是猜一个。
    """
    if not login_uid or not game_uid:
        raise SklandError("记账号映射要同时有通行证账号 id 与游戏 uid。")
    d = accounts_map(home)
    d[str(login_uid)] = {"gameUid": str(game_uid), "nickName": nick or "",
                         "channelName": channel or ""}
    p = _accounts_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return d[str(login_uid)]


def game_uid(home: Path | None = None) -> str | None:
    """当前账号的游戏 uid；还没问过森空岛就是 None。**离线**。"""
    u = current_uid(home)
    if not u:
        return None
    rec = accounts_map(home).get(str(u)) or {}
    g = str(rec.get("gameUid") or "").strip()
    return g or None


def pick_binding(blist: list[dict[str, Any]],
                 uid: str | None = None) -> dict[str, Any]:
    """从绑定列表里挑一个角色：给了 uid 就精确找，否则默认角色优先。"""
    if not blist:
        raise SklandError("没有绑定任何明日方舟角色")
    if uid:
        for b in blist:
            if str(b.get("uid")) == str(uid):
                return b
        raise SklandError(f"uid {uid} 不在绑定列表里：{blist}")
    for b in blist:
        if b.get("isDefault"):
            return b
    return blist[0]


def resolve_game_uid(*, home: Path | None = None, uid: str | None = None,
                     save: bool = True) -> dict[str, Any]:
    """**联网**问森空岛：当前凭据对应哪个游戏 uid。问完就记住。

    只走 `binding_list`——它是这条链上最轻的一步，不必拉全量玩家数据。

    ## 凭据过期时先补一次再问

    `cred` 是有寿命的（约两天），过期之后 `binding_list` 回的是泛泛的
    `code 10000 请求异常`——**与签名写错同码**，看字面完全看不出是过期。
    实测踩到过：本机凭据还是"今天 22:39"的，照样 10000，`cred` 补完才好。
    所以这里遇到失败就补一次 `cred`（走已缓存的 hgToken，不消耗验证码）
    再重问一次；补完仍失败才把错抛出去。

    hgToken 也过期时要重新扫码，那不是这一步能修的，诚实报错。
    """
    st = load_cred(home)
    cred, token = require_ready(st)
    try:
        target = pick_binding(binding_list(cred, token), uid)
    except SklandError as first:
        try:
            fresh = finish_login(home)
        except Exception:                                 # noqa: BLE001
            raise first from None
        cred2, token2 = require_ready(fresh)
        try:
            target = pick_binding(binding_list(cred2, token2), uid)
        except SklandError:
            raise first from None

    g = str(target.get("uid") or "").strip()
    if not g:
        raise SklandError(f"绑定列表里这条没有 uid：{target}")
    login_uid = str(st.get("userId") or current_uid(home) or "").strip()
    if save and login_uid:
        set_game_uid(login_uid, g, nick=target.get("nickName"),
                     channel=target.get("channelName"), home=home)
    return {"loginUid": login_uid, "gameUid": g,
            "nickName": target.get("nickName"),
            "channelName": target.get("channelName")}


def resolve_game_uid_for(login_uid: str, *, home: Path | None = None,
                         uid: str | None = None,
                         save: bool = True) -> dict[str, Any]:
    """**联网**给**指定的已登录账号**问一次绑定列表——它不必是当前账号。

    与 `resolve_game_uid` 的分工：那个只认**当前账号**（`load_cred()` 读的就是
    当前账号那一份）。而 TUI 的账号列表要一次给**每个登过的号**补上
    「游戏用户名 + 游戏uid」，切号又只动一个当前指向——所以这里按 uid 直接读
    那一份 `cred_<uid>.json`。

    ## 为什么不给非当前账号"补一次 cred"

    `finish_login()` 走的是**当前账号**的 hgToken 文件与在途票据（`pending.json`）。
    拿它去救另一个号，最坏的情况是**静默换错号**（`finish_login` 的文档里记的
    就是这个坑）。所以补 cred 只对当前账号做，别的账号失败就如实报错。

    失败时抛 `SklandError`，调用方要能逐账号分开报——一个号失败不该让整张
    列表都画不出来。
    """
    login_uid = str(login_uid or "").strip()
    if not login_uid:
        raise SklandError("补全账号信息要知道是哪个登录账号。")
    st = read_json(cred_path_for(login_uid, home))
    if not st:
        raise SklandError(f"账号 {login_uid} 的凭据文件不见了，补不了信息。")
    cred, token = require_ready(st)

    def _ask(c: str, t: str) -> dict[str, Any]:
        return pick_binding(binding_list(c, t), uid)

    try:
        target = _ask(cred, token)
    except SklandError as first:
        if current_uid(home) != login_uid:
            raise
        try:
            fresh = finish_login(home)
        except Exception:                                     # noqa: BLE001
            raise first from None
        cred2, token2 = require_ready(fresh)
        try:
            target = _ask(cred2, token2)
        except SklandError:
            raise first from None

    g = str(target.get("uid") or "").strip()
    if not g:
        raise SklandError(f"绑定列表里这条没有 uid：{target}")
    if save:
        set_game_uid(login_uid, g, nick=target.get("nickName"),
                     channel=target.get("channelName"), home=home)
    return {"loginUid": login_uid, "gameUid": g,
            "nickName": target.get("nickName"),
            "channelName": target.get("channelName")}


def activate(uid: str, home: Path | None = None) -> dict[str, Any]:
    """切回某个登录过的账号（不必重扫）。"""
    uid = str(uid or "").strip()
    if not uid:
        raise SklandError("没给 uid，不知道要切到哪个账号。")
    if not cred_path_for(uid, home).exists():
        legacy = read_json(_legacy_path(home))
        if not legacy or str(legacy.get("userId") or "").strip() != uid:
            raise SklandError(f"本机没有账号 {uid} 的凭据文件，先扫码登录。")
    set_current_uid(uid, home)
    return {"uid": uid}


def require_ready(st: dict[str, Any]) -> tuple[str, str]:
    """从凭据里取出可用的 (cred, token)。"""
    cred, token = st.get("cred"), st.get("token")
    if not cred or not token:
        raise SklandError(
            "凭据还没换完（只有 hgToken，没有 cred）。"
            "跑 `cred` 补完即可，不用重新收验证码。")
    return cred, token


def mask(s: str, keep: int = 4) -> str:
    if not s:
        return "<空>"
    return s[:keep] + "*" * max(0, len(s) - keep * 2) + s[-keep:]


# ---------------------------------------------------------------- 干员名册

#: 森空岛 chars[].skills[] 里可能的专精字段名（不同版本见过两种写法）
_SPEC_KEYS = ("specializeLevel", "specialize_level", "mastery", "specLevel")


def _pick(d: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def normalize_opers(chars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 data.chars 压成算符要用的口径：elite / level / potential / 专精 / 模组。"""
    out: list[dict[str, Any]] = []
    for c in chars or []:
        skills = []
        for s in _pick(c, "skills", default=[]) or []:
            skills.append({
                # 实测字段名就是 id（不是 skillId）
                "skillId": _pick(s, "id", "skillId", "skill_id"),
                "specializeLevel": _pick(s, *_SPEC_KEYS, default=0),
            })
        equips = []
        for e in _pick(c, "equip", "equips", default=[]) or []:
            equips.append({
                "id": _pick(e, "id", "equipId"),
                "level": _pick(e, "level", default=0),
                "locked": bool(_pick(e, "locked", default=False)),
            })
        out.append({
            "charId": _pick(c, "charId", "char_id", "id"),
            "elite": _pick(c, "evolvePhase", "elite"),
            "level": _pick(c, "level"),
            # 游戏里 potentialRank 是 0 起算，显示潜能 = rank + 1
            "potentialRank": _pick(c, "potentialRank"),
            "potential": (_pick(c, "potentialRank") or 0) + 1,
            "mainSkillLvl": _pick(c, "mainSkillLvl"),
            "favorPercent": _pick(c, "favorPercent"),
            "defaultSkillId": _pick(c, "defaultSkillId"),
            "defaultEquipId": _pick(c, "defaultEquipId"),
            "skills": skills,
            "equips": equips,
        })
    return out


def fetch_all(*, uid: str | None = None, home: Path | None = None,
              out_dir: Path | None = None) -> dict[str, Any]:
    """拉全量玩家数据并落盘，返回 {uid, raw_path, opers_path, opers}。

    顺带把"通行证账号 ↔ 游戏 uid"这个映射记下来：**只有这里能学到它**，
    而名册是按游戏 uid 存的（见上面那一段）。
    """
    st = load_cred(home)
    cred, token = require_ready(st)

    blist = binding_list(cred, token)
    target = pick_binding(blist, uid)

    real_uid = str(target["uid"])
    login_uid = str(st.get("userId") or current_uid(home) or "").strip()
    if login_uid:
        set_game_uid(login_uid, real_uid, nick=target.get("nickName"),
                     channel=target.get("channelName"), home=home)
    info = player_info(cred, token, real_uid)

    d = out_dir or DEFAULT_DATA
    d.mkdir(parents=True, exist_ok=True)
    raw_path = d / f"player_info_{real_uid}.json"
    raw_path.write_text(json.dumps(info, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    chars = (info.get("chars") or [])
    opers = normalize_opers(chars)
    # charInfoMap 是**比 character_table 更好的名字源**：它覆盖升变形态
    # （char_1001_amiya2 这类在 character_table 里查不到），还自带中文子职业。
    char_info = {}
    for cid, v in (info.get("charInfoMap") or {}).items():
        char_info[cid] = {k: v[k] for k in
                          ("name", "appellation", "rarity", "profession",
                           "subProfessionId", "subProfessionName",
                           "displayNumber") if k in v}
    opers_path = d / f"opers_{real_uid}.json"
    opers_path.write_text(json.dumps(
        {"uid": real_uid, "nickName": target.get("nickName"),
         "channelName": target.get("channelName"), "count": len(opers),
         "charInfo": char_info, "opers": opers},
        ensure_ascii=False, indent=2), encoding="utf-8")

    return {"uid": real_uid, "nickName": target.get("nickName"),
            "raw_path": raw_path, "opers_path": opers_path, "opers": opers}


# ---------------------------------------------------------------- 自检


def _selftest() -> int:
    """不联网：校验签名拼装与掩码。"""
    ok = 0
    fail = 0

    def chk(name: str, cond: bool, extra: str = "") -> None:
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  [ok] {name}")
        else:
            fail += 1
            print(f"  [XX] {name} {extra}")

    print("[1] 签名头键序与序列化")
    hdr = dict(SIGN_HEADERS_BASE)
    hdr["timestamp"] = "1700000000"
    js = json.dumps(hdr, separators=(",", ":"))
    chk("键序 platform/timestamp/dId/vName",
        list(hdr.keys()) == ["platform", "timestamp", "dId", "vName"], str(list(hdr.keys())))
    chk("无空格序列化",
        js == '{"platform":"1","timestamp":"1700000000",'
              '"dId":"de9759a5afaa634f","vName":"1.45.1"}', js)

    print("[2] 待加密串 = path + query/body + ts + 头JSON")
    s = sign_string("/api/v1/game/player/info", "uid=123", "1700000000")
    chk("GET 用 query", s.startswith("/api/v1/game/player/infouid=1231700000000{"), s[:60])
    chk("以头 JSON 结尾", s.endswith(js), s[-40:])
    s2 = sign_string("/x", json.dumps({"a": 1}, separators=(",", ":")), "1")
    chk("POST 用紧凑 body", s2 == '/x{"a":1}1' + json.dumps(
        {**SIGN_HEADERS_BASE, "timestamp": "1"}, separators=(",", ":")), s2)

    print("[3] HMAC-SHA256 → hex → MD5")
    import hashlib as _h
    import hmac as _hm
    tok = "TOKEN"
    msg = sign_string("/p", "q", "1")
    expect = _h.md5(_hm.new(tok.encode(), msg.encode(), _h.sha256).hexdigest()
                    .encode()).hexdigest()
    got, _ = generate_signature(tok, "/p", "q", "1")
    chk("与手工两步计算一致", got == expect, f"{got} != {expect}")
    chk("sign 是 32 位小写十六进制",
        len(got) == 32 and got == got.lower() and all(c in "0123456789abcdef" for c in got))

    print("[4] 凭据掩码不泄明文")
    m = mask("abcdefghijklmnop")
    chk("首尾保留、中段打码", m == "abcd********mnop", m)
    chk("空值安全", mask("") == "<空>")

    print("[5] 干员名册归一")
    # **夹具里的 potentialRank 是 5 不是 6**：上游 `potentialRank` 0 起算，
    # 显示潜能 = rank + 1，而潜能只到 6（即 rank 最大 5）。这里原先写 6，
    # 归一出来是「潜能 7」——一个不存在的值，那条断言于是长期为红。
    # 修的是夹具而不是断言：`normalize_opers` 的 rank + 1 是项目已定案的口径。
    demo = [{
        "charId": "char_002_amiya", "evolvePhase": 2, "level": 80,
        "potentialRank": 5, "mainSkillLvl": 7,
        "skills": [{"skillId": "sk_1", "level": 7, "specializeLevel": 3}],
        "equip": [{"id": "uniequip_002_amiya", "level": 3, "locked": False}],
    }]
    n = normalize_opers(demo)[0]
    chk("专精读出", n["skills"][0]["specializeLevel"] == 3)
    chk("模组等级读出", n["equips"][0]["level"] == 3)
    chk("精英/等级/潜能", (n["elite"], n["level"], n["potential"]) == (2, 80, 6))
    # 守卫：夹具的 rank 若被改回越界值，这条先红——免得又变成
    # 「断言看着没问题，实际喂进去的是一个游戏里不存在的输入」。
    chk("夹具的 potentialRank 在合法区间（0–5，对应潜能 1–6）",
        0 <= demo[0]["potentialRank"] <= 5, str(demo[0]["potentialRank"]))

    print(f"\n{ok} 通过 / {fail} 失败")
    return 1 if fail else 0


# ---------------------------------------------------------------- CLI


def _render_terminal_qr(content: str, *, plain: bool = False) -> str:
    """用项目里的渲染器画二维码。**惰性导入**——不画二维码就不需要 qrcode。"""
    from ak_tactic.qrterm import render as render_qr
    return render_qr(content, plain=plain)


def _cmd_qr(args: argparse.Namespace, home: Path | None) -> int:
    """扫码登录：申请 → 画码 → 轮询 → 落盘 hgToken → 换 cred。"""
    interval = max(1.0, float(args.interval))
    seen: dict[str, Any] = {"status": None}

    def on_qr(scan_id: str, content: str) -> None:
        print(f"scanId = {scan_id}")
        if args.link_only:
            print(f"二维码内容：{content}")
        else:
            print("用森空岛 APP 扫下面这个码：\n")
            print(_render_terminal_qr(content, plain=args.plain))
            print()

    def on_status(status: int, text: str) -> None:
        # 只在状态变化时打一行，别把终端刷爆（轮询 2 秒一次）
        if status != seen["status"]:
            seen["status"] = status
            print(f"  [{status}] {text}", flush=True)

    print(f"申请二维码……（{interval:.0f} 秒轮询一次，最多等 {args.timeout:.0f} 秒）")
    d = login_by_qr(home=home, interval=interval, timeout=args.timeout,
                    on_qr=on_qr, on_status=on_status)
    print(f"\ncred 已保存到 {cred_path(home)}")
    print(f"  userId = {d.get('userId')}  cred = {mask(d['cred'])}")
    for b in binding_list(d["cred"], d["token"]):
        print(f"  [{b.get('channelName')}] {b.get('nickName')} "
              f"uid={b.get('uid')} default={b.get('isDefault')}")
    print("\n扫码换到的 hgToken 已经一并落盘——过期时跑 `cred` 就能静默重铸，"
          "不必再扫一次。")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="skland", description="森空岛干员数据取数")
    p.add_argument("--home", help="凭据目录（默认 %s）" % DEFAULT_HOME)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="校验 cred 并列出绑定账号")
    sub.add_parser("selftest", help="不联网自检签名实现")
    sub.add_parser("did", help="生成/刷新设备指纹 dId")
    sub.add_parser("cred", help="用已缓存的 hgToken 补完 cred（不消耗验证码）")
    sub.add_parser("accounts", help="列出本机登录过的账号（当前账号排第一）")
    sub.add_parser("logout", help="退出当前账号（不删任何文件，可用 use 切回）")
    sub.add_parser("whoami",
                   help="问森空岛要**游戏 uid** 并记住（名册按它存，见 accounts.json）")

    up = sub.add_parser("use", help="切回某个登录过的账号（不必重扫）")
    up.add_argument("uid")

    sp = sub.add_parser("send-code", help="发短信验证码")
    sp.add_argument("phone")

    lp = sub.add_parser("login", help="手机号 + 验证码 换 cred")
    lp.add_argument("phone")
    lp.add_argument("code")

    qp = sub.add_parser("qr", help="扫码登录（森空岛 APP 扫，终端里画二维码）")
    qp.add_argument("--timeout", type=float, default=180.0,
                    help="等待扫码的秒数（默认 180）")
    qp.add_argument("--interval", type=float, default=2.0,
                    help="轮询间隔秒数（默认 2）")
    qp.add_argument("--plain", action="store_true",
                    help="用纯文本画二维码（不加 ANSI 颜色；非 tty 时自动如此）")
    qp.add_argument("--link-only", action="store_true",
                    help="只打印 deep link 文本，不画二维码")

    fp = sub.add_parser("fetch", help="拉全量数据并落盘")
    fp.add_argument("--uid")

    op = sub.add_parser("opers", help="只导出干员名册摘要")
    op.add_argument("--uid")
    op.add_argument("--full", action="store_true", help="打印每条干员明细")

    args = p.parse_args(argv)
    home = Path(args.home) if args.home else None

    try:
        if args.cmd == "selftest":
            return _selftest()

        if args.cmd == "send-code":
            r = send_phone_code(args.phone)
            print("发送结果：", json.dumps(r, ensure_ascii=False))
            return 0 if r.get("status") == 0 else 2

        if args.cmd == "login":
            d = login_by_phone_code(args.phone, args.code)
            save_cred({"cred": d["cred"], "token": d["token"],
                       "userId": d.get("userId"), "hgToken": None}, home)
            print(f"cred 已保存到 {cred_path(home)}")
            print(f"  userId = {d.get('userId')}")
            print(f"  cred   = {mask(d['cred'])}")
            blist = binding_list(d["cred"], d["token"])
            for b in blist:
                print(f"  [{b.get('channelName')}] {b.get('nickName')} "
                      f"uid={b.get('uid')} default={b.get('isDefault')}")
            return 0

        if args.cmd == "qr":
            return _cmd_qr(args, home)

        if args.cmd == "whoami":
            r = resolve_game_uid(home=home)
            print(f"通行证账号 uid={r['loginUid'] or '?'}"
                  f"  →  游戏 uid={r['gameUid']}"
                  f"  {r['nickName'] or ''} {r['channelName'] or ''}".rstrip())
            print(f"已记住（{_accounts_path(home)}）。名册按游戏 uid 存，"
                  f"所以它才是「这个号的名册是哪份」的依据。")
            return 0

        if args.cmd in ("accounts", "logout", "use"):
            if args.cmd == "use":
                r = activate(args.uid, home)
                print(f"已切到账号 uid={r['uid']}")
            elif args.cmd == "logout":
                r = logout(home)
                if r["uid"]:
                    print(f"已退出账号 uid={r['uid']}"
                          f"（凭据文件保留，`use {r['uid']}` 可切回，不必重扫）")
                else:
                    print("当前本来就没有登录的账号。")
            cur = current_uid(home)
            rows = known_accounts(home)
            amap = accounts_map(home)
            if not rows:
                print("本机没有登录过的账号。")
            else:
                print(f"登录过的账号（当前：{cur or '无'}）：")
                for a in rows:
                    mark = "  ←当前" if a["uid"] == cur else ""
                    g = (amap.get(a["uid"]) or {}).get("gameUid") or "?"
                    print(f"  uid={a['uid']}  游戏uid={g}  stage={a['stage'] or '?'}"
                          f"  cred={'有' if a['has_cred'] else '无'}{mark}")
                    print(f"    {a['path']}")
            return 0

        if args.cmd == "did":
            print(f"dId = {current_did(fresh=True)}")
            return 0

        if args.cmd == "cred":
            d = finish_login(home)
            print(f"cred 已保存到 {cred_path(home)}")
            print(f"  userId = {d.get('userId')}  cred = {mask(d['cred'])}")
            for b in binding_list(d["cred"], d["token"]):
                print(f"  [{b.get('channelName')}] {b.get('nickName')} "
                      f"uid={b.get('uid')} default={b.get('isDefault')}")
            return 0

        if args.cmd == "status":
            st = load_cred(home)
            print(f"凭据文件：{cred_path(home)}")
            print(f"dId = {current_did()}")
            print(f"阶段 = {st.get('stage') or '?'}")
            print(f"cred = {mask(st.get('cred') or '')}  userId = {st.get('userId')}")
            cred, token = require_ready(st)
            print("check:", json.dumps(check_cred(cred, token),
                                       ensure_ascii=False))
            for b in binding_list(cred, token):
                print(f"  [{b.get('channelName')}] {b.get('nickName')} "
                      f"uid={b.get('uid')} default={b.get('isDefault')}")
            return 0

        if args.cmd in ("fetch", "opers"):
            res = fetch_all(uid=args.uid, home=home)
            print(f"[{res['nickName']}] uid={res['uid']}  干员 {len(res['opers'])} 名")
            print(f"  原始数据 -> {res['raw_path']}")
            print(f"  名册     -> {res['opers_path']}")
            with_spec = sum(1 for o in res["opers"]
                            if any(s.get("specializeLevel") for s in o["skills"]))
            with_mod = sum(1 for o in res["opers"]
                           if any(e.get("level") for e in o["equips"]))
            print(f"  有专精的 {with_spec} 名；有模组的 {with_mod} 名")
            if args.cmd == "opers" and args.full:
                for o in res["opers"]:
                    spec = "/".join(str(s.get("specializeLevel") or 0) for s in o["skills"])
                    mod = ",".join(f"{e['id']}:{e['level']}" for e in o["equips"]) or "-"
                    print(f"  {o['name']}({o['charId']}) E{o['elite']} L{o['level']} "
                          f"潜{o['potential']} 专精[{spec}] 模组[{mod}]")
            return 0
    except SklandError as e:
        print(f"失败：{e}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
