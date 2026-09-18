"""规格键守卫：**Python 送出去的每一个键，Go 那边都得有人接**。

## 为什么需要它

`ak_tactic/simgo/spec.py` 送出去的是一份 JSON，`rios-sim/wire.go` 与
`rios-sim/mech/*.go` 用结构体标签接。两边是**手写对齐**的，而手写对齐的失败方式
特别安静：JSON 里多一个键，Go 的 `encoding/json` **不报错、不提示**，直接丢掉——
于是机制少一个参数、判决仍然「跑完了」，对拍只在恰好受影响的那一关才炸（或者
根本不炸，如果那一关正好不是这条参数说话）。

这个坑在本仓库已经吃过一次：`move_speed` 曾经在映射表里有键、而目标类没有同名字段，
解析结果被**静默丢弃**。

所以这条守卫问的是两个**差集**：

1. **规格里有、Go 没声明** —— 这是硬缺口，必须为零（除非登记在 `ALLOWED` 里，
   例如 `huai_shu_li.farmland`：它是**机制名**，Go 按名字查表取规格，不是结构体字段）。
2. **Go 声明了、样本里没出现过** —— 未必是错（可能只是这几关没这种敌人/装置），
   但值得看一眼：它常常正是"写好了却从没被任何一关走到"的字段。
   ⚠ 这一列里混着**回执侧**的键（`elapsed`／`events`／`cmd`／`go` 这些是我们读回来的
   判决字段，不是送出去的规格），扫标签分不出方向——看的时候按名字分辨即可。

⚠ 这道守卫**不替代对拍**：它只证明"键有人接"，不证明"接的人用得对"。对拍那三道
判据（一致 / 反证 / 落位要咬到）另在 `tools/check_mech_parity.py`。

跑法（工作目录 = 仓库根）：

    python tools/check_spec_keys.py
    python tools/check_spec_keys.py --go-dir D:\\home\\DSH\\ak-tactic\\rios-sim
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ak_tactic.gamedata import EnemyLibrary, GameDataSource, load_stage   # noqa: E402
from ak_tactic.battle.sim import BattleSimulator                          # noqa: E402
from ak_tactic.simgo import build_spec                                    # noqa: E402

#: 规格里会出现、但**不是**结构体字段的键：机制名（`mech.Load` 按名字取规格）。
ALLOWED = {"huai_shu_li.farmland"}

#: 取样关卡。取样的目标是**键的覆盖**，不是判决——所以挑装置/召唤/技能出手都有的关，
#: 加上几关只有普通敌人的，两边都要有。
SAMPLES: list[tuple[str, list[str]]] = [
    ("HS-1", ["char_002_amiya", "char_123_fang"]),
    ("HS-4", ["char_002_amiya", "char_123_fang"]),
    ("HS-8", ["char_002_amiya", "char_123_fang"]),
    ("HS-9", ["char_002_amiya", "char_123_fang"]),
    ("HS-EX-3", ["char_002_amiya", "char_123_fang"]),
    ("HS-EX-4", ["char_002_amiya", "char_124_kroos"]),
    ("HS-S-1", ["char_002_amiya", "char_123_fang"]),
    ("HS-EX-7", ["char_002_amiya", "char_123_fang"]),
]
STATS_KW = dict(elite=2, level=80, trust=100, potential=6)


def go_fields(go_dir: Path) -> dict[str, list[str]]:
    """Go 声明过的 JSON 键 → 出现在哪些文件里。

    扫的是**反引号标签里的 json:"键"**，只认小写字母数字下划线与点（机制名的形状）。
    """
    out: dict[str, list[str]] = {}
    for path in sorted(go_dir.rglob("*.go")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'`json:"([A-Za-z0-9_.]+)', text):
            out.setdefault(m.group(1), []).append(str(path.relative_to(go_dir)))
    return out


def spec_keys(node, path: str = "", out: dict[str, set[str]] | None = None):
    """规格里出现过的**字段名** → 它出现在哪些路径（路径只留最后一两段，便于报错）。

    ⚠ 只收"能当字段名"的键（标识符形状）。规格里有一批**映射形式的字典**：
    `spawns[].reborn_summons[].paths` 是 `{"10,4": [...], ...}`，键是坐标串。
    把这些键也当字段名收进来，会得到 43 条"Go 没声明"的**假账**——本工具因此
    长期退出码 1，真账混在假账里看不出来。这正是仓库明令禁止的一类事：宁可
    报得少，也不能拿假账充数，更不能因此把守卫放宽。

    非标识符键的**值**照样往下走（`path + "{}"`）：映射里的元素形状还是要查，
    否则真字段会跟着一起漏掉。
    """
    if out is None:
        out = {}
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k.isidentifier():
                out.setdefault(k, set()).add(path or "<根>")
                spec_keys(v, f"{path}.{k}", out)
            else:
                spec_keys(v, path + "{}", out)
    elif isinstance(node, list):
        for item in node[:1]:                      # 同一列表里的元素形状相同，取第一个
            spec_keys(item, path + "[]", out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go-dir", default=str(ROOT / "rios-sim"),
                    help="Go 源码目录（默认仓库里的 rios-sim/）")
    args = ap.parse_args()

    go_dir = Path(args.go_dir)
    if not go_dir.is_dir():
        print(f"❌ 找不到 Go 源码目录：{go_dir}")
        return 2
    fields = go_fields(go_dir)
    print(f"Go 声明过的 JSON 键：{len(fields)} 个（来自 {go_dir}）")

    src = GameDataSource()
    lib = EnemyLibrary(source=src)
    seen: dict[str, set[str]] = {}
    used_stages = 0
    for code, squad in SAMPLES:
        try:
            stage = load_stage(code, source=src)
        except Exception as exc:                                  # noqa: BLE001
            print(f"⊘ {code}：读不到关卡（{exc}）——跳过")
            continue
        try:
            # 复用对拍台那套计划与取敌人库的方式（`lib_get` 对 `Stage` 做了包装，
            # 直接拿 `lib.get(stage)` 会撞 "unhashable type: Stage"）。
            sys.path.insert(0, str(ROOT / "tools"))
            import check_mech_parity as C                         # noqa: PLC0415
            C.SRC, C.LIB = src, lib
            sim = C.BattleSimulator(stage, enemy_at=C.lib_get(stage))
            for d in C.plan_for(sim, stage, squad, C.CALC):
                sim.plan(d)
            spec = build_spec(sim, allow_devices=True)
        except Exception as exc:                                  # noqa: BLE001
            print(f"⊘ {code}：建规格失败（{type(exc).__name__}: {exc}）——跳过")
            continue
        used_stages += 1
        for k, paths in spec_keys(spec).items():
            seen.setdefault(k, set()).update(paths)

    missing = {k: v for k, v in seen.items()
               if k not in fields and k not in ALLOWED}
    unused = {k: v for k, v in fields.items() if k not in seen}

    print(f"取样 {used_stages} 关，规格里出现过 {len(seen)} 个键")
    if used_stages == 0:
        # ⚠ 空转绿灯：一关都没建成规格时，"没发现缺口"是**没有内容**的结论。
        # 这种绿灯比红灯更坏——它会让人以为这一层查过了。
        print("\n❌ 一关都没能建成规格：这条守卫什么也没证明（不是通过）")
        return 2
    if missing:
        print(f"\n❌ 规格里有、Go 没声明：{len(missing)} 个（会被静默丢掉）")
        for k in sorted(missing):
            print(f"   {k:32s} 出现在 {sorted(seen[k])[:3]}")
    else:
        print("\n✅ 规格里的每个键 Go 都声明了（`encoding/json` 不会静默丢东西）")

    if unused:
        print(f"\n· Go 声明了、这次取样没出现：{len(unused)} 个（未必是错，看一眼）")
        print("   " + "、".join(sorted(unused)[:24])
              + ("…" if len(unused) > 24 else ""))

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
