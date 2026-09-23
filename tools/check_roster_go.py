#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：Go 直读练度名册。

## 对的是什么

`ak_tactic/plan.py:186-238` 的 `Roster.from_json`——模拟器真正吃的那份名册。
期望值直接调它，不自己重写口径。

## 为什么这一件必须验

名册是本树里**唯一一处 Go 还没有入口**的输入（关卡／敌人／干员三层早已搬完）。
目标里写着「Go 直读 gamedata ＋ 名册 ＋ 计划」，没有名册，Go 就算把折算全部
搬完也构造不出规格。

## 原版里几处像笔误、其实都是口径

* **跳过条件是 `own is False`（恒等）**：`"own": 0` 取真值也是假，但
  `0 is False` 为假 ⇒ **留着**。写成真值判断会整批丢人。
* **`level` / `potential` 缺省 1，靠 `or` 兜底**：`"level": 0` 不是 0 级而是
  1 级；而 `elite` 缺省 0，于是 `elite: 0` 就是 0。
* **表按 `name` 做键**，同名**后写覆盖前写**，位置留在第一次插入处。
* `charId` 取不到才退到 `id`；`module` 走 `or None`（空串也是「没带」）。
* 读文件是 `utf-8-sig`，BOM 必须先清。

## 一处**声明过的分歧**（Go 更严，且是响的）

原版对 `name` / `charId` 不做类型约束：`{"id": 5, "name": "丁"}` 会被收下，
`char_id` 就是数字 `5`。Go 侧**报错拒收**（大声失败优于静默收下一个下游
认不出的 id）。判据把它单列，要求「Go 拒 / 原版收」这一对**同时成立**才算
这条分歧被登记到，而不是被当成对拍失败。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `Roster.from_json`，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/名册.json`，**不 import `ak_tactic`**。

★ 冻的是**一条用例一份期望值**（`{"accept", "entries", "names", "why"}`），
键里带**这一例的输入身份**（例号 ＋ 该例文件字节的 sha16）——那批合成用例是
脚本写死的常量，可**真夹具那一例**（`fixtures/roster_max_modelled.json`）是
活文件，只记例号会在夹具被改之后拿一份旧输入的期望值去比新输入。

用法:
    python tools\\check_roster_go.py
    python tools\\check_roster_go.py --mutate
    python tools\\freeze_baseline.py --record 名册
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
FIXTURE = ROOT / "fixtures" / "roster_max_modelled.json"

BOM = b"\xef\xbb\xbf"


def j(text: str) -> bytes:
    return text.encode("utf-8")


#: (标签, 文件字节, 期望, 这一例行使的分支名)
CASES: list[tuple[str, bytes, str, tuple[str, ...]]] = [
    ("真夹具（顶层数组）", None, "parity", ("顶层数组", "缺省练度")),
    ("顶层 opers 字典",
     j('{"opers":[{"charId":"char_1","name":"甲","elite":2,"level":80,'
       '"potential":6,"module":"mod_1","module_level":2},'
       '{"charId":"char_2","name":"乙"}]}'),
     "parity", ("顶层 opers", "带模组", "缺省练度")),
    ("顶层 chars 字典",
     j('{"chars":[{"charId":"char_3","name":"丙","elite":1,"level":50}]}'),
     "parity", ("顶层 chars",)),
    ("两个键都没有", j('{"foo":1}'), "parity", ("字典没有 opers/chars",)),
    ("own 的三种写法",
     j('[{"id":"c1","name":"甲","own":false},'
       '{"id":"c2","name":"乙","own":0},'
       '{"id":"c3","name":"丙","own":true},'
       '{"id":"c4","name":"丁"}]'),
     "parity", ("own 为 false 跳过", "own 为 0 留下", "own 缺省留下")),
    ("id 退路与坏行",
     j('[{"id":"c1","name":"甲","charId":""},'
       '{"charId":"c2"},'
       '{"id":"c3","name":"丙"},'
       '"not-dict", 42, null]'),
     "parity", ("charId 空退到 id", "缺 name 跳过", "非对象行跳过")),
    ("缺省与 or 兜底",
     j('[{"id":"c1","name":"甲"},'
       '{"id":"c2","name":"乙","elite":0,"level":0,"potential":0,'
       '"module_level":0},'
       '{"id":"c3","name":"丙","level":"42"}]'),
     "parity", ("level/potential 缺省 1", "level=0 兜到 1", "字符串数字")),
    ("模组三态",
     j('[{"id":"c1","name":"甲","module":"","module_level":3},'
       '{"id":"c2","name":"乙","module":"uniequip_001"},'
       '{"id":"c3","name":"丙","module":null}]'),
     "parity", ("空模组=没带", "模组缺省")),
    ("同名重复",
     j('[{"id":"c1","name":"甲","level":10},'
       '{"id":"c2","name":"乙","level":20},'
       '{"id":"c3","name":"甲","level":90}]'),
     "parity", ("同名后写覆盖",)),
    ("带 BOM 的文件",
     BOM + j('{"opers":[{"charId":"c1","name":"甲","elite":2,"level":90}]}'),
     "parity", ("BOM",)),
    ("顶层是标量", j('"hello"'), "both-refuse", ("形状不认识",)),
    ("name/id 不是字符串",
     j('[{"id":5,"name":"丁"}]'), "go-refuse", ("非字符串 id（分歧）",)),
]


def go_roster(path: Path) -> tuple[bool, object]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "roster", "path": str(path)}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(line[0])
    if not resp.get("ok"):
        return False, resp.get("error") or ""
    return True, resp["roster"]


def py_roster(path: Path):
    from ak_tactic.plan import Roster

    r = Roster.from_json(path)
    rows = [dict(v, name=k) for k, v in r.entries.items()]
    return rows, r.names()


def py_roster_expect(path: Path) -> dict:
    """一条用例的期望值（**两种模式共用的形状**）。

    ★ `accept` 记「原版收不收」——判据里有「Go 拒 ∧ 原版收」那一支，
    所以**「收不收」本身就是期望值**，不只冻那几行字段。
    ★ `ak_tactic` 的 import 住在 `py_roster()` 里：冻结档下本函数不会被调到。
    """
    try:
        rows, names = py_roster(path)
    except Exception as exc:                                   # noqa: BLE001
        msg = "%s: %s" % (type(exc).__name__, exc)
        #: ★ 报错正文里带着**这一次的临时文件路径**（每次跑都不同）——它不是期望值的
        #: 一部分，冻进去等于录了一个「只对那一次成立」的值（实测：不换掉的话
        #: `--check` 天天报改值 1，那正是本仓记过的「永久假红等于没有判据」）。
        #: ⚠ 只在**这一支**（原版拒收）上换；判据判的是 `accept` 与那几行字段。
        return {"accept": False, "entries": [], "names": [],
                "why": msg.replace(str(path), "<case>")}
    return {"accept": True, "entries": rows, "names": names, "why": ""}


def py_authority() -> str:
    """那一行的文件名。冻结档下不 import，也就没有它。"""
    import ak_tactic.plan as P
    return Path(P.__file__).name


def main() -> int:
    G = GB.bind("名册", __file__)

    print("Go 侧仪器：%s" % GO_BIN)
    if G.mode == GB.CHECK:
        print("Python 侧权威：ak_tactic.plan.Roster.from_json"
              "（冻结档不 import：读的是 fixtures/golden/名册.json）")
    else:
        print("Python 侧权威：ak_tactic.plan.Roster.from_json（%s）" % py_authority())
    print()

    mutate = "--mutate" in sys.argv
    seen: dict[str, int] = {}
    bad = 0
    compared = 0
    diverged: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        for i, (label, blob, expect, brs) in enumerate(CASES):
            path = FIXTURE if blob is None else Path(td) / ("case%d.json" % i)
            if blob is not None:
                path.write_bytes(blob)
            for b in brs:
                seen[b] = seen.get(b, 0) + 1

            ok, got = go_roster(path)
            #: ★ 键里带这一例的**输入身份**：例号 ＋ 该例文件字节的 sha16
            #: （真夹具那一例的文件是活的，只记例号会在它被改之后比错对象）。
            e = G.expect(("roster", i, GB.file_sha16(path)),
                         lambda path=path: py_roster_expect(path))
            rows, names = e["entries"], e["names"]
            py_ok = e["accept"]
            py_err = e["why"]

            if expect == "both-refuse":
                if ok or py_ok:
                    bad += 1
                    print("✗ %s —— 期望两边都拒：Go ok=%s Python ok=%s"
                          % (label, ok, py_ok))
                continue
            if expect == "go-refuse":
                if ok or not py_ok:
                    bad += 1
                    print("✗ %s —— 期望「Go 拒 ∧ 原版收」：Go ok=%s Python ok=%s"
                          % (label, ok, py_ok))
                else:
                    diverged.append("%s（Go: %s）" % (label, got))
                continue

            if not ok:
                bad += 1
                print("✗ %s —— Go 拒了：%s" % (label, got))
                continue
            if not py_ok:
                bad += 1
                print("✗ %s —— 原版拒了：%s" % (label, py_err))
                continue
            compared += 1
            if mutate and compared == 1:
                got = json.loads(json.dumps(got))
                got["entries"][0]["level"] = got["entries"][0]["level"] + 1
            ge = got["entries"]
            if len(ge) != len(rows):
                bad += 1
                print("✗ %s —— 条数 Go=%d Python=%d" % (label, len(ge), len(rows)))
                continue
            for k, (g, w) in enumerate(zip(ge, rows)):
                for f in ("name", "char_id", "elite", "level", "potential",
                          "module", "module_level"):
                    if g.get(f) != w.get(f):
                        bad += 1
                        print("✗ %s 第 %d 行 %s：Go=%r Python=%r"
                              % (label, k, f, g.get(f), w.get(f)))
                        break
            if got["names"] != names:
                bad += 1
                print("✗ %s names：Go=%r Python=%r" % (label, got["names"], names))

    print()
    print("已比：练度名册；%d 例对拍（另 %d 例只判拒收）"
          % (compared, len(CASES) - compared))
    print("★ 行使计数（每道口径各走了几例）：")
    for b, n in sorted(seen.items(), key=lambda kv: kv[0]):
        print("    %-22s %d" % (b, n))
    unchecked = [b for _, _, _, brs in CASES for b in brs if seen.get(b, 0) == 0]
    print()
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
    if diverged:
        print("★ 已登记的分歧（要求「Go 拒 ∧ 原版收」同时成立，不算对拍失败）：")
        for d in diverged:
            print("    %s" % d)
        print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    if unchecked:
        print("结论：用例表没覆盖到 %s —— 判红（不是实现错，是判据自己瞎）"
              % "、".join(unchecked))
        return 1
    if not diverged:
        print("结论：登记分歧那一例没跑成「Go 拒 ∧ 原版收」—— 判红")
        return 1
    print("结论：%d 例逐字段一致（另含 1 例登记分歧、1 例两边都拒）" % compared)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
