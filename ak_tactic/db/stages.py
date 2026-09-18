"""关卡索引（`stage` 表）与章节（`zone` 表）——把「SR-EX-8」这种显示名对上 levelId，
再补上「它叫什么、属于哪一章、什么环境」。

## 为什么必须有这两张表

`ak_tactic/gamedata/source.py` 早就扒得到关卡索引，但它只落在
`data/gamedata/_level_index.json`——那是**缓存**：`data/gamedata/` 已 gitignore、
TTL 7 天、文档明说「约 17 MB，可随时删」。清一次缓存或断网，选关界面就没东西可选了。
所以要一份持久的。

## 为什么不能只有 levelId

活动关的显示名与 levelId 之间**没有可推导关系**：`SR-EX-8` ↔ `act54side_ex08`
猜不出来（SR 前缀只存在于这份索引里，而 `excel/` 两个镜像都不带关卡表）。
主线还能靠 `main_01-07` → `1-7` 勉强猜，活动关一概不行。

## 三个实测事实

1. **同 code 会有多条。** 每个关卡号下还有一份 `#f#` 后缀的四星限定版，
   它的 `code` 与普通版**完全相同**（`main_00-01` 与 `main_00-01#f#` 的 code
   都是 `0-1`）。所以**主键是 levelId，不是 code**；按 code 查要自己处理撞车，
   `resolve_code()` 的约定是**普通难度优先**。
2. **规模**：写这段时实测 4694 条、去重后 2227 个 code。这是**会漂的水位**，
   别在文档里写死，用 `db info` 看活值。
3. **难度分四档**：NORMAL / FOUR_STAR / RUNE / SIX_STAR。

## 取数与落库

来源是两处，**一次 `db stage-fetch` 全取**：

- `map.ark-nights.com` 编译进 JS bundle 的那份**索引**（没有独立 JSON 端点，
  扒法在 `gamedata/source.py::_scrape_index`，这里直接复用，不重写一遍）；
- GitHub 镜像的 `excel/stage_table.json`（关卡中文名）、`excel/zone_table.json`
  （章节与分部）、`excel/activity_table.json`（**活动名与 zone→活动映射**）。
  ark-nights **没有 `excel/` 目录**，这三张表只在 GitHub 那边有。

**两处失败的口径不同**：索引取不到必须报错（选关界面会整个空掉），
名字那三张表取不到只让名字栏留空、界面退回显示 levelId——所以
`fetch_level_index()` 与 `fetch_names()` 分开抛，由 CLI 决定谁是硬失败。

**取不到时绝不写空表。** 顺序是「先取完、再打开库写」：取数阶段抛
`StageTableError`，此时一个字节都还没动，上一版表原样保留。这与 `tile` 表
（取不到只记警告、表留空）**是相反的口径**，而且是故意的——地块字典缺了只是
少几个中文名，关卡表空了却会让用户以为「这游戏没有关卡」。

`db build` 全程不联网，但它会把整份库文件换掉（`.part` + `os.replace`），
所以那里有一道 `carry_over()` 把旧库的两张表原样搬到新库，
否则每建一次库这两张表就被清空一次。

## 只取这五类（博士 2026-09-18）

`zone_table` 有 477 条、11 类。本项目**只留** `MAINLINE` / `BRANCHLINE` /
`CAMPAIGN` / `MAINLINE_ACTIVITY` / `ACTIVITY`——口径就是 theresa.wiki/map 的分类
（两边的类型名与逐类条数完全对得上：ACTIVITY 297、SIDESTORY 84、CLIMB_TOWER 24…）。
其余六类（肉鸽 6 / 爬塔 24 / 周常 9 / 导览 1 / `SIDESTORY` 84 / `MAINLINE_RETRO` 3）
**既不进库也不进菜单**：`insert_stages` 按 `CHAPTER_TYPES` 筛行、
`prune_foreign_rows` 把库里过时的清掉，`db stage-prune` 可单独跑（不联网）。

判据是**两条数据关系**，不是 id 前缀（前缀迟早会变）：
① `zone.type` 在白名单里；② 关卡的 `zone_id` 在 zone 表里查得到。
第二条一次覆盖两类东西——被剔除类型下面的关卡，以及 `zone_id` 指向一个 zone 表里
**根本没有的** zone 的关卡（干员密录 `mem_*` 308、生息演算 `sandbox_*` 159、
危机合约 128、小玩法 25、活动旧 id 64…）。实清一次：127 个 zone / 1660 关，
留下 350 个 zone / 3034 关。

**活动名去掉「复刻」后缀**（43 个里 42 个写 `墟·复刻`、1 个写 `不义之财 复刻`），
见 `clean_activity_name`。改名**不会**让菜单出现重复条目：活动复刻之后原版的 zone
就不再有关卡了（关卡全指到复刻那些 zone 上），所以那一对里只有一条进得了菜单。
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

__all__ = [
    "StageTableError", "fetch_level_index", "fetch_names", "insert_stages",
    "load_stages", "load_zones", "list_stages", "list_zones", "list_chapters",
    "zone_of", "zone_title", "resolve_code", "carry_over",
    "FOUR_STAR_SUFFIX", "DIFFICULTY_ORDER", "DIFFICULTY_LABELS", "ENV_LABELS",
    "ENV_ORDER", "CHAPTER_TYPES", "CAMPAIGN_TITLE", "clean_activity_name",
    "prune_foreign_rows", "clean_zone_names",
]

#: 四星限定版的后缀。普通版是 `main_00-01`，四星版是 `main_00-01#f#`，
#: 两者**共用同一个 code**——这是主键必须用 levelId 的原因。
FOUR_STAR_SUFFIX = "#f#"

#: 难度档的显示顺序（普通在前，其余按稀有度递进）
DIFFICULTY_ORDER = ("NORMAL", "FOUR_STAR", "RUNE", "SIX_STAR")

#: 难度档给人看的名字。**这是三档不是两档**：实测 `stage_table` 里
#: NORMAL 2730 / FOUR_STAR 774 / **SIX_STAR 45**，SIX_STAR 就是第 15-17 章的
#: 「险地作战」（第 15 章 34 关里 18 关 NORMAL、16 关 SIX_STAR）。
DIFFICULTY_LABELS = {
    "NORMAL": "普通（三星）",
    "FOUR_STAR": "突袭（四星）",
    "SIX_STAR": "险地作战（六星）",
    "RUNE": "符文（RUNE）",
    "": "未知",
}

#: 环境分层（`stage.diff_group`）给人看的名字。
#: 实测分布：EASY=剧情体验（关卡 id 前缀 `easy_*`）、NORMAL=标准实战（`main_*`）、
#: TOUGH=磨难险地（`tough_*`）、ALL=通用（`st_*`/`spst_*`/`tr_*`，剧情与教学关）、
#: NONE=无分层。第 9 章只有 EASY/NORMAL（**没有 TOUGH**），第 10-14 章三档齐全，
#: 第 0-8 章与第 15-17 章全是 NONE——后者的环境落在 `difficulty` 上。
#:
#: **「通用」（ALL）保留，这是博士 2026-09-17 的裁定。** 第 9 章的环境菜单因此是
#: **三条**而不是需求里写的两条（剧情体验 18 / 标准实战 41 / 通用 4）。当时问过
#: 博士要不要把它藏起来——他答「第九章那些就放在通用」，即留着。留着也是唯一
#: 说得通的选法：那 4 关的 `diff_group` 就是 ALL，不列出来它们在这套三层菜单里
#: **没有第二个入口**，等于悄悄少掉 4 关。
ENV_LABELS = {
    "EASY": "剧情体验",
    "NORMAL": "标准实战",
    "TOUGH": "磨难险地",
    "ALL": "通用",
    "NONE": "",
    "": "",
}
#: 环境那一层菜单里的排列顺序
ENV_ORDER = ("EASY", "NORMAL", "TOUGH", "ALL")

#: 本项目**只取这几类** zone（口径就是 theresa.wiki/map 的分类）。
#:
#: 博士 2026-09-18 裁定：`MAINLINE`（主线）/ `BRANCHLINE`（插曲·别传）/
#: `CAMPAIGN`（剿灭作战）/ `MAINLINE_ACTIVITY`（主线活动章）/ `ACTIVITY`（活动）。
#: 其余几类——`ROGUELIKE`（肉鸽）、`CLIMB_TOWER`（爬塔）、`WEEKLY`（周常）、
#: `GUIDE`（导览）、`SIDESTORY`、`MAINLINE_RETRO`——**既不进库也不进菜单**。
#:
#: 这是**写入口径**（`insert_stages` 按它筛行、`prune_foreign_rows` 按它清库），
#: 不只是菜单的白名单：库里留着 6 百多条肉鸽关卡而界面上一条都看不见，
#: 只会让人以为「这游戏有这些关」。
CHAPTER_TYPES = ("MAINLINE", "BRANCHLINE", "CAMPAIGN", "MAINLINE_ACTIVITY",
                 "ACTIVITY")

#: 菜单第一层的排列顺序。与 `CHAPTER_TYPES` 是**同一批**，只是顺序另有讲究：
#: 主线各章 → 第 15–17 章（`MAINLINE_ACTIVITY`，那也是主线，必须紧挨着）→
#: 剿灭作战 → 插曲·别传 → 活动。口径那一份（筛选用）不承担顺序，所以单列一份。
CHAPTER_ORDER = ("MAINLINE", "MAINLINE_ACTIVITY", "CAMPAIGN", "BRANCHLINE",
                 "ACTIVITY")

#: 剿灭作战在菜单里的显示名。它的 15 个 zone 在 gamedata 与 theresa.wiki 里
#: **名字全是空的**（取数只到 `zoneNameSecond: None` 这一层），只能自己给一个。
CAMPAIGN_TITLE = "剿灭作战"

#: 活动名里的「复刻」后缀。写法不止一种：绝大多数是 `墟·复刻`，实测还有
#: `不义之财 复刻`（空格），所以间隔符要放宽；`玛莉娅·临光` 那种带间隔符但
#: 不带「复刻」的名字**不能动**。
_RERUN_RE = re.compile(r"\s*[·・•]?\s*[（(]?\s*复刻\s*[）)]?\s*$")


class StageTableError(RuntimeError):
    """关卡索引取不到。**取不到时不要往库里写空表。**"""


def fetch_level_index(*, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """取关卡索引：`{level_id: {code, zone_id, data_path, difficulty}}`。

    走 `GameDataSource`（默认源 `map.ark-nights.com`），复用它的 bundle 扒法与
    7 天缓存。**这一步抛错时调用方还没碰过库**，所以上一版表能原样留着。
    """
    from ..gamedata.source import GamedataError, GameDataSource

    try:
        index = GameDataSource().level_index(refresh=refresh)
    except GamedataError as exc:
        raise StageTableError(f"关卡名获取失败：{exc}") from exc
    if not index:
        raise StageTableError("关卡名获取失败：索引是空的")
    return index


def fetch_names(*, refresh: bool = False) -> tuple[dict, dict]:
    """取「关卡中文名」「章节/分部名」「活动名」，返回 `(stages, zones)`。

    走 **GitHub 镜像**而不是默认源：`map.ark-nights.com` 不带 `excel/` 目录
    （`excel/*.json` 一律 404），而这三张表只在那里有。

    - `stages[level_id]` = `{name, stage_type, diff_group, hard_level_id}`
    - `zones[zone_id]` = `{zone_index, type, name_first, name_second,
      name_title, name_third, activity_id, activity_name}`

    **它和关卡索引是两回事，失败口径也不同**：索引取不到必须报错（选关界面会
    整个空掉），这里取不到只让名字栏留空、界面退回显示 levelId——所以本函数
    把异常包成 `StageTableError`，由调用方决定是硬失败还是记个警告继续。
    """
    from ..gamedata.source import GITHUB_BASE, GamedataError, GameDataSource

    src = GameDataSource(base=GITHUB_BASE)
    try:
        raw_stages = src.fetch_json("excel/stage_table.json",
                                    use_cache=not refresh)
        raw_zones = src.fetch_json("excel/zone_table.json",
                                   use_cache=not refresh)
    except GamedataError as exc:
        raise StageTableError(f"关卡中文名获取失败：{exc}") from exc
    except Exception as exc:                                   # noqa: BLE001
        raise StageTableError(
            f"关卡中文名获取失败：{type(exc).__name__}: {exc}") from exc

    # 活动名（「月行水上」）只在 activity_table 里，**它是第二层菜单的依据**：
    # zoneToActivity 给 zone → 活动，basicInfo 给活动 → 中文名。
    # 这张表拿不到不算失败——只是活动名留空，界面退回按 zone 名展示。
    zone_to_act: dict[str, str] = {}
    act_names: dict[str, str] = {}
    try:
        raw_act = src.fetch_json("excel/activity_table.json",
                                 use_cache=not refresh)
        zone_to_act = {str(k): str(v) for k, v in
                       (raw_act.get("zoneToActivity") or {}).items() if v}
        act_names = {str(k): str((v or {}).get("name") or "")
                     for k, v in (raw_act.get("basicInfo") or {}).items()}
    except Exception:                                          # noqa: BLE001
        pass

    stages: dict[str, dict[str, Any]] = {}
    for level_id, e in (raw_stages.get("stages") or {}).items():
        if not isinstance(e, dict):
            continue
        stages[str(level_id)] = {
            "name": str(e.get("name") or ""),
            "stage_type": str(e.get("stageType") or ""),
            "diff_group": str(e.get("diffGroup") or ""),
            "hard_level_id": str(e.get("hardStagedId") or ""),
        }

    zones: dict[str, dict[str, Any]] = {}
    for zone_id, e in (raw_zones.get("zones") or {}).items():
        if not isinstance(e, dict):
            continue
        act = zone_to_act.get(str(zone_id), "")
        zones[str(zone_id)] = {
            "zone_index": e.get("zoneIndex"),
            "type": str(e.get("type") or ""),
            "name_first": str(e.get("zoneNameFirst") or ""),
            "name_second": str(e.get("zoneNameSecond") or ""),
            "name_title": str(e.get("zoneNameTitleCurrent") or ""),
            "name_third": str(e.get("zoneNameThird") or ""),
            "activity_id": act,
            "activity_name": clean_activity_name(act_names.get(act, "")) if act else "",
        }
    # 大文件解析完丢掉原始对象（gamedata 的常规做法，不丢会胀上百 MB）
    for rel in ("excel/stage_table.json", "excel/zone_table.json",
                "excel/activity_table.json"):
        try:
            src.release(rel)
        except Exception:                                      # noqa: BLE001
            pass
    return stages, zones


_CN_DIGITS = "零一二三四五六七八九"


def clean_activity_name(name: str) -> str:
    """活动名去掉「复刻」后缀，只留本名（博士 2026-09-18）。

    实测 134 个活动名里 43 个带「复刻」：42 个写作 `墟·复刻`，1 个写作
    `不义之财 复刻`。去掉之后**会与原版撞名**（42 组），这是**已知且接受**的——
    复刻是一份独立的活动（自己的 zone 与关卡），不该因为名字相同就被吞掉。
    所以这里只改名字，不动归并逻辑。

    `玛莉娅·临光` 这类带间隔符但不带「复刻」的名字原样返回——判据是**后缀**，
    不是「有没有间隔符」。
    """
    raw = str(name or "").strip()
    if not raw:
        return ""
    out = _RERUN_RE.sub("", raw).strip()
    return out or raw                     # 名字本身就叫「复刻」时别清成空串


def _cn_num(n: int) -> str:
    """1–99 → 中文数字。第 1-14 章的 `name_first` 本来就是中文（「第九章」），
    第 15-17 章只有数字，要自己拼成同一副样子，否则同一个菜单里
    「第九章」与「第15章」并排，看着像两套东西。"""
    if n <= 0:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    tens, ones = divmod(n, 10)
    head = "十" if tens == 1 else _CN_DIGITS[tens] + "十"
    return head + (_CN_DIGITS[ones] if ones else "")


def _chapter_head(zone: dict[str, Any]) -> str:
    """主线那一类的**章号**：「第一章」「序章」「第十六章」；非主线返回空串。

    第 1-14 章 `name_first` 直接写着「第一章」…「第十四章」，用它就行；
    **第 15-17 章是 `MAINLINE_ACTIVITY`**，`name_first` 是英文
    （Critical Phase Transition），章号只在 `name_title`（"17"）——得自己拼成
    中文数字，与前十四章统一；序章的 `name_title` 是 "00"，不算章号。
    这段只此一份：`zone_title()` 与 `chapter_label()` 都从它取，免得两处漂。
    """
    first = (zone.get("name_first") or "").strip()
    title = (zone.get("name_title") or "").strip()
    if first.startswith("第") and first.endswith("章"):
        return first                                  # 第一章…第十四章
    if title.isdigit() and title != "00":
        return f"第{_cn_num(int(title))}章"            # MAINLINE_ACTIVITY
    if title == "00":
        return first or "序章"                         # 序章
    return ""


def zone_title(zone: dict[str, Any] | None) -> str:
    """把一个 zone 记录拼成**人看的章节名**。

    第 1-14 章 `name_first` 直接写着「第一章」…「第十四章」，直接用它。
    但**第 15-17 章是 `MAINLINE_ACTIVITY`**：`name_first` 是英文
    （Critical Phase Transition），中文副标题在 `name_second`，章号只在
    `name_title`（"17"）——「第十七章」**没有现成字段，得自己拼**。
    side story 没有章号，取分部名（通学路 / 殡仪堂）。
    """
    if not zone:
        return ""
    first = (zone.get("name_first") or "").strip()
    second = (zone.get("name_second") or "").strip()
    head = _chapter_head(zone)
    if head:
        # 章号后面挂副标题——「第十六章　反常光谱」。第 1-14 章不带副标题
        # （`zone_title` 是通用名，别处当分部名用），菜单那一层要的排版见
        # `chapter_label()`。
        if head.startswith("第") and second and not first.startswith("第"):
            return f"{head}　{second}"
        return head
    return second or first or (zone.get("zone_id") or "")


def chapter_label(zone: dict[str, Any] | None) -> str:
    """主线章节在**菜单第一层**的写法：`第七章　苦难摇篮`（博士 2026-09-18）。

    「给主线关标题改成【第X章 ’章节标题‘】」——博士原话，而**书名号与单引号只是
    他写格式说明用的记号，不是要印在屏幕上的字**（他随后澄清：「那只是我的格式
    说明」）。所以这一格就是「章号 + 全角空格 + 章节标题」，与第 15–17 章本来
    的写法（`第十六章　反常光谱`）一致；序章没有章号，写「序章　黑暗时代·上」。

    只认主线（`MAINLINE` 与 `MAINLINE_ACTIVITY`——第 15-17 章也是主线）：
    活动、剿灭作战、插曲那些名字都由活动名或分部名出，不走这里，返回空串，
    调用方退回 `zone_title()`。

    与 `zone_title()` 的分工：那个是**通用**章节名（第 1-14 章只给章号，别处
    当分部名用），这个是菜单第一层要的「章号 + 章节标题」。两处各写一份必然会漂，
    所以章号共用 `_chapter_head()`。
    """
    if not zone or (zone.get("type") or "") not in ("MAINLINE",
                                                    "MAINLINE_ACTIVITY"):
        return ""
    head = _chapter_head(zone)
    if not head:
        return ""
    sub = (zone.get("name_second") or "").strip()
    return f"{head}　{sub}" if sub else head


def _rows(index: dict[str, dict[str, Any]],
          names: dict[str, dict[str, Any]] | None = None,
          ) -> list[tuple[str, str, str, str, str, str, str, str, str]]:
    """把关卡索引与名字表并成待写入的行。

    **两表要 join 而不是替代**：索引 4694 条 vs `stage_table` 3549 条，
    索引独有 1346 条（生息演算那类），那些名字留空。
    """
    names = names or {}
    out: list[tuple[str, str, str, str, str, str, str, str, str]] = []
    for level_id, v in index.items():
        if not isinstance(v, dict):
            continue
        n = names.get(str(level_id)) or {}
        out.append((
            str(level_id),
            str(v.get("code") or ""),
            str(v.get("difficulty") or "NORMAL"),
            str(v.get("zone_id") or ""),
            str(v.get("data_path") or ""),
            str(n.get("name") or ""),
            str(n.get("stage_type") or ""),
            str(n.get("diff_group") or ""),
            str(n.get("hard_level_id") or ""),
        ))
    out.sort(key=lambda r: r[0])
    return out


#: `stage` 表的列，写入与搬运共用一份，免得两处列数对不上
_STAGE_COLS = ("level_id", "code", "difficulty", "zone_id", "data_path",
               "name", "stage_type", "diff_group", "hard_level_id")
_STAGE_SQL = (f"INSERT OR REPLACE INTO stage ({', '.join(_STAGE_COLS)}) "
              f"VALUES ({', '.join('?' * len(_STAGE_COLS))})")

#: `zone` 表的列
_ZONE_COLS = ("zone_id", "zone_index", "type", "name_first", "name_second",
              "name_title", "name_third", "activity_id", "activity_name")
_ZONE_SQL = (f"INSERT OR REPLACE INTO zone ({', '.join(_ZONE_COLS)}) "
             f"VALUES ({', '.join('?' * len(_ZONE_COLS))})")


def _keep_ph(n: int) -> str:
    """`?, ?, ?`——SQLite 不接受列表参数，只能自己拼占位符。"""
    return ", ".join("?" * n)


def _kept_zone_ids(conn: sqlite3.Connection,
                   zones: dict[str, dict[str, Any]] | None) -> set[str]:
    """本次该留下的 `zone_id` 集合（`CHAPTER_TYPES` 那五类）。

    优先用**本次取到的** zone 表；没取到（名字那三张表失败、只写索引）时退回
    库里现有的 zone 表——那时的口径是「按已知分类留下、其余不要」，而不是
    「什么都不筛」：一次没联网的重取不该把肉鸽关卡又请回来。
    """
    src = zones or {}
    if src:
        return {zid for zid, z in src.items()
                if (z.get("type") or "") in CHAPTER_TYPES}
    try:
        return {r[0] for r in conn.execute(
            f"SELECT zone_id FROM zone WHERE type IN ({_keep_ph(len(CHAPTER_TYPES))})",
            CHAPTER_TYPES)}
    except sqlite3.OperationalError:
        return set()


def prune_foreign_rows(conn: sqlite3.Connection, *,
                       keep_types: tuple[str, ...] = CHAPTER_TYPES,
                       ) -> tuple[int, int]:
    """清掉不属于 `keep_types` 的 zone，以及**所有不在 zone 表里的关卡**。

    返回 `(清掉的 zone 数, 清掉的关卡数)`。**不自己开事务**——调用方决定它跟谁
    同一个事务（`insert_stages` 就把它跟写入放在一起）。

    第二条同时覆盖两种东西：① 被剔除类型下面的关卡（肉鸽 696、爬塔 236、
    周常 35、导览 2）；② `zone_id` 指向一个 zone 表里**根本没有的** zone 的关卡
    （干员密录 `mem_*` 308、生息演算 `sandbox_*` 159、危机合约 128、小玩法 25、
    活动旧 id 64…）。这两类都进不了菜单，博士 2026-09-18 裁定一并清掉，
    库里只留这五类。**判据是「(zone.type, zone 表里有没有这条)」，不是 id 前缀**
    ——前缀迟早会变，而这两条是数据本身的关系。
    """
    zsql = f"DELETE FROM zone WHERE type IS NULL OR type NOT IN ({_keep_ph(len(keep_types))})"
    cur = conn.execute(zsql, keep_types)
    zones_gone = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    cur = conn.execute("DELETE FROM stage WHERE zone_id IS NULL OR zone_id = '' "
                       "OR zone_id NOT IN (SELECT zone_id FROM zone)")
    stages_gone = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return zones_gone, stages_gone


def clean_zone_names(conn: sqlite3.Connection) -> int:
    """把**已经写进库的**活动名里的「复刻」后缀擦掉，返回改了几条。

    取数时 `fetch_names` 已经洗过一遍（见 `clean_activity_name`），所以这条是给
    「库里还留着旧名字、又不想为改个名字联网重取」的场合用的——`db stage-prune`
    顺手就做。SQLite 没有正则，只能在 Python 侧比一遍再写回；350 条 zone 而已。
    """
    rows = list(conn.execute("SELECT zone_id, activity_name FROM zone "
                             "WHERE activity_name IS NOT NULL AND activity_name <> ''"))
    changed = [(clean_activity_name(name), zid) for zid, name in rows
               if clean_activity_name(name) != name]
    if changed:
        conn.executemany("UPDATE zone SET activity_name = ? WHERE zone_id = ?", changed)
    return len(changed)


def insert_stages(conn: sqlite3.Connection,
                  index: dict[str, dict[str, Any]],
                  names: dict[str, dict[str, Any]] | None = None,
                  zones: dict[str, dict[str, Any]] | None = None,
                  *,
                  prune: bool = True,
                  report: dict[str, int] | None = None) -> int:
    """把索引（连同名字与章节）写进库，返回写入的关卡条数。

    整体一个事务：中途炸掉不会留下半张表（`db build` 的原子落盘是文件级的，
    这里是语句级的，几张表各管一道）。

    `names` / `zones` 可以缺省——缺了就是「只要索引，不要名字」，
    行照写、名字列留空（调用方在取不到名字时走的就是这条路）。

    **只写这五类**（博士 2026-09-18 裁定）：zone 按 `type` 筛，关卡按
    「它的 zone 在这次要留的集合里」筛。`prune=True` 时还会在同一个事务里
    把库里过时的其余行清掉（`prune_foreign_rows`）——不筛写入的话，第一次
    取完之后库里那 1660 条肉鸽/爬塔/密录关卡会一直躺着。

    顺序是「先写要留的 zone → 再清 → 最后写关卡」：清关卡那一步的问法是
    「这个 zone_id 在 zone 表里吗」，所以 table 里必须先有**要留的那些** zone。

    `report` 传一个 dict 进来时，会把筛掉/清掉的条数写进去
    （`rows_skipped` / `zones_removed` / `stages_removed`），给 CLI 报数用；
    返回值仍是**写进去的**关卡条数。
    """
    rows = _rows(index, names)
    if not rows:
        raise StageTableError("关卡名获取失败：解析出的条目是 0 条")
    keep = _kept_zone_ids(conn, zones)
    payload = [r for r in rows if r[3] in keep]
    if not payload:
        raise StageTableError(
            f"关卡名获取失败：{len(rows)} 条里没有一条落在 {len(keep)} 个"
            f"该留的 zone 里——zone 表是不是取空了？"
            "（一条都不写，库保持原样）")
    # zone_id 是 `zones` 字典的**键**，不在值里——按列名取值会把主键写成 NULL，
    # 而 SQLite 允许 PRIMARY KEY 列为 NULL（没写 NOT NULL 时），477 行会静默地
    # 全挤在同一个 None 键上、读回来只剩 1 条。所以这里显式把键排在第一列。
    zone_payload = [(zid,) + tuple(z.get(c) for c in _ZONE_COLS[1:])
                    for zid, z in (zones or {}).items()
                    if (z.get("type") or "") in CHAPTER_TYPES]
    try:
        with conn:                               # 失败自动回滚
            if zone_payload:
                conn.executemany(_ZONE_SQL, zone_payload)
            if prune:
                gone = prune_foreign_rows(conn)
                if report is not None:
                    report["zones_removed"], report["stages_removed"] = gone
            conn.executemany(_STAGE_SQL, payload)
    except sqlite3.IntegrityError as exc:
        raise StageTableError(f"章节表写入被拒（主键为空或重复）：{exc}") from exc
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            raise StageTableError(
                "这个库还没有 stage/zone 表（结构版本是旧的）：先跑一次 "
                "`db build` 重建结构，再跑 `db stage-fetch`。") from exc
        raise
    if report is not None:
        report.setdefault("rows_skipped", 0)
        report["rows_skipped"] += len(rows) - len(payload)
    return len(payload)


def load_stages(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """读回全部关卡（表不存在或为空都返回空 dict，调用方自己决定怎么办）。

    旧库（v6）没有后四列，这里**退回旧列**而不是报错——重建结构前也得能读。
    """
    try:
        cur = conn.execute(
            "SELECT level_id, code, difficulty, zone_id, data_path, "
            "name, stage_type, diff_group, hard_level_id FROM stage")
    except sqlite3.OperationalError:
        try:
            cur = conn.execute(
                "SELECT level_id, code, difficulty, zone_id, data_path FROM stage")
        except sqlite3.OperationalError:
            return {}
        return {r[0]: {"code": r[1], "difficulty": r[2], "zone_id": r[3],
                       "data_path": r[4], "name": "", "stage_type": "",
                       "diff_group": "", "hard_level_id": ""} for r in cur}
    return {r[0]: {"code": r[1], "difficulty": r[2], "zone_id": r[3],
                   "data_path": r[4], "name": r[5], "stage_type": r[6],
                   "diff_group": r[7], "hard_level_id": r[8]} for r in cur}


def load_zones(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """读回全部章节/区域。表不存在或为空都返回空 dict。

    旧库没有活动那两列时退回旧列——重建结构前也得能读。
    """
    _base = ("zone_index", "type", "name_first", "name_second",
             "name_title", "name_third")
    try:
        cur = conn.execute(
            "SELECT zone_id, zone_index, type, name_first, name_second, "
            "name_title, name_third, activity_id, activity_name FROM zone")
    except sqlite3.OperationalError:
        try:
            cur = conn.execute(
                "SELECT zone_id, zone_index, type, name_first, name_second, "
                "name_title, name_third FROM zone")
        except sqlite3.OperationalError:
            return {}
        return {r[0]: dict(zip(_base, r[1:]), activity_id="",
                           activity_name="") for r in cur}
    return {r[0]: dict(zip(_base, r[1:7]), activity_id=r[7],
                       activity_name=r[8]) for r in cur}


def list_chapters(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """给选关界面第一层用的**章/活动**列表。

    这一层比 `zone` 高一级：`zone_table` 的 477 条里有 103 个活动含多个 zone
    （`act54side`「月行水上」= `act54side_zone1` 通学路 + `act54side_zone2` 殡仪堂），
    把它们平铺成 477 行等于让用户自己认前缀。所以先按 `activity_id` 归并：

    - 活动含 **1** 个 zone → 直接是一条（主线各章走这条，标题取章节名）；
    - 活动含 **多个** zone → 一条活动，`parts` 里是各个分部（界面加第二层）。

    返回 `[{key, title, subtitle, levels, parts: [{zone_id, title, levels}]}]`。
    `levels` **含四星限定版**，与下一层列表的行数一致；`zone_envs()` 同理。

    两处特例：

    * `ACTIVITY` 里原版与复刻是**两条独立活动**，去掉「复刻」后缀后名字会撞
      （42 组）。这是**接受的**——见 `clean_activity_name`。所以这里只按
      `activity_id` 归并，不按名字归并。
    * `CAMPAIGN`（剿灭作战）的 15 个 zone 名字全是空的，也没挂 `activity_id`：
      平铺出来就是 15 行「camp_zone_7」这种东西。所以**整类归成一条**
      「剿灭作战」，分部名取该分部里关卡的**关卡名**（龙门外环、龙门市区…），
      那是这一层唯一有意义的取数。
    """
    zones = load_zones(conn)
    # 读侧也过一遍口径。写侧（`insert_stages` / `prune_foreign_rows`）已经筛过，
    # 但库里那一份可能是**旧口径时代留下来的**（或者被 `db build` 的 carry_over
    # 整表搬过来的），而 `db build` 不联网、不会顺手清库。菜单不该因为库的状态
    # 就把肉鸽、爬塔那些摆出来。
    zones = {z: v for z, v in zones.items()
             if (v.get("type") or "") in CHAPTER_TYPES}
    counts: dict[str, int] = {}
    totals: dict[str, int] = {}
    stage_names: dict[str, list[str]] = {}
    for level_id, v in load_stages(conn).items():
        zid = v.get("zone_id") or ""
        totals[zid] = totals.get(zid, 0) + 1
        if level_id.endswith(FOUR_STAR_SUFFIX):
            continue
        counts[zid] = counts.get(zid, 0) + 1
        nm = (v.get("name") or "").strip()
        if nm:
            lst = stage_names.setdefault(zid, [])
            if nm not in lst:              # `#f#` 那份与普通版同名，去重
                lst.append(nm)

    groups: dict[str, list[str]] = {}
    for zid, z in zones.items():
        ztype = (z.get("type") or "")
        if ztype not in CHAPTER_TYPES:
            continue
        if not counts.get(zid):
            continue                       # 一条关卡都没有的 zone 不进菜单
        if ztype == "CAMPAIGN":
            key = CAMPAIGN_TITLE           # 整类一条，见 docstring
        else:
            key = (z.get("activity_id") or "").strip() or zid
        groups.setdefault(key, []).append(zid)

    out: list[dict[str, Any]] = []
    for key, zids in groups.items():
        def _zkey(z: str) -> tuple:
            """分部顺序：`zone_index` → （剿灭作战）zone_id 尾号 → zone_id。

            剿灭那 15 个 zone 的 `zone_index` **全是 0**，只按它排就会退化成
            字符串序（camp_zone_1、camp_zone_10、…、camp_zone_2），尾号才是
            它们真实的先后（也是图的上线顺序）。
            """
            zi = zones[z].get("zone_index")
            num = 99
            if (zones[z].get("type") or "") == "CAMPAIGN":
                tail = z.rsplit("_", 1)[-1]
                num = int(tail) if tail.isdigit() else 99
            return (zi if zi is not None else 99, num, z)

        zids.sort(key=_zkey)
        first = zones[zids[0]]
        act_name = (first.get("activity_name") or "").strip()
        # **条数一律含四星限定版**（= 下一层列表里真实看得见的行数）。
        # 菜单报 24 而列表给 41 行会让人以为筛错了；这一层不做去重，
        # 「同一个关卡的突袭版」在下一层用难度筛选区分。
        parts = [{"zone_id": z, "title": _part_title(zones[z], stage_names.get(z)),
                  "levels": totals.get(z, 0)} for z in zids]
        if key == CAMPAIGN_TITLE:
            title, subtitle = CAMPAIGN_TITLE, f"{len(zids)} 个部分"
        elif len(zids) == 1:
            # 单个 zone 的活动没有分部名可拼：章节名（主线各章）→ 活动名
            # → 最后才把内部 id（`act1multi`）摆上台面。缺了活动名那一退，
            # 「奇象巡展」「卫戍协议」这六个单 zone 活动会显示成空白行——
            # 实测就是空白，不是「名字太长被截了」。
            title = chapter_label(first) or zone_title(first) or act_name or key
            subtitle = ""
        else:
            # 活动名优先；拿不到活动名时退回分部的章节名，别把内部 id 摆上台面
            title = act_name or zone_title(first) or key
            subtitle = f"{len(zids)} 个部分"
        out.append({"key": key, "title": title, "subtitle": subtitle,
                    "levels": sum(p["levels"] for p in parts), "parts": parts})

    order = {t: i for i, t in enumerate(CHAPTER_ORDER)}

    def sort_key(e: dict[str, Any]) -> tuple:
        z = zones[e["parts"][0]["zone_id"]]
        title = (z.get("name_title") or "").strip()
        num = int(title) if title.isdigit() else 99
        return (order.get(z.get("type") or "", 9), num,
                z.get("zone_index") if z.get("zone_index") is not None else 99,
                e["key"])

    out.sort(key=sort_key)
    return out


def _part_title(zone: dict[str, Any],
                stage_names: list[str] | None = None) -> str:
    """第二层（分部）的显示名。

    side story 取分部名（通学路 / 殡仪堂）。主线各章只有一个 zone、**不会走到这**，
    这里取章节名只是为了万一（配了环境菜单时会用到）。

    `CAMPAIGN` 是个例外：它的 zone 名字全是空的，所以退到**这一分部里的关卡名**
    （「龙门外环、龙门市区、龙门商业街」）——玩家认的是图名。15 个分部的关卡名
    两两不重复，所以这么取也天然不会撞名。关卡名也拿不到时（名字表没取到）
    才退回 `zone_title`，那一步会露出 `camp_zone_7` 这种内部 id，是最后的退路。
    """
    if (zone.get("type") or "") == "CAMPAIGN" and stage_names:
        return "、".join(stage_names)
    # 主线（含第 15-17 章）与第一层同一套写法：【第X章 ‘章节标题’】
    return chapter_label(zone) or (zone.get("name_second") or "").strip() \
        or zone_title(zone)


def list_zones(conn: sqlite3.Connection, *,
               types: tuple[str, ...] = CHAPTER_TYPES,
               ) -> list[dict[str, Any]]:
    """列 zone（**不归并活动**），带拼好的 `title`。

    选关界面第一层用的是 `list_chapters()`（按活动归并）；本函数给
    `db` 命令行与需要逐 zone 看的场合用。
    """
    zones = load_zones(conn)
    out: list[dict[str, Any]] = []
    for zone_id, z in zones.items():
        if types and (z.get("type") or "") not in types:
            continue
        out.append({"zone_id": zone_id, "title": zone_title(z), **z})
    order = {t: i for i, t in enumerate(CHAPTER_ORDER)}

    def key(e: dict[str, Any]) -> tuple:
        title = (e.get("name_title") or "").strip()
        num = int(title) if title.isdigit() else 99
        return (order.get(e.get("type") or "", 9), num,
                e.get("zone_index") if e.get("zone_index") is not None else 99,
                e["zone_id"])

    out.sort(key=key)
    return out


def zone_of(conn: sqlite3.Connection, zone_id: str) -> dict[str, Any] | None:
    """取一条 zone，附带拼好的 `title`。取不到返回 None。"""
    z = load_zones(conn).get(zone_id or "")
    if z is None:
        return None
    return {"zone_id": zone_id, "title": zone_title(z), **z}


def list_stages(conn: sqlite3.Connection, *, keyword: str = "",
                difficulty: str = "", zone: str = "", zone_id: str = "",
                env: str = "", exclude_four_star: bool = False,
                limit: int = 0) -> list[dict[str, Any]]:
    """按关键词/难度/区域/环境筛关卡，`code` 升序、普通难度在前。

    `keyword` 同时匹配 levelId、code、zone_id 与**关卡中文名**——用户手上有可能是
    任意一种写法。`zone` 是**子串**匹配（命令行用），`zone_id` 是**精确**匹配
    （选关界面按分部下钻时用，`main_1` 用子串会连 `main_10` 一起捞出来）。
    """
    kw = keyword.strip().upper()
    out: list[dict[str, Any]] = []
    for level_id, v in load_stages(conn).items():
        if exclude_four_star and level_id.endswith(FOUR_STAR_SUFFIX):
            continue
        if difficulty and (v["difficulty"] or "").upper() != difficulty.upper():
            continue
        if zone_id and (v["zone_id"] or "") != zone_id:
            continue
        if zone and zone.upper() not in (v["zone_id"] or "").upper():
            continue
        if env and (v["diff_group"] or "").upper() != env.upper():
            continue
        if kw and kw not in level_id.upper() \
                and kw not in (v["code"] or "").upper() \
                and kw not in (v["zone_id"] or "").upper() \
                and kw not in (v.get("name") or "").upper():
            continue
        out.append({"level_id": level_id, **v})
    out.sort(key=lambda e: (
        e["level_id"].endswith(FOUR_STAR_SUFFIX),
        DIFFICULTY_ORDER.index(e["difficulty"])
        if e["difficulty"] in DIFFICULTY_ORDER else len(DIFFICULTY_ORDER),
        _code_sort_key(e["code"]),
        e["level_id"],
    ))
    return out[:limit] if limit > 0 else out


def _code_sort_key(code: str) -> tuple:
    """让 `2-7` 排在 `2-10` 前面（纯字符串排序会反）。"""
    parts = []
    for chunk in (code or "").replace(FOUR_STAR_SUFFIX, "").replace("_", "-").split("-"):
        parts.append((0, int(chunk), "") if chunk.isdigit() else (1, 0, chunk))
    return tuple(parts)


def resolve_code(conn: sqlite3.Connection, query: str) -> dict[str, Any] | None:
    """把用户写的关卡号解析成一条记录。

    认得 `SR-EX-8` / `1-7` / `act54side_ex08` 三种写法。**同 code 撞车时普通难度优先**
    （四星限定版要用就把 `#f#` 写全）。
    """
    q = (query or "").strip()
    if not q:
        return None
    table = load_stages(conn)
    if q in table:
        return {"level_id": q, **table[q]}

    upper = q.upper()
    hits = [{"level_id": k, **v} for k, v in table.items()
            if (v["code"] or "").upper() == upper]
    if not hits:
        return None
    normal = [h for h in hits if not h["level_id"].endswith(FOUR_STAR_SUFFIX)]
    return (normal or hits)[0]


def carry_over(old_path: Path | str | None, conn: sqlite3.Connection) -> int:
    """把旧库里的 `stage` / `zone` 原样搬进新库，返回搬运的关卡条数。

    `db build` 走 `.part` + `os.replace`，**整份文件换掉**——不搬的话，
    每建一次库这两张要联网才拿得到的表就被清空一次。旧库不存在、没有这两张表、
    或表是空的，都返回 0（那不是错误，只是还没 `db stage-fetch` 过）。

    **列数按旧库实际有什么来决定**：`stage` 早先只有 5 列、`zone` 早先没有活动那
    两列，按满列 SELECT 会报错。所以逐张表先试满列、失败退回旧列并给新列补空串
    ——老库搬过来只是暂时缺中文名，再跑一次 `db stage-fetch` 就有了。
    """
    if old_path is None:
        return 0
    old = Path(old_path)
    if not old.exists():
        return 0
    try:
        src = sqlite3.connect(f"file:{old.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    rows: list[tuple] = []
    zones: list[tuple] = []
    try:
        try:
            rows = src.execute(
                f"SELECT {', '.join(_STAGE_COLS)} FROM stage").fetchall()
        except sqlite3.Error:
            try:                                   # 旧库的 stage 只有 5 列
                old_rows = src.execute(
                    "SELECT level_id, code, difficulty, zone_id, data_path "
                    "FROM stage").fetchall()
                rows = [tuple(r) + ("", "", "", "") for r in old_rows]
            except sqlite3.Error:
                rows = []                          # 旧库根本没有 stage 表
        try:
            zones = src.execute(
                f"SELECT {', '.join(_ZONE_COLS)} FROM zone").fetchall()
        except sqlite3.Error:
            try:                                   # 旧库的 zone 没有活动那两列
                old_z = src.execute(
                    "SELECT zone_id, zone_index, type, name_first, name_second, "
                    "name_title, name_third FROM zone").fetchall()
                zones = [tuple(r) + ("", "") for r in old_z]
            except sqlite3.Error:
                zones = []                         # 旧库没有 zone 表，不是错误
    finally:
        src.close()
    # 丢掉主键为空的行。这类行在库里是**不可用**的（查不到、显示不出来），
    # 而新库的主键是 NOT NULL——不筛的话老库一旦有过一次主键写空的 bug，
    # 重建就会当场 IntegrityError 挡死在这里。真实来由见 insert_stages 的注释。
    bad = sum(1 for r in rows if not r[0]) + sum(1 for r in zones if not r[0])
    rows = [r for r in rows if r[0]]
    zones = [r for r in zones if r[0]]
    if not rows and not zones:
        return 0
    with conn:
        if rows:
            conn.executemany(_STAGE_SQL, rows)
        if zones:
            conn.executemany(_ZONE_SQL, zones)
    if bad:
        import sys as _sys
        print(f"    注：跳过 {bad} 行主键为空的旧记录（它们在旧库里就是坏的）",
              file=_sys.stderr)
    return len(rows)


# ---------------------------------------------------------------- 取数前的预估

#: 取数统计里本源的键
STATS_KEY = "level_index"


def estimate_fetch(*, refresh: bool = False):
    """取关卡索引之前先算一笔账：几个请求、多大、多久。

    两项**分开取来源**，因为它们的寿命不一样：
    耗时只有真取过才知道（攒在统计里），体积则每次都能用一个 HEAD 现测。
    **不能因为有了耗时就不探体积**——那样体积永远填不进去。
    """
    import time as _time

    from ..gamedata.source import GameDataSource
    from ..fetchplan import (DEFAULT_THROUGHPUT, POLITE_INTERVAL, FetchEstimate,
                             format_bytes, load_stats, probe_bytes)

    src = GameDataSource()
    cache = src.index_path
    ttl = getattr(src, "index_ttl", 7 * 86400)

    if not refresh and cache.exists() and \
            (_time.time() - cache.stat().st_mtime) < ttl:
        return FetchEstimate(
            key=STATS_KEY, label="关卡索引", hits=0,
            cached_bytes=cache.stat().st_size,
            basis=f"缓存还在有效期内（TTL {ttl / 86400:.0f} 天），不用重取")

    saved = (load_stats() or {}).get(STATS_KEY) or {}
    bits: list[str] = []

    # --- 耗时：优先用上次实测
    secs = float(saved["seconds"]) if saved.get("seconds") else None
    if secs is not None:
        bits.append(f"耗时 {secs:.0f} 秒为上次实测"
                    f"（{saved.get('at') or '时间不详'}）")
    if saved and not saved.get("ok"):
        bits.append("**上次这一项是失败的**")

    # --- 体积：上次测过就用，没测过就现探一次
    size = int(saved["bytes"]) if saved.get("bytes") else None
    hits = int(saved.get("hits") or 0)
    if size is not None:
        bits.append(f"体积 {format_bytes(size)} 取自"
                    f"{saved.get('bytes_basis') or '来源不详'}")

    if size is None:
        # 先取首页（小），从里面认出 bundle 名，再 HEAD 那个 bundle。
        hits = max(hits, 1)
        site = getattr(src, "site", "")
        bundles: list[str] = []
        try:
            html = src._download(f"{site}/", accept="text/html",
                                 timeout=30).decode("utf-8", "replace")
            bundles = re.findall(r'"(/bundle\.[0-9a-fA-F]+\.js)"', html)
        except Exception:                                      # noqa: BLE001
            pass
        if bundles:
            hits = max(hits, 1 + len(bundles))
            size, failed = probe_bytes([f"{site}{b}" for b in bundles])
            if size is not None:
                bits.append(f"体积 {format_bytes(size)} 是本次 HEAD 实测")
            else:
                bits.append(f"HEAD 拿不到 Content-Length（{len(failed)} 个），体积未知")
        else:
            bits.append("首页取不到，bundle 名认不出来——体积只能等真取的时候看")

    if hits == 0:
        hits = 2                                        # 首页 + 一个 bundle

    if secs is None:
        secs = (size / DEFAULT_THROUGHPUT) if size else None
        if secs is not None:
            bits.append(f"耗时按 {DEFAULT_THROUGHPUT / 1024:.0f} KB/s 估"
                        f"（假设值，取决于你的网络）")
        else:
            bits.append("耗时未知")

    return FetchEstimate(
        key=STATS_KEY, label="关卡索引", hits=hits, bytes_=size, seconds=secs,
        floor_seconds=0.0 if secs is not None else hits * POLITE_INTERVAL,
        basis="；".join(bits))
