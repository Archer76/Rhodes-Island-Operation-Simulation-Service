"""TUI 的数据访问层：名册、关卡、目录配置。

**这一层负责"没有登录态也能跑"**。登录只影响"名册是不是最新的"，不影响
"流程能不能走完"——名册有三个来源，按可信度依次退：

1. 森空岛名册缓存 `data/skland/roster_<uid>.json`（带专精与模组等级，最准）；
2. MAA 的 OperBox 导出（`tools/operbox_path.py` 定的位置；**没有专精与模组**）；
3. 都没有 → 返回 `None`，上层如实说"没有名册"，让用户手选或先登录。

第 2 条是**降级**而不是等价：OperBox 里 `elite/level/potential` 齐全，
但 `skills[].specializeLevel` 与 `equip[].level` 没有，编队里那些"专三/模组三"的
前提会算不准。上层要把它标出来，不能悄悄当完整名册用。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Operator", "Roster", "load_roster", "default_guides_dir",
           "load_config", "save_config", "config_path", "stage_rows",
           "chapter_rows", "zone_envs", "zone_diffs", "complete_dir",
           "operator_db_status",
           "PROFESSION_CN", "PROFESSION_ORDER", "TRAINED_FILTERS",
           "profession_cn", "group_label", "meets_trained",
           "skland_uid", "skland_game_uid", "roster_file", "roster_meta",
           "roster_for_uid", "cached_roster_uids"]

#: 配置放**仓库外**（`~/.rios/`）。理由与 data/ 一样：里面会有用户自己的绝对路径，
#: 写进仓库就违反了"仓库内不得出现本机绝对路径"的铁律。
CONFIG_FILE = "tui.json"


def config_path() -> Path:
    return Path.home() / ".rios" / CONFIG_FILE


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(**kw) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg.update(kw)
    try:
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    except OSError:
        pass


def default_guides_dir() -> Path:
    """MAA 作业的默认输出目录：**本工具根目录下的 `Guides/`**。

    刻意**不用** `~/Guides`——数据跟工具放在一起，一份克隆就是自包含的，
    换机器、换用户、放到 U 盘里都跟着走，不必再去猜作业写到哪里了。
    该目录已进 `.gitignore`（作业文件里有玩家自己的编队，不该进仓库）。
    """
    return Path(__file__).resolve().parent.parent.parent / "Guides"


def guides_dir() -> Path:
    raw = (load_config().get("guides_dir") or "").strip()
    return Path(raw).expanduser() if raw else default_guides_dir()


# ---------------------------------------------------------------- 名册

@dataclass
class Operator:
    """名册里的一名干员。字段名与 `tools/roster.py` 的产出保持一致。"""

    char_id: str
    name: str
    profession: str = ""
    sub_profession: str = ""
    elite: int = 0
    level: int = 1
    potential: int = 1
    trust: float = 0.0
    module: str | None = None
    module_level: int = 0
    equipped_status: str = ""
    skills: dict = field(default_factory=dict)

    @property
    def trained(self) -> tuple:
        """练度排序键：精英段 → 等级 → 潜能。"""
        return (self.elite, self.level, self.potential)

    def label(self) -> str:
        mod = ""
        if self.module and self.equipped_status == "ok":
            mod = f"  模组{self.module_level}"
        elif self.module:
            mod = f"  ({self.equipped_status})"
        return (f"{self.name}  E{self.elite} {self.level}级  "
                f"潜{self.potential}  信赖{self.trust:.0f}%{mod}")


@dataclass
class Roster:
    source: str                 # "skland" / "operbox"
    operators: list[Operator] = field(default_factory=list)
    uid: str = ""
    nick: str = ""
    path: str = ""
    note: str = ""              # 降级时必须说明缺了什么

    @property
    def complete(self) -> bool:
        """名册是否带专精与模组等级（只有森空岛那份带）。"""
        return self.source == "skland"

    def by_name(self, name: str) -> Operator | None:
        for op in self.operators:
            if op.name == name:
                return op
        return None

    def top(self, n: int = 0) -> list[Operator]:
        ops = sorted(self.operators, key=lambda o: o.trained, reverse=True)
        return ops[:n] if n > 0 else ops


def _from_skland(path: Path) -> list[Operator]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[Operator] = []
    for r in data.get("opers") or []:
        out.append(Operator(
            char_id=r.get("charId") or "",
            name=r.get("name") or r.get("charId") or "",
            profession=r.get("profession") or "",
            sub_profession=r.get("subProfession") or "",
            elite=int(r.get("elite") or 0),
            level=int(r.get("level") or 1),
            potential=int(r.get("potential") or 1),
            trust=float(r.get("trust") or 0.0),
            module=r.get("equipped_module") or r.get("module"),
            module_level=int(r.get("equipped_module_level")
                             or r.get("module_level") or 0),
            equipped_status=r.get("equipped_status") or "",
            skills={k: v for k, v in r.items()
                    if k.startswith("skill") or k == "defaultSkillId"},
        ))
    return out


def _from_operbox(path: Path) -> list[Operator]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    # MAA 的导出有两种外形：带 data 字段的包装、或直接是数组
    rows = raw.get("data") if isinstance(raw, dict) else raw
    if isinstance(rows, dict):
        rows = rows.get("characters") or rows.get("opers") or []
    out: list[Operator] = []
    for r in rows or []:
        if not r.get("own", True):
            continue
        out.append(Operator(
            char_id=r.get("id") or r.get("charId") or "",
            name=r.get("name") or r.get("id") or "",
            elite=int(r.get("elite") or 0),
            level=int(r.get("level") or 1),
            potential=int(r.get("potential") or 1),
            trust=float(r.get("favorPercent") or 0.0) / 2.0,
        ))
    return out


def skland_uid() -> str | None:
    """当前账号的**通行证账号 id**（凭据文件名用它）。没登过/已退出/失败 → None。"""
    try:
        from ak_tactic import skland
        return skland.current_uid()
    except Exception:                                     # noqa: BLE001
        return None


def skland_game_uid() -> str | None:
    """当前账号的**游戏 uid**（名册用它）。还没问过森空岛就是 None。**离线**。

    与 `skland_uid()` 是两个量：前者是通行证账号，后者才是森空岛数据里的 uid。
    拿前者去找名册会找不到——它们通常不相等（前者 13 位、后者 8 位），
    而账号 id 不出现在任何一份森空岛数据里，离线对不上。
    """
    try:
        from ak_tactic import skland
        return skland.game_uid()
    except Exception:                                     # noqa: BLE001
        return None


def roster_file(uid: str) -> Path:
    root = Path(__file__).resolve().parent.parent.parent
    return root / "data" / "skland" / f"roster_{uid}.json"


def cached_roster_uids() -> list[str]:
    """本机**有**名册缓存的账号 uid。

    退出账号不删文件，所以这里通常会有好几个。它的用途只有一个：
    当前账号还没拉过名册时，把"哪些号拉过"如实说出来——否则 `[0]` 屏只能
    干说一句「没有找到名册」，而人看着磁盘上明明躺着一份名册文件。
    """
    d = roster_file("x").parent
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("roster_*.json")):
        uid = p.stem[len("roster_"):]
        if uid:
            out.append(uid)
    return out


def roster_meta(uid: str) -> dict:
    """某个账号名册里的 uid / 昵称。**离线**读缓存文件，不联网。"""
    try:
        raw = json.loads(roster_file(uid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


# ------------------------------------------------- 账号行：游戏用户名 + 游戏uid
#
# **登录账号 ≠ 游戏 uid，这是两个量。** 登录账号是鹰角通行证的账号 id（13 位），
# 凭据文件 `cred_<它>.json` 用它命名；游戏 uid（8 位）才是森空岛数据与名册
# （`roster_<它>.json`）用的那个。两者通常不相等，而且账号 id **不出现在任何一份
# 森空岛数据里**，所以离线推不出映射，只能问一次森空岛再记住
# （`ak_tactic.skland.resolve_game_uid*` → `~/.skland/accounts.json`）。
#
# 账号列表原先两处都印**登录账号**、昵称又拿**登录账号**去名册里查——名册是按
# 游戏 uid 存的，于是昵称几乎永远是空的，一行看下来只有一串认不出的数字。
# 博士 2026-09-18 的口径：列表要显示**游戏用户名与游戏uid**，登录账号 id 只作附注。

def account_info(login_uid: str) -> dict:
    """一个**登录账号**在界面上要的两件事：游戏用户名、游戏uid。**离线**。

    来源按可信度排：
      ① `accounts.json` 里那条映射（按 U 真的问过森空岛之后记下的）——最准；
      ② 映射在、昵称空时，读该游戏 uid 的名册缓存里的 `nickName` 补一手。

    映射还没有时**不猜**：老机器上账号 id 与游戏 uid 有可能相同，那就用
    `roster_<登录账号>.json` 是否存在来反证——真存在才算，否则如实报未知。
    """
    login_uid = str(login_uid or "").strip()
    out = {"login_uid": login_uid, "game_uid": "", "nick": "", "channel": "",
           "has_roster": False, "known": False}
    try:
        from ak_tactic import skland
        rec = skland.accounts_map().get(login_uid) or {}
    except Exception:                                         # noqa: BLE001
        rec = {}
    game = str(rec.get("gameUid") or "").strip()
    nick = str(rec.get("nickName") or "").strip()
    out["channel"] = str(rec.get("channelName") or "").strip()
    if not game and login_uid and roster_file(login_uid).exists():
        game = login_uid
    if not nick and game:
        nick = str(roster_meta(game).get("nickName") or "").strip()
    out["game_uid"], out["nick"] = game, nick
    out["has_roster"] = bool(game) and roster_file(game).exists()
    out["known"] = bool(game or nick)
    return out


def describe_account(login_uid: str, *, current: bool = False,
                     roster_flag: bool = True,
                     login_note: bool = True) -> str:
    """一行账号的排版：**先游戏用户名与游戏uid**，登录账号 id 只作 dim 附注。

    `current=True` 加一个 `←当前` 标记。未知的字段如实写「未知」并给出补救办法
    （按 U 问一次森空岛）——把"还没问过"写成空白，人只会以为是程序坏了。

    `roster_flag=False` 去掉尾部那句「（无）名册缓存」：主界面把名册状态单独
    写成一句更准的话（份数、来源、降级警告），同一栏里再挂一个粗粒度的
    「有名册缓存」就是重复；登录屏那几处**照旧**带着它。

    `login_note=False` 去掉「（登录账号 <id>）」这个小注（博士 2026-09-18：
    主界面那一处删掉）。登录屏**照旧**带着它——那里正是要选"哪个账号"的地方，
    一个号可能有两个 id，标识得写全；主界面只回答"现在登的是哪个号"。
    """
    info = account_info(login_uid)
    uid = info["login_uid"]
    if info["nick"]:
        head = f"[bold]{info['nick']}[/]"
    else:
        head = "[warn]游戏用户名未知[/]"
    head += (f"　游戏uid={info['game_uid']}" if info["game_uid"]
             else "　[warn]游戏uid 未知[/]")
    if info["channel"]:
        head += f"　[dim]{info['channel']}[/]"
    if uid and login_note:
        head += f"　[dim]（登录账号 {uid}）[/]"
    if roster_flag:
        head += ("　[dim]有名册缓存[/]" if info["has_roster"]
                 else "　[dim]无名册缓存[/]")
    if not info["known"]:
        head += "\n    [dim]按 U 问一次森空岛，就能把这个号的用户名与游戏 uid 记下来。[/]"
    if current:
        head += "　[ok]←当前[/]"
    return head


def roster_for_uid(uid: str) -> tuple[list[Operator], dict, Path] | None:
    """某个账号的名册缓存。**只认这一个 uid**，取不到返回 None。"""
    f = roster_file(uid)
    if not f.exists():
        return None
    try:
        ops = _from_skland(f)
    except (OSError, ValueError):
        return None
    if not ops:
        return None
    try:
        meta = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    return ops, (meta if isinstance(meta, dict) else {}), f


def load_roster() -> Roster | None:
    """按可信度依次找名册。**找不到返回 None，不编一份出来。**

    ## 先说清"哪个 uid"

    这里要的是**游戏 uid**，不是凭据里的通行证账号 id——那是两个量，
    而名册（`roster_<游戏uid>.json`）按前者存。两者通常不相等
    （前者 13 位、后者 8 位），而且账号 id **不出现在任何一份森空岛数据里**，
    所以离线推不出这个映射，只能问森空岛一次再记住
    （`ak_tactic.skland.resolve_game_uid`，记在 `~/.skland/accounts.json`）。
    映射还没建立时先按登录 uid 找一遍——账号 id 与游戏 uid 相同的情况下
    那也能命中，且**不可能取到别人号的**（它只找这一个名字的文件）。

    ## 再说"为什么不能按 mtime 取最新的"

    `data/skland/` 下可能同时存着好几个账号的 `roster_<uid>.json`
    （本项目退出账号不删文件），照文件名排序或按 mtime 取第一份，
    会在切换账号之后**显示错账号的名册、而且不报错**——那是最坏的一类错：
    界面看着完全正常，报出来的练度却是别人号的。
    """
    root = Path(__file__).resolve().parent.parent.parent

    for uid in (skland_game_uid(), skland_uid()):
        if not uid:
            continue
        got = roster_for_uid(uid)
        if got:
            ops, meta, f = got
            return Roster(source="skland", operators=ops,
                          uid=str(meta.get("uid") or uid),
                          nick=str(meta.get("nickName") or ""),
                          path=str(f),
                          note="含专精与模组等级（森空岛口径，最准）")

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_operbox_path", root / "tools" / "operbox_path.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        box = mod.operbox_path()
    except Exception:                                     # noqa: BLE001
        box = None
    if box and Path(box).exists():
        try:
            ops = _from_operbox(Path(box))
        except (OSError, ValueError):
            ops = []
        if ops:
            return Roster(
                source="operbox", operators=ops, path=str(box),
                note="**降级来源**：MAA 的 OperBox 没有专精与模组等级，"
                     "编队里的专三/模组三前提会算不准")
    return None


# ---------------------------------------------------------------- 职业与筛人

#: 主职业的中文名。**这八个是游戏的职业枚举，不会漂**，所以直接写死——
#: 选人屏不该为了八个常量去开一次数据库。名册里的 `profession` 是英文枚举
#: （森空岛与 OperBox 两条来源都如此），中文名在 akdb 的 `operator.profession_cn`，
#: 两者可以互相核对。
PROFESSION_CN = {
    "PIONEER": "先锋",
    "WARRIOR": "近卫",
    "TANK": "重装",
    "SNIPER": "狙击",
    "CASTER": "术师",
    "MEDIC": "医疗",
    "SUPPORT": "辅助",
    "SPECIAL": "特种",
    # 下面两个不在八大职业里，但名册里可能出现（装置/召唤物混进来时）
    "TOKEN": "召唤物",
    "TRAP": "装置",
}

#: 界面上职业的排列顺序（游戏里的先后）
PROFESSION_ORDER = ("PIONEER", "WARRIOR", "TANK", "SNIPER", "CASTER", "MEDIC",
                    "SUPPORT", "SPECIAL", "TOKEN", "TRAP")

#: 选人屏的练度门槛。博士定的**三档**（2026-09-17）：
#: 不限 / 大于等于精英二 60 / 精英二 90。做成三个选项而不是两个独立的
#: 「精英化」「等级」下拉框——独立的两个会让人去凑没有意义的组合
#: （「精英 0 且 90 级」这种筛不出东西的条件）。
TRAINED_FILTERS = (
    ("不限", 0, 1),
    ("≥ 精英二 60 级", 2, 60),
    ("精英二 90 级", 2, 90),
)


def profession_cn(op) -> str:
    return PROFESSION_CN.get(getattr(op, "profession", "") or "",
                             getattr(op, "profession", "") or "未知")


def group_label(op, mode: str = "prof") -> str:
    """一行分组表头。

    `mode="prof"` → 「近卫」；`mode="sub"` → 「近卫·术战者」。
    子职业缺失时退回主职业名，不留一个孤零零的分隔点。
    """
    main = profession_cn(op)
    if mode != "sub":
        return main
    sub = (getattr(op, "sub_profession", "") or "").strip()
    return f"{main}·{sub}" if sub else main


def meets_trained(op, elite_min: int, level_min: int) -> bool:
    """练度门槛判定。按 `(精英段, 段内等级)` 元组比——

    等级是**阶段内等级**（精英二 60 级就是 `level=60`），所以元组比较正好
    就是「至少精英二且在精英二里至少 60 级」。
    """
    return (op.elite, op.level) >= (elite_min, level_min)


# ---------------------------------------------------------------- 关卡

def operator_db_status() -> dict:
    """干员库（`akdb.sqlite`）在不在、有多少名干员。

    主界面要在账号那一栏写一句「干员库是否已获取」（博士 2026-09-18），
    而**开机那一屏不能被它拖住**：只查一次 `COUNT`、只读打开、任何异常都
    如实装进返回值，绝不往外抛——那一栏宁可写「文件在，但读不出来」，
    也不要让整屏因为一个库文件坏掉而空白。

    返回 `{"path", "exists", "operators", "error"}`；`operators` 为 `None`
    表示没读到（库不在，或读失败，看 `error`）。
    """
    import sqlite3

    from ..db import DEFAULT_DB_PATH

    out = {"path": str(DEFAULT_DB_PATH), "exists": False,
           "operators": None, "error": ""}
    try:
        out["exists"] = Path(DEFAULT_DB_PATH).exists()
        if not out["exists"]:
            return out
        # 只读打开：这一屏绝不改库（`connect()` 会建表，不该在显示时发生）
        conn = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True)
        try:
            out["operators"] = conn.execute(
                "SELECT COUNT(*) FROM operator").fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:                                  # noqa: BLE001
        out["error"] = f"{exc.__class__.__name__}: {exc}"
    return out


def _ro_stage_conn():
    """打开的只读连接；库不存在或没有 stage 表时返回 None。"""
    from ..db import DEFAULT_DB_PATH, connect
    if not Path(DEFAULT_DB_PATH).exists():
        return None
    return connect()


def stage_rows(keyword: str = "", limit: int = 0, zone_id: str = "",
               env: str = "", difficulty: str = "") -> list[dict]:
    """从 akdb 的 `stage` 表取关卡。表空就返回空列表，由上层给提示。

    `zone_id` 是**精确**匹配（按分部下钻时必须精确：`main_1` 用子串会把
    `main_10` 一起捞出来）；`env` 对应 `diff_group`，`difficulty` 是难度档。
    """
    from ..db.stages import list_stages
    conn = _ro_stage_conn()
    if conn is None:
        return []
    try:
        return list_stages(conn, keyword=keyword, limit=limit,
                           zone_id=zone_id, env=env, difficulty=difficulty)
    finally:
        conn.close()


def chapter_rows() -> list[dict]:
    """选关界面第一层：章/活动。

    比 `zone` 高一级——103 个活动含多个 zone（「月行水上」= 通学路 + 殡仪堂），
    平铺会让用户自己认前缀。返回 `[{key, title, subtitle, levels, parts}]`。
    """
    from ..db.stages import list_chapters
    conn = _ro_stage_conn()
    if conn is None:
        return []
    try:
        return list_chapters(conn)
    finally:
        conn.close()


def zone_envs(zone_id: str) -> list[dict]:
    """某个 zone 里**实际存在**的环境分层，`[{"env","label","levels"}]`。

    按 `ENV_ORDER` 排（剧情体验 → 标准实战 → 磨难险地 → 通用）。
    第 9 章实测 EASY 18 / NORMAL 24 / ALL 4，第 10-14 章三档齐全，
    而第 0-8 章与第 15-17 章全是 NONE —— 后者这一层菜单就不该出现。

    **条数含四星限定版**，与下一层列表的行数一致（不含的话菜单报 24、
    列表给 41 行，看着像筛错了）。
    """
    from ..db.stages import ENV_LABELS, ENV_ORDER, load_stages
    conn = _ro_stage_conn()
    if conn is None:
        return []
    try:
        counts: dict[str, int] = {}
        for _level_id, v in load_stages(conn).items():
            if (v.get("zone_id") or "") != zone_id:
                continue
            g = (v.get("diff_group") or "").upper()
            if not g or g == "NONE":
                continue
            counts[g] = counts.get(g, 0) + 1
    finally:
        conn.close()
    order = {e: i for i, e in enumerate(ENV_ORDER)}

    def key(e: str) -> tuple:
        return (order.get(e, 99), e)

    return [{"env": e, "label": ENV_LABELS.get(e, e), "levels": n}
            for e, n in sorted(counts.items(), key=lambda kv: key(kv[0]))]


def zone_diffs(zone_id: str, env: str = "") -> list[dict]:
    """某个 (zone, 环境) 范围里**实际存在**的难度档，`[{"diff","label","levels"}]`。

    按 `DIFFICULTY_ORDER` 排。实测同一关可能有普通版与 `#f#` 四星限定版并存，
    第 15-17 章则是 NORMAL 与 SIX_STAR 各占一半——所以难度是一个**筛选器**，
    不是一个常量。
    """
    from ..db.stages import (DIFFICULTY_LABELS, DIFFICULTY_ORDER,
                             load_stages)
    conn = _ro_stage_conn()
    if conn is None:
        return []
    try:
        counts: dict[str, int] = {}
        for _level_id, v in load_stages(conn).items():
            if (v.get("zone_id") or "") != zone_id:
                continue
            if env and (v.get("diff_group") or "").upper() != env.upper():
                continue
            d = (v.get("difficulty") or "NORMAL").upper()
            counts[d] = counts.get(d, 0) + 1
    finally:
        conn.close()
    order = {d: i for i, d in enumerate(DIFFICULTY_ORDER)}

    def key(e: str) -> tuple:
        return (order.get(e, 99), e)

    return [{"diff": d, "label": DIFFICULTY_LABELS.get(d, d), "levels": n}
            for d, n in sorted(counts.items(), key=lambda kv: key(kv[0]))]


# ---------------------------------------------------------------- 路径补全

def complete_dir(text: str, base: Path | None = None) -> tuple[str, list[str]]:
    """把一段路径补全到"能补的最远处"，返回 `(新文本, 候选列表)`。

    给 Tab 键用。三种情形：

    - **空输入** → 补成默认目录并带上分隔符，省得从头敲；
    - **唯一匹配** → 直接补全；补的是目录就带分隔符，好接着往下打；
    - **多个匹配** → 补到**最长公共前缀**，候选交回给界面显示，不替用户猜。

    全用字符串处理（不 `Path.resolve()`）：用户可能正在敲一个还不存在的目录，
    而 `resolve` 会把不存在的部分原样留下、还会把相对路径锚到 cwd，反而把
    正在编辑的文本改形。只用 `Path.iterdir()` 读一层目录。
    """
    raw = (text or "").strip()
    # 全程只用**一种**分隔符：用户在打 `/` 就继续用 `/`，否则用系统的。
    # `/` 与 `\` 在 Windows 上都能用，但混起来（`D:/home/DSH\ak-tactic\`）
    # 看着像出错了，而补全的全部价值就是让人不用回头检查。
    sep = "/" if ("/" in raw and "\\" not in raw) else os.sep
    if not raw:
        return str(Path(base) if base is not None else guides_dir()) + sep, []

    if raw.endswith(("/", "\\")):
        head, tail = raw, ""
    else:
        head, tail = os.path.split(raw)
        # `os.path.split` **会把分隔符吃掉**：`D:/home/DSH/ak-tac` → 头是
        # `D:/home/DSH`、尾是 `ak-tac`。不补回来的话拼出的路径少一个斜杠
        # （`D:/home/DSH` + `ak-tactic\` = `D:/home/DSHak-tactic\`），
        # 而那个字符串看上去还挺像回事，只有真去用它才会发现。
        if head and not head.endswith(("/", "\\")):
            head += sep
    probe = Path(os.path.expanduser(head or "."))
    if not probe.is_dir():
        return raw, []
    try:
        names = sorted(p.name + (sep if p.is_dir() else "")
                       for p in probe.iterdir()
                       if p.name.lower().startswith(tail.lower()))
    except OSError:
        return raw, []
    if not names:
        return raw, []
    if len(names) == 1:
        return head + names[0], []
    # **大小写不敏感地**取公共前缀。`os.path.commonprefix` 是区分大小写的，
    # 而 Windows 路径不区分——`Ak-tactic\` 与 `ak-others\` 都命中了 "a"，
    # 公共前缀却算成空串，补完等于没补（用户看到的是一点变化都没有）。
    low = os.path.commonprefix([n.lower() for n in names])
    return head + names[0][:len(low)], names
