#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：`sim` 的**查询形式**（Go 自造规格）与**旧形式**（送造好的规格）。

## 核心断言（差分）

同一关、同一计划、同一对 `allow_*`：

    sim(查询形式) 的判决  ≡  sim(buildspec 造出的规格) 的判决     逐路径相同
    两次回报里的 unsupported                                   必须相同
                                                        （查询形式**必须**带上它）

★ 这是**差分**：不比「判决对不对」（那是对拍台的活），只比**两条入参路径会不会
给出不同的判决**。规格是同一个生产者造的，判决就该逐位相同；不同 ⇒ 接线错了。

## 一处**具名排除**（不是容差）

`verdict.sim_ms` 是**墙钟计时**（这一局跑了多少毫秒），两次调用必然不同。
排除它，并把两侧的值印出来当证据 —— 它不是"可以差一点"，是**另一个量**。

## 三种结局（分母现算，别把「拒跑」算进「比了判决」）

`sim` 慢（每关约 1.5s），所以这一套跑**全部 24 份夹具**，但结局分三态：

  · 两边都跑出判决 → 比判决逐路径相同（这是真正的差分）；
  · 两边都以**同一条错**拒跑 → 比错误文本逐字相同（当前是「天桩没带召唤模板（甲）」
    ——`mech_config.farmland.devices[].child` 那条已登记的 unported 在**两条路上一样**）；
  · 一边 ok 一边拒跑 → **判红**（那正是接线错了的样子）。

★ 两种「有声的结局」都必须至少出现一次：全是拒跑 ⇒ 判决那条断言**一次都没行使**，
那套绿是零信息量的绿；全是 ok ⇒ 拒跑那条没行使。

## 四条硬约束各自的判据

| 约束 | 这里怎么证 |
|---|---|
| 判别不许猜 | 契约组：两种都不像 / 两种都像 / 缺 `allow_devices` / 缺 `allow_skills` **各必须具名失败**，且错误里要点到那个键 |
| `unsupported` 必须带回 | 查询形式的应答**必须有** `unsupported`（且等于 `buildspec` 的 `spec.unsupported`）；旧形式**必须没有**（旧契约未变） |
| `allow_*` 必须随查询送 | 契约组里那两条缺字段的用例（不许兜底） |
| 规格必须在跑之前取 | Go 侧那道 `life > 0` 断言 ＋ 本判据对每一例断言「判决里的 `life` 与规格里的 `life` 同源」（见 `check_life`） |

用法:
    python tools\\check_sim_selfspec_go.py
    python tools\\check_sim_selfspec_go.py --mutate
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
FIXDIR = ROOT / "fixtures"
ROSTER_FIX = str(FIXDIR / "roster_max_modelled.json")

#: 判决里**必须排除**的那一个字段：墙钟计时。排除它要印出来（见文件头）。
NONDET_VERDICT_FIELDS = ("sim_ms",)

#: 拒跑的两条路都该给同一句话。当前那一条是已登记的 unported（pile 的 child）。
KNOWN_REFUSAL = "没带召唤模板"


def go_call(reqs: list[dict]) -> list[dict]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    lines = [json.dumps(r) for r in reqs]
    p = subprocess.run([GO_BIN], input=("\n".join(lines) + "\n").encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    return [json.loads(x) for x in p.stdout.decode("utf-8", "replace").strip().splitlines()]


def diff(a, b, p: str = "") -> list[tuple[str, object, object]]:
    """逐路径比真差异（与 `check_buildspec_go.py` 同款：不整块 `!=`）。"""
    out: list[tuple[str, object, object]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append((p + "." + k, "<缺>", b[k]))
            elif k not in b:
                out.append((p + "." + k, a[k], "<缺>"))
            else:
                out += diff(a[k], b[k], p + "." + k)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((p + ".len", len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, "%s[%d]" % (p, i))
    elif a != b:
        out.append((p, a, b))
    return out


def query_body(name: str, *, allow_devices: bool = True,
               allow_skills: bool = False) -> dict:
    return {"plan": str(FIXDIR / name), "roster": ROSTER_FIX,
            "allow_devices": allow_devices, "allow_skills": allow_skills}


def build_readings() -> list[dict]:
    """每个夹具问三次：查询形式、buildspec（拿它当旧形式的规格）、旧形式。"""
    import check_specgo_go as C

    rows = C.real_specs()
    out: list[dict] = []
    for name, spec, err, lv in rows:
        if spec is None:
            raise SystemExit("生产规格抄不到（%s）：%s" % (name, err))
        q = {"id": 1, "cmd": "sim", "level": lv, "spec": query_body(name)}
        b = {"id": 2, "cmd": "buildspec", "level": lv, "spec": query_body(name)}
        rq, rb = go_call([q, b])
        if not rb.get("ok"):
            raise SystemExit("buildspec 失败（%s）：%s" % (name, rb.get("error")))
        built = rb["build_spec"]["spec"]
        ro, = go_call([{"id": 3, "cmd": "sim", "spec": built}])
        out.append({"name": name, "level": lv, "query": rq, "built": rb["build_spec"],
                    "old": ro, "spec": built})
    return out


def compare(readings: list[dict]) -> tuple[list[str], dict]:
    problems: list[str] = []
    cov = {"cases": 0, "both_ok": 0, "both_refused": 0, "same_error": 0,
           "unsupported_present": 0, "unsupported_equal": 0, "nondet_keys": {}}
    for r in readings:
        cov["cases"] += 1
        q, o = r["query"], r["old"]
        #: ① 结局必须一致（一边 ok 一边拒跑 = 接线错了）
        if bool(q.get("ok")) != bool(o.get("ok")):
            problems.append("%s：两种形式的结局不同 —— 查询 ok=%s（%s）／旧 ok=%s（%s）"
                            % (r["name"], q.get("ok"), str(q.get("error"))[:80],
                               o.get("ok"), str(o.get("error"))[:80]))
            continue
        if not q.get("ok"):
            cov["both_refused"] += 1
            if str(q.get("error")) != str(o.get("error")):
                problems.append("%s：两边都拒跑，但**理由不同**\n      查询：%s\n      旧  ：%s"
                                % (r["name"], str(q.get("error"))[:120],
                                   str(o.get("error"))[:120]))
            else:
                cov["same_error"] += 1
                if KNOWN_REFUSAL not in str(q.get("error")):
                    problems.append("%s：两边同因拒跑，但不是已知那条（%s）——"
                                    "拒跑的理由变了，本判据的登记要重看"
                                    % (r["name"], str(q.get("error"))[:80]))
        else:
            cov["both_ok"] += 1
            d = diff(q.get("verdict"), o.get("verdict"))
            real = [(p, x, y) for p, x, y in d
                    if not any(p == "." + f for f in NONDET_VERDICT_FIELDS)]
            nondet = [(p, x, y) for p, x, y in d
                      if any(p == "." + f for f in NONDET_VERDICT_FIELDS)]
            for p, _x, _y in nondet:
                cov["nondet_keys"][p] = cov["nondet_keys"].get(p, 0) + 1
            for p, x, y in real:
                problems.append("%s：判决在 %s 上不同（查询=%r 旧=%r）"
                                % (r["name"], p, x, y))
        #: ② `unsupported`：查询形式**必须**带（这是闸门不静默失效的唯一通道）
        if "unsupported" not in q:
            problems.append("%s：查询形式的应答**没有** `unsupported` —— "
                            "Python 侧靠它决定退回原版，缺了就是闸门静默失效"
                            % r["name"])
        elif not isinstance(q["unsupported"], list):
            problems.append("%s：查询形式的 `unsupported` 不是数组（%r）"
                            % (r["name"], q["unsupported"]))
        else:
            cov["unsupported_present"] += 1
            want = r["built"]["spec"].get("unsupported") or []
            if q["unsupported"] != want:
                problems.append("%s：查询应答的 unsupported 与自造规格里的不同\n"
                                "      应答=%s\n      规格=%s"
                                % (r["name"],
                                   json.dumps(q["unsupported"], ensure_ascii=False),
                                   json.dumps(want, ensure_ascii=False)))
            else:
                cov["unsupported_equal"] += 1
        #: ③ 旧形式的契约**未变**：不带 `unsupported`（规格本来就在调用方手上）
        if "unsupported" in o:
            problems.append("%s：旧形式的应答多了 `unsupported` —— 旧契约被改了"
                            % r["name"])
        #: ④ 约束 4：规格在跑之前取。★ 这里**不能**比 `verdict.life == spec.life`
        #: ——那两个 `life` 是**两个量**：规格里的是**初始**生命点，判决里的是
        #: **打完之后剩的**（这 24 份里有 5 份打完剩 0，正是漏怪漏光的那些关）。
        #: 第一版就是这么写的，于是 5 例假红（红的是判据，不是实现）。
        #: 正确的判据是两条：① 自造规格的初始生命点必须 > 0（跑之后取的会是 0）；
        #: ② 剩下的不可能比初始的多。
        if r["spec"].get("life", 0) <= 0:
            problems.append("%s：自造规格的 `life`=%r ≤ 0 —— 规格像是**跑完之后**取的"
                            "（权威那边跑完 life=0，那种规格一帧不跑就判负）"
                            % (r["name"], r["spec"].get("life")))
        if q.get("ok"):
            v = q.get("verdict") or {}
            left = v.get("life")
            if not (isinstance(left, int) and 0 <= left <= int(r["spec"].get("life", 0))):
                problems.append("%s：判决里剩下的 life=%r 落在 [0, %r] 之外"
                                % (r["name"], left, r["spec"].get("life")))
    return problems, cov


def contract_checks(levels: list[str]) -> list[str]:
    """四条硬约束的**契约组**：判别与必填字段都必须具名失败。"""
    problems: list[str] = []
    lv = levels[0]
    cases = [
        ("两种都不像", {"id": 1, "cmd": "sim", "level": lv, "spec": {"fps": 30}},
         ["stage", "plan"]),
        ("两种都像", {"id": 1, "cmd": "sim", "level": lv,
                   "spec": {"stage": "X", "plan": "p"}}, ["不许猜"]),
        ("缺 allow_devices", {"id": 1, "cmd": "sim", "level": lv,
                          "spec": {"plan": str(FIXDIR / "hsex8.json"),
                                   "roster": ROSTER_FIX, "allow_skills": False}},
         ["allow_devices"]),
        ("缺 allow_skills", {"id": 1, "cmd": "sim", "level": lv,
                         "spec": {"plan": str(FIXDIR / "hsex8.json"),
                                  "roster": ROSTER_FIX, "allow_devices": True}},
         ["allow_skills"]),
        ("不认识的键", {"id": 1, "cmd": "sim", "level": lv,
                    "spec": {"plan": str(FIXDIR / "hsex8.json"), "roster": ROSTER_FIX,
                             "allow_devices": True, "allow_skills": False,
                             "plans": "x"}}, ["plans"]),
    ]
    for label, req, want in cases:
        resp, = go_call([req])
        if resp.get("ok"):
            problems.append("契约组「%s」：**没失败**（静默选了一边，或兜了默认值）" % label)
            continue
        err = str(resp.get("error", ""))
        miss = [w for w in want if w not in err]
        if miss:
            problems.append("契约组「%s」：失败了但错误里没点到 %s（现得 %r）"
                            % (label, miss, err[:150]))
        else:
            print("  ✓ 契约组「%s」具名失败（点到 %s）" % (label, want))
    return problems


MUTATIONS = ("改查询应答判决里的一个标量", "改一条同因拒跑的错误文本",
             "把应答的 unsupported 抹成另一份", "把一条拒跑改成 ok（结局不一致）",
             "抹掉查询应答的 unsupported 字段")

#: 每处注入**打在哪个断言分支**上（写清楚：不然「5 处都判红」这句话说明不了
#: 它们各自独立——本仓对独立性的要求是「一个改动红几条」要能答）。
MUTATION_BRANCH = {
    "改查询应答判决里的一个标量": "判决逐路径相同",
    "改一条同因拒跑的错误文本": "两边都拒跑但理由不同",
    "把应答的 unsupported 抹成另一份": "unsupported 与自造规格逐位相同",
    "把一条拒跑改成 ok（结局不一致）": "两种形式结局一致",
    "抹掉查询应答的 unsupported 字段": "查询应答必须带 unsupported",
}


def mutate(readings: list[dict], which: str) -> list[dict]:
    """注入做在**读数**上（比较是纯函数，不重跑 Go）。

    ⚠ 第一版有两处注入是**空转**的（改 `spec.life`、往查询应答里塞一个没人读的
    `_flip` 键）：它们不落在任何被比较的对象上，于是「没红」并不说明守不住。
    ⇒ 现在每一处都打在**具名的那条断言**上，见 `MUTATION_BRANCH`。
    """
    out = copy.deepcopy(readings)
    for r in out:
        if which == "改查询应答判决里的一个标量" and r["query"].get("ok"):
            r["query"]["verdict"]["kills"] = int(r["query"]["verdict"]["kills"]) + 1
            return out
        if which == "改一条同因拒跑的错误文本" and not r["query"].get("ok"):
            r["query"]["error"] = str(r["query"].get("error", "")) + "（注）"
            return out
        if which == "把应答的 unsupported 抹成另一份":
            r["query"]["unsupported"] = ["这是一个与规格不同的理由 ×1"]
            return out
        if which == "把一条拒跑改成 ok（结局不一致）" and not r["query"].get("ok"):
            r["query"]["ok"] = True
            r["query"]["verdict"] = {"kills": 0, "life": 1}
            r["query"]["error"] = ""
            return out
        if which == "抹掉查询应答的 unsupported 字段":
            r["query"].pop("unsupported", None)
            return out
    return out


def echo_control(readings: list[dict]) -> tuple[list[str], dict]:
    """口径参数的**两层**控制：① 它被原样带进去了吗；② 它现在有可观测效果吗。

    ⚠ 第一版我写成「把 `allow_devices` 翻转 ⇒ 必须拒跑」，**期望是错的**：
    Go 的闸门里 `关卡装置 ×N` 那一行是 **unported**（Go 没有装置层，
    见 `unsupported.go` 的 `unportedLines`），所以翻不翻**都不该变**。
    那一版在 `plan-hs06` 上报的红是**判据错**，不是实现错。

    正确的两层：

      · **被带进去了**：翻转之后应答里的 `self_spec.allow_devices` 必须跟着翻。
        没有这一层，调用方分不出「按这个口径算了」与「这个参数被静默丢了」。
      · **还没有效果**：翻转前后**结局必须相同**，且前提是「闸门把那一行列为
        unported」。哪天那一行接上了（unported 里没有它了），**这条控制必须红**
        ——那时「无效果」的预期就过期了，要回来重写。
    """
    problems: list[str] = []
    cov = {"checked": 0, "echo_flipped": 0, "outcome_same": 0}
    for r in readings:
        echo = (r["query"].get("self_spec") or {})
        if "allow_devices" not in echo:
            problems.append("%s：查询应答的 `self_spec` 里**没有** `allow_devices` 回显 "
                            "—— 这个口径参数是否被带进去，调用方无从取证" % r["name"])
            continue
        if bool(echo["allow_devices"]) is not True:
            problems.append("%s：回显的 allow_devices=%r，与我送进去的 true 不符"
                            % (r["name"], echo["allow_devices"]))
            continue
        body = query_body(r["name"], allow_devices=False)
        resp, = go_call([{"id": 1, "cmd": "sim", "level": r["level"], "spec": body}])
        cov["checked"] += 1
        flip_echo = ((resp.get("self_spec") or {}) if resp.get("ok") else {}) or {}
        #: 翻转后若拒跑，`self_spec` 还在吗？我的实现在失败路径上也回填 self_spec ✓
        if not flip_echo:
            flip_echo = (resp.get("self_spec") or {})
        if flip_echo.get("allow_devices") is not False:
            problems.append("%s：翻转后回显没跟着变（现得 %r）—— 口径参数没被原样带进去"
                            % (r["name"], flip_echo.get("allow_devices")))
        else:
            cov["echo_flipped"] += 1
        #: 结局：预期**不变**，前提是那一行还列在闸门的 unported 里。
        gate_unported = [u for u in (r["built"].get("unported") or [])
                         if u.startswith("unsupported: ")]
        devices_unported = any("devices" in u for u in gate_unported)
        same = bool(resp.get("ok")) == bool(r["query"].get("ok"))
        if not devices_unported:
            problems.append("%s：闸门的 unported 里**没有** devices 那一行了 —— "
                            "「翻转无效果」这个预期可能已过期（那一行接上了？），"
                            "本控制要重写（现在 unported=%s）"
                            % (r["name"], json.dumps(gate_unported, ensure_ascii=False)[:120]))
        elif not same:
            problems.append("%s：翻转 `allow_devices` 之后结局变了（%s→%s）—— "
                            "与「那一行 unported、故无效果」的登记不符"
                            % (r["name"], r["query"].get("ok"), resp.get("ok")))
        else:
            cov["outcome_same"] += 1
        print("  ✓ 口径两层：%s 回显跟着翻（true→false）＋ 结局不变（那一行仍 unported）"
              % r["name"])
        break  #: 一例足够证明「这个参数进了被测分支且有回显」
    if not cov["checked"]:
        problems.append("口径控制组**一例都没行使** —— 这个控制是空转的")
    return problems, cov


def main() -> int:
    mutate_mode = "--mutate" in sys.argv
    print("Go 侧仪器：%s" % GO_BIN)
    print("差分对象：`sim` 的查询形式（Go 自造规格）vs 旧形式（送 buildspec 造出的规格）")
    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception as e:                                       # noqa: BLE001
        raise SystemExit("取不到缓存关卡清单：%s" % e)

    print()
    print("一 · 契约组（判别不许猜 ＋ 必填字段不许兜底）")
    cbad = contract_checks(levels)

    readings = build_readings()
    print()
    print("二 · 差分（分母现算：%d 份夹具，全部跑；`sim` 每关约 1.5s）" % len(readings))
    problems, cov = compare(readings)
    print("  两边都跑出判决 %d 例（比判决逐路径）／两边都以同一条错拒跑 %d 例"
          "（比错误文本逐字）" % (cov["both_ok"], cov["both_refused"]))
    print("  同因拒跑 %d 例（已知那条：%s…）" % (cov["same_error"], KNOWN_REFUSAL))
    print("  具名排除的字段（墙钟计时，不属于判决）：%s"
          % json.dumps(cov["nondet_keys"], ensure_ascii=False))
    print("  `unsupported`：查询形式带回来的 %d / %d 例；与自造规格逐位相同的 %d / %d 例"
          % (cov["unsupported_present"], len(readings),
             cov["unsupported_equal"], len(readings)))
    print()
    print("三 · 覆盖率（两种有声的结局都要真被行使）")
    c2: list[str] = []
    if not cov["both_ok"]:
        c2.append("一例都没跑出判决 —— 判决那条断言**一次都没行使**，这套绿是零信息量的")
    if not cov["both_refused"]:
        c2.append("一例都没拒跑 —— 拒跑那条断言没被行使")
    if not cov["unsupported_equal"]:
        c2.append("`unsupported` 一条都没比过")
    for m in c2:
        print("  ✗ %s" % m)
    if not c2:
        print("  ✓ 判决 %d 例 ＋ 拒跑 %d 例 ＋ unsupported %d 例，三种都真跑到了"
              % (cov["both_ok"], cov["both_refused"], cov["unsupported_equal"]))
    print()
    print("四 · 口径控制组（`allow_devices` 被带进去了吗 ＋ 它现在有没有效果）")
    fbad, fcov = echo_control(readings)
    for m in fbad:
        print("  ✗ %s" % m)
    print()

    problems = cbad + problems + c2 + fbad

    if mutate_mode:
        print("五 · 反向守卫（每处注入都要独立判红，且要打在**具名的那条断言**上）")
        if problems:
            print("★ 基线本身不干净 ⇒ 反向守卫无从成立")
            return 1
        bad = 0
        for which in MUTATIONS:
            m = mutate(readings, which)
            if m == readings:
                print("  ✗ 注入「%s」**没落到任何对象上**（空转）" % which)
                bad += 1
                continue
            mp, _c = compare(m)
            ok = bool(mp)
            if not ok:
                bad += 1
            print("  %s 注入「%s」→ %s   【打在：%s】"
                  % ("✓" if ok else "✗", which, "判红" if ok else "没红（守不住）",
                     MUTATION_BRANCH[which]))
        if bad:
            print("★ %d / %d 处注入没判红或空转" % (bad, len(MUTATIONS)))
            return 1
        print("  反向守卫成立：%d / %d 处注入都判红（各自打在一条不同的断言上）"
              % (len(MUTATIONS), len(MUTATIONS)))
        return 0

    if problems:
        print("★ %d 处不一致：" % len(problems))
        for m in problems[:20]:
            print("  · %s" % m)
        if len(problems) > 20:
            print("  · …（另有 %d 条）" % (len(problems) - 20))
        print("结论：自造规格的 `sim` 对拍**未通过**（%d 处）" % len(problems))
        return 1
    print("结论：%d 例差分一致（判决 %d 例逐路径相同、拒跑 %d 例同因、"
          "unsupported %d 例逐位相同）；契约组 5 条具名失败全成立"
          % (len(readings), cov["both_ok"], cov["both_refused"], cov["unsupported_equal"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
