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
    "BLOCKER_KEY", "PUMP_KEY", "PILE_KEY", "DEVICE_NAMES", "BUILD_SECONDS",
    "DIRECTIONS", "front_of", "behind_of", "Device", "parse_devices", "devices_of",
]

#: 阻流阀：3 秒后建成 → 自身地块不再算田地。
BLOCKER_KEY = "trap_139_dhtl"
#: 泵站：在身后格与前方格之间搬病害。
PUMP_KEY = "trap_140_dhsb"
#: 天桩：分支装置，正文不在库内，本模块不实现其效果。
PILE_KEY = "trap_146_dhdcr"

DEVICE_NAMES = {
    BLOCKER_KEY: "阻流阀",
    PUMP_KEY: "泵站",
    PILE_KEY: "天桩",
}

#: 阻流阀的建成耗时，取自它自己的技能 `duration`（阻流：`3.0` 秒）。
BUILD_SECONDS = 3.0

#: 屏幕方向 → (dx, dy)，MAA 口径（原点左上、y 向下）。
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

    @property
    def front(self) -> tuple[int, int] | None:
        return front_of(self.cell, self.direction)

    @property
    def behind(self) -> tuple[int, int] | None:
        return behind_of(self.cell, self.direction)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "alias": self.alias,
                "cell": list(self.cell), "direction": self.direction,
                "front": list(self.front) if self.front else None,
                "behind": list(self.behind) if self.behind else None}


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
        ))
    return out


def devices_of(stage: Any, key: str | None = None,
               names: dict[str, str] | None = None) -> list[Device]:
    """取装置，可按 `characterKey` 过滤。"""
    ds = parse_devices(stage, names)
    return [d for d in ds if d.key == key] if key else ds
