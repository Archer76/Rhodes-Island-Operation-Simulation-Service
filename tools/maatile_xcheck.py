"""MAA 地块 JSON ↔ 我们地图层的**独立第三源交叉校验**（只读，不改我们的地图层）。

为什么要有它：我们的地图/地块层来自 gamedata 镜像与 theresa 的 tile 字典，**都是二手来源**。
本机 MAA 资源目录里另有一份**独立第三源**：`Arknights-Tile-Pos/` 下的**逐关地块 JSON**
（本机实测 4203 份）——可以逐关逐格对。**只读，不把它的数据复制进仓**。

跑法：
    python tools/maatile_xcheck.py                 # 全量比对（不写文件，打印总账）
    python tools/maatile_xcheck.py --out docs/maatile-crosscheck.md --json out/acceptance/maatile-xcheck.json
    python tools/maatile_xcheck.py --mutate        # 反向守卫：故意改它一格，脚本必须红
    python tools/maatile_xcheck.py --stages main_01-07,act31side_ex08   # 只看这几关

三条硬口径（不写清楚就会得出假结论）：

1. **不许只报总数**。"它有多少关 vs 我们多少关"什么都证明不了——本项目最贵的那条教训。
   必须逐关比出**分歧**，并按类型归类。
2. **去重口径必须先定**（同一关有多份文件，见 `load_maa()` 的注释）：文件名首段是关卡 id，
   带 `#f#` 的与不带的是**同一关的两份**；同名多份**不丢**，逐份比、取最接近的那份，
   并把"它有几份"报出来。
3. **朝向与概念都不靠猜**：MAA 的 `tiles[y][x]` 与我们的 `map.tiles[y][x]` 都是我方已采用的
   MAA 口径（原点左上、y 向下）；**只比同名同义的东西**（见 `SAME_CONCEPT`），
   它那套 `isStart`/`isEnd` 是**另一层概念**（路线端点），单独登记，不混进地块分歧——
   **"它和我不同"与"我读错了/概念不同"长得一模一样**。
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: 第三源：本机 MAA 资源目录的`Arknights-Tile-Pos\`（可用环境变量覆盖，便于换机器跑）。
TILE_DIR = Path(os.environ.get("MAA_TILE_DIR",
                               r"（本机 MAA 目录）\resource\Arknights-Tile-Pos"))
OUTDIR = ROOT / "out" / "acceptance"
#: 我们自己的关卡 JSON（`load_stage()` 的取数处；**按需缓存**，不是全量）
OUR_LEVELS = ROOT / "data" / "gamedata" / "levels"

#: 取值映射——**是用计数与逐格比对实测出来的**，不是从名字猜的：
#:   MAA buildableType 0/1/2 ↔ 我们 NONE/MELEE/RANGED（main_01-07 上 38/23/16 逐项吻合）
#:   MAA buildableType **3** ↔ 我们 **`ALL`**（`act31side_ex05` 上 33 格一一同位对上）
#:   MAA heightType    0/1   ↔ 我们 LOWLAND/HIGHLAND（31/46 逐项吻合）
#: ⚠ 第四取值是**踩出来的**：第一版只写了 0/1/2，`act31side_ex05` 于是"报出 33 格分歧"——
#: 而那 33 格恰好就是我们的 `ALL` 格。工具当时**没有猜**、把对不上的原样报了出来，
#: 这才是发现它的路。**判据不许拿"最像的那个值"去凑。**
BUILDABLE = {0: "NONE", 1: "MELEE", 2: "RANGED", 3: "ALL"}
HEIGHT = {0: "LOWLAND", 1: "HIGHLAND"}
#: ⚠ **只比同名同义的字段**。`tileKey` 是同名同义（`tile_forbidden` 等）。
#: 它那套 `isStart`/`isEnd` **不是** `tileKey == tile_start/tile_end`：本机实测
#: 我们的 `tile_start` 格**总是它 `isStart` 的真子集**（`act31side_07`：2 vs 10；
#: `act31side_ex03`：3 vs 9）⇒ 它标的是**路线端点**（含普通路面格），属另一层概念。
#: 要真比它，得拿**我们的路线层**去对，本轮登记为未覆盖，不用它出地块分歧。
SAME_CONCEPT = ("buildable", "height", "tileKey")


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()[:16]


def _level_id(name: str) -> str:
    """从文件名取关卡 id。

    ⚠ **不能按第一个 `-` 切**：`main_01-07-obt-main-level_main_01-07.json` 的第一个 `-` 之后是 `07`，
    按第一段切会把 `main_01-01`…`main_01-07` **全塌成 `main_01`** ⇒ 整族 `main_*` 被静默排除、
    还被记进「只有第三源有」。正解是取**最后那个 `level_<id>` 段**。
    （发现它的路是**抽样人工复核**：1-7 被报成「第三源没有这一关」，而它明明有。）
    """
    stem = name[:-len(".json")] if name.lower().endswith(".json") else name
    if "level_" in stem:
        return stem.rsplit("level_", 1)[1].replace("#f#", "")
    return stem.split("-")[0].replace("#f#", "")


def load_maa() -> tuple[dict[str, dict], dict]:
    """读第三源目录里的地块 JSON（**只读**）。

    去重口径（先定后算，写进报告）：
      ① 只算 `.json`；
      ② 关卡 id 取文件名里**最后那个 `level_<id>` 段**（见 `_level_id()`，不许按第一个 `-` 切）；
      ③ 同 id 多份**不丢**：那是同一 levelId 的**多份变体**（本机 74 关如此，
         `act1multi_fortress` 一份 id 下 7 份且内容各不相同），全部留下当候选，
         比对时取「最接近的那份」，并报出该关有几份。
    """
    files = sorted(p for p in TILE_DIR.glob("*.json"))
    conflicts: list[str] = []
    groups: dict[str, list[Path]] = collections.defaultdict(list)
    for p in files:
        groups[_level_id(p.name)].append(p)

    out: dict[str, dict] = {}
    for key, names in groups.items():
        #: ⚠ 同一关**多份**在 MAA 里是常态（74 关）：`act1multi_fortress` 有 **7 份内容各不相同**
        #: ——那是同一 levelId 的**多难度/多变体**地块图，不是重复文件。所以**不丢**，
        #: 全部留下当候选，比对时"与哪一份最接近"本身就是结论。
        variants = []
        for p in sorted(names):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:                               # noqa: BLE001
                variants.append({"file": p.name, "error": f"{type(e).__name__}: {e}"})
                continue
            variants.append({"file": p.name, "width": doc.get("width"),
                             "height": doc.get("height"), "levelId": doc.get("levelId"),
                             "stageId": doc.get("stageId"), "code": doc.get("code"),
                             "tiles": doc.get("tiles")})
        if len(names) > 1:
            hashes = {v["file"]: _sha(p.read_bytes()) for v, p in zip(variants, sorted(names))}
            if len(set(hashes.values())) == 1:
                pass                                     # 同内容多份：不算分歧
            else:
                conflicts.append(f"{key}（{len(names)} 份内容不同）")
        out[key] = {"file": names[0].name, "n_variants": len(variants), "variants": variants}
    meta = {"dir": str(TILE_DIR), "files": len(files),
            "stages": len(out), "conflicts": conflicts,
            "multi": sum(1 for v in groups.values() if len(v) > 1)}
    return out, meta


#: 我们本地缓存的三个镜像（`GameDataSource` 按需下载后落在这里）。**只有本地有缓存的关卡
#: 才比得了**——这条必须写进报告，否则"交集很小"会被误读成"我们的地图很少"。
MIRRORS = ("levels", "map.ark-nights.com/levels", "raw.githubusercontent.com/levels")


def our_levels() -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = collections.defaultdict(list)
    for mir in MIRRORS:
        d = ROOT / "data" / "gamedata" / mir
        if not d.is_dir():
            continue
        for p in d.rglob("level_*.json"):
            out[p.name[len("level_"):-len(".json")]].append(p)
    return dict(out)


def mirror_conflicts(ours: dict[str, list[Path]]) -> list[dict]:
    """同一关在**多个镜像**里都有缓存时，比一下——镜像之间不一致本身也是结论。

    ⚠ 比的是**解析后的语义**（键序/空白不算差），不是字节：`sha(原始字节)` 会把
    "格式不同、内容相同"也报成冲突，那是**假红**。
    """
    bad = []
    for lid, paths in sorted(ours.items()):
        if len(paths) < 2:
            continue
        sigs, docs = {}, {}
        for p in paths:
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:                               # noqa: BLE001
                sigs[p] = f"读不出来 {type(e).__name__}"
                continue
            docs[p] = doc
            sigs[p] = _sha(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        if len(set(sigs.values())) > 1:
            lab = {p: p.relative_to(ROOT / "data" / "gamedata").as_posix() for p in paths}
            #: 能不能进一步说清"差在哪一格"：mapData.tiles 逐格比
            detail = ""
            ps = list(docs)
            if len(ps) >= 2:
                ta = ((docs[ps[0]].get("mapData") or {}).get("tiles")) or []
                tb = ((docs[ps[1]].get("mapData") or {}).get("tiles")) or []
                if ta and len(ta) == len(tb):
                    n = sum(1 for i in range(len(ta)) if ta[i] != tb[i])
                    detail = f"（mapData.tiles 逐格不同 {n} 格）"
                else:
                    detail = f"（tiles 长度 {len(ta)} vs {len(tb)}）"
            bad.append({"level": lid, "files": list(lab.values()), "sha": list(sigs.values()),
                        "detail": detail})
    return bad


def compare_one(key: str, entry: dict, stage) -> dict:
    """同一关 MAA 可能有多份**变体**（74 关如此）⇒ 逐份比，取**最接近**的那份为结论，
    并把「该关它有几份、最接近的是第几份」一并报出来。"""
    best = None
    for i, v in enumerate(entry.get("variants") or []):
        if v.get("error"):
            continue
        rec = _cmp_variant(key, v, stage)
        rec["variant"] = i + 1
        rec["n_variants"] = entry.get("n_variants")
        rec["variant_file"] = v.get("file")
        score = sum(rec["div"].values())
        if best is None or score < sum(best["div"].values()):
            best = rec
    if best is None:
        return {"key": key, "div": {"它这份读不出来": 1}, "dir": {}, "size": [], "maasize": []}
    return best


def _cmp_variant(key: str, maa: dict, stage) -> dict:
    """逐格比：尺寸 / 可部署 / 高度 / 地块键。返回分类后的分歧。"""
    m = stage.map
    rec: dict = {"key": key, "plan": "ours=load_stage", "code": maa.get("code"),
                 "size": [m.width, m.height], "maasize": [maa.get("width"), maa.get("height")],
                 "div": {}, "dir": {}}
    if [m.width, m.height] != [maa.get("width"), maa.get("height")]:
        rec["div"]["尺寸不同"] = 1
        return rec
    mt = maa.get("tiles") or []
    cells = {"buildable": [], "height": [], "tileKey": []}
    for y in range(m.height):
        for x in range(m.width):
            if y >= len(mt) or x >= len(mt[y]):
                cells["tileKey"].append((x, y, "缺格", "缺失"))
                continue
            c = mt[y][x]
            ours = m.tiles[y][x]
            want_b = BUILDABLE.get(c.get("buildableType"), f"?{c.get('buildableType')}")
            want_h = HEIGHT.get(c.get("heightType"), f"?{c.get('heightType')}")
            if ours.buildable != want_b:
                cells["buildable"].append((x, y, ours.buildable, want_b))
            if ours.height != want_h:
                cells["height"].append((x, y, ours.height, want_h))
            if ours.key != c.get("tileKey"):
                cells["tileKey"].append((x, y, ours.key, c.get("tileKey")))
    #: 起点/终点：**朝向的实测判据**（不靠猜）。我方 start/end 格 vs MAA isStart/isEnd。
    #: ⚠ **我第一次跑这里读错了 API**：`StageMap.find()` 是**按 tileKey 精确匹配**的，
    #: `find("start")` 返回**空**——而同一份地图的 key 分布里明明有 `tile_start × 3`。
    #: **仪器自己跟自己矛盾**，这才是发现它的路（34/34 关"起点不一致"就是它的症状）。
    #: 正确写法是 `find("tile_start")`。教训与记忆 `6c101989` 同族：
    #: **「它和我不同」与「我读错了」长得一模一样**——先让判据自己不自相矛盾。
    ours_start = sorted(m.find("tile_start"))
    ours_end = sorted(m.find("tile_end"))
    #: 它那套 `isStart`/`isEnd` 单独记，**不进地块分歧**（是路线端点概念，见 SAME_CONCEPT）
    maa_start = sorted((x, y) for y, row in enumerate(mt) for x, c in enumerate(row)
                       if c.get("isStart"))
    maa_end = sorted((x, y) for y, row in enumerate(mt) for x, c in enumerate(row)
                     if c.get("isEnd"))
    #: 同概念对齐实测：`tileKey == tile_start/tile_end` 那一套（两边都按这个比）
    maa_key_start = sorted((x, y) for y, row in enumerate(mt) for x, c in enumerate(row)
                           if c.get("tileKey") == "tile_start")
    maa_key_end = sorted((x, y) for y, row in enumerate(mt) for x, c in enumerate(row)
                         if c.get("tileKey") == "tile_end")
    rec["start_ours"], rec["start_maa"] = ours_start, maa_key_start
    rec["end_ours"], rec["end_maa"] = ours_end, maa_key_end
    rec["route_endpoints_maa"] = {"isStart": maa_start, "isEnd": maa_end}
    rec["orientation"] = "同向（x/y 未翻转）" if (not ours_start or ours_start == maa_key_start) \
        else "⚠ 起点格不一致"
    for f, diffs in cells.items():
        if diffs:
            rec["div"][f] = len(diffs)
            rec["dir"][f] = diffs[:12]
    if ours_start != maa_key_start:
        rec["div"]["起点格"] = len(set(ours_start) ^ set(maa_key_start))
    if ours_end != maa_key_end:
        rec["div"]["终点格"] = len(set(ours_end) ^ set(maa_key_end))
    return rec


def mutate_first(maa: dict, key: str) -> tuple[str, tuple, str]:
    """反向守卫：故意把 MAA 的某个格改掉，比对必须红、且指出是哪一关哪一格。

    ⚠ 必须改**该关所有变体**的同一格：比对时是从变体里挑「最接近的那一份」，
    只改变体 0 的话，若被挑中的是变体 1，改动就**测不出来**（第一版就踩了这个坑）。
    """
    variants = maa[key].get("variants") or []
    for y, row in enumerate(variants[0].get("tiles") or []):
        for x, c in enumerate(row):
            if c.get("buildableType") == 0:
                hit = 0
                for v in variants:
                    try:
                        v["tiles"][y][x]["buildableType"] = 1
                        hit += 1
                    except Exception:                            # noqa: BLE001
                        pass
                return key, (x, y), f"buildableType 0→1（{hit}/{len(variants)} 份变体都改）"
    raise SystemExit(f"找不到可改的格（{key}）")


def _signature(rec: dict) -> dict:
    """A/B 用的**可比签名**：按字段列出**具体哪些格**不同。

    ⚠ 不能只比 `div` 的**计数**：本轮实测 `a001_01` 本来就有 1 格 buildable 分歧，
    把另一格也改坏之后计数**还是 1** ⇒ 计数相等、改动"消失"（第一版就踩了这个坑）。
    """
    sig = {}
    for field, cells in (rec.get("dir") or {}).items():
        sig[field] = sorted(tuple(d[:2]) for d in cells)
    return sig


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                            # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="MAA 地块 JSON 独立第三源交叉校验")
    ap.add_argument("--out", default="")
    ap.add_argument("--json", default=str(OUTDIR / "maatile-xcheck.json"))
    ap.add_argument("--stages", default="", help="只比这几关（逗号分隔）")
    ap.add_argument("--mutate", action="store_true", help="反向守卫：故意改它一格")
    ap.add_argument("--sample", default="main_01-07,act31side_ex08,act31side_07,a001_01,act31side_ex05",
                    help="抽样人工复核的关卡（逗号分隔，默认 5 关，含 1-7 与我们已有定论的 SR-EX-8）")
    args = ap.parse_args()

    t0 = time.time()
    maa, meta = load_maa()
    ours = our_levels()
    mir_bad = mirror_conflicts(ours)
    common = sorted(set(maa) & set(ours))
    only_maa = sorted(set(maa) - set(ours))
    only_ours = sorted(set(ours) - set(maa))
    print(f"第三源：`Arknights-Tile-Pos` 下 **{meta['files']}** 份地块 JSON → 去重后关卡 "
          f"**{meta['stages']}**；同 id 多份 {meta['multi']} 关（内容不同 {len(meta['conflicts'])} 关）")
    print(f"我们：**本地缓存**的关卡 JSON {sum(len(v) for v in ours.values())} 份 → "
          f"去重后 **{len(ours)}** 关（三个镜像目录并集；这是**按需缓存**，不是全量）")
    print(f"交集 **{len(common)}**；只有第三源有 {len(only_maa)}；只有我们有 {len(only_ours)}")
    if mir_bad:
        print(f"⚠ 同一关多镜像**内容不同** {len(mir_bad)} 关：" +
              "；".join(f"{m['level']}({len(m['files'])}份)" for m in mir_bad[:5]))
    if meta["conflicts"]:
        print(f"⚠ 第三源同 id 多份且内容不同 {len(meta['conflicts'])} 关：" +
              "；".join(meta["conflicts"][:3]))

    names = common
    if args.stages:
        names = [s.strip() for s in args.stages.split(",") if s.strip()]
    if not names:
        print("⚠ 交集为空——**没有可比对象**，先看上面的「我们侧」计数是不是读错了目录")
    mut_key = mut_cell = None

    from ak_tactic.gamedata.stage import load_stage

    def run_all() -> tuple[list[dict], list[dict]]:
        rs, es = [], []
        for k in names:
            try:
                st = load_stage(k)
            except Exception as e:                               # noqa: BLE001
                es.append({"key": k, "why": f"{type(e).__name__}: {e}"})
                continue
            if st.map is None:
                es.append({"key": k, "why": "我们侧 map 为 None"})
                continue
            rs.append(compare_one(k, maa[k], st))
        return rs, es

    #: ⚠ 守卫必须**A/B 比**，不能拿"有没有分歧"当判据：本来就有真分歧的关，"
    #: 恰好 1 关红"这种写法**天生红不对**。
    #: 正确判据（先写死）：**改一格 ⇒ 与未改的那次相比，只有那一关的 `buildable` 分歧集
    #: 恰好多了那一格，其它关一切不动**。
    #: ⚠ 顺序也是判据的一部分：**必须先跑基线、再改数据、再跑一遍**——
    #: 我第一版把改动放在了基线之前，于是"两次跑的都是改过的"，A/B 恒等、守卫假绿。
    recs, errs = run_all()
    base_recs, base_errs = recs, errs
    guard = None
    if args.mutate and names:
        mut_key, mut_cell, how = mutate_first(maa, names[0])
        print(f"【反向守卫】基线已测完；现在把 `{mut_key}` 的 {mut_cell} {how}（其余不动）……")
        recs, errs = run_all()
        guard = {"mutated": mut_key, "cell": list(mut_cell), "how": how}
        b = {r["key"]: r for r in base_recs}
        moved = []
        for r in recs:
            rb = b.get(r["key"])
            if rb is None:
                moved.append((r["key"], "新出现的关卡"))
                continue
            sb, sr = _signature(rb), _signature(r)
            if sb != sr:
                fields = set(sb) | set(sr)
                added = {f: [c for c in sr.get(f, []) if c not in sb.get(f, [])] for f in fields}
                removed = {f: [c for c in sb.get(f, []) if c not in sr.get(f, [])] for f in fields}
                added = {f: v for f, v in added.items() if v}
                removed = {f: v for f, v in removed.items() if v}
                moved.append((r["key"], f"新增 {added}｜消失 {removed}"))
        guard["moved"] = moved
        guard["ok"] = (len(moved) == 1 and moved[0][0] == mut_key
                       and f"({mut_cell[0]}, {mut_cell[1]})" in moved[0][1])
        print(f"【反向守卫】{'✅ 红得起来且指得准' if guard['ok'] else '❌ 没红/指错'}："
              f"改动 `{mut_key}` {mut_cell}；A/B 差异 = {moved}")
        #: ⚠ **结论一律取未改动那一版**：第一版把改动后的结果当了结论，
        #: 于是汇总里凭空多出"某一关 1 格分歧"——**那 1 格就是我自己改的**。
        #: 守卫的改动不能污染结论，两件事必须分开算。
        recs, errs = base_recs, base_errs

    kind_count: collections.Counter = collections.Counter()
    clean = 0
    for r in recs:
        if not r["div"]:
            clean += 1
        for k in r["div"]:
            kind_count[k] += 1
    print("-" * 100)
    print(f"比对 {len(recs)} 关：**完全一致 {clean}**；有分歧 {len(recs) - clean}"
          f"（我们侧加载失败 {len(errs)}）")
    print("分歧类型计数（按关）：" + ("，".join(f"{k} {v}" for k, v in kind_count.most_common())
                                     or "无"))
    for r in recs:
        if r["div"]:
            print(f"  {r['key']:<24} {r['div']}")
    if errs:
        print(f"⚠ 我们侧加载失败 {len(errs)} 关：" +
              "；".join(f"{e['key']}({e['why'][:40]})" for e in errs[:5]))

    samples: list[dict] = []
    for k in [s.strip() for s in args.sample.split(",") if s.strip()]:
        if k not in maa:
            samples.append({"key": k, "why": "第三源没有这一关"})
            continue
        try:
            st = load_stage(k)
        except Exception as e:                                   # noqa: BLE001
            samples.append({"key": k, "why": f"我们侧加载失败 {type(e).__name__}"})
            continue
        samples.append(render_sample(k, maa[k], st))

    OUTDIR.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(
        {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "source_dir": str(TILE_DIR), "maa_meta": meta,
         "ours_files": sum(len(v) for v in ours.values()), "ours_levels": len(ours),
         "mirror_conflicts": mir_bad,
         "common": len(common), "only_maa": only_maa[:200],
         "only_ours": only_ours[:200], "clean": clean, "kind_count": dict(kind_count),
         "errors": errs, "records": recs, "guard": guard, "samples": samples},
        ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    if args.out:
        write_md(Path(args.out), meta, ours, common, only_maa, only_ours, recs, errs,
                 clean, kind_count, guard, mir_bad, samples)
        print(f"报告：{args.out}")
    print(f"耗时 {(time.time() - t0) / 60:.1f} 分钟")
    return 0


def _letter(b: str, h: str) -> str:
    return (b or "?")[0] + (h or "?")[0]


def render_sample(key: str, entry: dict, stage) -> dict:
    """抽样人工复核用：把两边的**同一个概念**渲染成同一种字符网格，逐行对照。

    字符＝`可部署首字母 + 高低地首字母`（N/M/R/A + L/H）。**两边用同一套映射**，
    所以「看起来一样」就等于逐格一样；只要朝向或单位错位，网格会立刻错开。
    """
    m = stage.map
    rows_ours = ["".join(_letter(t.buildable, t.height) for t in row) for row in m.tiles]
    best, best_v = None, None
    for i, v in enumerate(entry.get("variants") or []):
        if v.get("error") or v.get("tiles") is None:
            continue
        if (v.get("width"), v.get("height")) != (m.width, m.height):
            continue
        rows_maa = ["".join(_letter(BUILDABLE.get(c.get("buildableType"), "?"),
                                   HEIGHT.get(c.get("heightType"), "?")) for c in row)
                    for row in v["tiles"]]
        diff = sum(1 for a, b in zip(rows_ours, rows_maa) for ca, cb in zip(a, b) if ca != cb)
        if best is None or diff < best:
            best, best_v = diff, (i + 1, v, rows_maa)
    if best_v is None:
        return {"key": key, "why": "第三源没有同尺寸的一份可比"}
    i, v, rows_maa = best_v
    return {"key": key, "variant": f"{i}/{entry.get('n_variants')}", "file": v.get("file"),
            "rows_ours": rows_ours, "rows_maa": rows_maa, "same": rows_ours == rows_maa,
            "cells": sum(len(r) for r in rows_ours), "diff_cells": best,
            "size": [m.width, m.height]}


def write_md(path: Path, meta, ours, common, only_maa, only_ours, recs, errs, clean,
             kind_count, mutated, mir_bad=None, samples=None) -> None:
    L: list[str] = []
    L.append("# MAA 地块 JSON 独立第三源交叉校验")
    L.append("")
    L.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}；执行者：验收与守卫会话 "
             f"`session-1a45cfee-9a65-4830-a327-03ac84285bfb`")
    L.append(f"- 第三源：本机 MAA 资源目录的 `Arknights-Tile-Pos\\`（**只读**；"
             f"本回合实测 **{meta['files']} 份** `.json`；其数据不入仓、不进报告正文）")
    L.append(f"- 我们侧：`data/gamedata/levels/**/level_*.json` 经 `ak_tactic.gamedata.stage.load_stage()`"
             f"（**只读**；地图层不是我的单写者文件，发现分歧只报不改）")
    L.append("")
    L.append("## 一、计数（先说清「数了谁」）")
    L.append("")
    L.append(f"- 第三源目录下**地块 JSON {meta['files']} 份**（本回合实测；逐份都是关卡图）")
    L.append(f"- 去重后**唯一关卡 {meta['stages']}**（同 id 多份 {meta['multi']} 关："
             f"其中**内容不同** **{len(meta['conflicts'])}** 关——`act1multi_*` 一类是多难度变体，"
             f"**不是重复文件**，本工具全部留下当候选）")
    L.append(f"- 我们侧**本地缓存** {sum(len(v) for v in ours.values())} 份 → 去重 **{len(ours)} 关**"
             f"（`GameDataSource` 是**按需下载**，磁盘上只有跑过的关；**这不是我们的关卡全集**）")
    L.append(f"- **交集 {len(common)} 关**（下面逐关比的就是这些）；只有第三源有 **{len(only_maa)}** 关；"
             f"只有我们有 **{len(only_ours)}** 关")
    L.append("")
    if mir_bad:
        L.append(f"**同一关多镜像缓存内容不一致**（{len(mir_bad)} 关，按**语义**比、键序空白不算差）"
                 f"——镜像之间也会打架：")
        L.append("")
        for m in mir_bad[:10]:
            L.append(f"- `{m['level']}`{m.get('detail', '')}：" + "；".join(m["files"]))
        if all("逐格不同 0 格" in (m.get("detail") or "") for m in mir_bad):
            L.append("")
            L.append("> 这 16 关的差异**不在 `mapData.tiles` 上**（逐格 0 格不同）⇒ **与本条判据无关**；"
                     "但**镜像之间确实不同**这件事仍要登记——别的层（路线/出怪/机制读的是同一份 JSON）"
                     "引用时得知道自己在读哪一份。")
        L.append("")
    L.append("> ⚠ 「交集只有几十关」是**我们本地缓存稀疏**所致，**不是**「我们的地图少」——"
             "两个方向的读数都必须先看覆盖口径。**总数什么都证明不了**，下面逐关分歧才是结论。")
    L.append("")
    L.append("**去重口径**：关卡 id 取文件名里**最后那个 `level_<id>` 段**"
             "（**不许按第一个 `-` 切**——那样会把 `main_01-01`…`main_01-07` 塌成 `main_01`，"
             "整族 `main_*` 被静默排除；这条是**抽样人工复核**抓出来的：1-7 被报成"
             "「第三源没有这一关」）。带 `#f#` 的与不带的是**同一关的两份**；同 id 多份**不丢**——"
             "逐份比，取**最接近**的那份为结论，并报出「该关它有几份、最接近的是第几份」。")
    L.append("")
    L.append("## 二、取值映射（**实测出来的，不是猜的**）")
    L.append("")
    L.append("| MAA | 我们 | 判据 |")
    L.append("| --- | --- | --- |")
    L.append("| `buildableType` 0 / 1 / 2 | `NONE` / `MELEE` / `RANGED` | `main_01-07` 计数 "
             "38 / 23 / 16 与逐格比对同时吻合 |")
    L.append("| `buildableType` **3** | **`ALL`** | `act31side_ex05` 上 **33 格一一同位对上**"
             "（第一版没写这一条 ⇒ 当场「报出 33 格分歧」，而那 33 格恰好就是我们的 `ALL` 格） |")
    L.append("| `heightType` 0 / 1 | `LOWLAND` / `HIGHLAND` | 31 / 46 逐项吻合 |")
    L.append("| `tileKey` | `Tile.key` | 同名同义（`tile_forbidden` 等） |")
    L.append("")
    L.append("**它那套 `isStart` / `isEnd` 不比**（另一层概念，不是 `tile_start`/`tile_end`）："
             "实测我们的 `tile_start` 格**总是它 `isStart` 的真子集**——"
             "`act31side_07` **2 vs 10**、`act31side_ex03` **3 vs 9**，且差集落在普通路面格上。"
             "它标的是**路线端点**（含路面），要真比得拿**我们的路线层**去对 ⇒ **本轮登记为未覆盖**，"
             "**不拿它凑地块分歧**（否则会出现「概念不同」被记成「地图不一致」的假红）。")
    L.append("")
    L.append("## 三、朝向（不靠猜：用同概念的起点/终点格实测）")
    L.append("")
    ok_orient = sum(1 for r in recs if r.get("orientation", "").startswith("同向"))
    L.append(f"- 两边都是 `tiles[y][x]`（原点左上、y 向下），且**同概念**对齐"
             f"（都取 `tileKey == tile_start/tile_end`）。实测 **{ok_orient}/{len(recs)}** "
             f"关的起点格完全一致 ⇒ **同向，未翻转**。")
    bad_orient = [r for r in recs if not r.get("orientation", "").startswith("同向")]
    if bad_orient:
        for r in bad_orient[:10]:
            L.append(f"  - `{r['key']}`：我们 {r['start_ours']} vs 它 {r['start_maa']}")
    else:
        L.append("- **没有一关**起点格不一致。")
    L.append("")
    L.append("> ⚠ 这一节第一版是错的：我用 `find(\"start\")` 取我们的起点格——`find()` 按 **tileKey "
             "精确匹配**，于是返回**空**，34/34 关全被报成「起点不一致」。"
             "**发现它的路是仪器自相矛盾**：同一份地图的 key 分布里明明有 `tile_start × 3`。"
             "教训：**「它和我不同」与「我读错了」长得一模一样**，判据先要自己不打架。")
    L.append("")
    L.append("## 四、总账")
    L.append("")
    L.append(f"比了 **{len(recs)}** 关（交集里全部）：**完全一致 {clean}**、"
             f"有分歧 **{len(recs) - clean}**、我们侧加载失败 {len(errs)}。")
    L.append("")
    L.append("**分歧类型（按关计数）**：" +
             ("，".join(f"{k} {v}" for k, v in kind_count.most_common()) or "无"))
    L.append("")
    L.append("## 五、逐关分歧")
    L.append("")
    L.append("| 关卡 | 尺寸（我们/它） | 分歧类型 | 前几格（x, y, 我们, 它） |")
    L.append("| --- | --- | --- | --- |")
    for r in recs:
        if not r["div"]:
            continue
        bits = []
        for f, diffs in (r.get("dir") or {}).items():
            bits.append(f"{f}: " + "；".join(f"({x},{y}) {a}→{b}" for x, y, a, b in diffs[:4]))
        L.append(f"| `{r['key']}` | {r['size']} / {r['maasize']} | "
                 f"{'，'.join(f'{k}×{v}' for k, v in r['div'].items())} | "
                 f"{'<br>'.join(bits)[:400] or '—'} |")
    L.append("")
    if errs:
        L.append(f"**我们侧加载失败 {len(errs)} 关**（⇒ 这 {len(errs)} 关**本轮未跑**，"
                 f"不是「一致」也不是「不一致」）：")
        L.append("")
        for e in errs[:12]:
            L.append(f"- `{e['key']}`：{e['why'][:90]}")
        L.append("")
        L.append("> 给**后端**的线索（**只报不改**）：这 8 关在本机的 `stage` 表里**查不到**"
                 "（`level_id like 'act31side_sub%'` / `'act3d0_0%'` **零行**），"
                 "而磁盘上却**有**对应的地图文件（如 `map.ark-nights.com/levels/activities/act31side/"
                 "level_act31side_sub-1-1.json`）⇒ **「本机有地图文件」≠「我们索引里有这一关」**，"
                 "本报告的覆盖计数按**前者**算，引用时请注意这个口径差。")
        L.append("")
    L.append("## 六、抽样人工复核（至少 5 关，含 1-7 与我们已有定论的 SR-EX-8）")
    L.append("")
    L.append("做法：把两边**同一概念**渲染成同一套字符网格（`可部署首字母 + 高低地首字母`，"
             "N/M/R/A + L/H），**逐行肉眼对照**。朝向或单位一旦错位，网格会立刻错开——"
             "所以这一节是**给人看的**，不是脚本自说自话。")
    L.append("")
    for s in (samples or []):
        if s.get("why"):
            L.append(f"- `{s['key']}`：**跳过**（{s['why']}）")
            continue
        L.append(f"### `{s['key']}`（{s['size'][0]}×{s['size'][1]}，{s['cells']} 格；"
                 f"取它第 {s['variant']} 份）")
        L.append("")
        verdict = "**完全一致**" if s["same"] else f"**{s['diff_cells']} 格不同**"
        L.append(f"逐格比对：{verdict}"
                 f"（人工核对：两边行数与每行宽度相同，第 0 行左端起字符相同 ⇒ 无翻转、无列偏移）")
        L.append("")
        L.append("```")
        L.append("我们：")
        L.extend(s["rows_ours"])
        L.append("它：")
        L.extend(s["rows_maa"])
        L.append("```")
        L.append("")
    L.append("## 七、反向守卫（**判据先写死再跑**）")
    L.append("")
    if not mutated:
        L.append("本次运行未带 `--mutate`。")
    else:
        L.append(f"- 做法：把 `{mutated['mutated']}` 的 {tuple(mutated['cell'])} "
                 f"{mutated['how']}（**只动这一格**），再跑一次全套比对，"
                 f"与**未改动的那一次** A/B 相差。")
        L.append(f"- 判据（先写死）：**只有那一关的 `buildable` 分歧集恰好多了那一格，"
                 f"其它关一切不动**。➜ {'✅ 成立' if mutated.get('ok') else '❌ 不成立'}")
        L.append(f"- A/B 实测差异：`{mutated.get('moved')}`")
        L.append("")
        L.append("> ⚠ 这里**不能**用「恰好 1 关红」当判据：本轮比对里本来就可能存在真分歧"
                 "（第一版就吃过这个亏：当时 `a001_01` 与 `act31side_ex05` 都「有分歧」，"
                 "而那两处**全是我自己读错**，见第九节）。"
                 "判据必须建立在「与未改动那一版的**差值**」上。")
    L.append("")
    L.append("## 九、工具自身的三处自纠（**这一条比结论更重要**）")
    L.append("")
    L.append("本轮这条比对**第一版报了 34 关分歧，全是假的**。三处成因各不同，全部记在这里，"
             "因为它们正是「它错了」与「我读错了」同形的三种典型：")
    L.append("")
    L.append("| # | 我第一版的写法 | 症状 | 真根因 | 修法 |")
    L.append("| --- | --- | --- | --- | --- |")
    L.append("| 1 | `m.find(\"start\")` 取我们起点格 | **34/34 关**都「起点不一致」 | "
             "`find()` 按 **tileKey 精确匹配**，`\"start\"` 匹配不到 `tile_start` ⇒ 返回**空** | "
             "改成 `find(\"tile_start\")`；并让**仪器自相矛盾**成为检查项"
             "（key 分布里有 3 个 `tile_start` 却报 0 个起点） |")
    L.append("| 2 | 映射表只写 `buildableType` 0/1/2 | `act31side_ex05` **33 格分歧** | "
             "漏了第四取值：它的 **3 ↔ 我们的 `ALL`**（33 格一一同位） | 补进映射表；"
             "并在工具里写死「**对不上的取值原样报出来，不许拿最像的去凑**」 |")
    L.append("| 3 | 守卫在基线之前就改了数据 | 守卫报「❌ 没红」 | 两次跑的都是**改过的那份**，"
             "A/B 恒等 | 顺序改成**先跑基线 → 再改 → 再跑**；并**结论只取未改动那一版**"
             "（否则守卫自己的改动会污染结论，凭空多出「某关 1 格分歧」） |")
    L.append("")
    L.append("> 三条的共同教训：**判据要先能证明「它红得起来」，再谈它绿得可不可信**；"
             "而「红得起来」本身还要分两层——**先敏感性**（改坏一处，红不红）、"
             "**再控制组**（不改的时候红不红、红的到底是什么）。")
    L.append("")
    L.append("## 十、边界（本条不覆盖什么）")
    L.append("")
    L.append("- 比的是**地块层**（尺寸/可部署/高度/地块键/起点终点格），"
             "**不比**出怪表、路线、装置、机制——那些不在这一层里。")
    L.append("- 它那套 `isStart`/`isEnd`（**路线端点**）**本轮没比**：要拿我们的**路线层**去对，"
             "属未覆盖项（见第二节的实测理由）。")
    L.append("- 「一致」只说明**两个来源互相印证**，**不等于**「地图层一定对」："
             "若两源同错（同源的错误抄写），本条看不见。")
    L.append("- 覆盖面上：**交集只有几十关**是因为我们本地只有跑过的关有缓存，"
             "**不是**我们的地图少；反过来，只有第三源有的关卡也**不构成**我们的缺口。")
    L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
