#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：练度解析（名册与计划合起来之后的那一组面板入参）。

## 对的是什么

`ak_tactic/verify.py:548-569` 的 `Verifier._entry(d, roster)`，外加它的
`_by_name`（`:571-577`）。这是「名册／计划读进来了」到「有面板入参可用」之间的
那一步——也就是两份输入**第一次被真的用上**的地方。

## 为什么不用起 sim 当 oracle

`_entry` 只读 `roster` / `d` 两样，另一处是 `self._by_name`。所以拿一个只带
`calc` 的替身对象把**真实方法**当纯函数调即可，oracle 依旧是原版。

## 覆盖面

* `fixtures/` 下**全部 24 份打法夹具** × 真夹具名册，逐条部署对拍；
* 另加一组合成用例，逐条走 `_entry` 的各道口径。

## 原版里几处容易抄混的

* 基准**按名字**查名册（与名册的键口径一致），六项练度**打法里写了就覆盖**，
  判据是 `is not None`——所以 `elite: 0` 是一次**有效覆盖**，不是「没写」。
* 三条 `setdefault`（elite→0、level→1、potential→1）只在**键整个不存在**时
  生效；基准来自名册时那三个键一定在，所以它们只对「名册里没有这个人」的
  那条路有意义。
* `char_id` 缺失时按**名字**回数据里找，跳过 `TRAP`/`TOKEN`，取**行序上的
  第一个**。这一步是 Go 侧最容易做错的地方：用 map 迭代会随机挑到同名 id。
* `trust` **只有打法能给**（名册那一份结构里没有 trust 这一项）。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `Verifier._entry`，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/练度.json`，**不 import `ak_tactic`**。

★ 这一套要冻**四样**，少一样 check 档就复现不出当前这一份判据：

1. **逐份打法的期望值**：键带输入身份 `("loadout", 夹具名, 打法内容 sha16, 名册 sha16)`；
2. **查询集**：`fixtures/` 下带 `deploys` 的那些打法（**它会长大** ⇒ 与冻的那一批对账）；
3. **判定参数**：合成用例要用的两个名字（`in_roster` / `outside`）——它们是
   名册与数据表的产物，**不在冻的那份里就造不出合成用例**；
4. **失败也是期望值**：本套有一支判据是「**两边都拒**」（`both_refused`）。
   把「Python 侧抛了什么」录成值，check 档才复现得出那一支——
   录成「没有这个键」会把它读成**通道错**，而那是两种完全不同的东西。

⚠ **`fixtures/` 是活的注册表**：另一个会话加一份打法夹具，这里的分母就变。
所以查询集要进对账：**内容身份住在键里**，改它得到的是「键配不上」＝
**对象集变了**那个形状 ⇒ 本套的批次记录**不参与判定**，`--control` 的 **P4 不适用**
（探针会自己这么说，具名）。

用法:
    python tools\\check_loadout_go.py
    python tools\\check_loadout_go.py --mutate
    python tools\\freeze_baseline.py --record 练度
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
FIXDIR = ROOT / "fixtures"
ROSTER_FIX = FIXDIR / "roster_max_modelled.json"

KEYS = ("char_id", "elite", "level", "potential", "trust", "module",
        "module_level")


def j(text: str) -> bytes:
    return text.encode("utf-8")


def plan_text(op: str, extra: str = "") -> bytes:
    return j('{"stage":"1-7","deploys":[{"operator":"%s","position":[1,1]%s}]}'
             % (op, extra))


def go_loadout(plan: Path, roster: Path | None) -> tuple[bool, object]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    spec = {"plan": str(plan), "roster": str(roster) if roster else ""}
    req = json.dumps({"id": 1, "cmd": "loadout", "spec": spec}) + "\n"
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
    return True, resp["loadout"]


_STUB = None


def stub():
    """只带 `calc` 的替身 + **真实方法**。全表只建一次（冻结档下根本不会建）。"""
    global _STUB
    if _STUB is None:
        _STUB = make_authority()
    return _STUB


def make_authority():
    """一个只带 `calc` 的替身 + 真实方法。"""
    from ak_tactic.operator import OperatorCalculator
    from ak_tactic.verify import Verifier

    class Stub:
        _by_name = Verifier._by_name
        _entry = Verifier._entry

        def __init__(self, calc):
            self.calc = calc

    return Stub(OperatorCalculator())


def plan_records() -> list[dict]:
    """查询集：`fixtures/` 下带 `deploys`/`deploy` 的那些打法（**内容 sha16 当身份**）。

    ★ 数据侧取数（只读文件字节），**不 import `ak_tactic`** ⇒ 冻结档也跑得动。
    ★ `fixtures/` 是**活的注册表**（另一个会话会加夹具），所以这一份要进对账。
    """
    out = []
    for f in sorted(FIXDIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            continue
        if isinstance(d, dict) and ("deploys" in d or "deploy" in d):
            out.append({"name": f.name, "sha16": GB.file_sha16(f),
                        "roster_sha16": GB.file_sha16(ROSTER_FIX)
                        if ROSTER_FIX.is_file() else "-"})
    return out


def py_loadout_wants(plan_path: Path, roster_path: Path | None) -> dict:
    """期望值：**整份打法**里每条部署的练度六项。

    ★ 成功 ⇒ `{"wants": [...]}`；**Python 侧抛了 ⇒ `{"py_error": "…"}`**。
    失败也是期望值（本套有一支判据就是「两边都拒」）——把它录成值，
    check 档才复现得出那一支；录成「缺键」会被读成通道错。
    """
    from ak_tactic.plan import Plan, Roster
    try:
        plan = Plan.load(plan_path)
        ros = Roster.from_json(roster_path) if roster_path else Roster.empty()
        return {"wants": [stub()._entry(d, ros) for d in plan.deploys]}
    except Exception as exc:                                # noqa: BLE001
        return {"py_error": "%s: %s" % (type(exc).__name__, exc)}


def py_loadout_names() -> dict:
    """判定参数：合成用例要用的两个名字（**名册与数据表的产物**，必须冻住）。"""
    from ak_tactic.plan import Roster
    ros = Roster.from_json(ROSTER_FIX)
    in_roster = ros.names()[0]
    #: 一个**在数据里、但不在名册里**的真干员名——用来走 `_by_name` 那条回退。
    chars = stub().calc._load_chars()
    outside = None
    for _cid, c in chars.items():
        nm = c.get("name")
        if nm and nm not in ros and c.get("profession") not in ("TRAP", "TOKEN"):
            outside = nm
            break
    if outside is None:
        GB._channel_fail("★ 找不到「在数据里但不在名册里」的干员名，合成用例造不出来")
    return {"in_roster": in_roster, "outside": outside}


def main() -> int:
    G = GB.bind("练度", __file__)

    print("Go 侧仪器：%s" % GO_BIN)
    if G.mode == GB.CHECK:
        #: ★ 这一行**只用来打印**，但它在冻结档会把 `ak_tactic` 拉进来 ⇒
        #: 拦截器当场响 ⇒ 整轮以「未转完」收场（实测过：rc 由 6 变成 1）。
        #: 所以它不是「无关紧要的 print」，而是**必须挪进分支**的一处 import。
        print("Python 侧权威（默认档）：ak_tactic.verify 的 Verifier._entry/_by_name")
    else:
        import ak_tactic.verify as V
        print("Python 侧权威：ak_tactic.verify 的 Verifier._entry/_by_name（%s）"
              % Path(V.__file__).name)
    print()

    #: ③ 判定参数：合成用例要用的两个名字（Python/数据侧产物）⇒ 与期望值一起冻住。
    names = G.expect(("consts", "loadout_names"), py_loadout_names)
    in_roster, outside = names["in_roster"], names["outside"]

    #: ② 查询集：`fixtures/` 下带 deploys 的那些打法。**活的那一份**单独算，
    #: 用来与冻的那一批对账（下面 `coverage`）。
    live_plans = plan_records()
    if G.mode == GB.RECORD:
        #: 把「这一次录的是哪一批打法」记成一条**可读的**记录（含内容 sha16）。
        #: 冻结档**不读它**用于判定——它回答「这份基线录的是哪一批」，
        #: 而 `--check` 的「改值」栏会量到它。
        #: ⇒ 本套的批次记录**不被消费**，所以 `--control` 的 **P4 不适用**
        #: （与文件头那条一致；工具会自己具名说清为什么不适用）。
        G.expect(("query", "loadout_plans"), lambda: live_plans)

    #: 合成用例表（**表本身在脚本里**；每例的身份用它的**内容 sha16**）。
    cases = [
        ("名册有人 / 打法不写", plan_text(in_roster), ROSTER_FIX, "基准来自名册"),
        ("名册有人 / 打法覆盖 elite+level",
         plan_text(in_roster, ',"elite":1,"level":55'), ROSTER_FIX, "打法覆盖练度"),
        ("名册有人 / 打法写 elite:0",
         plan_text(in_roster, ',"elite":0'), ROSTER_FIX, "elite:0 是有效覆盖"),
        ("名册有人 / 打法覆盖 module",
         plan_text(in_roster, ',"module":"uniequip_001","module_level":3'),
         ROSTER_FIX, "打法覆盖模组"),
        ("名册有人 / 打法把 module 覆盖成空串",
         plan_text(in_roster, ',"module":""'), ROSTER_FIX, "module 空串是有效覆盖"),
        ("名册有人 / 打法写 trust", plan_text(in_roster, ',"trust":100'),
         ROSTER_FIX, "trust 只有打法能给"),
        ("名册没人 / 打法写全 elite+level",
         plan_text(outside, ',"elite":2,"level":80'), ROSTER_FIX,
         "char_id 走 _by_name 回退"),
        ("名册没人 / 打法写全且带 potential",
         plan_text(outside, ',"elite":0,"level":1,"potential":6'), ROSTER_FIX,
         "名册没人时 setdefault 生效"),
        ("名册没人 / 名字数据里也找不到",
         plan_text("不存在的干员", ',"elite":1,"level":1'), ROSTER_FIX,
         "两边都找不到 → 报错"),
        ("名册没人 / 打法只写 elite", plan_text(outside, ',"elite":2'), ROSTER_FIX,
         "练度没着落 → 报错"),
        ("没有名册文件 / 打法写全",
         plan_text(outside, ',"elite":2,"level":80'), None, "无名册文件仍可解析"),
        ("没有名册文件 / 打法不写", plan_text(in_roster), None,
         "无名册且打法没写 → 报错"),
    ]

    def case_key(label: str, blob: bytes, roster_path: Path | None):
        """一例的键：**身份用内容 sha16**（临时目录名每轮都不同，不能进键）。"""
        return ("loadout", label, GB.sh16(blob),
                GB.file_sha16(ROSTER_FIX) if roster_path else "-")

    #: ★ 对账要把**所有会变成键的对象**都算进来（夹具 ＋ 合成用例）。
    #: 只算一半的话，另一半会被读成「冻着、这次没问」而把整轮判成 rc=6
    #: ——实测就是这么栽的：夹具 24 ＋ 合成 12，只列举了 24。
    live_records = [(r["name"], r["sha16"], r["roster_sha16"]) for r in live_plans]
    live_records += [case_key(lb, bl, rp)[1:] for lb, bl, rp, _br in cases]
    cov = G.coverage("loadout", live_records)
    covered = {tuple(x) for x in cov.covered} if G.mode == GB.CHECK else None

    def uncovered(key) -> bool:
        return G.mode == GB.CHECK and tuple(key[1:]) not in covered

    mutate = "--mutate" in sys.argv
    seen: dict[str, int] = {}
    bad = 0
    compared = 0
    both_refused = 0

    def check(label: str, plan_path: Path, roster_path: Path | None, key):
        nonlocal bad, compared, both_refused
        ok, got = go_loadout(plan_path, roster_path)
        #: ★ 期望值只能从这里来：默认档现调 Python，冻结档读冻的那份
        #: （**含「Python 侧抛了」这一支**）。
        rec = G.expect(key, lambda: py_loadout_wants(plan_path, roster_path))
        if "py_error" in rec:
            wants, py_ok, py_err = None, False, rec["py_error"]
        else:
            wants, py_ok, py_err = rec["wants"], True, ""
        if not ok or not py_ok:
            if not ok and not py_ok:
                both_refused += 1
                return
            bad += 1
            print("✗ %s —— Go ok=%s（%s） Python ok=%s（%s）"
                  % (label, ok, got if not ok else "-",
                     py_ok, py_err if not py_ok else "-"))
            return
        compared += 1
        if mutate and compared == 1:
            got = json.loads(json.dumps(got))
            got[0]["level"] = 999
        if len(got) != len(wants):
            bad += 1
            print("✗ %s —— 条数 Go=%d Python=%d" % (label, len(got), len(wants)))
            return
        for i, (g, w) in enumerate(zip(got, wants)):
            for k in KEYS:
                if g.get(k) != w.get(k):
                    bad += 1
                    print("✗ %s 第 %d 条 %s：Go=%r Python=%r"
                          % (label, i, k, g.get(k), w.get(k)))

    #: ---- 全量夹具 × 真夹具名册 ----
    seen["全量夹具 × 真名册"] = len(live_plans)
    for r in live_plans:
        key = ("loadout", r["name"], r["sha16"], r["roster_sha16"])
        if uncovered(key):
            #: 未覆盖的**不比**（它在对账里已具名）——猜＝自己写一份期望值。
            continue
        check("夹具 %s" % r["name"], FIXDIR / r["name"], ROSTER_FIX, key)

    #: ---- 合成用例 ----
    print("合成用例用的两个名字：名册里有的「%s」、只在数据里的「%s」"
          % (in_roster, outside))
    print()

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for n, (label, blob, roster_path, br) in enumerate(cases, 1):
            #: ★ 行使计数**按用例表走**，与覆盖与否无关：
            #: 它量的是「这套判据的口径有没有被测到」，不是「这次比了几例」。
            seen[br] = seen.get(br, 0) + 1
            p = tdp / ("c%d.json" % n)
            p.write_bytes(blob)
            key = case_key(label, blob, roster_path)
            if uncovered(key):
                continue
            check(label, p, roster_path, key)

    print()
    if G.mode == GB.CHECK and not cov.ok:
        print(cov.report("loadout", len(live_plans)))
        #: ★ 两种因分开列：**同一份夹具换了内容**与**多/少了几份夹具**都落在
        #: extra/missing 两栏、长得一样，而下一个人要靠这句话决定重录还是查对象集。
        ex = {g[0] for g in cov.extra}
        ms = {g[0] for g in cov.missing}
        chg, add, gone = sorted(ex & ms), sorted(ex - ms), sorted(ms - ex)
        if chg:
            print("  · ★ **内容变了**（同一份夹具、内容 sha 变了，%d 份）：%s"
                  % (len(chg), "、".join(chg[:8])))
        if add:
            print("  · **对象集变了**（新增，%d 份）：%s"
                  % (len(add), "、".join(add[:8])))
        if gone:
            print("  · **对象集变了**（这次没问、但冻着，%d 份）：%s"
                  % (len(gone), "、".join(gone[:8])))
        print()
    print("已比：练度解析；全量夹具 %d 份（× 真名册）＋合成 %d 例，"
          "共 %d 例逐字段比、%d 例两边都拒"
          % (len(live_plans), len(seen) - 1, compared, both_refused))
    print("★ 行使计数（每道口径各走了几例）：")
    for b, n in sorted(seen.items(), key=lambda kv: kv[0]):
        print("    %-24s %d" % (b, n))
    expect = ("基准来自名册", "打法覆盖练度", "elite:0 是有效覆盖", "打法覆盖模组",
              "module 空串是有效覆盖", "trust 只有打法能给",
              "char_id 走 _by_name 回退", "名册没人时 setdefault 生效",
              "两边都找不到 → 报错", "练度没着落 → 报错", "无名册文件仍可解析",
              "无名册且打法没写 → 报错", "全量夹具 × 真名册")
    unchecked = [b for b in expect if seen.get(b, 0) == 0]
    print()
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
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
    print("结论：%d 例逐字段一致（另 %d 例两边都拒）" % (compared, both_refused))
    if bad:
        #: 覆盖部分真的不一致 ⇒ 判据红，优先于「基线该重录」。
        return 1
    if G.mode == GB.CHECK and not cov.ok:
        #: 覆盖部分一致，但**对象集/内容变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
