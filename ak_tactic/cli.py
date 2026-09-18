"""命令行入口：`python -m ak_tactic <命令>`。

    get     取一个干员的结构化数据（prts.wiki）
    list    列干员名录（Cargo 全表 / SMW 按职业稀有度筛）
    range   看攻击范围网格
    stage   取一个关卡：地图网格、出怪路线、波次时间轴（gamedata）
    enemy   取敌人的图鉴与数值（gamedata）
    stats   算干员属性：等级 + 信赖 + 潜能 + 模组
    skills  看干员技能：倍率、技力回转、持续、范围
    talents 看干员天赋
    formula 正文 → 公式项：干员侧入口（敌人侧用 enemydb formula）
    db      干员库（gamedata）：建库与查询
    enemydb 敌人库（prts.wiki）：建库与查询（另一个文件，与干员库分开）
    cache   缓存管理
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .gamedata import (
    EnemyLibrary,
    GameDataSource,
    GamedataError,
    load_stage,
)
from .prts import (
    PrtsClient,
    PrtsError,
    RangeRegistry,
    all_operator_names,
    default_client,
    fetch_operator,
    parse_svg,
)
from .prts.grid import merge_ranges
from .prts.wikitext import render as render_wiki
from .operator import (
    OperatorCalculator,
    OperatorError,
    SkillBook,
    TalentBook,
    parse_rarity,
    render_description,
)
from .db import (
    DB_SCHEMA_DOC,
    DEFAULT_DB_PATH,
    ENEMY_DB_SCHEMA_DOC,
    DatabaseMissing,
    build_db,
    build_enemy_db,
    char_detail,
    connect,
    connect_enemy,
    db_info,
    enemy_db_info,
    enemy_detail,
    enemy_sql,
    find_enemies,
    find_operators,
    run_sql,
    search_skills,
    search_talents,
    skill_levels,
)

#: character_table 的职业是英文枚举，面板上看的是中文
PROFESSION_CN = {
    "PIONEER": "先锋", "WARRIOR": "近卫", "TANK": "重装", "SNIPER": "狙击",
    "CASTER": "术师", "MEDIC": "医疗", "SUPPORT": "辅助", "SPECIAL": "特种",
    "TOKEN": "召唤物", "TRAP": "装置",
}


def _client(args: argparse.Namespace) -> PrtsClient:
    return PrtsClient(use_cache=not getattr(args, "no_cache", False))


# ------------------------------------------------------------------ get

def cmd_get(args: argparse.Namespace) -> int:
    c = _client(args)
    try:
        op = fetch_operator(args.name, client=c)
    except PrtsError as e:
        print(f"取数失败：{e}", file=sys.stderr)
        candidates = []
        try:
            candidates = [n for n in all_operator_names(client=c) if args.name in n]
        except PrtsError:
            pass
        if candidates:
            print("你是不是想找：" + "、".join(candidates[:8]), file=sys.stderr)
        return 2

    if args.json:
        data = op.to_dict()
        if not args.full:
            for sk in data["skills"]:
                sk["levels"] = [l for l in sk["levels"] if l["level"] in (7, 10)]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(op.summary())

    # 技能等级全表（-v 时展开）
    if args.full:
        for sk in op.skills:
            print(f"\n  技能{sk.index}「{sk.name}」")
            for lv in sk.levels:
                dur = f" 持续{lv.duration}s" if lv.duration else ""
                print(f"    {lv.label:>4s}  SP {lv.sp_init}/{lv.sp_cost}{dur}")
                print(f"          {lv.description}")

    if args.range:
        reg = RangeRegistry(client=c)
        ranges = reg.for_operator(op)
        if ranges:
            print()
            for slot, rng in sorted(ranges.items()):
                print(f"  {slot}（{rng.code}）——{rng.size} 格")
                for line in rng.draw().splitlines():
                    print("      " + line)
            reg.save()
    return 0


# ----------------------------------------------------------------- list

def cmd_list(args: argparse.Namespace) -> int:
    c = _client(args)
    if args.raw_names:
        names = all_operator_names(client=c)
        print(json.dumps(names, ensure_ascii=False, indent=1) if args.json
              else "\n".join(names))
        print(f"\n共 {len(names)} 个页面", file=sys.stderr)
        return 0

    from .prts.operator import _smw_operators, list_operators

    if args.profession or args.rarity is not None:
        rows = _smw_operators(c, profession=args.profession,
                              rarity=args.rarity, limit=args.limit)
    else:
        rows = list_operators(client=c)

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0

    if rows and "profession" in rows[0]:
        for r in rows:
            print(f"  ★{r['rarity']}  {r['profession']:4s}  {r['title']}")
    else:
        for r in rows:
            print(f"  HP {r.get('hp','?'):>5s}  ATK {r.get('atk','?'):>5s}  "
                  f"费用 {r.get('cost','?'):>4s}  {r.get('Page','?')}")
    print(f"\n共 {len(rows)} 条", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- range

def cmd_range(args: argparse.Namespace) -> int:
    c = _client(args)
    reg = RangeRegistry(client=c)

    if args.operator:
        op = fetch_operator(args.operator, client=c)
        ranges = reg.for_operator(op)
        if not ranges:
            print(f"{op.name} 页面上没有攻击范围数据", file=sys.stderr)
            return 1
        for slot, rng in sorted(ranges.items()):
            print(f"{op.name} {slot}（{rng.code}）—— {rng.size} 格")
            for line in rng.draw().splitlines():
                print("  " + line)
            print()
        reg.save()
        if args.json:
            print(json.dumps({k: v.to_dict() for k, v in ranges.items()},
                             ensure_ascii=False, indent=1))
        return 0

    codes = args.codes or reg.known()
    if not codes:
        print("没有指定代号，本地索引也是空的。试试：ak_tactic range 3-3", file=sys.stderr)
        return 1

    out: dict[str, dict] = {}
    ranges = []
    for code in codes:
        try:
            rng = reg.get(code)
        except PrtsError as e:
            print(f"  {code}: 取不到（{e}）", file=sys.stderr)
            continue
        ranges.append(rng)
        out[code] = rng.to_dict()
    reg.save()

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        for rng in ranges:
            print(f"{rng.code} —— {rng.cols}×{rng.rows} 网格，覆盖 {rng.size} 格")
            for line in rng.draw().splitlines():
                print("  " + line)
            print()
    return 0


# ---------------------------------------------------------------- stage

def display_code(level_id: str) -> str:
    """把 levelId 折成玩家熟悉的关卡号：main_01-07 → 1-7。

    这是**没有关卡索引时的兜底**。走 ark-nights 源时索引里有现成的
    `code` 字段（连 SR-EX-8 这种无规律的活动关号都在），优先用那个。
    """
    if not level_id.startswith("main_"):
        return level_id
    parts = level_id[len("main_"):].split("-")
    out = []
    for p in parts:
        try:
            out.append(str(int(p)))
        except ValueError:
            out.append(p)
    return "-".join(out)


def _gamedata(args: argparse.Namespace) -> GameDataSource:
    return GameDataSource(use_cache=not getattr(args, "no_cache", False))


def _print_stage_map(stage, *, with_routes: bool) -> None:
    legend = ("H 高台可部署  # 不可部署  . 地面可部署(近战位)  "
              ", 地面不可部署  S 敌人出生点  E 防守点")
    print(f"  图例：{legend}")
    print()
    if with_routes:
        print(stage.render_with_routes())
        print("\n  （数字 = 路线编号的个位，* = 多条路线叠在一起）")
    else:
        print(stage.map.render())


def cmd_stage(args: argparse.Namespace) -> int:
    src = _gamedata(args)

    if not args.level_id and not args.search:
        print("要指定关卡号（如 SR-EX-8、1-7），或用 --search 先找",
              file=sys.stderr)
        return 1

    if args.search:
        try:
            rows = src.search_levels(args.search, limit=args.limit)
        except GamedataError as e:
            print(f"取关卡索引失败：{e}", file=sys.stderr)
            return 2
        if not rows:
            print(f"没有匹配「{args.search}」的关卡", file=sys.stderr)
            return 1
        for e in rows:
            print(f"  {e.code:<12} {e.level_id:<30} {e.zone_id:<24} {e.difficulty}")
        print(f"\n共 {len(rows)} 条（索引共 {len(src.level_index())} 个关卡）")
        return 0

    try:
        stage = load_stage(args.level_id, chapter=args.chapter or None, source=src)
    except GamedataError as e:
        print(f"取关卡失败：{e}", file=sys.stderr)
        try:
            rows = src.search_levels(args.level_id, limit=8)
            if rows:
                print("你是不是想找：" + "、".join(r.code for r in rows), file=sys.stderr)
        except GamedataError:
            pass
        return 2

    lib = None if args.map else EnemyLibrary(source=src)

    if args.json:
        data = stage.to_dict()
        if lib is not None:
            data["enemies"] = {
                eid: {**lib.get(eid, 0).to_dict(), "count": n}
                for eid, n in stage.enemy_counts().items()
            }
            data["timeline"] = [
                {"time": round(t, 2), "enemy_id": s.enemy_id,
                 "name": lib.name(s.enemy_id), "route": s.route_index,
                 "start": list(stage.route(s.route_index).start)}
                for t, s in stage.timeline()
            ]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(stage.summary())
    if stage.code and stage.code != stage.level_id:
        print(f"  关卡号：{stage.code}")
    print()
    print("=== 地图 ===")
    _print_stage_map(stage, with_routes=not args.no_routes)

    if not args.map:
        print()
        print("=== 出怪路线 ===")
        for r in stage.used_routes():
            pts = " -> ".join(f"({x},{y})" for x, y in r.path)
            print(f"  route[{r.index:>2}] {r.mode:5s} {pts}")
        # 几何形状相同的路线合并着看，免得刷屏
        shapes: dict[tuple, list[int]] = {}
        for r in stage.used_routes():
            shapes.setdefault(tuple(r.path), []).append(r.index)
        if len(shapes) < len(stage.used_routes()):
            print(f"\n  实际上只有 {len(shapes)} 种不同走法：")
            for path, idx in shapes.items():
                print(f"    {' -> '.join(f'({x},{y})' for x, y in path)}"
                      f"   用于 route {idx}")

        print()
        print("=== 敌人 ===")
        for eid, n in stage.enemy_counts().items():
            s = lib.get(eid, 0)
            alias = f"（战斗数据里叫「{s.alias}」）" if s.alias else ""
            print(f"  {s.name}{alias}  ×{n}")
            print(f"      HP {s.max_hp:g}  攻 {s.atk:g}  防 {s.defense:g}  "
                  f"法抗 {s.magic_resistance:g}%  移速 {s.move_speed:g}  "
                  f"攻击间隔 {s.base_attack_time:g}s  重量 {s.weight:g}  "
                  f"漏怪扣 {s.life_point_reduce:g}")
        print(f"\n  合计 {stage.total_enemies()} 只")

        print()
        print("=== 出怪时间轴 ===")
        if args.timeline:
            for t, s in stage.timeline():
                r = stage.route(s.route_index)
                print(f"  {t:7.1f}s  {lib.name(s.enemy_id):<12s} "
                      f"route[{s.route_index:>2}] 从 ({r.start[0]},{r.start[1]}) 入场")
        else:
            tl = stage.timeline()
            for t, s in tl[:args.limit]:
                r = stage.route(s.route_index)
                print(f"  {t:7.1f}s  {lib.name(s.enemy_id):<12s} "
                      f"route[{s.route_index:>2}] 从 ({r.start[0]},{r.start[1]}) 入场")
            if len(tl) > args.limit:
                print(f"  …… 还有 {len(tl) - args.limit} 条，用 --timeline 看全部")
        print(f"\n  最后一只出现于 {stage.estimated_duration():.1f}s "
              f"（是出怪结束，不是通关时刻）")
    return 0


# ---------------------------------------------------------------- enemy

def cmd_enemy(args: argparse.Namespace) -> int:
    src = _gamedata(args)
    try:
        lib = EnemyLibrary(source=src)
        if args.search:
            hits = [eid for eid in lib.all_ids() if args.search in lib.name(eid)]
            if not hits:
                print(f"没有名字含「{args.search}」的敌人", file=sys.stderr)
                return 1
            for eid in hits[:args.limit]:
                print(f"  {lib.name(eid):<16s} {eid}  档位 {lib.levels(eid)}")
            if len(hits) > args.limit:
                print(f"  …… 还有 {len(hits) - args.limit} 个")
            return 0
        if not args.enemy_id:
            print("要么给敌人 id，要么用 --search 按名字找", file=sys.stderr)
            return 1
        if not lib.exists(args.enemy_id):
            print(f"属性库里没有 {args.enemy_id}", file=sys.stderr)
            near = [e for e in lib.all_ids() if args.enemy_id.split("_")[-1] in e][:6]
            if near:
                print("相近的 id：" + "、".join(near), file=sys.stderr)
            return 2
        st = lib.get(args.enemy_id, args.level)
    except GamedataError as e:
        print(f"取敌人数据失败：{e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(st.to_dict(), ensure_ascii=False, indent=2))
        return 0
    print(lib.describe(args.enemy_id, args.level))
    if len(lib.levels(args.enemy_id)) > 1:
        print(f"  可用档位：{lib.levels(args.enemy_id)}（用 --level 指定）")
    return 0


# ---------------------------------------------------------------- stats

def cmd_stats(args: argparse.Namespace) -> int:
    calc = OperatorCalculator(rounding=args.rounding)

    if args.search:
        rows = calc.find(args.search, limit=args.limit)
        if not rows:
            print(f"没有匹配「{args.search}」的干员", file=sys.stderr)
            return 1
        for cid, name in rows:
            c = calc.character(cid)
            caps = [int(p.get("maxLevel") or 0) for p in (c.get("phases") or [])]
            prof = PROFESSION_CN.get(c.get("profession") or "", c.get("profession") or "")
            print(f"  {name:<12} {cid:<26} ★{parse_rarity(c.get('rarity'))}  "
                  f"{prof:<4} 上限 {caps}")
        print(f"\n共 {len(calc.all_ids())} 名干员")
        return 0

    if not args.char_id:
        print("要指定干员 id 或中文名（如 char_002_amiya / 阿米娅），"
              "或用 --search 先找", file=sys.stderr)
        return 1

    char_id = args.char_id
    if not calc.exists(char_id):
        hits = calc.find(char_id, limit=6)
        if not hits:
            print(f"没有这个干员：{args.char_id}", file=sys.stderr)
            return 2
        # find() 已把完全同名的排在最前，直接采用；仅在不是同名时才提示
        char_id = hits[0][0]
        if hits[0][1] != args.char_id.strip():
            others = "、".join(f"{n}（{i}）" for i, n in hits[1:4])
            print(f"（按「{args.char_id}」取到 {hits[0][1]}）"
                  + (f"，另有 {others}" if others else ""), file=sys.stderr)

    if args.modules:
        rows = calc.modules(char_id)
        if not rows:
            print(f"{char_id} 没有模组")
            return 0
        for m in rows:
            mark = "有属性" if m["has_stats"] else "证章（无属性）"
            lv = ""
            if m["has_stats"]:
                lv = " 等级 " + "/".join(str(x) for x in sorted(calc.module_levels(m["id"])))
            print(f"  {m['name']:<20} {m['id']:<26} {m['type']:<9} {mark}{lv}")
        return 0

    st = calc.stats(char_id, elite=args.elite, level=args.level,
                    trust=args.trust, potential=args.potential,
                    module=args.module or None, module_level=args.module_level)

    if args.json:
        print(json.dumps(st.to_dict(), ensure_ascii=False, indent=2))
        return 0

    prof = PROFESSION_CN.get(st.profession, st.profession)
    print(f"{st.name}（{st.char_id}）  ★{st.rarity}  {prof}"
          + (f" · {st.sub_profession}" if st.sub_profession else ""))
    parts = [f"{st.phase_name} · 等级 {st.level}"]
    if st.trust:
        parts.append(f"信赖 {st.trust:g}%")
    if st.potential > 1:
        parts.append(f"潜能 {st.potential}")
    if st.module and st.module_level:
        parts.append(f"模组 {st.module} Lv{st.module_level}")
    print("  " + " · ".join(parts))
    print("  " + "─" * 62)

    has_bonus = bool(st.trust_bonus or st.potential_bonus or st.module_bonus)
    for _, label, value in st.panel():
        base = st.base.get(_)
        if has_bonus and isinstance(base, (int, float)) and not isinstance(base, bool):
            seg = [f"{base:>8g}"]
            for src_ in (st.trust_bonus, st.potential_bonus, st.module_bonus):
                v = src_.get(_, 0)
                seg.append(f"{v:>+7g}" if v else f"{'·':>7}")
            print(f"  {label:<10}{''.join(seg)} = {value:>8g}")
        else:
            print(f"  {label:<10}{value:>8g}")
    if has_bonus:
        print(f"  {'':<10}{'基础':>8}{'信赖':>7}{'潜能':>7}{'模组':>7}")
    return 0


# ---------------------------------------------------------------- skills

def _resolve_char(calc, key: str) -> str:
    """把中文名或 id 收敛成 char_id，顺带提示近似项。"""
    if calc.exists(key):
        return key
    hits = calc.find(key, limit=6)
    if not hits:
        raise OperatorError(f"没有这个干员：{key}")
    if hits[0][1] != key.strip():
        others = "、".join(f"{n}（{i}）" for i, n in hits[1:4])
        print(f"（按「{key}」取到 {hits[0][1]}）"
              + (f"，另有 {others}" if others else ""), file=sys.stderr)
    return hits[0][0]


def _print_skill_level(lv, atk: float | None, *, indent: str = "    ") -> None:
    """打印一个技能等级的全部可读信息。"""
    dur = "无限" if lv.infinite else f"{lv.duration:g}s"
    if lv.duration_type == "AMMO":
        ammo = lv.effects.ammo
        dur = f"弹药 {ammo} 发" if ammo else "弹药"
    ready = lv.time_to_ready()
    print(f"{indent}{lv.label}   {lv.skill_type_cn} · {lv.sp_type_cn}"
          f" · SP {lv.init_sp:g}/{lv.sp_cost:g} · 持续 {dur}")
    if ready is not None:
        print(f"{indent}      攒满需 {ready:.0f}s（从 0 技力起算）")
    if lv.range_id:
        print(f"{indent}      攻击范围改为 {lv.range_id}")
    desc = lv.description.replace("\n", "\n" + indent + "      ")
    print(f"{indent}      {desc}")
    eff = lv.effects.describe()
    if eff:
        print(f"{indent}      效果：{'  '.join(eff)}")
    if atk is not None:
        # 「一次攻击」= 面板口径 × 技能倍率。两段都在这里显式乘开：`attack_power`
        # 只到面板（2026-09-18 裁定），倍率归 `damage.resolve_damage`，
        # 所以这个展示值要把两边合起来才是玩家看到的那一下。
        print(f"{indent}      一次攻击 "
              f"{lv.effects.attack_power(atk) * lv.effects.atk_scale:,.0f}"
              f"（基于攻击力 {atk:g}）"
              f"   连击 {lv.effects.hit_count}×   目标 {lv.effects.max_target}")
    leftover = {k: v for k, v in lv.effects.other.items()}
    if leftover:
        top = sorted(leftover.items(), key=lambda kv: -abs(kv[1]))[:6]
        print(f"{indent}      未解析："
              + "  ".join(f"{k}={v:g}" for k, v in top)
              + (f"  …共 {len(leftover)} 项" if len(leftover) > 6 else ""))


def cmd_talents(args: argparse.Namespace) -> int:
    """`talents` 子命令：天赋档位 + 黑板 + 已建模的机制。"""
    from .battle.talents import MODELED, squad_cost_bonus, find_snow

    book = TalentBook()
    calc = OperatorCalculator()

    if args.coverage:
        cov = book.coverage()
        print(f"天赋候选总数 {cov['candidates']:,}，"
              f"不同黑板键 {cov['distinct_keys']} 种，键被用 {cov['uses']:,} 次")
        print("（归档逻辑与技能共用；已显式建模的机制见下）")
        for k, v in MODELED.items():
            print(f"  {k:<12} {v}")
        return 0

    if not args.char_id:
        print("请给一个干员，或用 --coverage 看整体规模", file=sys.stderr)
        return 2

    char_id = _resolve_char(calc, args.char_id)
    if char_id is None:
        return 1

    if args.all_candidates:
        rows = book.all_candidates(char_id)
    else:
        rows = book.for_operator(char_id, elite=args.elite, level=args.level,
                                 potential=args.potential)
    if args.json:
        print(json.dumps([t.to_dict() for t in rows], ensure_ascii=False, indent=1))
        return 0

    name = calc.character(char_id).get("name") or char_id
    print(f"{name}（{char_id}）  精{args.elite} {args.level}级 潜能{args.potential}")
    if not rows:
        print("  这个练度下没有生效的天赋"
              "（注意：低精英阶段有些干员本来就还没有天赋）")
        return 0
    for t in rows:
        flags = []
        if find_snow([t]):
            flags.append("已建模：积雪")
        if squad_cost_bonus([t]):
            flags.append(f"已建模：部署返费 {squad_cost_bonus([t]):g}")
        mark = f"  ← {'、'.join(flags)}" if flags else ""
        print(f"  {t.title}「{t.name}」（{t.label}）{mark}")
        print(f"    {t.description}")
        keys = {k: v for k, v in t.blackboard.items() if not k.startswith("$")}
        if keys:
            print("    黑板：" + "  ".join(f"{k}={v:g}" for k, v in keys.items()))
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    book = SkillBook()
    calc = OperatorCalculator()

    if args.search:
        rows = calc.find(args.search, limit=args.limit)
        if not rows:
            print(f"没有匹配「{args.search}」的干员", file=sys.stderr)
            return 1
        for cid, name in rows:
            n = len(book.for_operator(cid))
            names = "、".join(s.name for s in book.for_operator(cid)) or "无"
            print(f"  {name:<12} {cid:<26} {n} 个技能：{names}")
        return 0

    if args.coverage:
        cov = book.coverage()
        print(f"skill_table 的黑板键归类覆盖率："
              f"{cov['classified']:,} / {cov['total']:,} = {cov['coverage'] * 100:.1f}%")
        print(f"未归类的键有 {cov['distinct_unknown']} 种，最常见的：")
        for k, n in cov["top_unknown"]:
            print(f"  {k:<42} {n:>6}")
        return 0

    if not args.char_id:
        print("要指定干员 id 或中文名（如 char_002_amiya / 阿米娅），"
              "或用 --search 先找", file=sys.stderr)
        return 1

    char_id = _resolve_char(calc, args.char_id)
    skills = book.for_operator(char_id)
    if not skills:
        print(f"{char_id} 没有技能数据")
        return 0

    # 想显示绝对伤害就得先算出攻击力
    atk = None
    if not args.no_atk:
        try:
            st = calc.stats(char_id, elite=args.elite, level=args.level,
                            trust=args.trust, potential=args.potential)
            atk = float(st.total.get("atk") or 0) or None
        except OperatorError:
            atk = None

    if args.json:
        print(json.dumps(
            {"char_id": char_id, "atk": atk,
             "skills": [s.to_dict(level=args.level, mastery=args.mastery)
                        for s in skills]},
            ensure_ascii=False, indent=2))
        return 0

    char = calc.character(char_id)
    prof = PROFESSION_CN.get(char.get("profession") or "", char.get("profession") or "")
    print(f"{char.get('name')}（{char_id}）  {prof}  共 {len(skills)} 个技能")
    if atk is not None:
        print(f"  攻击力按 精英{args.elite} {args.level}级"
              + (f" 信赖{args.trust:g}% 潜能{args.potential}" if args.trust or args.potential > 1 else "")
              + f" 算得 {atk:g}")
    print()

    for sk in skills:
        print(f"  技能{sk.slot}「{sk.name}」  精英{sk.unlock_phase} 解锁"
              f"  （{sk.skill_id}）")
        if args.all:
            for lv in sk.levels:
                _print_skill_level(lv, atk, indent="      ")
        else:
            _print_skill_level(sk.level(args.level, args.mastery), atk, indent="      ")
        print()
    return 0


# ------------------------------------------------------------------ db

def _table(rows: list[dict], columns: list[str]) -> None:
    """把若干行按固定列宽打出来。列宽按内容自适应。"""
    if not rows:
        print("    （没有匹配项）")
        return
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows))
              for c in columns}
    head = "  ".join(c.ljust(widths[c]) for c in columns)
    print("    " + head)
    print("    " + "-" * len(head))
    for r in rows:
        print("    " + "  ".join(str(r.get(c, "")).ljust(widths[c])
                                 for c in columns))


def _n(v) -> str:
    """数字显示：整数不掉小数点，None 打「—」。"""
    if v is None:
        return "—"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _enemy_text(text: str, indent: str = "  ") -> str:
    """把敌人页上的 wikitext 还原成人话，按行缩进。"""
    if not text:
        return f"{indent}—"
    lines = [ln.strip() for ln in render_wiki(text).split("\n")]
    body = "\n".join(indent + ln for ln in lines if ln)
    return body or f"{indent}—"


def _print_enemy(d: dict) -> None:
    tags = []
    if d["is_irregular"]:
        tags.append("非常规敌人")
    if not d["has_handbook"]:
        tags.append("无图鉴")
    head = d["name"] + (f"（显示名 {d['display_name']}）" if d["display_name"] else "")
    print(f"{head}  {d['page']}  模板id={d['prts_id']}  "
          f"编号={d['index_code'] or '—'}  {d['grade'] or '—'}  "
          f"{d['category'] or '—'}" + (f"  [{' / '.join(tags)}]" if tags else ""))
    print(f"  伤害类型 {d['damage_type'] or '—'}  攻击方式 {d['attack_way'] or '—'}  "
          f"行动方式 {d['move_way'] or '—'}  阵营 {d['camp'] or '—'}")
    if d["debut_event"]:
        print(f"  登场活动：{d['debut_event']}")
    if d["ability"]:
        print("  能力：")
        print(_enemy_text(d["ability"], "      "))

    for lv in d["levels"]:
        print(f"  档 {lv['level']}（{lv['name']}，{lv['grade'] or '—'}）")
        print(f"      生命 {_n(lv['hp'])}  攻击 {_n(lv['atk'])}  "
              f"防御 {_n(lv['defense'])}  法抗 {_n(lv['res'])}%  "
              f"移速 {_n(lv['move_speed'])}  攻速 {_n(lv['attack_speed'])}  "
              f"攻击间隔 {_n(lv['base_attack_time'])}")
        print(f"      重量 {_n(lv['weight'])}  攻击半径 {_n(lv['range_radius'])}  "
              f"目标价值 {_n(lv['target_value'])}  嘲讽 {_n(lv['taunt_level'])}  "
              f"损伤抵抗 {_n(lv['damage_resistance'])}  "
              f"元素抗性 {_n(lv['element_resistance'])}")
        if lv["resists"]:
            print(f"      免疫：{'、'.join(lv['resists'])}")
        if lv["sp_recovery_type"]:
            print(f"      技力槽 {_n(lv['init_sp'])}/{_n(lv['max_sp'])}，"
                  f"{lv['sp_recovery_type']}（{_n(lv['sp_recovery_value'])}）")
        if lv["talent"]:
            print("      天赋：")
            print(_enemy_text(lv["talent"], "        "))
        for s in lv["skills"]:
            print(f"      技能{s['slot']} {s['name']}  首次冷却 "
                  f"{_n(s['init_cooldown'])}s  周期冷却 {_n(s['cooldown'])}s  "
                  f"技力消耗 {_n(s['sp_cost'])}")
            if s["effect"]:
                print(_enemy_text(s["effect"], "        "))
        if lv["blackboard"]:
            print("      黑板：" + json.dumps(lv["blackboard"], ensure_ascii=False))
        if lv["hidden_params"]:
            print("      注释里的参数（页面上不显示）："
                  + json.dumps(lv["hidden_params"], ensure_ascii=False))


def cmd_verify(args: argparse.Namespace) -> int:
    """验证一份打法：关卡无关的三星判定 + 归因。

    打法有两种给法：`--plan` 指一份 JSON，或 `--team` 现写一行。
    两者都没有时报错——**不要**给一个默认阵容，那会让"跑出来的结果"
    和"我以为我在验的东西"对不上。
    """
    from dataclasses import asdict

    from .plan import Plan, PlanError, Roster
    from .verify import Verifier

    if args.plan:
        plan = Plan.load(args.plan)
        if args.stage and plan.stage != args.stage:
            print(f"注意：打法里的关卡是 {plan.stage}，与命令行的 {args.stage} "
                  f"不一致，以打法里的为准", file=sys.stderr)
    elif args.team:
        if not args.stage:
            print("用 --team 时必须给关卡号，例如 "
                  "`verify main_01-07 --team \"…\"`", file=sys.stderr)
            return 2
        plan = Plan.quick(args.stage, args.team)
    else:
        print("要么给 --plan <文件>，要么给 --team \"名字:x,y[:朝向[:技能槽]]; …\"",
              file=sys.stderr)
        return 2

    if args.save_plan:
        print(f"打法已写出：{plan.dump(args.save_plan)}")

    roster = Roster.from_json(args.box) if args.box else Roster.empty()
    verifier = Verifier(use_range_table=not args.no_range_table,
                        verbose=args.verbose)
    try:
        v = verifier.run(plan, roster=roster)
    except (PlanError, KeyError) as exc:
        print(f"打法有问题：{exc}", file=sys.stderr)
        return 2

    if args.json:
        out = asdict(v)
        out.pop("result", None)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(v.report())

    # 阶段六的两个输出：摆位图与时间轴。默认不开——它们是给人看的，
    # 而 verify 的主输出是给机器看的判定。
    if args.diagram or args.timeline or args.report:
        from .diagram import placement_diagram, timeline_table
        stage = verifier.stage(plan.stage)
        if args.report:
            from .diagram import battle_report
            text = battle_report(stage, plan, verdict=v,
                                 route_metric=args.heat_metric)
            Path(args.report).write_text(text, encoding="utf-8")
            print(f"\n完整报告已写出：{args.report}")
        if args.diagram:
            print("\n" + placement_diagram(stage, plan, verdict=v,
                                           show_enemy=True))
        if args.timeline:
            print("\n" + timeline_table(stage, plan, verdict=v))
    return 0 if v.stars == 3 else 1


def cmd_search(args: argparse.Namespace) -> int:
    """搜索一套能三星的阵容：落位、朝向、顺序都由搜索决定。

    与 `verify` 是**反方向**：verify 拿一份已知打法去验，search 从零找一份。
    搜索两层——先用到达时刻表做几何剪枝（哪些落位根本接不到敌人），
    再用验证器做 beam search。
    """
    from .plan import PlanError, Roster
    from .search import Searcher
    from .verify import Verifier

    if not args.box:
        print("搜索必须给 --box <名册.json>——搜索要知道你**有什么**，"
              "否则无从搜起", file=sys.stderr)
        return 2
    roster = Roster.from_json(args.box)
    team = [n.strip() for n in (args.team or "").replace(",", ";").split(";")
            if n.strip()]
    if not team:
        # 不给 --team 就走组队建议层：先占「回费先锋」「骗伤处决者」两个
        # 角色位，其余按练度补齐。原先这里是"取名册前 N 名"——那是按练度
        # 排的，与这一关需要什么角色无关（详见 ak_tactic/team.py 的 docstring）。
        from .team import suggest
        sug = suggest(roster, size=args.top, stage=(args.stage or None))
        team = sug.team()
        if not team:
            print("名册里没有可用的干员", file=sys.stderr)
            return 2
        print(sug.report(), file=sys.stderr)
        print(f"未指定 --team，按角色取 {len(team)} 名："
              f"{'、'.join(team)}", file=sys.stderr)

    verifier = Verifier(use_range_table=not args.no_range_table,
                        verbose=False)
    searcher = Searcher(verifier, verbose=False)
    try:
        got = searcher.search(
            args.stage, roster, team,
            max_ops=args.max_ops, beam=args.beam, per_op=args.per_op,
            cells=None)
    except (PlanError, KeyError) as exc:
        print(f"搜不下去：{exc}", file=sys.stderr)
        return 2

    if args.save_plan and got.plan is not None:
        print(f"打法已写出：{got.plan.dump(args.save_plan)}")

    if args.json:
        out = {
            "stage": args.stage, "evaluated": got.evaluated,
            "depth": got.depth, "stars": got.verdict.stars
            if got.verdict else 0,
            "steps": got.steps,
            "plan": got.plan.to_dict() if got.plan else None,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(got.report())
    return 0 if got.ok else 1


def cmd_team(args: argparse.Namespace) -> int:
    """按角色出一份组队建议：回费先锋 + 骗伤处决者 + 练度补齐。

    与 `search` 的分工：`search` 是"给定人找打法"，这一步是"给定名册挑人"。
    `search` 不给 `--team` 时现在就取这里的产物。
    """
    from .plan import Roster
    from .team import suggest

    if not args.box:
        print("要出一份组队建议，必须给 --box <名册.json>", file=sys.stderr)
        return 2
    try:
        roster = Roster.from_json(args.box)
    except Exception as exc:                              # noqa: BLE001
        print(f"名册读不进来：{exc}", file=sys.stderr)
        return 2

    sug = suggest(roster, size=args.size, path=args.db or None,
                  with_charger=not args.no_charger,
                  stage=(getattr(args, "stage", "") or None))
    if args.json:
        print(json.dumps({
            "picks": [p.__dict__ for p in sug.picks],
            "filler": [p.__dict__ for p in sug.filler],
            "rejected": [p.__dict__ for p in sug.rejected],
            "team": sug.team(),
            "cost_env": {"tight": sug.cost_note[0], "note": sug.cost_note[1]},
            "notes": sug.notes,
        }, ensure_ascii=False, indent=2))
    else:
        print(sug.report())
    return 0


def cmd_enemy_db(args: argparse.Namespace) -> int:
    """敌人库：prts.wiki → `data/enemydb.sqlite`。与干员库是两个独立的文件。

    注意与上面的 `cmd_enemy` 区分：那个是**实时**从 gamedata 取一个敌人的
    图鉴与数值（`ak_tactic enemy 源石虫`），这个是查**本地库**。
    """
    path = Path(args.path) if args.path else None

    if args.action == "schema":
        print(ENEMY_DB_SCHEMA_DOC)
        return 0

    if args.action == "build":
        what = f"（只抓前 {args.pages} 页）" if args.pages else ""
        print(f"从 prts.wiki 重建敌人库{what}……")
        report = build_enemy_db(path, verbose=args.verbose, limit=args.pages)
        print(report.summary())
        return 0

    conn = connect_enemy(path)
    try:
        if args.action == "info":
            info = enemy_db_info(conn)
            print("版本戳：")
            for k, v in info["meta"].items():
                print(f"    {k:<14} {v}")
            print("行数：")
            for k, v in info["counts"].items():
                print(f"    {k:<20} {v:>8,}")
            if not info["version_ok"]:
                print(f"\n警告：库的结构版本是 {info['meta'].get('db_version')}，"
                      f"当前代码要 {info['expected_version']}——"
                      f"请跑 `enemy build` 重建。")
            return 0

        if args.action == "find":
            rows = find_enemies(conn, args.key, limit=args.limit, grade=args.grade)
            _table(rows, ["page", "name", "index_code", "grade", "damage_type",
                          "move_way", "level_count"])
            return 0

        if args.action == "show":
            if not args.key:
                print("要给一个敌人，例如 `enemy show 源石虫`", file=sys.stderr)
                return 2
            d = enemy_detail(conn, args.key)
            if args.json:
                print(json.dumps(d, ensure_ascii=False, indent=2))
                return 0
            _print_enemy(d)
            return 0

        if args.action == "formula":
            from .db import DEFAULT_ENEMY_DB_PATH
            from .enemy_formula import enemy_formulas
            if not args.key:
                print("要给一个敌人，例如 `enemydb formula 死志的凝结`",
                      file=sys.stderr)
                return 2
            try:
                rep = enemy_formulas(path or DEFAULT_ENEMY_DB_PATH, args.key)
            except KeyError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            if args.json:
                out = dict(rep)
                out["sections"] = [
                    {**s, "terms": [t.to_dict() for t in s["terms"]]}
                    for s in rep["sections"]]
                print(json.dumps(out, ensure_ascii=False, indent=2))
                return 0
            total = sum(len(s["terms"]) for s in rep["sections"])
            print(f"{rep['name']}   {rep['page']}")
            print(f"{len(rep['sections'])} 段正文，编译出 {total} 个公式项\n")
            for s in rep["sections"]:
                head = s["source"]
                if s["level"] is not None:
                    head += f" 档{s['level']}"
                if s["skill"]:
                    head += f"  {s['skill']}"
                print(f"── {head}")
                print(f"   {s['flat'][:130]}")
                if not s["terms"]:
                    print("     （未编译出公式项）")
                for t in s["terms"]:
                    print(f"     · {t.line()}")
                print()
            if len(rep["candidates"]) > 1:
                others = ", ".join(c["name"] for c in rep["candidates"][1:])
                print(f"（另有相似条目：{others}）")
            return 0

        if args.action == "sql":
            if not args.key:
                print("要给一条 SELECT", file=sys.stderr)
                return 2
            rows = enemy_sql(conn, args.key, limit=args.limit)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                _table(rows, list(rows[0]) if rows else [])
            return 0
    finally:
        conn.close()
    return 0


def cmd_db(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else None

    if args.action == "schema":
        print(DB_SCHEMA_DOC)
        return 0

    if args.action == "build":
        import time as _time

        from .db.build import DEFAULT_SOURCE
        from .fetchplan import (GAMEDATA_STATS_KEY, EstimateReport, dir_bytes,
                                estimate_gamedata, record)
        from .gamedata.source import GameDataSource

        target = path or DEFAULT_DB_PATH
        est, pending = estimate_gamedata()
        rep = EstimateReport(title=f"重建干员库 → {target}")
        rep.items.append(est)
        rep.notes.append("建库全程不联网；要下多少只取决于缓存里还缺哪几张表。")
        rep.notes.append("关卡索引不在这里取（要联网，走 `db stage-fetch`）；"
                         "重建时它从旧库沿用，不会被清空。")
        print(rep.render())
        if args.dry_run:
            print("\n（--dry-run：只估算，没有建库。）")
            return 0

        src = GameDataSource(base=DEFAULT_SOURCE)
        before = dir_bytes(src.cache_dir)
        t0 = _time.time()
        print("\n从 gamedata 重建干员库……")
        report = build_db(target, verbose=args.verbose)
        secs = _time.time() - t0
        got = max(0, dir_bytes(src.cache_dir) - before)
        record(GAMEDATA_STATS_KEY, hits=len(pending), bytes_=got or None,
               seconds=secs, bytes_basis="建库前后的缓存目录增量")
        print(report.summary())
        print(f"耗时 {secs:.1f} 秒，其中新下载约 {got / 1048576:.1f} MB"
              f"（实测吞吐会用于下次预估）。")
        return 0

    if args.action == "stage-fetch":
        import time as _time

        from .db.stages import (CHAPTER_TYPES, STATS_KEY, StageTableError,
                                estimate_fetch, fetch_level_index, fetch_names,
                                insert_stages, prune_foreign_rows, zone_title)
        from .fetchplan import EstimateReport, record

        target = path or DEFAULT_DB_PATH
        est = estimate_fetch(refresh=args.force)
        rep = EstimateReport(title=f"取关卡索引与名字（联网）→ {target}")
        rep.items.append(est)
        rep.notes.append("取不到时会明确报「关卡名获取失败」，并**保留上一版表**"
                         "——绝不写一张空表下去。")
        rep.notes.append("重复取是幂等的：同一个 levelId 覆盖写。")
        rep.notes.append("同时取**关卡中文名与章节名**：索引来自 map.ark-nights.com，"
                         "而名字只在 GitHub 镜像的 excel/ 里（ark-nights 没有该目录）。"
                         "名字那一项取不到**不算硬失败**——索引照写、名字栏留空。")
        print(rep.render())
        if args.dry_run:
            print("\n（--dry-run：只估算，没有真取、没有写库。）")
            return 0

        print("\n开始取……")
        t0 = _time.time()
        try:
            index = fetch_level_index(refresh=args.force)
        except StageTableError as exc:
            record(STATS_KEY, hits=est.hits, bytes_=None,
                   seconds=_time.time() - t0, ok=False)
            print(f"\n{exc}")
            print("库没有被改动，上一版关卡表原样保留。")
            return 1

        names: dict = {}
        zones: dict = {}
        name_err = ""
        try:
            names, zones = fetch_names(refresh=args.force)
        except StageTableError as exc:
            name_err = str(exc)

        conn = connect(target, readonly=False)
        prune_rep: dict[str, int] = {}
        try:
            count = insert_stages(conn, index, names, zones, report=prune_rep)
        finally:
            conn.close()
        secs = _time.time() - t0
        # 耗时是本次真取的实测；体积沿用**本次预估里那次 HEAD 探测**的值
        # （本函数不统计真正下了多少字节，绝不假装它是下载量）。
        record(STATS_KEY, hits=est.hits, bytes_=est.bytes_,
               bytes_basis="本关卡索引的 HEAD 探测", seconds=secs)
        codes = {v.get("code") for v in index.values() if v.get("code")}
        print(f"\n取到 {count} 个关卡（{len(codes)} 个关卡号），耗时 {secs:.1f} 秒，"
              f"已写入 {target}")
        print(f"    只写这五类 zone：{'、'.join(CHAPTER_TYPES)}"
              f"（其余类型与 zone 表里没有的关卡在同一个事务里清掉："
              f"筛掉 {prune_rep.get('rows_skipped', 0)} 条索引条目、"
              f"清掉 {prune_rep.get('zones_removed', 0)} 个 zone / "
              f"{prune_rep.get('stages_removed', 0)} 个关卡）")
        if name_err:
            print(f"\n[警告] {name_err}")
            print("      索引已照常写入，但**关卡中文名与章节名是空的**"
                  "——选关界面会退回显示 levelId。")
        else:
            named = sum(1 for n in names.values() if n.get("name"))
            print(f"关卡中文名 {named} 条（索引独有、stage_table 里没有的留空），"
                  f"章节/区域 {len(zones)} 条")
            samples = [(zid, {**z, "zone_id": zid}) for zid, z in zones.items()
                       if z.get("type") in ("MAINLINE", "MAINLINE_ACTIVITY")]

            def _chap(kv: tuple) -> tuple:
                """按「主线 → 主线活动」再按章号排。

                不能按 `zone_index` 排——那是游戏内部的**分段序号**（0–5 循环），
                第 15–17 章与序章、第四章同号，排出来会把它们埋在中间看不见。
                """
                z = kv[1]
                t = (z.get("name_title") or "").strip()
                return (0 if z.get("type") == "MAINLINE" else 1,
                        int(t) if t.isdigit() else 99)

            samples.sort(key=_chap)
            if samples:
                picked = samples[:3] + samples[-2:]
                print("  章名样例：" + "、".join(
                    zone_title(z) for _zid, z in picked))
            act = [(zid, {**z, "zone_id": zid}) for zid, z in zones.items()
                   if z.get("type") == "ACTIVITY"
                   and (zid or "").startswith("act54side")]
            if act:
                print("  月行水上的分部：" + "、".join(
                    f"{zone_title(z)}（{zid}）" for zid, z in sorted(act)))
        print("看几个：`db stages SR-EX`")
        return 0

    if args.action == "stage-prune":
        # 不联网也能清：口径（只留这五类）是本地判定，不需要重取。
        from .db.stages import CHAPTER_TYPES, clean_zone_names, prune_foreign_rows

        target = path or DEFAULT_DB_PATH
        if args.dry_run:
            conn = connect(target)
            try:
                per_type = dict(conn.execute(
                    "SELECT type, count(*) FROM zone GROUP BY type"))
                gone_z = sum(n for t, n in per_type.items()
                             if t not in CHAPTER_TYPES)
                gone_s = conn.execute(
                    "SELECT count(*) FROM stage WHERE zone_id IS NULL OR zone_id = '' "
                    "OR zone_id NOT IN (SELECT zone_id FROM zone WHERE type IN (%s))"
                    % ", ".join("?" * len(CHAPTER_TYPES)),
                    CHAPTER_TYPES).fetchone()[0]
            finally:
                conn.close()
            drop = {t: n for t, n in per_type.items() if t not in CHAPTER_TYPES}
            print(f"（--dry-run）会清掉 {gone_z} 个 zone、{gone_s} 个关卡。")
            print(f"    要清的 zone 类型：{drop}")
            print(f"    留下的是：{'、'.join(CHAPTER_TYPES)}"
                  f"（{sum(n for t, n in per_type.items() if t in CHAPTER_TYPES)} 个 zone）")
            return 0
        conn = connect(target, readonly=False)
        try:
            with conn:
                gone = prune_foreign_rows(conn)
                renamed = clean_zone_names(conn)
        finally:
            conn.close()
        print(f"清掉 {gone[0]} 个 zone、{gone[1]} 个关卡（不在 "
              f"{'、'.join(CHAPTER_TYPES)} 里的，以及 zone_id 在 zone 表里查不到的）")
        print(f"活动名擦掉「复刻」后缀：{renamed} 条")
        print(f"已写回 {target}")
        return 0

    if args.action == "tile-fetch":
        from .db.tiles import fetch_tile_info
        tiles = fetch_tile_info(force=args.force)
        print(f"地块字典取到 {len(tiles)} 条（已写入缓存 data/cache/theresa/）")
        print("注意：这是缓存，要进库请跑 `db build`（或后续版本提供单独灌入）。")
        return 0

    conn = connect(path)
    try:
        if args.action == "info":
            info = db_info(conn)
            print("版本戳：")
            for k, v in info["meta"].items():
                print(f"    {k:<14} {v}")
            print("行数：")
            for k, v in info["counts"].items():
                print(f"    {k:<20} {v:>8,}")
            if not info["version_ok"]:
                print(f"\n警告：库的结构版本是 "
                      f"{info['meta'].get('db_version')}，"
                      f"当前代码要 {info['expected_version']}——"
                      f"请跑 `db build` 重建。")
            return 0

        if args.action == "tiles":
            from .db.tiles import KNOWN_GAPS, load_tiles
            table = load_tiles(conn)
            if not table:
                print("tile 表是空的。地块字典不是 gamedata 来源，"
                      "建库时若取不到会留空——跑 `db build` 重试，"
                      "或先用 `db tile-fetch` 探一下网络。")
                return 1
            kw = (args.key or "").strip()
            hit = {k: v for k, v in table.items()
                   if not kw or kw in k or kw in (v.get("name") or "")
                   or kw in (v.get("description") or "")}
            if args.json:
                print(json.dumps(hit, ensure_ascii=False, indent=2))
                return 0
            print(f"地块字典：库内 {len(table)} 条"
                  f"{f'，命中「{kw}」{len(hit)} 条' if kw else ''}")
            for k in sorted(hit):
                v = hit[k]
                flag = " [功能性]" if v.get("is_functional") else ""
                print(f"    {k:<24} {v.get('name') or '(无名)':<10}{flag}")
                print(f"        {v.get('description') or ''}")
            gap = [g for g in KNOWN_GAPS if g not in table]
            if gap:
                print(f"    已知缺口（在关卡里出现过但字典没有）：{'、'.join(gap)}")
            return 0

        if args.action == "stages":
            from .db.stages import (ENV_LABELS, FOUR_STAR_SUFFIX, list_stages,
                                    load_zones, zone_title)
            hits = list_stages(conn, keyword=args.key,
                               difficulty=args.difficulty, limit=args.limit)
            if args.json:
                print(json.dumps(hits, ensure_ascii=False, indent=2))
                return 0
            if not hits:
                print("关卡索引是空的（或没有匹配）。"
                      "跑 `db stage-fetch` 取一次，要联网。")
                return 1
            print(f"关卡索引：命中 {len(hits)} 条")
            if not any(e.get("name") for e in hits):
                print("    注：这一批没有关卡中文名。名字与章节要跑一次 "
                      "`db stage-fetch`（要联网，取自 GitHub 镜像的 excel/）。")
            zones = load_zones(conn)
            for e in hits:
                star = " [四星限定]" if e["level_id"].endswith(FOUR_STAR_SUFFIX) else ""
                diff = "" if e["difficulty"] == "NORMAL" else f" [{e['difficulty']}]"
                env = ENV_LABELS.get(e.get("diff_group") or "", "")
                env = f" [{env}]" if env else ""
                z = zones.get(e.get("zone_id") or "")
                zt = zone_title(z) if z else ""
                print(f"    {e['code'] or '(无名)':<13} {(e.get('name') or '—'):<13}"
                      f"{e['level_id']:<31}{e['zone_id']:<18}"
                      f"{zt:<20}{diff}{env}{star}")
            return 0

        if args.action == "find":
            rows = [dict(r) for r in find_operators(
                conn, args.key, limit=args.limit,
                operators_only=not args.include_tokens)]
            _table(rows, ["char_id", "name", "rarity", "profession_cn",
                          "sub_profession_name", "position"])
            return 0

        if args.action == "char":
            if not args.key:
                print("要给一个干员，例如 `db char 阿米娅`", file=sys.stderr)
                return 2
            d = char_detail(conn, args.key)
            if args.json:
                print(json.dumps(d, ensure_ascii=False, indent=2))
                return 0
            print(f"{d['name']}（{d['appellation']}） {d['rarity']}★ "
                  f"{d['profession']}·{d['sub_profession']}  "
                  f"{'近战' if d['position'] == 'MELEE' else '远程'}"
                  f"  {d['char_id']}")
            print(f"  特性：{render_description(d['trait'] or '', {})}")
            print(f"  标签：{'、'.join(d['tags']) or '—'}")
            print("  阶段与范围：" + "  ".join(
                f"精{p['phase']}({p['range_id']}, ≤{p['max_level']})"
                for p in d["phases"]))
            print("  属性关键帧（等级帧）：")
            _table([a for a in d["attributes"] if a["kind"] == "phase"],
                   ["phase", "level", "hp", "atk", "def", "res", "cost",
                    "block_cnt", "base_attack_time"])
            print("  信赖帧：")
            _table([a for a in d["attributes"] if a["kind"] == "trust"],
                   ["level", "hp", "atk", "def", "res"])
            print("  潜能：")
            _table(d["potential"], ["rank", "description"])
            print("  天赋：")
            for t in d["talents"]:
                desc = render_description(t.get("description") or "",
                                          t.get("blackboard") or {})
                print(f"    组{t['group_index']}·候选{t['cand_index']} "
                      f"{t['name']}（精{t['unlock_phase']} "
                      f"{t['unlock_level']}级，潜能{t['required_potential_rank']}）")
                print(f"        {desc}")
                print(f"        黑板 {t['blackboard']}")
            if d["traits"]:
                print("  结构化特性：")
                for t in d["traits"]:
                    desc = render_description(t.get("override_description") or "",
                                              t.get("blackboard") or {})
                    print(f"    {desc}  黑板 {t['blackboard']}")
            print("  技能：")
            for s in d["skills"]:
                print(f"    槽{s['slot']} {s['name']}（{s['skill_id']}，"
                      f"{s['level_count']} 级，精{s['unlock_phase']} "
                      f"{s['unlock_level']}级解锁）")
            print("  模组：")
            for m in d["modules"]:
                flag = "特限/特勤" if m["is_special_equip"] else (
                    "无战斗数值" if not m["level_count"] else "专属")
                print(f"    {m['name']}（{m['module_id']}，{m['type']}，{flag}，"
                      f"{m['level_count']} 级，精{m['unlock_evolve_phase']} "
                      f"{m['unlock_level']}级解锁）")
            return 0

        if args.action == "skill":
            rows = search_skills(conn, args.key, limit=args.limit,
                                 blackboard_key=args.bb_key)
            _table(rows, ["skill_id", "name", "skill_type", "sp_type",
                          "sp_cost", "init_sp", "duration", "range_id"])
            return 0

        if args.action == "talent":
            rows = search_talents(conn, args.key, limit=args.limit,
                                  blackboard_key=args.bb_key)
            for r in rows:
                r["blackboard"] = (r["blackboard"] or "")[:60]
                r["description"] = (r["description"] or "").replace("\n", " ")[:40]
            _table(rows, ["operator", "name", "unlock_phase",
                          "required_potential_rank", "blackboard"])
            return 0

        if args.action == "levels":
            if not args.key:
                print("要给一个技能 id，例如 `db levels skchr_amiya_1`",
                      file=sys.stderr)
                return 2
            rows = skill_levels(conn, args.key)
            for r in rows:
                r["blackboard"] = (r["blackboard"] or "")[:48]
                r.pop("blackboard_raw", None)
                r.pop("description", None)
            _table(rows, ["level", "name", "sp_cost", "init_sp", "duration",
                          "skill_type", "duration_type", "blackboard"])
            return 0

        if args.action == "sql":
            if not args.key:
                print("要给一条 SQL，例如 `db sql \"select * from skill limit 3\"`",
                      file=sys.stderr)
                return 2
            rows = run_sql(conn, args.key, limit=args.limit)
            print(f"    {len(rows)} 行")
            if rows:
                _table(rows, list(rows[0]))
            return 0

        print(f"不认识的动作：{args.action}", file=sys.stderr)
        return 2
    finally:
        conn.close()


# ---------------------------------------------------------------- formula

def _emit_terms(terms: list[Any], indent: str = "     ") -> None:
    for t in terms:
        print(f"{indent}· {t.line()}")


def _parse_bb(spec: str) -> dict[str, Any]:
    """解析 `--bb`：`atk=0.5,sluggish=6.5` 或一段 JSON 对象。

    黑板负责填系数，而它的量纲**不统一**（同名键可能存的是别的量，
    如 `attack@sluggish` 存的是持续秒数而不是减速幅度），所以这里只做
    「数字转数字、其余原样当字符串」，不做任何推断。见 docs/formula-units.md。
    """
    s = (spec or "").strip()
    if not s:
        return {}
    if s.startswith("{"):
        try:
            got = json.loads(s)
        except ValueError as exc:
            raise ValueError(f"--bb 不是合法 JSON：{exc}") from exc
        if not isinstance(got, dict):
            raise ValueError("--bb 的 JSON 必须是一个对象")
        return got
    out: dict[str, Any] = {}
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"--bb 片段「{part}」缺 `=`，应写成 键=值")
        k, v = part.split("=", 1)
        v = v.strip()
        val: Any = v
        try:
            val = int(v)
        except ValueError:
            try:
                val = float(v)
            except ValueError:
                val = v
        out[k.strip()] = val
    return out


def _resolve_skill(conn: sqlite3.Connection, keyword: str) -> tuple[str, str]:
    """技能名或 skill_id → (skill_id, 显示名)。

    先按 id 精确试（`db skill` 只按名字搜，`db skill skchr_wang_1` 会空手而归，
    这里把那条路补上）；命中多个候选时**报错列出**，不替用户挑一个。
    """
    rows = skill_levels(conn, keyword)
    if rows:
        return keyword, f"{rows[0]['name']}（{keyword}）"
    hits = search_skills(conn, keyword, limit=20)
    if not hits:
        raise DatabaseMissing(f"库里没有技能 {keyword!r}")
    ids = list(dict.fromkeys(h["skill_id"] for h in hits))
    if len(ids) > 1:
        names = "、".join(f"{h['name']}（{h['skill_id']}）" for h in hits[:8])
        raise DatabaseMissing(
            f"{keyword!r} 命中 {len(ids)} 个技能，请用 skill_id 指定：{names}")
    return ids[0], f"{hits[0]['name']}（{ids[0]}）"


def _print_operator_scan(rep: dict[str, Any]) -> None:
    print("干员语料编译覆盖")
    print(f"    总条数 {rep['total']:,}   已编译 {rep['parsed']:,}   "
          f"覆盖率 {rep['ratio'] * 100:.1f}%   公式项 {rep['terms']:,}")
    print("    分来源：")
    for k, v in rep["by_source"].items():
        pct = v["parsed"] / v["total"] * 100 if v["total"] else 0.0
        print(f"        {k:<14} {v['parsed']:>7,}/{v['total']:<7,}{pct:>6.1f}%")
    if rep["unmatched"]:
        print(f"    未命中的高频残句（{len(rep['unmatched'])} 条）：")
        for skel, n in rep["unmatched"]:
            print(f"        {n:>4}×  {skel}")


def _print_enemy_scan(rep: dict[str, Any]) -> None:
    total, hit = rep["rows"], rep["hit_rows"]
    print("敌人语料编译覆盖")
    print(f"    总条数 {total:,}   已编译 {hit:,}   "
          f"覆盖率 {hit / total * 100 if total else 0.0:.1f}%")
    print("    分来源：")
    for k, v in rep["by_source"].items():
        pct = v["hit"] / v["total"] * 100 if v["total"] else 0.0
        print(f"        {k:<14} {v['hit']:>7,}/{v['total']:<7,}{pct:>6.1f}%")
    if rep["top_rules"]:
        print("    命中最多的规则（前几条）：")
        for name, n in rep["top_rules"]:
            print(f"        {n:>5}×  {name}")


def _formula_text(args: argparse.Namespace, text: str,
                  bb: dict[str, Any]) -> int:
    """任意文本 → 公式项。不查库，纯函数。"""
    from . import formula as F

    if args.enemy:
        from .enemy_formula import (RULES_ENEMY, detemplate, formulas_enemy,
                                    parse_enemy)
        flat = detemplate(text)
        terms = parse_enemy(text, bb or None)
        fx = formulas_enemy(text, bb or None)
        note = (f"敌人规则 {len(RULES_ENEMY)} 条"
                "，含 wiki 模板展开与带变量的算式")
    else:
        flat = F.normalize(text)[0]
        terms = F.parse(text, bb or None)
        fx = F.formulas(terms)
        note = f"干员规则 {len(F.RULES)} 条"

    if args.json:
        print(json.dumps({
            "mode": "text",
            "rules": "enemy" if args.enemy else "operator",
            "text": text, "flat": flat, "blackboard": bb,
            "terms": [t.to_dict() for t in terms],
            "formulas": fx,
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"文本 → 公式项（{note}）")
    print(f"  原文：{text}")
    if flat != text:
        print(f"  洗净：{flat}")
    if bb:
        print(f"  黑板：{bb}")
    if not terms:
        print("     （未编译出公式项）")
    _emit_terms(terms)
    print(f"  {len(terms)} 个公式项")
    if fx:
        print("  表达式：")
        for k, v in fx.items():
            print(f"     {k}: {v}")
    return 0


def cmd_formula(args: argparse.Namespace) -> int:
    """正文 → 公式项。三种用法：任意文本 / 库内一个干员或技能 / 扫全库。

    这是**干员侧**的入口，与 `enemydb formula`（敌人侧）对称；`--enemy`
    可临时改用敌人规则编译任意文本。只做识别与结构化，**不做数值推断**——
    带变量的算式只保留结构（`amount` 为空），谁给它算出个值就是错的。
    详见 docs/formula-maintenance.md 与 docs/enemy-formula.md。
    """
    from . import formula as F

    path = Path(args.path) if args.path else None
    try:
        bb = _parse_bb(args.bb)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.scan:
        if args.enemy:
            from .db import DEFAULT_ENEMY_DB_PATH
            from .enemy_formula import enemy_scan
            rep = enemy_scan(path or DEFAULT_ENEMY_DB_PATH, top=args.top)
            if args.json:
                print(json.dumps(rep, ensure_ascii=False, indent=2))
                return 0
            _print_enemy_scan(rep)
            return 0
        rep = F.scan(path or DEFAULT_DB_PATH, top=args.top)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
            return 0
        _print_operator_scan(rep)
        return 0

    if args.char and args.skill:
        print("--char 与 --skill 只能给一个", file=sys.stderr)
        return 2

    if not (args.char or args.skill):
        text = (args.text or "").strip()
        if not text:
            print('要给一段正文，例如 `formula "攻击力+50%，攻击速度+30"`；'
                  "或用 --char / --skill / --scan", file=sys.stderr)
            return 2
        return _formula_text(args, text, bb)

    db_path = path or DEFAULT_DB_PATH
    conn = connect(db_path)
    try:
        if args.char:
            d = char_detail(conn, args.char)     # 撞名会列出候选并报错
            key, label = d["char_id"], f"{d['name']}（{d['char_id']}）"
        else:
            key, label = _resolve_skill(conn, args.skill)
    finally:
        conn.close()

    rows = F.describe_row(db_path, key)
    if args.json:
        print(json.dumps({
            "mode": "char" if args.char else "skill",
            "key": key, "name": label,
            "sections": [{**s, "terms": [t.to_dict() for t in s["terms"]]}
                         for s in rows],
        }, ensure_ascii=False, indent=2))
        return 0

    total = sum(len(s["terms"]) for s in rows)
    print(f"{label}")
    print(f"{len(rows)} 段正文，编译出 {total} 个公式项\n")
    for s in rows:
        head = str(s["kind"])
        if s.get("id"):
            head += f"  {s['id']}"
        if s.get("level") is not None:
            head += f"  L{s['level']}"
        if s.get("name"):
            head += f"  {s['name']}"
        print(f"── {head}")
        print(f"   {s['text']}")
        if not s["terms"]:
            print("     （未编译出公式项）")
        _emit_terms(s["terms"])
        print()
    return 0


# ---------------------------------------------------------------- 地图机制

def cmd_activity(args: argparse.Namespace) -> int:
    """活动机制完整性盘点。

    每个活动都会新引入一批装置、敌人黑板键、runes 键。这个命令把该活动**全部**
    承载机制的实体列出来，逐个标出：已实现 / 待实现 / 不需要 / **未登记**。

    判据在 `ak_tactic.activity` 的三张登记表里；任何既没实现、也没登记的东西
    都会被判 UNKNOWN。派生的用途是"逐活动走一遍、做完整了再进下一个"——
    先跑这里看还剩什么，做完再把登记表的状态改掉。

    退出码 1 表示有未登记项或活动盘不到；待实现项**不影响退出码**（它们是待办，
    不是失败——把没做的标成已做才是失败）。
    """
    import json as _json

    from .activity import UNKNOWN, audit_activity

    act = args.activity or "act31side"
    rep = audit_activity(act, with_enemies=not args.no_enemies)

    if getattr(args, "json", False):
        print(_json.dumps({
            "activity": rep.activity, "stages": rep.stages,
            "devices": rep.devices, "runes": rep.runes, "enemies": rep.enemies,
            "enemy_blackboards": sorted(rep.enemy_bb),
            "todo": [e.to_dict() for e in rep.todo],
            "unknown": [{"kind": k, "key": v} for k, v in rep.unknown],
        }, ensure_ascii=False, indent=2))
        return 1 if rep.unknown or not rep.stages else 0

    if not rep.stages:
        print(f"盘不到活动 {act} 的关卡——检查 data/gamedata 下有没有这个目录")
        return 1

    print(rep.summary())
    print()
    print("── 装置")
    for k, n in rep.devices.items():
        st = next((e for e in rep._entries() if e.key == k), None)
        print(f"  {k:<20} ×{n:<5} {st.status if st else UNKNOWN:<9} "
              f"{st.name if st else ''}")
    print("── runes")
    for k, n in rep.runes.items():
        st = next((e for e in rep._entries() if e.key == k), None)
        print(f"  {k:<28} ×{n:<5} {st.status if st else UNKNOWN:<9} "
              f"{st.name if st else ''}")
    if rep.enemy_bb:
        print(f"── 敌人黑板机制（{len(rep.enemy_bb)} 类）")
        for p in sorted(rep.enemy_bb):
            st = next((e for e in rep._entries() if e.key == p), None)
            n = len(rep.enemy_bb[p])
            print(f"  {p:<24} {n} 只  {st.status if st else UNKNOWN:<9} "
                  f"{st.name if st else ''}")
    return 1 if rep.unknown else 0


def cmd_mechanics(args: argparse.Namespace) -> int:
    """地图机制：取术语表／关卡机制文本，并编译成公式项。

    三条来源在输出里**分别标明**，不混为一谈：

    * 全局术语表 —— prts.wiki「特殊机制」页（每个活动新引入的机制都登记在这）
    * 单关实数   —— 关卡页的「特殊地形效果」「关卡描述」「情报」字段
    * gamedata   —— 关卡 JSON 的 ``runes[].blackboard``（数值住 `value`）

    编译走 `ak_tactic.mechanics.parse_mechanic`，与干员/敌人两层同一套规则扫描。
    """
    import json as _json

    from .mechanics import (STAGE_FIELDS, fetch_glossary, parse_mechanic,
                            scan_glossary, stage_mechanics)

    as_json = bool(getattr(args, "json", False))

    if getattr(args, "stage", ""):
        sm = stage_mechanics(args.stage)
        terms = parse_mechanic(sm.plain())
        if as_json:
            print(_json.dumps({
                "title": sm.title, "fields": sm.texts, "refs": list(sm.refs),
                "terms": [t.to_dict() for t in terms],
            }, ensure_ascii=False, indent=2))
            return 0
        if not sm.fields:
            print(f"{sm.title}：该页没有机制字段（找的是 "
                  f"{'、'.join(STAGE_FIELDS)}）")
            return 1
        print(f"── {sm.title}（关卡页机制字段）")
        for k, v in sm.texts.items():
            print(f"\n[{k}]\n  {v}")
        if sm.refs:
            print(f"\n引用到的机制：{'、'.join(sm.refs)}")
        print(f"\n编译出 {len(terms)} 项：")
        _emit_terms(terms)
        return 0

    ms = fetch_glossary()
    if getattr(args, "scan", False):
        r = scan_glossary(ms)
        if as_json:
            print(_json.dumps({k: v for k, v in r.items() if k != "samples"},
                              ensure_ascii=False, indent=2))
            return 0
        print(f"术语表 {r['total']} 条，编译出公式项的 {r['hit']} 条"
              f" = {r['rate'] * 100:.1f}%")
        for k, v in r["sections"].items():
            print(f"  {k:<16} {v['hit']:>2}/{v['total']:<2}"
                  f" = {v['hit'] / v['total'] * 100:5.1f}%")
        top = int(getattr(args, "top", 25) or 25)
        print(f"\n未命中的高频残句（前 {top}）：")
        for k, n in r["residual"][:top]:
            print(f"  ×{n}  {r['samples'][k]}  ::  {k[:64]}")
        return 0

    want = (getattr(args, "name", "") or "").strip()
    picked = [m for m in ms if not want or want in m.name]
    if not picked:
        print(f"术语表里没有匹配「{want}」的机制。")
        return 1
    if as_json:
        print(_json.dumps([{
            "name": m.name, "section": m.section, "origin": m.origin,
            "text": m.text, "note": m.note_text,
            "terms": [t.to_dict() for t in parse_mechanic(m.text)],
        } for m in picked], ensure_ascii=False, indent=2))
        return 0
    for m in picked:
        terms = parse_mechanic(m.text)
        print(f"── {m.name}　[{m.section}]　({len(terms)} 项)")
        print(f"   {m.text[:400]}")
        if m.note_text:
            print(f"   ※ {m.note_text[:200]}")
        _emit_terms(terms)
        print()
    return 0


# ---------------------------------------------------------------- tui

def cmd_tui(args: argparse.Namespace) -> int:
    """终端界面。

    `textual` **在这个函数里才被导入**——它是本项目唯一的重依赖，
    不能因为没装它就让 `db` / `formula` / `verify` 一起跑不起来。
    （守卫见 `tools/check_tui.py`：它真的去断言"跑别的子命令不会导入 textual"。）
    """
    try:
        from .tui.app import run
    except ImportError as exc:                       # pragma: no cover
        print("终端界面需要 textual（本项目唯一的重依赖）：", file=sys.stderr)
        print("    pip install textual", file=sys.stderr)
        print(f"  导入失败：{exc}", file=sys.stderr)
        return 2
    return run(skip_login=args.no_login, stage=args.stage, squad=args.squad)


# ---------------------------------------------------------------- cache

def cmd_cache(args: argparse.Namespace) -> int:
    c = default_client()
    if args.clear:
        n = c.cache.clear()
        print(f"已清空 {n} 个缓存文件：{c.cache.root}")
        return 0
    if args.drop_ranges:
        p = RangeRegistry(client=c).index_path
        if p.exists():
            p.unlink()
            print(f"已删除攻击范围索引：{p}")
        else:
            print(f"攻击范围索引本来就不存在：{p}")
        return 0
    if args.clear_gamedata:
        src = GameDataSource()
        n, size = src.clear_cache()
        print(f"已删除 {n} 个 gamedata 缓存文件，释放 {size / 1048576:.1f} MB：{src.cache_dir}")
        return 0

    files = list(c.cache.root.glob("*.json")) if c.cache.root.exists() else []
    total = sum(f.stat().st_size for f in files)
    print(f"prts 缓存目录：{c.cache.root}")
    print(f"  文件数：{len(files)}")
    print(f"  占用：  {total / 1024:.1f} KB")
    print(f"  有效期：{c.cache.ttl // 86400} 天")
    idx = RangeRegistry(client=c).index_path
    print(f"攻击范围索引：{idx}（{'存在' if idx.exists() else '不存在'}）")

    gsrc = GameDataSource()
    gfiles = gsrc.cached_files()
    print(f"\ngamedata 缓存目录：{gsrc.cache_dir}")
    print(f"  文件数：{len(gfiles)}")
    print(f"  占用：  {gsrc.cache_size() / 1048576:.1f} MB")
    for f in gfiles:
        rel = f.relative_to(gsrc.cache_dir)
        print(f"    {f.stat().st_size / 1024:>10.1f} KB  {rel}")
    print(f"  （可用 cache --clear-gamedata 整体删除）")
    print(f"\n本次进程统计：{c.stats}")
    return 0


# ----------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ak_tactic",
        description="明日方舟数据工具——干员数据取自 prts.wiki，"
                    "关卡地图与敌人的数值取自游戏本体 gamedata")
    p.add_argument("--no-cache", action="store_true", help="跳过缓存，强制重新取数")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("get", help="取一个干员的数据")
    g.add_argument("name", help="干员名，如 能天使")
    g.add_argument("--json", action="store_true", help="输出 JSON")
    g.add_argument("--full", action="store_true",
                   help="展开全部技能等级（默认只留 7 级与专精三）")
    g.add_argument("--range", action="store_true", help="同时打印攻击范围网格")
    g.set_defaults(func=cmd_get)

    l = sub.add_parser("list", help="列干员")
    l.add_argument("--profession", default="", help="按职业筛，如 狙击")
    l.add_argument("--rarity", type=int, default=None, help="按星级筛，如 6")
    l.add_argument("--limit", type=int, default=1000)
    l.add_argument("--raw-names", action="store_true", help="改为列分类里的页面名")
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_list)

    r = sub.add_parser("range", help="看攻击范围")
    r.add_argument("codes", nargs="*", help="范围代号，如 3-3；不给则用本地索引")
    r.add_argument("--operator", "-o", default="", help="按干员名取它的三个精英阶段范围")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_range)

    s = sub.add_parser("stage", help="取关卡：地图、出怪路线、波次时间轴")
    s.add_argument("level_id", nargs="?", default="",
                   help="关卡号或 levelId，如 SR-EX-8、1-7、act54side_ex08")
    s.add_argument("--search", default="",
                   help="按关卡号/区域/levelId 模糊找关卡（不取数据）")
    s.add_argument("--chapter", default="", help="关卡所属章节子目录，默认从 id 前缀推断")
    s.add_argument("--map", action="store_true", help="只看地图，不加载敌人数据")
    s.add_argument("--no-routes", action="store_true", help="地图上不叠路线")
    s.add_argument("--timeline", action="store_true", help="打印完整出怪时间轴")
    s.add_argument("--limit", type=int, default=25, help="时间轴默认只显示前 N 条")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_stage)

    e = sub.add_parser("enemy", help="取敌人的图鉴与数值")
    e.add_argument("enemy_id", nargs="?", default="", help="敌人 id，如 enemy_1007_slime_2")
    e.add_argument("--level", type=int, default=None, help="档位，默认取最高档")
    e.add_argument("--search", default="", help="按中文名搜索，如 --search 源石虫")
    e.add_argument("--limit", type=int, default=30)
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=cmd_enemy)

    st = sub.add_parser("stats", help="算干员属性：等级 + 信赖 + 潜能 + 模组")
    st.add_argument("char_id", nargs="?", default="",
                    help="干员 id 或中文名，如 char_002_amiya / 阿米娅")
    st.add_argument("--elite", type=int, default=0, help="精英阶段 0/1/2")
    st.add_argument("--level", type=int, default=1, help="阶段内等级，从 1 开始")
    st.add_argument("--trust", type=float, default=0.0,
                    help="信赖 0–100 内部标度（= 游戏显示信赖 ÷ 2；100 即满信赖 200%%）")
    st.add_argument("--potential", type=int, default=1, help="潜能 1–6")
    st.add_argument("--module", default="", help="模组 id，如 uniequip_002_amiya")
    st.add_argument("--module-level", type=int, default=0, help="模组等级 1/2/3")
    st.add_argument("--modules", action="store_true", help="只列出该干员的模组")
    st.add_argument("--rounding", default="round",
                    choices=["floor", "round", "ceil", "none"],
                    help="插值取整方式，默认 round（四舍五入，2026-09-17 实测定案）")
    st.add_argument("--search", default="", help="按 id 或中文名找干员（不计算）")
    st.add_argument("--limit", type=int, default=20)
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_stats)

    sk = sub.add_parser("skills", help="看干员技能：倍率、技力回转、持续、范围")
    sk.add_argument("char_id", nargs="?", default="",
                    help="干员 id 或中文名，如 char_002_amiya / 阿米娅")
    sk.add_argument("--level", type=int, default=7, help="技能等级 1–7")
    sk.add_argument("--mastery", type=int, default=0, help="专精等级 0–3")
    sk.add_argument("--all", action="store_true", help="展开全部十个等级")
    sk.add_argument("--elite", type=int, default=2, help="算攻击力用的精英阶段")
    sk.add_argument("--trust", type=float, default=0.0,
                    help="信赖 0–100 内部标度（= 游戏显示信赖 ÷ 2；100 即满信赖 200%%）")
    sk.add_argument("--potential", type=int, default=1, help="潜能 1–6")
    sk.add_argument("--no-atk", action="store_true", help="不显示绝对伤害")
    sk.add_argument("--coverage", action="store_true",
                    help="改为报告黑板键的归类覆盖率")
    sk.add_argument("--search", default="", help="按 id 或中文名找干员（只列技能名）")
    sk.add_argument("--limit", type=int, default=20)
    sk.add_argument("--json", action="store_true")
    sk.set_defaults(func=cmd_skills)

    tl = sub.add_parser("talents", help="看干员天赋：档位、黑板、已建模的机制")
    tl.add_argument("char_id", nargs="?", default="",
                    help="干员 id 或中文名，如 char_1046_sbell2 / 圣聆初雪")
    tl.add_argument("--elite", type=int, default=2, help="精英阶段 0–2")
    tl.add_argument("--level", type=int, default=1, help="阶段内等级")
    tl.add_argument("--potential", type=int, default=1, help="潜能 1–6")
    tl.add_argument("--all-candidates", action="store_true",
                    help="把这个干员天赋的**全部档位**列出来（含未解锁）")
    tl.add_argument("--coverage", action="store_true", help="报告天赋黑板的规模")
    tl.add_argument("--json", action="store_true")
    tl.set_defaults(func=cmd_talents)

    d = sub.add_parser("db", help="干员库（gamedata）：建库与查询")
    d.add_argument("action", nargs="?", default="info",
                   choices=["build", "info", "char", "find", "skill", "talent",
                            "levels", "sql", "schema", "tiles", "tile-fetch",
                            "stages", "stage-fetch", "stage-prune"],
                   help="build 重建库 / info 版本与行数 / char 干员详情 / "
                        "find 找干员 / skill 搜技能 / talent 搜天赋 / "
                        "levels 一个技能的全等级 / sql 只读查询 / schema 表说明 / "
                        "tiles 查地块字典 / tile-fetch 重取地块字典 / "
                        "stages 查关卡索引 / stage-fetch 取关卡索引（要联网）/ "
                        "stage-prune 清掉不属于这五类的 zone 与关卡（不联网）")
    d.add_argument("key", nargs="?", default="",
                   help="动作的对象：干员 id 或名字 / 关键词 / 技能 id / SQL /"
                        " 地块关键词或 tileKey / 关卡关键词")
    d.add_argument("--key", dest="bb_key", default="",
                   help="按黑板键过滤，如 atk_scale / sluggish / ammo")
    d.add_argument("--limit", type=int, default=30)
    d.add_argument("--path", default="", help="库文件路径（默认 data/akdb.sqlite）")
    d.add_argument("--include-tokens", action="store_true",
                   help="find 时把召唤物与装置也列出来")
    d.add_argument("--verbose", action="store_true", help="build 时打印进度")
    d.add_argument("--force", action="store_true",
                   help="tile-fetch / stage-fetch 时忽略缓存强制重取")
    d.add_argument("--difficulty", default="",
                   help="stages 时按难度筛：NORMAL / FOUR_STAR / RUNE / SIX_STAR")
    d.add_argument("--dry-run", action="store_true",
                   help="只报预估时间与体积，不真的取数、不写库")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_db)

    fm = sub.add_parser(
        "formula", help="正文 → 公式项：把中文描述编译成结构化公式")
    fm.add_argument("text", nargs="?", default="",
                    help="要编译的正文（任意文本）；也可改用 "
                         "--char / --skill / --scan")
    fm.add_argument("--char", default="",
                    help="编译一个干员的全部天赋（名字或 char_id）")
    fm.add_argument("--skill", default="",
                    help="编译一个技能的全部等级（技能名或 skill_id）")
    fm.add_argument("--scan", action="store_true",
                    help="统计全库覆盖率与未命中的高频残句")
    fm.add_argument("--enemy", action="store_true",
                    help="改用敌人规则（含 wiki 模板展开与带变量的算式）；"
                         "配 --scan 时统计敌人库")
    fm.add_argument("--bb", default="",
                    help='黑板系数，如 "atk=0.5,sluggish=6.5"（也接受 JSON 对象）')
    fm.add_argument("--top", type=int, default=25,
                    help="scan 时列几条高频残句/规则（默认 25）")
    fm.add_argument("--path", default="",
                    help="库文件路径（默认 data/akdb.sqlite；"
                         "--enemy --scan 时是 data/enemydb.sqlite）")
    fm.add_argument("--json", action="store_true")
    fm.set_defaults(func=cmd_formula)

    mc = sub.add_parser(
        "mechanics",
        help="地图机制：prts.wiki 特殊机制表 + 关卡页机制字段 → 公式项")
    mc.add_argument("name", nargs="?", default="",
                    help="机制名（可只给一部分做子串匹配）；留空则列全表")
    mc.add_argument("--stage", default="",
                    help='改看某个关卡页的机制字段，如 "HS-8 种因"')
    mc.add_argument("--scan", action="store_true",
                    help="统计术语表覆盖率与未命中的高频残句")
    mc.add_argument("--top", type=int, default=25,
                    help="scan 时列几条残句（默认 25）")
    mc.add_argument("--json", action="store_true")
    mc.set_defaults(func=cmd_mechanics)

    ac = sub.add_parser(
        "activity",
        help="活动机制完整性盘点：逐个列出装置/敌人黑板/runes 的实现状态")
    ac.add_argument("activity", nargs="?", default="act31side",
                    help="活动目录名（默认 act31side = 怀黍离）")
    ac.add_argument("--no-enemies", action="store_true",
                    help="跳过敌人黑板（只盘装置与 runes，快很多）")
    ac.add_argument("--json", action="store_true")
    ac.set_defaults(func=cmd_activity)

    vf = sub.add_parser(
        "verify", help="验证一份打法：能不能三星，不能又是为什么")
    vf.add_argument("stage", nargs="?", default="",
                    help="关卡号（如 main_01-07 / act54side_06）；"
                         "给 --plan 时可省，关卡号以打法文件里的为准")
    vf.add_argument("--plan", default="", help="打法 JSON 文件")
    vf.add_argument("--team", default="",
                    help='临时打法，如 "圣聆初雪:5,4:Right:3; 德克萨斯:6,3:Right:0"'
                         "（干员之间用 `;` 分隔，逗号留给坐标）")
    vf.add_argument("--box", default="", help="名册 JSON（MAA OperBox 或森空岛名册）")
    vf.add_argument("--save-plan", default="", help="把临时打法存成 JSON 再跑")
    vf.add_argument("--json", action="store_true")
    vf.add_argument("--no-range-table", action="store_true",
                    help="不给模拟器接真实攻击范围（退回 3 格近似，用于回归对照）")
    vf.add_argument("--verbose", action="store_true")
    vf.add_argument("--diagram", action="store_true",
                    help="附上地图摆位图（MAA 坐标，原点左上）")
    vf.add_argument("--timeline", action="store_true",
                    help="附上时间轴表格（出怪/落地/开技能/漏怪/到终点）")
    vf.add_argument("--report", default="",
                    help="把摆位图+热度图+时间轴+战报写成一份完整报告文件")
    vf.add_argument("--heat-metric", default="dwell",
                    choices=("dwell", "routes"),
                    help="路线热度图的度量：dwell=敌人·秒 / routes=路线条数")
    vf.set_defaults(func=cmd_verify)

    se = sub.add_parser(
        "search", help="搜索一套能三星的阵容（落位/朝向/顺序都由搜索决定）")
    se.add_argument("stage", help="关卡号（如 main_01-07 / act54side_06）")
    se.add_argument("--box", default="", help="名册 JSON（必给）")
    se.add_argument("--team", default="",
                    help="限定搜索的干员，用 `;` 或 `,` 分隔；"
                         "不给则取名册前 --top 名")
    se.add_argument("--top", type=int, default=8,
                    help="未指定 --team 时取名册前几名（默认 8）")
    se.add_argument("--max-ops", type=int, default=4, help="最多上几个人")
    se.add_argument("--beam", type=int, default=5, help="每层保留几个状态")
    se.add_argument("--per-op", type=int, default=6,
                    help="每个干员留几个候选落位")
    se.add_argument("--save-plan", default="", help="找到的打法写到哪里")
    se.add_argument("--json", action="store_true")
    se.add_argument("--no-range-table", action="store_true",
                    help="不给模拟器接真实攻击范围（退回 3 格近似）")
    se.set_defaults(func=cmd_search)

    tm = sub.add_parser(
        "team", help="按角色出名册建议：回费先锋 + 骗伤处决者 + 低费位 + 练度补齐")
    tm.add_argument("--box", default="", help="名册 JSON（必给）")
    tm.add_argument("--size", type=int, default=8, help="建议几人（默认 8）")
    tm.add_argument("--stage", default="",
                    help="关卡（如 main_01-07 / HS-8）。给了才判费用环境——"
                         "初始费用不够开局下一个人时，会加一个低费位")
    tm.add_argument("--no-charger", action="store_true",
                    help="只要一个回费位，不再搭第二个先锋")
    tm.add_argument("--db", default="", help="干员库路径（默认 data/akdb.sqlite）")
    tm.add_argument("--json", action="store_true")
    tm.set_defaults(func=cmd_team)

    e = sub.add_parser("enemydb", help="敌人库（prts.wiki）：建库与查询")
    e.add_argument("action", nargs="?", default="info",
                   choices=["build", "info", "find", "show", "formula",
                            "sql", "schema"],
                   help="build 重建库（要联网，首次约 51s）/ info 版本与行数 / "
                        "find 找敌人 / show 敌人详情 / "
                        "formula 把正文编译成公式项 / sql 只读查询 / schema 表说明")
    e.add_argument("key", nargs="?", default="",
                   help="动作的对象：页名或名字 / 关键词 / SQL")
    e.add_argument("--grade", default="", help="find 时按地位级别过滤：普通/精英/领袖")
    e.add_argument("--limit", type=int, default=30)
    e.add_argument("--pages", type=int, default=None,
                   help="build 时只抓前 N 页，供试跑用")
    e.add_argument("--path", default="",
                   help="库文件路径（默认 data/enemydb.sqlite）")
    e.add_argument("--verbose", action="store_true", help="build 时打印进度")
    e.add_argument("--json", action="store_true")
    e.set_defaults(func=cmd_enemy_db)

    tu = sub.add_parser("tui", help="终端界面：选关卡 → 指定编队 → 解算 → 导出")
    tu.add_argument("--no-login", action="store_true",
                    help="跳过 [0] 登录屏，直接进选关卡。"
                         "**测试全新启动的流程时用这个**——登录只决定名册要不要刷新，"
                         "不是流程的闸门")
    tu.add_argument("--stage", default="",
                    help="预填关卡（如 SR-EX-8），给了就跳过选关卡那一步")
    tu.add_argument("--squad", default="",
                    help="预填编队，逗号分隔（如 赤刃明霄陈,圣聆初雪）")
    tu.set_defaults(func=cmd_tui)

    c = sub.add_parser("cache", help="缓存管理")
    c.add_argument("--clear", action="store_true", help="清空 prts HTTP 缓存")
    c.add_argument("--drop-ranges", action="store_true", help="删除攻击范围索引")
    c.add_argument("--clear-gamedata", action="store_true",
                   help="删除 gamedata 缓存（关卡与敌人数据，约 17 MB）")
    c.set_defaults(func=cmd_cache)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
    except (PrtsError, GamedataError, OperatorError, DatabaseMissing) as e:
        print(f"上游出错：{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
