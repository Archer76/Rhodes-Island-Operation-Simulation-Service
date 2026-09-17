# -*- coding: utf-8 -*-
"""关卡环境机制自检（怀黍离 田地 / 病害值）。

分六节：**黑板**（runes 取值与难度消歧）、**坐标**（init_pollut 的翻转）、
**田地几何**（判据与连通域）、**参数**（逐关与关卡页对照）、
**演化**（缓存释放与靠拢）、**结算与阻流阀**。

跑法：`python tools/check_environment.py`

需要 `data/gamedata/` 下的怀黍离关卡缓存。缺缓存时相关节**跳过并说明**，
不算失败——本文件不联网。
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ak_tactic.battle import environment as E                          # noqa: E402
from ak_tactic.gamedata.stage import load_stage                        # noqa: E402

_PASSED = 0
_FAILED: list[str] = []
_SKIPPED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(label)
        print(f"  [FAIL] {label}" + (f"   {detail}" if detail else ""))


def skip(label: str, why: str) -> None:
    _SKIPPED.append(label)
    print(f"  [skip] {label}   {why}")


def stage(level_id: str):
    try:
        return load_stage(level_id)
    except Exception as exc:                                   # noqa: BLE001
        skip(level_id, f"{type(exc).__name__}: {exc}")
        return None


# ---------------------------------------------------------------- 1 黑板

def check_blackboard() -> None:
    print("\n[1] 黑板：runes 取值与难度消歧")

    # 形状取自真实的 act31side_ex08：两条同名 rune，只差 difficultyMask。
    bb = [
        {"key": "init_pollut_value", "value": 0, "valueStr": "1,1:0"},
        {"key": "hp_recovery_per_sec", "value": 50, "valueStr": None},
        {"key": "damage_ratio", "value": 4, "valueStr": None},
    ]
    runes = [
        {"key": "env_system_new", "difficultyMask": "NORMAL", "blackboard": bb},
        {"key": "env_system_new", "difficultyMask": "FOUR_STAR", "blackboard": []},
        {"key": "global_lifepoint", "difficultyMask": "FOUR_STAR",
         "blackboard": [{"key": "value", "value": 1, "valueStr": None}]},
    ]

    # 数值住 value，字符串住 valueStr —— 读错列会得到「参数全是 None」。
    check("数值键读 value", E.bb_number(bb, "damage_ratio") == 4.0,
          str(E.bb_number(bb, "damage_ratio")))
    check("字符串键读 valueStr", E.bb_text(bb, "init_pollut_value") == "1,1:0",
          str(E.bb_text(bb, "init_pollut_value")))
    check("★ 数值键的 valueStr 是 null，误读 valueStr 会得 None",
          E.bb_text(bb, "damage_ratio") is None,
          "这条就是「五个参数全是 None」那个假结论的来源")
    check("不存在的键返回 None", E.bb_number(bb, "nope") is None)

    # 难度消歧
    check("NORMAL 取到 NORMAL 那条",
          E.find_rune(runes, "env_system_new", "NORMAL")["blackboard"] == bb)
    check("FOUR_STAR 取到 FOUR_STAR 那条（不是第一条）",
          E.find_rune(runes, "env_system_new", "FOUR_STAR")["blackboard"] == [],
          "取第一条会拿到 NORMAL 的黑板")
    check("键不存在返回 None", E.find_rune(runes, "nothing", "NORMAL") is None)

    # ⚠ ALL 必须认：act31side_08 用的就是 ALL，不认则环境系统整条静默消失。
    allr = [{"key": "env_system_new", "difficultyMask": "ALL", "blackboard": bb}]
    check("★ difficultyMask=ALL 在两种难度下都生效（act31side_08 就是 ALL）",
          E.find_rune(allr, "env_system_new", "NORMAL") is not None
          and E.find_rune(allr, "env_system_new", "FOUR_STAR") is not None,
          "只认 NORMAL 会把整条环境系统漏掉，且不报错")


# ---------------------------------------------------------------- 2 坐标

def check_coords() -> None:
    print("\n[2] 坐标：init_pollut 的 row 翻转")

    # act31side_08 写 7,1:100，高 9 → y = 9-1-7 = 1。
    check("单点：7,1 在高 9 的图上翻成 y=1",
          E.parse_init_pollut("7,1:100", 9) == {(1, 1): 100.0},
          str(E.parse_init_pollut("7,1:100", 9)))
    check("多点：| 分隔",
          E.parse_init_pollut("5,5:90|5,3:90", 8) == {(5, 2): 90.0, (3, 2): 90.0},
          str(E.parse_init_pollut("5,5:90|5,3:90", 8)))
    check("空串/None 得到空表，不抛异常",
          E.parse_init_pollut(None, 8) == {} and E.parse_init_pollut("", 8) == {})
    check("坏条目跳过而不是整条炸掉",
          E.parse_init_pollut("坏,条目|1,2:30|,,:", 8) == {(2, 6): 30.0},
          str(E.parse_init_pollut("坏,条目|1,2:30|,,:", 8)))

    # 翻不翻得对，靠关卡情报反证：act31side_08 的情报写「场地**左上角**田地区域
    # 的初始病害值+100」，而未翻转时该点落在最下面一行。
    st = stage("act31side_08")
    if st is None:
        return
    p = E.PolluteParams.from_stage(st, "NORMAL")
    (pt,) = p.init_pollut
    x, y = pt
    check("★ 实关反证：污染点落在图上靠近顶部（情报说「左上角」）",
          y <= 1, f"落在 ({x},{y})，图高 {st.map.height}")
    # 判据是「原始 row 与翻出来的 y 不同」——写成 `height-1-7 != y` 是把翻转又算了
    # 一遍再和 y 比，恒假（本轮真这么错过一次，跑出唯一一项红）。
    check("翻转确实改变了位置：原始 row=7 与翻出的 y 不同",
          y != 7, f"原始 row 7 → y={y}，图高 {st.map.height}；"
                  f"不翻会落在下半部分")


# ---------------------------------------------------------------- 3 田地几何

def check_farmland() -> None:
    print("\n[3] 田地几何：判据与连通域")

    class T:
        def __init__(self, key, height):
            self.key, self.height = key, height
        @property
        def is_lowland(self):
            return self.height == "LOWLAND"
        @property
        def is_highland(self):
            return self.height == "HIGHLAND"

    check("普通低地是田地", E.is_farmland(T("tile_road", "LOWLAND")))
    check("高台不是田地", not E.is_farmland(T("tile_wall", "HIGHLAND")))
    for k in ("tile_telin", "tile_telout", "tile_hole"):
        check(f"{k} 不是田地（原文：传送门出入口/地穴除外）",
              not E.is_farmland(T(k, "LOWLAND")))
    # ⚠ 这几个**不能**排除：第一版自造的排除集把它们排掉了，被博士的图证伪。
    for k in ("tile_start", "tile_end", "tile_fence_bound", "tile_flystart"):
        check(f"{k} **仍然是**田地（第一版误排除，已由地图预览证伪）",
              E.is_farmland(T(k, "LOWLAND")))

    st = stage("act31side_08")
    if st is None:
        return
    cells = E.farmland_cells(st.map)
    groups = E.farmland_groups(st.map)
    holes = {t.key for row in st.map.tiles for t in row
             if t.key in ("tile_hole", "tile_telin", "tile_telout")}
    check("这一关确有特殊地形（否则下面的连通域断言没有说服力）",
          bool(holes), "、".join(sorted(holes)))
    check("田地不含任何特殊地形格",
          not any(st.map.tile(x, y).key in E.FARMLAND_EXCLUDED_KEYS
                  for x, y in cells))
    check("田地全是低地",
          all(st.map.tile(x, y).is_lowland for x, y in cells))
    check("田地少于全部低地（说明排除真的生效了）",
          len(cells) < sum(1 for row in st.map.tiles for t in row if t.is_lowland),
          f"田地 {len(cells)} < 低地 "
          f"{sum(1 for row in st.map.tiles for t in row if t.is_lowland)}")

    # ★ 这一关有一条 5 格长的地穴竖墙，它必须把田地切成两片——
    #   这正是「必须按 tileKey 判、不能只看 (height,buildable,passable)」的理由：
    #   穴的三个字段与普通低地完全一致，只看字段会把墙当成可通的田地。
    check("★ 地穴墙把田地切成 2 片（只看字段会把它当普通地面而连成一片）",
          len(groups) == 2, f"实得 {len(groups)} 片")
    check("分组是划分：不重不漏",
          sorted(c for g in groups for c in g) == sorted(cells))

    # 四邻而非八邻：斜接的一对角不算同一片。
    class M:
        width = height = 2
        tiles = [[T("tile_road", "LOWLAND"), T("tile_wall", "HIGHLAND")],
                 [T("tile_wall", "HIGHLAND"), T("tile_road", "LOWLAND")]]
    check("斜向相接的两格**不算**同一片（四邻连通）",
          len(E.farmland_groups(M())) == 2)


# ---------------------------------------------------------------- 4 参数

def check_params() -> None:
    print("\n[4] 参数：逐关与关卡页对照")

    # ⚠ 这张表是**判据**，不是水位：数值来自关卡 JSON 的 runes 黑板，
    #   并与 prts.wiki 关卡页的「特殊地形效果」逐项对照过（两条来源互为校验）。
    want = {
        ("act31side_08", "NORMAL"):   (20, 3, 100, 9),
        ("act31side_ex08", "NORMAL"): (30, 4, 200, 14),
        ("act31side_ex08", "FOUR_STAR"): (30, 4, 200, 14),
        ("act31side_ex03", "NORMAL"): (30, 4, 200, 14),
    }
    seen = {}
    for (lid, diff), exp in want.items():
        st = stage(lid)
        if st is None:
            continue
        p = E.PolluteParams.from_stage(st, diff)
        got = (p.basic_damage, p.damage_ratio,
               p.first_basic_damage, p.first_damage_ratio)
        seen[(lid, diff)] = p
        check(f"{lid}/{diff}：{exp[0]}/{exp[1]} + {exp[2]}/{exp[3]}",
              got == exp, f"实得 {got}")
        check(f"{lid}/{diff}：五个参数齐备（valid）", p.valid)
        check(f"{lid}/{diff}：hp_recovery_per_sec=50", p.hp_recovery_per_sec == 50.0)

    # 与关卡页文字对照：HS-8 页写「20+病害值×3」与「100+病害值×9」。
    p = seen.get(("act31side_08", "NORMAL"))
    if p is not None:
        check("★ 与关卡页文字逐项吻合（HS-8：20+病害值×3 / 100+病害值×9）",
              (p.basic_damage, p.damage_ratio, p.first_basic_damage,
               p.first_damage_ratio) == (20, 3, 100, 9))

    # 难度不同则 init 不同——这是「禁止取第一条」的存在理由。
    a, b = seen.get(("act31side_ex08", "NORMAL")), seen.get(("act31side_ex08", "FOUR_STAR"))
    if a and b:
        check("★ 同关两种难度的 init_pollut 不同（这就是禁止取第一条的理由）",
              a.init_pollut != b.init_pollut,
              f"NORMAL={a.init_pollut} FOUR_STAR={b.init_pollut}")
        check("但五个数值参数相同（只有初始污染点不同）",
              (a.basic_damage, a.damage_ratio) == (b.basic_damage, b.damage_ratio))

    st = stage("act31side_08")
    if st is not None:
        check("没有环境系统的关卡返回 None",
              E.PolluteParams.from_stage(st, "NORMAL", runes=[]) is None)


# ---------------------------------------------------------------- 5 演化

def check_evolution() -> None:
    print("\n[5] 演化：缓存释放与靠拢")

    for d, jia, yi in ((1, 2, 1), (24, 2, 1), (25, 2, 1), (26, 3, 2),
                       (50, 3, 2), (100, 5, 4)):
        check(f"步长：差值 {d} → 甲 {jia} / 乙 {yi}（原文有两种读法）",
              E.actual_step(d) == jia and E.actual_step(d, base=0) == yi,
              f"甲={E.actual_step(d)} 乙={E.actual_step(d, base=0)}")
    check("差值为 0 或负时步长为 0（不会反向抖）",
          E.actual_step(0) == 0 and E.actual_step(-5) == 0)
    check("甲比乙恰好大 1 点/秒——这是那句话两种读法的全部差别",
          all(E.actual_step(d) - E.actual_step(d, base=0) == 1 for d in (1, 26, 100)))

    st = stage("act31side_ex08")
    if st is None:
        return
    # 用 NORMAL（初始污染点 1,1:0）起一片干净的场地，手动加缓存。
    p = E.PolluteParams.from_stage(st, "NORMAL")
    fs = E.FarmlandSystem(st, p)
    check("NORMAL 开场无污染", all(v == 0 for v in fs.actual.values()))

    ys = sorted({y for _x, y in fs._index})
    probe = next(c for c in sorted(fs._index) if c[0] > 0)
    fs.add_cache(*probe, 10.0)
    f = fs.field_at(*probe)
    check("缓存加的是【最大】不是【实际】",
          f.cache == 10.0 and fs.actual_at(*probe) == 0.0,
          f"cache={f.cache} actual={fs.actual_at(*probe)}")

    # 0.2s 释放 1 点：推 1 秒应当恰好放出 5 点。
    fs.tick(1.0)
    check("★ 缓存每 0.2s 释放 1 点：1 秒放 5 点",
          f.cache == 5.0, f"cache={f.cache}")
    check("【最大】被抬到 5", f.maximum == 5.0, f"max={f.maximum}")

    fs.tick(0.6)                     # 再放 3 点
    check("0.6s 再放 3 点", f.cache == 2.0, f"cache={f.cache}")
    check("【最大】=8", f.maximum == 8.0, f"max={f.maximum}")

    fs.tick(2.0)
    check("缓存放完之后为 0", f.cache == 0.0, f"cache={f.cache}")

    # 【实际】1 秒靠拢一次：max=10 时差值 10 → 甲给 ceil(10/25+1)=2
    fs2 = E.FarmlandSystem(st, p)
    fs2.add_cache(*probe, 10.0)
    fs2.tick(0.2 * 5)                # 先让 10 点全进 max
    f2 = fs2.field_at(*probe)
    base = fs2.actual_at(*probe)
    fs2.tick(1.0)
    step = fs2.actual_at(*probe) - base
    check("★ 【实际】每秒向【最大】靠拢一次，步长与公式一致",
          step == E.actual_step(f2.maximum - base),
          f"max={f2.maximum} 起点={base} 步长={step}")
    check("靠拢不会越过【最大】", fs2.actual_at(*probe) <= f2.maximum)

    check("病害值被夹在 0–100",
          all(0.0 <= v <= 100.0 for v in fs2.actual.values()))


# ---------------------------------------------------------------- 6 结算与阻流阀

def check_settlement() -> None:
    print("\n[6] 结算与阻流阀")

    st = stage("act31side_08")
    if st is None:
        return
    p = E.PolluteParams.from_stage(st, "NORMAL")
    fs = E.FarmlandSystem(st, p)
    polluted = next(iter(p.init_pollut))

    # HS-8：病害值 100 时，每秒 20+100×3 = 320；部署瞬间 100+100×9 = 1000。
    check("★ 每秒结算 = basic_damage + 实际 × damage_ratio",
          fs.damage_per_second(*polluted) == 320.0,
          f"{fs.damage_per_second(*polluted)}")
    check("★ 部署瞬间 = first_basic_damage + 实际 × first_damage_ratio",
          fs.deploy_damage(*polluted) == 1000.0,
          f"{fs.deploy_damage(*polluted)}")

    clean = next(c for c in sorted(fs._index) if fs.actual_at(*c) == 0)
    check("病害值 0 的田地不结算伤害",
          fs.damage_per_second(*clean) == 0.0 and fs.deploy_damage(*clean) == 0.0)
    check("★ 病害值 0 时改为每秒回复 hp_recovery_per_sec（=50）",
          fs.regen_per_second(*clean) == 50.0,
          f"{fs.regen_per_second(*clean)}")
    check("病害值 >0 时不回复",
          fs.regen_per_second(*polluted) == 0.0)

    # 非田地一律不结算（高台不受此机制影响）。
    high = next((x, y) for y in range(st.map.height) for x in range(st.map.width)
                if st.map.tile(x, y).is_highland)
    check("★ 高台不受此机制影响（不结算也不回复）",
          fs.damage_per_second(*high) == 0.0
          and fs.regen_per_second(*high) == 0.0
          and fs.deploy_damage(*high) == 0.0)

    # 阻流阀
    before = len(fs.field_at(*polluted).cells)
    fs.sever(*polluted)
    check("阻流阀之后该格不再是田地", not fs.is_farmland(*polluted))
    check("该格的【实际】被清零", fs.actual_at(*polluted) == 0.0)
    check("田地被断开（总格数少了 1）",
          len(fs._index) ==
          len({c for f in fs.fields for c in f.cells}) and
          len(fs._index) < len(E.farmland_cells(st.map)),
          f"重新分组后在册 {len(fs._index)} 格")
    check("原组变大还是分裂，取决于这一格是不是割点",
          all(f.cells for f in fs.fields), f"{len(fs.fields)} 组")


def check_sim_wiring() -> None:
    """接进战斗模拟的那条链路。"""
    print("\n[7] 接进模拟器")

    from ak_tactic.battle.sim import BattleSimulator                      # noqa: PLC0415
    from ak_tactic.gamedata.enemy import EnemyLibrary                     # noqa: PLC0415

    try:
        lib = EnemyLibrary()
    except Exception as exc:                                              # noqa: BLE001
        skip("模拟器接线", f"敌人库不可用：{type(exc).__name__}: {exc}")
        return

    def sim(level_id, **kw):
        st = load_stage(level_id)
        return BattleSimulator(st, enemy_at=lib.get, **kw), st

    # ★ 没有环境系统的关卡必须**一个对象都不建**——绝大多数关卡走这条，
    #   建了对象就是白白每帧多跑一次 tick。
    st17 = stage("1-7")
    if st17 is not None:
        s, _ = sim("1-7")
        check("★ 没有环境系统的关卡不建对象（1-7 上零开销）",
              s.farmland is None, f"farmland={s.farmland!r}")
        check("`environment='off'` 显式关闭时也不建",
              sim("act31side_08", environment="off")[0].farmland is None)

    st = stage("act31side_08")
    if st is None:
        return
    s, _ = sim("act31side_08")
    check("★ 有环境系统的关卡自动建好（默认 auto）", s.farmland is not None)
    if s.farmland is None:
        return
    check("模拟器里的田地格数与单独构造一致",
          len(s.farmland._index) == len(E.farmland_cells(st.map)),
          f"{len(s.farmland._index)}")

    # ⚠ 这一关**有病害的那片田地里确实有 10 个可部署格**，所以接线是有效的、
    #   不是"建了对象但永远打不到人"。这是接线有没有意义的关键判据。
    polluted = [f for f in s.farmland.fields if f.maximum > 0]
    dep_in = [c for f in polluted for c in f.cells if st.map.tile(*c).deployable]
    check("★ 有病害的田地里存在可部署格（否则接线毫无意义）",
          len(dep_in) >= 1, f"{len(dep_in)} 格，如 {sorted(dep_in)[:4]}")

    # 逐格播种：开场只有污染点那一格有【实际】，同组其余格子从 0 爬升。
    # 这条**钉住一个待裁定项**（另见 FarmlandSystem._seed 的文档）：
    # 若改成整片播种，这里会红，提醒改的人去核对那处歧义。
    hot = sorted(dep_in, key=lambda c: -s.farmland.actual_at(*c))
    check("⚠ 逐格播种：开场时同组的可部署格【实际】为 0（待实机校正）",
          all(s.farmland.actual_at(*c) == 0 for c in dep_in),
          f"最高 {s.farmland.actual_at(*hot[0]):g}")
    check("但所属田地的【最大】已经是 100",
          all(s.farmland.maximum_at(*c) == 100 for c in dep_in))

    # ⚠ 爬升是**渐近**的，不是恒速：步长 = ceil(差值/25 + 1) 随差值缩小而变小。
    # 我第一版写的是「20 秒后到 100」，那是假设了恒速 5/秒——跑出 77 才暴露。
    # 正确的判据是逐秒对拍那条**规律**，而不是某个秒数上的某个数。
    fs = s.farmland
    cell = dep_in[0]
    mism: list[str] = []
    trace: list[float] = []
    for _ in range(30):
        before = fs.actual_at(*cell)
        mx = fs.maximum_at(*cell)
        fs.tick(1.0)
        after = fs.actual_at(*cell)
        trace.append(after)
        if after - before != E.actual_step(mx - before):
            mism.append(f"{before:g}->{after:g}(max {mx:g})")
    check("★ 逐秒对拍：增量恰好 = actual_step(最大 − 实际)", not mism,
          "; ".join(mism[:3]) or "30 秒全对")
    check("爬升单调不减、且绝不越过【最大】",
          trace == sorted(trace) and all(v <= 100 for v in trace),
          f"1/10/20/30 秒 = {trace[0]:g}/{trace[9]:g}/{trace[19]:g}/{trace[29]:g}")
    check("30 秒后逼近但未达 100（渐近的必然结果）",
          90 <= trace[-1] < 100, f"{trace[-1]:g}")
    a = fs.actual_at(*cell)
    check("每秒伤害恒 = basic_damage + 实际×damage_ratio",
          fs.damage_per_second(*cell) == 20 + a * 3,
          f"实际={a:g} → {fs.damage_per_second(*cell):g}")


def check_devices() -> None:
    """关卡装置（阻流阀 / 泵站 / 天桩）。"""
    print("\n[8] 关卡装置")
    from ak_tactic.battle import devices as D                              # noqa: PLC0415

    check("方向表覆盖四个屏幕方向",
          set(D.DIRECTIONS) == {"LEFT", "RIGHT", "UP", "DOWN"})
    check("★ UP 是屏幕上方 = MAA 坐标 y−1（与内部 y 轴朝哪边无关）",
          D.front_of((5, 5), "UP") == (5, 4), str(D.front_of((5, 5), "UP")))
    check("LEFT 前方是 x−1", D.front_of((5, 5), "LEFT") == (4, 5))
    check("身后格与前方格相反",
          D.behind_of((5, 5), "UP") == (5, 6)
          and D.behind_of((5, 5), "LEFT") == (6, 5))
    check("不认识的方向返回 None（不猜）",
          D.front_of((5, 5), "SIDEWAYS") is None
          and D.front_of((5, 5), "") is None)

    st = stage("act31side_08")
    if st is None:
        return
    ds = D.parse_devices(st)
    check("解析出装置", len(ds) > 0, f"{len(ds)} 个")
    check("装置身份取自 inst.characterKey（prefabKey 不存在）",
          all(d.key.startswith("trap_") for d in ds),
          "、".join(sorted({d.key for d in ds})))
    check("中文名解析出来了",
          all(d.name != d.key for d in ds),
          "、".join(sorted({d.name for d in ds})))
    check("全部装置都在图内",
          all(st.map.inside(*d.cell) for d in ds))

    # ★ 行翻转的实关判据：这些装置是**摆在田地上**的（闸门不可能摆在高台上）。
    #   行不翻的话它们会整批落到图的另一侧，落到高台或图外。
    fs = E.FarmlandSystem(st, E.PolluteParams.from_stage(st, "NORMAL"))
    on_farm = [d for d in ds if d.cell in fs._index]
    check("★ 全部装置都落在田地上（行翻转的实关判据）",
          len(on_farm) == len(ds), f"{len(on_farm)}/{len(ds)}")

    blockers = [d for d in ds if d.key == D.BLOCKER_KEY]
    check("这一关有阻流阀", len(blockers) > 0, f"{len(blockers)} 个")
    # 我先前只看探针打印的前 12 个装置就断言「全在一列」，实际 16 个并非同一个 y；
    # 正确的判据是「**存在**一条成列的坝」，以及如实报出分布。
    rows = {}
    for d in blockers:
        rows.setdefault(d.cell[1], []).append(d.cell[0])
    biggest = max((len(v) for v in rows.values()), default=0)
    spread = "；".join(f"y={y}: x{min(v)}-{max(v)}（{len(v)}个）"
                      for y, v in sorted(rows.items()))
    check("★ 阻流阀成列摆放（最大一列 ≥ 5 个，是一道坝而非零散）",
          biggest >= 5, spread)

    # ★ 阻流阀建成会**改变田地几何本身**：切断之后片数必须变多。
    before = len(fs.fields)
    for d in blockers:
        fs.sever(*d.cell)
    check("★ 阻流阀建成后田地重划（片数变多，不是原地不动）",
          len(fs.fields) > before, f"{before} 片 -> {len(fs.fields)} 片")
    check("被摘掉的地块不再是田地",
          all(not fs.is_farmland(*d.cell) for d in blockers))

    # 接进模拟器：阻流阀按自己的技能 duration 在 3 秒后建成。
    from ak_tactic.battle.sim import BattleSimulator                      # noqa: PLC0415
    from ak_tactic.gamedata.enemy import EnemyLibrary                     # noqa: PLC0415
    try:
        lib = EnemyLibrary()
        s = BattleSimulator(st, enemy_at=lib.get)
    except Exception as exc:                                              # noqa: BLE001
        skip("阻流阀建成时机", f"敌人库不可用：{type(exc).__name__}")
        return
    check("模拟器读到了阻流阀的坐标",
          len(s._blocker_cells) == len(blockers), f"{len(s._blocker_cells)}")
    check("开场时阻流阀还没建成（地块仍是田地）",
          s.farmland.is_farmland(*blockers[0].cell))
    s._t = 0.0
    s._environment_tick(D.BUILD_SECONDS, D.BUILD_SECONDS)
    check("★ 到 BUILD_SECONDS 后阻流阀建成、地块不再是田地",
          not s.farmland.is_farmland(*blockers[0].cell),
          f"{D.BUILD_SECONDS:g}s")
    check("第二次 tick 不会重复切断（一次性事件）",
          len({c for f in s.farmland.fields for c in f.cells})
          == len(s.farmland._index))


def check_pump() -> None:
    """泵站「泵水」。

    实关里泵站的水源地**多半是清澈的**（8 关 14 个泵站里，开场【实际】>0 的
    几乎没有），所以受污那一支、以及「范围+2」必须**用构造场景测**——
    只跑实关会把两个分支全漏掉，而覆盖率看着还是满的。
    """
    print("\n[9] 泵站")
    st = stage("act31side_04")
    if st is None:
        return
    from ak_tactic.battle.devices import parse_devices, PUMP_KEY            # noqa: PLC0415
    from ak_tactic.battle.environment import pump_once                      # noqa: PLC0415

    pumps = [d for d in parse_devices(st) if d.key == PUMP_KEY]
    check("这一关有泵站", len(pumps) > 0, f"{len(pumps)} 个")
    if not pumps:
        return
    p = pumps[0]

    def fresh():
        return E.FarmlandSystem(st, E.PolluteParams.from_stage(st, "NORMAL"))

    fs = fresh()
    src, tgt = p.behind, p.front
    check("条件齐备（身后与前方都是田地）",
          fs.is_farmland(*src) and fs.is_farmland(*tgt),
          f"身后{src} 前方{tgt}")

    # ---- 清澈分支：只降【最大】，不动各格【当前】
    check("源头开场是清澈的", fs.actual_at(*src) == 0)
    g = fs.field_at(*tgt)
    before_max, before_act = g.maximum, fs.actual_at(*tgt)
    r = fs.pump(p.cell, p.direction)
    check("★ 清澈 → 目标组【最大】−1", r and r["kind"] == "clear"
          and g.maximum == before_max - 1, f"{before_max:g} → {g.maximum:g}")
    check("★ 清澈分支**不动**各格【当前】（与受污分支不对称，原文如此）",
          fs.actual_at(*tgt) == before_act, f"当前 {before_act:g}")

    # ---- 受污分支：既抬【最大】也抬**各格的**【当前】
    # ⚠ 必须同时抬**水源地那片田的【最大】**。我第一版只把那一格的【当前】
    #   设成 50、却留着组【最大】=0，于是停止条件 `目标组max >= 水源地max`
    #   立刻成立（30>=0）而返回 hold —— 那是**构造出来的不可能状态**：
    #   正常演化里【当前】是朝【最大】靠拢的，不会出现当前 50 而最大 0。
    fs = fresh()
    g = fs.field_at(*tgt)
    gs = fs.field_at(*src)
    gs.maximum = 50.0
    fs.actual[src] = 50.0
    m0 = g.maximum
    act_cells = {c: fs.actual_at(*c) for c in list(g.cells)[:5]}
    r = fs.pump(p.cell, p.direction)
    check("★ 受污 → 目标组【最大】+1", r and r["kind"] == "raise"
          and g.maximum == m0 + 1, f"{m0:g} → {g.maximum:g}")
    check("★ 并且**每一格的【当前】也 +1**（不是只抬最大）",
          all(fs.actual_at(*c) == v + 1 for c, v in act_cells.items()),
          f"{len(act_cells)} 格")

    # ---- 停止条件：目标组【最大】≥ 水源地【最大】时停（组间比较）
    fs = fresh()
    g = fs.field_at(*tgt)
    gs = fs.field_at(*src)
    gs.maximum = 30.0
    fs.actual[src] = 30.0
    g.maximum = 30.0
    r = fs.pump(p.cell, p.direction)
    check("★ 追平后停止增加（比的是**组间【最大】**，不是那一格的【当前】）",
          r is not None and r["kind"] == "hold" and r["delta"] == 0.0,
          str({k: v for k, v in (r or {}).items() if k != "group"}))

    # ---- 范围：默认身前一格；水源地有我方单位时 +2
    check("★ 范围是**前方格数**（1 → 3），不是攻击范围那种几何",
          E.PUMP_RANGE == 1 and E.PUMP_RANGE_BONUS == 2)
    fs = fresh()
    check("默认范围下找得到目标", fs.pump(p.cell, p.direction) is not None)
    check("水源地有我方单位时用 3 格（本轮实关无此场景，走参数）",
          fs.pump(p.cell, p.direction, ally_on_source=True) is not None)

    # ★ 身后不是田地 → 一定不泵水。用「拿目标格当泵站、朝原方向」构造：
    #   它的身后是泵站自己那格，而那格**是**田地，所以不能这么测；
    #   改用朝地图外的一侧，身后必然越界。
    out_open = E.FarmlandSystem(st, E.PolluteParams.from_stage(st, "NORMAL"))
    edge = min(out_open._index, key=lambda c: c[0])       # 最左的田地格
    check("★ 身后越界（不是田地）→ 完全不泵水",
          out_open.pump(edge, "RIGHT") is None
          or out_open.field_at(edge[0] + 1, edge[1]) is not None,
          f"取 {edge} 朝右")
    check("方向不认识 → 不泵水（不猜）", out_open.pump(p.cell, "SIDEWAYS") is None)

    # ---- 驱动函数：只认 PUMP_KEY，别的装置混进来要被忽略
    fs = fresh()
    mixed = pumps + [d for d in parse_devices(st) if d.key != PUMP_KEY]
    out = pump_once(fs, mixed, ally_cells=())
    check("★ pump_once 只驱动泵站，混进别的装置会被忽略",
          all(isinstance(x, dict) for x in out), f"{len(out)} 条")
    check("泵水速率是每秒 1 点（原文「以每秒1点的速度」）",
          E.PUMP_RATE == 1.0)





def check_enemy_mech() -> None:
    """敌人侧关卡机制（怀黍离）：死亡污染、加速、蜕皮、召唤、明识形态、
    以及 runes 的**敌人修饰层**（属性乘数 / 黑板乘数 / 生命点 / 费用回复）。

    ⚠ 这一节全部是**构造场景**：怀黍离不在三条回归基线里（1-7 / SR-6 /
    SR-EX-8 都没有这些机制），拿不到"真关卡里跑出来的数"来对。
    凡是在真实关卡数据里**不可达**的分支，这里会明说，而不是假装跑过。
    """
    print("\n[10] 敌人侧机制（怀黍离）")
    from ak_tactic.battle import stage_mul as M                            # noqa: PLC0415
    from ak_tactic.battle.damage import DamageType                         # noqa: PLC0415
    from ak_tactic.battle.sim import BattleSimulator                       # noqa: PLC0415
    from ak_tactic.gamedata.enemy import EnemyLibrary                      # noqa: PLC0415

    try:
        lib = EnemyLibrary()
    except Exception as exc:                                              # noqa: BLE001
        skip("敌人侧机制", f"敌人库不可用：{type(exc).__name__}: {exc}")
        return

    # ---------------------------------------------------------- 10.1 黑板
    # 逐键对真数据。这些数**不是**从 prts 正文抄的，是 gamedata 黑板里的原值
    # （正文与黑板拼法不一致的地方已在 mech_fields 的文档里写明）。
    spec = [
        # (敌人, 档, 字段, 期望)
        ("enemy_1390_dhsbr_2", 0, "passive_pollut", 5.0),      # 除秽
        ("enemy_1392_dhshld_2", 0, "passive_pollut", 15.0),    # 厌肮
        ("enemy_1396_dhdts_2", 0, "speedup_move", 3.0),        # 田鼷猛士
        ("enemy_1397_dhtsxt_2", 0, "speedup_move", 4.0),       # 田鼷大盗
        ("enemy_1397_dhtsxt_2", 0, "speedup_duration", 5.0),
        ("enemy_1397_dhtsxt_2", 0, "speedup_cooldown", 10.0),
        ("enemy_1397_dhtsxt", 0, "death_cnt", 2),              # 田鼷飞贼
        ("enemy_1396_dhdts", 0, "aura_hit_ratio", 0.5),        # 田鼷力士
        ("enemy_1396_dhdts_2", 0, "aura_hit_ratio", 0.7),
        ("enemy_1550_dhnzzh", 1, "phit_cnt", 4),
        ("enemy_1550_dhnzzh", 1, "phit_atk", -40.0),
        ("enemy_1550_dhnzzh", 1, "phit_max_stack", 80),
        ("enemy_1550_dhnzzh", 1, "pm2_atk", -0.6),
        ("enemy_1550_dhnzzh", 1, "pm2_mark_pollut", 40.0),
        ("enemy_1550_dhnzzh", 1, "pm2_invincible", 5.0),
    ]
    bad = []
    for eid, lv, field, want in spec:
        got = getattr(lib.get(eid, lv), field, None)
        if got != want:
            bad.append(f"{eid}.{field}={got!r}≠{want!r}")
    check("★ 六个黑板前缀逐键取到真值", not bad, "; ".join(bad[:3]) or f"{len(spec)} 项")
    check("死亡给装置点名的是阻流阀",
          lib.get("enemy_1397_dhtsxt").death_token == "trap_139_dhtl")
    check("★ 两代前缀拼法都认（瘴走 Reborning、死志走 Reborn）",
          lib.get("enemy_1394_dhzts").reborn_prefix == "Reborning."
          and lib.get("enemy_1394_dhzts").reborn_interval == 0.5,
          f"瘴 interval={lib.get('enemy_1394_dhzts').reborn_interval:g}")

    # ★ 充能与召唤是**两条互不相干的分支**：瘴只有充能、祟只有召唤。
    #   混起来的读法（"有 interval 就是充能"）会把祟算成「每次扣 0 点病害值」
    #   的充能怪，而召唤整支静默消失——所以这两条要同时钉住。
    check("★ 瘴有充能无召唤", lib.get("enemy_1394_dhzts").reborn_summons == ()
          and lib.get("enemy_1394_dhzts").reborn_pollut == 10.0)
    summon = lib.get("enemy_1550_dhnzzh", 1).reborn_summons
    check("★ 祟有召唤无充能（两条分支没被合并）",
          len(summon) == 2 and lib.get("enemy_1550_dhnzzh", 1).reborn_interval == 0.0,
          str(summon))
    def _exists(eid: str) -> bool:
        try:
            lib.get(eid)
            return True
        except Exception:                                                 # noqa: BLE001
            return False

    check("召唤点名的敌人都真实存在",
          all(_exists(eid) for _i, _c, eid in
              tuple(summon) + tuple(lib.get("enemy_1550_dhnzzh", 0).reborn_summons)),
          str([e for _i, _c, e in summon]))

    # ---------------------------------------------------------- 10.2 runes
    st7 = stage("act31side_ex07") or load_stage("act31side_ex07")
    m7 = M.parse_rune_muls(st7.raw.get("runes"), "FOUR_STAR")
    base5 = lib.get("enemy_1390_dhsbr_2").passive_pollut
    got10 = M.apply_rune_muls(lib.get("enemy_1390_dhsbr_2"), m7).passive_pollut
    got30 = M.apply_rune_muls(lib.get("enemy_1392_dhshld_2"), m7).passive_pollut
    check("★ 天赋黑板乘数生效：+5 → +10、+15 → +30（ex07 四星档）",
          (got10, got30) == (10.0, 30.0), f"{got10:g} / {got30:g}")
    check("★ 乘数**不改库**（下一关不会跟着变强）",
          lib.get("enemy_1390_dhsbr_2").passive_pollut == base5, f"{base5:g}")
    check("NORMAL 档不吃四星乘数",
          M.apply_rune_muls(lib.get("enemy_1390_dhsbr_2"),
                            M.parse_rune_muls(st7.raw.get("runes"), "NORMAL")
                            ).passive_pollut == base5)
    # ★ 但真正要验的是**模拟器走的那条路**：乘数包在 `enemy_at` 的出口上，
    #   不是手动调一下 `apply_rune_muls` 就算接了线。
    s7f = BattleSimulator(stage("act31side_ex07#f#"), enemy_at=lib.get,
                          environment_difficulty="FOUR_STAR")
    s7n = BattleSimulator(stage("act31side_ex07"), enemy_at=lib.get)
    check("★ 走模拟器自己的取数口：四星档 +10、普通档仍是 +5",
          s7f.enemy_at("enemy_1390_dhsbr_2", 0).passive_pollut == 10.0
          and s7n.enemy_at("enemy_1390_dhsbr_2", 0).passive_pollut == 5.0,
          f"{s7f.enemy_at('enemy_1390_dhsbr_2', 0).passive_pollut:g} / "
          f"{s7n.enemy_at('enemy_1390_dhsbr_2', 0).passive_pollut:g}")
    check("乘数层不改库（模拟器跑完，库里还是原值）",
          lib.get("enemy_1390_dhsbr_2").passive_pollut == base5)

    st2 = load_stage("act31side_ex02")
    m2 = M.parse_rune_muls(st2.raw.get("runes"), "FOUR_STAR")
    a = M.apply_rune_muls(lib.get("enemy_1395_dhxts_2"), m2)
    b = lib.get("enemy_1395_dhxts_2")
    check("★ 属性乘数生效：点名条叠在全局条之上（1.2 × 1.5）",
          a.max_hp == b.max_hp * 1.8 and a.atk == b.atk * 1.2,
          f"hp {b.max_hp:g}→{a.max_hp:g}、atk {b.atk:g}→{a.atk:g}")
    check("点名条只动它点名的敌人（别的敌人只吃全局 1.2，不吃 1.5）",
          abs(M.apply_rune_muls(lib.get("enemy_1390_dhsbr_2"), m2).max_hp
              - lib.get("enemy_1390_dhsbr_2").max_hp * 1.2) < 1e-9)

    st4 = load_stage("act31side_ex04")
    m4 = M.parse_rune_muls(st4.raw.get("runes"), "FOUR_STAR")
    sk = M.apply_rune_muls(lib.get("enemy_1393_dhele_2"), m4)
    v = [x for x in sk.skills_raw[0]["blackboard"] if x["key"] == "atk_scale_magic"][0]
    check("技能黑板乘数按 prefabKey 点名改写（0.8 × 1.3 = 1.04）",
          abs(v["value"] - 1.04) < 1e-9, f"{v['value']!r}")
    check("⚠ 但它**没有消费者**（模拟器不驱动敌方技能，故仍标 TODO）",
          lib.get("enemy_1393_dhele_2").skills_raw[0]["blackboard"][0]["value"] == 0.8)

    # 生命点与费用回复：两代键名（`global_lifepoint` / `gbuff_lifepoint`）
    st1 = load_stage("act31side_ex01")
    check("★ 生命点改写：ex01 四星档 = 1、普通档 = 3",
          M.global_lifepoint(st1, "FOUR_STAR") == 1
          and M.global_lifepoint(st1, "NORMAL") is None)
    s_lp, _ = BattleSimulator(load_stage("act31side_ex01#f#"), enemy_at=lib.get,
                              environment_difficulty="FOUR_STAR"), None
    check("★ 模拟器真的按 rune 覆写生命点（四星 1 条命）", s_lp.life == 1,
          f"life={s_lp.life}")
    check("普通档不覆写（用关卡自己的 3）",
          BattleSimulator(load_stage("act31side_ex01"), enemy_at=lib.get).life == 3)

    st17 = stage("1-7")
    if st17 is not None:
        check("★ 老键名同样认（1-7 四星档用的是 gbuff_lifepoint）",
              M.global_lifepoint(st17, "FOUR_STAR") == 1,
              f"lp={M.global_lifepoint(st17, 'FOUR_STAR')}")
        check("费用回复乘数：1-7 四星档 scale=2 → 每点费用 0.5 秒",
              M.cost_recovery_scale(st17, "FOUR_STAR") == 2.0
              and BattleSimulator(st17, enemy_at=lib.get,
                                  environment_difficulty="FOUR_STAR"
                                  ).cost_time == 0.5)
    # ★ 三条回归基线都是**普通档**、且这一层对它们是空的 —— 钉住"没动基线"。
    for lid in ("main_01-07", "act54side_06", "act54side_ex08"):
        s0 = BattleSimulator(load_stage(lid), enemy_at=lib.get)
        check(f"  回归基线 {lid} 上没有修饰层（零改动）",
              not s0.rune_muls and M.global_lifepoint(load_stage(lid)) is None)

    # ------------------------------------------------- 10.3 死亡污染（走真链路）
    st = stage("act31side_08")
    if st is None:
        return
    fs0 = E.FarmlandSystem(st, E.PolluteParams.from_stage(st, "NORMAL"))
    cells = sorted(fs0.fields[0].cells) if fs0.fields else []
    if not cells:
        skip("死亡污染落点", "这一关没有田地")
        return
    cell = cells[0]

    def mech_sim(enemy_id, level, at, **kw):
        stx = load_stage("act31side_08")
        s = BattleSimulator(stx, enemy_at=lib.get, **kw)
        e = s._build_enemy(enemy_id, level, [(float(at[0]), float(at[1]))], [],
                           0.0, 0.0)
        e.position = (float(at[0]), float(at[1]))
        s.enemies.append(e)
        return s, e

    s, e = mech_sim("enemy_1390_dhsbr_2", 0, cell)
    before = s.farmland.actual_at(*cell)
    mx_before = s.farmland.maximum_at(*cell)
    s._damage_enemy(e, e.max_hp + 1, 1.0, DamageType.PHYSICAL)
    check("构造场景里敌人确实被打死了", not e.alive)
    s._enemy_mech_tick(0.05, 1.05)
    after = s.farmland.actual_at(*cell)
    check("★ 未被阻挡时：污染落在**自身**那格的田地上（+5）",
          abs(after - before - 5.0) < 1e-9, f"{before:g}→{after:g}")
    check("★ 同一格【最大】也被顶上去（否则下一秒就被靠拢拉回去）",
          s.farmland.maximum_at(*cell) >= max(mx_before, after),
          f"最大 {mx_before:g}→{s.farmland.maximum_at(*cell):g}")
    check("死亡效果只结一次（第二帧不再加）",
          (s._enemy_mech_tick(0.05, 1.10)
           or s.farmland.actual_at(*cell)) == after)

    # 被阻挡时：圆心挪到**挡它的那个干员**脚下那一格（原文的括号条件）
    other = cells[-1] if cells[-1] != cell else (cell[0] + 1, cell[1])

    class _Stub:
        """只有「还活着 / 在哪」的干员桩。

        这一节测的是**污染落点与标记**，不是阻挡判定本身——阻挡关系由
        `check_battle.py` 管，这里只需一个能塞进 `blocked_by` 的位置。
        """

        def __init__(self, pos):
            self.position = (float(pos[0]), float(pos[1]))
            self.alive = True
            self.retreated = False

    s2, e2 = mech_sim("enemy_1390_dhsbr_2", 0, cell)
    e2.blocked_by = _Stub(other)
    b_self, b_op = s2.farmland.actual_at(*cell), s2.farmland.actual_at(*other)
    s2._damage_enemy(e2, e2.max_hp + 1, 1.0, DamageType.PHYSICAL)
    s2._enemy_mech_tick(0.05, 1.05)
    check("★ 被阻挡时：圆心是阻挡者那一格（自身那格不动）",
          s2.farmland.actual_at(*other) > b_op
          and abs(s2.farmland.actual_at(*cell) - b_self) < 1e-9,
          f"干员格 {b_op:g}→{s2.farmland.actual_at(*other):g}、"
          f"自身格 {b_self:g}→{s2.farmland.actual_at(*cell):g}")

    # 半径 1.0 的**圆**：十字五格，够不到斜角
    check("★ 半径 1.0 是圆不是方（斜角 √2 够不到）",
          set(E.cells_in_radius(5, 5, 1.0))
          == {(5, 5), (4, 5), (6, 5), (5, 4), (5, 6)})
    check("半径 0.5 只覆盖自身那一格（阻流阀那条用的是 0.5）",
          E.cells_in_radius(5, 5, 0.5) == [(5, 5)])

    # ------------------------------------------------------- 10.4 加速
    s3, e3 = mech_sim("enemy_1397_dhtsxt", 0, cell)
    check("开场无增益", e3.haste_multiplier == 1.0)
    s3._damage_enemy(e3, 10.0, 1.0, DamageType.PHYSICAL)
    check("★ 受击且未被阻挡 → 移速 ×(1+4.0)",
          e3.haste_multiplier == 5.0 and e3.speedup_timer == 5.0,
          f"haste={e3.haste_multiplier:g}")
    e3.reborn_at = -1.0
    e3.blocked_by = _Stub(cell)
    s3._enemy_mech_tick(0.1, 1.1)
    check("★ 被阻挡**立刻**解除（不是等持续时间走完）",
          e3.haste_multiplier == 1.0)
    e3.blocked_by = None
    s3._damage_enemy(e3, 10.0, 1.5, DamageType.PHYSICAL)
    check("★ 冷却期内（10 秒）不能再获得", e3.haste_multiplier == 1.0)
    s3._damage_enemy(e3, 10.0, 11.5, DamageType.PHYSICAL)
    check("冷却过后可以再获得", e3.haste_multiplier == 5.0)
    s3._enemy_mech_tick(5.0, 16.5)
    check("持续时间到点自动收回", e3.haste_multiplier == 1.0)
    check("★ 增益不写在 `speed_multiplier` 上（那个被积雪每帧重写）",
          e3.speedup_move > 0 and hasattr(e3, "haste_multiplier"))

    # ------------------------------------------------------- 10.5 蜕皮
    s4, e4 = mech_sim("enemy_1550_dhnzzh", 1, cell)
    atk0 = e4.atk
    for i in range(4):
        s4._damage_enemy(e4, 100.0, 1.0 + i * 0.1, DamageType.PHYSICAL)
    check("★ 每 4 次伤害蜕皮一层（次数不是伤害量）", e4.phit_stacks == 1,
          f"stacks={e4.phit_stacks} hits={e4.phit_hits}")
    check("★ 一层改属性：攻击 −40 / 防御 −50 / 法抗 −1 / 移速 +0.01",
          (e4.atk, e4.defense, e4.res)
          == (atk0 - 40, 4000 - 50, 80 - 1), f"atk={e4.atk:g}")
    s4._damage_enemy(e4, 100.0, 1.5, DamageType.PHYSICAL)
    check("满 4 次即触发，第 5 次只累计不叠层",
          (e4.phit_stacks, e4.phit_hits) == (1, 1),
          f"stacks={e4.phit_stacks} hits={e4.phit_hits}")
    # 上限：一路打到 80 层就不再叠（也不能把攻击力叠成负数）
    for i in range(4 * 100):
        s4._damage_enemy(e4, 1.0, 2.0 + i * 0.001, DamageType.PHYSICAL)
    check("★ 蜕皮封顶 80 层（继续挨打也不再加）", e4.phit_stacks == 80,
          f"stacks={e4.phit_stacks} atk={e4.atk:g}")
    check("每 10 层重量 −1（80 层即 −8）", e4.weight == 10 - 8,
          f"weight={e4.weight:g}")

    # ------------------------------------------------- 10.6 召唤与明识形态
    s5, e5 = mech_sim("enemy_1550_dhnzzh", 1, cell)
    check("祟带两路召唤（8 秒 2 个 / 20 秒 1 个）",
          len(e5.reborn_summons) == 2 and e5.reborn_summons[0][:2] == (8.0, 2),
          str(e5.reborn_summons))
    e5.reborn_delay = 1.0
    s5._damage_enemy(e5, e5.max_hp + 1, 1.0, DamageType.PHYSICAL)
    s5._reborn_tick(1.0)
    check("★ 倒下进入重生窗口、排好两路召唤",
          e5.pending_reborn and list(e5.reborn_summon_at) == [9.0, 21.0],
          f"{e5.reborn_summon_at}")
    check("★ 重生完成即切**明识形态**：攻击 ×0.4、2 连击、5 秒无敌",
          (s5._reborn_tick(2.0), e5.pm2_active, e5.atk, e5.attack_times,
           e5.invincible_until)[1:] == (True, 4000 * 0.4, 2, 7.0),
          f"atk={e5.atk:g} 连击={e5.attack_times} 无敌到 {e5.invincible_until:g}")
    check("明识形态下防御 ×0.3、法抗 −30、移速 +200%",
          abs(e5.defense - 4000 * (1.0 + e5.pm2_def)) < 1e-9
          and abs(e5.res - 50) < 1e-9 and e5.haste_multiplier == 3.0,
          f"def={e5.defense:g} res={e5.res:g} haste={e5.haste_multiplier:g}")
    check("★ 无敌期内打不掉血（这是「5 秒无敌」，不是减伤）",
          s5._damage_enemy(e5, 1000.0, 5.0, DamageType.PHYSICAL) == 0.0)
    check("属性改写**只做一次**（反复进形态不会指数衰减）",
          abs(e5.atk - 4000 * 0.4) < 1e-9)
    check("⚠ 远程化只在本来就有射程时生效（祟 rangeRadius = −1，故仍近战）",
          e5.apply_way != "RANGED", f"applyWay={e5.apply_way} "
          f"range={e5.attack_range:g}")

    # 召唤真的落地（第二路 21 秒时也要出）
    s6, e6 = mech_sim("enemy_1550_dhnzzh", 1, cell)
    # ⚠ **不要**把 `reborn_delay` 改短：召唤只在重生窗口内按点走，
    #   把 40 秒窗口压成 1 秒会让 8 秒/20 秒两路**根本来不及**出——
    #   而"8 秒那路在同一次调用里先出再复活"又会让检查假绿。
    s6._damage_enemy(e6, e6.max_hp + 1, 0.0, DamageType.PHYSICAL)
    s6._reborn_tick(0.0)
    # 召唤真的落地。⚠ 换一个**不是保护目标**的格子：脚下就是终点时
    # `ground_path` 会返回只含自身的一点路径，"有没有路径"这条检查会假绿。
    away = next((c for c in ((x, y) for y in range(st.map.height)
                             for x in range(st.map.width))
                 if st.map.walkable(*c) and c not in set(st.map.end_points)
                 and s6.farmland.is_farmland(*c)), None)
    if away is None:
        skip("召唤路径", "找不到非终点的可行走田地格")
    else:
        e6.position = (float(away[0]), float(away[1]))
    n0 = len(s6.enemies)
    s6._reborn_tick(8.0)
    new = [x for x in s6.enemies if x is not e6 and x not in s6.enemies[:n0]]
    check("★ 到点真的召唤出 2 个随从，位置在脚下那一格",
          len(new) == 2 and all(x.cell() == e6.cell() for x in new),
          f"{len(new)} 个：{sorted({x.enemy_id for x in new})} 于 {e6.cell()}")
    check("★ 召唤体带得出通往**保护目标**的路径（不是原地不动的死物）",
          bool(new) and len(new[0].route) > 1,
          f"route={len(new[0].route) if new else 0} 点、"
          f"起点 {new[0].route[0] if new else None} → "
          f"终点 {new[0].route[-1] if new else None}")
    check("召唤体走的是最短的那条可达路径（逐目标试出来的）",
          bool(new) and new[0].route[-1] in set(st.map.end_points),
          f"终点 {new[0].route[-1] if new else None}")

    # 清水：明识形态站在**病害值 0 的田地**上要再减一档
    clean_cell = next((c for f in s6.farmland.fields for c in sorted(f.cells)
                       if s6.farmland.actual_at(*c) == 0), None)
    if clean_cell is None:
        skip("明识形态的清水分支", "这一关没有病害值 0 的田地")
    else:
        s7, e7 = mech_sim("enemy_1550_dhnzzh", 1, clean_cell)
        s7._enter_pm2(e7, 100.0)
        base_def = e7.reborn_def_base
        check("清水前：防御 ×0.3、移速 ×3",
              abs(e7.defense - base_def * (1.0 + e7.pm2_def)) < 1e-9
              and e7.haste_multiplier == 3.0,
              f"def={e7.defense:g} haste={e7.haste_multiplier:g}")
        s7._pm2_tick(e7, 100.0)
        check("★ 站在病害值 0 的田地上 → 防御再降到 0.15 倍、**失去移速加成**",
              (e7.pm2_clean, e7.haste_multiplier) == (True, 1.0)
              and abs(e7.defense - base_def * 0.15) < 1e-9,
              f"def={e7.defense:g} haste={e7.haste_multiplier:g}")
        # 离开清水要能收回来
        dirty = next((f for f in s7.farmland.fields if f.maximum > 0), None)
        if dirty is not None:
            e7.position = (float(sorted(dirty.cells)[0][0]),
                           float(sorted(dirty.cells)[0][1]))
            s7.farmland.pollute_cell(*e7.cell(), 5.0)
            s7._pm2_tick(e7, 101.0)
            check("★ 离开清水后减益收回（不是单向的）",
                  e7.pm2_clean is False and abs(e7.defense - base_def * 0.3) < 1e-9
                  and e7.haste_multiplier == 3.0,
                  f"def={e7.defense:g} haste={e7.haste_multiplier:g}")

    # 标记退场：被它打过的干员退场 → 若它未被阻挡，田地再被污染
    s8, e8 = mech_sim("enemy_1550_dhnzzh", 1, cell)
    s8._enter_pm2(e8, 0.0)
    op_stub = _Stub(cell)
    s8.operators.append(op_stub)
    # ⚠ 要等无敌过去再打：进入形态带 5 秒无敌，无敌期内伤害为 0，
    #   而标记只在**真的挨到伤害**时才记（`dealt > 0` 之后）。
    #   先前这一条没等，标记自然是空的——这正说明"无敌确实挡掉了伤害"。
    s8._damage_enemy(e8, 10.0, 6.0, DamageType.PHYSICAL, source=op_stub)
    check("★ 明识形态记下了伤害来源（标记）", id(op_stub) in e8.marked_ops,
          f"marked={len(e8.marked_ops)}")
    op_stub.alive = False
    p_before = s8.farmland.actual_at(*cell)
    s8._pm2_tick(e8, 6.5)
    check("★ 被标记者退场 → 半径 1.0 内田地 +40（未被阻挡时）",
          s8.farmland.actual_at(*cell) > p_before,
          f"{p_before:g}→{s8.farmland.actual_at(*cell):g}")
    check("标记用掉即摘除（不会每帧重复污染）", not e8.marked_ops)

    # 被击倒给装置的机制**只记账**：这是"数据对了、效果无处落地"的如实记录
    s9, e9 = mech_sim("enemy_1397_dhtsxt", 0, cell)
    s9._damage_enemy(e9, e9.max_hp + 1, 1.0, DamageType.PHYSICAL)
    s9._enemy_mech_tick(0.05, 1.05)
    check("★ 田鼷飞贼被击倒记下 2 个阻流阀（但模拟器没有部署装置层）",
          s9.result.device_tokens
          and s9.result.device_tokens[0][1:] == ("trap_139_dhtl", 2),
          str(s9.result.device_tokens))
    check("⚠ 这条机制仍标 TODO（只记账不算实现）",
          __import__("ak_tactic.activity", fromlist=["ENEMY_BB_REGISTRY"])
          .ENEMY_BB_REGISTRY["DeathPassive."].status == "todo")

    # ★ 前提守卫：SpeedUp 写 `haste_multiplier`、明识形态也写它，
    #   两者若落在**同一个敌人**身上就会互相覆盖。当前数据里两拨敌人不相交，
    #   写成检查，以后谁把两套机制挂到同一个敌人身上会立刻红。
    both = [eid for eid in ("enemy_1396_dhdts", "enemy_1396_dhdts_2",
                            "enemy_1397_dhtsxt", "enemy_1397_dhtsxt_2",
                            "enemy_1550_dhnzzh")
            if lib.get(eid).speedup_move > 0 and lib.get(eid, 1).pm2_move > 0]
    check("★ 假设守卫：没有敌人同时带 SpeedUp 与明识形态（否则移速加成会打架）",
          not both, str(both))

    # ------------------------------------------- 10.7 「祟」整条链上真实几何
    # 上面几段都在桩场景里。这一段把 **ex08 的真实地图/装置/寻路**拿来，
    # 按关卡自己的出怪路线把「祟」摆出来，然后打掉它，走完
    # 倒下 → 召唤 → 归来 → 明识形态 这条链。
    # 真关卡里要走到这一步得先打掉它 50000 血，构造触发是唯一可行的验法。
    st8 = stage("act31side_ex08")
    if st8 is None:
        skip("「祟」整条链", "缺 act31side_ex08 缓存")
        return
    zspawn = next((sp for _t, sp in st8.timeline()
                   if sp.enemy_id.startswith("enemy_1550")), None)
    if zspawn is None:
        skip("「祟」整条链", "这一关的出怪表里没有「祟」")
        return
    s10 = BattleSimulator(st8, enemy_at=lib.get)
    e10 = s10._spawn(zspawn.enemy_id, zspawn.level, zspawn.route_index, 0.0)
    s10.enemies.append(e10)
    check("祟按关卡自己的路线入场",
          e10.position == tuple(e10.route[0]), f"{e10.position}")
    # ⚠ **不动** `reborn_delay`：关卡的 40 秒就是召唤窗口（8 秒 / 20 秒两路都在里面）
    s10._damage_enemy(e10, e10.max_hp + 1, 0.0, DamageType.PHYSICAL)
    s10._reborn_tick(0.0)
    check("★ 打掉后进入重生窗口（不是当场算死）", e10.pending_reborn)
    n_before = len(s10.enemies)
    s10._reborn_tick(8.0)
    born = [x for x in s10.enemies[n_before:] if x is not e10]
    check("★ 真实关卡上召唤出随从、数值取自本关的敌人档位",
          len(born) == 2 and all(x.level == s10._summon_level(x.enemy_id)
                                 for x in born),
          f"{len(born)} 个 {sorted({(x.enemy_id, x.level) for x in born})}")
    check("★ 召唤体从「祟」脚下那一格起步、朝保护目标走",
          bool(born) and all(x.route and x.route[0] == e10.route[0]
                             for x in born)
          and all(x.route[-1] in set(st8.map.end_points) for x in born),
          f"{born[0].route[0]} → {born[0].route[-1]}" if born else "无")
    # 第二拍：8 秒那路在 16 秒再出 2 个，20 秒那路出 1 个 —— 一共 3 个。
    # （按**增量**数，不要用"总长度减一减一"，那样会把「祟」自己减两次。）
    n_before2 = len(s10.enemies)
    s10._reborn_tick(20.5)
    check("★ 两路各自按自己的间隔走（16 秒那次 2 个 + 20 秒那路 1 个）",
          len(s10.enemies) - n_before2 == 3,
          f"新增 {len(s10.enemies) - n_before2} 个")
    s10._reborn_tick(41.5)
    check("★ 40 秒后归来并切明识形态（真实关卡上同样成立）",
          e10.pm2_active and e10.attack_times == 2,
          f"pm2={e10.pm2_active} 连击={e10.attack_times}")


def main() -> int:
    print("=" * 68)
    print("关卡环境机制自检（ak_tactic/battle/environment.py）")
    print("=" * 68)
    check_blackboard()
    check_coords()
    check_farmland()
    check_params()
    check_evolution()
    check_settlement()
    check_sim_wiring()
    check_devices()
    check_pump()
    check_enemy_mech()
    print("\n" + "=" * 68)
    tail = f"通过 {_PASSED} 项，失败 {len(_FAILED)} 项"
    if _SKIPPED:
        tail += f"，跳过 {len(_SKIPPED)} 项（多为缺关卡缓存）"
    print(tail + "：")
    for name in _FAILED:
        print(f"  - {name}")
    print("=" * 68)
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
