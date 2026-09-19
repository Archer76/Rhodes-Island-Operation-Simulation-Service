"""`golden_go.py` 参数缺陷的**反向守卫**（判据＝基线文件逐字节不变）。

为什么单独写一条判据：这次缺陷的要害不是"rc 不对"，而是**破坏性默认值**——
`--help` 与拼错的开关都曾让 `fixtures/golden_go.json` 被静默重写。
所以真正的断言只有一条：**跑完这些调用之后，基线的 `git hash-object` 与跑之前相同**；
rc≠0 只是副证。

判据（先写死）：
  ① 不给动作 ⇒ **不写基线**（rc 任意，但哈希不变、且**不再**走重写分支）；
  ② `--help` ⇒ rc=0 且**哈希不变**、输出里含全部可用开关；
  ③ 拼错的开关（`--chekc`）⇒ **rc≠0**、输出列出可用开关、**哈希不变**；
  ④ `--rebless` 不带 `--why` ⇒ **rc≠0** 且**哈希不变**；
  ⑤ 未知位置参数（`foo.json`）⇒ **rc≠0** 且**哈希不变**；
  ⑥ 控制组：`--check` 在同一套夹具上必须**能**返回 0（证明上面不是"什么都跑不动"）。
反向守卫：把基线文件**故意改一个数** ⇒ `--check` 必须 rc=1（判据红得起来）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
PY = sys.executable
GOLDEN = ROOT / "fixtures" / "golden_go.json"


def blob_hash(p: Path) -> str:
    """用 git 自己的哈希算——与"这次提交里它是什么"同一把尺子。"""
    r = subprocess.run(["git", "hash-object", str(p)], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() or f"NOGIT(rc={r.returncode})"


def run(args: list[str]) -> tuple[int, str]:
    r = subprocess.run([PY, str(ROOT / "tools" / "golden_go.py"), *args],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=5400)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    if not GOLDEN.exists():
        print(f"⛔ 基线不在 {GOLDEN}，这条守卫无从谈起")
        return 1
    h0 = blob_hash(GOLDEN)
    print(f"基线 {GOLDEN.relative_to(ROOT)}　起始哈希 {h0[:16]}")
    print("=" * 88)

    cases = [
        ("no-action", [], "哈希不变（不许重写）", None, False),
        ("help", ["--help"], "rc=0、哈希不变、列出开关", 0, True),
        ("typo-switch", ["--chekc"], "rc≠0、列出开关、哈希不变", "nonzero", True),
        ("typo-switch2", ["--reblesss", "--why", "x"], "rc≠0、列出开关、哈希不变", "nonzero", True),
        #: ⚠ `--rebless` 不带 `--why` 是**跑完 19 份之后**才拒绝的 ⇒ 它**不该**出现在
        #: 「列出可用开关」那一类里（第一版把它也要求了列出开关，于是判据自己红）。
        ("rebless-no-why", ["--rebless"], "rc≠0、哈希不变", "nonzero", False),
        ("stray-positional", ["foo.json"], "rc≠0、列出开关、哈希不变", "nonzero", True),
    ]
    bad = 0
    for name, args, want, rc_want, need_list in cases:
        rc, out = run(args)
        h1 = blob_hash(GOLDEN)
        hash_ok = h1 == h0
        rc_ok = (rc_want is None) or (rc == rc_want if isinstance(rc_want, int)
                                      else rc != 0)
        listed = ("--rebless" in out and "--extend" in out and "--check" in out)
        ok = hash_ok and rc_ok and (listed or not need_list)
        bad += 0 if ok else 1
        print(f"[{name:<16}] rc={rc:<3} 哈希不变={'✅' if hash_ok else '❌ ' + h1[:16]} "
              f"rc符合={'✅' if rc_ok else '❌'} 列出开关={'✅' if listed else '—'} "
              f"⇒ {'✅' if ok else '❌'}")
        if not hash_ok:
            print(f"     ⛔ **基线被改写了**——这条缺陷的要害就在这里")
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-3:]
        for ln in tail:
            print(f"     | {ln[:110]}")

    #: 控制组：`--check` 必须给出**比对结论**（一致 / 有 k 份不一致）——**不是"必须绿"**。
    #: ⚠ 第一版把控制组写成"必须 rc=0"，于是它用**默认（共享）exe** 时自己红了，而我差点
    #: 把这份红读成"工具坏了"。真相是：**同一份词表换一枚二进制就会翻**（未钉仪器时，
    #: `hsex8_max` 用共享 exe 报 814.0333s、用私有构建报 221.6667s）。控制组要证明的是
    #: **"它真的比了"**，不是"它说绿了"。
    rc, out = run(["--check"])
    verdict = ("份与基线逐项一致" in out) or ("份不一致" in out)
    ctrl_ok = rc in (0, 1) and verdict
    print(f"[控制组 --check   ] rc={rc}　给出比对结论={'✅' if verdict else '❌'}"
          f"　⇒ {'✅ 判据活着' if ctrl_ok else '❌ 它没比'}")
    if not verdict:
        print(f"     ⛔ 没有比对结论 ⇒ 工具没跑到位，上面的 rc 都不算数")
    bad += 0 if ctrl_ok else 1

    #: 反向守卫：把基线故意改一个数 ⇒ `--check` 必须红（证明它真的在比）
    backup = GOLDEN.read_text(encoding="utf-8")
    try:
        doc = json.loads(backup)
        k = sorted(doc)[0]
        doc[k]["kills"] = int(doc[k].get("kills") or 0) + 1
        GOLDEN.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True),
                          encoding="utf-8")
        rc, out = run(["--check"])
        guard_ok = rc != 0 and "不一致" in out
        print(f"[反向守卫 改基线] rc={rc}　⇒ {'✅ 红得起来' if guard_ok else '❌ 没红'}"
              f"（改了 `{k}` 的 kills）")
        bad += 0 if guard_ok else 1
    finally:
        GOLDEN.write_text(backup, encoding="utf-8")
        print(f"[还原] 哈希 {'✅ 与起始一致' if blob_hash(GOLDEN) == h0 else '❌ 不一致'}")

    print("=" * 88)
    print(f"{'✅ 全部守卫成立' if bad == 0 else f'❌ {bad} 项不成立'}"
          f"（判据：跑完后基线哈希与起始逐字节相同 + rc 符合 + 列出开关）")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
