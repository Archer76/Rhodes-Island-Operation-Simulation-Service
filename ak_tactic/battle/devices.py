"""怀黍离的关卡装置（摆位与效果）。

装置与干员不同：**它们由关卡摆好**，数据在关卡 JSON 的
`predefines.tokenInsts` 里，每条形如::

    {"position": {"row": 1, "col": 1}, "direction": "LEFT",
     "alias": "trap_139_dhtl#1",
     "inst": {"characterKey": "trap_139_dhtl", "level": 1, ...}}

⚠ 三个坑：

1. **`prefabKey` 这个字段不存在。** 装置的身份在 `inst.characterKey`
   （`prefabKey` 只在敌人与召唤物那边用），照着它取会得到一列 `?`。
2. **`position.row` 是游戏内部口径（自下而上）**，与 `routes[].row` 同规矩，
   要用 `y = 高 - 1 - row` 翻一次；`col` 直接就是 `x`。
3. **`direction` 一律是屏幕方向**，与内部 y 轴朝哪边无关，故
   `UP` 就是「屏幕上方」＝ MAA 坐标的 `y - 1`。

act31side 全 24 关只用了三个装置（实测）：

| characterKey | 名字 | 出现在 | 效果正文 |
|---|---|---|---|
| `trap_139_dhtl` | 阻流阀 | 23 关 ×128 | 「3秒后建成，阻隔水流」 |
| `trap_146_dhdcr` | 天桩 | 10 关 ×36 | 技能「生成」**正文为空**，黑板只有 `branch_id` |
| `trap_140_dhsb` | 泵站 | 8 关 ×14 | 「将身后一格的浅水泵至前方…」 |

天桩的正文不在库内（它是**分支装置**，`branch_id` 指向变体，正文写在
prts.wiki 的「天桩-甲」「天桩-乙」两个页面上）。本模块**不为它编效果**——
按本项目惯例，编不出来是漏，编错了是错。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

__all__ = [
    "BLOCKER_KEY", "PUMP_KEY", "PILE_KEY", "DEVICE_NAMES", "DEVICE_HP",
    "DEVICE_COST", "BUILD_SECONDS", "BLOCKER_BUILD_FRACTION", "AURA_HIT_RADIUS",
    "DIRECTIONS", "front_of", "behind_of", "Device", "DeviceUnit",
    "DeviceDeployment", "parse_devices", "devices_of", "make_devices",
    "device_hp", "device_cost", "branch_id_of", "initial_device_tokens",
]

#: 阻流阀：3 秒后建成 → 自身地块不再算田地。
BLOCKER_KEY = "trap_139_dhtl"
#: 泵站：在身后格与前方格之间搬病害。
PUMP_KEY = "trap_140_dhsb"
#: 天桩：登场时在自身位置召唤一名「天桩-甲」；所在地块的甲退场时自身死亡。
PILE_KEY = "trap_146_dhdcr"

DEVICE_NAMES = {
    BLOCKER_KEY: "阻流阀",
    PUMP_KEY: "泵站",
    PILE_KEY: "天桩",
}

#: 装置的阶段生命值，取自 prts.wiki 各装置页的「装置信息」（阶段 1 与阶段 2 同值）。
#: 三个都是 100——这一点很要紧：AuraHit 打的是**目标最大生命值**的 50%/70%
#: （田鼷力士/飞贼 0.5、猛士/大盗 0.7），也就是 50/70 点，所以田鼷**两次经过**
#: 就能拆掉一个阻流阀（50+50=100）。这不是巧合，是设计。
DEVICE_HP = {
    BLOCKER_KEY: 100.0,      # 阻流阀
    PUMP_KEY: 100.0,         # 泵站
    PILE_KEY: 100.0,         # 天桩
}

#: 装置的默认生命值（`DEVICE_HP` 里没有的 key 用这个）。
DEFAULT_DEVICE_HP = 100.0

#: 装置的**部署费用**，取自角色表 `phases[0].attributesKeyFrames[0].data.cost`
#: （阻流阀 5、泵站 0、天桩 0）。玩家手动部署才用得上——关卡预先摆好的那些
#: 不花费用。自检 `tools/check_environment.py` 里对着角色表逐条核过。
DEVICE_COST = {
    BLOCKER_KEY: 5,
    PUMP_KEY: 0,
    PILE_KEY: 0,
}

#: `DEVICE_COST` 里没有的 key 用这个（0 = 不花费用，宁可不收也不乱收）。
DEFAULT_DEVICE_COST = 0


def device_cost(key: str) -> int:
    """这个装置的部署费用。表里没有的给 `DEFAULT_DEVICE_COST`（不猜）。"""
    return int(DEVICE_COST.get(key, DEFAULT_DEVICE_COST))


def make_deployed_device(key: str, cell: tuple[int, int],
                         direction: str = "RIGHT",
                         name: str | None = None) -> "Device":
    """造一个**玩家部署用**的 `Device`：没有关卡 predefine，只有 key 与格子。

    关卡预置的装置都从 `tokenInsts` 解析（那里有 alias 与 `branch_id`），
    而玩家手动放下去的那个在关卡 JSON 里根本不存在——它只有"放到哪一格、
    朝哪个方向"。`branch_id` 留空是**有意的**：空值在天桩那条路上会走
    `branch_for("")` 的退路而不是随便认一条支线（见 `Stage.branch_for`）。
    """
    return Device(key=key, name=name or _name_of(key), alias="",
                  cell=(int(cell[0]), int(cell[1])),
                  direction=str(direction or "").upper(), branch_id="")

#: **玩家手动部署**的阻流阀：建成前生命值只有最大值的 3.4%，3 秒内涨满，期间无敌
#: （prts.wiki「阻流阀」技能 1 备注：『部署后自身生命值降至最大生命值的3.4%，
#: 并在3秒内逐渐提升至最大值，期间持有无敌』）。
BLOCKER_BUILD_FRACTION = 0.034

#: 阻流阀的建成耗时，取自它自己的技能 `duration`（阻流：`3.0` 秒）。
#:
#: ⚠ **只对玩家手动部署的那一种成立**。关卡开始时已自动部署的阻流阀走的是
#: 技能 2（同名「阻流」，`初始=0/消耗=0`、**没有持续时间**），正文只写「阻隔水流」，
#: 也就是说它们**开场即在位**。早先这里把 3 秒套在全部阻流阀头上，等于让每一张
#: 有田地的图在前 3 秒少算了「阻流阀把自身地块从田里摘掉」这件事。
BUILD_SECONDS = 3.0

#: 田鼷「进入阻流阀**半径 0.5**范围内时立刻对其造成…真实伤害」里的那个半径。
#: 0.5 格意味着**只有同格**才够得着（相邻格格心距 1.0）。
AURA_HIT_RADIUS = 0.5

#: 屏幕方向 → (dx, dy)，MAA 口径（原点左上、y 向下）。
#:
#: ⚠⚠ **本表是 UPPER（`"LEFT"` / `"RIGHT"` / `"UP"` / `"DOWN"`）**，
#: 与 `ak_tactic/frontend/geometry.py` 那张 **Title Case**（`"Right"` / `"Left"` / …）
#: **是两张不同的表**——装置的朝向是 UPPER，干员的 `direction` 是 Title Case。
#: **别把两张并成一张**：并了不报错，只会让查不到的那一半静默落回
#: `DIRECTIONS.get(..., (1, 0))` 的默认值，即**方向反了**。
#: （本轮曾在 `unit.py` 上踩过这个坑，见 `AK-TACTIC-进度.md` §3.34。）
DIRECTIONS = {
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
    "UP": (0, -1),
    "DOWN": (0, 1),
}


def front_of(cell: tuple[int, int], direction: str) -> tuple[int, int] | None:
    """朝向前方那一格。方向不认识时返回 None（不猜）。"""
    d = DIRECTIONS.get((direction or "").upper())
    return None if d is None else (cell[0] + d[0], cell[1] + d[1])


def behind_of(cell: tuple[int, int], direction: str) -> tuple[int, int] | None:
    """背对的那一格（「身后一格」）。"""
    d = DIRECTIONS.get((direction or "").upper())
    return None if d is None else (cell[0] - d[0], cell[1] - d[1])


@dataclass(frozen=True)
class Device:
    """关卡摆好的一个装置实例。"""

    key: str
    name: str
    alias: str
    cell: tuple[int, int]
    direction: str
    #: 装置 predefine 的 `overrideSkillBlackboard` 里 `branch_id` 那一项。
    #: 天桩的技能「生成」只有一个键就是它：它指向关卡 ``branches`` 里的一条
    #: 支线，支线里写着**召唤谁、走哪条 ``extraRoutes``**
    #: （见 `BattleSimulator._pile_spec`）。关卡没写覆盖时是空串，
    #: 由 `Stage.branch_for` 退回技能默认黑板。
    branch_id: str = ""

    @property
    def front(self) -> tuple[int, int] | None:
        return front_of(self.cell, self.direction)

    @property
    def behind(self) -> tuple[int, int] | None:
        return behind_of(self.cell, self.direction)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "alias": self.alias,
                "cell": list(self.cell), "direction": self.direction,
                "branch_id": self.branch_id,
                "front": list(self.front) if self.front else None,
                "behind": list(self.behind) if self.behind else None}


def branch_id_of(inst: dict) -> str:
    """从装置 predefine 里取 `branch_id`（`overrideSkillBlackboard` 的一项）。"""
    for kb in (inst.get("overrideSkillBlackboard") or []):
        if kb.get("key") == "branch_id":
            return str(kb.get("valueStr") or "")
    return ""


def _name_of(key: str) -> str:
    """装置的中文名。先查本模块的表，再退回干员库（装置也在库里）。"""
    if key in DEVICE_NAMES:
        return DEVICE_NAMES[key]
    return key


def parse_devices(stage: Any,
                  names: dict[str, str] | None = None) -> list["Device"]:
    """从关卡里取出全部装置。

    `stage.raw["predefines"]["tokenInsts"]` 是唯一来源；取不到就是空表，
    **不要**退而求其次去 `characterInsts`——那里是关卡预置的**干员**，
    混进来会凭空多出几个"装置"。
    """
    raw = getattr(stage, "raw", None) or {}
    pre = raw.get("predefines") or {}
    insts = pre.get("tokenInsts") or []
    height = stage.map.height
    table = dict(DEVICE_NAMES)
    table.update(names or {})

    out: list[Device] = []
    for it in insts:
        key = (it.get("inst") or {}).get("characterKey") or ""
        if not key:
            continue
        pos = it.get("position") or {}
        row, col = pos.get("row"), pos.get("col")
        if row is None or col is None:
            continue
        out.append(Device(
            key=key,
            name=table.get(key, _name_of(key)),
            alias=str(it.get("alias") or ""),
            cell=(int(col), height - 1 - int(row)),   # ⚠ row 自下而上，翻一次
            direction=str(it.get("direction") or "").upper(),
            branch_id=branch_id_of(it),
        ))
    return out


def devices_of(stage: Any, key: str | None = None,
               names: dict[str, str] | None = None) -> list[Device]:
    """取装置，可按 `characterKey` 过滤。"""
    ds = parse_devices(stage, names)
    return [d for d in ds if d.key == key] if key else ds


@dataclass(frozen=True)
class DeviceDeployment:
    """作业里的一条**装置部署**计划：什么时刻、把哪个装置放到哪一格。

    为什么要有它：`DeathPassive.`（田鼷飞贼 / 田鼷大盗被击倒时予我方可部署装置）
    给出的阻流阀，**放哪一格是战术决定**，数据里没有。项目约定是
    「不由模拟器猜」：计划里写了就放，没写就只记账（见
    `docs/verdicts-pending.md` E7）。
    """

    time: float
    device_key: str
    position: tuple[int, int]
    direction: str = "RIGHT"
    note: str = ""

    def to_dict(self) -> dict:
        return {"time": self.time, "device_key": self.device_key,
                "position": list(self.position), "direction": self.direction,
                "note": self.note}


def initial_device_tokens(stage: Any) -> dict[str, int]:
    """关卡**开局就给的**装置额度：`predefines.tokenCards[].initialCnt`。

    这是"玩家手里有几张这个装置的牌"。怀黍离里阻流阀与泵站都是按张给的
    （03 关 2 张阻流阀、ex05 关 10 张……），而 `DeathPassive.` 击杀掉落是
    在这个额度上**再加**。两份合起来才是一局里能放几个。
    """
    raw = getattr(stage, "raw", None) or {}
    out: dict[str, int] = {}
    for sec in ("predefines", "hardPredefines"):
        blk = raw.get(sec) or {}
        if not isinstance(blk, dict):
            continue
        for c in (blk.get("tokenCards") or []):
            key = (c.get("inst") or {}).get("characterKey") or ""
            if not key:
                continue
            out[key] = out.get(key, 0) + int(c.get("initialCnt") or 0)
    return out


# ================================================================ 运行态

def device_hp(key: str) -> float:
    """这个装置的最大生命值。表里没有的给 `DEFAULT_DEVICE_HP`（不猜 0）。"""
    return DEVICE_HP.get(key, DEFAULT_DEVICE_HP)


@dataclass
class DeviceUnit:
    """一个装置的**运行态**：静态描述 + 生命值 + 建成进度 + 存活。

    `Device` 是关卡 JSON 里的静态描述（一辈子不变），`DeviceUnit` 是会变的那个。
    两者的字段名（`key` / `name` / `cell` / `direction` / `front` / `behind`）
    **故意保持一致**：`pump_once()` 这类只读装置表的函数两种都收。

    ⚠ 三条容易想当然的地方：

    * **预置装置开场即在位。** 关卡 JSON 里 `predefines.tokenInsts` 摆的那些走的是
      装置自己的技能 2（无持续时间），不是「3 秒后建成」那一支。真正要等 3 秒的
      是玩家手动部署的阻流阀（技能 1），而它的生命值在建成期间只有 3.4% 且无敌。
    * **无敌只在建成期间**（`building_invincible`），建成后照常挨打。
    * **天桩的「生死」挂在别人身上**：所在地块的「天桩-甲」一退场，天桩就死
      （`summoned` 里记着它召唤出来的那些甲）。所以它有 `summoned` 这个字段，
      别的装置一直是空表。
    """

    device: Device
    max_hp: float = DEFAULT_DEVICE_HP
    #: 当前生命值。<0 表示"按满血补齐"（构造时补，省得每个调用点各写一遍）。
    hp: float = -1.0
    alive: bool = True
    #: 建成倒计时（秒）。预置装置为 0 = 开场即在位。
    build_left: float = 0.0
    #: 建成期间是否无敌（手动部署的阻流阀：3 秒内 3.4%→100%，期间无敌）。
    building_invincible: bool = True
    #: 天桩召唤出来的「天桩-甲」实例（甲退场 → 本装置死亡）。
    summoned: list[Any] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.hp < 0.0:
            self.hp = self.max_hp
        self.hp = min(self.hp, self.max_hp)

    # ---- 与 `Device` 同名的一层（让只读装置表的代码两种都收）
    @property
    def key(self) -> str:
        return self.device.key

    @property
    def name(self) -> str:
        return self.device.name

    @property
    def alias(self) -> str:
        return self.device.alias

    @property
    def cell(self) -> tuple[int, int]:
        return self.device.cell

    @property
    def direction(self) -> str:
        return self.device.direction

    @property
    def front(self) -> tuple[int, int] | None:
        return self.device.front

    @property
    def behind(self) -> tuple[int, int] | None:
        return self.device.behind

    @property
    def branch_id(self) -> str:
        """透出 `Device.branch_id`——天桩靠它找到自己那条支线。"""
        return self.device.branch_id

    # ---- 运行态
    @property
    def built(self) -> bool:
        return self.build_left <= 0.0

    @property
    def hp_ratio(self) -> float:
        return self.hp / self.max_hp if self.max_hp > 0 else 0.0

    def tick_build(self, dt: float) -> None:
        """推进建成进度。建成期间生命值线性涨满（3.4% → 100%）。"""
        if self.build_left <= 0.0:
            return
        self.build_left = max(0.0, self.build_left - dt)
        if self.build_left <= 0.0:
            self.hp = self.max_hp
        else:
            done = 1.0 - self.build_left / BUILD_SECONDS
            self.hp = self.max_hp * (BLOCKER_BUILD_FRACTION
                                     + (1.0 - BLOCKER_BUILD_FRACTION) * done)

    def take_damage(self, amount: float) -> float:
        """对装置造成伤害，返回**实际生效**的量。

        建成期间无敌：返回 0（不是"返回请求量但血没扣"，那样调用方会以为打中了）。
        被摧毁时 `alive` 置假，血量夹到 0。
        """
        if not self.alive or amount <= 0.0:
            return 0.0
        if self.build_left > 0.0 and self.building_invincible:
            return 0.0
        dealt = min(amount, self.hp)
        self.hp -= dealt
        if self.hp <= 0.0:
            self.hp = 0.0
            self.alive = False
        return dealt

    def to_dict(self) -> dict[str, Any]:
        out = self.device.to_dict()
        out.update({"max_hp": self.max_hp, "hp": self.hp, "alive": self.alive,
                    "built": self.built})
        return out


def make_devices(stage: Any, names: dict[str, str] | None = None,
                 *, build_seconds: float = 0.0) -> list["DeviceUnit"]:
    """把关卡预置的装置变成运行态。

    `build_seconds` 默认 **0**：预置装置开场即在位（见 `DeviceUnit` 的注释）。
    传正值只对"这一关的装置是玩家现场部署的"这种情形才有意义。
    """
    out = []
    for d in parse_devices(stage, names):
        out.append(DeviceUnit(device=d, max_hp=device_hp(d.key),
                              build_left=build_seconds))
    return out
