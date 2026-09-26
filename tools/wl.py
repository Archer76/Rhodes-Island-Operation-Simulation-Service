r"""worklog 仓的入口（口径与判据见本文件末尾「长期政策」一节）。

产品仓（**本文件所在的那一个**）只留产品；内部件由**另一套 git 目录**跟踪同一份工作区。
文件一个不搬 —— 内部仪器 `import ak_tactic`，搬走即断。

用法：
    python wl.py status
    python wl.py add tools/probe_x.py docs/y.md
    python wl.py commit "说明"
    python wl.py log [-N]
    python wl.py list
    python wl.py check [--fix] [--explain]     # ★ 长期政策，见下

★ 长期政策（博士 2026-09-24 定，**长期有效**）：

    **本项目所有「不上传 GitHub」且「不可重建」的文件，都必须在 worklog 里。**

`check` 就是这条政策的判据：它把产品仓的两个清单求并（被忽略的 ＋ 未跟踪的），
减去**可重建白名单**，剩下的每一个都必须在 worklog 的索引里；缺一个就 rc=1。
`--fix` 把缺的按**逐路径** add 进来（本仓禁用 `-A`，这里给的是算出来的具名清单）；
`--explain` 印白名单以及**每一条由谁负责再造出来**。
★ 这份文件**也会进公开仓**（博士 2026-09-26 裁）：它是**恢复流程的入口本身** ——
`<worklog>\wl.py` 只是一个 `runpy` 转发壳，真实现住在这里；这一份被误删，
恢复工具与「该恢复什么」的知识就一起断了。所以它按**公开件**的标准写：
路径一律从 `__file__` 推（可用 `AK_TACTIC_SRC` / `AK_WORKLOG_GITDIR` 覆盖），
不写死本机路径，也**不内嵌任何账号 uid**（范围正对照改为运行时现找同族文件）。

它管的那套东西叫「同一条工作区、两套索引」：产品仓只跟踪产品，
另一个仓外本地仓（`--git-dir` 指向别处、`--work-tree` 仍是这里）跟踪内部件，
文件一个不搬（内部仪器 `import ak_tactic`，搬走即断）。
"""
import fnmatch
import os
import pathlib
import subprocess
import sys

#: 产品仓根：**从本文件位置推**（本文件住在 `<仓根>/tools/wl.py`），不写死。
SRC = pathlib.Path(os.environ.get("AK_TACTIC_SRC")
                   or pathlib.Path(__file__).resolve().parent.parent).resolve()
#: worklog 仓的 `.git`：默认取**与产品仓同级**的那个目录，同样不写死；
#: 放在别处就用 `AK_WORKLOG_GITDIR` 指。
GITDIR = pathlib.Path(os.environ.get("AK_WORKLOG_GITDIR")
                      or SRC.parent / "ak-tactic-worklog" / ".git")

#: 可重建／可重取白名单：**不在库里也不算丢**。每一条都要能说出「谁把它再造出来」，
#: 说不出的一律不许进这张表 —— 否则这条政策会退化成「反正都能重建」。
#: 形态是 (路径前缀, 前缀之后的匹配式, 由谁再造)。
REBUILDABLE = (
    ("data/gamedata/", "*",
     "按需缓存：GameDataSource 访问哪个键就落哪一份，没有独立重建命令。"
     "★ THIRD-PARTY.md 明令不分发，所以也**不得** git add"),
    ("data/cache/", "*",
     "第三方原始响应缓存（prts／theresa／ark-nights），重新访问就有"),
    ("out/", "*",
     "判据产物与 Go exe：`cd rios-sim; go build -o ..\\out\\acceptance\\rios-sim-stage3.exe .`"
     " ＋ 跑判据脚本就有"),
    ("data/", "akdb.sqlite", "tools/rebuild_data.py --offline（约 14 秒，不联网）"),
    ("data/", "enemydb.sqlite", "tools/rebuild_data.py（要联网，冷启约 53 秒）"),
    ("data/", "prts-notes.sqlite", "tools/rebuild_data.py（要联网，约 10~15 分钟）"),
    ("data/", "op-briefs.txt", "tools/rebuild_data.py --offline（由 prts-notes 展平）"),
    ("data/", "ranges.json", "tools/rebuild_data.py（要联网，约 1~2 分钟）"),
    ("", "*__pycache__/*",
     "CPython 在 import 时按源码自动重建：`.py` 源码有家（产品仓或 worklog 索引），"
     "而 pyc 不承载独立信息 —— 它只是那份源码在某个解释器版本下的字节码"
     "（本机是 cpython-314，换版本即作废，留着反而误导）。"
     "★ 2026-09-26 补：原先没有这条，于是 14 个新生成的 pyc 被报成「不上传、"
     "且不可重建，却不在 worklog 里」的**假红** —— 全是 `tools/__pycache__/` 下"
     "源码俱在的普通字节码。白名单缺项的假红与真缺一样有害：它耗掉的是"
     "「这条政策还看得见东西」的信任。"),
)


def git(*a, **kw):
    return subprocess.run(["git", f"--git-dir={GITDIR}", f"--work-tree={SRC}", *a],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(SRC), **kw)


def prod(*a, **kw):
    """**产品仓**的 git（不带 `--git-dir`，就在 `SRC` 里跑）。

    ⚠ 这一条是踩出来的：最初 `check` 用上面的 `git()` 算「产品仓收不进的文件」，
    而那支命令带的是 **worklog 的 `--git-dir`** ⇒ 量到的是 **worklog 的索引**。
    于是已经收进来的 971 个文件全都变成「不是 others」，被忽略数从 3032 掉到 2179、
    候选数从 779 掉到 **0** —— 一条**永远说「全部在库」**的假绿。
    口径：谁收不收，是**产品仓**说了算；worklog 只回答「收进来了没有」。
    """
    return subprocess.run(["git", "-c", "core.quotePath=false", *a],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(SRC), **kw)


#: 范围的正对照：这些**一定**在产品仓的「收不进」清单里。一条都看不见，就说明
#: 上面那句查询没跑成功（本仓记过：报零命中之前先证明查询跑成功了）。
#:
#: ★ 2026-09-26：由「写死两个带账号 uid 的具体文件名」改成**运行时现找同族文件**。
#:   理由是这份文件要进公开仓，而原来那两个名字里嵌着 uid，那串 uid 已于
#:   2026-09-17 按隐私口径从本仓历史摘除过 —— 写回来等于自打嘴巴。
#:   改法**不改语义**：仍旧是「拿一条已知该在被忽略清单里的文件，去证明这次的范围
#:   查询真的看见了东西」。找不到任何同族文件时**不许当绿**，见 check() 的 rc=3。
SCOPE_CONTROL_FAMILIES = ("docs/roster-*.md", "data/skland/opers_*.json")


def scope_control() -> list[str]:
    out: list[str] = []
    for fam in SCOPE_CONTROL_FAMILIES:
        out.extend(sorted(p.relative_to(SRC).as_posix() for p in SRC.glob(fam)))
    return out


def _z(out: str) -> list[str]:
    return [x for x in out.split("\0") if x]


def is_rebuildable(p: str) -> bool:
    for pre, pat, _why in REBUILDABLE:
        if p.startswith(pre) and fnmatch.fnmatch(p[len(pre):], pat):
            return True
    return False


def candidates() -> tuple[list[str], str, list[str], list[str]]:
    """产品仓收不进（被忽略或未跟踪）、且**不在**可重建白名单里的文件。

    取证范围是**现算**的两个清单求并 —— 手写名单会随交付漂移，而本仓已经
    因为「名单本身污染读它的尺子」踩过一次。

    第三、四个返回值是**范围自检**：`unseen` ＝ 正对照里没被看见的那些，
    `ctrl` ＝ 本次实际拿到的正对照名单（空 ⇒ 连对照都没得做，读数作废）。
    """
    ignored = _z(prod("ls-files", "--others", "--ignored",
                      "--exclude-standard", "-z").stdout)
    untracked = _z(prod("ls-files", "--others", "--exclude-standard", "-z").stdout)
    ctrl = scope_control()
    unseen = [p for p in ctrl if p not in ignored and p not in untracked]
    return ([p for p in ignored + untracked if not is_rebuildable(p)],
            "%d（被忽略）＋ %d（未跟踪）" % (len(ignored), len(untracked)),
            unseen, ctrl)


def check(fix: bool = False) -> int:
    if not GITDIR.exists():
        print("WORKLOG_MISSING_REPO %s" % GITDIR)
        return 3
    cand, scope, unseen, ctrl = candidates()
    if not ctrl:
        print("SCOPE_CONTROL_UNAVAILABLE —— 找不到任何可用于正对照的同族文件（%s）"
              "⇒ 无法证明这次的范围查询看见了东西，**读数作废**"
              % " / ".join(SCOPE_CONTROL_FAMILIES))
        return 3
    if unseen:
        for p in unseen:
            print("SCOPE_CONTROL_UNSEEN %s" % p)
        print("范围自检不过：产品仓的「收不进」清单里看不见 %d 个已知该在的文件 ⇒ "
              "这次的范围查询不可信，读数作废" % len(unseen))
        return 3
    tracked = set(x for x in git("ls-files").stdout.splitlines() if x)
    missing = sorted(p for p in cand if p not in tracked)
    print("取证范围：产品仓收不进的文件 %s（范围自检 %d/%d ✓）"
          % (scope, len(ctrl) - len(unseen), len(ctrl)))
    print("  减去可重建白名单 %d 条 ⇒ 必须入库的 %d 个" % (len(REBUILDABLE), len(cand)))
    print("  worklog 索引现有 %d 个" % len(tracked))
    if not missing:
        print("结论：**全部在库**（0 个缺）")
        return 0
    for p in missing:
        print("WORKLOG_MISSING %s" % p)
    print("结论：**%d 个缺**（不上传、且不可重建，却不在 worklog 里）" % len(missing))
    if fix:
        r = git("add", "-f", "--", *missing)
        print("--fix：逐路径 add %d 个 ⇒ rc=%d" % (len(missing), r.returncode))
        if r.stderr.strip():
            print(r.stderr.strip()[:300])
        return r.returncode
    return 1


def selftest() -> int:
    """尺子的正负对照：**不依赖仓库当前状态**。

    来历：本仓记过「报零命中之前先证明查询跑成功了」。这条检查的主判据是
    「缺 0 个」，而缺 0 有两个来源 —— 真的齐了，或**尺子没看见任何东西**。
    所以必须用合成输入分别证一次「能看见」与「能判绿」。
    """
    bad = 0
    #: 正对照：白名单里的东西**不许**被判成必须入库
    for p, want in (("data/gamedata/map.ark-nights.com/levels/obt/main/level_main_00-01.json", False),
                    ("data/cache/prts/x.txt", False),
                    ("out/acceptance/rios-sim-stage3.exe", False),
                    ("data/akdb.sqlite", False),
                    ("data/prts-notes.sqlite", False),
                    ("data/skland/opers_00000000.json", True),
                    ("data/operbox/Arknights_OperBox_Export.json", True),
                    ("data/roster-00000000.md", True),
                    ("docs/roster-00000000.md", True),
                    ("tools/probe_x.py", True),
                    ("_proto/a.py", True)):
        got = not is_rebuildable(p)
        if got != want:
            print("✗ 白名单判错：%s ⇒ 判成必须入库=%s，应为 %s" % (p, got, want))
            bad += 1
        else:
            print("✓ %-72s 必须入库=%s" % (p, got))
    #: 负对照：把白名单清空，**每一个**都该变成必须入库（否则白名单是空操作）
    global REBUILDABLE
    keep = REBUILDABLE
    try:
        REBUILDABLE = ()
        n = sum(1 for p, _ in (("data/akdb.sqlite", 0), ("out/x.exe", 0),
                               ("data/cache/y", 0)) if not is_rebuildable(p))
    finally:
        REBUILDABLE = keep
    if n != 3:
        print("✗ 负对照：清空白名单后应 3 个全判必须入库，实得 %d" % n)
        bad += 1
    else:
        print("✓ 负对照：清空白名单 ⇒ 3/3 全判必须入库（白名单不是空操作）")
    print("自检：%s" % ("成立 ✓" if bad == 0 else "不成立 ✗（%d 条）" % bad))
    return 1 if bad else 0


def explain() -> int:
    print("可重建白名单（不在库里也不算丢）—— 每条都要能说出谁把它再造出来：")
    for pre, pat, why in REBUILDABLE:
        print("  %-14s %-18s %s" % (pre, pat, why))
    print()
    print("其余一切「产品仓收不进」的文件，都必须在 worklog 里。")
    return 0


def main(argv):
    if not GITDIR.exists():
        print(f"找不到 {GITDIR} —— worklog 仓还没建")
        return 2
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]

    if cmd == "status":
        r = git("status", "--short")
    elif cmd == "check":
        if "--selftest" in rest:
            return selftest()
        if "--explain" in rest:
            return explain()
        return check(fix="--fix" in rest)
    elif cmd == "add":
        if not rest:
            print("要给出路径；本仓禁用 -A")
            return 2
        bad = [p for p in rest if p.startswith("-")]
        if bad:
            print(f"不接受开关：{bad}（逐路径 add 是本仓的规矩）")
            return 2
        r = git("add", "-f", "--", *rest)
    elif cmd == "commit":
        if not rest:
            print("要给出说明")
            return 2
        r = git("commit", "-m", " ".join(rest))
    elif cmd == "log":
        n = rest[0].lstrip("-") if rest else "5"
        r = git("log", "--oneline", f"-{n}")
    elif cmd == "list":
        r = git("ls-files")
    else:
        print(f"不认识的子命令：{cmd}")
        return 2

    if r.stdout:
        print(r.stdout.rstrip())
    if r.returncode != 0 and r.stderr:
        print(r.stderr.rstrip(), file=sys.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
