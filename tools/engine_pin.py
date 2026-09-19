#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**自建自钉**：给需要跑 Go 引擎的工具提供一枚"自己造的、自己钉住的"二进制。

## 为什么必须有这个小模块

`find_binary()` 在 2026-09-19 23:36（`52c89a4`）之后**未设 `RIOS_SIM_BIN` 就抛
`EngineBinaryUnpinned`，不再回退到工作树里那枚预编译 exe、也不再返回 `None`**。
在那之前，"没钉住"是一个**静默**状态：读数会落到一枚可能与源码无关的旧 exe 上——
实测同一份基线、同一批 19 份、同一条 `--check`，只因一枚是旧的共享 exe
（构建于 19:08、落后 16 个提交）一枚是当轮构建，`hsex8_max.json` 一处 814.0333s/591046.1、
一处 221.6667s/282276.8。**报告里没有仪器身份时，两台仪器会被当成一台。**

于是每个要跑引擎的工具只有两条正当出路：**自建自钉**，或**当场拒绝**。
这个模块给的是前者：按 `rios-sim/**/*.go` 的源码摘要算出 `source_sig`，
缺哪一枚就就地 `go build` 一枚，然后**把 `RIOS_SIM_BIN` 钉进本进程环境**，
并返回身份三件套，供报告打印。

## 用法

    from engine_pin import ensure_pinned
    exe, sha16, src_sig = ensure_pinned()      # 已钉 / 自建后钉 / 失败即抛

⚠ **不许**把它当成"自动兜底"：`source_sig` 变了就会**重新构建**，
构建失败**必须让调用方失败**（抛出来），不许回退到任何既有 exe。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "acceptance"


class EngineBuildError(RuntimeError):
    """自建失败。**不许**退回旧 exe——那正是这套机制要消灭的东西。"""


def source_sig() -> str:
    """`rios-sim/**/*.go` 的内容摘要（不带文件名前缀的裸内容，按路径排序后拼）。"""
    src = sorted((ROOT / "rios-sim").glob("**/*.go"))
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in src)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def ensure_pinned(verbose: bool = True) -> tuple[Path, str, str]:
    """返回 (exe, sha16, source_sig)。已钉就直接用；没钉就自建一枚再钉。"""
    raw = (os.environ.get("RIOS_SIM_BIN") or "").strip()
    sig = source_sig()
    if raw:
        p = Path(raw)
        if not p.exists():
            raise EngineBuildError(f"RIOS_SIM_BIN 指着一个不存在的文件：{p}")
        h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        if verbose:
            print(f"仪器：已钉 {p.name}（sha16 {h}）")
        return p, h, sig
    target = OUT / f"rios-sim-{sig}.exe"
    if not target.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        go = shutil.which("go") or "go"
        t0 = time.time()
        if verbose:
            print(f"仪器：未钉 ⇒ **自建**（source_sig={sig}）……")
        r = subprocess.run([go, "build", "-buildvcs=false", "-o", str(target), "."],
                           cwd=ROOT / "rios-sim", capture_output=True, text=True)
        if r.returncode != 0 or not target.exists():
            raise EngineBuildError(
                f"自建失败（rc={r.returncode}）：{(r.stderr or r.stdout or '')[-400:]}\n"
                f"⛔ 不退回任何既有 exe——旧 exe 正是'读数不可归因'的成因")
        if verbose:
            print(f"      构建完成 {time.time() - t0:.1f}s → {target.name}")
    os.environ["RIOS_SIM_BIN"] = str(target)
    h = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
    if verbose:
        print(f"仪器：已自建并钉住 {target.name}（sha16 {h}，source_sig={sig}）")
    return target, h, sig


if __name__ == "__main__":
    try:
        exe, h, sig = ensure_pinned()
    except EngineBuildError as e:
        print(f"❌ {e}")
        raise SystemExit(1)
    print(f"✅ {exe}\n   sha16={h}\n   source_sig={sig}\n   字节={exe.stat().st_size}")
    print(f"   源码最新 mtime="
          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(max(p.stat().st_mtime for p in (ROOT / 'rios-sim').glob('**/*.go'))))}")
    sys.exit(0)
