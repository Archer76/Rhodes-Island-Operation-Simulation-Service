# -*- coding: utf-8 -*-
"""编译安装器，并把判据 7 的**四件**逐件验成读数。

四件（迁移图 §12.5）：
  1. **依赖自检**：装完就能用启动器自查，缺件**具名**（不是跑到一半才炸）；
  2. **不覆盖已有 `data/`**：玩家自己取过数据就不许动它；
  3. **卸载干净**：程序文件走干净，而玩家的数据**先问再删**（无人值守时不弹框、按保留处理）；
  4. **可重复安装／升版本**：就地覆盖，第二次装照样成功。

另外两条顺带验的（都来自已定裁定）：
  · **`SHA256SUMS.txt` 不进包**（§12.6：删掉它程序照样跑 ⇒ 不是运行时必须）；
  · 安装器产物**逐件点名 sha256**（目标里明写的一条纪律）。

判据一律**自己造对照**：先造一棵"已经有 data 的旧安装"，再装，看那份数据还在不在 ——
"不被覆盖"这种性质，只有在**存在**被覆盖的机会时才是可判的。

用法：
    python tools/build_installer.py --version 0.3.0
    python tools/build_installer.py --version 0.3.0 --no-smoke    # 只编译
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "tools" / "rios_setup.iss"

#: ISCC 的位置：winget 装的是**用户级**（与安装器自身 PrivilegesRequired=lowest 一致）。
ISCC_CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
]


def die(msg: str) -> None:
    print("★ " + msg)
    sys.exit(1)


def sh(cmd, cwd=None, timeout=None, stdin_nul=False):
    kw = {"stdin": subprocess.DEVNULL} if stdin_nul else {}
    p = subprocess.run([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, **kw)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def find_iscc() -> Path:
    for p in ISCC_CANDIDATES:
        if p.is_file():
            return p
    die("找不到 ISCC.exe。装一个：winget install --id JRSoftware.InnoSetup -e")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compile_installer(version: str, tree: Path) -> Path:
    iscc = find_iscc()
    rc, out, err = sh([iscc, f"/DAppVersion={version}", f"/DSrcDir={tree}", ISS],
                      timeout=1800)
    print("      ISCC rc=%d" % rc)
    if rc != 0:
        die("编译失败：\n%s%s" % (out[-2000:], err[-2000:]))
    #: OutputDir 在 .iss 里是相对它自己的 `..\out\release`
    exe = ROOT / "out" / "release" / ("RIOS-Setup-%s.exe" % version)
    if not exe.is_file():
        die("编译说成功了，但 %s 不在" % exe)
    return exe


def install(exe: Path, target: Path, log: Path):
    return sh([exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
               "/NOCANCEL", f"/DIR={target}", f"/LOG={log}"], timeout=1800)


def uninstall(target: Path, log: Path):
    un = target / "unins000.exe"
    if not un.is_file():
        return 1, "", "找不到卸载器 %s" % un
    return sh([un, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={log}"],
              timeout=1800)


def smoke(version: str, exe: Path) -> None:
    """装 → 查 → 卸 → 再装。每一步都要有读数或者具名失败。"""
    work = Path(tempfile.mkdtemp(prefix="rios-installer-"))
    target = work / "RIOS"
    #: ★ 对照：先造一份"玩家自己取的数据"。没有被覆盖的机会时，「不覆盖」是不可判的。
    marker = target / "eng" / "data" / "玩家自己取的数据.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("这一行必须活过安装与卸载\n", encoding="utf-8")
    print("  · 对照夹具：先摆一份 eng\\data 里的玩家数据（%s）" % marker.name)

    print("  · 第一次安装（静默，装到临时目录）")
    rc, out, err = install(exe, target, work / "install1.log")
    if rc != 0:
        die("安装失败（rc=%d）：\n%s%s\n日志：%s" % (rc, out[-1500:], err[-1500:],
                                              work / "install1.log"))
    print("      实得 rc=0")

    want = ["rios-tui.exe", "rios-sim.exe", "启动.cmd",
            "eng/ak_tactic/__init__.py", "eng/tools/rios_bridge.py"]
    missing = [w for w in want if not (target / w).is_file()]
    if missing:
        die("装完缺文件：%s" % missing)
    print("      运行时该有的都在（%d 件点名过）" % len(want))

    if (target / "SHA256SUMS.txt").exists():
        die("SHA256SUMS.txt 进了安装包 —— §12.6 的判据是「删掉它程序跑不起来吗」，它不该进")
    print("      SHA256SUMS.txt 没进包（§12.6）")

    if not marker.is_file():
        die("玩家的 eng\\data 被安装覆盖/删掉了 —— 判据 7 第 2 件不成立")
    print("      玩家数据活过了安装（判据 7 第 2 件）")

    print("  · 装完自查（缺件要具名，不是跑到一半才炸）")
    #: ⚠ **不要**在这里跑 `启动.cmd`：它现在的第一步是 `-setup`，而空树上 `-setup`
    #: 会**真的去下载** 94 MB 数据 —— 那会把这条冒烟变成十几分钟（上一版就是撞了超时）。
    #: 所以分成两问：能不能自己说清缺什么（跑 `-preflight`），以及接线对不对（内容断言）。
    rc2, out2, err2 = sh([str(target / "rios-tui.exe"), "-preflight"], cwd=target,
                         timeout=600)
    text = out2 + err2
    if "启动前自检" not in text:
        die("预检没打印报告（rc=%d）：\n%s" % (rc2, text[-1500:]))
    if "★ 缺" in text:
        die("这棵临时树上引擎与 eng/ 都在，不该有致命缺件：\n%s" % text[-1500:])
    if "起不来" not in text and "待办" not in text:
        die("没有派生库时应当报「起不来」或「待办」，实得：\n%s" % text[-1500:])
    print("      实得 rc=%d，报告里点了名（致命缺件 0 件）" % rc2)

    cmd_text = (target / "启动.cmd").read_text(encoding="utf-8", errors="replace")
    i_setup = cmd_text.find("-setup")
    i_ui = cmd_text.find("rios-tui.exe", i_setup + 1)
    if i_setup < 0 or i_ui < 0:
        die("启动器里找不到「先 -setup 再起界面」这两步：\n%s" % cmd_text)
    print("      启动器接线：-setup 在裸 rios-tui.exe 之前 ✓")

    print("  · 静默卸载（玩家数据不许被带走，且不许弹框挂住）")
    rc3, out3, err3 = uninstall(target, work / "uninstall1.log")
    if rc3 != 0:
        die("卸载失败（rc=%d）：\n%s%s\n日志：%s" % (rc3, out3[-1500:], err3[-1500:],
                                              work / "uninstall1.log"))
    print("      实得 rc=0")
    if (target / "rios-tui.exe").exists():
        die("卸载之后 rios-tui.exe 还在 —— 判据 7 第 3 件不成立")
    print("      程序文件走干净了（判据 7 第 3 件）")
    if not marker.is_file():
        die("静默卸载把玩家的 eng\\data 删了 —— 静默应当按「保留」处理")
    print("      玩家数据留下了（静默卸载不弹框、按保留处理）")

    print("  · 第二次安装（可重复安装／升版本）")
    rc4, out4, err4 = install(exe, target, work / "install2.log")
    if rc4 != 0:
        die("第二次安装失败（rc=%d）：\n%s%s" % (rc4, out4[-1500:], err4[-1500:]))
    if not (target / "rios-tui.exe").is_file():
        die("第二次装完 rios-tui.exe 不在")
    print("      实得 rc=0，装回去了（判据 7 第 4 件）")

    print("  · 收尾：再卸一次并把临时目录清掉")
    rc5, _, _ = uninstall(target, work / "uninstall2.log")
    if rc5 != 0:
        print("      （第二次卸载 rc=%d，收尾不判红；现场留在 %s）" % (rc5, work))
        return
    shutil.rmtree(work, ignore_errors=True)
    print("      清掉了")


def main() -> int:
    ap = argparse.ArgumentParser(description="编译并验证 R.I.O.S. 安装器")
    ap.add_argument("--version", required=True, help="版本号，如 0.3.0（不带 v）")
    ap.add_argument("--tree", default=None, help="拆分发布树（缺省 out/release/rios-v<版本>）")
    ap.add_argument("--no-smoke", action="store_true", help="只编译，不做装卸冒烟")
    args = ap.parse_args()

    tree = Path(args.tree) if args.tree else ROOT / "out" / "release" / ("rios-v" + args.version)
    if not (tree / "rios-tui.exe").is_file():
        die("发布树不对：%s 里没有 rios-tui.exe（先跑 build_release.py）" % tree)

    print("[1/2] 编译安装器（版本 %s）" % args.version)
    exe = compile_installer(args.version, tree)
    size = exe.stat().st_size
    print("      产物 %s  %d 字节" % (exe.name, size))
    print("      sha256 %s" % sha256(exe))

    if args.no_smoke:
        print("[2/2] 跳过装卸冒烟（--no-smoke）")
        return 0
    print("[2/2] 装 → 查 → 卸 → 再装（四件逐件验）")
    smoke(args.version, exe)
    print()
    print("判据 7 的四件全部有读数；产物 %s（%d 字节，sha256 见上）" % (exe.name, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
