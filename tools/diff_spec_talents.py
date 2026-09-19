# -*- coding: utf-8 -*-
"""`plan-hs06` 的规格为什么变了：把 `spec.py` 里那个 `talent_finders` 换回 `battle.talents`，
两份规格逐项 diff。

## 手法

`spec.py` 里的 `from ..frontend import talent_finders as _talents` 是**函数内**导入，
所以每次调用都走一次 `sys.modules` 查表。把 `sys.modules['ak_tactic.frontend.talent_finders']`
（以及包上的属性）临时换成 `ak_tactic.battle.talents`，同一份代码就会去读**原件**。

⇒ 两台实现在同一条路径上跑同一份计划，产出两份规格，diff 出来就是真差异。
这比"看代码像不像"强得多。

跑法：`python tools\\diff_spec_talents.py [计划名]`（缺省 plan-hs06）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

PLAN = sys.argv[1] if len(sys.argv) > 1 else "plan-hs06"


def _find(name: str) -> Path:
    for cand in (ROOT / "out" / name, ROOT.parent / "ak-tactic-head" / "out" / name):
        if cand.exists():
            return cand
    raise SystemExit("找不到 %s" % name)


class SpecCapture:
    """把 `build_spec` 的产物截下来。"""

    def __init__(self) -> None:
        self.spec: dict | None = None
        self.err: str | None = None


def build(talents_module: ModuleType) -> dict:
    """用指定的 `talents` 实现跑一遍 `build_spec`。"""
    import ak_tactic.frontend as pkg
    from ak_tactic.frontend import talent_finders as newmod
    from ak_tactic.plan import Plan, Roster
    from ak_tactic.verify import Verifier

    from ak_tactic.simgo import spec as spec_mod
    from ak_tactic.simgo import verifier as verifier_mod

    holder = SpecCapture()
    real = spec_mod.build_spec
    #: ⚠ `verifier.py` 写的是 `from .spec import build_spec`，**名字已经绑进它自己的
    #: 命名空间**，改 `spec.build_spec` 对它无效——第一版就是这么"没截到规格"的。
    #: 两个都换。
    real_v = getattr(verifier_mod, "build_spec", None)
    keep_pkg_attr = getattr(pkg, "talent_finders", None)
    keep_sys = sys.modules.get("ak_tactic.frontend.talent_finders")

    def spy(*a, **kw):
        try:
            holder.spec = real(*a, **kw)
        except Exception as exc:                                  # noqa: BLE001
            holder.err = "%s: %s" % (type(exc).__name__, exc)
            raise
        return holder.spec

    spec_mod.build_spec = spy
    if real_v is not None:
        verifier_mod.build_spec = spy
    pkg.talent_finders = talents_module
    sys.modules["ak_tactic.frontend.talent_finders"] = talents_module
    try:
        raw = json.loads(_find(PLAN + ".json").read_text(encoding="utf-8-sig"))
        v = Verifier()
        v.run(Plan.from_dict(raw),
              roster=Roster.from_json(_find("roster_max_modelled.json")))
    finally:
        spec_mod.build_spec = real
        if real_v is not None:
            verifier_mod.build_spec = real_v
        if keep_pkg_attr is not None:
            pkg.talent_finders = keep_pkg_attr
        if keep_sys is not None:
            sys.modules["ak_tactic.frontend.talent_finders"] = keep_sys
    if holder.spec is None:
        raise SystemExit("没截到规格：%s" % holder.err)
    return holder.spec


def walk(a, b, path=""):
    """逐项 diff，返回差异清单。"""
    out = []
    if type(a) is not type(b) and not (isinstance(a, (int, float))
                                      and isinstance(b, (int, float))):
        return [("%s 类型 %s → %s" % (path, type(a).__name__, type(b).__name__))]
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append("%s.%s 只在**新**里" % (path, k))
            elif k not in b:
                out.append("%s.%s 只在**旧**里" % (path, k))
            else:
                out += walk(a[k], b[k], "%s.%s" % (path, k))
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append("%s 长度 %d → %d" % (path, len(a), len(b)))
        for i in range(min(len(a), len(b))):
            out += walk(a[i], b[i], "%s[%d]" % (path, i))
    elif a != b:
        out.append("%s: %r → %r" % (path, a, b))
    return out


def main() -> int:
    from ak_tactic.battle import talents as old
    from ak_tactic.frontend import talent_finders as new

    print("跑两遍 %s ……" % PLAN)
    spec_new = build(new)
    spec_old = build(old)
    diffs = walk(spec_old, spec_new, "spec")
    if not diffs:
        print("✅ 两份规格逐项一致（那 spec_sha 的差别来自别处）")
        return 0
    print("❌ %d 处不同：" % len(diffs))
    for d in diffs[:40]:
        print("   " + d)
    if len(diffs) > 40:
        print("   …… 还有 %d 处" % (len(diffs) - 40))
    return 1


if __name__ == "__main__":
    sys.exit(main())
