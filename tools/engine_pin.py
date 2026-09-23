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


def source_sig(head: bool = False) -> str:
    """`rios-sim/**/*.go` 的身份摘要（不带文件名前缀的裸内容，按路径排序后拼）。

    ⚠ **这是"磁盘此刻"的身份，不是"HEAD 的身份"**（实测：同一实现，23:45 算得 `2a9c381a`、
    23:55 算得 `9b81f2d5`——中间别人动了 `.go`；两棵树、同一个函数，值不同的唯一原因是**时刻**）。
    共享工作区里任何会话的**未提交中间态**都会被摘进去。要比"**这台仪器是不是 HEAD 的构建**"，
    用 `head=True`（逐文件从 `git show HEAD:<path>` 取内容，同一套折行规则算）。
    两条都要：**"是不是那次构建"看 exe 哈希，"是哪份源码"看这两个摘要**。
    """
    src = sorted((ROOT / "rios-sim").glob("**/*.go"))
    if not head:
        blob = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in src)
    else:
        #: ⚠ **HEAD 里没有的文件要跳过**（不是记空串）：否则「新增一个未入库的 .go」
        #: 会因为多出一个空元素而**改变 head 摘要**——那样两个身份就分不开了。
        #: 语义是「HEAD 这份源码的身份」＝HEAD 里那些 .go 的内容。
        parts = []
        for p in src:
            rel = p.relative_to(ROOT).as_posix()
            r = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8")
            if r.returncode == 0:
                parts.append(r.stdout)
        blob = "\n".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def source_sig_head() -> str:
    """**HEAD 那份源码**的身份（从 blob 算，检出无关；与 `source_sig()` 同一套折行规则，可比）。

    判「这台仪器是不是 **HEAD 的构建**」**只能用这个**：磁盘版会把别人正在编辑的中间态摘进去。
    """
    return source_sig(head=True)


def source_identity() -> dict:
    """一次把两个身份 + dirty 证据都取出来（**取 disk 版必须同时报 dirty**）。

    返回 `{disk, head, same, dirty_n, dirty_files, glob}`。
    """
    r = subprocess.run(["git", "status", "--porcelain", "--", "rios-sim"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    files = [ln[3:].strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    d = source_sig()
    h = source_sig_head()
    return {"disk": d, "head": h, "same": d == h, "dirty_n": len(files),
            "dirty_files": files, "glob": "rios-sim/**/*.go"}


def ensure_pinned(verbose: bool = True) -> tuple[Path, str, str]:
    """返回 (exe, sha16, source_sig)。已钉就直接用；没钉就自建一枚再钉。"""
    raw = (os.environ.get("RIOS_SIM_BIN") or "").strip()
    sig = source_sig()
    head_sig = source_sig_head()
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
        print(f"仪器：已自建并钉住 {target.name}（sha16 {h}，source_sig={sig}"
              + (f"，⚠ 磁盘源码 ≠ HEAD（HEAD={head_sig}）" if head_sig != sig else "，= HEAD") + "）")
    return target, h, sig


def selftest() -> int:
    """**反向守卫**：写一行**不提交**的 `.go` ⇒ `source_sig_disk` 必须变、`source_sig_head` **必须不变**。

    这一条同时验两件事：两个身份确实**分开**了，而且 head 版**检出无关**。
    夹具用**临时新文件**（不动别人可能正在编辑的文件），跑完删掉并复核两个摘要都回到原值。
    """
    bad = 0
    before = source_identity()
    print(f"起始：disk={before['disk']}　head={before['head']}　同否={before['same']}"
          f"　dirty(rios-sim)={before['dirty_n']}　glob={before['glob']}")
    probe = ROOT / "rios-sim" / "zz_guard_source_sig_probe.go"
    if probe.exists():
        print(f"⛔ 夹具路径已被占用：{probe}")
        return 1
    try:
        probe.write_text("package main\n\n// 反向守卫夹具：只为改 disk 摘要，不入库\n",
                         encoding="utf-8")
        mid = source_identity()
        ok_disk = mid["disk"] != before["disk"]
        ok_head = mid["head"] == before["head"]
        bad += 0 if ok_disk else 1
        bad += 0 if ok_head else 1
        print(f"写入未入库的 .go ⇒ disk={mid['disk']}（{'✅ 变了' if ok_disk else '❌ 没变'}）"
              f"　head={mid['head']}（{'✅ 没变' if ok_head else '❌ 也变了 ⇒ 两个身份没分开'}）")
    finally:
        probe.unlink(missing_ok=True)
    after = source_identity()
    ok_back = after["disk"] == before["disk"] and after["head"] == before["head"]
    bad += 0 if ok_back else 1
    print(f"删掉夹具后 ⇒ disk={after['disk']}　head={after['head']}　"
          f"{'✅ 两个摘要都回到原值' if ok_back else '❌ 没回到原值'}")
    print("✅ 两个身份确实分开" if bad == 0 else f"❌ {bad} 项不成立")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    try:
        exe, h, sig = ensure_pinned()
    except EngineBuildError as e:
        print(f"❌ {e}")
        raise SystemExit(1)
    ident = source_identity()
    print(f"✅ {exe}\n   sha16={h}\n   source_sig(disk)={ident['disk']}"
          f"\n   source_sig(head)={ident['head']}"
          f"\n   两个身份相同={ident['same']}　dirty(rios-sim)={ident['dirty_n']} 条"
          + (f"：{ident['dirty_files'][:6]}" if ident["dirty_files"] else "")
          + f"\n   glob={ident['glob']}")
    print(f"   源码最新 mtime="
          f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(max(p.stat().st_mtime for p in (ROOT / 'rios-sim').glob('**/*.go'))))}")
    sys.exit(0)
