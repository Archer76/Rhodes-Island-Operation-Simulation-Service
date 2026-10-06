# -*- coding: utf-8 -*-
"""把 R.I.O.S. 打成**拆分目录**（迁移图 §12.2）。

判据（§12.6）：**一个文件进包 ⟺ 删掉它，程序跑不起来、或首次运行走不下去。**
逐个候选问一遍「删掉它会怎样」，答不出后果的一律不进包。所以这里进包的只有：

    rios-tui.exe        界面本体，也是**唯一入口**（删了没有入口）
    rios-sim.exe        引擎（界面是**子进程**调它）
    eng/ak_tactic/      登录／名册／建库走 Python 子进程（§11.4）
    eng/tools/*.py      桥与首次运行第 3 步要用的那几个（见 REQUIRED_TOOLS）

不进包：`docs/` 全树、`tools/` 的全部判据、`fixtures/`、`out/`、Go 源码、
仓根文件、`data/`（玩家自取）、Python 运行时（玩家自装）。

## 为什么不再写 `启动.cmd`（博士 2026-09-27 裁，迁移图 §12.9）

原先那个壳只干三件事，其中两件在 Go 里**早已解决**：

1. **`cd /d "%~dp0"` —— 不需要**：路径解析三处全走 `os.Executable()`
   （`main.go` 的 `dataDirCandidates`／`engclient.go` 的 `findBridgeScript`／
   `engpipe.go` 的 `findEngineExe`），cwd 在哪都不影响取数与找桥。
2. **先 `-setup` 再起界面 —— 不需要壳**：`-setup` 是**同一个程序自己的参数**，
   而 `main.go` 在无参数时（`flag.NFlag()==0`）自己先跑一遍准备（判据是纯函数
   `shouldAutoSetup`）。壳去串"两步"这件事本身多余。
3. **`chcp 65001` 与失败时 `pause` —— 已进 Go**：`console_windows.go` 用 syscall 调
   kernel32 的 `Set/GetConsoleOutputCP` 把代码页切成 UTF-8、退出前恢复原值；
   `pauseIfInteractive` 只在 stdin 是字符设备时停（管道／重定向不停，判据友好）。

⇒ 双击 `rios-tui.exe` 就是入口，**发布形态里不再有启动器这类中间件**。所以本文件
既不生成它，`smoke()` 里那条「`-setup` 必须在裸 exe 之前」的**顺序断言也一并删掉**
（没有 .cmd 可断言了）；那条性质改由「缺 `eng/` 时 `rios-tui.exe -setup` 必须具名
失败且非零退出」来守 —— 后者验的是**程序自己**的行为，比验一份脚本文本更结实。

## 发布边界

1. 玩家首次运行只建干员库、关卡索引、敌人库；`fetch_prts_notes.py` 是内部件，
   不属于 REQUIRED_TOOLS，也不随包分发。运行时必须文件缺失仍须当场具名失败。
2. **发布树的数据根是 `eng/data/`，不是 `<发布根>/data/`**。Python 侧的
   `DEFAULT_DB_PATH`／名册路径是**硬编码**的 `parents[2]/data`（`ak_tactic/db/build.py:40`、
   `ak_tactic/tui/data.py:239`），而 `ak_tactic` 在 `eng/` 下 ⇒ `parents[2]` 就是 `eng/`。
   Go 侧跟着 `RIOS_DB` 走，且 `dataDirCandidates()` 已经把 `eng/data` 列进候选
   （2026-09-27 加），所以两侧指向同一处。

用法：

    python tools/build_release.py --version v0.3.0
    python tools/build_release.py --version v0.3.0 --out D:\\tmp\\rel
    python tools/build_release.py --version v0.3.0 --no-selftest   # 跳过全量自检（快）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    from .selftest_gate import validate_selftest
except ImportError:  # direct script execution
    from selftest_gate import validate_selftest

ROOT = Path(__file__).resolve().parents[1]

#: 进包的运行时文件（§12.6 那张表）。名字后面写清「删掉它会怎样」。
REQUIRED_TOOLS = {
    "rios_bridge.py": "登录／名册那条链的桥（§11.4）——删了这三件事全废",
    "rebuild_data.py": "首次运行第 3 步要跑它（§12.5）",
    "operbox_path.py": "名册的降级来源（OperBox 位置）；ak_tactic/tui/data.py 按路径加载它",
    #: ⚠ `fetch_prts_notes.py` **不进包**（2026-09-27 起）：它只被 `rebuild_data.py` 的
    #: 「干员备注库」那一步用（`tools/rebuild_data.py` 里它是那一步的 argv），
    #: 而玩家的一键流程现在只跑三步（干员库／关卡索引／敌人库，见
    #: `rios-sim/cmd/rios-tui/setup.go` 的 `playerSteps`）—— 备注语料 Go 与 Python 的
    #: 产品路径**零命中**，只有判据与开发审计用得上。§12.6 的判据是「删掉它程序跑不起来吗」：
    #: 对玩家那条路，答案是"跑得起来"。开发要用它，仓库里有。
}

def sh(cmd, cwd=None, timeout=None, stdin_nul=False, env=None):
    """跑一条命令并把两条流都收回来（检查类脚本**零重定向**）。

    `stdin_nul` 把 stdin 接到 NUL：入口在真终端里会 `pauseIfInteractive` 停住等按键
    （那是给双击的人看的），接 NUL 就不是字符设备 ⇒ 它不停 ——
    这正是"入口能不能被自动验"的关键。
    `env` 用来给某一条判据换一份环境（例如摘掉 `RIOS_DB`，见 `smoke()`）。
    """
    kw = {}
    if stdin_nul:
        kw["stdin"] = subprocess.DEVNULL
    if env is not None:
        kw["env"] = env
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
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {"RIOS_DB", "RIOS_DATA", "RIOS_SIM_BIN", "RIOS_BRIDGE", "RIOS_PYTHON", "PYTHONPATH", "PYTHONHOME"}}
    jobs = [
        (["go", "build", "-trimpath", "-ldflags", ldflags, "-o", str(tree / "rios-sim.exe"), "."],
         ROOT / "rios-sim"),
        (["go", "build", "-trimpath", "-ldflags", ldflags, "-o", str(tree / "rios-tui.exe"),
          "./cmd/rios-tui"], ROOT / "rios-sim"),
    ]
    for cmd, cwd in jobs:
        rc, out, err = sh(cmd, cwd=cwd, env=env)
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
        lines.append("  处置：恢复上面点名的运行时文件后重新构建；内部备注抓取工具不属于玩家运行时。")
        die("\n".join(lines))


def assert_only_runtime_files(tree: Path) -> list:
    """判据（§12.6）：树里除了运行时必须的那几件，不许有别的东西。

    这条是**反着判**的：白名单之外的任何文件都要拦下来 —— 否则「顺手把 docs 拷进来」
    或「把 out/ 拖进来」不会被任何人发现。
    """
    allowed_exact = {"rios-tui.exe", "rios-sim.exe", "SHA256SUMS.txt", "verification.json"}
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
        if len(rel.parts) == 1 and rel.suffix.lower() in (".cmd", ".bat"):
            #: 入口已经是 `rios-tui.exe` 自己（§12.9），所以这一族文件回来就是**回归**。
            #: 单独具名是为了让下一个看到红的人一眼知道"这不是漏拷了一个文件"。
            bad.append((rel, "启动器已取消（博士 2026-09-27 裁，迁移图 §12.9）——"
                            "入口是 rios-tui.exe 自己，不再有 .cmd/.bat 这一类中间件"))
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


def release_env(tree: Path, *, data_dir: Path | None = None, pin: bool = True) -> dict:
    """Discard inherited component/data overrides before testing this package."""
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {"RIOS_DB", "RIOS_DATA", "RIOS_SIM_BIN", "RIOS_BRIDGE", "RIOS_PYTHON", "PYTHONPATH", "PYTHONHOME"}}
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", RIOS_PYTHON=sys.executable)
    if pin:
        env["RIOS_SIM_BIN"] = str((tree / "rios-sim.exe").resolve())
        env["RIOS_BRIDGE"] = str((tree / "eng/tools/rios_bridge.py").resolve())
    if data_dir is not None:
        env["RIOS_DB"] = str(data_dir.resolve())
        env["RIOS_DATA"] = str((data_dir / "gamedata").resolve())
    return env


def component_identity(tree: Path) -> dict:
    """Exercise exact package components offline; fingerprints identify the bytes."""
    env = release_env(tree)
    components = {}
    for name, rel, argv, payload, version_key in (
        ("engine", "rios-sim.exe", [str((tree / "rios-sim.exe").resolve())], "pong", "version"),
        ("bridge", "eng/tools/rios_bridge.py", [sys.executable, "-I", str((tree / "eng/tools/rios_bridge.py").resolve())], None, "proto"),
    ):
        path = (tree / rel).resolve()
        if not path.is_file():
            die("包内组件缺失：%s" % path)
        before = sha256(path)
        try:
            p = subprocess.run(argv, input='{"id":719,"cmd":"ping"}\n', cwd=tree,
                               env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="strict", timeout=30)
        except (OSError, UnicodeError, subprocess.TimeoutExpired):
            die("包内 %s 身份握手无法完成（启动／编码／超时错误，原始日志不输出）" % name)
        try:
            lines = p.stdout.splitlines()
            reply = json.loads(lines[0]) if len(lines) == 1 else None
            body = reply.get(payload) if payload and isinstance(reply, dict) else reply
            if p.returncode != 0 or not isinstance(reply, dict) or reply.get("id") != 719 or reply.get("ok") is not True:
                raise ValueError("invalid ping envelope/exit")
            if not isinstance(body, dict) or body.get(version_key) != 1:
                raise ValueError("unexpected component protocol")
            if sha256(path) != before:
                raise ValueError("component changed during probe")
        except (ValueError, TypeError, IndexError) as exc:
            die("包内 %s 身份握手失败：%s；rc=%d（原始响应／日志可能包含账号信息，不输出）" % (name, exc, p.returncode))
        # Do not publish bridge UID/credential state or engine start timestamp.
        components[name] = {"relative_path": rel, "resolved_path": str(path),
                            "sha256": before, "size": path.stat().st_size,
                            "protocol": body[version_key], "ping_id": 719,
                            "runtime": {k: body[k] for k in ("go", "os", "arch", "python", "impl") if k in body}}
    return {"schema_version": 1, "components": components}


def run_preflight(tree: Path):
    """在**发布树里**跑启动前自检（cwd 就是树本身，免得读到开发树的东西）。

    ★ 这一条问的是"**这棵树自己**缺不缺件"，所以显式摘掉 `RIOS_DB`：
    本机环境变量一进来，开发树的库就会被当成"在位"，全新树的读数直接变假绿。
    """
    env = release_env(tree, pin=False)
    rc, out, err = sh([str(tree / "rios-tui.exe"), "-preflight"], cwd=tree, timeout=300,
                      env=env)
    return rc, out + err


def smoke(tree: Path, data_dir: Path | None) -> dict:
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

    #: 入口自己也要真跑一次 —— 但**不能**跑"数据齐全之前"那种会去下载的路径：
    #: 无参数运行会先跑 `-setup`，而空树上它会真的开始取 94 MB 数据（上一版撞了 300 秒超时）；
    #: 直接跑界面更不行 —— 实测以 NUL 作 stdin 起 TUI 会**挂住**（bubbletea 无 TTY 不退出）。
    #: 所以换个问法：**把 `eng/` 拿掉 ⇒ `-setup` 找不到那条重建命令，必须当场具名失败、
    #: 非零退出**。这一条同时守三件事：
    #:   ① 缺件要具名（§12.6 的口径，不许静默退化成"跑一半才炸"）；
    #:   ② 缺件时**不许**返回 0（否则入口会接着去起界面）；
    #:   ③ stdin 是 NUL（不是字符设备）时**不许暂停** —— 若它停了，这里会直接撞超时炸掉，
    #:      所以"在超时以内返回了"本身就是"没暂停"的读数。
    #: （旧的「顺序断言：-setup 在裸 rios-tui.exe 之前」随 `启动.cmd` 一起删掉：没有 .cmd
    #:   就没有那份文本可断言了；等价性质现在落在下面这条，且验的是程序自己而非脚本。）
    print("  · 入口 rios-tui.exe -setup：缺 eng/ 时必须具名失败（stdin 接 NUL，不许暂停）")
    # Negative controls must discover missing package files, never external overrides.
    env_setup = release_env(tree, pin=False)
    eng_dir2 = tree / "eng"
    bak_dir2 = tree / "eng.bak2"
    eng_dir2.rename(bak_dir2)
    try:
        t0 = time.monotonic()
        rc4, out4, err4 = sh([str(tree / "rios-tui.exe"), "-setup"], cwd=tree,
                             timeout=300, stdin_nul=True, env=env_setup)
        dt4 = time.monotonic() - t0
    finally:
        bak_dir2.rename(eng_dir2)
    if rc4 == 0:
        die("少了 eng/ 时 `-setup`**不该**返回 0（它应当停下来并说明）")
    txt4 = out4 + err4
    if "首次运行准备" not in txt4:
        die("`-setup` 没报准备计划（输出里没有「首次运行准备」）：\n%s" % txt4[-1200:])
    #: 具名说法的两条：机器上有 Python ⇒ 走到"找不到工程侧脚本"；没有 ⇒ 报"没有可用的
    #: Python"。两条都是**具名**的，都算过；一条都没有才是"没说清缺什么"。
    named = [s for s in ("找不到工程侧脚本", "没有可用的 Python") if s in txt4]
    if not named:
        die("缺 eng/ 时 `-setup` 没有具名说出缺在哪（两条具名说法都不在输出里）：\n%s"
            % txt4[-1200:])
    print("      实得 rc=%d（%.1fs 内返回 ⇒ 没暂停），具名说法：%s"
          % (rc4, dt4, named[0]))

    if data_dir is None:
        print("  · 发布验收 unverified：--no-selftest 明确跳过 required 自检；构建不等于验收")
        return {"status": "unverified", "reason": "--no-selftest: required selftest not run"}
    if not (data_dir / "akdb.sqlite").is_file():
        die("发布验收拒绝：required prerequisites 缺数据 %s/akdb.sqlite；不允许静默跳过" % data_dir)

    print("  · 发布树的 exe 跑全量自检（RIOS_DB 指到本机数据，只为把界面跑起来）")
    env = release_env(tree, data_dir=data_dir)
    p = subprocess.run([str(tree / "rios-tui.exe"), "-selftest"], cwd=tree, env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    try:
        manifest = json.loads((ROOT / 'tools' / 'selftest_manifest.json').read_text(encoding='utf-8'))
        report = validate_selftest(p.stdout or '', p.returncode, manifest)
    except (OSError, ValueError) as exc:
        die('发布验收拒绝：%s\nstdout:\n%s\nstderr（仅诊断，不参与gate）:\n%s'
            % (exc, (p.stdout or '')[-3000:], (p.stderr or '')[-3000:]))
    print('      发布验收 verified：所有静态 required cases 完整、通过且实际行使')
    return {'status': 'verified', 'reason': 'all-required machine report validated', 'report': report}


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

    print("[1/5] 建两个 exe")
    build_exes(tree)

    print("[2/5] 拷工程侧 Python 到 eng/")
    copy_eng(tree)

    print("[3/5] 判据：树里只有运行时必须的文件（§12.6）")
    files = assert_only_runtime_files(tree)
    print("      树里共 %d 个文件，全部在白名单内（入口 rios-tui.exe 自己；无 .cmd）"
          % len(files))

    print("[4/5] 装完自查（正例 ＋ 两条负对照 ＋ 入口缺件那条）")
    data_dir = ROOT / "data"
    identity = component_identity(tree)
    verification = smoke(tree, None if args.no_selftest else data_dir)
    # A build bypass is never a verified release, even if a future smoke refactor
    # accidentally returns a green value. Normal verified status comes only from gate.
    if args.no_selftest:
        verification = {"status": "unverified", "reason": "--no-selftest: required selftest not run"}
    verification["identity"] = identity
    (tree / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("[5/5] 清掉自查留下的 Python 编译缓存，然后逐件点名 sha256")
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
    print("构建：完成（rc=0）。构建完成与发布验收是不同结论。")
    print("发布验收：%s —— %s" % (verification["status"], verification["reason"]))
    return 0


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return str(n)


if __name__ == "__main__":
    sys.exit(main())
