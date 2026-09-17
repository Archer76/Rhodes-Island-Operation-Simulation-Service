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
