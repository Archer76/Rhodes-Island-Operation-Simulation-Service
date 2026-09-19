"""调用 `rios-sim`：子进程 + 标准输入输出上的 JSON 行协议。

## 为什么是子进程而不是 Python 扩展

* 免掉 FFI 构建链（本机没有 MSVC/clang，`cgo` 那条路走不通）；
* 一次进程**批量**作业：进程启动约 3ms，一场 1-7 约几十微秒——搜索是"几千场"
  的量级，逐场起进程会把省下来的时间又还回去；
* 直接复用 `ak_tactic/parallel.py` 的多进程并行（每个工作进程各起一个 rios-sim）。

## 版本核对

`ping` 一次，比对协议版本。不核对的话，二进制与调用方不一致的症状是
"判决微妙地对不上"——那是最难查的一类错，所以在门口挡住。
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
from typing import Any, Iterable

#: 调用方认的协议版本，必须与 `rios-sim/main.go` 的 `protocolVersion` 一致
PROTOCOL_VERSION = 1

#: 规格里的这些字段两边都当"结果"，逐项对拍用
_COMPARE_FIELDS = ("won", "kills", "leaks", "deployed", "operator_deaths",
                   "spawns_placed", "spawns_total", "timed_out")


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent.parent


class EngineBinaryUnpinned(RuntimeError):
    """没钉住引擎二进制。

    ⚠ 这不是"找不到文件"那类错，是**拒绝**：不许悄悄挑一个能跑的（PM 2026-09-19 裁定）。
    """


def legacy_binary() -> pathlib.Path | None:
    """工作树里那枚预编译的 `rios-sim/rios-sim.exe`。

    ⚠ 它在 `.gitignore` 里 ⇒ **不入库、任何一次 Go 改动之后都会过期**，而各会话都从
    工作树构建 ⇒ 它看起来"一直能用"。2026-09-19 实测：它比本树最新 `.go` 旧 260 分钟、
    落后 16 个 rios-sim 提交，却让同一条 `--check` 从 48杀/221.6667s 读成 83杀/814.0333s。
    现在它**只用于把"旧了多少"写进报错消息**，不再作为回退项。
    """
    for name in ("rios-sim.exe", "rios-sim"):
        cand = repo_root() / "rios-sim" / name
        if cand.exists():
            return cand
    return None


def staleness_minutes(p: pathlib.Path) -> tuple[float, pathlib.Path] | None:
    """`p` 比本树最新的 `.go` 源旧多少分钟。返回 `(分钟, 那个 .go)`，不旧则 None。"""
    srcs = list((repo_root() / "rios-sim").rglob("*.go"))
    if not srcs or not p.exists():
        return None
    newest = max(srcs, key=lambda q: q.stat().st_mtime)
    delta = (newest.stat().st_mtime - p.stat().st_mtime) / 60.0
    return (delta, newest) if delta > 0 else None


def build_hint() -> str:
    """报错消息里给出的**那一条能直接粘的命令**——报错不附修法等于只报了一半。"""
    return ('cd rios-sim && go build -o "../out/acceptance/rios-sim-'
            '$(git -C .. rev-parse --short HEAD).exe" .  '
            '# 然后 RIOS_SIM_BIN=<该文件> 再跑')


def require_binary() -> pathlib.Path:
    """取**显式钉住**的引擎二进制。没钉就大声失败。

    ## 为什么默认值是"不许有默认值"

    先说事实（2026-09-19，同一条 `--check`、同一批 19 份、同一份基线，**只差这台仪器**）：

    * 未钉 ⇒ 落到工作树那枚 19:08 的 exe ⇒ `hsex8_max` 83杀/1漏/814.0333s，报 1 份不一致；
    * 钉住 ⇒ 当轮私有构建 ⇒ 48杀/3漏/221.6667s，19/19 一致。

    两台仪器都不报错、都给出"看起来正常"的数。**"默认仪器是老的"比"没有默认仪器"危险**：
    前者静默，后者立刻可见。所以这里**不回退**——工作树那枚只用来把"旧了多少分钟"写进消息。
    """
    raw = (os.environ.get("RIOS_SIM_BIN") or "").strip()
    if not raw:
        legacy = legacy_binary()
        extra = ""
        if legacy is not None:
            st = staleness_minutes(legacy)
            extra = (f"\n  查见工作树里那枚 {legacy}（{legacy.stat().st_size}B）"
                     + (f"：比本树最新 .go 旧 **{st[0]:.1f} 分钟**（{st[1].name}）"
                        if st else "（目前不比 .go 旧）")
                     + "——**未采用**。")
        raise EngineBinaryUnpinned(
            "没有钉住 Go 引擎二进制：环境变量 RIOS_SIM_BIN 未设。\n"
            f"  先构建：{build_hint()}\n"
            "  ⚠ 不自动挑工作树里那枚 rios-sim.exe：它是构建产物、会在 Go 改动后悄悄过期，"
            "静默用旧会让读数不可比（2026-09-19 事故：未钉与钉住只差这一项，读数 814.0333s vs 221.6667s）。"
            + extra)
    p = pathlib.Path(raw)
    if not p.exists():
        raise EngineBinaryUnpinned(
            f"RIOS_SIM_BIN 指向的文件不存在：{p}\n  先构建：{build_hint()}")
    return p


def find_binary() -> pathlib.Path:
    """**已改名为 `require_binary()` 的旧入口**，保留只为不改动几十处调用方。

    ⚠ 语义已变：以前"找不到就返回 None（调用方据此跳过）"——**"跳过"是静默的**，
    而静默跳过在读数上长得跟"跑过了、一致"一模一样。现在一律抛 `EngineBinaryUnpinned`。
    """
    return require_binary()


class Simgo:
    """一个 `rios-sim` 进程。用 `with` 保证收尾。"""

    def __init__(self, exe: pathlib.Path | str | None = None,
                 timeout: float = 120.0) -> None:
        self.exe = pathlib.Path(exe) if exe else require_binary()
        self.timeout = timeout
        self._proc = subprocess.Popen(
            [str(self.exe)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            bufsize=1)

    # -------------------------------------------------- 生命周期

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                self._proc.stdin.close()          # type: ignore[union-attr]
                self._proc.wait(timeout=5)
            except Exception:                     # noqa: BLE001
                self._proc.kill()

    def __enter__(self) -> "Simgo":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -------------------------------------------------- 调用

    def _call(self, cmd: str, spec: Any = None, idx: int = 1) -> dict:
        req: dict[str, Any] = {"id": idx, "cmd": cmd}
        if spec is not None:
            req["spec"] = spec
        line = json.dumps(req, ensure_ascii=False, separators=(",", ":"))
        assert self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()
        got = self._proc.stdout.readline()
        if not got:
            err = (self._proc.stderr.read() if self._proc.stderr else "") or ""
            raise RuntimeError(f"rios-sim 没有应答就退出了：{err.strip()[:400]}")
        return json.loads(got)

    def ping(self) -> dict:
        """握手：核对协议版本。版本不一致**当场炸**，不带着疑问往下跑。"""
        resp = self._call("ping")
        if not resp.get("ok"):
            raise RuntimeError(f"ping 失败：{resp.get('error')}")
        pong = resp.get("pong") or {}
        if int(pong.get("version", -1)) != PROTOCOL_VERSION:
            raise RuntimeError(
                f"协议版本不一致：rios-sim 报 {pong.get('version')}，"
                f"调用方认 {PROTOCOL_VERSION}——重新 go build 一次")
        return pong

    def mechanisms(self) -> list[str]:
        """本二进制里编译进来的**关卡特有机制**名（`mech.Available()`）。

        Python 侧据此判断"这一关的机制能不能交给 Go 跑"，不各自维护名单
        （博士 2026-09-18：机制单独成层、每个活动分开、按需取用）。
        """
        return list(self.ping().get("mechanisms") or [])

    def sim(self, spec: dict) -> dict:
        """跑一场。返回判决；不支持时 raise（**绝不返回残缺判决**）。"""
        resp = self._call("sim", spec)
        if not resp.get("ok"):
            raise RuntimeError(str(resp.get("error") or "未知错误"))
        return resp["verdict"]

    def sim_many(self, specs: Iterable[dict]) -> list[dict]:
        """一批同序应答。`id` 递增，落单的应答按 id 归位。"""
        out: list[dict] = []
        for i, spec in enumerate(specs, start=1):
            resp = self._call("sim", spec, idx=i)
            if not resp.get("ok"):
                raise RuntimeError(f"第 {i} 场失败：{resp.get('error')}")
            out.append(resp["verdict"])
        return out


# ------------------------------------------------------------ 对拍

def compare(py_result, go_verdict: dict, *,
            tolerance: float = 1e-6) -> dict[str, Any]:
    """把原版 `BattleResult` 与 Go 判决逐项对拍。

    返回 `{"ok": bool, "diff": {字段: (原版, Go)}, "note": str}`。

    对拍口径：

    * `won` / 计数类字段**逐位相等**（它们都是整数或布尔，没有浮点容忍的余地）；
    * `elapsed` 与 `damage_dealt` 用**相对容忍**——两次浮点累加的最后一位可能不同，
      但"差一个帧"（1/30 秒）必须是错，所以容忍度取到 1e-6 而不是"看着差不多"；
    * `leak_events` 逐笔比（时刻 + 名字 + 扣命）。

    原版没有的字段（`sim_ms` 之类）不参与对拍。
    """
    diff: dict[str, Any] = {}
    for field in _COMPARE_FIELDS:
        want = getattr(py_result, field, None)
        got = go_verdict.get(field)
        if want is None:
            continue
        if bool(want) != bool(got) if isinstance(want, bool) else want != got:
            diff[field] = (want, got)
    if abs(float(getattr(py_result, "elapsed", 0.0))
           - float(go_verdict.get("elapsed", 0.0))) > 1e-6:
        diff["elapsed"] = (round(float(py_result.elapsed), 6),
                           round(float(go_verdict.get("elapsed", 0.0)), 6))
    if abs(float(getattr(py_result, "damage_dealt", 0.0))
           - float(go_verdict.get("damage_dealt", 0.0))) > max(
                tolerance, 1e-6 * max(1.0, float(getattr(py_result, "damage_dealt", 1.0)))):
        diff["damage_dealt"] = (round(float(py_result.damage_dealt), 3),
                                round(float(go_verdict.get("damage_dealt", 0.0)), 3))
    py_leaks = [(round(float(t), 6), str(name), int(cost))
                for t, name, cost in getattr(py_result, "leak_events", [])]
    go_leaks = [(round(float(t), 6), str(name), int(cost))
                for t, name, cost in (go_verdict.get("leak_events") or [])]
    if py_leaks != go_leaks:
        diff["leak_events"] = (py_leaks[:5], go_leaks[:5])
    # 技能开启次数：原版有 `skill_activations` 这个计数器，Go 侧就是时间线上
    # `kind == "skill"` 的笔数。**这是状态机唯一一个直接可比的量**——次数对上
    # 不代表时刻一定对，但对不上就一定有一边的状态机错了（本数是先验判据）。
    want_sk = getattr(py_result, "skill_activations", None)
    if want_sk is not None:
        got_sk = sum(1 for e in (go_verdict.get("events") or [])
                     if e.get("kind") == "skill")
        if int(want_sk) != got_sk:
            diff["skill_activations"] = (int(want_sk), got_sk)
    return {"ok": not diff, "diff": diff,
            "note": "" if not diff else "逐项不一致，见 diff"}


def main(argv: list[str] | None = None) -> int:
    """命令行自检：`python -m ak_tactic.simgo` → ping 一次，报告版本与能力。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        exe = require_binary()
    except EngineBinaryUnpinned as e:
        #: ⚠ 走到 stderr、退出码 2：**没钉住就是没钉住**，不许在这里自己挑一枚。
        print(f"⛔ {e}", file=sys.stderr)
        return 2
    with Simgo(exe) as sim:
        pong = sim.ping()
    print(f"rios-sim：{exe}")
    print(f"  协议版本 {pong.get('version')}　Go {pong.get('go')}　"
          f"{pong.get('os')}/{pong.get('arch')}")
    print(f"  sim 已实现：{pong.get('spec_done')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
