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
import tempfile
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
    #: 这一步的子命令支不支持 `--progress-file`（往进度文件里写 tick）。
    #: ★ 只有声明了才给它加这个参数：给别的子命令加上去，它们会当场以
    #: 「unrecognized arguments」失败 —— 那是一处会**静默毁掉整个首次运行**的写法。
    wants_progress: bool = False

    def describe(self) -> str:
        net = {"offline": "不联网", "online": "**要联网**", "external": "外部输入"}[self.kind]
        return (f"{self.key:<18} {net:<10} {self.eta:<10} {self.produces}\n"
                f"{'':<18} 来源：{self.source}\n"
                f"{'':<18} 前提：{self.needs}\n"
                f"{'':<18} 失败长什么样：{self.fail_looks_like}")


STEPS: list[Step] = [
    Step(
        key="gamedata 源表", title="游戏源表", kind="online",
        produces="data/gamedata/raw.githubusercontent.com/excel/*.json（8 张）",
        source="GitHub 镜像 Kengxxiao/ArknightsGameData 的 zh_CN/gamedata/excel/",
        needs="**要联网**；不需要登录；取过一次之后离线步骤才做得了",
        eta="约 10~30 秒（8 个文件）",
        fail_looks_like="证书链报错（沙箱/代理做 TLS 检查）⇒ 见日志里的具名三条路；"
                        "403/404 ⇒ 镜像地址变了",
        argv=[sys.executable, "-m", "ak_tactic", "cache", "--fetch-gamedata"],
        #: ★ 2026-09-28 补：这一步**原先不存在**（离线建干员库要这批源表，却没人负责取）
        #: ⇒ 全新机器首启必挂。它能报百分比（8 张表）与下载速度。
        wants_progress=True,
    ),
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
        key="stage 表", title="关卡索引", kind="online",
        produces="data/akdb.sqlite 的 stage / zone 两张表",
        source="map.ark-nights.com 的 JS bundle + 镜像的 excel/zone_table.json、stage_table.json",
        needs="**要联网**；不需要登录",
        eta="约 1 分钟",
        fail_looks_like="`stage` 行数为 0；`db info` 里会自带一行警告",
        argv=[sys.executable, "-m", "ak_tactic", "db", "stage-fetch"],
    ),
    Step(
        key="关卡文件", title="逐关 JSON（引擎 load 读它）", kind="online",
        produces="data/gamedata/<镜像域名>/levels/ 下的逐关 JSON",
        source="map.ark-nights.com（`levels/<data_path>`，按关卡索引给的路径）",
        needs="**要联网**；`stage 表` 必须先有（范围＝库里的 distinct level_id）；可续跑",
        eta="首次约 1~2 分钟（约 1200 个文件、57 MB，8 线程）",
        fail_looks_like="末尾逐条列 `✗`（镜像里没有 ≠ 网络抖动）；**没它的话**，"
                        "界面里选到那一关会报「取部署人数上限失败：读关卡文件失败」",
        argv=[sys.executable, "-m", "ak_tactic", "cache", "--fetch-levels"],
        wants_progress=True,
    ),
    Step(
        key="enemydb.sqlite", title="敌人库", kind="online",
        produces="data/enemydb.sqlite",
        source="prts.wiki 的「分类:敌人」（约 1800 页）",
        needs="**要联网**；不需要登录；必带浏览器 UA（脚本自己会带）",
        eta="冷启约 53 秒",
        fail_looks_like="库能建出来但 `enemy` 行数远小于预期；或对 prts.wiki 的请求 403",
        argv=[sys.executable, "-m", "ak_tactic", "enemydb", "build"],
        #: ★ 2026-09-28：这一步是 1800 个页面，**给得出百分比与下载速度**
        #: （`build_enemy_db(progress=…)` 每抓一批就报一次 done/total/bytes）。
        wants_progress=True,
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
        fail_looks_like="**两档分开**：「源上没有」（`PrtsError: 页面不存在`）记 `not_on_source`、"
                        "**不进失败计数**；「解析不出」（`RangeParseError`：站位格数不对）才算失败。"
                        "两类都**逐条列出**，不截断",
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

def _flatten_op_briefs() -> tuple[str, str]:
    """把备注库展平成人读语料。

    ⚠ **格式由本脚本定义**：原 `data/op-briefs.txt`（561 KB / 3249 行）在
    2026-09-20 丢失，而**全仓找不到它的生产者**（`grep -r briefs` 只命中
    `.gitignore` 与 `docs/data-sources.md`）。所以这里**不是"复原"，是新定义**，
    谁要用它的格式请以本函数为准。

    返回 `(ok|skipped|failed, 说明)`。★ **前置缺失是 skipped 不是 failed**——
    空状态实跑（2026-09-20）正是栽在这里：备注库不在时它报 failed，
    害得 `--offline` 空跑 rc=1，把"按需跳过"误报成"故障"。
    """
    db = DATA / "prts-notes.sqlite"
    if not db.exists():
        return "skipped", "跳过：data/prts-notes.sqlite 不存在（先把那一步跑出来）"
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in c.execute("pragma table_info(fact)")}
        if not {"char_id", "kind", "value"} <= cols:
            return "failed", f"fact 表列不对：{sorted(cols)}"
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
    return "ok", f"已写 {target.name}：{len(rows)} 条 + 2 行表头"


def _rebuild_ranges() -> tuple[str, str]:
    """重建 `data/ranges.json`：代号从 akdb 取，网格从 prts.wiki 取。

    走的是**既有 API**（`ak_tactic.prts.RangeRegistry`），不自己解析 SVG。
    """
    akdb = DATA / "akdb.sqlite"
    if not akdb.exists():
        return "skipped", "跳过：data/akdb.sqlite 不存在（代号要从它的 attack_range 取）"
    c = sqlite3.connect(f"file:{akdb}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in c.execute("pragma table_info(attack_range)")}
        col = "code" if "code" in cols else ("range_id" if "range_id" in cols else None)
        if col is None:
            return "failed", f"attack_range 里找不到代号列：{sorted(cols)}"
        codes = sorted({r[0] for r in c.execute(f"select distinct {col} from attack_range")
                        if r[0]})
    finally:
        c.close()
    if not codes:
        return "failed", "attack_range 里一个代号都没有"

    sys.path.insert(0, str(ROOT))
    from ak_tactic.prts import RangeRegistry                      # noqa: PLC0415
    from ak_tactic.prts.client import PrtsError                   # noqa: PLC0415
    from ak_tactic.prts.grid import RangeParseError               # noqa: PLC0415

    # ★ `fresh=True`：**不读旧索引**，每个代号都从 SVG 重新解析。
    #   ⚠ 不传它的话，已在盘上的代号会被 `_load()` 装进内存、`get()` 直接返回，
    #   **改了解析器也传不到它们身上**——那不是重建，是**把自己的输出当权威**
    #   （2026-09-20 实测：改了站位格解析后重跑，63 个老代号原样不动）。
    reg = RangeRegistry(fresh=True)
    got = 0
    # ★ **两档分开**（PM 2026-09-20 裁定，本任务第六次同族）：
    #   · `not_on_source`（源上没有）——**这不是失败**，是"这一项在源上不存在"，
    #     **不进失败计数**；处置是"等上游补"。
    #   · `failed`（我们没取到）——**这才是失败**；处置是"我们改解析"。
    #   压在一起 ⇒ **永远分不清"该等谁"**。
    not_on_source: list[str] = []
    failed: list[str] = []
    for code in codes:
        try:
            reg.get(code)
            got += 1
        except RangeParseError as e:
            # grid.py:115 —— 页面在，但站位格数不对 ⇒ 我们的解析问题
            failed.append(f"{code}｜**解析不出**：{e}")
        except PrtsError as e:
            if "页面不存在" in str(e):
                # client.py:197 —— 源上没有这一页
                not_on_source.append(f"{code}｜{e}")
            else:
                # ⚠ **只有拿到"页面不存在"这条正面证据才算源上没有。**
                #   别的 `PrtsError`（403／超时／…）一律算失败——
                #   否则就是把"**我们没取到**"伪装成"**源上没有**"，
                #   那是**方向相反的同一种病**：又是两种不同的空压成一个值。
                failed.append(f"{code}｜**取数失败**（非「页面不存在」）：{e}")
        except Exception as e:                                     # noqa: BLE001
            failed.append(f"{code}｜未知异常 {type(e).__name__}：{e}")
    reg.save()

    lines = [f"代号 {len(codes)} 个：取到 {got} 个，落盘 {reg.index_path.name}"]
    if not_on_source:
        lines.append(f"  · **源上没有 {len(not_on_source)} 个**（记 `not_on_source`，"
                     f"**不是失败、不进失败计数**；处置＝等上游补）：")
        lines += [f"      {x}" for x in not_on_source]
    if failed:
        # ★ **失败项逐条列出，不许截断**——"只报前 N 条"会让"共几个失败"重新变成猜的。
        # （原先写的是 `failed[:8]`，2026-09-20 第一次实跑时当场吃掉了 2 条。）
        lines.append(f"  · ⛔ **失败 {len(failed)} 个**（我们没取到；处置＝改解析）：")
        lines += [f"      {x}" for x in failed]
    msg = "\n".join(lines)
    return ("failed" if failed else "ok"), msg


def _report_external() -> tuple[str, str]:
    """外部输入不重建——只如实报告在不在。"""
    box = DATA / "operbox"
    skl = DATA / "skland"
    nb = len(list(box.glob("*"))) if box.exists() else 0
    ns = len(list(skl.glob("*"))) if skl.exists() else 0
    return "ok", (f"外部输入（**不可重建**）：operbox/ {nb} 个文件、skland/ {ns} 个文件"
                  "——缺了不影响本脚本 rc，但名册会退档")


# ---------------------------------------------------------------- 跑

@dataclass
class Result:
    key: str
    status: str               # ok / failed / skipped
    seconds: float
    message: str


class Progress:
    """把「哪一步在跑、跑到哪了」写成 **JSONL 文件** —— 给界面渲染进度条用。

    ★ 为什么是**文件**而不是管道：本仓记过一条硬约束 —— 本机沙箱下用管道捕获
    子进程输出会 **EPERM**（`_run_step` 那条注释就是它）。所以父子之间的进度
    通道走**普通文件**：子进程 append 一行、父进程按偏移量增量读，谁也不碰管道。

    事件形状（一行一个 JSON）：
        {"ev":"plan","steps":[{"key":…,"title":…}, …]}
        {"ev":"step","key":…,"state":"run"}
        {"ev":"tick","key":…,"done":N,"total":M}
        {"ev":"step","key":…,"state":"ok|fail|skip","sec":1.2,"msg":"…"}
        {"ev":"summary","ok":N,"failed":N}
    """

    def __init__(self, path: str | None) -> None:
        self.path = path

    def _w(self, obj: dict) -> None:
        if not self.path:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except OSError:
            pass                       #: 进度写不进去不该让建库失败

    def plan(self, steps: list) -> None:
        self._w({"ev": "plan",
                 "steps": [{"key": s.key, "title": s.title} for s in steps]})

    def run(self, key: str) -> None:
        self._w({"ev": "step", "key": key, "state": "run"})

    def done(self, key: str, state: str, sec: float, msg: str = "") -> None:
        self._w({"ev": "step", "key": key, "state": state,
                 "sec": round(sec, 1), "msg": msg[:300]})

    def tick(self, key: str, done: int, total: int, *, bytes_: int = 0) -> None:
        """报一次进度（子进程往这个文件 append，界面按偏移量增量读）。

        `bytes_` 是**累计已下载字节** —— 界面拿两次 tick 的差 ÷ 时间差算速度。
        给不出就写 0，界面只画百分比、不编速度。
        """
        self._w({"ev": "tick", "key": key, "done": int(done), "total": int(total),
                 "bytes": int(bytes_)})

    def summary(self, ok: int, failed: int) -> None:
        self._w({"ev": "summary", "ok": ok, "failed": failed})


def skipped_by_datapack(step: Step) -> bool:
    """这一步能不能因为"数据包已装入"而跳过。

    只对 **enemydb.sqlite** 成立：它整库来自数据包（纯 prts 派生）。别的步骤不能跳
    ——`akdb.sqlite`／`stage 表` 的主体是游戏本体数据（不在包里），`关卡文件`同理。
    地块字典那一份不需要在这里判：它是**缓存文件**，装包时已刷过 mtime，
    `db build` 自己会用它。
    """
    if step.key != "enemydb.sqlite":
        return False
    return (DATA / "datapack.json").is_file() and (DATA / "enemydb.sqlite").is_file()


def _run_step(step: Step, *, offline_only: bool,              progress: "Progress | None" = None,
              logs_dir: Path | None = None, quiet: bool = False) -> Result:
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
            status, msg = fn()
        except Exception as e:                                     # noqa: BLE001
            return Result(step.key, "failed", time.time() - t0, f"{type(e).__name__}: {e}")
        if status not in ("ok", "skipped", "failed"):
            return Result(step.key, "failed", time.time() - t0,
                          f"内部函数返回了不认识的状态 {status!r}")
        return Result(step.key, status, time.time() - t0, msg)

    # ⚠ 子进程**不抓管道**（本机沙箱下会 EPERM）。两种处置：
    #   · 平时：stdout/stderr **继承**，进度实时可见；
    #   · 给界面渲染进度条时（`--progress-file`）：输出**改写成日志文件**
    #     （文件重定向不是管道，不受那条限制），失败时把日志尾部打出来 ——
    #     既不刷屏，诊断也不丢。
    argv = list(step.argv)
    log_path = None
    if progress is not None and progress.path:
        #: 让子步骤也往同一个进度文件里写 tick（只有声明支持的那一步会拿到这个参数）
        if step.wants_progress:
            argv += ["--progress-file", progress.path]
        if logs_dir is not None:
            log_path = logs_dir / ("%s.log" % step.key.replace(" ", "_"))
    try:
        if log_path is not None:
            with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
                cp = subprocess.run(argv, cwd=str(ROOT), check=False,
                                    stdout=lf, stderr=subprocess.STDOUT)
        else:
            cp = subprocess.run(argv, cwd=str(ROOT), check=False)
    except Exception as e:                                         # noqa: BLE001
        return Result(step.key, "failed", time.time() - t0, f"{type(e).__name__}: {e}")
    rc = cp.returncode
    msg = f"rc={rc}"
    if rc != 0 and log_path is not None and log_path.is_file():
        tail = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        if tail:
            msg += "｜日志尾部：" + " / ".join(t.strip() for t in tail[-3:])[:400]
        msg += "｜完整日志：%s" % log_path
    return Result(step.key, "ok" if rc == 0 else "failed", time.time() - t0, msg)


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


#: 库 ↔ "产出它的那一步"。★ **没跑的那一步不为它的缺失负责**——
#: `--offline` / `--only` 时，别的库本来就不该在；报成"缺表"就是假红。
DB_OWNER: dict[str, str] = {
    "akdb.sqlite": "akdb.sqlite",
    "enemydb.sqlite": "enemydb.sqlite",
    "prts-notes.sqlite": "prts-notes.sqlite",
}


def _reconcile(ran: dict[str, str]) -> tuple[list[str], list[str]]:
    """`ran`：步骤 key → 状态（ok/failed/skipped/notrun）。返回 (问题, 提示)。问题 ⇒ rc=1。"""
    problems: list[str] = []
    notes: list[str] = []
    counts = _row_counts()
    seen: dict[str, dict[str, int]] = {}
    for db, t, n, _why in counts:
        seen.setdefault(db, {})[t] = n

    for db, musts in MUST_HAVE_ROWS.items():
        owner = DB_OWNER.get(db, "")
        st = ran.get(owner, "notrun")
        got = seen.get(db)
        if st in ("skipped", "notrun"):
            # ★ **"那一步没跑" ≠ "这个库不在"**——同族第三例。
            # `--only stage 表,enemydb` 时 akdb 那步没跑，但它就在盘上、行数齐全；
            # 这时报一句"akdb 没建"就是**假信号**。库在且有行 ⇒ 什么都不说。
            if got and any(v > 0 for v in got.values()):
                continue
            notes.append(f"{db} 没建 —— 它的那一步（`{owner}`）本次"
                         + ("**被 `--offline` 跳过**" if st == "skipped"
                            else "**没在 `--only` 里**"))
            continue
        if got is None:
            problems.append(f"{db} 建不出来（表都没读到），而它的那一步报的是 {st}")
            continue
        for t in musts:
            if t not in got:
                problems.append(f"{db} 少了表 `{t}`（必须在）")
            elif got[t] == 0:
                problems.append(f"{db}.{t} **0 行**（必须在，空了说明这一步没做成）")

    for db, allows in MAY_BE_EMPTY.items():
        got = seen.get(db)
        if got is None:
            continue
        for t, reason in allows.items():
            if got.get(t) == 0:
                notes.append(f"{db}.{t} 是 0 行 —— {reason}")
    return problems, notes


def _gamedata_count() -> tuple[int, int]:
    """`data/gamedata/` 的文件数与字节数。★ 它**按需增长**，不是不变量。"""
    gd = DATA / "gamedata"
    if not gd.exists():
        return 0, 0
    files = [f for f in gd.rglob("*") if f.is_file()]
    return len(files), sum(f.stat().st_size for f in files)



def _inventory() -> list[str]:
    """`data/` 的目录清单：文件/目录 + 大小；sqlite 再补**逐表行数**。

    ★ 单独做成一个可打印的东西，是为了让"重建前 vs 重建后"的对照**能被别人复现**，
    而不是只活在某一次汇报里。用法：跑之前 `--snapshot` 存一份，跑完再存一份，对比即可。
    """
    out: list[str] = []
    if not DATA.exists():
        return ["（data/ 不存在）"]
    for p in sorted(DATA.iterdir(), key=lambda x: x.name):
        if p.is_dir():
            files = [f for f in p.rglob("*") if f.is_file()]
            size = sum(f.stat().st_size for f in files)
            out.append(f"  [目录] {p.name + '/':<26} {len(files):>6} 个文件  {size:>14,} B")
        else:
            out.append(f"  [文件] {p.name:<26} {'':>6}            {p.stat().st_size:>14,} B")
    out.append("")
    out.append("  逐表行数：")
    for db, t, n, why in _row_counts():
        if t == "—":
            out.append(f"    {db:<20} {why}")
            continue
        flag = "⛔" if n < 0 else ("⚠ 空" if n == 0 else "  ")
        out.append(f"    {flag} {db:<20} {t:<20} {n:>8}" + (f"  ← {why}" if why else ""))
    # 外部输入单独点名：它们**不在**这份清单的重建范围里
    for name, note in (("operbox", "玩家从 MAA 导出，不可重建"),
                       ("skland", "要登录态，不可离线重建")):
        p = DATA / name
        n = len([f for f in p.rglob("*") if f.is_file()]) if p.exists() else 0
        out.append(f"    ⚠ {name + '/':<20} {'':<20} {n:>8}  ← {note}")
    return out


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
    ap.add_argument("--snapshot", action="store_true",
                    help="只打印 data/ 清单（文件＋大小＋逐表行数），不动手；"
                         "跑重建前后各存一份即可做对照")
    ap.add_argument("--only", metavar="KEYS",
                    help="只跑这些步骤（逗号分隔；用 --list 看有哪些 key）。"
                         "用于按需放行联网步骤，不必整跑")
    ap.add_argument("--progress-file", metavar="PATH",
                    help="把进度写成 JSONL 到该文件（界面据此渲染每步一条进度条）；"
                         "同时把各子步骤的输出改写成日志文件，失败时打印日志尾部")
    ap.add_argument("--quiet", action="store_true",
                    help="少说话（配 --progress-file 时用：屏幕交给进度条）")
    args = ap.parse_args()

    wanted: set[str] | None = None
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        unknown = wanted - {s.key for s in STEPS}
        if unknown:
            print(f"⛔ 不认识的步骤：{sorted(unknown)}", file=sys.stderr)
            print(f"   可用：{[s.key for s in STEPS]}", file=sys.stderr)
            return 2

    if args.snapshot:
        print(f"data/ 清单（快照）—— {DATA}")
        print("=" * 78)
        for line in _inventory():
            print(line)
        return 0

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
        #: ★ 2026-09-28 改成**提示**而不是拒跑：这批源表现由 `gamedata 源表` 那一步
        #: 自己联网取（`cache --fetch-gamedata`）。原先是"报错 + 让玩家去 GitHub 手下"，
        #: 而全新机器上首启必然走到这里 ⇒ 那等于首启必挂。
        print(f"  · gamedata 源表还没有：{GAMEDATA_DIR}")
        print(f"    ⇒ 由 `gamedata 源表` 那一步联网取（{GAMEDATA_SRC}）；离线步骤排在它后面")
    print(f"  data/ 现有：{sorted(p.name for p in DATA.iterdir()) if DATA.exists() else '（无）'}")

    if args.dry_run:
        print("\n== 计划（--dry-run，不动手） ==")
        for s in STEPS:
            #: ★ 干跑必须认 `--only`：真跑那条循环（下面 L52x）会跳过不在清单里的步骤，
            #: 而干跑原先**不看** wanted ⇒ 明明只用跑三步，它把八步全印成「要跑」。
            #: 仪器说错话比不说话坏：2026-09-27 我就是照它那行读数差点裁定
            #: 「`--only` 没生效」。标记分三档，与真跑的行为一一对应。
            if wanted is not None and s.key not in wanted:
                mark = "不在 --only 里"
            elif args.offline and s.kind == "online":
                mark = "跳过"
            else:
                mark = "要跑"
            print(f"  [{mark}] {s.key:<18} {s.kind:<9} {s.eta:<12} {s.produces}")
        return 0

    progress = Progress(args.progress_file)
    if args.progress_file:
        #: 每次都从头写（旧事件留着会让界面把上一次的进度也画出来）
        try:
            with open(args.progress_file, "w", encoding="utf-8"):
                pass
        except OSError as e:
            print(f"⚠ 进度文件写不了（{e}）—— 照常跑，只是界面没有进度条", file=sys.stderr)
            progress = Progress(None)
    logs_dir: Path | None = None
    if args.progress_file:
        logs_dir = Path(tempfile.mkdtemp(prefix="rios-rebuild-logs-"))
    to_run = [s for s in STEPS if wanted is None or s.key in wanted]
    progress.plan(to_run)

    if not args.quiet:
        print("\n== 步骤 ==")
        print("  ⚠ 本脚本**只加不删**：它不删除任何文件；重建 = 覆盖写。")
    results: list[Result] = []
    for s in to_run:
        #: ★ 数据包已装入 ⇒ 跳过"抓 prts.wiki 建敌人库"这一步（2026-09-27）。
        #: 判据是**标记文件 + 库在位**两条都成立；少一条就照常自己抓。
        #: 不跳的话，装进来的库下一轮会被重抓覆盖 —— 那个包就白装了。
        if skipped_by_datapack(s):
            r = Result(s.key, "skipped", 0.0,
                       "来自数据包（要自己重抓就删掉 data/datapack.json）")
            results.append(r)
            progress.done(s.key, "skip", 0.0, r.message)
            print(f"  ⏭ skipped（{r.seconds:.1f}s）{r.message}")
            continue
        if not args.quiet:
            print(f"\n---- {s.key}｜{s.title} ----")
            print(f"     来源：{s.source}")
            print(f"     前提：{s.needs}　预计：{s.eta}")
        progress.run(s.key)
        r = _run_step(s, offline_only=args.offline, progress=progress,
                      logs_dir=logs_dir, quiet=args.quiet)
        results.append(r)
        progress.done(s.key, {"ok": "ok", "failed": "fail",
                              "skipped": "skip"}[r.status], r.seconds, r.message)
        icon = {"ok": "✅", "failed": "⛔", "skipped": "⏭"}[r.status]
        print(f"  {icon} {r.status}（{r.seconds:.1f}s）{r.message}")
    progress.summary(sum(1 for r in results if r.status == "ok"),
                     sum(1 for r in results if r.status == "failed"))

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

    problems, notes = _reconcile({r.key: r.status for r in results})

    ngd, sgd = _gamedata_count()
    print("\n  ⚠ data/gamedata/：%d 个文件、%s MB —— **按需缓存**，没有重建命令，"
          % (ngd, f"{sgd / 1048576:.1f}"))
    print("     **它不是一个不变量**：访问哪个键就落哪一份，所以别把「共 N 份」写进判据。")
    print("     合规红线：它被 .gitignore 忽略 ⇒ 留在缓存里就不分发；"
          "**任何 level_*.json 都不得 git add**（THIRD-PARTY.md）。")

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
