# -*- coding: utf-8 -*-
"""Go 版模拟器（`rios-sim/`）的门口自检。

现在只量三件最基础的事：**能不能编译、协议版本对不对、出错时会不会说假话**。
对拍台（判决逐项比对）还没落地——它落地的第一天就该长在这个文件里。

## 本机没装 Go 时**跳过**，不是失败

克隆仓库的人不该被一个新组件拦在门外。判据同 `ak_tactic` 的其它工具：
`shutil.which("go")` 与 `go env` 都活着才算装了。

用法：`python tools/check_simgo.py`
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIMDIR = ROOT / "rios-sim"
EXE = SIMDIR / ("rios-sim.exe" if os.name == "nt" else "rios-sim")

_PASSED = 0
_FAILED: list[str] = []
_SKIPPED: list[str] = []


def check(what: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {what}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(what)
        print(f"  [FAIL] {what}" + (f"   {detail}" if detail else ""))


def skip(what: str, why: str) -> None:
    _SKIPPED.append(what)
    print(f"  [skip] {what}   {why}")


def _env() -> dict:
    env = dict(os.environ)
    # 本机 Go 是 1.26；`GOTOOLCHAIN=local` 挡住"发现工具链版本不够就去联网下一份"
    # 的默认行为——自检不该在背后下载东西。
    env["GOTOOLCHAIN"] = "local"
    return env


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(SIMDIR), env=_env(),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def _proto(args: list[str], stdin: str) -> tuple[int, list[dict], str]:
    """跑一次二进制，把 stdout 的 JSON 行解出来。"""
    p = subprocess.run([str(EXE), *args], input=stdin, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    rows: list[dict] = []
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"__bad_json__": line})
    return p.returncode, rows, p.stderr or ""


def main() -> int:
    print("检查 Go 版模拟器（rios-sim/）")

    if shutil.which("go") is None:
        skip("rios-sim 全部检查", "本机没装 Go（新组件，不拦别人）")
        print(f"\n通过 {_PASSED} 项，跳过 {len(_SKIPPED)} 项。")
        return 0

    check("rios-sim 目录在（go.mod / main.go 都在）",
          (SIMDIR / "go.mod").is_file() and (SIMDIR / "main.go").is_file())
    if not (SIMDIR / "go.mod").is_file():
        print("\nrios-sim 目录不完整，后面的检查没有意义。")
        return 1

    ver = _run(["go", "mod", "edit", "-json"])
    mod = ver.stdout or ""
    check("go.mod 用的是本机 Go 能编的版本",
          ver.returncode == 0 and "rios-sim" in mod,
          mod.splitlines()[1].strip() if mod.count("\n") > 0 else mod[:40])

    # 构建产物不入库：它是可再生的（.gitignore 已挡）
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("构建产物被 .gitignore 挡住（可再生的东西不入库）",
          "rios-sim/rios-sim" in gi or "rios-sim/*.exe" in gi, gi[:0])

    b = _run(["go", "build", "-o", EXE.name, "."])
    check("go build 能编译出二进制", b.returncode == 0 and EXE.is_file(),
          (b.stderr or "").strip()[-120:])
    if not EXE.is_file():
        print(f"\n通过 {_PASSED} 项，失败 {len(_FAILED)} 项。")
        return 1

    vet = _run(["go", "vet", "./..."])
    check("go vet 干净", vet.returncode == 0, (vet.stderr or "").strip()[-120:])

    # ---- 协议：ping / 未知命令 / 坏 JSON / 未实现的 sim
    rc, rows, _ = _proto([], '{"id":1,"cmd":"ping"}\n')
    ping = rows[0] if rows else {}
    check("ping 回一行合法 JSON、且 ok:true",
          rc == 0 and len(rows) == 1 and ping.get("ok") is True, json.dumps(ping)[:90])
    check("ping 带回协议版本（调用方要先核对它）",
          isinstance(ping.get("pong", {}).get("version"), int),
          str(ping.get("pong", {}).get("version")))
    check("ping 里的版本与本文件认的一致（v1）",
          ping.get("pong", {}).get("version") == 1)

    rc, rows, _ = _proto([], '{"id":2,"cmd":"nope"}\n')
    check("不认识的命令 → ok:false 并说清支持什么",
          len(rows) == 1 and rows[0].get("ok") is False
          and "ping" in rows[0].get("error", ""), json.dumps(rows[:1])[:100])

    rc, rows, _ = _proto([], 'not json\n')
    check("坏 JSON → 一行错误，不崩、不静默",
          rc == 0 and len(rows) == 1 and rows[0].get("ok") is False
          and "JSON" in rows[0].get("error", ""), json.dumps(rows[:1])[:100])

    rc, rows, _ = _proto([], '{"id":3,"cmd":"sim","spec":{}}\n')
    check("**sim 没实现时如实说没实现**（绝不返回假判决——那会让对拍台失效）",
          len(rows) == 1 and rows[0].get("ok") is False
          and "verdict" not in rows[0], json.dumps(rows[:1])[:110])

    # ---- 一批多条：应答与请求同序
    rc, rows, _ = _proto([], '{"id":1,"cmd":"ping"}\n{"id":2,"cmd":"ping"}\n'
                             '{"id":3,"cmd":"nope"}\n')
    check("一批多条按序应答（id 与请求一一对应）",
          [r.get("id") for r in rows] == [1, 2, 3], str([r.get("id") for r in rows]))

    print(f"\n通过 {_PASSED} 项", end="")
    if _SKIPPED:
        print(f"，跳过 {len(_SKIPPED)} 项", end="")
    if _FAILED:
        print(f"，失败 {len(_FAILED)} 项：")
        for f in _FAILED:
            print(f"  - {f}")
        return 1
    print("，无失败。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
