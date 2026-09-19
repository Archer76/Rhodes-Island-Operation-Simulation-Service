#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Go 痕迹（stderr）的**唯一**解析入口。

## 为什么要有这个模块

痕迹的列会随排查需要**不断增删**——本会话给 `POS` 那一行加过
`blocked/pause/sluggish/snow/latch/recheck/fgt0/p`，又删回去过几列。
每次增删，所有**逐列写死的正则**同时失配，而失配的表现是
「0 帧」「共 0 条分歧」——**与"真的没有记录""真的对齐了"长得一模一样**。

本会话为此吃了两次假信号：

1. `probe_firstdiff` 报「共 0 条坐标分开」，看着像已经对齐，实际是
   `snow=`/`latch=` 两列让正则失配、Go 侧一条记录都没解析出来；
2. `probe_go_pos --idx 8` 报「0 帧」，据此以为那只敌人在 63 秒就不在场上了，
   实际它好好地站在 `[10,4]` 上——只是解析器还在等已删掉的 `recheck` 列。

## 用法

每条痕迹行都是 `标签 key=value key=value …`，所以一律**通用拆键**：

    tag, d = parse_trace(line)          # 标签 + {键: 值}，不是痕迹行给 None
    if tag == "POS": ...

再配 `require(d, POS_NEEDED, line)`：**缺列当场报错**，绝不退化成"没有输出"。
"""
from __future__ import annotations

import re

#: 通用拆键：值不许含空白（痕迹里也没有含空白的值）。
#:
#: ⚠ **值允许为空**（`(\S*)` 不是 `(\S+)`）。Go 的痕迹里有好几列是 `|` 连接的
#: **列表**，空列表就渲染成 `block= pick=` 这样——值后面什么都没有，是**格式
#: 允许的空值**，不是"这一列没打"。早先写成 `(\S+)` 时，`OPATK` 一行会被拆掉
#: 四列（`block`/`pick`/`inrange`/`heals`），`require` 当场报"缺列"。
#: 那次报错是**对的**（它逼我来看这一行，而不是静默给出 0 个目标——
#: 而"0 个目标"恰恰是这次要查的那个数）；**错的是正则**。
#: 两件事要同时成立：空值要收下，真缺列仍要报。
_KV_RE = re.compile(r"(\w+)=(\S*)")

#: 坐标比对的最低必需列。少任何一列都必须当场报错。
POS_NEEDED = ("t", "idx", "name", "x", "y")


def parse_trace(line: str) -> tuple[str, dict[str, str]] | None:
    """把一行痕迹拆成 `(标签, {键: 值})`；不是痕迹行就给 `None`。"""
    line = line.strip()
    if not line or "=" not in line:
        return None
    tag, _, rest = line.partition(" ")
    if not rest:
        return None
    return tag, dict(_KV_RE.findall(rest))


def require(d: dict[str, str], keys, line: str) -> None:
    """缺列就报错——**不要**让它静默退化成空结果。"""
    missing = [k for k in keys if k not in d]
    if missing:
        raise RuntimeError(
            f"痕迹缺列 {missing}：解析器与该轮的痕迹格式对不上。"
            "这不是'没有记录'，别再当成'没有分歧'。原始行：" + line.strip())


def rows(stderr: str, tag: str, needed=()) -> list[dict[str, str]]:
    """把某个标签的所有痕迹行拆成字典列表（缺 `needed` 里的列会报错）。

    **所有探针都该走这里**，不要再为每种痕迹手写正则——见模块头的两次假信号。
    """
    out = []
    for line in (stderr or "").splitlines():
        parsed = parse_trace(line)
        if parsed is None:
            continue
        t, d = parsed
        if t != tag:
            continue
        if needed:
            require(d, needed, line)
        out.append(d)
    return out


def pos_rows(stderr: str, tag: str = "POS") -> list[dict[str, str]]:
    """把所有 `POS` 行拆成字典列表（缺必需列会报错）。"""
    return rows(stderr, tag, POS_NEEDED)


def fnum(d: dict[str, str], key: str, default: float = 0.0) -> float:
    """取一个浮点列；缺列给默认值（用于"可有可无"的列）。"""
    v = d.get(key)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def flag(d: dict[str, str], key: str, default: bool = False) -> bool:
    v = d.get(key)
    if v is None:
        return default
    return v == "true"
