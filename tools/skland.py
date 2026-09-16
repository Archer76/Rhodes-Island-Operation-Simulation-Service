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

凭据只落盘在 `~/.skland/cred.json`（默认 `D:\\home\\DSH\\.skland\\`），
不进仓库、不打印明文。

用法
----
    python tools/skland.py status                     # 校验 cred + 列出绑定账号
    python tools/skland.py send-code <手机号>          # 发短信验证码
    python tools/skland.py login <手机号> <验证码>      # 换取并保存 cred
    python tools/skland.py fetch [--uid U]            # 拉全量数据，落 data/skland/
    python tools/skland.py opers [--uid U]            # 只导出干员名册（含专精/模组）
    python tools/skland.py selftest                   # 不联网：校验签名拼装
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
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import skland_did
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
    """用已保存的 hgToken 走完 grant + cred。可反复重试，不再消耗验证码。"""
    st = load_cred(home)
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


def cred_path(home: Path | None = None) -> Path:
    return (home or DEFAULT_HOME) / "cred.json"


def save_cred(payload: dict[str, Any], home: Path | None = None) -> Path:
    p = cred_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_cred(home: Path | None = None) -> dict[str, Any]:
    p = cred_path(home)
    if not p.exists():
        raise SklandError(f"没有凭据文件 {p}，先跑 `send-code` + `login`。")
    return json.loads(p.read_text(encoding="utf-8"))


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
    """拉全量玩家数据并落盘，返回 {uid, raw_path, opers_path, opers}。"""
    st = load_cred(home)
    cred, token = require_ready(st)

    blist = binding_list(cred, token)
    if not blist:
        raise SklandError("没有绑定任何明日方舟角色")
    target = None
    if uid:
        for b in blist:
            if str(b.get("uid")) == str(uid):
                target = b
                break
        if target is None:
            raise SklandError(f"uid {uid} 不在绑定列表里：{blist}")
    else:
        for b in blist:
            if b.get("isDefault"):
                target = b
                break
        target = target or blist[0]

    real_uid = str(target["uid"])
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
    demo = [{
        "charId": "char_002_amiya", "evolvePhase": 2, "level": 80,
        "potentialRank": 6, "mainSkillLvl": 7,
        "skills": [{"skillId": "sk_1", "level": 7, "specializeLevel": 3}],
        "equip": [{"id": "uniequip_002_amiya", "level": 3, "locked": False}],
    }]
    n = normalize_opers(demo)[0]
    chk("专精读出", n["skills"][0]["specializeLevel"] == 3)
    chk("模组等级读出", n["equips"][0]["level"] == 3)
    chk("精英/等级/潜能", (n["elite"], n["level"], n["potential"]) == (2, 80, 6))

    print(f"\n{ok} 通过 / {fail} 失败")
    return 1 if fail else 0


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="skland", description="森空岛干员数据取数")
    p.add_argument("--home", help="凭据目录（默认 %s）" % DEFAULT_HOME)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="校验 cred 并列出绑定账号")
    sub.add_parser("selftest", help="不联网自检签名实现")
    sub.add_parser("did", help="生成/刷新设备指纹 dId")
    sub.add_parser("cred", help="用已缓存的 hgToken 补完 cred（不消耗验证码）")

    sp = sub.add_parser("send-code", help="发短信验证码")
    sp.add_argument("phone")

    lp = sub.add_parser("login", help="手机号 + 验证码 换 cred")
    lp.add_argument("phone")
    lp.add_argument("code")

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
