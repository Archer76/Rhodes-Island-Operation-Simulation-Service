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


def find_binary() -> pathlib.Path | None:
    """找 `rios-sim` 的二进制。找不到就返回 None（调用方据此**跳过**，不是失败）。"""
    env = os.environ.get("RIOS_SIM_BIN")
    if env and pathlib.Path(env).exists():
        return pathlib.Path(env)
    root = repo_root() / "rios-sim"
    for name in ("rios-sim.exe", "rios-sim"):
        cand = root / name
        if cand.exists():
            return cand
    return None


class Simgo:
    """一个 `rios-sim` 进程。用 `with` 保证收尾。"""

    def __init__(self, exe: pathlib.Path | str | None = None,
                 timeout: float = 120.0) -> None:
        self.exe = pathlib.Path(exe) if exe else find_binary()
        if self.exe is None:
            raise FileNotFoundError(
                "没找到 rios-sim 的可执行文件：先 cd rios-sim && go build")
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
    return {"ok": not diff, "diff": diff,
            "note": "" if not diff else "逐项不一致，见 diff"}


def main(argv: list[str] | None = None) -> int:
    """命令行自检：`python -m ak_tactic.simgo` → ping 一次，报告版本与能力。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    exe = find_binary()
    if exe is None:
        print("没找到 rios-sim 的可执行文件（先 cd rios-sim && go build）")
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
