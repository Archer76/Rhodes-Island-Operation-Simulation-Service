# -*- coding: utf-8 -*-
"""把 R.I.O.S. 打成**拆分目录**（迁移图 §12.2）＋ 写出 `启动.cmd`。

判据（§12.6）：**一个文件进包 ⟺ 删掉它，程序跑不起来、或首次运行走不下去。**
逐个候选问一遍「删掉它会怎样」，答不出后果的一律不进包。所以这里进包的只有：

    rios-tui.exe        界面本体（删了没有入口）
    rios-sim.exe        引擎（界面是**子进程**调它）
    启动.cmd            一键入口，且启动器自检落在它身上（§12.3）
    eng/ak_tactic/      登录／名册／建库走 Python 子进程（§11.4）
    eng/tools/*.py      桥与首次运行第 3 步要用的那几个（见 REQUIRED_TOOLS）

不进包：`docs/` 全树、`tools/` 的全部判据、`fixtures/`、`out/`、Go 源码、
仓根文件、`data/`（玩家自取）、Python 运行时（玩家自装）。

## 三件必须记在这里的事（都会让包"装出来才炸"）

1. **`tools/fetch_prts_notes.py` 不在 git 索引里**（它是内部件，被 `.gitignore` 摘出过），
   而首次运行第 3 步要用它 ⇒ 只能从**工作树**取。缺了必须**当场具名报错**，
   不许"照 git ls-files 找、找不到就少一件"（那正是 §12.3 要防的形状）。
2. **发布树的数据根是 `eng/data/`，不是 `<发布根>/data/`**。Python 侧的
   `DEFAULT_DB_PATH`／名册路径是**硬编码**的 `parents[2]/data`（`ak_tactic/db/build.py:40`、
   `ak_tactic/tui/data.py:239`），而 `ak_tactic` 在 `eng/` 下 ⇒ `parents[2]` 就是 `eng/`。
   Go 侧跟着 `RIOS_DB` 走，且 `dataDirCandidates()` 已经把 `eng/data` 列进候选
   （2026-09-27 加），所以两侧指向同一处。
3. **`启动.cmd` 保持纯 ASCII**：cmd.exe 是按**当前代码页**逐行读批处理的，
   `chcp 65001` 生效前的行若含中文就会变乱码。给玩家看的中文一律由 `rios-tui.exe
   -preflight` 打印（那一步已经 chcp 过了）。

用法：

    python tools/build_release.py --version v0.3.0
    python tools/build_release.py --version v0.3.0 --out D:\\tmp\\rel
    python tools/build_release.py --version v0.3.0 --no-selftest   # 跳过全量自检（快）
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: 进包的运行时文件（§12.6 那张表）。名字后面写清「删掉它会怎样」。
REQUIRED_TOOLS = {
    "rios_bridge.py": "登录／名册那条链的桥（§11.4）——删了这三件事全废",
    "rebuild_data.py": "首次运行第 3 步要跑它（§12.5）",
    "fetch_prts_notes.py": "首次运行第 3 步要跑它（§12.5）；★ 不在 git 索引里，只能从工作树取",
    "operbox_path.py": "名册的降级来源（OperBox 位置）；ak_tactic/tui/data.py 按路径加载它",
}

#: `启动.cmd`。纯 ASCII、CRLF、无 BOM —— 三条都是 cmd.exe 的脾气，不是风格。
LAUNCHER = "\r\n".join([
    "@echo off",
    "rem R.I.O.S. launcher - double-click this file.",
    "rem Keep this file ASCII-only: cmd.exe parses a batch file with the *current*",
    "rem code page, so non-ASCII above the chcp line would come out as mojibake.",
    "rem All player-facing text comes from 'rios-tui.exe -preflight'.",
    "chcp 65001 >nul",
    'cd /d "%~dp0"',
    #: 别让 Python 往安装目录里写 __pycache__：装到 Program Files 之类没写权限的地方时
    #: 那些写失败是无害的噪音，但会把目录弄脏（哈希清单、卸载残留都要跟着解释）。
    "set PYTHONDONTWRITEBYTECODE=1",
    #: 先跑首次运行准备：缺数据／缺派生库就自动补（装 Python 会问一句），
    #: 什么都不缺时它一个字节都不打印、立刻返回 —— 所以每次启动都调它是安全的。
    "rios-tui.exe -setup",
    "if errorlevel 1 (",
    "  echo.",
    "  echo Setup did not finish - read the messages above.",
    "  echo Press any key to close.",
    "  pause >nul",
    "  exit /b 1",
    ")",
    "rios-tui.exe",
    "set RIOS_RC=%ERRORLEVEL%",
    'if not "%RIOS_RC%"=="0" (',
    "  echo.",
    '  echo The UI exited with code %RIOS_RC%.',
    "  echo Press any key to close.",
    "  pause >nul",
    ")",
    "exit /b %RIOS_RC%",
    "",
])


def sh(cmd, cwd=None, timeout=None, stdin_nul=False):
    """跑一条命令并把两条流都收回来（检查类脚本**零重定向**）。

    `stdin_nul` 把 stdin 接到 NUL：批处理里那句 `pause` 在无人值守时会一直等，
    接 NUL 就立刻返回（这正是"启动器能不能被自动验"的关键）。
    """
    kw = {}
    if stdin_nul:
        kw["stdin"] = subprocess.DEVNULL
    p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       **kw)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def die(msg):
    print("★ " + msg)
    sys.exit(1)


def build_exes(tree: Path) -> None:
    """建两个 exe。`-trimpath -ldflags "-s -w"` 与 v0.2.0 发布附件同口径。"""
    ldflags = "-s -w"
    jobs = [
        (["go", "build", "-trimpath", "-ldflags", ldflags, "-o", str(tree / "rios-sim.exe"), "."],
         ROOT / "rios-sim"),
        (["go", "build", "-trimpath", "-ldflags", ldflags, "-o", str(tree / "rios-tui.exe"),
          "./cmd/rios-tui"], ROOT / "rios-sim"),
    ]
    for cmd, cwd in jobs:
        rc, out, err = sh(cmd, cwd=cwd)
        if rc != 0:
            die("构建失败（%s）：\n%s%s" % (" ".join(cmd[-1:]), out, err))
        print("    建好 %s" % Path(cmd[cmd.index("-o") + 1]).name)


def copy_eng(tree: Path) -> None:
    """把工程侧 Python 拷成 `eng/`。"""
    eng = tree / "eng"
    #: ① ak_tactic 整包（§12.6 那张表写的是「至少 ak_tactic/」；
    #:    能瘦到哪一步还没量过 —— 迁移图 §12.6 末尾已登记为未核项，
    #:    所以这里取**上界**，宁可多带几个模块，也不要装出来缺一个 import）。
    src = ROOT / "ak_tactic"
    if not src.is_dir():
        die("找不到 %s" % src)
    shutil.copytree(src, eng / "ak_tactic",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))

    #: ② tools 里运行时必须的那几个
    (eng / "tools").mkdir(parents=True, exist_ok=True)
    missing = []
    for name, why in REQUIRED_TOOLS.items():
        p = ROOT / "tools" / name
        if not p.is_file():
            missing.append((name, why, p))
            continue
        shutil.copy2(p, eng / "tools" / name)
    if missing:
        lines = ["运行时必须的 Python 文件缺失（打包不能静默少一件）："]
        for name, why, p in missing:
            lines.append("  · %s（%s）" % (name, why))
            lines.append("    找过：%s" % p)
        #: ★ 这一条是 §12.6 点名要登记的：fetch_prts_notes.py 是**内部件**，
        #: 不在 git 索引里 ⇒ 干净克隆里没有它，必须从本机工作树取。
        lines.append("  处置：fetch_prts_notes.py 属内部件（.gitignore 摘出），"
                     "干净克隆里本来就没有；打包必须在有它的工作树上做。")
        die("\n".join(lines))


def write_launcher(tree: Path) -> None:
    (tree / "启动.cmd").write_bytes(LAUNCHER.encode("ascii"))


def assert_only_runtime_files(tree: Path) -> list:
    """判据（§12.6）：树里除了运行时必须的那几件，不许有别的东西。

    这条是**反着判**的：白名单之外的任何文件都要拦下来 —— 否则「顺手把 docs 拷进来」
    或「把 out/ 拖进来」不会被任何人发现。
    """
    allowed_exact = {"rios-tui.exe", "rios-sim.exe", "启动.cmd", "SHA256SUMS.txt"}
    bad = []
    files = []
    for p in sorted(tree.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(tree)
        files.append(rel)
        if rel.parts[0] == "eng":
            if "__pycache__" in rel.parts or rel.suffix in (".pyc", ".pyo"):
                bad.append((rel, "编译缓存，运行时用不着"))
            continue
        if len(rel.parts) == 1 and rel.name in allowed_exact:
            continue
        bad.append((rel, "不在运行时必须的白名单里（§12.6 判据：删掉它程序跑不起来吗）"))
    if bad:
        lines = ["发布树里有不该进包的东西："]
        for rel, why in bad:
            lines.append("  · %s —— %s" % (rel, why))
        die("\n".join(lines))
    return files


def clean_pycache(tree: Path) -> int:
    """清掉 Python 编译缓存（`__pycache__` / `*.pyc`）。

    ★ 为什么非清不可：装完自查那一步会**真的起一次桥**（`-preflight` 的握手），
    而 Python 一旦 import `ak_tactic` 就会在**发布树里**写出 `__pycache__`。
    于是"自查通过"与"树是干净的"两件事互相打架 —— 上一版就是这样：
    自查全绿，紧接着第 6 步判据说树里有 6 个 .pyc。

    清掉是对的（那些文件是**可重建**的，判据 §12.6：删掉它程序照样跑），
    而且哈希清单必须在**清完之后**算 —— 清单描述的是发出去的那棵树。
    """
    n = 0
    for p in list(tree.rglob("__pycache__")):
        if p.is_dir():
            shutil.rmtree(p)
            n += 1
    for p in list(tree.rglob("*.pyc")) + list(tree.rglob("*.pyo")):
        if p.is_file():
            p.unlink()
            n += 1
    return n


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_preflight(tree: Path):
    """在**发布树里**跑启动器自检（cwd 就是树本身，免得读到开发树的东西）。"""
    rc, out, err = sh([str(tree / "rios-tui.exe"), "-preflight"], cwd=tree, timeout=300)
    return rc, out + err


def smoke(tree: Path, data_dir: Path | None) -> None:
    """装完自己验一遍：一条正例 ＋ 两条负对照（尺子必须先证明它会判红）。"""
    print("  · 正例：全新的树（data 不随包，所以期望是 3 = 起不来，且指出 eng/data）")
    rc, out = run_preflight(tree)
    if rc != 3:
        die("期望 rc=3（缺派生库 ⇒ 界面起不来），实得 rc=%d：\n%s" % (rc, out))
    if "eng/data/gamedata" not in out:
        die("提示里没有指出发布树的数据位置 eng/data/gamedata —— 玩家会放错地方：\n%s" % out)
    if "★ 缺" in out:
        die("全新的树不该有**致命**缺件（引擎与 eng/ 都该在）\n%s" % out)
    print("      实得 rc=3，且提示里点名了 eng/data/gamedata")

    print("  · 负对照一：把引擎改名 ⇒ 必须 rc=2 且点名它")
    eng_exe = tree / "rios-sim.exe"
    bak = tree / "rios-sim.exe.bak"
    eng_exe.rename(bak)
    try:
        rc2, out2 = run_preflight(tree)
    finally:
        bak.rename(eng_exe)
    if rc2 != 2 or "引擎" not in out2:
        die("负对照失败：把引擎拿掉之后应当 rc=2 且点名引擎，实得 rc=%d：\n%s" % (rc2, out2))
    print("      实得 rc=2，报告里点名了引擎")

    print("  · 负对照二：把 eng/ 改名 ⇒ 必须 rc=2 且点名工程侧 Python")
    eng_dir = tree / "eng"
    bak_dir = tree / "eng.bak"
    eng_dir.rename(bak_dir)
    try:
        rc3, out3 = run_preflight(tree)
    finally:
        bak_dir.rename(eng_dir)
    if rc3 != 2 or "工程侧" not in out3:
        die("负对照失败：把 eng/ 拿掉之后应当 rc=2 且点名工程侧 Python，实得 rc=%d：\n%s"
            % (rc3, out3))
    print("      实得 rc=2，报告里点名了工程侧 Python")

    #: 启动器自己也要真跑一次 —— 但**不能**在"数据齐全之前"跑那种会去下载的路径：
    #: 现在 `启动.cmd` 的第一步是 `-setup`，而空树上它会真的开始取 94 MB 数据
    #: （上一版就是这样撞了 300 秒超时）。所以这里换个问法：
    #:   ① 把 `eng/` 拿掉 ⇒ `-setup` 找不到那条重建命令，**当场具名失败**、
    #:      启动器必须停住（同时验到 `.cmd` 里的分支确实是"setup 失败就不启动"）；
    #:   ② 顺序用内容断言钉住（`-setup` 必须在裸 `rios-tui.exe` **之前**）。
    #: ⚠ 未核：装完之后双击真的进界面这一条，只有真终端能验（这里没有 TTY）。
    print("  · 启动器 启动.cmd：真跑一次「准备失败就该停住」那条路（stdin 接 NUL）")
    eng_dir2 = tree / "eng"
    bak_dir2 = tree / "eng.bak2"
    eng_dir2.rename(bak_dir2)
    try:
        rc4, out4, err4 = sh(["cmd", "/c", "启动.cmd"], cwd=tree, timeout=300,
                             stdin_nul=True)
    finally:
        bak_dir2.rename(eng_dir2)
    if rc4 == 0:
        die("少了 eng/ 时启动器**不该**返回 0（它应当停下来并说明）")
    txt4 = out4 + err4
    if "首次运行准备" not in txt4:
        die("启动器没有先跑 -setup（输出里没有「首次运行准备」）：\n%s" % txt4[-1200:])
    print("      实得 rc=%d，且确实先跑了 -setup" % rc4)

    cmd_text = (tree / "启动.cmd").read_text(encoding="utf-8", errors="replace")
    i_setup = cmd_text.find("-setup")
    i_ui = cmd_text.find("rios-tui.exe", i_setup + 1)
    if i_setup < 0 or i_ui < 0:
        die("启动器里找不到「先 -setup 再起界面」这两步：\n%s" % cmd_text)
    print("      顺序断言：-setup 在裸 rios-tui.exe 之前 ✓")

    if data_dir is None:
        print("  · 跳过后半段：没有可用的 data 目录（拿它才跑得动全量自检）")
        return
    if not (data_dir / "akdb.sqlite").is_file():
        print("  · 跳过后半段：%s 里没有 akdb.sqlite" % data_dir)
        return

    print("  · 发布树的 exe 跑全量自检（RIOS_DB 指到本机数据，只为把界面跑起来）")
    env = dict(os.environ)
    env["RIOS_DB"] = str(data_dir)
    env["RIOS_SIM_BIN"] = str(tree / "rios-sim.exe")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([str(tree / "rios-tui.exe"), "-selftest"], cwd=tree, env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    text = (p.stdout or "") + (p.stderr or "")
    ticks = text.count("✓")
    if p.returncode != 0 or "结论：**全绿**" not in text:
        die("发布树的 exe 跑自检不绿（rc=%d，✓=%d）—— 发布树与开发树行为不一致：\n%s"
            % (p.returncode, ticks, text[-3000:]))
    #: ★ 发布树里 ✓ 会比开发树**少 6 条**（实测：216 → 210），少的是：
    #:   · 2 条扫本包 Go 源码的防绕过判据（发布树里没有 .go）；
    #:   · 4 条要真名册的判据（名册缓存在 Python 侧认 `eng/data/skland/`，发布树里没有）。
    #: 所以这里**不盯那个总数**（盯它就会把"环境不同"误判成"少跑了"），
    #: 盯的是**性质**：少跑的每一条都得有具名说法，不许静默消失。
    if ticks < 200:
        die("自检只跑了 %d 条 ⇒ 疑似大面积空跑，不是环境差异：\n%s" % (ticks, text[-3000:]))
    for needle, why in (("读不到本包源码目录", "扫源码的防绕过判据"),
                        ("桥这次取不到名册", "要真名册的那几条")):
        if needle not in text:
            die("发布树自检里少了「%s」，但也没有具名的未核说明 —— "
                "那是**静默少跑**，本仓口径不许：\n%s" % (why, text[-3000:]))
    print("      实得 rc=0，✓=%d（开发树 216；差的 6 条各有具名未核），结论全绿" % ticks)


def main() -> int:
    ap = argparse.ArgumentParser(description="打 R.I.O.S. 的拆分发布目录")
    ap.add_argument("--version", required=True, help="版本号（也是目录名的一部分），如 v0.3.0")
    ap.add_argument("--out", default=str(ROOT / "out" / "release"), help="输出根目录")
    ap.add_argument("--no-selftest", action="store_true", help="跳过全量自检那一段")
    args = ap.parse_args()

    tree = Path(args.out) / ("rios-" + args.version)
    if tree.exists():
        print("清掉旧的 %s" % tree)
        shutil.rmtree(tree)
    tree.mkdir(parents=True)

    print("[1/6] 建两个 exe")
    build_exes(tree)

    print("[2/6] 拷工程侧 Python 到 eng/")
    copy_eng(tree)

    print("[3/6] 写 启动.cmd")
    write_launcher(tree)

    print("[4/6] 判据：树里只有运行时必须的文件（§12.6）")
    files = assert_only_runtime_files(tree)
    print("      树里共 %d 个文件，全部在白名单内" % len(files))

    print("[5/6] 装完自查（正例 ＋ 两条负对照）")
    data_dir = ROOT / "data"
    smoke(tree, None if args.no_selftest else data_dir)

    print("[6/6] 清掉自查留下的 Python 编译缓存，然后逐件点名 sha256")
    n_pyc = clean_pycache(tree)
    print("      清掉 %d 个 __pycache__/*.pyc（可重建；自查那一步真起过桥，Python 会写）"
          % n_pyc)
    lines = []
    for rel in assert_only_runtime_files(tree):
        p = tree / rel
        lines.append("%s  %10d  %s" % (sha256(p), p.stat().st_size, rel.as_posix()))
    (tree / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for ln in lines:
        print("      " + ln)

    total = sum(p.stat().st_size for p in tree.rglob("*") if p.is_file())
    print()
    print("发布树：%s" % tree)
    print("文件 %d 个，合计 %s（含 exe 与 eng/；data/ 与 Python 运行时不随包）"
          % (len(lines), human(total)))
    return 0


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return str(n)


if __name__ == "__main__":
    sys.exit(main())
