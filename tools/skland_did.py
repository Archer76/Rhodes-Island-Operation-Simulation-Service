# -*- coding: utf-8 -*-
"""生成森空岛要的**真实设备指纹 dId**（数美 ishumei 设备指纹 v4）。

为什么需要它
------------
`zonai.skland.com/web/v1/user/auth/generate_cred_by_code` 现在会校验请求头里的
`dId`。社区通用的占位值 `de9759a5afaa634f` 已经不被接受，服务端直接回

    {"code": 10001, "message": "设备信息无效"}

所以必须真的去数美换一个设备号。**这一步不需要任何登录态**，可以先跑先验。

协议（逆向自社区实现，MIT）
--------------------------
    待加密对象 = {浏览器环境 + protocol/organization/appId/os/version/sdkver/
                  box/rtype/smid/subVersion/time}
    tn          = md5(按 key 排序后把所有值拼成一串)   # 数字字段要先 ×10000
    逐字段 DES-ECB 加密（key 见 DES_RULE，密文 btoa）+ 改名为 obfuscated_name
    → JSON → gzip(level 2) → AES-CBC 加密（key = md5(uid)[:16]，iv 固定，零填充）
    → hex 作为 data 发给 https://fp-it.portal101.cn/deviceprofile/v4

**两个必须逐字节复刻的坑**（否则服务端解密失败但不报明错）：

1. `cryptography` 的 `CipherContext.update()` 对不足整块的尾部**只缓冲不输出**，
   原实现又从不调 `finalize()`。所以 DES 那步的真实语义是
   「取字符串前 `⌊len/8⌋×8` 字节做 ECB」——**不是零填充到整块**。
   本项目用 pycryptodome 复刻同一语义，必须显式截断。
2. AES 那步是**零填充**到 16 的倍数（不是 PKCS7）。

依赖：`Cryptodome`（pycryptodome 的命名空间变体，本机已装 3.23.0）。
开放平台全项目零依赖，唯独这个工具需要它——若无该库，本模块会给出明确提示，
其余功能不受影响。

用法
----
    python tools/skland_did.py            # 生成并缓存 dId
    python tools/skland_did.py --fresh    # 丢弃缓存重新生成
    python tools/skland_did.py selftest   # 不联网：校验加密拼装
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

DEFAULT_HOME = Path(os.environ.get("SKLAND_HOME") or Path.home() / ".skland")

DEVICES_INFO_URL = "https://fp-it.portal101.cn/deviceprofile/v4"

SM_ORGANIZATION = "UWXspnCCJN4sfYlNfqps"
SM_APP_ID = "default"
SM_PUBLIC_KEY = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCmxMNr7n8ZeT0tE1R9j/mPixoinPke"
    "M+k4VGIn/s0k7N5rJAfnZ0eMER+QhwFvshzo0LNmeUkpR8uIlU/GEVr8mN28sKmwd2gpygqj0ePn"
    "BmOW4v0ZVwbSYK+izkhVFk2V/doLoMbWy6b+UnA8mkjvg0iYWRByfRsK2gdl7llqCwIDAQAB"
)

#: 每个字段用什么 DES key、加密后改叫什么名字。
DES_RULE: dict[str, dict] = {
    "appId": {"cipher": "DES", "is_encrypt": 1, "key": "uy7mzc4h", "obfuscated_name": "xx"},
    "box": {"is_encrypt": 0, "obfuscated_name": "jf"},
    "canvas": {"cipher": "DES", "is_encrypt": 1, "key": "snrn887t", "obfuscated_name": "yk"},
    "clientSize": {"cipher": "DES", "is_encrypt": 1, "key": "cpmjjgsu", "obfuscated_name": "zx"},
    "organization": {"cipher": "DES", "is_encrypt": 1, "key": "78moqjfc", "obfuscated_name": "dp"},
    "os": {"cipher": "DES", "is_encrypt": 1, "key": "je6vk6t4", "obfuscated_name": "pj"},
    "platform": {"cipher": "DES", "is_encrypt": 1, "key": "pakxhcd2", "obfuscated_name": "gm"},
    "plugins": {"cipher": "DES", "is_encrypt": 1, "key": "v51m3pzl", "obfuscated_name": "kq"},
    "pmf": {"cipher": "DES", "is_encrypt": 1, "key": "2mdeslu3", "obfuscated_name": "vw"},
    "protocol": {"is_encrypt": 0, "obfuscated_name": "protocol"},
    "referer": {"cipher": "DES", "is_encrypt": 1, "key": "y7bmrjlc", "obfuscated_name": "ab"},
    "res": {"cipher": "DES", "is_encrypt": 1, "key": "whxqm2a7", "obfuscated_name": "hf"},
    "rtype": {"cipher": "DES", "is_encrypt": 1, "key": "x8o2h2bl", "obfuscated_name": "lo"},
    "sdkver": {"cipher": "DES", "is_encrypt": 1, "key": "9q3dcxp2", "obfuscated_name": "sc"},
    "status": {"cipher": "DES", "is_encrypt": 1, "key": "2jbrxxw4", "obfuscated_name": "an"},
    "subVersion": {"cipher": "DES", "is_encrypt": 1, "key": "eo3i2puh", "obfuscated_name": "ns"},
    "svm": {"cipher": "DES", "is_encrypt": 1, "key": "fzj3kaeh", "obfuscated_name": "qr"},
    "time": {"cipher": "DES", "is_encrypt": 1, "key": "q2t3odsk", "obfuscated_name": "nb"},
    "timezone": {"cipher": "DES", "is_encrypt": 1, "key": "1uv05lj5", "obfuscated_name": "as"},
    "tn": {"cipher": "DES", "is_encrypt": 1, "key": "x9nzj1bp", "obfuscated_name": "py"},
    "trees": {"cipher": "DES", "is_encrypt": 1, "key": "acfs0xo4", "obfuscated_name": "pi"},
    "ua": {"cipher": "DES", "is_encrypt": 1, "key": "k92crp1t", "obfuscated_name": "bj"},
    "url": {"cipher": "DES", "is_encrypt": 1, "key": "y95hjkoo", "obfuscated_name": "cf"},
    "version": {"is_encrypt": 0, "obfuscated_name": "version"},
    "vpw": {"cipher": "DES", "is_encrypt": 1, "key": "r9924ab5", "obfuscated_name": "ca"},
}

BROWSER_ENV: dict[str, object] = {
    "plugins": ("MicrosoftEdgePDFPluginPortableDocumentFormatinternal-pdf-viewer1,"
                "MicrosoftEdgePDFViewermhjfbmdgcfjbbpaeojofohoefgiehjai1"),
    "ua": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0"),
    "canvas": "259ffe69",
    "timezone": -480,
    "platform": "Win32",
    "url": "https://www.skland.com/",
    "referer": "",
    "res": "1920_1080_24_1.25",
    "clientSize": "0_0_1080_1920_1920_1080_1920_1080",
    "status": "0011",
}


class DidError(RuntimeError):
    pass


def _require_crypto():
    try:
        from Cryptodome.Cipher import AES, DES  # noqa: F401
        from Cryptodome.Cipher import PKCS1_v1_5  # noqa: F401
        from Cryptodome.PublicKey import RSA  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise DidError("需要 pycryptodome（import Cryptodome）："
                       "pip install --target <dir> pycryptodome") from e


# ---------------------------------------------------------------- 加密原语


def get_tn(o: dict) -> str:
    """按 key 排序，把所有值拼成一串；数字字段先 ×10000。"""
    parts = []
    for k in sorted(o.keys()):
        v = o[k]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(v * 10000)
        elif isinstance(v, dict):
            v = get_tn(v)
        parts.append(v)
    return "".join(parts)


def des_field(value: object, key: str) -> str:
    """逐字段 DES-ECB + base64。

    复刻原实现「先 `data += b"\\x00"*8`、再交给 `cryptography` 的 `update()`」的语义。
    `update()` 只输出完整块、把不足一块的尾部缓冲掉且从不 `finalize()`，所以真正
    参与加密的是 `data + 8个空字节` 的前 ⌊L/8⌋×8 字节：

        n % 8 == 0  →  加密 n+8 字节（多补一整块）
        n % 8 != 0  →  加密 ⌈n/8⌉×8 字节（零填充到块边界）

    两者合并即 `total = ⌊(n+8)/8⌋×8` 的零填充。
    第 1 版我误读成「截断掉尾部」，密文长度不对，数美直接回 1902 拒绝。
    """
    from Cryptodome.Cipher import DES
    data = str(value).encode("utf-8")
    total = ((len(data) + 8) // 8) * 8
    padded = data + b"\x00" * (total - len(data))
    cipher = DES.new(key.encode("utf-8"), DES.MODE_ECB)
    return base64.b64encode(cipher.encrypt(padded)).decode("utf-8")


def des_object(o: dict) -> dict:
    """按 DES_RULE 改名并加密每个字段。"""
    out: dict = {}
    for k, v in o.items():
        rule = DES_RULE.get(k)
        if rule is None:
            out[k] = v
            continue
        if rule.get("is_encrypt") == 1:
            out[rule["obfuscated_name"]] = des_field(v, rule["key"])
        else:
            out[rule["obfuscated_name"]] = v
    return out


def gzip_b64(o: dict) -> bytes:
    js = json.dumps(o, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(gzip.compress(js, 2, mtime=0))


def aes_cbc_hex(payload: bytes, key: bytes, iv: bytes = b"0102030405060708") -> str:
    """AES-CBC 加密，**零填充**到 16 的倍数。"""
    from Cryptodome.Cipher import AES
    v = payload + b"\x00"
    while len(v) % 16 != 0:
        v += b"\x00"
    return AES.new(key, AES.MODE_CBC, iv).encrypt(v).hex()


def rsa_ep(uid: bytes) -> str:
    from Cryptodome.Cipher import PKCS1_v1_5
    from Cryptodome.PublicKey import RSA
    pub = RSA.import_key(base64.b64decode(SM_PUBLIC_KEY))
    return base64.b64encode(PKCS1_v1_5.new(pub).encrypt(uid)).decode("utf-8")


def get_smid() -> str:
    t = time.localtime()
    stamp = (f"{t.tm_year}{t.tm_mon:0>2d}{t.tm_mday:0>2d}"
             f"{t.tm_hour:0>2d}{t.tm_min:0>2d}{t.tm_sec:0>2d}")
    uid = str(uuid.uuid4())
    v = stamp + hashlib.md5(uid.encode("utf-8")).hexdigest() + "00"
    smsk_web = hashlib.md5(("smsk_web_" + v).encode("utf-8")).hexdigest()[0:14]
    return v + smsk_web + "0"


def build_payload() -> tuple[dict, str]:
    """返回 (请求体, priId)。priId = AES 密钥。"""
    uid = str(uuid.uuid4()).encode("utf-8")
    pri_id = hashlib.md5(uid).hexdigest()[0:16]

    browser = dict(BROWSER_ENV)
    now_ms = int(time.time() * 1000)
    browser.update({"vpw": str(uuid.uuid4()), "svm": now_ms,
                    "trees": str(uuid.uuid4()), "pmf": now_ms})

    target: dict = {
        **browser,
        "protocol": 102,
        "organization": SM_ORGANIZATION,
        "appId": SM_APP_ID,
        "os": "web",
        "version": "3.0.0",
        "sdkver": "3.0.0",
        "box": "",
        "rtype": "all",
        "smid": get_smid(),
        "subVersion": "1.0.0",
        "time": 0,
    }
    target["tn"] = hashlib.md5(get_tn(target).encode("utf-8")).hexdigest()

    data = aes_cbc_hex(gzip_b64(des_object(target)), pri_id.encode("utf-8"))
    body = {
        "appId": SM_APP_ID,
        "compress": 2,
        "data": data,
        "encode": 5,
        "ep": rsa_ep(uid),
        "organization": SM_ORGANIZATION,
        "os": "web",
    }
    return body, pri_id


def fetch_did(timeout: float = 30.0) -> str:
    """真去数美换一个 dId，返回形如 'B' + deviceId。"""
    _require_crypto()
    body, _ = build_payload()
    req = urllib.request.Request(
        DEVICES_INFO_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": BROWSER_ENV["ua"]},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if payload.get("code") != 1100:
        raise DidError(f"数美拒绝：{json.dumps(payload, ensure_ascii=False)[:400]}")
    device_id = (payload.get("detail") or {}).get("deviceId")
    if not device_id:
        raise DidError(f"响应里没有 deviceId：{payload}")
    return "B" + device_id


# ---------------------------------------------------------------- 缓存


def did_path(home: Path | None = None) -> Path:
    return (home or DEFAULT_HOME) / "did.txt"


def get_did(*, home: Path | None = None, fresh: bool = False) -> str:
    """取 dId：优先用缓存（保持指纹稳定），否则现生成并落盘。"""
    p = did_path(home)
    if not fresh and p.exists():
        v = p.read_text(encoding="utf-8").strip()
        if v:
            return v
    v = fetch_did()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(v, encoding="utf-8")
    return v


# ---------------------------------------------------------------- 自检


def _selftest() -> int:
    ok = fail = 0

    def chk(name: str, cond: bool, extra: str = "") -> None:
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  [ok] {name}")
        else:
            fail += 1
            print(f"  [XX] {name} {extra}")

    print("[1] 依赖")
    try:
        _require_crypto()
        chk("Cryptodome 可用", True)
    except DidError as e:
        chk("Cryptodome 可用", False, str(e))
        print(f"\n{ok} 通过 / {fail} 失败")
        return 1

    print("[2] tn：排序 + 数字×10000")
    chk("数字字段放大", get_tn({"b": 1}) == "10000", get_tn({"b": 1}))
    chk("负数", get_tn({"tz": -480}) == "-4800000", get_tn({"tz": -480}))
    chk("零", get_tn({"t": 0}) == "0", get_tn({"t": 0}))
    chk("按 key 排序", get_tn({"b": "B", "a": "A"}) == "AB", get_tn({"b": "B", "a": "A"}))
    chk("嵌套递归", get_tn({"z": {"b": 1, "a": 2}}) == "2000010000",
        get_tn({"z": {"b": 1, "a": 2}}))

    print("[3] DES 语义 = 零填充到块边界，已对齐则再补一整块")
    # n=7 → ⌊15/8⌋×8 = 8 字节
    chk("7 字节 → 8 字节密文(12 字符 base64)",
        len(des_field("default", "uy7mzc4h")) == 12, repr(des_field("default", "uy7mzc4h")))
    # n=8 → 已对齐 → 16 字节
    one = des_field("abcdefgh", "uy7mzc4h")
    chk("8 字节 → 16 字节密文(24 字符 base64)", len(one) == 24, f"{len(one)} {one}")
    # n=15 → ⌊23/8⌋×8 = 16 字节
    chk("15 字节 → 16 字节密文",
        len(des_field("abcdefghijklmno", "uy7mzc4h")) == 24)
    # n=16 → ⌊24/8⌋×8 = 24 字节
    chk("16 字节 → 24 字节密文",
        len(des_field("abcdefghijklmnop", "uy7mzc4h")) == 32)
    # 不可与「截断」版本混同
    chk("8 字节与 15 字节结果不同（不是同一块）",
        des_field("abcdefghijklmno", "uy7mzc4h") != one)
    chk("同输入同输出", des_field("abcdefgh", "uy7mzc4h") == one)

    print("[4] 字段改名")
    d = des_object({"appId": "x", "box": "", "version": "3.0.0"})
    chk("appId→xx（加密）", "xx" in d and "appId" not in d, str(list(d)))
    chk("box→jf（不加密）", d.get("jf") == "")
    chk("version→version（不加密）", d.get("version") == "3.0.0")

    print("[5] AES 零填充到 16 的倍数")
    ct = aes_cbc_hex(b"hello", b"0123456789abcdef")
    chk("密文长度为 16 字节 → 32 hex", len(ct) == 32, str(len(ct)))
    chk("同输入同输出", ct == aes_cbc_hex(b"hello", b"0123456789abcdef"))
    chk("换 key 结果不同", ct != aes_cbc_hex(b"hello", b"fedcba9876543210"))

    print("[6] gzip 可解回原 JSON")
    gz = gzip_b64({"a": "中文"})
    back = json.loads(gzip.decompress(base64.b64decode(gz)).decode("utf-8"))
    chk("往返一致", back == {"a": "中文"}, str(back))

    print("[7] smid 形状")
    s = get_smid()
    # 时间戳14 + md5(uid)32 + "00" + md5(smsk_web_…)[:14] + "0"
    chk("长度 14+32+2+14+1 = 63", len(s) == 63, f"len={len(s)}")
    chk("末位为 0", s.endswith("0"))
    chk("前 14 位是时间戳", s[:14].isdigit(), s[:14])

    print("[8] 整体请求体形状")
    body, pri = build_payload()
    chk("priId 为 16 位 hex",
        len(pri) == 16 and all(c in "0123456789abcdef" for c in pri), pri)
    chk("data 为 hex 且长度是 32 的倍数",
        len(body["data"]) % 32 == 0 and all(c in "0123456789abcdef" for c in body["data"]))
    chk("encode=5 / compress=2",
        body["encode"] == 5 and body["compress"] == 2)
    chk("ep 非空 base64", len(body["ep"]) > 100)

    print(f"\n{ok} 通过 / {fail} 失败")
    return 1 if fail else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="skland_did", description="生成森空岛 dId")
    p.add_argument("--home", help="凭据目录（默认 %s）" % DEFAULT_HOME)
    p.add_argument("--fresh", action="store_true", help="丢弃缓存重新生成")
    p.add_argument("cmd", nargs="?", default="get", choices=["get", "selftest"])
    args = p.parse_args(argv)

    if args.cmd == "selftest":
        return _selftest()

    home = Path(args.home) if args.home else None
    try:
        v = get_did(home=home, fresh=args.fresh)
    except DidError as e:
        print(f"失败：{e}", file=sys.stderr)
        return 2
    print(f"dId = {v}")
    print(f"缓存 = {did_path(home)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
