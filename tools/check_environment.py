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

    # ---------------------------------------------------- 2.2 可部署格的第四个取值
    #
    # `buildableType` 有四个取值，`ALL` = 地面与高台**都能放**。原先代码只认
    # MELEE / RANGED，`ALL` 于是落进"两种都不能"：`act31side_ex05`（33 格）与
    # `act31side_sub-1-2`（42 格）**整图一个可部署格都没有** → 搜索的几何剪枝
    # 一个候选都不剩 → 无论选什么都是 0 条结果（见 `docs/environment.md` 第十四节）。
    from ak_tactic.gamedata.stage import Tile                          # noqa: PLC0415
    all_tile = Tile(key="tile_road", height="LOWLAND", buildable="ALL",
                    passable="ALL")
    check("★ `buildableType: ALL` 判成地面与高台**都能放**",
          all_tile.deployable_melee and all_tile.deployable_ranged
          and all_tile.deployable, all_tile.buildable)
    check("  MELEE 只算地面、RANGED 只算高台（没被顺手放宽）",
          Tile(key="tile_road", height="LOWLAND", buildable="MELEE",
               passable="ALL").deployable_melee
          and not Tile(key="tile_road", height="LOWLAND", buildable="MELEE",
                       passable="ALL").deployable_ranged
          and Tile(key="tile_wall", height="HIGHLAND", buildable="RANGED",
                   passable="FLY_ONLY").deployable_ranged
          and not Tile(key="tile_wall", height="HIGHLAND", buildable="RANGED",
                       passable="FLY_ONLY").deployable_melee)
    check("  NONE 两种都不算",
          not Tile(key="tile_floor", height="LOWLAND", buildable="NONE",
                   passable="ALL").deployable)
    for sid, want in (("act31side_ex05", 33),):
        st_all = stage(sid)
        if st_all is None:
            skip(f"{sid} 可部署格", "关卡缓存缺失")
            continue
        got = len(st_all.map.melee_spots)
        check(f"★ {sid} 整图 `ALL`：可部署格不再是 0", got == want,
              f"{got} 格（原先是 0）")

    # 取值普查：`buildableType` **只许**出现这四个。换数据源/换版本时若冒出
    # 第五个取值，这里立刻红——否则它会像 `ALL` 一样，静静地把整图判成不可部署。
    import json as _json                                             # noqa: PLC0415
    import pathlib as _pathlib                                       # noqa: PLC0415

    known = {"NONE", "MELEE", "RANGED", "ALL"}
    root = _pathlib.Path(__file__).resolve().parent.parent
    lv_dir = root / "data" / "gamedata" / "map.ark-nights.com" / "levels"
    seen: dict[str, int] = {}
    odd: list[str] = []
    files = 0
    if lv_dir.exists():
        for p in lv_dir.rglob("level_*.json"):
            try:
                j = _json.loads(p.read_text(encoding="utf-8"))
            except Exception:                                        # noqa: BLE001
                continue
            files += 1
            for t in ((j.get("mapData") or {}).get("tiles") or []):
                v = t.get("buildableType")
                seen[v] = seen.get(v, 0) + 1
                if v not in known:
                    odd.append(f"{p.stem}:{v}")
    if files:
        check(f"★ 全量普查 {files} 个关卡：`buildableType` 没有第五个取值",
              not odd, f"未见过载：{odd[:5]}；取值分布 {seen}")
        check("  `ALL` 真的在用（不是理论取值）", seen.get("ALL", 0) > 0,
              f"ALL×{seen.get('ALL', 0)}")
    else:
        skip("buildableType 普查", "没有本地关卡缓存")


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
    # ★ 预置阻流阀**开场即在位**（它们走装置技能 2，没有持续时间），所以模拟器
    #   一建好，那些格子就已经不算田地了。判据要跟"单独构造"差出阻流阀的格数。
    from ak_tactic.battle import devices as D                              # noqa: PLC0415
    blk = [d for d in D.parse_devices(st) if d.key == D.BLOCKER_KEY]
    check("★ 模拟器里的田地 = 单独构造 − 预置阻流阀的格子（开场即在位）",
          len(s.farmland._index) == len(E.farmland_cells(st.map)) - len(blk),
          f"{len(s.farmland._index)} = {len(E.farmland_cells(st.map))} − {len(blk)}")
    check("★ 预置阻流阀的格子开场就不是田地",
          not any(s.farmland.is_farmland(*d.cell) for d in blk))
    check("田地被这道坝切成多片（不是原地不动）",
          len(s.farmland.fields) > 2, f"{len(s.farmland.fields)} 片")

    # ⚠ 接线判据要挂在**受污田地里真有可部署格**的关卡上，否则"接了线但永远
    #   打不到人"。开场就断开田地的预置阻流阀让这件事变得很挑：`act31side_08`
    #   的受污片只有 2 格、**没有可部署格**；`act31side_05` 的受污片有 10 格。
    #   所以几何看 08、接线与逐秒对拍看 05。
    st5 = stage("act31side_05")
    s5 = sim("act31side_05")[0] if st5 is not None else None
    if s5 is None or s5.farmland is None:
        skip("接线判据", "act31side_05 没有环境系统")
    else:
        fs5 = s5.farmland
        polluted = [f for f in fs5.fields if f.maximum > 0]
        dep_in = [c for f in polluted for c in f.cells
                  if st5.map.tile(*c).deployable]
        check("★ 有病害的田地里存在可部署格（否则接线毫无意义）",
              len(dep_in) >= 1, f"{len(dep_in)} 格，如 {sorted(dep_in)[:4]}")

        # 逐格播种：开场只有污染点那一格有【实际】，同组其余格子从 0 爬升。
        # 这条**钉住一个待裁定项**（另见 docs/verdicts-pending.md 的 E2）：
        # 若改成整片播种，这里会红，提醒改的人去核对那处歧义。
        seeds = set(fs5.params.init_pollut)
        others = [c for c in dep_in if c not in seeds]
        hot = sorted(others or dep_in, key=lambda c: -fs5.actual_at(*c))
        check("⚠ 逐格播种：开场时同组的**其余**可部署格【实际】为 0（待实机校正）",
              all(fs5.actual_at(*c) == 0 for c in others),
              f"{len(others)} 格；最高 {fs5.actual_at(*hot[0]):g}")
        seeded = [c for c in dep_in if c in seeds]
        if seeded:
            check("而播种点自己就是它的值（另注：这一点也可部署）",
                  all(fs5.actual_at(*c) == fs5.params.init_pollut[c]
                      for c in seeded),
                  f"{[(c, fs5.actual_at(*c)) for c in seeded]}")
        check("但所属田地的【最大】已经顶到污染点的值",
              all(fs5.maximum_at(*c) > 0 for c in dep_in),
              f"最低 {min(fs5.maximum_at(*c) for c in dep_in):g}")

        # ⚠ 爬升是**渐近**的，不是恒速：步长 = ceil(差值/25 + 1) 随差值缩小而变小。
        # 我第一版写的是「20 秒后到 100」，那是假设了恒速 5/秒——跑出 77 才暴露。
        # 正确的判据是逐秒对拍那条**规律**，而不是某个秒数上的某个数。
        fs = fs5
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
              trace == sorted(trace)
              and all(v <= fs.maximum_at(*cell) for v in trace),
              f"1/10/20/30 秒 = {trace[0]:g}/{trace[9]:g}/{trace[19]:g}/{trace[29]:g}")
        check("30 秒后逼近但未达顶（渐近的必然结果）",
              trace[-1] < fs.maximum_at(*cell),
              f"{trace[-1]:g} < {fs.maximum_at(*cell):g}")
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
    # ★ 预置阻流阀走**装置技能 2**（同名「阻流」，初始/消耗皆为 0、没有持续时间），
    #   正文只写「阻隔水流」；「3秒后建成」是**玩家手动部署**那一支（技能 1）的事。
    #   所以开场时它们已经在位——早先这里断言的是"开场还没建成、3 秒后才建成"，
    #   那等于让每一张有田地的图前 3 秒多算了若干格田地。
    check("★ 预置阻流阀开场即在位（技能 2，无持续时间）",
          s._blockers_built and not s.farmland.is_farmland(*blockers[0].cell))
    check("而它的生命值是满的（3.4% 是**手动部署**那一支的建成过程）",
          all(d.hp == d.max_hp for d in s._devices))
    check("只切了一次、没有重复切断",
          len({c for f in s.farmland.fields for c in f.cells})
          == len(s.farmland._index))

    # ★ 装置有血、会被拆（AuraHit）；拆掉之后**地形还回去**。
    #   这一整条用一个构造场景测：把一个阻流阀挪到一只田鼷脚下，
    #   让它"进入范围"两次（50+50=100），看装置是否被拆、田地是否并回来。
    from ak_tactic.battle.devices import (AURA_HIT_RADIUS, BLOCKER_KEY,      # noqa: PLC0415
                                          DEVICE_HP, DeviceUnit, device_hp,
                                          make_devices)
    from ak_tactic.battle.environment import FarmlandSystem                 # noqa: PLC0415

    check("三个装置的最大生命值都是 100（prts.wiki 装置信息）",
          all(DEVICE_HP[k] == 100.0 for k in
              (D.BLOCKER_KEY, D.PUMP_KEY, D.PILE_KEY)),
          str(sorted(DEVICE_HP.items())))
    check("AuraHit 半径 0.5 = 只有同格够得着",
          AURA_HIT_RADIUS == 0.5 and AURA_HIT_RADIUS < 1.0)
    unit = DeviceUnit(device=D.parse_devices(st)[0], max_hp=device_hp(D.BLOCKER_KEY))
    check("新装置满血、已建成", unit.hp == 100.0 and unit.built and unit.alive)
    check("★ 田鼷一次经过打掉目标最大生命值的 50%（=50 点）",
          unit.take_damage(0.5 * unit.max_hp) == 50.0 and unit.hp == 50.0)
    check("★ 再来一次拆掉（50+50 = 100）",
          unit.take_damage(0.5 * unit.max_hp) == 50.0
          and not unit.alive and unit.hp == 0.0)
    check("建成期间的装置无敌（手动部署的阻流阀 3 秒内打不掉）",
          DeviceUnit(device=D.parse_devices(st)[0], max_hp=100.0,
                     build_left=1.0).take_damage(999.0) == 0.0)

    # 地形还原：08 关的 (5,3) 是孤立的阻流阀格，拆掉它应当把那一格还回田地。
    fs_r = FarmlandSystem(st, E.PolluteParams.from_stage(st, "NORMAL"))
    for d in blockers:
        fs_r.sever(*d.cell)
    n_before, f_before = len(fs_r._index), len(fs_r.fields)
    cells = [d.cell for d in blockers]
    target_cell = (5, 3) if (5, 3) in cells else cells[0]
    fs_r.restore(*target_cell)
    check("★ 装置被拆 → 那一格还回田地",
          fs_r.is_farmland(*target_cell), f"{target_cell}")
    check("还回来的格数 +1",
          len(fs_r._index) == n_before + 1,
          f"{n_before} → {len(fs_r._index)}")
    check("田地重新连片（片数不变或变少，绝不会变多）",
          len(fs_r.fields) <= f_before,
          f"{f_before} → {len(fs_r.fields)} 片")
    check("还回来的格子【实际】从 0 起（它此前不是田地，没人污染过它）",
          fs_r.actual_at(*target_cell) == 0.0)
    # 高台/通道格即便被装置占了也不算田地：还回去应当什么都不做（不是报错）。
    not_farm = next(((x, y) for y in range(st.map.height)
                     for x in range(st.map.width)
                     if not fs_r.is_farmland(x, y)), None)
    if not_farm is not None:
        before_n = len(fs_r._index)
        fs_r.restore(*not_farm)
        check("不是田地的格子还回去也不变成田地（无副作用）",
              len(fs_r._index) == before_n and not fs_r.is_farmland(*not_farm),
              f"{not_farm}")


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
    fld = s.farmland.field_at(*cell)
    # 圆心那一格周围有 2 格同片田地，所以这一片缓存该收到 5×2 —— 原文是按
    # **地块**算的（「半径1.0范围内的田地地块病害值+5」），而缓存是按**连片**存的，
    # 于是同片里被点到的每格各记一份。这个乘积本身就是一条判据，下面单独验。
    hit = [c for c in E.cells_in_radius(*cell, 1.0)
           if s.farmland.is_farmland(*c)]
    want = 5.0 * len(hit)
    s._damage_enemy(e, e.max_hp + 1, 1.0, DamageType.PHYSICAL)
    check("构造场景里敌人确实被打死了", not e.alive)
    s._enemy_mech_tick(0.05, 1.05)
    # ★ 博士给的 prts.wiki「特殊机制#病害值」原文：污染**先进【缓存】**，
    #   每 0.2s 释放 1 点累加到【最大】，【实际】再每 1s 靠拢【最大】。
    #   所以"倒下那一瞬间"的正确表现是：**只动缓存，两套值都不动**。
    check("★ 被击倒时污染先进【缓存】（每格 +5），当场不改【实际】/【最大】",
          abs(fld.cache - want) < 1e-9
          and s.farmland.actual_at(*cell) == before
          and s.farmland.maximum_at(*cell) == mx_before,
          f"缓存={fld.cache:g}（半径内 {len(hit)} 格 ×5）"
          f" 实际={s.farmland.actual_at(*cell):g}"
          f" 最大={s.farmland.maximum_at(*cell):g}")
    cache_after = fld.cache
    s._enemy_mech_tick(0.05, 1.10)
    check("死亡效果只结一次（第二帧不再加）",
          abs(fld.cache - cache_after) < 1e-9, f"{cache_after:g}→{fld.cache:g}")
    # 0.2s 一拍、每拍 1 点 → 1 秒整好放完 5 点（本该放的量）
    s.farmland.tick(1.0)
    released = min(cache_after, 5.0)
    check("★ 缓存每 0.2s 释放 1 点：1.0 秒放 5 点、【最大】涨 5",
          abs(fld.cache - (cache_after - released)) < 1e-9
          and abs(s.farmland.maximum_at(*cell) - (mx_before + released)) < 1e-9,
          f"缓存 {cache_after:g}→{fld.cache:g}、"
          f"最大 {mx_before:g}→{s.farmland.maximum_at(*cell):g}")
    check("★ 【实际】不会凭空跟上：同一秒内的靠拢只走 actual_step(差值)",
          s.farmland.actual_at(*cell)
          == before + E.actual_step(s.farmland.maximum_at(*cell) - before),
          f"{before:g}→{s.farmland.actual_at(*cell):g}")
    check("⚠ 这条链路正是「+N 要不要抬【最大】」那个假两难的答案：两套值都不直接加",
          not hasattr(E, "POLLUTE_LIFTS_MAX"))

    # 缓存是**按连片**的：【最大】按片共享，缓存也跟着按片走。
    # 一次 pollute_area 里，每一格各自往**它所属那片**的缓存里记一份。
    c0 = sorted(fld.cells)[0]
    in_r = E.cells_in_radius(c0[0], c0[1], 1.0)
    farm_hit = [c for c in in_r if s.farmland.is_farmland(*c)]
    same = [c for c in farm_hit if s.farmland.field_at(*c) is fld]
    cache0 = fld.cache
    got = s.farmland.pollute_area(c0[0], c0[1], 1.0, 5.0)
    check("★ 逐格各记一份：记入总量 = 5 × 范围内**田地**格数",
          abs(got - 5.0 * len(farm_hit)) < 1e-9,
          f"{len(farm_hit)} 格 → 记入 {got:g}")
    check("★ 缓存按**连片**走：只有同片那几格的量落到这一片的缓存上",
          abs(fld.cache - cache0 - 5.0 * len(same)) < 1e-9,
          f"同片 {len(same)} 格 → 本片缓存 +{fld.cache - cache0:g}"
          f"（余下 {len(farm_hit) - len(same)} 格落在邻居片上）")

    # 被阻挡时：圆心挪到**挡它的那个干员**脚下那一格（原文的括号条件）。
    # ⚠ 两处踩过的坑：① 圆心必须取**另一片**田地里的格子，否则两边读的是同一个
    #   Field 对象，"自身那片没动"永远立不住；② 基线必须从**这一场**（s2）取，
    #   从上一场（s）取的 `fld_self` 是另一个系统的对象，比出来是 15→0。
    class _Stub:
        """只有「还活着 / 在哪」的干员桩。

        这一节测的是**污染落点与标记**，不是阻挡判定本身——阻挡关系由
        `check_battle.py` 管，这里只需一个能塞进 `blocked_by` 的位置。

        `skill_active = False`：`_enemy_on_hit` 里「打中时按技能概率控场」
        那一段要看它（另一个会话在加的机制）。桩不处在技能状态，如实写 False；
        少了这个属性整节会直接 `AttributeError`，而那与本节要测的东西无关。
        """

        def __init__(self, pos):
            self.position = (float(pos[0]), float(pos[1]))
            self.alive = True
            self.retreated = False
            self.skill = None
            self.skill_active = False

    s2, e2 = mech_sim("enemy_1390_dhsbr_2", 0, cell)
    fld_self = s2.farmland.field_at(*cell)
    other = next((c for f in s2.farmland.fields if f is not fld_self
                  for c in sorted(f.cells)), None)
    if other is None:
        skip("被阻挡时的污染圆心", "这一关只有一片田地，分不出两片")
        other = cell
    e2.blocked_by = _Stub(other)
    f_op = s2.farmland.field_at(*other)
    b_self, b_op = fld_self.cache, (f_op.cache if f_op else 0.0)
    s2._damage_enemy(e2, e2.max_hp + 1, 1.0, DamageType.PHYSICAL)
    s2._enemy_mech_tick(0.05, 1.05)
    check("★ 被阻挡时：圆心是阻挡者那一格的**那一片**（自身那片缓存不动）",
          f_op is not None and f_op.cache > b_op
          and abs(s2.farmland.field_at(*cell).cache - b_self) < 1e-9,
          f"干员片缓存 {b_op:g}→{f_op.cache if f_op else 0:g}、"
          f"自身片缓存 {b_self:g}→{s2.farmland.field_at(*cell).cache:g}")

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
            # ⚠ 不能只 `pollute_cell` 就完事：污染进的是【缓存】，要让这一格
            #   真的"脏"起来得推进时间（缓存 0.2s 释放 1 点 → 【最大】→
            #   1s 靠拢 → 【实际】）。
            s7.farmland.pollute_cell(*e7.cell(), 20.0)
            s7.farmland.tick(2.0)
            check("   （构造场景：这一格确实被弄脏了）",
                  s7.farmland.actual_at(*e7.cell()) > 0,
                  f"实际={s7.farmland.actual_at(*e7.cell()):g}")
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
    f8 = s8.farmland.field_at(*cell)
    p_before = f8.cache if f8 else 0.0
    s8._pm2_tick(e8, 6.5)
    check("★ 被标记者退场 → 半径 1.0 内田地 +40 记入缓存（未被阻挡时）",
          f8 is not None and f8.cache > p_before,
          f"缓存 {p_before:g}→{f8.cache if f8 else 0:g}")
    check("标记用掉即摘除（不会每帧重复污染）", not e8.marked_ops)

    # 被击倒给装置这条**已经接通**（2026-09-16）：额度进账 + `plan_device` 花得
    # 出去 + 建成那一刻断田。这里核的是"进账"那一半，"花出去"那一半在 §12。
    s9, e9 = mech_sim("enemy_1397_dhtsxt", 0, cell)
    s9._damage_enemy(e9, e9.max_hp + 1, 1.0, DamageType.PHYSICAL)
    s9._enemy_mech_tick(0.05, 1.05)
    check("★ 田鼷飞贼被击倒记下 2 个阻流阀（并进手上的额度）",
          s9.result.device_tokens
          and s9.result.device_tokens[0][1:] == ("trap_139_dhtl", 2)
          and int(s9.device_token_balance.get("trap_139_dhtl", 0)) == 2,
          f"{s9.result.device_tokens} / 额度 {s9.device_token_balance}")
    check("★ 这条机制已标 DONE（部署层真的存在，不是只记账）",
          __import__("ak_tactic.activity", fromlist=["ENEMY_BB_REGISTRY"])
          .ENEMY_BB_REGISTRY["DeathPassive."].status == "done")

    # ★ 前提守卫：SpeedUp 写 `haste_multiplier`、明识形态也写它，
    #   两者若落在**同一个敌人**身上就会互相覆盖。当前数据里两拨敌人不相交，
    #   写成检查，以后谁把两套机制挂到同一个敌人身上会立刻红。
    both = [eid for eid in ("enemy_1396_dhdts", "enemy_1396_dhdts_2",
                            "enemy_1397_dhtsxt", "enemy_1397_dhtsxt_2",
                            "enemy_1550_dhnzzh")
            if lib.get(eid).speedup_move > 0 and lib.get(eid, 1).pm2_move > 0]
    check("★ 假设守卫：没有敌人同时带 SpeedUp 与明识形态（否则移速加成会打架）",
          not both, str(both))

    # ------------------------------------------- 10.6b AuraHit：田鼷拆阻流阀
    # 走**真链路**（`_device_tick`），不是只测 `DeviceUnit.take_damage`：
    # 原文「进入阻流阀**半径 0.5** 范围内时**立刻**对其造成目标最大生命值
    # 50%/70% 的**真实**伤害」。半径 0.5 = 只有同格够得着，所以把田鼷力士
    # （0.5 → 50 点）放到阻流阀那一格上，"经过"两次就拆掉了。
    blk_cell = s._blocker_cells[0] if s._blocker_cells else None
    if blk_cell is not None:
        sA, eA = mech_sim("enemy_1396_dhdts", 0, blk_cell)
        dev = next(d for d in sA._devices if d.cell == blk_cell)
        check("构造场景：田鼷力士站在阻流阀的格子上",
              abs(eA.position[0] - blk_cell[0]) < 1e-9
              and abs(eA.position[1] - blk_cell[1]) < 1e-9)
        sA._device_tick(1 / 30, 0.0)
        check("★ 进入范围立刻真伤 = 目标最大生命值 × 0.5（不是田鼷自己的 19000×0.5）",
              abs(dev.hp - 50.0) < 1e-9, f"{dev.hp:g}/{dev.max_hp:g}")
        check("装置挨打不进 `devices_lost`（还没拆掉）", not sA.result.devices_lost)
        sA._device_tick(1 / 30, 1 / 30)
        check("★ 是**进入**触发、不是站着每秒掉血（第二帧不再打）",
              abs(dev.hp - 50.0) < 1e-9, f"{dev.hp:g}")
        eA.position = (blk_cell[0] + 2.0, blk_cell[1])
        sA._device_tick(1 / 30, 2 / 30)
        eA.position = (float(blk_cell[0]), float(blk_cell[1]))
        sA._device_tick(1 / 30, 3 / 30)
        check("★ 两次经过 = 50+50 → 阻流阀被拆掉",
              not dev.alive and dev.hp == 0.0, f"hp={dev.hp:g}")
        check("★ 被拆记进 `devices_lost`（时刻、key、格子、谁拆的）",
              len(sA.result.devices_lost) == 1
              and sA.result.devices_lost[0][1] == "trap_139_dhtl"
              and sA.result.devices_lost[0][2] == blk_cell
              and sA.result.devices_lost[0][3] == eA.name,
              str(sA.result.devices_lost))
        check("★ 被拆之后地形**还回**田地（原文：重写只在『自技能结束到自身退场』期间有效）",
              sA.farmland.is_farmland(*blk_cell))
        check("拆掉的装置不再挨打、也不会再记一次",
              dev.take_damage(999.0) == 0.0 and len(sA.result.devices_lost) == 1)
    else:
        skip("AuraHit 真链路", "这一关没有阻流阀")

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


def check_pile() -> None:
    """天桩链：装置 → 天桩-甲 → 天桩-乙 → 身上的天标。

    四跳里**只有一跳**是结构化字段（甲 → 乙，走 `CheckAwake…enemy_key`），
    另外两跳只有正文，所以这一段同时把"正文里写的"与"数据里写的"逐条对齐：
    值的来源、以及写死的那两张表都与数据一致（改数据会立刻红）。
    """
    print("\n[11] 天桩链")
    import ak_tactic.battle.sim as S                                      # noqa: PLC0415
    from ak_tactic.battle.devices import PILE_KEY, parse_devices          # noqa: PLC0415
    from ak_tactic.battle.damage import DamageType                        # noqa: PLC0415
    from ak_tactic.battle.sim import BattleSimulator                      # noqa: PLC0415
    from ak_tactic.gamedata.enemy import EnemyLibrary                     # noqa: PLC0415

    class _OpStub:
        """干员桩：只带乙扑咬与天标附着要用的那几个接口。

        这一节验的是"乙怎么飞过去、天标怎么扣血"，不是干员的属性模型——
        防御给 500 是为了让"200 物理走 5% 保底 = 10"这条判据可读，
        天标那 200 则是**不走防御**的定额伤害，两者对比才是重点。
        """

        def __init__(self, pos, hp=2000.0):
            self.name = "干员桩"
            self.position = (float(pos[0]), float(pos[1]))
            self.alive = True
            self.retreated = False
            self.hp = self.max_hp = float(hp)
            self.defense = 500.0
            self.res = 20.0
            self.dodge_phys = self.dodge_arts = 0.0
            self.shield = 0.0

        def take(self, amount):
            amount = max(0.0, amount)
            self.hp = max(0.0, self.hp - amount)
            if self.hp <= 0:
                self.alive = False
            return amount

        def current_defense(self):
            return self.defense

        def current_res(self):
            return self.res

    try:
        lib = EnemyLibrary()
    except Exception as exc:                                              # noqa: BLE001
        skip("天桩链", f"敌人库不可用：{type(exc).__name__}: {exc}")
        return

    # ---------------------------------------------------- 11.1 数据对齐
    check("装置 key 与设备表一致（天桩）", PILE_KEY == "trap_146_dhdcr",
          PILE_KEY)
    # 「装置 → 甲」**不是正文跳，是结构化字段**（2026-09-16 更正）：
    # 装置 predefine 的 `overrideSkillBlackboard[branch_id]` → 关卡 `branches`
    # → `key` 是甲、`routeIndex` 指向 `extraRoutes`。`PILE_CHILD` 降级为退路。
    from ak_tactic.gamedata.stage import branch_prefix                     # noqa: PLC0415
    check("★ 装置 key → 支线前缀（`trap_146_dhdcr` → `branch_dhdcr`）",
          branch_prefix("trap_146_dhdcr") == "branch_dhdcr",
          branch_prefix("trap_146_dhdcr"))
    check("★ **没有支线语义的装置推不出前缀**（阻流阀/泵站不会被误配）",
          branch_prefix("trap_139_dhtl") == "branch_dhtl"
          and branch_prefix("trap_140_dhsb") == "branch_dhsb",
          f"{branch_prefix('trap_139_dhtl')} / {branch_prefix('trap_140_dhsb')}")
    check("★ 装置 → 甲的对照表退路与正文一致（正常路径已不用它）",
          S.PILE_CHILD == {"trap_146_dhdcr": "enemy_1398_dhdcr"},
          str(S.PILE_CHILD))
    par = lib.get("enemy_1398_dhdcr")
    check("★ 甲的黑板**自报**了它召唤谁（甲 → 乙那一跳）",
          par.awake_enemy_key == "enemy_1399_dhtb",
          f"黑板={par.awake_enemy_key}")
    check("★ 甲的黑板四个数（1% 自伤 / 10% 一批 / 阈值 100 / 红闪 70）",
          (par.awake_hp_ratio, par.awake_summon_ratio, par.awake_value,
           par.awake_value_eff, par.awake_summon_cnt)
          == (0.01, 0.1, 100.0, 70.0, 3),
          f"{par.awake_hp_ratio}/{par.awake_summon_ratio}/"
          f"{par.awake_value}/{par.awake_value_eff}/{par.awake_summon_cnt}")
    # 写死的"乙 → 天标"：乙的 talentBlackboard 是**空的**，这一跳只有正文
    # （「攻击命中时，在目标所在地块中心召唤1个[[身上的天标]]」）。
    for diver, mark in sorted(S.PILE_MARK.items()):
        d_stats = lib.get(diver)
        m_stats = lib.get(mark)
        check(f"★ {diver} → {mark}：正文那一跳的对照表对得上",
              d_stats.name.startswith("天桩-乙") or "天桩-乙" in d_stats.name,
              f"{d_stats.name} → {m_stats.name}")
        check(f"  天标的附着伤害 = 它自己的 Passive.damage_value",
              m_stats.passive_attach_damage in (200.0, 300.0),
              f"{m_stats.name} 每秒 {m_stats.passive_attach_damage:g}")
        check(f"  天标是「非首要目标」：嘲讽等级 −1（索敌排最后）",
              m_stats.taunt_level == -1.0, f"{m_stats.taunt_level:g}")
    check("★ 甲的「不可阻挡」用得上：它不是飞行单位（只能靠天赋挡不住）",
          not par.is_flying and par.apply_way == "NONE" and par.atk == 1.0,
          f"fly={par.is_flying} way={par.apply_way} atk={par.atk:g}")
    check("甲两型的召唤配置与正文一致（默认 3 个 / 失控 4 个、8% 一批）",
          (lib.get("enemy_1398_dhdcr_2").awake_summon_cnt,
           lib.get("enemy_1398_dhdcr_2").awake_summon_ratio) == (4, 0.08),
          f"{lib.get('enemy_1398_dhdcr_2').awake_summon_cnt} / "
          f"{lib.get('enemy_1398_dhdcr_2').awake_summon_ratio:g}")

    # 支线里写的是哪一型甲：**不是**全用默认型（2026-09-16 更正）——
    # act31side_ex03 / ex07 / ex08 的支线里写的是失控天桩-甲 `_2`，
    # 03/04/07/tr01/tr02 写的是关卡本地的 `enemy_1398_dhdcr_b`。
    st = stage("act31side_08")
    if st is None:
        skip("天桩链（模拟器侧）", "缺 act31side_08 缓存")
        return
    levels = ["act31side_%02d" % i for i in range(1, 10)] + \
             ["act31side_ex%02d" % i for i in range(1, 9)] + \
             ["act31side_tr%02d" % i for i in range(1, 3)]
    users, piles = [], 0
    kinds: dict[str, list[str]] = {}
    route_start_ok = route_start_bad = 0
    for lid in levels:
        stx = stage(lid)
        if stx is None:
            continue
        ds = [d for d in parse_devices(stx) if d.key == PILE_KEY]
        if not ds:
            continue
        users.append(lid)
        piles += len(ds)
        for d in ds:
            br = stx.branch_for(d.branch_id, prefix=branch_prefix(d.key))
            acts = stx.branch_actions(br)
            if not acts:
                continue
            kinds.setdefault(acts[0].enemy_key, []).append(lid)
            r = stx.extra_route(acts[0].route_index)
            if r is not None and r.start == d.cell:
                route_start_ok += 1
            else:
                route_start_bad += 1
    check("★ 本活动里带天桩的关卡都在（9 关 / 32 个装置）",
          len(users) >= 8 and piles >= 30,
          f"{len(users)} 关 {piles} 个：{'、'.join(users)}")
    check("★ 支线里的甲 key **不止一型**（默认 / 失控 / 关卡本地）",
          set(kinds) == {"enemy_1398_dhdcr", "enemy_1398_dhdcr_2",
                         "enemy_1398_dhdcr_b"},
          str({k: len(v) for k, v in kinds.items()}))
    check("★ 失控天桩-甲真的被用上了（ex03 / ex07 / ex08 三关）",
          sorted(set(kinds.get("enemy_1398_dhdcr_2") or []))
          == ["act31side_ex03", "act31side_ex07", "act31side_ex08"],
          "、".join(sorted(set(kinds.get("enemy_1398_dhdcr_2") or []))))
    check("★ 每个天桩装置格 == 它那条指派路径的起点格（32 个逐条核）",
          route_start_bad == 0 and route_start_ok == piles,
          f"{route_start_ok} 对 / {route_start_bad} 错")

    # 关卡本地的敌人定义（`useDb: false`）：甲_b / 乙_b 不在属性库里
    st3 = stage("act31side_03")
    if st3 is not None:
        loc = st3.local_enemies()
        check("★ 关卡本地的敌人定义被读出来了（03 关：甲_b + 乙_b）",
              set(loc) == {"enemy_1398_dhdcr_b", "enemy_1399_dhtb_b"},
              str(sorted(loc)))
        check("★ 本地敌人的 prefabKey 指得出库里的那一个",
              st3.local_enemy_prefab("enemy_1398_dhdcr_b") == "enemy_1398_dhdcr"
              and st3.local_enemy_prefab("enemy_1399_dhtb_b")
              == "enemy_1399_dhtb",
              st3.local_enemy_prefab("enemy_1398_dhdcr_b"))
        a_b = lib.with_overwrite("enemy_1398_dhdcr_b", loc["enemy_1398_dhdcr_b"], 0)
        check("★ 本地覆盖：数值与 prefab 同档一致（生命 5 万 / 防御 250）",
              (a_b.max_hp, a_b.defense, a_b.atk) == (par.max_hp, par.defense,
                                                     par.atk),
              f"{a_b.max_hp:g}/{a_b.defense:g}/{a_b.atk:g}")
        check("★ 本地覆盖**重算了派生字段**：03 关的甲_b 召 `…dhtb_b`",
              a_b.awake_enemy_key == "enemy_1399_dhtb_b",
              a_b.awake_enemy_key)
        st7 = stage("act31side_07")
        if st7 is not None:
            a7 = lib.with_overwrite("enemy_1398_dhdcr_b",
                                    st7.local_enemies()["enemy_1398_dhdcr_b"], 0)
            check("★ 同 id 不同关，黑板不同（07 关的甲_b 召回默认乙）",
                  a7.awake_enemy_key == "enemy_1399_dhtb",
                  a7.awake_enemy_key)
        check("★ 覆盖**不写回库**：库里的 prefab 仍是自己那一支",
              lib.get("enemy_1398_dhdcr", 0).awake_enemy_key
              == "enemy_1399_dhtb"
              and lib.get("enemy_1398_dhdcr", 0).enemy_id
              == "enemy_1398_dhdcr")
        # 整条链在"本地敌人"这条路上也要通：甲_b → 乙_b → 天标（prefab 退路）
        s3 = BattleSimulator(st3, enemy_at=lib.get)
        s3._pile_tick(1 / 30, 0.0)
        kid3 = next((e for e in s3.enemies if e.awake_value > 0), None)
        check("★ 本地敌人也能被真召唤出来（模拟器走 prefab 覆盖取数）",
              kid3 is not None and kid3.enemy_id == "enemy_1398_dhdcr_b"
              and kid3.max_hp == 50000.0,
              f"{getattr(kid3, 'enemy_id', None)} hp="
              f"{getattr(kid3, 'max_hp', 0):g}")
        if kid3 is not None:
            check("  本地甲的召唤目标也来自**本关自己的黑板**",
                  kid3.awake_enemy_key == "enemy_1399_dhtb_b",
                  kid3.awake_enemy_key)
            diver3 = s3._build_enemy("enemy_1399_dhtb_b", 0, [(0.0, 0.0)],
                                     [], 0.0, 0.0)
            check("★ 本地乙（`…dhtb_b`）→ 天标：走 prefabKey 退路查表",
                  s3._pile_mark_key(diver3) == "enemy_1400_dhtbgj",
                  s3._pile_mark_key(diver3))

    # ---------------------------------------------------- 11.2 模拟器：甲
    s = BattleSimulator(st, enemy_at=lib.get)
    check("装置不改写地块：天桩脚下的格子**仍是田地**（与阻流阀相反）",
          s.farmland is not None and s.farmland.is_farmland(10, 3))
    s._pile_tick(1 / 30, 0.0)
    kids = [e for e in s.enemies if e.awake_value > 0]
    check("★ 每个天桩装置召唤出 1 个甲，位置就在装置那一格",
          len(kids) == len([d for d in s._devices if d.key == PILE_KEY])
          and all(k.cell() == d.cell for k, d in zip(
              sorted(kids, key=lambda e: e.cell()),
              sorted([d for d in s._devices if d.key == PILE_KEY],
                     key=lambda d: d.cell))),
          f"{len(kids)} 个")
    p = kids[0]
    check("★ 甲**站着不动**：它的天赋第一句是「自缚」，路径是关卡指派给它的"
          "（起点=装置格），不是行进计划",
          len(p.route) == 1 and p.route_length == 0.0 and p.progress == 0.0,
          f"route={p.route} 长度={p.route_length:g}")
    p.advance(30.0, s.speed_scale)
    check("  推 30 秒也不动、也不会被判成漏怪（单点路线长度为 0）",
          p.position == (float(p.cell()[0]), float(p.cell()[1]))
          and not p.reached_end and not p.leaked, str(p.position))
    check("★ 甲开场是**监测状态**：无敌 + 不死，且从第 0 帧起就不可阻挡",
          p.monitor and p.always_invincible and p.unblockable)
    check("★ 监测状态重设生命百分比 = 所在地块病害值（这里是 0 → 压到 1 点，"
          "**不会因此死亡**）", p.hp == 1.0 and p.monitor,
          f"hp={p.hp:g} 病害值={s.farmland.actual_at(*p.cell()):g}")
    before = s.result.damage_dealt
    s._damage_enemy(p, 1e9, 0.0, DamageType.PHYSICAL)
    check("★ 监测状态无敌：打它一下伤害为 0、也不算进「我方总伤害」",
          p.hp == 1.0 and s.result.damage_dealt == before)

    # 灌满它所在的那片田地 → 病害值到 100 → 激活
    fld = s.farmland.field_at(*p.cell())
    fld.cache = 100.0 * len(fld.cells)
    for _ in range(200):
        s.farmland.tick(0.2)
    check("构造场景：那一片田地的实际病害值到了 100（= CheckAwake.value）",
          s.farmland.actual_at(*p.cell()) >= 100.0,
          f"{s.farmland.actual_at(*p.cell()):g}")
    s._pile_tick(1 / 30, 1.0)
    check("★ 病害值首次 ≥100 → 切**激活状态**，同时解除无敌",
          (not p.monitor) and (not p.always_invincible))
    check("激活那一刻生命百分比 = 100%（50000）", p.hp == p.max_hp,
          f"{p.hp:g}/{p.max_hp:g}")
    s._pile_tick(1.0, 2.0)
    check("★ 激活后每秒受 1% 最大生命的**真实伤害**（不经 `_damage_enemy`）",
          abs(p.hp - (p.max_hp - p.max_hp * 0.01)) < 1e-6,
          f"{p.hp:g}")
    check("  自伤不记进「我方总伤害」（它不是我打的）",
          s.result.damage_dealt == before)

    # 每损失 10% → 1.25s 后 3 个乙
    t = 2.0
    scheduled = None
    while t < 20.0 and scheduled is None:
        t += 1.0
        s._pile_tick(1.0, t)
        if p.awake_pending:
            scheduled = (t, p.awake_pending[0], p.awake_batches)
    check("★ 损失满 10% 的**那一刻**排下一批（10 秒 1%，第 10 秒到 10%）",
          scheduled is not None and scheduled[2] == 1,
          f"第 {scheduled[2] if scheduled else '?'} 批、"
          f"t={scheduled[0] if scheduled else '?'}")
    check("★ 排定的到点时刻 = 当时 + 1.25s（原文 1~1.5s 随机取中值）",
          scheduled is not None
          and abs(scheduled[1] - (scheduled[0] + S.PILE_SUMMON_DELAY)) < 1e-9,
          f"{scheduled[1]:g} = {scheduled[0]:g} + {S.PILE_SUMMON_DELAY:g}")
    check("  还没到点时**一个乙都不该冒出来**",
          not [e for e in s.enemies if e.enemy_id in S.PILE_MARK])
    landed_at = None
    while t < (scheduled[1] if scheduled else 0.0) + 0.5:
        t += 1 / 30
        s._pile_tick(1 / 30, t)
        if landed_at is None and any(
                e.enemy_id in S.PILE_MARK and e.cell() == p.cell()
                for e in s.enemies):
            landed_at = t
    # ⚠ 这一关的 10 个天桩**都在同一片田里**，所以 10 个甲一起激活、一起召唤：
    #   判据必须按"这一个甲脚下那一格"筛，不然数出来的是 10×3。
    new = [e for e in s.enemies
           if e.enemy_id in S.PILE_MARK and e.cell() == p.cell()]
    check("★ 到点后一次落地 3 个乙（一批 = cnt）", len(new) == 3,
          f"{len(new)} 个（全场 {sum(1 for e in s.enemies if e.enemy_id in S.PILE_MARK)} 个）")
    check("★ 落地时刻与排定时刻差不到一帧",
          landed_at is not None and abs(landed_at - scheduled[1]) < 1.5 / 30,
          f"t={landed_at:.2f} vs 排定 {scheduled[1]:.2f}")
    check("  召唤延迟取中值 1.25s（原文 1~1.5s 随机，模拟器不掷骰）",
          S.PILE_SUMMON_DELAY == 1.25)
    check("★ 「1.0 边长正方形范围内随机位置」= 脚下那一格（不掷骰）",
          all(e.cell() == p.cell() for e in new),
          f"{len(new)} 个都落在这里 {p.cell()}")
    check("★ 别的甲也在**自己脚下**召唤（不是一个甲替全场放怪）",
          all(e.cell() == next(k.cell() for k in kids if k.cell() == e.cell())
              for e in s.enemies if e.enemy_id in S.PILE_MARK))
    check("★ 乙登场时持有 1 秒自缚（待机：不能移动也不能出手）",
          all(e.idle_timer == S.PILE_SELF_BIND for e in new))
    check("乙是飞行单位（地表干员挡不住它）", all(e.is_flying for e in new))

    # 跑到甲自己把自己耗死 → 装置随它死亡
    while p.hp > 0 and t < 200.0:
        t += 1.0
        s._pile_tick(1.0, t)
    check("★ 激活后 100 秒耗完（每秒 1%），甲自己倒下", p.hp == 0.0,
          f"t={t:g}")
    dev = next(d for d in s._devices if d.key == PILE_KEY and d.cell == p.cell())
    check("★ 甲退场 → 所在地块的天桩**自动死亡**", not dev.alive)
    check("★ 这条死亡记进 `devices_lost`（装置 key、格子、由谁带来）",
          any(r[1] == PILE_KEY and r[2] == p.cell() for r in s.result.devices_lost),
          str(s.result.devices_lost[:1]))
    check("  天桩死亡**不还田地**（它本来就没改写地块）",
          s.farmland.is_farmland(*p.cell()))

    # ---------------------------------------------------- 11.3 乙 → 天标
    op = _OpStub(p.cell())
    s2 = BattleSimulator(st, enemy_at=lib.get)
    s2.farmland.field_at(*p.cell()).cache = 0.0
    fld2 = s2.farmland.field_at(10, 3)
    fld2.cache = 100.0 * len(fld2.cells)
    for _ in range(200):
        s2.farmland.tick(0.2)
    s2._pile_tick(1 / 30, 0.0)
    op.position = (9.0, 5.0)
    s2.operators.append(op)
    t = 0.0
    diver = None
    while t < 20.0 and diver is None:
        t += 1 / 30
        s2._pile_tick(1 / 30, t)
        diver = next((e for e in s2.enemies
                      if e.enemy_id in S.PILE_MARK and e.hp > 0), None)
    if diver is None:
        skip("乙 → 天标", "没能召唤出乙")
        return
    for e in s2.enemies:
        if e.idle_timer > 0:
            e.idle_timer = max(0.0, e.idle_timer - 1 / 30)
    hp0 = op.hp
    for _i in range(3000):
        t += 1 / 30
        if diver.idle_timer > 0:
            diver.idle_timer = max(0.0, diver.idle_timer - 1 / 30)
        diver.advance(1 / 30, s2.speed_scale)
        s2._pile_tick(1 / 30, t)
        if diver.attacked_once:
            break
    check("★ 乙扑到干员身上咬一口（200 物理，吃防御、走 5% 保底）",
          diver.attacked_once and hp0 - op.hp > 0,
          f"干员 {hp0:g} → {op.hp:g}（防御 500 → 保底 10）")
    check("  咬中时落点就是目标那一格（地块中心）",
          abs(diver.position[0] - 9.0) < 1e-9
          and abs(diver.position[1] - 5.0) < 1e-9, str(diver.position))
    check("★ 攻击结束（动作时间到）后强制击杀自身",
          diver.self_destruct_at > 0)
    marks = [e for e in s2.enemies if e.attach_damage > 0]
    check("★ 命中即在目标所在地块中心召唤 1 个天标", len(marks) == 1,
          f"{len(marks)} 个")
    m = marks[0]
    check("★ 附着对象 = **登场时**半径 0.3 内的我方单位（快照，就这一格的人）",
          m.attached == [op] and abs(m.position[0] - 9.0) < 1e-9,
          f"附着 {len(m.attached)} 人")
    check("  附着伤害 = `Passive.damage_value`（200），不是 `extra_value`",
          m.attach_damage == 200.0, f"{m.attach_damage:g}")
    hp1 = op.hp
    s2._pile_mark_tick(m, 1.0, t + 1)
    check("★ 每秒 200 的**预计算无途径**伤害：定额扣血，不吃防御/法抗",
          abs((hp1 - op.hp) - 200.0) < 1e-9, f"{hp1:g} → {op.hp:g}")
    op.alive = False
    s2._pile_mark_tick(m, 1 / 30, t + 2)
    check("★ 任一附着对象的效果结束 → 天标强制击杀自身", m.hp == 0.0)
    # 索敌：天标嘲讽 −1，干员优先打别人
    check("★ 嘲讽 −1 真的在索敌里生效（同一格时正常敌人优先）",
          sorted([m, diver], key=lambda e: (-e.taunt_level, -e.progress))[0]
          is diver)


def check_device_deploy() -> None:
    """玩家**手动部署装置**这一层（`DeathPassive.` 的落点）。

    「被击倒时予我方可部署装置」在此前只进账不花：额度算出来了，却没有"部署
    装置"这条路，等于没接。这一节验的就是那条路：额度（关卡 `tokenCards`
    给的 + 击杀掉落的）→ 费用（角色表 `cost`，阻流阀 5）→ 落点 → **3 秒建成
    那一刻**才改写地块。
    """
    print("\n[12] 装置部署层（额度 / 费用 / 建成即断田）")
    from ak_tactic.battle.devices import (BLOCKER_KEY, BUILD_SECONDS,
                                          DeviceDeployment, device_cost,
                                          initial_device_tokens)
    from ak_tactic.battle.sim import BattleSimulator
    from ak_tactic.gamedata.enemy import EnemyLibrary

    check("★ 部署费用与角色表一致（阻流阀 5 费 / 泵站与天桩 0 费）",
          (device_cost(BLOCKER_KEY), device_cost("trap_140_dhsb"),
           device_cost("trap_146_dhdcr")) == (5, 0, 0),
          f"{device_cost(BLOCKER_KEY)}/{device_cost('trap_140_dhsb')}/"
          f"{device_cost('trap_146_dhdcr')}")
    check("  表里没有的装置不猜费用（给 0，不收也不乱收）",
          device_cost("trap_999_nope") == 0)

    st = stage("act31side_03")
    if st is None:
        skip("装置部署层", "缺 act31side_03 缓存")
        return
    check("★ 关卡给的装置额度取自 `tokenCards[].initialCnt`",
          initial_device_tokens(st) == {BLOCKER_KEY: 2},
          str(initial_device_tokens(st)))

    try:
        lib = EnemyLibrary()
    except Exception as exc:                                              # noqa: BLE001
        skip("装置部署层", f"敌人库不可用：{type(exc).__name__}: {exc}")
        return
    sim = BattleSimulator(st, enemy_at=lib.get, verbose=False)
    sim.cost_mode = "strict"
    sim.cost = 100.0
    check("★ 构造时就带着关卡给的额度", sim.device_token_balance == {BLOCKER_KEY: 2},
          str(sim.device_token_balance))
    free = [c for f in sim.farmland.fields for c in f.cells
            if not any(d.alive and d.cell == c for d in sim._devices)]
    check("  找到一格空地（不是预置装置那一格）", bool(free), f"{len(free)} 格可放")
    cell = free[0]
    sim.plan_device(DeviceDeployment(time=1.0, device_key=BLOCKER_KEY,
                                     position=cell, direction="RIGHT"))
    sim._do_deploy_device(sim.device_deployments[0], 1.0)
    check("★ 放下去：扣 5 费、额度 −1、记进 `devices_deployed`",
          sim.cost == 95.0 and sim.device_token_balance[BLOCKER_KEY] == 1
          and sim.result.devices_deployed == [(1.0, BLOCKER_KEY, cell)],
          f"费 {sim.cost:g} 余 {sim.device_token_balance[BLOCKER_KEY]}")
    new_dev = [d for d in sim._devices if d.cell == cell][0]
    check("★ 落下去**还没断田**（那 3 秒里它仍算田地）",
          sim.farmland.is_farmland(*cell) and not new_dev.built
          and new_dev.building_invincible,
          f"建成倒计时 {new_dev.build_left:g}s，无敌={new_dev.building_invincible}")
    check("  建成期间生命值只有最大值的 3.4%（原文）",
          abs(new_dev.hp - new_dev.max_hp * 0.034) < 1e-9,
          f"{new_dev.hp:g}/{new_dev.max_hp:g}")
    for _ in range(int(BUILD_SECONDS * 30) + 1):
        sim._device_tick(1 / 30, 1.0)
    check("★ **建成那一刻**才改写地块：那一格不再是田地",
          new_dev.built and not sim.farmland.is_farmland(*cell)
          and cell in sim._blocker_cells,
          f"建成={new_dev.built} 片数={len(sim.farmland.fields)}")

    # ---- 三类拒收都要留痕
    before = len(sim.result.device_deploy_rejected)
    sim._do_deploy_device(DeviceDeployment(time=2.0, device_key=BLOCKER_KEY,
                                           position=cell), 2.0)
    check("★ 同一格放第二个 → 拒收并写明理由",
          len(sim.result.device_deploy_rejected) == before + 1
          and "已经有装置" in sim.result.device_deploy_rejected[-1][2],
          sim.result.device_deploy_rejected[-1][2])
    other = [c for c in free if c != cell]
    sim._do_deploy_device(DeviceDeployment(time=2.0, device_key=BLOCKER_KEY,
                                           position=other[0]), 2.0)
    check("★ 第二次放得下去（额度 1 → 0）",
          sim.device_token_balance[BLOCKER_KEY] == 0
          and len(sim.result.devices_deployed) == 2,
          str(sim.device_token_balance))
    sim._do_deploy_device(DeviceDeployment(time=3.0, device_key=BLOCKER_KEY,
                                           position=other[1]), 3.0)
    check("★ 额度用完 → 拒收（不是白送一个）",
          "额度" in sim.result.device_deploy_rejected[-1][2]
          and len(sim.result.devices_deployed) == 2,
          sim.result.device_deploy_rejected[-1][2])
    sim.device_token_balance[BLOCKER_KEY] = 2      # 假设又打死了几只飞贼
    sim.cost = 0.0
    sim._do_deploy_device(DeviceDeployment(time=4.0, device_key=BLOCKER_KEY,
                                           position=other[1]), 4.0)
    check("★ 有额度但费不够 → 同样拒收（与干员部署同一道闸门）",
          "费用不足" in sim.result.device_deploy_rejected[-1][2]
          and sim.result.cost_denied, sim.result.device_deploy_rejected[-1][2])

    # ---- `DeathPassive.` 掉落的额度真的进账
    sim2 = BattleSimulator(st, enemy_at=lib.get)
    class _Thief:
        name, death_token, death_cnt = "田鼷飞贼", BLOCKER_KEY, 2
        passive_pollut, passive_radius = 0.0, 1.0
    sim2._on_enemy_death(_Thief(), 5.0)         # type: ignore[arg-type]
    check("★ 击杀掉落**进额度**（关卡给的 2 + 掉的 2 = 4）",
          sim2.device_token_balance[BLOCKER_KEY] == 4
          and sim2.result.device_tokens == [(5.0, BLOCKER_KEY, 2)],
          str(sim2.device_token_balance))


class _ProbeOp:
    """干员桩（模块级）：只带"技能攻击打上去"要用的那几个接口。

    不是干员属性模型——防御/法抗给 0 是为了让"物理 100% + 法术 104%"
    这两段在数值上可读，`block_cnt` 则用来验「部署于地面」那一条。
    """

    def __init__(self, pos, name="干员桩", hp=5000.0, block=2):
        self.name = name
        self.position = (float(pos[0]), float(pos[1]))
        self.alive = True
        self.retreated = False
        self.hp = self.max_hp = float(hp)
        self.defense = 0.0
        self.res = 0.0
        self.dodge_phys = self.dodge_arts = 0.0
        self.shield = 0.0
        self.block_cnt = block
        self.skill = None
        self.skill_active = False
        self.sp = 0.0

    def take(self, amount):
        amount = max(0.0, amount)
        self.hp = max(0.0, self.hp - amount)
        if self.hp <= 0:
            self.alive = False
        return amount

    def current_defense(self):
        return self.defense

    def current_res(self):
        return self.res


def check_skill_attack() -> None:
    """敌方**技能出手**：怀黍离「玷 / 勿玷」的技能「污」。

    这一节同时钉两件事：① 技能黑板那两个数是**结构化**的、并且 rune
    `enemy_skill_blackb_mul` 真的改到了派生字段；② 正文那五件事（1 名 /
    地面 / 十字 / 100% / 不做普攻）确实写死在 `PROSE_SKILL_ATTACK` 里。
    """
    print("\n[13] 敌方技能出手（玷 / 勿玷 的技能「污」）")
    import inspect
    from ak_tactic.battle.damage import DamageType
    from ak_tactic.battle.sim import BattleSimulator
    from ak_tactic.battle.stage_mul import parse_rune_muls, wrap_enemy_at
    from ak_tactic.gamedata.enemy import (EnemyLibrary, PROSE_SKILL_ATTACK,
                                          skill_attack_fields)

    spec = PROSE_SKILL_ATTACK.get("Drink")
    check("★ 正文规格写死在表里（技能 `Drink` → 1 名 / 十字 / 地面 / 100%）",
          spec is not None and spec["targets"] == 1 and spec["cross"] == 1
          and spec["ground_only"] and spec["scale_phys"] == 1.0,
          str(spec))
    # 正文那五件事必须在**代码注释**里留下原文，免得日后被人"顺手"改数
    src = inspect.getsource(skill_attack_fields)
    flat = src.replace(" ", "").replace("\n", "")
    check("★ 那五件事的出处（prts 图鉴原文）就写在派生函数的文档里",
          all(t in flat for t in ("不进行远程普通攻击", "周围4格",
                                  "攻击力100%的物理伤害", "病害值+5")),
          f"文档 {len(src)} 字符")

    try:
        lib = EnemyLibrary()
    except Exception as exc:                                              # noqa: BLE001
        skip("敌方技能出手", f"敌人库不可用：{type(exc).__name__}: {exc}")
        return
    e0 = lib.get("enemy_1393_dhele_2", 0)
    check("★ 技能攻击的字段由**技能黑板**派生（0.8 / +5 / 首手 7 / 不做普攻）",
          (e0.skill_atk_key, e0.skill_atk_scale_magic, e0.skill_atk_pollut,
           e0.skill_atk_init, e0.skill_atk_no_normal)
          == ("Drink", 0.8, 5.0, 7.0, True),
          f"{e0.skill_atk_key} magic={e0.skill_atk_scale_magic} "
          f"pollut={e0.skill_atk_pollut}")
    check("  另一型玷（`enemy_1393_dhele`）同规格（两型共用技能 `Drink`）",
          lib.get("enemy_1393_dhele", 0).skill_atk_scale_magic == 0.8)
    check("  没有这个技能的敌人**全是 0/False**（不会误伤别的敌人）",
          lib.get("enemy_1390_dhsbr", 0).skill_atk_key == ""
          and lib.get("enemy_1390_dhsbr", 0).skill_atk_scale_magic == 0.0)

    st = stage("act31side_ex04")
    if st is None:
        skip("敌方技能出手（模拟器侧）", "缺 act31side_ex04 缓存")
        return
    muls = parse_rune_muls(st.raw.get("runes"), "FOUR_STAR")
    at4 = wrap_enemy_at(lib.get, muls)
    check("★ rune `enemy_skill_blackb_mul` 真的改到了**派生字段**（0.8 → 1.04）",
          abs(at4("enemy_1393_dhele_2", 0).skill_atk_scale_magic - 1.04) < 1e-9,
          f"{at4('enemy_1393_dhele_2', 0).skill_atk_scale_magic}")
    check("  乘数**不写回库**（别的关卡还是 0.8）",
          lib.get("enemy_1393_dhele_2", 0).skill_atk_scale_magic == 0.8)

    # ---------------- 模拟器侧：打谁、打几格、附加法术、污染
    sim = BattleSimulator(st, enemy_at=at4, verbose=False)
    if sim.farmland is None:
        skip("敌方技能出手（模拟器侧）", "ex04 没开田地系统")
        return
    fld = sim.farmland.fields[0]
    cell = sorted(fld.cells)[0]
    ops = {}
    for name, pos, block in (("远处近战", (cell[0] + 6, cell[1]), 2),
                             ("十字高台", (cell[0] + 1, cell[1]), 0),
                             ("目标近战", cell, 2)):
        op = _ProbeOp(pos, name, block=block)
        ops[name] = op
        sim.operators.append(op)          # 顺序 = 部署顺序，最后那个才是目标
    e = sim._build_enemy("enemy_1393_dhele_2", 0,
                         [(float(cell[0]), float(cell[1]))], [], 0.0, 0.0)
    sim.enemies.append(e)
    check("★ 技能攻击的数值进了 `EnemyUnit`（物理 100% / 法术 1.04 / +5）",
          (e.skill_atk_scale_phys, e.skill_atk_scale_magic, e.skill_atk_pollut)
          == (1.0, 1.04, 5.0),
          f"{e.skill_atk_scale_phys}/{e.skill_atk_scale_magic}/{e.skill_atk_pollut}")
    far = ops["远处近战"]
    check("★ 挑目标是**全图**（射程 −1 也照打）且只要**地面**单位（`block_cnt>0`）",
          sim._skill_atk_target(e) is ops["目标近战"],
          f"选中 {sim._skill_atk_target(e).name}")
    ops["目标近战"].block_cnt = 0
    check("  地面限定真的生效：唯一的地面单位变成高台后就不打了",
          sim._skill_atk_target(e) is ops["远处近战"]
          or sim._skill_atk_target(e) is None,
          str(getattr(sim._skill_atk_target(e), "name", None)))
    ops["目标近战"].block_cnt = 2

    # ① 自身**不在**受污染田地上：只有物理那一段，也不污染
    t = 0.0
    hp0 = ops["目标近战"].hp
    while t < 7.5 and ops["目标近战"].hp == hp0:
        t += 1 / 30
        sim._skill_attack_tick(1 / 30, t)
    dmg = hp0 - ops["目标近战"].hp
    check("★ 首手在 `initCooldown`(7s) 到点时出手；这一下是**攻击力 100% 物理**",
          abs(dmg - e.atk) < 1e-6 and abs(t - 7.0) < 0.1,
          f"t={t:.2f} 伤害 {dmg:g}（攻击力 {e.atk:g}）")
    check("★ 十字：目标**及其四邻**都吃这一下",
          abs((hp0 - ops["十字高台"].hp) - dmg) < 1e-6, "四邻同样掉血")
    check("★ 远处（不在十字里）的单位**不掉血**",
          far.hp == far.max_hp, f"{far.hp:g}")
    check("  自身不在受污染的田地上 → **没有**附加法术、也不污染目标地块",
          sim.farmland.field_at(*cell).cache == 0.0,
          f"缓存 {sim.farmland.field_at(*cell).cache:g}")

    # ② 把它挪到受污染的田地上：附加法术 + 目标地块 +5（记入缓存）
    other = None
    for f in sim.farmland.fields:
        for c in sorted(f.cells):
            if c != cell:
                other = c
                break
        if other:
            break
    if other is None:
        skip("敌方技能出手（② 附加法术）", "找不到第二片田地")
        return
    f2 = sim.farmland.field_at(*other)
    f2.cache = 100.0 * len(f2.cells)
    for _ in range(200):
        sim.farmland.tick(0.2)
    e.route = [(float(other[0]), float(other[1]))]
    e.position = (float(other[0]), float(other[1]))
    ops["目标近战"].position = (float(other[0]), float(other[1]))
    ops["十字高台"].position = (float(other[0]), float(other[1] + 1))
    check("构造场景：它脚下那格的病害值 > 0",
          sim.farmland.actual_at(*other) > 0.0,
          f"{sim.farmland.actual_at(*other):g}")
    cache0 = sim.farmland.field_at(*other).cache
    # 目标给 30 法抗：两段**分开减抗**的话，法术那段要乘 (1−0.3)；
    # 把两段加起来当一次物理打则不会。这是这两行代码唯一的可判区别。
    ops["目标近战"].res = 30.0
    ops["十字高台"].res = 30.0
    hp1 = ops["目标近战"].hp
    t = 7.0
    while t < 14.5 and ops["目标近战"].hp == hp1:
        t += 1 / 30
        sim._skill_attack_tick(1 / 30, t)
    dmg2 = hp1 - ops["目标近战"].hp
    phys = e.atk                       # 物理那段：攻击力 100%，目标防御 0
    mag = e.atk * 1.04 * (1 - 0.30)    # 法术那段：攻击力 104% 再减 30 法抗
    check("★ 站在受污染田地上 → **额外附加**攻击力 ×`atk_scale_magic` 的法术伤害",
          abs(dmg2 - (phys + mag)) < 1e-6,
          f"实得 {dmg2:g} = 物理 {phys:g} + 法术 {mag:.0f}")
    check("★ 两段**分开减抗**（不是加起来打一次）：法术那段按 30 法抗折算",
          abs(dmg2 - (phys + e.atk * 1.04)) > 1.0,
          f"合并打一次会得 {phys + e.atk * 1.04:.0f}，实得 {dmg2:g}")
    check("★ 令**目标地块**病害值 +5（记入【缓存】，不是当场改实际）",
          abs(sim.farmland.field_at(*other).cache - (cache0 + 5.0)) < 1e-9,
          f"缓存 {cache0:g} → {sim.farmland.field_at(*other).cache:g}")
    check("  第二次出手与第一次相隔 `attack_interval`（7s）",
          abs(t - 14.0) < 0.1, f"t={t:.2f}")
    check("  普攻那一路**关掉了**（天赋「不进行远程普通攻击」）",
          e.skill_atk_no_normal and sim._enemy_target(e) is None,
          f"no_normal={e.skill_atk_no_normal}")
    check("★ 伤害类型用的是 `DamageType.MAGIC`（写 `ARTS` 会直接抛异常）",
          DamageType.MAGIC == "MAGIC")


def check_settlement_props() -> None:
    """[14] 结算判据：**「既打不死又不会离场」的单位不能挡住"打完了"**。

    博士 2026-09-18 报的「TUI 解算无论选什么都是 0 条结果，似乎没接上模拟器」
    根因之一就在这里：主循环原先的完成判据是"场上还有活着的敌人就不算打完"，
    而天桩-甲是「自缚 + 监测状态无敌不死」——它既不会被打死，也不会走到目标点，
    于是**凡是有天桩的关卡永远跑满时间上限**，判定成"失败 0 星"。搜索于是永远
    搜不到三星方案，用户看到的就是"0 条结果"。

    这一节钉三件事：真数据里它在场时这一局**照样能结束**；判据是**窄**的
    （普通敌人还活着时该跑满就跑满，不能顺手把结算放宽）；以及归因措辞
    （跑满上限 ≠ 生命归零）。
    """
    print("\n[14] 结算判据（清不掉的单位不挡结算）")
    from ak_tactic.battle.sim import BattleSimulator                      # noqa: PLC0415
    from ak_tactic.gamedata.enemy import EnemyLibrary                     # noqa: PLC0415
    from ak_tactic.gamedata.stage import load_stage                       # noqa: PLC0415

    try:
        lib = EnemyLibrary()
        st = load_stage("act31side_03")
    except Exception as exc:                                              # noqa: BLE001
        skip("结算判据", f"数据不可用：{type(exc).__name__}: {exc}")
        return

    def fresh():
        s = BattleSimulator(st, enemy_at=lib.get)
        s._pile_tick(1 / 30, 0.0)          # 装置召唤出真甲（1 个天桩）
        s._spawns[:] = []                  # 出怪表当作已经放完
        return s

    s = fresh()
    jia = [e for e in s.enemies if e.owner_device is not None]
    check("构造场景：真甲已在场（装置召唤）且**只**剩它一个",
          len(jia) == 1 and jia[0].awake_value > 0.0
          and jia[0].owner_device is not None,
          f"{len(jia)} 个")
    check("★ 它同时满足「打不死」与「不会离场」两个条件",
          BattleSimulator._cannot_clear(jia[0])
          and jia[0].always_invincible and jia[0].route_length == 0.0,
          f"无敌={jia[0].always_invincible} 路线长={jia[0].route_length:g}")
    r = s.run()
    check("★ 只剩它时这一局**当场结束**（不是跑满上限）",
          r.won and not r.timed_out, f"won={r.won} timed_out={r.timed_out} "
          f"elapsed={r.elapsed:.1f}")
    check("  甲确实还站在场上（无敌不死，它不会自己走）",
          any(e.owner_device is not None and e.alive for e in s.enemies))
    check("  它也没被算成击杀/漏怪（两本账都不认它）",
          r.kills == 0 and r.leaks == 0, f"杀 {r.kills} 漏 {r.leaks}")

    # 反向对照：把「打不死」这一条摘掉，同一条判据必须**仍然拒绝收场**。
    # 没有这一条，"排除清不掉的单位"就变成了"顺手把结算放宽"也无从发现。
    s2 = fresh()
    for e in s2.enemies:
        e.always_invincible = False
    r2 = s2.run()
    check("★ 反向对照：同一个甲**摘掉无敌之后**这一局就收不了场",
          (not r2.won) and r2.timed_out,
          f"won={r2.won} timed_out={r2.timed_out} elapsed={r2.elapsed:.1f}")
    # 反向对照之二：会走的不算。`route_length` 是只读属性（真实单位的路线在
    # 构造时就定了），所以这一条拿一个最小对象来问同一个判据。
    from types import SimpleNamespace                                     # noqa: PLC0415
    walker = SimpleNamespace(always_invincible=True, route_length=3.0)
    mortal = SimpleNamespace(always_invincible=False, route_length=0.0)
    check("★ 反向对照之二：能走的无敌单位**不算**清不掉（它走掉了这一局就完了）",
          not BattleSimulator._cannot_clear(walker)
          and not BattleSimulator._cannot_clear(mortal)
          and BattleSimulator._cannot_clear(
              SimpleNamespace(always_invincible=True, route_length=0.0)),
          f"会走={BattleSimulator._cannot_clear(walker)} "
          f"会死={BattleSimulator._cannot_clear(mortal)}")

    # 归因口径：跑满上限 ≠ 生命归零。原先两者共用一句话，会写出
    # 「失败：生命归零（初始 3 点，共漏 0 只、扣了 0 点）」这种自相矛盾的话。
    from ak_tactic.verify import Verdict, Verifier                        # noqa: PLC0415

    vf = Verifier(verbose=False)
    fake = Verdict(0, False, 3, 3, 0, 0, r2.elapsed, 0.0, title="跑满上限的局")
    said = " ".join(vf._diagnose(fake, s2, r2, 3))
    check("★ 跑满上限的归因说的是「跑满时间上限」而不是「生命归零」",
          "跑满时间上限" in said and "生命归零" not in said, said)
    check("  并且点名留下的是什么（天桩-甲）", "天桩-甲" in said, said)

    # 真·生命归零那一支照旧：把 timed_out 摘掉，说的必须还是「生命归零」
    r2.timed_out = False
    said2 = " ".join(vf._diagnose(fake, s2, r2, 3))
    check("  生命真的归零时，归因仍说「生命归零」",
          "生命归零" in said2, said2)

    # ---------------------------------------------------- 14.2 端到端那一局
    #
    # 上面两条是**构造场景**（把出怪表清空，只留一个甲）。这里补上真跑一场：
    # 同一关、同一套落位，修好前是"跑满上限、0 星"，修好后应当 **247.7s 三星**。
    # 这条就是博士报的「TUI 算不出结果」的回归坐标——搜索层一个字没改，
    # 改的只是主循环的完成判据。
    #
    # **不读本机名册**：练度写成内联表（只写"这个人精二 90 潜 1 模组 3"，
    # 不含任何账号数据），`Verifier` 走的仍是与 CLI/TUI 相同的取数路径
    # （天赋、模组、真实攻击范围表），所以强度没有打折。
    from ak_tactic.plan import DeployOrder, Plan, Roster                  # noqa: PLC0415
    from ak_tactic.verify import Verifier                                 # noqa: PLC0415

    roster = Roster({"圣聆初雪": {"char_id": "char_1046_sbell2", "elite": 2,
                                 "level": 90, "potential": 1,
                                 "module": "uniequip_002_sbell2",
                                 "module_level": 3}})
    plan = Plan(stage="act31side_03", deploys=[
        DeployOrder("圣聆初雪", (3, 1), "Right", skill=0, mastery=0, elite=2,
                    level=90, potential=1, module="uniequip_002_sbell2",
                    module_level=3, auto_skill=True)], title="1 人")
    got = Verifier(verbose=False).run(plan, roster=roster)
    check("★ HS-3 端到端收得了场（修好前这里跑满上限、0 星）",
          bool(got.won) and got.stars == 3, got.line())
    check("  耗时 247.7s、击杀 38、漏怪 0（回归坐标）",
          abs(got.elapsed - 247.67) < 0.1 and got.kills == 38 and got.leaks == 0,
          f"{got.elapsed:.2f}s 杀 {got.kills} 漏 {got.leaks}")
    check("  归因说的是三星，而不是「跑满上限」",
          "三星" in " ".join(got.diagnosis), " ".join(got.diagnosis))


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
    check_pile()
    check_device_deploy()
    check_skill_attack()
    check_settlement_props()
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
