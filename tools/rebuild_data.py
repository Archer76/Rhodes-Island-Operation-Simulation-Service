"""把 `data/` 下的**派生物**重建出来（一条命令；**只加不删**）。

## 为什么要有它

`data/*.sqlite`、`data/ranges.json`、`data/op-briefs.txt` 全在 `.gitignore` 里
⇒ **任何 `git clean -xdf` 都会把它们当忽略文件删掉**。2026-09-20 凌晨就发生过一次：
`prts-notes.sqlite` / `op-briefs.txt` / `enemydb.sqlite` / `ranges.json` / `operbox/`
在 01:0x 还在、03:1x 全无，而**回收站是空的**。

**这不怪谁手快，怪"数据可重建"没有被当成硬要求。**
这个脚本就是那个硬要求：**一条命令，把该有的东西全部重建，并且逐项自报结果。**

## 三条设计

1. **只加不删**。本脚本**不删除任何文件**——不"顺手清理"。重建就是覆盖写。
   （如果哪天确实需要先删旧的，**必须把删了什么打印出来**：今晚的教训。）
2. **没做成的步骤要出列，不许静默跳过**。每步跑完都记 `ok/failed/skipped`，
   末尾汇总按状态分组；有 `failed` 就 **rc=1**。
3. **跑完必须逐表报行数**，且与预期对账。**"跑通"不等于"库是完整的"**：
   在"只剩 `gamedata/`"的空状态下重建，`stage` 表会是 **0 行**（要联网跑
   `db stage-fetch`）——脚本返回 0 而库少一张表，是最坏的一种"成功"。

用法：
    python tools/rebuild_data.py                 # 全量（含联网步骤）
    python tools/rebuild_data.py --offline       # 只跑不需要联网的
    python tools/rebuild_data.py --dry-run       # 只报计划，不动手
    python tools/rebuild_data.py --list          # 逐项列出来源 / 耗时 / 是否联网
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

#: 下载 gamedata 的地址。**它是所有离线步骤的源头**，但本脚本不负责取它
#: （那是一次几十 MB 的仓库下载，且不在"派生物"范畴）。
GAMEDATA_SRC = ("https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData"
                "/master/zh_CN/gamedata")
GAMEDATA_DIR = DATA / "gamedata" / "raw.githubusercontent.com" / "excel"


# ---------------------------------------------------------------- 步骤定义

@dataclass
class Step:
    key: str
    title: str
    kind: str                 # offline / online / external
    produces: str             # 产物（给人看的一行）
    source: str               # 从哪来
    needs: str                # 需不需要登录 / Cookie / 前置
    eta: str
    fail_looks_like: str
    argv: list[str] | None = None      # 直接跑的 CLI
    func: str = ""                     # 或本脚本内的函数名

    def describe(self) -> str:
        net = {"offline": "不联网", "online": "**要联网**", "external": "外部输入"}[self.kind]
        return (f"{self.key:<18} {net:<10} {self.eta:<10} {self.produces}\n"
                f"{'':<18} 来源：{self.source}\n"
                f"{'':<18} 前提：{self.needs}\n"
                f"{'':<18} 失败长什么样：{self.fail_looks_like}")


STEPS: list[Step] = [
    Step(
        key="akdb.sqlite", title="干员库", kind="offline",
        produces="data/akdb.sqlite",
        source="本地 gamedata 源表（character_table / skill_table / uniequip_table / "
               "battle_equip_table / range_table / char_patch_table）",
        needs="`data/gamedata/` 必须在；**不需要登录**",
        eta="约 14 秒",
        fail_looks_like="`FileNotFoundError` 指向 gamedata 缓存；或建完 `operator` 行数为 0",
        argv=[sys.executable, "-m", "ak_tactic", "db", "build", "--verbose"],
    ),
    Step(
        key="stage 表", title="关卡索引（akdb 里的一张表）", kind="online",
        produces="data/akdb.sqlite 的 stage / zone 两张表",
        source="map.ark-nights.com 的 JS bundle + 镜像的 excel/zone_table.json、stage_table.json",
        needs="**要联网**；不需要登录",
        eta="约 1 分钟",
        fail_looks_like="`stage` 行数为 0；`db info` 里会自带一行警告",
        argv=[sys.executable, "-m", "ak_tactic", "db", "stage-fetch"],
    ),
    Step(
        key="enemydb.sqlite", title="敌人库", kind="online",
        produces="data/enemydb.sqlite",
        source="prts.wiki 的「分类:敌人」（约 1800 页）",
        needs="**要联网**；不需要登录；必带浏览器 UA（脚本自己会带）",
        eta="冷启约 53 秒",
        fail_looks_like="库能建出来但 `enemy` 行数远小于预期；或对 prts.wiki 的请求 403",
        argv=[sys.executable, "-m", "ak_tactic", "enemydb", "build"],
    ),
    Step(
        key="prts-notes.sqlite", title="干员备注库", kind="online",
        produces="data/prts-notes.sqlite",
        source="prts.wiki 干员页的 `|备注=` / `|特性备注=`（按名册逐页）",
        needs="**要联网**；不需要登录；请求间隔 ≥1.2 s（脚本自己限速）；**可续跑**",
        eta="约 10~15 分钟（460 页）",
        fail_looks_like="某些页抓不到 ⇒ **脚本会把失败页逐页列出来**；"
                        "正常结果约 `fact` 3247 条 / `page` 459 页",
        argv=[sys.executable, str(ROOT / "tools" / "fetch_prts_notes.py")],
    ),
    Step(
        key="op-briefs.txt", title="备注语料展平", kind="offline",
        produces="data/op-briefs.txt",
        source="**从 `data/prts-notes.sqlite` 的 `fact` 表展平**（人读用）",
        needs="`data/prts-notes.sqlite` 必须先建好",
        eta="不到 1 秒",
        # ⚠ 这一条必须说清楚：原文件在 2026-09-20 丢失，**且全仓找不到它的生产者**。
        fail_looks_like="`prts-notes.sqlite` 不存在 ⇒ 本步 skipped（不算失败）",
        func="_flatten_op_briefs",
    ),
    Step(
        key="ranges.json", title="攻击范围索引", kind="online",
        produces="data/ranges.json",
        source="prts.wiki 的 `Widget:Range/<代号>` SVG（代号从 akdb 的 `attack_range` 取）",
        needs="**要联网**；`data/akdb.sqlite` 必须先建好（用来找代号）",
        eta="约 1~2 分钟（代号只有几十种）",
        fail_looks_like="个别代号取不到 ⇒ 逐个报出来，不静默少格子",
        func="_rebuild_ranges",
    ),
    Step(
        key="operbox/", title="账号名册（MAA 导出）", kind="external",
        produces="data/operbox/Arknights_OperBox_Export.json",
        source="**玩家自己从 MAA 导出的文件**",
        needs="**不可重建**——必须由人放到约定位置（或用环境变量 `AK_OPERBOX` 指路）",
        eta="—",
        fail_looks_like="文件不在 ⇒ 名册三来源退到下一档；不是错误",
        func="_report_external",
    ),
    Step(
        key="skland/", title="森空岛名册缓存", kind="external",
        produces="data/skland/*.json",
        source="森空岛 API（干员练度 + 模组，比 MAA 导出更全）",
        needs="**不可离线重建**——要登录态；见 `docs/data-sources.md` 第 7 条",
        eta="—",
        fail_looks_like="没有登录态 ⇒ 取不到；名册会退回 operbox 档",
        func="_report_external",
    ),
]


# ---------------------------------------------------------------- 本脚本内的两步

def _flatten_op_briefs() -> tuple[bool, str]:
    """把备注库展平成人读语料。

    ⚠ **格式由本脚本定义**：原 `data/op-briefs.txt`（561 KB / 3249 行）在
    2026-09-20 丢失，而**全仓找不到它的生产者**（`grep -r briefs` 只命中
    `.gitignore` 与 `docs/data-sources.md`）。所以这里**不是"复原"，是新定义**，
    谁要用它的格式请以本函数为准。
    """
    db = DATA / "prts-notes.sqlite"
    if not db.exists():
        return False, "跳过：data/prts-notes.sqlite 不存在"
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in c.execute("pragma table_info(fact)")}
        if not {"char_id", "kind", "value"} <= cols:
            return False, f"fact 表列不对：{sorted(cols)}"
        rows = c.execute(
            "select char_id, kind, value from fact order by char_id, kind").fetchall()
    finally:
        c.close()
    out = [f"# 由 tools/rebuild_data.py 从 data/prts-notes.sqlite 展平生成；共 {len(rows)} 条。",
           "# 每行一条：char_id\\tkind\\t正文（正文里的换行与制表符已替换成空格）。"]
    for cid, kind, value in rows:
        flat = " ".join(str(value).split())
        out.append(f"{cid}\t{kind}\t{flat}")
    target = DATA / "op-briefs.txt"
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    return True, f"已写 {target.name}：{len(rows)} 条 + 2 行表头"


def _rebuild_ranges() -> tuple[bool, str]:
    """重建 `data/ranges.json`：代号从 akdb 取，网格从 prts.wiki 取。

    走的是**既有 API**（`ak_tactic.prts.RangeRegistry`），不自己解析 SVG。
    """
    akdb = DATA / "akdb.sqlite"
    if not akdb.exists():
        return False, "跳过：data/akdb.sqlite 不存在（代号要从它的 attack_range 取）"
    c = sqlite3.connect(f"file:{akdb}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in c.execute("pragma table_info(attack_range)")}
        col = "code" if "code" in cols else ("range_id" if "range_id" in cols else None)
        if col is None:
            return False, f"attack_range 里找不到代号列：{sorted(cols)}"
        codes = sorted({r[0] for r in c.execute(f"select distinct {col} from attack_range")
                        if r[0]})
    finally:
        c.close()
    if not codes:
        return False, "attack_range 里一个代号都没有"

    sys.path.insert(0, str(ROOT))
    from ak_tactic.prts import RangeRegistry                      # noqa: PLC0415

    reg = RangeRegistry()
    got, failed = 0, []
    for code in codes:
        try:
            reg.get(code)
            got += 1
        except Exception as e:                                     # noqa: BLE001
            failed.append(f"{code}（{e}）")
    reg.save()
    msg = f"代号 {len(codes)} 个：取到 {got} 个，落盘 {reg.index_path.name}"
    if failed:
        msg += f"；⚠ 取不到 {len(failed)} 个：" + "、".join(failed[:8])
    return (not failed), msg


def _report_external() -> tuple[bool, str]:
    """外部输入不重建——只如实报告在不在。"""
    box = DATA / "operbox"
    skl = DATA / "skland"
    nb = len(list(box.glob("*"))) if box.exists() else 0
    ns = len(list(skl.glob("*"))) if skl.exists() else 0
    return True, (f"外部输入（**不可重建**）：operbox/ {nb} 个文件、skland/ {ns} 个文件"
                  "——缺了不影响本脚本 rc，但名册会退档")


# ---------------------------------------------------------------- 跑

@dataclass
class Result:
    key: str
    status: str               # ok / failed / skipped
    seconds: float
    message: str


def _run_step(step: Step, *, offline_only: bool) -> Result:
    if step.kind == "online" and offline_only:
        return Result(step.key, "skipped", 0.0, "--offline：需要联网，未跑")
    if step.kind == "external":
        pass                      # 外部输入照报不误
    t0 = time.time()
    if step.func:
        fn = {"_flatten_op_briefs": _flatten_op_briefs,
              "_rebuild_ranges": _rebuild_ranges,
              "_report_external": _report_external}[step.func]
        try:
            ok, msg = fn()
        except Exception as e:                                     # noqa: BLE001
            return Result(step.key, "failed", time.time() - t0, f"{type(e).__name__}: {e}")
        # 外部输入没有"成功/失败"可言，永远记 ok（信息在 msg 里）
        status = "ok" if (ok or step.kind == "external") else "failed"
        return Result(step.key, status, time.time() - t0, msg)

    # ⚠ 子进程**让它的 stdout/stderr 直接继承**（不抓管道）：
    #   本机沙箱下用管道捕获子进程输出会 EPERM；继承还有个好处——进度实时可见。
    try:
        cp = subprocess.run(step.argv, cwd=str(ROOT), check=False)
    except Exception as e:                                         # noqa: BLE001
        return Result(step.key, "failed", time.time() - t0, f"{type(e).__name__}: {e}")
    rc = cp.returncode
    return Result(step.key, "ok" if rc == 0 else "failed", time.time() - t0,
                  f"rc={rc}")


# ---------------------------------------------------------------- 逐表对账

#: 这些表**必须非空**。空了就是这一步没做成（而不是"游戏里本来就没有"）。
MUST_HAVE_ROWS: dict[str, tuple[str, ...]] = {
    "akdb.sqlite": ("operator", "operator_attr", "operator_phase", "operator_potential",
                    "operator_talent", "operator_trait", "operator_skill",
                    "skill", "skill_level", "module", "module_level", "attack_range"),
    "enemydb.sqlite": ("enemy", "enemy_level"),
    "prts-notes.sqlite": ("fact", "page"),
}

#: 这些表**允许为空**，但空的时候必须把原因说出来——**否则"跑通"就是"静默少表"**。
MAY_BE_EMPTY: dict[str, dict[str, str]] = {
    "akdb.sqlite": {
        "stage": "需要联网：跑 `python -m ak_tactic db stage-fetch`（本脚本的「stage 表」一步）",
        "zone": "同上，跟 stage 一起由 stage-fetch 灌入",
    },
    "enemydb.sqlite": {},
    "prts-notes.sqlite": {},
}


def _row_counts() -> list[tuple[str, str, int, str]]:
    """[(库, 表, 行数, 备注)]。库不存在 ⇒ 备注里写明。"""
    out: list[tuple[str, str, int, str]] = []
    for dbname in ("akdb.sqlite", "enemydb.sqlite", "prts-notes.sqlite"):
        p = DATA / dbname
        if not p.exists():
            out.append((dbname, "—", -1, "**库不存在**"))
            continue
        if p.stat().st_size == 0:
            out.append((dbname, "—", -1, "**0 字节**"))
            continue
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in c.execute(
                "select name from sqlite_master where type='table' order by name")]
            for t in tables:
                try:
                    n = c.execute(f"select count(*) from {t}").fetchone()[0]
                except sqlite3.Error as e:                         # noqa: BLE001
                    out.append((dbname, t, -1, f"数不出来：{e}"))
                    continue
                out.append((dbname, t, n, ""))
        finally:
            c.close()
    return out


def _reconcile() -> tuple[list[str], list[str]]:
    """返回 (问题清单, 提示清单)。问题 ⇒ rc=1。"""
    problems: list[str] = []
    notes: list[str] = []
    counts = _row_counts()
    seen: dict[str, dict[str, int]] = {}
    for db, t, n, why in counts:
        seen.setdefault(db, {})[t] = n
    for db, musts in MUST_HAVE_ROWS.items():
        got = seen.get(db)
        if got is None:
            problems.append(f"{db} 建不出来（表都没读到）")
            continue
        for t in musts:
            if t not in got:
                problems.append(f"{db} 少了表 `{t}`（必须在）")
            elif got[t] == 0:
                problems.append(f"{db}.{t} **0 行**（必须在，空了说明这一步没做成）")
    for db, allows in MAY_BE_EMPTY.items():
        got = seen.get(db) or {}
        for t, reason in allows.items():
            if got.get(t) == 0:
                notes.append(f"{db}.{t} 是 0 行 —— {reason}")
    return problems, notes


# ---------------------------------------------------------------- main

def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")                        # type: ignore[union-attr]
        except Exception:                                          # noqa: BLE001
            pass

    ap = argparse.ArgumentParser(
        description="重建 data/ 下的派生物（只加不删；跑完逐表对账）")
    ap.add_argument("--offline", action="store_true", help="只跑不需要联网的步骤")
    ap.add_argument("--dry-run", action="store_true", help="只报计划，不动手")
    ap.add_argument("--list", action="store_true", help="逐项列出来源/耗时/是否联网")
    args = ap.parse_args()

    if args.list:
        print("data/ 派生物一览（来源 / 是否联网 / 耗时 / 失败长什么样）")
        print("=" * 78)
        for s in STEPS:
            print(s.describe())
            print("-" * 78)
        return 0

    print("== 前置检查 ==")
    if GAMEDATA_DIR.exists():
        n = len(list(GAMEDATA_DIR.glob("*.json")))
        print(f"  ✅ gamedata 源表在：{GAMEDATA_DIR}（{n} 个 json）")
    else:
        print(f"  ⛔ **gamedata 源表不在**：{GAMEDATA_DIR}")
        print(f"     离线步骤全部做不了。取它：从 {GAMEDATA_SRC} 下载到该目录。")
    print(f"  data/ 现有：{sorted(p.name for p in DATA.iterdir()) if DATA.exists() else '（无）'}")

    if args.dry_run:
        print("\n== 计划（--dry-run，不动手） ==")
        for s in STEPS:
            mark = "跳过" if (args.offline and s.kind == "online") else "要跑"
            print(f"  [{mark}] {s.key:<18} {s.kind:<9} {s.eta:<12} {s.produces}")
        return 0

    print("\n== 步骤 ==")
    print("  ⚠ 本脚本**只加不删**：它不删除任何文件；重建 = 覆盖写。")
    results: list[Result] = []
    for s in STEPS:
        print(f"\n---- {s.key}｜{s.title} ----")
        print(f"     来源：{s.source}")
        print(f"     前提：{s.needs}　预计：{s.eta}")
        r = _run_step(s, offline_only=args.offline)
        results.append(r)
        icon = {"ok": "✅", "failed": "⛔", "skipped": "⏭"}[r.status]
        print(f"  {icon} {r.status}（{r.seconds:.1f}s）{r.message}")

    print("\n" + "=" * 78)
    print("== 逐表行数（★ 空表必须给出原因，否则「跑通」就是「静默少表」） ==")
    print("=" * 78)
    counts = _row_counts()
    for db in ("akdb.sqlite", "enemydb.sqlite", "prts-notes.sqlite"):
        rows = [(t, n, w) for d, t, n, w in counts if d == db]
        print(f"\n  【{db}】")
        if not rows:
            print("    ⛔ 没有读到任何表")
            continue
        for t, n, why in rows:
            if n < 0:
                flag = "⛔"
            elif n == 0:
                flag = "⚠ 空"
            else:
                flag = "  "
            extra = f"　← {why}" if why else ""
            print(f"    {flag} {t:<20} {n:>8}{extra}")

    problems, notes = _reconcile()

    print("\n" + "=" * 78)
    print("== 汇总 ==")
    print("=" * 78)
    for st, label in (("ok", "做成"), ("failed", "失败"), ("skipped", "跳过")):
        group = [r for r in results if r.status == st]
        print(f"  {label} {len(group)} 项：" + ("、".join(r.key for r in group) or "（无）"))
    if notes:
        print("\n  ⚠ 空表说明（**不是失败，但必须知道**）：")
        for n in notes:
            print(f"    · {n}")
    if problems:
        print("\n  ⛔ 对账不过（rc=1）：")
        for p in problems:
            print(f"    · {p}")
    else:
        print("\n  ✅ 逐表对账通过：该有行的表都有行。")

    failed = [r for r in results if r.status == "failed"] or problems
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
