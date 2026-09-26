#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在**冻结树**上跑一次完整整闸，并把「四件套身份」一起印出来。

## 它解决什么

整闸读数此前只能**手工**取：建 worktree、拷 data、补名册、在树里自己 build、跑、收尾。
手工做有三处会出错，而且**错的时候读数看起来都对**：

1. **忘了补名册** ⇒ `干员` 那套给 `rc=3`（仪器缺输入），而整闸的结论会写成「25/26」——
   看起来像判据红，其实是我自己少拷了一个文件。实测踩过一次。
2. **用了主树的 exe** ⇒ 量的是别处的二进制。本仓为此栽过不止一次。
3. **收尾时用 `git worktree remove --force`** ⇒ **穿透 junction 删掉主仓 `data/`**。
   2026-09-24 真发生过一次，当晚重建。

⇒ 本脚本把这三处都变成**代码**：**绝不建 junction**（只复制）、
**仪器只用这棵树自己 build 的那一枚**、**收尾先删拷贝再摘树**（不用 `--force` 兜数据）。

## 用法

    python tools\\verify_pinned_tree.py                 # 用当前 HEAD
    python tools\\verify_pinned_tree.py --sha 5ee2707    # 用指定 sha
    python tools\\verify_pinned_tree.py --keep           # 跑完不清理（便于复查）
    python tools\\verify_pinned_tree.py --skip-roster    # 故意不补名册（演示 rc=3 那一态）

## 输出

四件套（**树 ／ 仪器 ／ 输入 ／ 结果**）＋ 逐套结论行 ＋ 一份日志落 `out/`。
退出码＝整闸自己的退出码（0 绿、非 0 红）；**脚本自身的错另给 3**（与判据红分开）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import roster_path as RP                                       # noqa: E402

WT = Path(os.environ.get("TEMP", "/tmp")) / "rios-pinned-tree"
ROSTER = RP.roster_path()


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd or ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def git(*a: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return run(["git", *a], cwd=cwd)


def head_sha() -> str:
    return git("rev-parse", "HEAD").stdout.strip()


def cleanup(keep: bool) -> None:
    """收尾：**先删拷贝，再摘树**，且**不用 `--force`**。

    ⚠ 顺序不能反，也不能图省事直接 `--force`：2026-09-24 那次事故就是
    `git worktree remove --force` 穿透 junction 把主仓 `data/` 删了。
    这里**从不建 junction**，所以目标本来就不会被穿透；先删拷贝只是第二道防线。
    """
    if keep or not WT.exists():
        return
    data = WT / "data"
    if data.exists():
        mb = sum(f.stat().st_size for f in data.rglob("*") if f.is_file()) / 1024 / 1024
        shutil.rmtree(data, ignore_errors=True)
        print("  已删掉拷进去的 data/（%.0f MB）" % mb)
    r = git("worktree", "remove", str(WT))
    if r.returncode != 0:
        print("  worktree remove rc=%d：%s" % (r.returncode, r.stderr.strip()[:120]))
        print("  ⇒ 留着手工处理；**不要**为省事加 --force（先确认里面没有 junction）")
    else:
        print("  已摘掉冻结树")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", default="", help="要验证的提交（缺省＝当前 HEAD）")
    ap.add_argument("--keep", action="store_true", help="跑完不清理")
    ap.add_argument("--skip-roster", action="store_true",
                    help="故意不补名册（演示 干员 rc=3 那一态）")
    a = ap.parse_args()

    sha = a.sha or head_sha()
    if git("cat-file", "-t", sha).stdout.strip() != "commit":
        print("PINTREE_BAD_SHA %s" % sha)
        return 3

    print("=== 冻结树整闸 ===")
    print("树      ：%s" % sha)
    print("冻结树  ：%s" % WT)
    print("开始    ：%s" % datetime.now().isoformat(timespec="seconds"))

    # 1) 建树（detached；**不建任何 junction**）
    if WT.exists():
        cleanup(False)
    if git("worktree", "add", "--detach", str(WT), sha).returncode != 0:
        print("PINTREE_WORKTREE_FAILED")
        return 3
    print("  已建冻结树")

    # 2) 拷输入（**复制**，不是链接）
    shutil.copytree(ROOT / "data", WT / "data", dirs_exist_ok=True)
    print("  已复制 data/")
    if a.skip_roster:
        print("  ★ 按参数**故意不补名册** —— 干员那套应当给 rc=3")
    elif ROSTER.is_file():
        shutil.copy2(ROSTER, WT / "docs" / ROSTER.name)
        print("  已补名册 %s" % ROSTER.name)
    else:
        print("  ★ 名册不在本机（%s）—— 干员那套会给 rc=3" % ROSTER)

    # 3) 在树里自己 build；仪器只用这一枚
    b = run(["go", "build", "-o", str(WT / "out" / "acceptance" / "rios-sim-stage3.exe"), "."],
            cwd=WT / "rios-sim")
    if b.returncode != 0:
        print("PINTREE_BUILD_FAILED rc=%d\n%s" % (b.returncode, (b.stderr or b.stdout)[:400]))
        cleanup(a.keep)
        return 3
    exe = WT / "out" / "acceptance" / "rios-sim-stage3.exe"
    sha16 = hashlib.sha256(exe.read_bytes()).hexdigest()[:16]
    print("  已 build；仪器 sha256(16)=%s" % sha16)
    print("  ⚠ 这个 sha 是**构建身份**（换目录就会变），**不是源码身份**——见 docs/gate-readings.md")

    # 4) 跑整闸
    env = {**os.environ, "RIOS_SIM_BIN": str(exe)}
    log = ROOT / "out" / ("pinned-gate-%s.log" % sha[:7])
    r = run([sys.executable, "-X", "utf8", "tools/check_go_all.py", "--selfcheck"],
            cwd=WT, env=env)
    log.write_text(r.stdout + r.stderr, encoding="utf-8")

    lines = [l for l in r.stdout.splitlines() if l.startswith("结论：") or "守卫全部" in l
             or l.startswith("✗")]
    print()
    print("结果    ：rc=%d" % r.returncode)
    for l in lines[-4:]:
        print("  %s" % l.strip())
    print("留证    ：%s" % log.relative_to(ROOT))
    print("结束    ：%s" % datetime.now().isoformat(timespec="seconds"))

    cleanup(a.keep)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
