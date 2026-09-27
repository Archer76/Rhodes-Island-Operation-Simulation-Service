# -*- coding: utf-8 -*-
"""把发布树打成 **zip**（2026-09-27 博士裁：下版本起发布物就是 zip，不再用安装包）。

## 为什么换

安装器（Inno）能做的事，zip 全都不做：不写注册表、没有开始菜单项、不"卸载"。
博士的裁定是**只要一个压缩包**——解压到哪由玩家定，程序本来就不依赖固定安装位置
（数据根是**树内的** `eng/data/`，见 §12.1 那三条硬事实）。

## 三条设计

1. **顶层一个目录**：zip 里的路径一律是 `rios-<版本>/…`，解开就是一个整齐的文件夹，
   不会把 `eng/`、`rios-tui.exe` 撒到玩家的下载目录里。
2. **排除清单要出声**：`eng/data/`（玩家自己取的数据，几十 MB~上百 MB）、
   `__pycache__/`、`*.pyc`、`*.part` **不进包**；排除了几个文件、多少字节**打印出来**
   —— 静默排除与静默多带一样坏。
   ★ 这一条同时挡住一个真会出事的情形：树里的 `eng/data` 可能是**junction**（开发时
   指向本机 `data/`），`zipfile` 会顺着它把整棵开发数据目录打进去（几百 MB 且内容
   不对）。所以这里**按路径前缀排除**，而不是"看它是不是目录"。
3. **打完自己验一遍**：重新打开 zip，把里面的条目名与"应当有的那些"逐条比
   —— 少了、多了都要报；并单独断言**没有 `eng/data` 前缀**的条目。
   比对器自己配一条负对照（故意漏掉一个名字 ⇒ 必须报差异），否则"没报差异"可能
   只是比对器瞎。

用法：
    python tools/build_zip.py --version v0.3.3 --tree out/release/rios-v0.3.3
    python tools/build_zip.py --version v0.3.3 --tree <树> --out D:\\别的目录
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 不进包的东西（**按相对路径前缀判**，见文件头第 2 条）
EXCLUDE_DIRS = ("eng/data", "data", "eng/__pycache__")
EXCLUDE_SUFFIX = (".pyc", ".part")
#: 名字里带这些目录段的整棵排掉（`__pycache__` 在层层子目录里都有）
EXCLUDE_ANY = ("__pycache__",)


def die(msg: str) -> None:
    print("★ %s" % msg, file=sys.stderr)
    raise SystemExit(1)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect(tree: Path) -> tuple[list[str], list[tuple[str, int]]]:
    """列出「应当进包」的相对路径；顺带报出被排除的那些 `(路径, 字节数)`。"""
    keep: list[str] = []
    dropped: list[tuple[str, int]] = []
    for dirpath, dirnames, filenames in os.walk(tree):
        rel_dir = Path(dirpath).relative_to(tree).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        #: 目录级排除：命中就整棵跳过（`os.walk` 里原地改 dirnames 才是真跳过）
        kept_dirs = []
        for d in sorted(dirnames):
            rel = ("%s/%s" % (rel_dir, d)).lstrip("/")
            if rel in EXCLUDE_DIRS or d in EXCLUDE_ANY:
                n = sum(len(fs) for _dp, _dn, fs in os.walk(Path(dirpath) / d))
                dropped.append((rel + "/", n))
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fn in sorted(filenames):
            rel = ("%s/%s" % (rel_dir, fn)).lstrip("/")
            p = Path(dirpath) / fn
            if rel in EXCLUDE_DIRS or fn.endswith(EXCLUDE_SUFFIX):
                dropped.append((rel, p.stat().st_size))
                continue
            keep.append(rel)
    return keep, dropped


def compare(expected: list[str], got: list[str]) -> tuple[list[str], list[str]]:
    """返回 `(少了, 多了)`。**纯函数**，负对照直接喂它。"""
    exp, g = set(expected), set(got)
    return sorted(exp - g), sorted(g - exp)


def main() -> int:
    ap = argparse.ArgumentParser(description="把发布树打成 zip（发布物＝zip）")
    ap.add_argument("--version", required=True, help="版本号，如 v0.3.3（也是顶层目录名）")
    ap.add_argument("--tree", required=True, help="要打包的发布树（build_release.py 的产物）")
    ap.add_argument("--out", default=str(ROOT / "out" / "release"), help="zip 输出目录")
    ap.add_argument("--name", help="zip 文件名（默认 RIOS-<版本>-win64.zip）")
    args = ap.parse_args()

    tree = Path(args.tree).resolve()
    if not tree.is_dir():
        die("发布树不在：%s（先跑 python tools/build_release.py --version %s）"
            % (tree, args.version))
    if not (tree / "rios-tui.exe").is_file():
        die("这棵树里没有 rios-tui.exe，看着不像发布树：%s" % tree)

    top = "rios-" + args.version
    keep, dropped = collect(tree)
    if not keep:
        die("树里一个文件都没有：%s" % tree)

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    name = args.name or ("RIOS-%s-win64.zip" % args.version.lstrip("v"))
    zpath = outdir / name

    print("[1/3] 打包 %d 个文件 → %s" % (len(keep), zpath))
    if dropped:
        print("      排除 %d 项（**不进包**）：" % len(dropped))
        for rel, n in dropped:
            print("        - %-40s %d 个文件" % (rel, n))
    else:
        print("      没有要排除的东西（树里本来就没有 data/ 与 __pycache__）")

    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in keep:
            z.write(tree / rel, arcname="%s/%s" % (top, rel))

    print("[2/3] 打完自己验一遍（重新打开、逐条比名字）")
    with zipfile.ZipFile(zpath) as z:
        got = [n for n in z.namelist() if not n.endswith("/")]
        bad = z.testzip()
    if bad is not None:
        die("zip 校验失败，第一个坏条目：%s" % bad)
    expected = ["%s/%s" % (top, rel) for rel in keep]
    missing, extra = compare(expected, got)
    ok = True
    if missing:
        ok = False
        print("      ✗ 少了 %d 条：%s" % (len(missing), missing[:5]))
    if extra:
        ok = False
        print("      ✗ 多了 %d 条：%s" % (len(extra), extra[:5]))
    leaked = [n for n in got if n.startswith(top + "/eng/data")]
    if leaked:
        ok = False
        print("      ✗ 包里有 eng/data 的东西（那是玩家自己的数据，绝不能进包）：%s"
              % leaked[:5])
    #: ★ 比对器自己的负对照：故意漏掉一个名字 ⇒ 必须报"少了 1 条"。
    #: 少了它，"没报差异"可能只是比对器瞎（本仓那条口径：每把尺子必配负对照）。
    if compare(expected, got[:-1])[0] != [got[-1]]:
        ok = False
        print("      ✗ 负对照不成立：比对器对「故意漏一条」没反应 ⇒ 上面那句"
              "「逐条比过」不作数")
    if not ok:
        die("zip 自验不过（见上）")
    print("      ✓ 条目名逐条对得上（%d 条）；无 eng/data；负对照成立" % len(got))

    size = zpath.stat().st_size
    digest = sha256_of(zpath)
    print("[3/3] 产物")
    print("      %s" % zpath)
    print("      %d 字节（%.1f MB）；树里原始 %d 字节（%.1f MB）"
          % (size, size / 1048576.0,
             sum((tree / r).stat().st_size for r in keep),
             sum((tree / r).stat().st_size for r in keep) / 1048576.0))
    print("      sha256 %s" % digest)
    print("      解开后顶层目录：%s/" % top)
    print()
    print("玩家拿到手：解压到任意位置 → 跑 rios-tui.exe（首次会引导取数据与建库）。")
    print("★ 从网上下来的 zip 会被 Windows 打上「来自网络」标记 ⇒ exe 首次运行可能弹"
          " SmartScreen；右键 zip → 属性 → 勾「解除锁定」再解压，即可避免。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
